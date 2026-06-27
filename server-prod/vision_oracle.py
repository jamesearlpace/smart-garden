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

Provider selection:
- Azure OpenAI (preferred when configured):
    AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_DEPLOYMENT
    Optional: AZURE_OPENAI_API_VERSION (default 2024-10-21)
- OpenAI platform fallback:
    OPENAI_API_KEY
"""
import base64
import io
import json
import logging
import os
import time
import urllib.request

log = logging.getLogger("vision_oracle")

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MODEL = os.environ.get("ORACLE_MODEL", "gpt-4o")
AZURE_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")

# ── Rate-limit circuit breaker ────────────────────────────────────────────
# Azure OpenAI deployments with a low per-minute TPM/RPM return HTTP 429
# rate_limit_exceeded when called too fast. Without a brake, every caller (the
# live per-frame fallback AND the archive-heal/converge background workers that
# re-read a frame every ~1.5s) keeps hammering and 429-storms the log while
# never succeeding. This module-level breaker makes ALL callers back off
# together: after a 429 we refuse new HTTP calls for a short, exponentially
# growing window, reset on the next successful response. Env-tunable.
_RATE_BACKOFF_BASE_SECS = float(
    os.environ.get("ORACLE_RATE_BACKOFF_BASE_SECS", "20"))
_RATE_BACKOFF_MAX_SECS = float(
    os.environ.get("ORACLE_RATE_BACKOFF_MAX_SECS", "300"))
_rate_state = {"block_until": 0.0, "strikes": 0}


def rate_limited_until():
    """Epoch secs until which calls are suppressed due to 429s (0 = not blocked)."""
    return _rate_state["block_until"]


def _note_rate_limit():
    """Record a 429 and extend the backoff window (exponential, capped)."""
    _rate_state["strikes"] += 1
    backoff = min(
        _RATE_BACKOFF_BASE_SECS * (2 ** (_rate_state["strikes"] - 1)),
        _RATE_BACKOFF_MAX_SECS)
    _rate_state["block_until"] = time.time() + backoff
    return backoff


def _clear_rate_limit():
    """A successful HTTP response means we're no longer throttled — reset."""
    if _rate_state["strikes"] or _rate_state["block_until"]:
        _rate_state["strikes"] = 0
        _rate_state["block_until"] = 0.0

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
        ls = f"{int(last):09d}"
        # The meter moves only a few hundred counts between reads, so the first
        # SIX digits ("094100") barely change — only the last ~3 move. Telling
        # the model the expected leading block is the single biggest accuracy
        # win against glare on the middle digits (which it otherwise guesses).
        parts.append(
            f"For context, this meter was last read very close to {ls} "
            f"({int(last) / 1000:,.3f} ft\u00b3). It is a cumulative odometer that "
            "rises only slowly, so the reading you see is almost certainly within "
            "a few counts of that. In practice the first SIX digits "
            f"('{ls[:6]}') are the same as last time and ONLY THE LAST 2-3 DIGITS "
            "have changed. Do not force a match, but use this to resolve glare on "
            "the left and middle digits.")
    if prefix:
        parts.append(
            f"The leading digits are almost certainly '{prefix}'.")
    parts.append(
        "Read the LAST 3 digits directly and carefully from the image (those are "
        "the ones that actually change) and report exactly what you see. Keep the "
        "leading digits consistent with the context above unless the image very "
        "clearly shows otherwise (e.g. a rollover).")
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


def _env(name, default=None):
    val = os.environ.get(name)
    if val not in (None, ""):
        return val
    try:
        for line in open("/etc/smart-garden/cam-env"):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return default


