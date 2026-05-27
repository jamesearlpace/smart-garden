"""Replace PIN login with Google OAuth for home-net-watch.

Patches:
1. Adds Google OAuth auth functions
2. Replaces the login_page route with Google Sign-In
3. Adds /auth/config, /auth/google, /auth/logout, /auth/check endpoints  
4. Keeps _check_pin working for session-authenticated users
5. Creates allowed_emails.json (James only)
"""
import json, os

BASE = "/opt/home-net-watch"
HOME = "/home/jamesearlpace/home-net-watch"

# 1. Create allowed_emails.json
emails = [{"email": "jamesearlpace@gmail.com", "name": "James Pace"}]
for path in [BASE, HOME]:
    with open(os.path.join(path, "allowed_emails.json"), "w") as f:
        json.dump(emails, f, indent=2)
print("Created allowed_emails.json in both locations")

# 2. Patch app.py
app_path = os.path.join(BASE, "app.py")
with open(app_path) as f:
    code = f.read()

if "auth/google" in code:
    print("app.py already has Google auth — skipping")
    exit(0)

# Add imports after existing imports
import_block = '''
import hashlib, hmac, urllib.request, urllib.parse
import json as auth_json
'''
code = code.replace(
    'from flask import Flask, render_template, jsonify, request, session, redirect',
    'from flask import Flask, render_template, jsonify, request, session, redirect, make_response' + import_block
)

# Add Google auth constants after PIN line
google_auth_block = '''
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
SESSION_SECRET_HMAC = os.environ.get("SESSION_SECRET", "homenetwatch2026")
ALLOWED_EMAILS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "allowed_emails.json")

def _load_allowed_emails():
    try:
        with open(ALLOWED_EMAILS_FILE) as f:
            return {e["email"].lower() for e in auth_json.load(f)}
    except Exception:
        return set()

def _verify_google_token(credential):
    url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(credential)}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = auth_json.loads(resp.read().decode())
        if data.get("aud") != GOOGLE_CLIENT_ID:
            return None
        return data.get("email", "").lower()
    except Exception:
        return None
'''
code = code.replace(
    'PIN = os.environ.get("NETMON_PIN", "1234")',
    'PIN = os.environ.get("NETMON_PIN", "1234")' + google_auth_block
)

# Replace the login_page route with Google Sign-In
old_login = """@app.route("/login")
def login_page():
    return '''
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login</title>
<style>
  body { background: #0f0f1a; color: #e0e0e0; font-family: -apple-system, sans-serif;
         display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
  .box { width: 220px; text-align: center; }
  input { width: 100%; padding: 14px; font-size: 1.1rem; text-align: center;
          background: #1a1a2e; border: 1px solid #333; border-radius: 10px; color: #fff;
          letter-spacing: 0.3em; box-sizing: border-box; }
  input:focus { outline: none; border-color: #555; }
  .e { color: #c44; font-size: 0.8rem; margin-top: 0.75rem; min-height: 1.2em; }
</style>
</head>
<body>
<div class="box">
  <form onsubmit="g(event)">
    <input type="password" id="p" placeholder="\\u2022\\u2022\\u2022\\u2022\\u2022\\u2022" inputmode="numeric" autofocus>
  </form>
  <div class="e" id="e"></div>
</div>
<script>
async function g(e) {
  e.preventDefault();
  const p = document.getElementById("p").value;
  const r = await fetch("/api/login", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({pin:p})});
  const d = await r.json();
  if (d.ok) window.location.href = "/";
  else document.getElementById("e").textContent = "Incorrect";
}
</script>
</body>
</html>
\\'\\'\\'"""

# Since the login page is inline HTML with complex quoting, let's use a simpler approach
# Find and replace the login route
import re

# Replace login page with Google Sign-In
new_login = '''@app.route("/login")
def login_page():
    return """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Network Monitor - Login</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,sans-serif;background:#0f0f1a;color:#e0e0e0;
display:flex;justify-content:center;align-items:center;min-height:100vh}
.card{background:#1a1a2e;border-radius:16px;padding:40px;max-width:380px;width:90%;
text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.3)}
h1{font-size:1.5rem;margin-bottom:8px;color:#8b5cf6}
.sub{color:#94a3b8;font-size:.85rem;margin-bottom:24px}
.google-btn{margin:20px auto;display:flex;justify-content:center}
.error{color:#ef4444;font-size:.85rem;margin-top:12px;display:none}
</style></head><body>
<div class="card">
<h1>Network Monitor</h1>
<div class="sub">Sign in with Google to continue</div>
<div class="google-btn">
<div id="g_id_onload" data-client_id="" data-callback="onGoogleSignIn" data-auto_prompt="false"></div>
<div class="g_id_signin" data-type="standard" data-size="large" data-theme="filled_black"></div>
</div>
<div class="error" id="error"></div>
</div>
<script src="https://accounts.google.com/gsi/client" async defer></script>
<script>
fetch('/auth/config').then(r=>r.json()).then(cfg=>{
document.getElementById('g_id_onload').setAttribute('data-client_id',cfg.client_id);
if(window.google&&google.accounts){google.accounts.id.initialize({client_id:cfg.client_id,callback:onGoogleSignIn});
google.accounts.id.renderButton(document.querySelector('.g_id_signin'),{theme:'filled_black',size:'large'});}});
function onGoogleSignIn(response){
fetch('/auth/google',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({credential:response.credential})}).then(r=>r.json()).then(data=>{
if(data.ok)window.location.href='/';
else{document.getElementById('error').style.display='block';
document.getElementById('error').textContent=data.error||'Not authorized';}});}
</script></body></html>"""

@app.route("/auth/config")
def auth_config():
    return jsonify({"client_id": GOOGLE_CLIENT_ID})

@app.route("/auth/google", methods=["POST"])
def auth_google():
    data = request.get_json(silent=True) or {}
    credential = data.get("credential", "")
    email = _verify_google_token(credential)
    if not email:
        return jsonify({"ok": False, "error": "Invalid Google token"}), 401
    if email not in _load_allowed_emails():
        return jsonify({"ok": False, "error": "Not authorized"}), 403
    session.permanent = True
    session["authenticated"] = True
    session["email"] = email
    return jsonify({"ok": True, "email": email})

@app.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/login")

@app.route("/auth/check")
def auth_check():
    if session.get("authenticated"):
        return jsonify({"authenticated": True, "email": session.get("email", "")})
    return jsonify({"authenticated": False}), 401'''

# Find the login route in the code - it starts with @app.route("/login") and ends before @app.route("/api/login"
login_start = code.find('@app.route("/login")')
login_end = code.find('@app.route("/api/login"')
if login_start == -1 or login_end == -1:
    print("ERROR: Could not find login route boundaries")
    exit(1)

code = code[:login_start] + new_login + "\n\n" + code[login_end:]

# Update before_request to allow auth routes
code = code.replace(
    'if request.path in ("/login", "/api/login") or request.path.startswith("/static/"):',
    'if request.path in ("/login", "/api/login") or request.path.startswith("/static/") or request.path.startswith("/auth/"):'
)

with open(app_path, "w") as f:
    f.write(code)

# Also copy to home dir
import shutil
shutil.copy2(app_path, os.path.join(HOME, "app.py"))

print("Patched app.py with Google OAuth")

# Verify syntax
try:
    compile(code, "app.py", "exec")
    print("Syntax check: PASSED")
except SyntaxError as e:
    print(f"Syntax check: FAILED - {e}")
