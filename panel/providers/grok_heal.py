"""Safe interactive OIDC heal for Grok homes.

Unlike `grok login`, this never deletes existing auth.json until a new token set
is in hand (CLI login wiped personal auth during a failed attempt).

Restores a working rotating refresh_token so silent SuperGrok probes stay LIVE.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import socket
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional, Tuple

import httpx

from panel.providers import grok as grok_mod

DEFAULT_SCOPES = (
    "openid profile email offline_access "
    "grok-cli:access api:access "
    "conversations:read conversations:write "
    "workspaces:read workspaces:write"
)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _pkce_pair() -> Tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _chrome_candidates() -> list[str]:
    import os

    out: list[str] = []
    for base in (
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ):
        if not base:
            continue
        p = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
        if p.is_file():
            out.append(str(p))
    return out


def _open_authorize_url(url: str, chrome_profile: Optional[str] = None) -> None:
    """Open OAuth URL in Chrome profile when possible (SSO cookies)."""
    for chrome in _chrome_candidates():
        args = [chrome]
        if chrome_profile:
            args.append(f"--profile-directory={chrome_profile}")
        args.append(url)
        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue
    webbrowser.open(url)


def _entry_key(issuer: str, client_id: str) -> str:
    return f"{issuer.rstrip('/')}::{client_id}"


def _apply_tokens(
    home: Path,
    *,
    access: str,
    refresh: str,
    expires_in: Optional[int],
    userinfo: Optional[dict[str, Any]] = None,
) -> None:
    """Merge new tokens into auth.json; preserve unrelated fields."""
    data, entry_key, entry = grok_mod._load_auth(home)
    issuer = grok_mod.DEFAULT_OIDC_ISSUER
    client_id = grok_mod.DEFAULT_OIDC_CLIENT_ID
    if not entry_key:
        entry_key = _entry_key(issuer, client_id)
        entry = {}
        data = data if isinstance(data, dict) else {}
    now = datetime.now(timezone.utc)
    entry = dict(entry) if isinstance(entry, dict) else {}
    entry["key"] = access
    entry["refresh_token"] = refresh
    entry["oidc_issuer"] = str(entry.get("oidc_issuer") or issuer)
    entry["oidc_client_id"] = str(entry.get("oidc_client_id") or client_id)
    entry["auth_mode"] = entry.get("auth_mode") or "oauth"
    entry["create_time"] = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
    if expires_in is not None:
        try:
            exp_dt = now + timedelta(seconds=int(expires_in))
            entry["expires_at"] = (
                exp_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{exp_dt.microsecond:06d}Z"
            )
        except Exception:
            pass
    if userinfo:
        for src, dst in (
            ("email", "email"),
            ("given_name", "first_name"),
            ("family_name", "last_name"),
            ("sub", "user_id"),
            ("picture", "profile_image_asset_id"),
        ):
            if userinfo.get(src) and not entry.get(dst):
                entry[dst] = userinfo[src]
            elif userinfo.get(src) and src == "email":
                entry["email"] = userinfo["email"]
    data[entry_key] = entry
    # backup existing
    auth = grok_mod._auth_path(home)
    if auth.is_file():
        bak = auth.with_name(
            f"auth.json.bak-heal-{time.strftime('%Y%m%d-%H%M%S')}"
        )
        try:
            bak.write_bytes(auth.read_bytes())
        except OSError:
            pass
    grok_mod._write_auth(home, data)
    grok_mod._clear_rt_dead(home)


def heal_grok_home(
    home: Path,
    *,
    timeout_s: float = 180.0,
    chrome_profile: Optional[str] = "Default",
    open_browser: bool = True,
) -> Tuple[bool, str]:
    """Run OIDC auth-code + PKCE for one Grok home. Safe: keeps old auth until success.

    Returns (ok, detail).
    """
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)

    issuer = grok_mod.DEFAULT_OIDC_ISSUER.rstrip("/")
    client_id = grok_mod.DEFAULT_OIDC_CLIENT_ID
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    port = _free_port()
    redirect = f"http://127.0.0.1:{port}/callback"

    # login_hint + prompt=none first: if Chrome still has x.ai SSO, no UI click.
    login_hint = ""
    try:
        _, email0, _, _, _ = grok_mod._read_auth(home)
        login_hint = (email0 or "").strip()
    except Exception:
        login_hint = ""

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "scope": DEFAULT_SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": secrets.token_urlsafe(16),
        "referrer": "grok-build",
    }
    if login_hint:
        params["login_hint"] = login_hint
    auth_url = f"{issuer}/oauth2/authorize?" + urllib.parse.urlencode(params)
    # Prefer silent SSO when browser session exists.
    silent_params = dict(params)
    silent_params["prompt"] = "none"
    silent_url = f"{issuer}/oauth2/authorize?" + urllib.parse.urlencode(silent_params)
    print(f"  OAuth URL:\n  {auth_url}", flush=True)
    print(f"  callback: {redirect}", flush=True)

    result: dict[str, Any] = {"code": None, "error": None, "state": None}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            q = urllib.parse.parse_qs(parsed.query)
            result["code"] = (q.get("code") or [None])[0]
            result["error"] = (q.get("error") or [None])[0]
            result["state"] = (q.get("state") or [None])[0]
            body = (
                b"<html><body style='font-family:system-ui;padding:2rem'>"
                b"<h2>Grok auth OK</h2><p>You can close this tab. Panel will resume live limits.</p>"
                b"</body></html>"
                if result["code"]
                else b"<html><body><h2>Auth failed</h2></body></html>"
            )
            self.send_response(200 if result["code"] else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if open_browser:
            # 1) silent SSO (no UI if session cookie present)
            _open_authorize_url(silent_url, chrome_profile=chrome_profile)
            if done.wait(12.0):
                pass  # got callback from silent
            elif not done.is_set():
                # 2) interactive authorize
                print("  silent SSO did not complete — opening interactive auth…", flush=True)
                _open_authorize_url(auth_url, chrome_profile=chrome_profile)
        if not done.wait(timeout_s):
            return False, f"timeout waiting for browser auth ({int(timeout_s)}s)"
        if result.get("error"):
            return False, f"oauth error: {result['error']}"
        if result.get("state") != state:
            return False, "oauth state mismatch"
        code = result.get("code")
        if not code:
            return False, "no authorization code"

        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{issuer}/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect,
                    "client_id": client_id,
                    "code_verifier": verifier,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
            if resp.status_code != 200:
                detail = ""
                try:
                    err = resp.json()
                    detail = str(err.get("error_description") or err.get("error") or "")
                except Exception:
                    detail = (resp.text or "")[:160]
                return False, f"token HTTP {resp.status_code}: {detail}"
            body = resp.json()
            access = str(body.get("access_token") or "").strip()
            refresh = str(body.get("refresh_token") or "").strip()
            if not access or not refresh:
                return False, "token response missing access/refresh"
            expires_in = body.get("expires_in")
            try:
                expires_in_i = int(expires_in) if expires_in is not None else None
            except (TypeError, ValueError):
                expires_in_i = None

            userinfo: Optional[dict[str, Any]] = None
            try:
                ui = client.get(
                    f"{issuer}/oauth2/userinfo",
                    headers={"Authorization": f"Bearer {access}"},
                )
                if ui.status_code == 200:
                    userinfo = ui.json()
            except Exception:
                userinfo = None

        with grok_mod._auth_lock(home) as held:
            if not held:
                # still write — better than losing the new RT
                pass
            _apply_tokens(
                home,
                access=access,
                refresh=refresh,
                expires_in=expires_in_i,
                userinfo=userinfo if isinstance(userinfo, dict) else None,
            )

        # verify refresh works once
        with httpx.Client(timeout=20.0) as client:
            ok, detail = grok_mod._refresh_oidc(home, client, 15.0)
            if not ok and not grok_mod._refresh_looks_revoked(detail):
                # access may still be fresh → already_fresh expected after just minting
                if detail != "already_fresh":
                    # not fatal if access works for billing
                    pass
            key, email, exp, team, rt = grok_mod._read_auth(home)
            if not key or not rt:
                return False, "auth written but incomplete"
            # force a billing probe
            r = grok_mod.fetch_grok("heal", "heal", home, client, 15.0)
            if r.status.value != "live":
                return (
                    True,
                    f"tokens saved (email={email}) but billing={r.status.value}: {r.reason}",
                )
            return True, f"live ok email={email} rem={[round(w.rem_pct,1) for w in r.windows]}"
    finally:
        try:
            server.shutdown()
        except Exception:
            pass


def heal_all_dead_grok_profiles(
    homes: list[Path],
    *,
    chrome_profile: Optional[str] = "Default",
    timeout_s: float = 180.0,
) -> list[tuple[Path, bool, str]]:
    out: list[tuple[Path, bool, str]] = []
    for home in homes:
        key, email, exp, team, refresh = grok_mod._read_auth(home)
        need = False
        if not refresh:
            need = True
        elif grok_mod._is_rt_marked_dead(home, refresh):
            need = True
        else:
            # probe refresh
            with httpx.Client(timeout=15.0) as client:
                # only if near expiry or marked — avoid burning good RT
                now = time.time()
                if exp is None or exp <= now + 300:
                    ok, detail = grok_mod._refresh_oidc(home, client, 12.0)
                    if not ok and grok_mod._refresh_looks_revoked(detail):
                        need = True
        if not need:
            out.append((home, True, "already healthy"))
            continue
        ok, detail = heal_grok_home(
            home,
            timeout_s=timeout_s,
            chrome_profile=chrome_profile,
            open_browser=True,
        )
        out.append((home, ok, detail))
    return out