def _provider_config():
    """Resolve runtime provider configuration.

    Prefer Azure OpenAI when endpoint+key+deployment are configured; otherwise
    fall back to OpenAI platform key.
    """
    az_endpoint = _env("AZURE_OPENAI_ENDPOINT")
    az_key = _env("AZURE_OPENAI_KEY")
    az_deploy = _env("AZURE_OPENAI_DEPLOYMENT") or _env("ORACLE_MODEL") or MODEL
    az_api_version = _env("AZURE_OPENAI_API_VERSION", AZURE_API_VERSION)

    if az_endpoint and az_key and az_deploy:
        return {
            "provider": "azure_openai",
            "endpoint": str(az_endpoint).rstrip("/"),
            "key": az_key,
            "deployment": az_deploy,
            "api_version": az_api_version,
        }

    key = _api_key()
    if key:
        return {
            "provider": "openai",
            "url": OPENAI_URL,
            "key": key,
        }
    return None


def available():
    return bool(_provider_config())


def read_meter(jpeg_bytes, rotate180=True, hint=None, model=None):
    """Send a JPEG frame to GPT-4o vision and return a parsed reading.

    ``hint`` (optional dict) supplies physics context so the model can reason
    through glare on the high digits: {last_value, min_value, max_value,
    high_prefix}. It never overrides clearly-read low digits — see _build_hint.

    ``model`` (optional) overrides the default ORACLE_MODEL for this single
    call — used by the hybrid arbiter: a cheap model (gpt-4o-mini) for the
    routine heartbeat reads, and a stronger model (gpt-4o) only when the read
    is about to MOVE the lock (a correction), where accuracy matters most.

    Returns a dict: {"ok":bool, "value":int|None, "digits":str, "confidence":str,
    "readable":bool, "error":str|None, "cost_tokens":int}. ``value`` is the int
    of the 9 digits (leading zeros kept via 9-width), or None if unreadable.
    """
    cfg = _provider_config()
    if not cfg:
        return {"ok": False, "error": "no oracle credentials configured", "value": None,
                "digits": "", "confidence": "none", "readable": False,
                "cost_tokens": 0}
    # Rate-limit circuit breaker: if a recent 429 put us in a backoff window,
    # don't make another HTTP call (it would just 429 again). Fail fast so the
    # caller skips this read instead of hammering the provider.
    _now = time.time()
    if _now < _rate_state["block_until"]:
        return {"ok": False,
                "error": ("rate_limited: backing off "
                          f"{_rate_state['block_until'] - _now:.0f}s"),
                "value": None, "digits": "", "confidence": "none",
                "readable": False, "provider": cfg.get("provider"),
                "rate_limited": True, "cost_tokens": 0}
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

    req_url = cfg.get("url")
    req_headers = {"Content-Type": "application/json"}
    req_model = model or MODEL
    provider = cfg.get("provider")

    if provider == "azure_openai":
        deployment = str(model or cfg.get("deployment") or MODEL)
        req_url = (
            f"{cfg.get('endpoint')}/openai/deployments/{deployment}/chat/completions"
            f"?api-version={cfg.get('api_version') or AZURE_API_VERSION}"
        )
        req_headers["api-key"] = cfg.get("key")
        req_model = deployment
    else:
        req_headers["Authorization"] = f"Bearer {cfg.get('key')}"
        body["model"] = req_model

    req = urllib.request.Request(
        req_url, data=json.dumps(body).encode(), headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            out = json.load(r)
        _clear_rate_limit()  # a 200 response means we're not throttled
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
            "model": req_model,
            "provider": provider,
                "cost_tokens": tokens}
    except Exception as e:
        detail = ""
        if hasattr(e, "read"):
            try:
                detail = e.read().decode()[:200]
            except Exception:
                pass
        code = getattr(e, "code", None)
        blob = f"{e} {detail}".lower()
        if (code == 429 or "rate_limit" in blob
                or "too_many_requests" in blob or "429" in blob):
            backoff = _note_rate_limit()
            log.warning(
                "oracle rate-limited (429) — suppressing oracle calls for %.0fs "
                "(strike %d)", backoff, _rate_state["strikes"])
        else:
            log.warning("oracle call failed: %s %s", e, detail)
        return {"ok": False, "error": f"{type(e).__name__}: {e} {detail}",
                "value": None, "digits": "", "confidence": "none",
            "readable": False, "provider": provider,
            "cost_tokens": 0}
