#!/usr/bin/env python3
"""Replace the wiring panel in index.html with the new SVG-based version."""
import sys

template_path = sys.argv[1] if len(sys.argv) > 1 else "/home/jamesearlpace/smart-garden-server/templates/index.html"
svg_path = sys.argv[2] if len(sys.argv) > 2 else "/home/jamesearlpace/smart-garden-server/static/wiring-diagram.svg"

with open(template_path, "r") as f:
    lines = f.readlines()

with open(svg_path, "r") as f:
    svg_content = f.read()

# Find wiring panel start and next panel
wiring_start = None
next_panel = None
for i, line in enumerate(lines):
    if 'id="p-wiring"' in line:
        wiring_start = i
    elif wiring_start is not None and next_panel is None and 'id="p-map"' in line:
        next_panel = i
        break

if wiring_start is None or next_panel is None:
    print(f"ERROR: Could not find panel boundaries (start={wiring_start}, next={next_panel})")
    sys.exit(1)

print(f"Replacing lines {wiring_start+1} to {next_panel} ({next_panel - wiring_start} lines)")

# Build new wiring panel content
new_panel = f'''  <div class="panel" id="p-wiring">
    <div style="padding:16px;max-width:1100px;margin:0 auto;">
      <h2 style="color:#e2e8f0;margin-bottom:16px;font-size:1.2em;">Wiring Diagram</h2>
      <p style="color:#94a3b8;font-size:.85em;margin-bottom:12px;">
        Updated 2026-05-01: ESP32U + MCP23017 expansion board. Valves 1-8 on I2C expander, valves 9-10 on ESP32 GPIO.
        Hover over components for details.
      </p>
      {svg_content}
    </div>
  </div>
'''

new_lines = lines[:wiring_start] + [new_panel] + lines[next_panel:]

with open(template_path, "w") as f:
    f.writelines(new_lines)

print(f"SUCCESS: Replaced {next_panel - wiring_start} lines with new wiring panel")
