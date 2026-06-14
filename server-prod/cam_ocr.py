"""Water Meter OCR — extracts meter readings from ESP32-CAM images.

Primary: Azure Computer Vision Read API (if configured).
Fallback: Tesseract OCR (local).

Improvements:
- Always flip 180° (camera is mounted upside-down)
- Aggressive image preprocessing: contrast, sharpen, threshold
- Crop to center LCD region to reduce noise from meter housing
- Skip duplicate Azure calls since orientation is known
- Smarter number extraction (prefer 5+ digit sequences for meter)
- Running median filter to reject outlier readings
"""

import io
import os
import re
import logging
import statistics
from datetime import datetime
from threading import Lock
from collections import deque

log = logging.getLogger("cam_ocr")

# --- Physical constants for a Sensus iPERL register reading in cubic feet ---
# The LCD shows 9 digits with the decimal 3 from the right, so each displayed
# count = 0.001 ft³. 1 ft³ = 7.48052 US gallons.
COUNTS_PER_CF = 1000.0
GAL_PER_CF = 7.48052
COUNTS_PER_GAL = COUNTS_PER_CF / GAL_PER_CF      # ~133.69 counts per gallon
FRAME_SECS = 5.0                                  # nominal capture cadence

# Monotonic id assigned to every readings-table row so the UI can deep-link to
# a single record (and the worker can stash that frame's JPEG under the same
# id). epoch-ms prefix keeps ids unique across restarts and naturally sortable.
_ENTRY_SEQ = 0

# --- Seven-segment digit model (for context-aware per-digit recognition) ---
# Each digit lights a known set of the 7 LCD segments (a=top, b=top-right,
# c=bottom-right, d=bottom, e=bottom-left, f=top-left, g=middle). Two digits
# that differ by only one segment (e.g. 7 vs 1 = the top bar; 0 vs 8 = the
# middle bar) look almost identical when the image is blurry, which is exactly
# how this cheap OV2640 misreads. Scoring candidate digits by segment overlap
# lets us recover the true reading from a smudged frame instead of failing the
# whole string. Letters the OCR sometimes emits are folded to their nearest
# digit shape.
_SEG = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "fgbc",
    "5": "afgcd", "6": "afgcde", "7": "abc", "8": "abcdefg", "9": "abcfgd",
}
_SEG = {k: frozenset(v) for k, v in _SEG.items()}
# Common OCR letter->digit shape confusions on a 7-seg LCD.
_LETTER_TO_DIGIT = {
    "o": "0", "O": "0", "D": "0", "Q": "0", "i": "1", "I": "1", "l": "1",
    "L": "4", "z": "2", "Z": "2", "s": "5", "S": "5", "b": "6", "G": "6",
    "T": "7", "B": "8", "g": "9", "q": "9", "n": "0", "u": "0", "c": "0",
}


def _seg_sim(a, b):
    """Visual similarity of two digit characters, 0..1, by shared 7-seg shape.

    1.0 = identical; ~0.86 = differ by one segment (7 vs 1, 0 vs 8); lower as
    more segments differ. Non-digit chars fold to their nearest digit shape, or
    score a low constant if unknown (no information).
    """
    a = a if a in _SEG else _LETTER_TO_DIGIT.get(a, a)
    b = b if b in _SEG else _LETTER_TO_DIGIT.get(b, b)
    sa, sb = _SEG.get(a), _SEG.get(b)
    if sa is None or sb is None:
        return 0.3                       # unknown char: weak, non-zero prior
    if sa == sb:
        return 1.0
    return 1.0 - len(sa ^ sb) / 7.0      # Hamming over 7 segments


