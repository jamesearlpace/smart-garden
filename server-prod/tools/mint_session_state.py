#!/usr/bin/env python3
"""Mint a Playwright storage-state with a valid smart-garden session cookie.

Runs ON the server (where SESSION_SECRET + allowed_emails live). Writes the
storage-state JSON to the given path. Prints only a short confirmation, never
the secret or the token.
"""
import json, hmac, hashlib, time, subprocess, os, sys

BASE = "/home/jamesearlpace/smart-garden-server"


def service_secret():
    try:
        pid = subprocess.check_output(
            ["systemctl", "show", "smart-garden-server", "-p", "MainPID", "--value"]
        ).decode().strip()
        raw = open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
        env = dict(e.split(b"=", 1) for e in raw if b"=" in e)
        return env.get(b"SESSION_SECRET", b"smartgarden2026default").decode()
    except Exception:
        return os.environ.get("SESSION_SECRET", "smartgarden2026default")


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/auth-state.json"
    secret = service_secret()
    emails = json.load(open(os.path.join(BASE, "allowed_emails.json")))
    email = emails[0]["email"].lower()
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{email}|{ts}".encode(), hashlib.sha256).hexdigest()
    token = f"{email}|{ts}|{sig}"
    exp = int(time.time()) + 86400 * 30
    cookie = {
        "name": "session", "value": token,
        "domain": "sprinklers.savagepace.com", "path": "/",
        "expires": exp, "httpOnly": True, "secure": True, "sameSite": "Lax",
    }
    state = {"cookies": [cookie], "origins": []}
    with open(out_path, "w") as f:
        json.dump(state, f)
    print(f"OK wrote storage-state for {email} -> {out_path}")


if __name__ == "__main__":
    main()
