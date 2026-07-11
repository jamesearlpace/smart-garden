import json
import subprocess
from playwright.sync_api import sync_playwright

BASE = "https://sprinklers.savagepace.com"
token = subprocess.check_output(
    ["ssh", "acer", "sudo bash ~/smart-garden-server/tools/authcookie.sh"],
    text=True,
).strip()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 390, "height": 844})
    context.add_cookies([{
        "name": "session", "value": token, "domain": "sprinklers.savagepace.com",
        "path": "/", "httpOnly": True, "secure": True, "sameSite": "Strict",
    }])

    page = context.new_page()
    page.goto(BASE + "/water-usage", wait_until="networkidle")
    page.locator("#sub").wait_for(state="visible")
    bucket_text = page.locator("#sub").inner_text()
    assert "1.5 min (90 sec)" in bucket_text, bucket_text
    page.locator("#auditBtn").click()
    page.locator("#auditPanel .auditcheck").filter(has_text="Reconciliation").wait_for()
    assert "boundary/carry adjustment" in page.locator("#auditPanel").inner_text()

    page.add_init_script("localStorage.setItem('cam_focus_v2', JSON.stringify({roiLocked:true,rotationLocked:true}));")
    page.goto(BASE + "/cam/focus", wait_until="networkidle")
    page.locator("#roiLockBtn").wait_for()
    assert page.locator("#roiLockBtn").inner_text() == "Unlock ROI"
    assert page.locator("#rotationLockBtn").inner_text() == "Unlock rotation"
    assert page.locator("#roiX").is_disabled()
    assert page.locator("#rotateDeg").is_disabled()
    assert page.locator("#mtnBar").evaluate("el => el.scrollLeft") == 0

    guest = browser.new_context()
    login = guest.new_page()
    login.goto(BASE + "/login?error=invalid_token&next=%2Fcam%2Freading%2F1")
    assert login.locator("#error").get_attribute("role") == "alert"
    source_next = login.locator("body").evaluate("() => document.documentElement.innerHTML.includes('const nextPath = \\\"/cam/reading/1\\\"')")
    assert source_next
    print(json.dumps({"water_usage": "pass", "focus": "pass", "login": "pass"}))
    browser.close()