def _load_env_file(path="/etc/smart-garden/cam-env"):
    """Load KEY=VALUE pairs from a file into os.environ."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


_load_env_file()


class MeterReader:
    def __init__(self):
        self.azure_endpoint = os.environ.get("AZURE_VISION_ENDPOINT", "").rstrip("/")
        self.azure_key = os.environ.get("AZURE_VISION_KEY", "")
        self.readings = []
        self.lock = Lock()
        # Learned state
        self.orientation = "flipped"  # Locked: camera is upside-down
        self.last_good = None
        self.avg_rate = 0.0
        self._tesseract_ok = None
        self.backend = "azure" if self.azure_endpoint and self.azure_key else "tesseract"
        # Recent valid readings for median filter (reject outliers)
        self.recent_valid = deque(maxlen=20)
        # Recent full 9-digit reads, used to find the dominant cluster. The OCR
        # produces a mix of good reads (the real 09399xxxx value) and glare /
        # blur garbage (e.g. 866660130, 598166660) that lands hundreds of
        # millions away. Clustering lets us lock onto the real value and
        # reject the outliers instead of echoing whatever last arrived.
        self.recent_nine = deque(maxlen=15)
        # A water meter is a cumulative counter: it only ever counts UP, and
        # never by more than this much between consecutive 5s frames. Anything
        # outside [0, max_jump] from the locked value is an OCR misread.
        self.max_jump = int(os.environ.get("METER_MAX_JUMP", "50000"))
        # Trailing-digit OCR jitter can make a read dip slightly below the
        # locked value; absorb that (hold steady) rather than rejecting.
        self.jitter_tol = int(os.environ.get("METER_JITTER_TOL", "300"))
        # For flow-rate: capture time + value of the last reading whose value
        # actually CHANGED. When the value next changes, the rate is averaged
        # over the real elapsed time (which spans any held frames in between),
        # so a delta that accumulated while the OCR was stuck isn't mistaken
        # for a 5-second burst.
        self._last_change_ts = None
        self._last_change_val = None
        # Capture time of the immediately preceding frame, to show the gap
        # between consecutive captures (should be ~5s; surfaces cam stalls).
        self._prev_captured_ts = None
        # Capture time of the currently locked value, used by the physical
        # flow-rate ceiling: a longer blind gap allows a proportionally larger
        # (but still physically possible) increase.
        self._lock_ts = None
        # Absolute max flow the plumbing could ever produce, gal/min — even a
        # burst/cut pipe won't exceed this. Any read implying a faster rate is
        # a misread, not real water, and is rejected.
        self.max_gpm = float(os.environ.get("METER_MAX_GPM", "20"))
        # Minimum digit-fit score (0..1) to accept a context-scored reading.
        self.fit_min = float(os.environ.get("METER_FIT_MIN", "0.80"))
        # Last digit-fit score, surfaced in the row note for visibility.
        self._last_fit = None
        # The per-digit scorer only commits readings within this many counts of
        # the lock. Small enough that secondary-dial garbage (whose low digits
        # fall outside this window's range) can never form a FALSE-HIGH lock —
        # which would be catastrophic (the monotonic rule would then hold every
        # real read below it forever). Genuine advances larger than this (a long
        # blind gap with heavy flow) stay held until a clean read or re-anchor;
        # that's recoverable, a false-high lock is not. ~400 counts = 3 gal.
        self.score_window = int(os.environ.get("METER_SCORE_WINDOW", "250"))
        # The OCR's best-guess interpretation of the current frame (what the
        # digit model THINKS it read), set every frame independent of whether
        # the value was committed. Surfaced as its own column so you can see the
        # model's read vs the validated/held reading side by side.
        self._ocr_guess = None
        self._ocr_guess_fit = None
        # Corroboration buffer for ADVANCES. A single frame may never move the
        # lock — the real meter produces the SAME reading across several
        # consecutive 5s frames (it sits, or ticks slowly), while OCR garbage
        # is different every frame. So an advance is only committed once the
        # same value has been the scorer's pick in >=2 of the last few frames.
        # This is what stops a sporadic garbage match from ratcheting the lock
        # upward (the bug that drifted the lock 3000+ counts above truth).
        self._adv_buf = deque(maxlen=4)
        # The raw OCR's own low-digit read (last 5 digits it literally saw),
        # independent of the lock window — used to gate training-data banking so
        # we only bank frames the OCR independently corroborates (not circular).
        self._raw_low = None
        # After this many seconds with no clean read, the held value is STALE:
        # the meter has almost certainly moved up but we can't read it, so we
        # must present the held number honestly as a lower bound ("≥"), not as
        # a confirmed current reading.
        self.stale_secs = float(os.environ.get("METER_STALE_SECS", "20"))
        # Persisted lock state so a restart doesn't re-bootstrap from scratch
        # (which is when the OCR's systematic 60-prefix garbage once formed a
        # false cluster and latched onto 604001016).
        self._state_path = os.environ.get(
            "METER_STATE_PATH", "/tmp/meter_state.json")
        # KNOWN ANCHOR: the operator-confirmed true reading at a known time.
        # The meter is monotonic, so the true value can never be BELOW the
        # anchor, and can never be ABOVE it by more than max_gpm flow over the
        # elapsed time. This makes a garbage value like 604001016 impossible to
        # lock onto. Default: 094007078 (= 094007.078 ft³) at 2026-06-12 16:12,
        # confirmed by the operator from the physical meter.
        self.anchor_value = int(os.environ.get("METER_ANCHOR_VALUE", "94007078"))
        self.anchor_ts = self._parse_anchor_ts(
            os.environ.get("METER_ANCHOR_TS", "2026-06-12 16:12:00"))
        self._load_state()
        if self.last_good is None and self.anchor_value:
            # Seed the lock from the anchor so real reads are accepted
            # immediately and garbage can never form the initial lock.
            self.last_good = self.anchor_value
            self._lock_ts = self.anchor_ts
            self._last_change_ts = self.anchor_ts
            self._last_change_val = self.anchor_value
        log.info("MeterReader backend: %s, orientation: %s, max_gpm: %.1f, "
                 "anchor: %s@%s, locked: %s", self.backend, self.orientation,
                 self.max_gpm, self.anchor_value, self.anchor_ts, self.last_good)

    @staticmethod
    def _parse_anchor_ts(s):
        """Parse the anchor timestamp (ISO-ish local time) to epoch seconds."""
        if not s:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(s, fmt).timestamp()
            except ValueError:
                continue
        try:
            return float(s)  # already an epoch
        except ValueError:
            return None

    def _load_state(self):
        """Load the persisted lock (value + capture time) if newer than the
        anchor, so a restart resumes the real reading instead of re-bootstrapping."""
        try:
            import json
            with open(self._state_path) as f:
                st = json.load(f)
            val = int(st.get("last_good"))
            ts = float(st.get("lock_ts"))
            # Only trust persisted state at or above the anchor (monotonic).
            if val >= self.anchor_value:
                self.last_good = val
                self._lock_ts = ts
                self._last_change_ts = ts
                self._last_change_val = val
        except Exception:
            pass

    def reanchor(self, value, ts=None, source="oracle"):
        """Force the lock to a trusted external reading (e.g. the vision LLM).

        Accepts only a value at/above the known anchor floor (monotonic). Resets
        the lock, lock time, change baseline, and advance buffer so the fast
        pipeline resumes cleanly from the trusted value. Returns True if applied.
        """
        try:
            value = int(value)
        except (TypeError, ValueError):
            return False
        if value < self.anchor_value:
            return False
        now = ts if ts is not None else datetime.now().timestamp()
        self.last_good = value
        self._lock_ts = now
        self._last_change_ts = now
        self._last_change_val = value
        try:
            self._adv_buf.clear()
        except Exception:
            pass
        self.recent_nine.clear()
        self._save_state()
        log.info("reanchor -> %09d (source=%s)", value, source)
        return True

    def _save_state(self):
        """Persist the current lock so it survives a restart."""
        if self.last_good is None:
            return
        try:
            import json
            tmp = self._state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"last_good": int(self.last_good),
                           "lock_ts": self._lock_ts or 0}, f)
            os.replace(tmp, self._state_path)
        except Exception:
            pass

    @property
    def enabled(self):
        if self.backend == "azure":
            return True
        if self._tesseract_ok is None:
            try:
                import pytesseract
                pytesseract.get_tesseract_version()
                self._tesseract_ok = True
            except Exception:
                self._tesseract_ok = False
        return self._tesseract_ok

    # ------------------------------------------------------------------
    def process(self, img_bytes):
        """Full pipeline: preprocess -> OCR -> extract -> validate -> store."""
        if not self.enabled:
            return self._entry(error="OCR not configured")

        try:
            from PIL import Image
            pytesseract = None
            if self.backend == "tesseract":
                import pytesseract
        except ImportError as e:
            return self._entry(error=str(e))

        img = Image.open(io.BytesIO(img_bytes))

        # --- Step 1: Rotate 180 (camera is upside-down) ---
        img = img.rotate(180)

        # --- Step 2: OCR (single call to save API quota) ---
        # Azure does better with the color image; Tesseract needs preprocessing
        if self.backend == "azure":
            raw_text = self._ocr(img, pytesseract)
        else:
            processed = self._preprocess(img)
            raw_text = self._ocr(processed, pytesseract)

        # --- Step 3: Extract number ---
        reading, digits = self._extract(raw_text)
        raw_used = raw_text

        # --- Step 5: Validate against water-meter physics (monotonic up) ---
        reading, delta, confidence, note = self._validate(reading, digits, None)

        entry = self._entry(
            reading=reading,
            delta=delta,
            confidence=confidence,
            orientation=self.orientation,
            raw_n=(raw_used or raw_text or "")[:80],
            raw_f="",
            note=note,
        )
        with self.lock:
            self.readings.append(entry)
            if len(self.readings) > 2000:
                self.readings = self.readings[-2000:]
        return entry

    # ------------------------------------------------------------------
    def process_text(self, raw_text, captured_ts=None, queue_depth=None):
        """Validate + store a reading from OCR text done elsewhere (e.g. the
        tower OCR service). Reuses the same extract/validate logic as
        process(); the heavy OCR just happens off-box.

        ``captured_ts`` is the epoch time the frame was uploaded by the cam, so
        the table can show how far behind real-time a reading is. ``queue_depth``
        is how many frames were still buffered when this one was processed.

        When the value increases after a multi-frame blind gap (frames missed
        or too garbled to read), the increase is distributed evenly across the
        missed ~5s slots as ``derived`` rows so the consumption timeline stays
        continuous — like a human reasoning "the meter went up N over that
        minute, so it was ~N/12 each 5s". All raw frames remain in the table.
        """
        prev_change_ts = self._last_change_ts
        prev_change_val = self._last_change_val

        self._ocr_guess = None
        self._ocr_guess_fit = None
        reading, digits = self._extract(raw_text, captured_ts)
        ocr_guess = self._ocr_guess
        ocr_guess_fit = self._ocr_guess_fit
        reading, delta, confidence, note = self._validate(
            reading, digits, captured_ts)

        # Gap since the previous captured frame (should be ~5s).
        gap_s = None
        if captured_ts is not None and self._prev_captured_ts is not None:
            gap_s = captured_ts - self._prev_captured_ts
        if captured_ts is not None:
            self._prev_captured_ts = captured_ts

        backfill = []
        rate_gpm = None
        value_changed = (delta is not None and delta > 0 and reading is not None)

        if value_changed and captured_ts is not None:
            if prev_change_ts is not None and prev_change_val is not None:
                elapsed = captured_ts - prev_change_ts
                if elapsed > 0:
                    rate_gpm = self._gpm(delta, elapsed)
                    # Back-fill derived rows across any missed 5s slots.
                    slots = int(round(elapsed / FRAME_SECS))
                    if slots >= 2:
                        per = delta / slots
                        per_gpm = self._gpm(per, FRAME_SECS)
                        for i in range(1, slots):
                            backfill.append(self._entry(
                                reading=prev_change_val + per * i,
                                delta=per, confidence="derived",
                                note="derived (no capture)",
                                captured_ts=prev_change_ts + i * FRAME_SECS,
                                gap_s=FRAME_SECS, rate_gpm=per_gpm,
                                kind="derived"))
            self._last_change_ts = captured_ts
            self._last_change_val = reading
        elif (self._last_change_ts is None and captured_ts is not None
              and reading is not None and self.last_good is not None):
            # Seed the baseline once the value is first locked.
            self._last_change_ts = captured_ts
            self._last_change_val = reading

        # OCR's best guess for this frame. Prefer the digit-model's top pick
        # (set in _best_candidate, even if it was below the accept threshold);
        # fall back to the raw OCR digits' literal 9-digit interpretation so the
        # column is never blank when the OCR did read SOMETHING.
        if ocr_guess is None:
            raw_digits = re.sub(r"[^0-9]", "", raw_text or "")
            if raw_digits:
                ocr_guess = int(raw_digits[-9:])

        entry = self._entry(
            reading=reading, delta=delta, confidence=confidence,
            orientation=self.orientation, raw_n=(raw_text or "")[:80], raw_f="",
            note=note, captured_ts=captured_ts, queue_depth=queue_depth,
            gap_s=gap_s, rate_gpm=rate_gpm, kind="raw",
            ocr_guess=ocr_guess, ocr_guess_fit=ocr_guess_fit,
            raw_low=self._raw_low)
        with self.lock:
            self.readings.extend(backfill)
            self.readings.append(entry)
            if len(self.readings) > 4000:
                self.readings = self.readings[-4000:]
        return entry

    # ------------------------------------------------------------------
    def get_readings(self, limit=100):
        with self.lock:
            return list(reversed(self.readings[-limit:]))

    # ------------------------------------------------------------------
    def get_reading_by_id(self, rid):
        """Return the single readings-table row dict with this id, or None.

        Used by the per-reading detail page so a row can be inspected (full
        field dump + the exact frame the OCR saw) long after it scrolled off
        the live table.
        """
        with self.lock:
            for e in reversed(self.readings):
                if e.get("id") == rid:
                    return e
        return None

    # ------------------------------------------------------------------
    #  Preprocessing
    # ------------------------------------------------------------------
    @staticmethod
    def _preprocess(img):
        """Aggressively preprocess for LCD digit OCR."""
        from PIL import ImageEnhance, ImageOps, ImageFilter, Image as PILImage

        # Crop to center 60% -- the LCD display is in the middle,
        # edges are meter housing/debris
        w, h = img.size
        crop_x = int(w * 0.2)
        crop_y = int(h * 0.25)
        img = img.crop((crop_x, crop_y, w - crop_x, h - crop_y))

        # Grayscale
        gray = ImageOps.grayscale(img)

        # Auto-contrast (stretches histogram to full 0-255 range)
        gray = ImageOps.autocontrast(gray, cutoff=2)

        # Sharpen aggressively (helps with OV2640 fixed-focus blur)
        gray = gray.filter(ImageFilter.SHARPEN)
        gray = gray.filter(ImageFilter.SHARPEN)

        # Boost contrast
        enhancer = ImageEnhance.Contrast(gray)
        gray = enhancer.enhance(3.0)

        # Upscale 2x (helps OCR with small text)
        gray = gray.resize((gray.width * 2, gray.height * 2), PILImage.LANCZOS)

        return gray

    # ------------------------------------------------------------------
    #  OCR backends
    # ------------------------------------------------------------------
    def _ocr(self, img, pytesseract=None):
        if self.backend == "azure":
            return self._ocr_azure(img)
        return self._ocr_tesseract(img, pytesseract)

    def _ocr_azure(self, img):
        import requests as http_req
        try:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            img_bytes = buf.getvalue()

            url = f"{self.azure_endpoint}/computervision/imageanalysis:analyze"
            r = http_req.post(
                url,
                params={"features": "read", "api-version": "2024-02-01"},
                headers={
                    "Ocp-Apim-Subscription-Key": self.azure_key,
                    "Content-Type": "application/octet-stream",
                },
                data=img_bytes,
                timeout=10,
            )
            if r.status_code != 200:
                log.warning("Azure OCR %s: %s", r.status_code, r.text[:200])
                return ""
            lines = []
            for block in r.json().get("readResult", {}).get("blocks", []):
                for line in block.get("lines", []):
                    lines.append(line.get("text", ""))
            return " ".join(lines)
        except Exception as e:
            log.warning("Azure OCR error: %s", e)
            return ""

    def _ocr_tesseract(self, img, pytesseract):
        try:
            from PIL import ImageOps
            if img.mode != "L":
                gray = ImageOps.grayscale(img)
            else:
                gray = img
            text = pytesseract.image_to_string(
                gray,
                config="--psm 7 -c tessedit_char_whitelist=0123456789."
            )
            return text.strip()
        except Exception as e:
            log.warning("Tesseract error: %s", e)
            return ""

    # ------------------------------------------------------------------
    #  Number extraction
    # ------------------------------------------------------------------
    def _extract(self, text, captured_ts=None):
        """Pull the most likely meter reading from raw OCR text.

        This is a Sensus iPERL with a 9-digit LCD. Returns ``(value, width)``
        where ``width`` is the digit count actually matched (a leading-zero
        read like ``093998320`` reports width 9, not 8 — ``int()`` would drop
        the leading zero and make a good full read look partial).

        The OCR frequently emits a spurious secondary token (a sub-dial that
        reads as ``~60006``) next to the real reading, and sometimes drops the
        leading zero (8-digit). So this is **lock-aware**: once a reading is
        locked, it prefers the digit group within the physical flow ceiling
        that is the smallest forward step from the lock (ignores the junk token,
        tolerates a missing leading zero). Returns ``(None, 0)`` if nothing
        usable is found.
        """
        if not text:
            return None, 0
        nums = re.findall(r"\d+", text)
        if not nums:
            return None, 0

        # All plausible digit groups, plus the full concatenation if it's 9.
        cands = [(int(n), len(n)) for n in nums if len(n) >= 5]
        all_digits = re.sub(r"[^0-9]", "", text)
        if len(all_digits) == 9:
            cands.append((int(all_digits), 9))

        # The OCR's own LOW-digit read (last 5 digits it literally saw),
        # independent of the lock window. Used to gate banking so we only keep
        # training samples the OCR independently agrees with.
        self._raw_low = all_digits[-5:] if len(all_digits) >= 5 else None

        # Lock-aware path. Once we know roughly where the meter is, the set of
        # physically-possible next readings is tiny (the flow ceiling), so we
        # SCORE every candidate in that window digit-by-digit against what the
        # OCR saw (7-segment similarity) and take the best fit. This reasons
        # about each digit in the context of all the others and of the odometer
        # — a smudged 7-read-as-1 still scores high, and the monotonic window
        # rules out impossible values — instead of pass/fail on the raw string.
        # NOTE: this runs even when no single token is long enough (the digits
        # often fragment across tokens, e.g. "008 432"), so it must come BEFORE
        # any "not enough digits" bail-out.
        if self.last_good is not None:
            ceiling = self._max_forward_counts(captured_ts)

            best = self._best_candidate(all_digits, ceiling)
            if best is not None:
                return best, 9

            # Fallbacks (kept for cases the scorer abstains on):
            # 1) a whole token that's already a clean forward step,
            forward = [(v, w) for (v, w) in cands
                       if 0 <= v - self.last_good <= ceiling]
            if forward:
                forward.sort(key=lambda vw: (vw[0] - self.last_good, -(vw[1] == 9)))
                self._last_fit = None
                return forward[0]
            # 2) splice the locked high digits onto a reliable low tail.
            spliced = self._splice_low(nums, ceiling)
            if spliced is not None:
                self._last_fit = None
                return spliced, 9

            # Locked, but nothing reads as a plausible forward step. Report
            # no-read so the validator cleanly holds the locked value.
            self._last_fit = None
            return None, 0

        # No lock (bootstrap): prefer an exact 9-digit token, else the longest.
        if not cands:
            return None, 0
        nine = [(v, w) for (v, w) in cands if w == 9]
        if nine:
            return nine[0]
        cands.sort(key=lambda vw: -vw[1])
        return cands[0]

    def _best_candidate(self, ocr_digits, ceiling):
        """Context-aware per-digit reader. Enumerate every physically-possible
        reading in ``[last_good, last_good + ceiling]`` and score each one
        against the OCR digit string ``ocr_digits`` by per-position 7-segment
        similarity, weighting the reliable low (right-hand) digits more. Return
        the best-fitting value if its score clears ``fit_min``, else ``None``.

        The monotonic window does the heavy lifting: it excludes everything
        below the lock or beyond the flow ceiling, so only readings near the
        truth survive, and the digit scoring then picks among them — even when
        the high digits are pure garbage (they're pinned by the window anyway).
        """
        if not ocr_digits or len(ocr_digits) < 4 or self.last_good is None:
            return None
        lo = self.last_good
        # Bound the window TIGHTLY (not by the time-grown ceiling) so garbage
        # can never jump the lock far forward. Genuine large catch-ups are left
        # to the clean-read / cluster paths.
        hi = self.last_good + min(int(ceiling), self.score_window)
        od = ocr_digits[-9:]            # trust the rightmost (low) digits
        n = len(od)
        # The last few digits are the meter's "movers" and encode where it sits
        # inside the window — they must match strongly. This is the structural
        # guard against garbage frames whose tail (e.g. "016") happens to be one
        # segment away from an in-window value ("816"): the hundreds digit 0 vs
        # 8 scores 0.857 < the gate, so no candidate passes and we hold instead
        # of inventing a reading.
        k = min(3, n)
        od_low = od[-k:]
        gate = 0.90
        wsum = n * (n + 1) / 2.0        # 1+2+...+n (rightmost weighs most)
        best_v, best_s, second_s = None, -1.0, -1.0
        for v in range(lo, hi + 1):
            cs = f"{v:09d}"
            clow = cs[-k:]
            if any(_seg_sim(clow[j], od_low[j]) < gate for j in range(k)):
                continue                 # low digits don't corroborate -> skip
            ctail = cs[-n:]
            s = 0.0
            for i in range(n):
                s += (i + 1) * _seg_sim(ctail[i], od[i])
            score = s / wsum
            if score > best_s:
                second_s, best_s, best_v = best_s, score, v
            elif score > second_s:
                second_s = score
        # Record the model's best guess for this frame (even if below the accept
        # threshold) so the UI can show what the OCR thinks vs what was committed.
        if best_v is not None:
            self._ocr_guess = best_v
            self._ocr_guess_fit = best_s
        if best_v is not None and best_s >= self.fit_min:
            self._last_fit = best_s
            return best_v
        self._last_fit = None
        return None

    def _splice_low(self, nums, ceiling):
        """Reconstruct a 9-digit reading by keeping the locked value's high
        digits and trusting the low digits of a long OCR token.

        Only used when locked. Requires a source token long enough (>=7 digits)
        that its tail is trustworthy. Tries 5- then 4-digit low windows, handles
        a low-window rollover (carry), and only returns a value that is a small
        forward step within the physical flow ``ceiling``. Returns the int value
        or ``None``.
        """
        if self.last_good is None:
            return None
        lg = self.last_good
        lg_str = f"{lg:09d}"
        # Splicing trusts the low digits of a possibly-garbage token, so keep
        # the accepted step tight even when the time-based ceiling is large
        # (after a gap) — a real catch-up read is usually a clean 9-digit/thin
        # read handled elsewhere; splice is the last resort and must not let
        # garbage low digits invent a big jump.
        cap = min(ceiling, 2000)

        # Build the list of "tail source" digit strings to trust the low end of.
        # 1) Any single long token (>=7 digits).
        # 2) The concatenation of ALL tokens, and of all-but-the-first, to
        #    handle frames where the low digits fragment across tokens
        #    (e.g. "60nn 400 10 78" -> drop "60" junk, join "400"+"10"+"78").
        sources = [n for n in nums if len(n) >= 7]
        joined = "".join(nums)
        if len(joined) >= 7:
            sources.append(joined)
        if len(nums) > 1:
            tail_join = "".join(nums[1:])   # drop a leading junk token
            if len(tail_join) >= 7:
                sources.append(tail_join)

        for K in (5, 4):
            high = lg_str[:9 - K]
            unit = 10 ** K
            for src in sources:
                low = src[-K:]
                try:
                    cand = int(high + low)
                except ValueError:
                    continue
                for v in (cand, cand + unit):   # plain, then low-window carry
                    d = v - lg
                    if 0 <= d <= cap:
                        return v
        return None


    # ------------------------------------------------------------------
    #  Water-meter validation (the reading only ever counts UP)
    # ------------------------------------------------------------------
    def _validate(self, reading, digits, captured_ts=None):
        """Apply water-meter domain logic to a freshly extracted reading.

        A water meter is a cumulative odometer: the value can only stay the
        same or INCREASE, and never faster than the physical flow ceiling
        (``max_gpm`` gal/min). That ceiling is **time-aware** — a 5s frame may
        only advance a few counts, but after a 60s blind gap the meter could
        legitimately be up to 60s of flow higher. The OCR stream is roughly
        half good reads and half glare/blur garbage that lands far away, so:

          1. Only trust full 9-digit reads to drive the lock.
          2. Bootstrap by locking onto the dominant *cluster* of recent reads
             (median of the largest group) — ignores interleaved garbage.
          3. In steady state, accept forward progress within the physical
             ceiling, hold steady through small trailing-digit jitter, and
             reject everything else (keeping the last trustworthy value).
          4. Self-heal: if a solid cluster persistently disagrees with the
             locked value (a bad initial lock), resync to it.

        Returns ``(reading, delta, confidence, note)``.
        """
        if reading is None:
            # Frame too garbled to read. We still HOLD the last trustworthy
            # value, but we must be HONEST about it: the meter is monotonic, so
            # the held value is only a LOWER BOUND. If it's been more than a few
            # seconds since a clean read, the true value has almost certainly
            # moved up — so mark it "stale" with a "≥" so the row never claims a
            # stale number is the confirmed current reading.
            if self.last_good is not None:
                stale = None
                if captured_ts is not None and self._lock_ts is not None:
                    stale = captured_ts - self._lock_ts
                if stale is not None and stale >= self.stale_secs:
                    return (self.last_good, None, "stale",
                            f"stale {stale:.0f}s — true value higher (≥)")
                return self.last_good, None, "medium", "hold (no read)"
            return None, None, "none", "no-read"

        ceiling = self._max_forward_counts(captured_ts)

        # Partial reads (OCR dropped a digit) don't drive the lock. But once
        # we have a lock, an 8-digit read is almost always the real reading
        # with its leading zero dropped by OCR — if its value is a physically
        # possible forward step, trust it rather than freezing on the old value
        # (which would show a stale reading under a fresh timestamp).
        if digits != 9:
            if (self.last_good is not None and reading is not None
                    and digits >= 7):
                d = reading - self.last_good
                if 0 <= d <= ceiling:
                    self.last_good = reading
                    self._lock_ts = captured_ts
                    self.recent_valid.append(reading)
                    self._save_state()
                    return reading, d, "high", "thin"
            if self.last_good is not None:
                return self.last_good, None, "medium", "partial-hold"
            return reading, None, "low", "partial"

        self.recent_nine.append(reading)
        self.recent_valid.append(reading)

        # --- Bootstrap: lock onto the dominant cluster ---
        if self.last_good is None:
            if len(self.recent_nine) < 5:
                return reading, None, "low", "warming-up"
            locked = self._cluster_value()
            if locked is None:
                return reading, None, "low", "warming-up"
            self.last_good = locked
            self._lock_ts = captured_ts
            return locked, None, "high", "locked"

        delta = reading - self.last_good

        # No change -> accept, holds steady (and clears any pending advance).
        if delta == 0:
            self._lock_ts = captured_ts
            self._adv_buf.clear()
            return reading, 0, "high", ""

        # Forward progress within the physical ceiling, but a single frame may
        # NOT move the lock — require corroboration. The same value must have
        # been the scorer's pick in >=2 of the last few frames before we commit
        # it. The real meter reads the same value across consecutive frames;
        # one-off OCR garbage never repeats, so it can't ratchet the lock up.
        if 0 < delta <= ceiling:
            self._adv_buf.append(reading)
            hits = sum(1 for v in self._adv_buf if abs(v - reading) <= 20)
            if hits >= 2:
                self.last_good = reading
                self._lock_ts = captured_ts
                self._adv_buf.clear()
                self._save_state()
                note = f"fit {self._last_fit:.2f}" if self._last_fit is not None else ""
                return reading, delta, "high", note
            # Seen once — hold pending a second corroborating frame.
            return self.last_good, None, "medium", "pending confirm"

        # Small trailing-digit jitter dipping below the lock -> hold steady
        if -self.jitter_tol <= delta < 0:
            return self.last_good, 0, "medium", "hold"

        # Implausible read (garbage, decreased, or faster than physically
        # possible). With an anchor-seeded lock we NEVER chase a far-away
        # cluster (that's how it once latched onto 604001016 garbage). A
        # cluster may only nudge the lock FORWARD within the physical ceiling
        # and never below the known anchor.
        cand = self._cluster_value()
        if (cand is not None and cand >= self.anchor_value
                and 0 < cand - self.last_good <= ceiling):
            prev = self.last_good
            self.last_good = cand
            self._lock_ts = captured_ts
            self._save_state()
            return cand, cand - prev, "medium", "resync"

        return self.last_good, None, "rejected", (
            "decreased" if delta < 0 else "too-fast")

    def _cluster_value(self):
        """Return the median of the largest group of recent 9-digit reads that
        fall within ``max_jump`` of each other, provided that group is a
        majority of the recent reads. Garbage reads scatter far from the real
        value, so the real cluster dominates. Returns ``None`` if no clear
        cluster has formed yet.
        """
        vals = sorted(self.recent_nine)
        if len(vals) < 3:
            return None
        best = []
        for i in range(len(vals)):
            j = i
            while j < len(vals) and vals[j] - vals[i] <= self.max_jump:
                j += 1
            if (j - i) > len(best):
                best = vals[i:j]
        if len(best) >= max(3, (len(vals) + 1) // 2):
            return int(statistics.median(best))
        return None

    # ------------------------------------------------------------------
    #  Physical flow model
    # ------------------------------------------------------------------
    @staticmethod
    def _gpm(counts, elapsed_s):
        """Convert a count increase over ``elapsed_s`` seconds to gal/min."""
        if elapsed_s <= 0:
            return 0.0
        gal = counts / COUNTS_PER_GAL
        return gal / (elapsed_s / 60.0)

    def _max_forward_counts(self, captured_ts):
        """Largest count increase that is physically possible since the lock.

        Derived from ``max_gpm`` (the absolute plumbing ceiling) times the real
        elapsed capture time, so a 5s frame allows only ~5s of flow while a
        60s blind gap allows ~60s of flow. A 30% margin and a small floor keep
        a single fast/rounding frame from being wrongly rejected. Falls back to
        the loose ``max_jump`` when there's no timing info (e.g. bootstrap).
        """
        if captured_ts is None or self._lock_ts is None:
            return self.max_jump
        elapsed = max(0.0, captured_ts - self._lock_ts)
        counts = (self.max_gpm / 60.0) * elapsed * COUNTS_PER_GAL
        return max(300.0, counts * 1.3)

    # ------------------------------------------------------------------
    def _pick_closer(self, r1, t1, r2, t2):
        """Pick the reading closer to last known good."""
        if self.last_good is None:
            # No history -- prefer the one with more digits
            s1 = str(r1).replace(".", "")
            s2 = str(r2).replace(".", "")
            return (r1, t1) if len(s1) >= len(s2) else (r2, t2)
        d1 = abs(r1 - self.last_good)
        d2 = abs(r2 - self.last_good)
        return (r1, t1) if d1 <= d2 else (r2, t2)

    # ------------------------------------------------------------------
    def _entry(self, reading=None, delta=None, confidence="none",
               orientation="unknown", raw_n="", raw_f="", error=None,
               note="", captured_ts=None, queue_depth=None,
               gap_s=None, rate_gpm=None, kind="raw",
               ocr_guess=None, ocr_guess_fit=None, raw_low=None):
        """Pure formatter: build a readings-table row dict. All stateful
        tracking (lock, last-change, gap) is done by the callers; this just
        renders the numbers."""
        if reading is not None:
            r_str = str(int(reading))
            reading_str = r_str.zfill(9) if len(r_str) <= 9 else r_str
        else:
            reading_str = "\u2014"
        if ocr_guess is not None:
            g = str(int(ocr_guess))
            ocr_guess_str = g.zfill(9) if len(g) <= 9 else g
            if ocr_guess_fit is not None:
                ocr_guess_str += f" ({ocr_guess_fit:.2f})"
        else:
            ocr_guess_str = "\u2014"
        now = datetime.now()
        cap_str = "\u2014"
        lag_str = "\u2014"
        if captured_ts is not None:
            try:
                cap_dt = datetime.fromtimestamp(captured_ts)
                cap_str = cap_dt.strftime("%H:%M:%S")
                lag_str = f"{(now - cap_dt).total_seconds():.1f}s"
            except Exception:
                pass
        gap_str = f"{gap_s:.1f}s" if gap_s is not None else "\u2014"
        rate_str = f"{rate_gpm:.1f}" if rate_gpm is not None else "\u2014"
        global _ENTRY_SEQ
        _ENTRY_SEQ += 1
        rid = f"{int((captured_ts or now.timestamp()) * 1000)}-{_ENTRY_SEQ}"
        if reading is not None:
            ft3 = reading / COUNTS_PER_CF
            reading_ft3 = f"{ft3:,.3f}"
            reading_gal = f"{ft3 * GAL_PER_CF:,.1f}"
        else:
            reading_ft3 = "\u2014"
            reading_gal = "\u2014"
        if delta is not None:
            dft3 = delta / COUNTS_PER_CF
            dgal = dft3 * GAL_PER_CF
            sign = "+" if dft3 >= 0 else ""
            delta_ft3 = f"{sign}{dft3:.3f}"
            delta_gal = f"{sign}{dgal:.1f}"
            delta_str = f"+{int(delta)}" if delta >= 0 else str(int(delta))
        else:
            delta_ft3 = "\u2014"
            delta_gal = "\u2014"
            delta_str = "\u2014"
        return {
            "id": rid,
            "ts": now.strftime("%H:%M:%S"),
            "captured": cap_str,
            "lag": lag_str,
            "gap": gap_str,
            "queue": queue_depth if queue_depth is not None else "\u2014",
            "reading": reading_str,
            "ocr_guess": ocr_guess_str,
            "reading_ft3": reading_ft3,
            "reading_gal": reading_gal,
            "delta": delta_str,
            "delta_ft3": delta_ft3,
            "delta_gal": delta_gal,
            "rate": rate_str,
            "confidence": confidence,
            "stale": confidence == "stale",
            "orientation": orientation,
            "raw_n": raw_n,
            "raw_f": raw_f,
            "error": error,
            "note": note,
            "kind": kind,
            # Whether the validated reading's low 5 digits exactly match what
            # the OCR independently read (raw_low) — the trustworthy-banking
            # signal. None when no raw low digits were available.
            "raw_low_match": (
                None if raw_low is None or reading is None
                else (f"{int(reading):09d}"[-5:] == raw_low)),
        }
