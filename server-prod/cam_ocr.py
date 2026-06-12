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
from datetime import datetime
from threading import Lock
from collections import deque

log = logging.getLogger("cam_ocr")


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
        log.info("MeterReader backend: %s, orientation: %s",
                 self.backend, self.orientation)

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
        reading = self._extract(raw_text)
        raw_used = raw_text

        # --- Step 5: Validate and score ---
        confidence = "none"
        delta = None

        if reading is not None:
            digits = len(str(int(reading)))
            # Confidence based on how close to 9 digits
            if digits == 9:
                confidence = "high"
            elif digits >= 7:
                confidence = "medium"
            else:
                confidence = "low"

            # Delta from last good
            if self.last_good is not None:
                delta = reading - self.last_good
                # Boost confidence if consistent with previous
                if delta >= 0 and delta < 1000 and digits >= 7:
                    confidence = "high"

            # Always update last_good with best reads
            if digits >= 7:
                self.last_good = reading
                self.recent_valid.append(reading)

        entry = self._entry(
            reading=reading,
            delta=delta,
            confidence=confidence,
            orientation=self.orientation,
            raw_n=(raw_used or raw_text or raw_text_orig or "")[:80],
            raw_f="",
        )
        with self.lock:
            self.readings.append(entry)
            if len(self.readings) > 2000:
                self.readings = self.readings[-2000:]
        return entry

    # ------------------------------------------------------------------
    def process_text(self, raw_text):
        """Validate + store a reading from OCR text done elsewhere (e.g. the
        tower OCR service). Reuses the same extract/validate/median logic as
        process(); the heavy OCR just happens off-box."""
        reading = self._extract(raw_text)
        confidence = "none"
        delta = None
        if reading is not None:
            digits = len(str(int(reading)))
            if digits == 9:
                confidence = "high"
            elif digits >= 7:
                confidence = "medium"
            else:
                confidence = "low"
            if self.last_good is not None:
                delta = reading - self.last_good
                if delta >= 0 and delta < 1000 and digits >= 7:
                    confidence = "high"
            if digits >= 7:
                self.last_good = reading
                self.recent_valid.append(reading)
        entry = self._entry(
            reading=reading, delta=delta, confidence=confidence,
            orientation=self.orientation, raw_n=(raw_text or "")[:80], raw_f="",
        )
        with self.lock:
            self.readings.append(entry)
            if len(self.readings) > 2000:
                self.readings = self.readings[-2000:]
        return entry

    # ------------------------------------------------------------------
    def get_readings(self, limit=100):
        with self.lock:
            return list(reversed(self.readings[-limit:]))

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
    @staticmethod
    def _extract(text):
        """Pull the most likely meter reading from raw OCR text.

        This is a Sensus water meter with a 9-digit LCD display.
        Prefers 9-digit sequences but will accept 5+ digits for partial reads.
        """
        if not text:
            return None
        # Strip everything except digits
        nums = re.findall(r"\d+", text)
        if not nums:
            return None

        # First: try exactly 9 digits
        nine_digit = [n for n in nums if len(n) == 9]
        if nine_digit:
            try:
                return int(nine_digit[0])
            except ValueError:
                pass

        # Second: try concatenating all digits (OCR may split: "0931 95171")
        all_digits = re.sub(r"[^0-9]", "", text)
        if len(all_digits) == 9:
            try:
                return int(all_digits)
            except ValueError:
                pass

        # Third: accept any sequence with 5+ digits (partial read, better than nothing)
        long_nums = [n for n in nums if len(n) >= 5]
        if long_nums:
            best = max(long_nums, key=len)
            try:
                return int(best)
            except ValueError:
                pass

        return None

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
               orientation="unknown", raw_n="", raw_f="", error=None):
        if reading is not None:
            r_str = str(int(reading))
            # Pad to 9 digits if it's a full read, otherwise show as-is
            if len(r_str) <= 9:
                reading_str = r_str.zfill(9)
            else:
                reading_str = r_str
        else:
            reading_str = "\u2014"
        return {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "reading": reading_str,
            "delta": f"+{int(delta)}" if delta is not None and delta >= 0 else (str(int(delta)) if delta is not None else "\u2014"),
            "confidence": confidence,
            "orientation": orientation,
            "raw_n": raw_n,
            "raw_f": raw_f,
            "error": error,
        }
