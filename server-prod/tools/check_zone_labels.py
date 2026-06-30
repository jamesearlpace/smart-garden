"""Guard against showing internal 0-based zone ids in UI labels.

Internal zone ids are 0-8. User-facing labels must use either API-provided
zone_label/zone_number or explicit +1 fallback math.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECK_PATHS = [
    ROOT / "dashboard.py",
    ROOT / "flow_monitor.py",
    ROOT / "templates",
]

# Obvious bad forms this bug came from, e.g. "Zone " + ev.zone_id.
BAD_PATTERNS = [
    re.compile(r"Zone\s*['\"]?\s*\+\s*[A-Za-z_][A-Za-z0-9_]*(?:\.zone_id|\[['\"]zone_id['\"]\])\b(?!\s*\+)"),
    re.compile(r"f['\"]Zone\s*\{(?:zone_id|zid|zoneId)\}"),
]


def iter_files():
    for path in CHECK_PATHS:
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from path.rglob("*.html")


def main() -> int:
    failures = []
    for path in iter_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "Zone" not in line:
                continue
            if "zone_label" in line or "zone_number" in line:
                continue
            if " + 1" in line or "+1" in line:
                continue
            if "Zone {" in line and any(token in line for token in ("zone_id", "zid", "zoneId")):
                failures.append((path.relative_to(ROOT), lineno, line.strip()))
                continue
            for pat in BAD_PATTERNS:
                if pat.search(line):
                    failures.append((path.relative_to(ROOT), lineno, line.strip()))
                    break
    if failures:
        for rel, lineno, line in failures:
            print(f"{rel}:{lineno}: {line}")
        return 1
    print("zone label check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
