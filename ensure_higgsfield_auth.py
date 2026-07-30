#!/usr/bin/env python3
"""Ensure Higgsfield CLI auth without interactive login.

Priority:
1. HIGGSFIELD_CREDENTIALS / HIGGSFIELD_CREDENTIALS_FILE → inject credentials.json
2. Existing credentials that still work (CLI refresh_token)
3. Playwright OAuth: spawn `higgsfield auth login`, capture authorize URL via
   fake BROWSER, sign in with HIGGSFIELD_EMAIL + HIGGSFIELD_PASSWORD

Official CLI has no long-lived API key for Marketing Studio yet
(see higgsfield-ai/cli#47). This bridges the gap for automation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DEFAULT_CREDS = Path.home() / ".config" / "higgsfield" / "credentials.json"
CALLBACK_PORT = int(os.getenv("HIGGSFIELD_OAUTH_PORT", "8765"))


def credentials_path() -> Path:
    override = os.getenv("HIGGSFIELD_CREDENTIALS_PATH")
    return Path(override).expanduser() if override else DEFAULT_CREDS


def which_higgsfield() -> str:
    path = shutil.which("higgsfield")
    if not path:
        raise SystemExit(
            "higgsfield CLI not found. Install: npm i -g @higgsfield/cli"
        )
    return path


def ensure_workspace() -> None:
    workspace_id = os.getenv("HIGGSFIELD_WORKSPACE_ID", "").strip()
    if not workspace_id:
        return
    hf = which_higgsfield()
    proc = subprocess.run(
        [hf, "workspace", "set", workspace_id],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"Failed to set workspace {workspace_id}:\n{proc.stderr or proc.stdout}"
        )
    print(f"Workspace set → {workspace_id}")


def account_ok() -> bool:
    try:
        proc = subprocess.run(
            [which_higgsfield(), "account", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0:
            return True
        err = (proc.stderr or proc.stdout or "").lower()
        # Token works; only workspace selection is missing
        if "no workspace selected" in err:
            return True
        return False
    except (OSError, subprocess.TimeoutExpired):
        return False


def write_credentials(raw: str | bytes | dict) -> Path:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(raw, dict):
        data = raw
    else:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        data = json.loads(text)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"Wrote credentials → {path}")
    return path


def inject_from_env() -> bool:
    file_path = os.getenv("HIGGSFIELD_CREDENTIALS_FILE")
    raw = os.getenv("HIGGSFIELD_CREDENTIALS")
    if file_path:
        src = Path(file_path).expanduser()
        if not src.exists():
            raise SystemExit(f"HIGGSFIELD_CREDENTIALS_FILE not found: {src}")
        write_credentials(src.read_text(encoding="utf-8"))
        return True
    if raw and raw.strip():
        write_credentials(raw.strip())
        return True
    return False


def playwright_login() -> None:
    email = os.getenv("HIGGSFIELD_EMAIL", "").strip()
    password = os.getenv("HIGGSFIELD_PASSWORD", "").strip()
    if not email or not password:
        raise SystemExit(
            "Need headless auth credentials.\n"
            "Set in .env one of:\n"
            "  HIGGSFIELD_CREDENTIALS='{...credentials.json...}'\n"
            "  HIGGSFIELD_CREDENTIALS_FILE=/path/to/credentials.json\n"
            "  HIGGSFIELD_EMAIL=... + HIGGSFIELD_PASSWORD=...\n"
        )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "playwright not installed. Run:\n"
            "  pip install playwright && playwright install chromium"
        ) from exc

    hf = which_higgsfield()
    with tempfile.TemporaryDirectory(prefix="hf-oauth-") as tmp:
        tmp_path = Path(tmp)
        url_file = tmp_path / "authorize_url.txt"
        browser_shim = tmp_path / "browser.sh"
        browser_shim.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$*" > "{url_file}"\n',
            encoding="utf-8",
        )
        browser_shim.chmod(0o755)

        env = os.environ.copy()
        env["BROWSER"] = str(browser_shim)
        # Some CLIs honor these instead of BROWSER
        env["PATH"] = f"{tmp_path}:{env.get('PATH', '')}"

        print(
            f"Starting OAuth login on :{CALLBACK_PORT} "
            f"(Playwright will complete Clerk sign-in)..."
        )
        login_proc = subprocess.Popen(
            [hf, "auth", "login", "--port", str(CALLBACK_PORT)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        authorize_url = None
        deadline = time.time() + 45
        while time.time() < deadline:
            if url_file.exists():
                content = url_file.read_text(encoding="utf-8").strip()
                # BROWSER may receive: open "URL" or just URL
                for part in content.replace("'", " ").replace('"', " ").split():
                    if part.startswith("http://") or part.startswith("https://"):
                        authorize_url = part
                        break
                if authorize_url:
                    break
            if login_proc.poll() is not None:
                out = login_proc.stdout.read() if login_proc.stdout else ""
                raise SystemExit(
                    f"higgsfield auth login exited early ({login_proc.returncode}):\n{out}"
                )
            time.sleep(0.25)

        if not authorize_url:
            login_proc.kill()
            raise SystemExit(
                "Timed out waiting for OAuth authorize URL. "
                "CLI may not honor BROWSER on this platform."
            )

        print(f"Authorize URL captured ({authorize_url[:60]}...)")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(authorize_url, wait_until="domcontentloaded", timeout=90_000)

            # Clerk hosted sign-in: email → continue → password → continue
            # Selectors are resilient; Clerk markup changes occasionally.
            email_selectors = [
                'input[name="identifier"]',
                'input[name="emailAddress"]',
                'input[type="email"]',
                'input[autocomplete="username"]',
            ]
            password_selectors = [
                'input[name="password"]',
                'input[type="password"]',
                'input[autocomplete="current-password"]',
            ]

            email_el = None
            for sel in email_selectors:
                loc = page.locator(sel).first
                try:
                    loc.wait_for(state="visible", timeout=15_000)
                    email_el = loc
                    break
                except Exception:
                    continue
            if email_el is None:
                browser.close()
                login_proc.kill()
                raise SystemExit(
                    "Could not find Clerk email field. "
                    "Account may require Google SSO (not headless-friendly)."
                )

            email_el.fill(email)
            # Click continue if present
            for label in ("Continue", "Next", "continue"):
                btn = page.get_by_role("button", name=label)
                if btn.count():
                    btn.first.click()
                    break
            else:
                page.keyboard.press("Enter")

            password_el = None
            for sel in password_selectors:
                loc = page.locator(sel).first
                try:
                    loc.wait_for(state="visible", timeout=20_000)
                    password_el = loc
                    break
                except Exception:
                    continue
            if password_el is None:
                browser.close()
                login_proc.kill()
                raise SystemExit(
                    "Password field not found after email step. "
                    "If this account uses magic-link/Google only, use "
                    "HIGGSFIELD_CREDENTIALS from a one-time manual login instead."
                )

            password_el.fill(password)
            for label in ("Continue", "Sign in", "Log in", "continue"):
                btn = page.get_by_role("button", name=label)
                if btn.count():
                    btn.first.click()
                    break
            else:
                page.keyboard.press("Enter")

            # Wait until CLI finishes callback exchange
            try:
                login_proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                browser.close()
                login_proc.kill()
                raise SystemExit("OAuth callback timed out after password submit")

            browser.close()

        out = login_proc.stdout.read() if login_proc.stdout else ""
        if login_proc.returncode != 0:
            raise SystemExit(
                f"higgsfield auth login failed ({login_proc.returncode}):\n{out}"
            )
        print(out.strip() or "OAuth login completed.")


def dump_credentials_hint() -> None:
    path = credentials_path()
    if path.exists():
        print(
            f"Tip: persist for CI with\n"
            f"  export HIGGSFIELD_CREDENTIALS=\"$(cat {path})\"\n"
            f"or copy into .env as HIGGSFIELD_CREDENTIALS=..."
        )


def main() -> int:
    force = "--force" in sys.argv

    if inject_from_env():
        if account_ok():
            ensure_workspace()
            print("Auth OK (injected credentials).")
            return 0
        print("Injected credentials did not authenticate; trying refresh/login...")

    if not force and account_ok():
        ensure_workspace()
        print("Auth OK (existing session / refresh_token).")
        return 0

    playwright_login()

    if not account_ok():
        raise SystemExit("Login finished but `higgsfield account status` still fails.")

    ensure_workspace()
    print("Auth OK.")
    dump_credentials_hint()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
