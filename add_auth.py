"""Add Google OAuth authentication to the smart-garden-server dashboard.

Creates:
  - allowed_emails.json (James + Natalie only)
  - login.html (Google Sign-In page)
  - Patches dashboard.py to add auth middleware

Also updates the systemd service to include GOOGLE_CLIENT_ID and SESSION_SECRET.
"""
import json, os, textwrap

BASE = "/home/jamesearlpace/smart-garden-server"

# 1. Create allowed_emails.json
emails = [
    {"email": "jamesearlpace@gmail.com", "name": "James Pace"},
    {"email": "natalielpace@gmail.com", "name": "Natalie Pace"},
]
with open(os.path.join(BASE, "allowed_emails.json"), "w") as f:
    json.dump(emails, f, indent=2)
print("Created allowed_emails.json")

# 2. Create login.html
login_html = textwrap.dedent('''\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Garden - Login</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0f172a; color: #e2e8f0; display: flex; justify-content: center;
               align-items: center; min-height: 100vh; }
        .card { background: #1e293b; border-radius: 16px; padding: 40px; max-width: 380px;
                width: 90%; text-align: center; box-shadow: 0 8px 32px rgba(0,0,0,0.3); }
        h1 { font-size: 1.5rem; margin-bottom: 8px; color: #22c55e; }
        .sub { color: #94a3b8; font-size: 0.85rem; margin-bottom: 24px; }
        .google-btn { margin: 20px auto; display: flex; justify-content: center; }
        .error { color: #ef4444; font-size: 0.85rem; margin-top: 12px; display: none; }
    </style>
</head>
<body>
    <div class="card">
        <h1>🌱 Smart Garden</h1>
        <div class="sub">Sign in with Google to continue</div>
        <div class="google-btn">
            <div id="g_id_onload"
                 data-client_id=""
                 data-callback="onGoogleSignIn"
                 data-auto_prompt="false">
            </div>
            <div class="g_id_signin" data-type="standard" data-size="large"
                 data-theme="filled_black" data-text="sign_in_with"
                 data-shape="rectangular" data-logo_alignment="left">
            </div>
        </div>
        <div class="error" id="error"></div>
    </div>
    <script src="https://accounts.google.com/gsi/client" async defer></script>
    <script>
        // Fetch client ID from server
        fetch('/auth/config').then(r => r.json()).then(cfg => {
            document.getElementById('g_id_onload').setAttribute('data-client_id', cfg.client_id);
            // Re-init Google button with client ID
            if (window.google && google.accounts) {
                google.accounts.id.initialize({
                    client_id: cfg.client_id,
                    callback: onGoogleSignIn
                });
                google.accounts.id.renderButton(
                    document.querySelector('.g_id_signin'),
                    { theme: 'filled_black', size: 'large', text: 'sign_in_with' }
                );
            }
        });

        function onGoogleSignIn(response) {
            fetch('/auth/google', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ credential: response.credential })
            }).then(r => r.json()).then(data => {
                if (data.ok) {
                    window.location.href = '/';
                } else {
                    document.getElementById('error').style.display = 'block';
                    document.getElementById('error').textContent = data.error || 'Not authorized';
                }
            }).catch(err => {
                document.getElementById('error').style.display = 'block';
                document.getElementById('error').textContent = 'Sign-in failed';
            });
        }
    </script>
</body>
</html>
''')
with open(os.path.join(BASE, "templates", "login.html"), "w") as f:
    f.write(login_html)
print("Created templates/login.html")

# 3. Patch dashboard.py to add auth
dashboard_path = os.path.join(BASE, "dashboard.py")
with open(dashboard_path) as f:
    code = f.read()

# Check if already patched
if "auth/google" in code:
    print("dashboard.py already has auth — skipping patch")
else:
    # Add imports and auth setup after the first "def create_app" or after initial imports
    auth_block = textwrap.dedent('''\

    # ── Authentication ──────────────────────────────────────────────
    import hashlib, hmac, time, json as auth_json, urllib.request, urllib.parse

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    SESSION_SECRET = os.environ.get("SESSION_SECRET", "smartgarden2026default")
    SESSION_MAX_AGE = 86400 * 30  # 30 days
    ALLOWED_EMAILS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "allowed_emails.json")

    def _load_allowed_emails():
        try:
            with open(ALLOWED_EMAILS_FILE) as f:
                return {e["email"].lower() for e in auth_json.load(f)}
        except Exception:
            return set()

    def _make_session_token(email):
        ts = str(int(time.time()))
        sig = hmac.new(SESSION_SECRET.encode(), f"{email}|{ts}".encode(), hashlib.sha256).hexdigest()
        return f"{email}|{ts}|{sig}"

    def _verify_session_token(token):
        try:
            parts = token.split("|")
            if len(parts) != 3:
                return None
            email, ts, sig = parts
            expected = hmac.new(SESSION_SECRET.encode(), f"{email}|{ts}".encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                return None
            if time.time() - int(ts) > SESSION_MAX_AGE:
                return None
            return email
        except Exception:
            return None

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

    @app.before_request
    def check_auth():
        # Public routes
        public = ("/login", "/auth/", "/favicon.ico", "/static/")
        if any(request.path.startswith(p) for p in public) or request.path == "/login":
            return None
        # Check session cookie
        token = request.cookies.get("session")
        if token:
            email = _verify_session_token(token)
            if email and email in _load_allowed_emails():
                return None
        # Not authenticated — redirect to login
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"error": "Not authenticated"}), 401
        return redirect("/login")

    @app.route("/login")
    def login_page():
        return render_template("login.html")

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
        resp = make_response(jsonify({"ok": True, "email": email}))
        token = _make_session_token(email)
        resp.set_cookie("session", token, max_age=SESSION_MAX_AGE, httponly=True, samesite="Lax", secure=True)
        return resp

    @app.route("/auth/logout")
    def auth_logout():
        resp = make_response(redirect("/login"))
        resp.delete_cookie("session")
        return resp

    @app.route("/auth/check")
    def auth_check():
        token = request.cookies.get("session")
        if token:
            email = _verify_session_token(token)
            if email:
                return jsonify({"authenticated": True, "email": email})
        return jsonify({"authenticated": False}), 401

''')
    # Find the right insertion point — after create_app function setup
    # Look for the first route definition and insert before it
    marker = "    @app.route"
    idx = code.find(marker)
    if idx == -1:
        print("ERROR: Could not find insertion point in dashboard.py")
    else:
        # Also need to add imports for redirect, make_response, render_template
        # Check if they're already imported
        if "from flask import" in code:
            for needed in ["redirect", "make_response", "render_template"]:
                if needed not in code.split("from flask import")[1].split("\n")[0]:
                    code = code.replace("from flask import", f"from flask import {needed}, ", 1)

        code = code[:idx] + auth_block + code[idx:]
        with open(dashboard_path, "w") as f:
            f.write(code)
        print("Patched dashboard.py with auth middleware")

print("\nDone! Next: update systemd service with env vars and restart.")
