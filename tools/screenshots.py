"""Screenshots of every screen at phone and desktop width, for checking the layout by eye.

  python tools/screenshots.py --base http://127.0.0.1:8010 --out shots/ [--down http://127.0.0.1:8011]

Uses the Edge browser already installed (Playwright channel "msedge"), so no browser is downloaded. Signs in
through the API as each practice account (password from LEAKTRACE_DEMO_PASSWORD) and opens each screen.
--down points at a server whose FalkorDB is unreachable, to capture the error states.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402,F401  (loads .env)

SIZES = {"phone": {"width": 390, "height": 844}, "desktop": {"width": 1440, "height": 900}}


def token(base: str, user: str) -> dict:
    tenant = httpx.get(f"{base}/public/info").json()["demo_tenant"]
    r = httpx.post(f"{base}/auth/login", json={"tenant": tenant, "username": user,
                                               "password": os.environ["LEAKTRACE_DEMO_PASSWORD"]})
    r.raise_for_status()
    out = r.json()
    return {"token": out["token"], "who": {"user": user, "role": out["role"], "tenant": out["tenant"]}}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--down")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    op = token(a.base, "operator1")
    probs = httpx.get(f"{a.base}/problems", headers={"Authorization": f"Bearer {op['token']}"}).json()
    waiting = next((x["id"] for x in probs if x["status"] == "open"), probs[0]["id"])
    done = next((x["id"] for x in probs if x["status"] != "open"), waiting)
    codes = [c for x in probs for c in httpx.get(f"{a.base}/problems/{x['id']}",
                                                 headers={"Authorization": f"Bearer {op['token']}"}).json()["reports"]]
    code = codes[0]
    shots = [
        ("1a-report", None, "#/report", None),
        ("1b-track", None, f"#/track/{code}", None),
        ("login", None, "#/login", None),
        ("2-problems-needs-ok", "operator1", f"#/problems/{waiting}", None),
        ("2-problems-handled", "operator1", f"#/problems/{done}", None),
        ("3-jobs", "tech1", "#/jobs", None),
        ("4-auto-settings", "manager1", "#/auto", None),
        ("4-auto-review", "manager1", "#/auto", "To review"),
        ("4-auto-learned", "manager1", "#/auto", "What we've learned"),
        ("5-who-did-what", "operator1", f"#/who/{waiting}", None),
        ("5b-ask-leaktrace", "operator1", f"#/who/{waiting}", "Why did we avoid valve V-09?"),
        ("6-how-it-works", None, "#/how-it-works", "Run this on the live map"),
    ]
    tokens = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        for size, vp in SIZES.items():
            for name, user, hash_, click in shots:
                ctx = browser.new_context(viewport=vp, device_scale_factor=1)
                if user:
                    tokens.setdefault(user, token(a.base, user))
                    t = tokens[user]
                    ctx.add_init_script(f"localStorage.setItem('leaktrace.token', {json.dumps(t['token'])});"
                                        f"localStorage.setItem('leaktrace.who', {json.dumps(json.dumps(t['who']))});")
                page = ctx.new_page()
                page.goto(f"{a.base}/{hash_}")
                page.wait_for_load_state("networkidle")
                target = click and page.get_by_role("tab", name=click).or_(page.get_by_role("button", name=click))
                if target and target.count():  # an example question is shown only before the first one is asked
                    target.first.click()
                    page.wait_for_load_state("networkidle")
                page.wait_for_timeout(600)
                page.screenshot(path=str(out / f"{name}-{size}.png"), full_page=True)
                ctx.close()
            if a.down:
                ctx = browser.new_context(viewport=vp)
                page = ctx.new_page()
                page.goto(f"{a.down}/#/how-it-works")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(600)
                page.screenshot(path=str(out / f"6-how-it-works-down-{size}.png"), full_page=True)
                ctx.close()
        browser.close()
    print(json.dumps(sorted(x.name for x in out.glob("*.png"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
