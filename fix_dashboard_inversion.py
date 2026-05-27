"""Fix dashboard.py: add _apply_esp32_inversion helper and use it in /api/dashboard response."""
import re

path = "/home/jamesearlpace/smart-garden-server/dashboard.py"

with open(path, "r") as f:
    code = f.read()

# Remove the mangled insertion
code = re.sub(
    r'\n    def _apply_esp32_inversion\(status\):.*?return result\n',
    '\n',
    code,
    flags=re.DOTALL
)

# Revert the jsonify line to original if it was changed
code = code.replace(
    '"esp32": _apply_esp32_inversion(status_data) if status_data else None,',
    '"esp32": dict(status_data) if status_data else None,'
)

# Now do clean insertions:
# 1. Add helper function right before "def cached_valves():"
helper = '''    def _apply_esp32_inversion(status):
        """Return a copy of ESP32 status with valve open flags inverted for inverted zones."""
        import copy
        result = copy.deepcopy(status) if not isinstance(status, dict) else dict(status)
        if "valves" in result:
            result["valves"] = apply_inversion(result["valves"])
        return result

'''
code = code.replace(
    '    def cached_valves():',
    helper + '    def cached_valves():'
)

# 2. Use it in the /api/dashboard response
code = code.replace(
    '"esp32": dict(status_data) if status_data else None,',
    '"esp32": _apply_esp32_inversion(status_data) if status_data else None,'
)

with open(path, "w") as f:
    f.write(code)

print("Done. Verifying...")

# Verify
with open(path) as f:
    content = f.read()

assert "def _apply_esp32_inversion" in content, "Helper not found!"
assert "_apply_esp32_inversion(status_data)" in content, "Usage not found!"
assert content.count("def _apply_esp32_inversion") == 1, "Duplicate helper!"
print("All checks passed.")
