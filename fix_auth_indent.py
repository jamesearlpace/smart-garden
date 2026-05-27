"""Fix auth: move the auth block inside create_app function."""
import re

path = "/home/jamesearlpace/smart-garden-server/dashboard.py"

with open(path) as f:
    lines = f.readlines()

# Find the auth block (starts with "# ── Authentication" at column 0, ends before first indented @app.route)
auth_start = None
auth_end = None
for i, line in enumerate(lines):
    if "Authentication" in line and line.strip().startswith("#") and not line.startswith("    "):
        auth_start = i - 1  # include blank line before
        break

if auth_start is None:
    print("ERROR: Could not find auth block")
    exit(1)

# Find end of auth block - it's the line before the first "    @app.route" after the auth block
for i in range(auth_start + 1, len(lines)):
    if lines[i].strip().startswith("@app.route") and not lines[i].startswith("    "):
        # This is a module-level @app.route that should be inside create_app
        # Keep scanning until we find the first INDENTED @app.route (existing routes)
        continue
    if lines[i].startswith("    @app.route"):
        auth_end = i
        break

if auth_end is None:
    print("ERROR: Could not find end of auth block")
    exit(1)

print(f"Auth block: lines {auth_start+1} to {auth_end}")

# Extract the auth block
auth_lines = lines[auth_start:auth_end]

# Remove auth block from its current position
new_lines = lines[:auth_start] + lines[auth_end:]

# Now indent all auth lines by 4 spaces (they need to be inside create_app)
# But some are already at 0 indent (module level), need 4 spaces
indented_auth = []
for line in auth_lines:
    if line.strip() == "":
        indented_auth.append("\n")
    elif line.startswith("    "):
        # Already indented, keep as-is
        indented_auth.append(line)
    elif line.startswith("@"):
        indented_auth.append("    " + line)
    elif line.startswith("def "):
        indented_auth.append("    " + line)
    elif line.startswith("#"):
        indented_auth.append("    " + line)
    elif line.startswith("import ") or line.startswith("from "):
        # Move imports to top of file instead
        indented_auth.append("    " + line)
    else:
        indented_auth.append("    " + line)

# Find insertion point - right before the first "    @app.route" in new_lines
insert_idx = None
for i, line in enumerate(new_lines):
    if line.startswith("    @app.route"):
        insert_idx = i
        break

if insert_idx is None:
    print("ERROR: Could not find insertion point")
    exit(1)

print(f"Inserting at line {insert_idx+1}")

# Insert
final = new_lines[:insert_idx] + indented_auth + new_lines[insert_idx:]

with open(path, "w") as f:
    f.writelines(final)

print("Fixed! Auth block moved inside create_app.")

# Verify
with open(path) as f:
    content = f.read()
    
# Quick syntax check
try:
    compile(content, path, "exec")
    print("Syntax check: PASSED")
except SyntaxError as e:
    print(f"Syntax check: FAILED - {e}")
