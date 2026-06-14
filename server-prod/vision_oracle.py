"""Vision-LLM oracle for the water meter — reads the meter with GPT-4o.

The fast local pipeline (RapidOCR + physics) runs every 5s and is right most of
the time, but it can't read badly-glared/blurred frames and has no way to
recover from a false-high lock on its own. This oracle is the high-quality
fallback: it sends the ORIGINAL full-color frame to GPT-4o vision (which reads
the 9-digit odometer far better than scene-text OCR) and returns a trusted
reading. It is used SPARINGLY — for auto-re-anchoring a drifted/stale lock and
for producing trusted training-data labels — never on every 5s frame, so cost
stays at a few tenths of a cent per call.

Key + endpoint come from /etc/smart-garden/cam-env (root-only).
"""
import base64
import io
import json
import logging
import os
import urllib.request

log = logging.getLogger("vision_oracle")

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MODEL = os.environ.get("ORACLE_MODEL", "gpt-4o")

_SYS = (
    "You read residential water-meter LCD odometers. The display shows exactly "
    "9 digits in a single horizontal row (the right-most digits are the small/"
    "decimal ones). Reply ONLY with strict JSON: "
    '{"digits":"<exactly 9 digits>","confidence":"high|medium|low",'
    '"readable":true|false}. No prose. Read carefully, digit by digit. If a '
    "digit is genuinely unreadable, set readable=false and give your best guess."
)


def _build_hint(hint):
    """Turn a context dict into a plain-language prompt addendum that helps the
    model disambiguate glare-garbled HIGH digits using context it can't see in
    the pixels: the leading digits almost never change between reads, so the
    expected prefix is a strong anchor for the left side of the display.

    Critical framing: the prefix helps disambiguate glare on the HIGH (left)
    digits ONLY. The reading is NOT forced to be >= the last value — the last
    value is just a rough sanity-check, because our previous estimate can be
    slightly off. The LOW (right-hand) digits change with every gallon and must
    be read straight from the image — report exactly what you see, even if the
    result is a little below the last estimate.
    """
    if not hint:
        return ""
    parts = []
    last = hint.get("last_value")
    lo = hint.get("min_value")
    hi = hint.get("max_value")
    prefix = hint.get("high_prefix")
    if last is not None:
        parts.append(
            f"For context, this meter was last estimated near {int(last):09d} "
            f"({int(last) / 1000:,.3f} ft\u00b3); it's a cumulative odometer that "
            "rises slowly, but that estimate may be slightly off so do not force "
            "your answer to match it.")
    if lo is not None and hi is not None:
        parts.append(
            f"It is normally in the rough range {int(lo):09d}-{int(hi):09d}.")
    if prefix:
        parts.append(
            f"The leading digits are almost certainly '{prefix}' (the high "
            "digits barely move between reads); if glare makes the left side "
            "ambiguous, trust this prefix.")
    parts.append(
        "Use the context ONLY to resolve glare on the LEFT/high digits. The "
        "RIGHT-hand (low) digits change constantly — read those directly from "
        "the image and report exactly what you see.")
    return " ".join(parts)


def _api_key():
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    try:
        for line in open("/etc/smart-garden/cam-env"):
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def available():
    return bool(_api_key())


def read_meter(jpeg_bytes, rotate180=True, hint=None):
    """Send a JPEG frame to GPT-4o vision and return a parsed reading.

    ``hint`` (optional dict) supplies physics context so the model can reason
    through glare on the high digits: {last_value, min_value, max_value,
    high_prefix}. It never overrides clearly-read low digits — see _build_hint.

    Returns a dict: {"ok":bool, "value":int|None, "digits":str, "confidence":str,
    "readable":bool, "error":str|None, "cost_tokens":int}. ``value`` is the int
    of the 9 digits (leading zeros kept via 9-width), or None if unreadable.
    """
    key = _api_key()
    if not key:
        return {"ok": False, "error": "no OPENAI_API_KEY", "value": None,
                "digits": "", "confidence": "none", "readable": False,
                "cost_tokens": 0}
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(jpeg_bytes))
        if rotate180:
            img = img.rotate(180)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=92)
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        return {"ok": False, "error": f"image: {e}", "value": None,
                "digits": "", "confidence": "none", "readable": False,
                "cost_tokens": 0}

    user_text = "Read the 9 digits on this water meter, left to right."
    hint_text = _build_hint(hint)
    if hint_text:
        user_text += " " + hint_text
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": _SYS},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}",
                               "detail": "high"}},
            ]},
        ],
        "max_tokens": 80,
        "temperature": 0,
    }
    req = urllib.request.Request(
        OPENAI_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            out = json.load(r)
        content = out["choices"][0]["message"]["content"].strip()
        tokens = out.get("usage", {}).get("total_tokens", 0)
        # Strip code fences if the model added them.
        if content.startswith("```"):
            content = content.strip("`")
            content = content[content.find("{"):]
        parsed = json.loads(content[content.find("{"):content.rfind("}") + 1])
        digits = "".join(ch for ch in str(parsed.get("digits", "")) if ch.isdigit())
        value = int(digits) if len(digits) == 9 else None
        return {"ok": value is not None, "value": value, "digits": digits,
                "confidence": parsed.get("confidence", "low"),
                "readable": bool(parsed.get("readable", False)),
                "error": None if value is not None else "not 9 digits",
                "cost_tokens": tokens}
    except Exception as e:
        detail = ""
        if hasattr(e, "read"):
            try:
                detail = e.read().decode()[:200]
            except Exception:
                pass
        log.warning("oracle call failed: %s %s", e, detail)
        return {"ok": False, "error": f"{type(e).__name__}: {e} {detail}",
                "value": None, "digits": "", "confidence": "none",
                "readable": False, "cost_tokens": 0}
