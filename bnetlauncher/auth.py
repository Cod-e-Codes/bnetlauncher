"""
Battle.net OAuth2 authentication.

Flow:
1. Open browser to Blizzard OAuth authorization endpoint.
2. Local redirect server catches the auth code.
3. Exchange code for access + refresh tokens via token endpoint.
4. Tokens persisted in config.

Blizzard OAuth2 documentation:
https://develop.battle.net/documentation/guides/using-oauth

WSL2: the callback server binds to 0.0.0.0 so Windows (where the browser runs)
can reach the listener via localhost forwarding. Use redirect URI
http://localhost:6547/callback in the developer portal.
"""
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

from bnetlauncher.config import get_config

OAUTH_BASE = "https://oauth.battle.net"
AUTH_URL = f"{OAUTH_BASE}/authorize"
TOKEN_URL = f"{OAUTH_BASE}/token"
REDIRECT_URI = "http://localhost:6547/callback"
REDIRECT_PORT = 6547
# Listen on all interfaces so WSL2 receives Windows→localhost forwarded traffic.
LISTEN_HOST = "0.0.0.0"

SCOPES = "openid wow.profile sc2.profile"

_USER_AGENT = "bnetlauncher/1.0 (+https://github.com/Cod-e-Codes/bnetlauncher)"

# Cached: False = cannot run Windows .exe from this WSL (interop off / Exec format error).
_wsl_windows_interop: Optional[bool] = None


def _is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="ignore") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def _windows_fs_roots() -> list[str]:
    """Mounted Windows directories under /mnt (WSL), de-duplicated by realpath."""
    roots: list[str] = []
    seen: set[str] = set()
    for raw in ("/mnt/c/Windows", "/mnt/c/WINDOWS", "/mnt/c/windows"):
        if not os.path.isdir(raw):
            continue
        try:
            key = os.path.realpath(raw).lower()
        except OSError:
            key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(raw)
    return roots


def _wsl_windows_interop_available() -> bool:
    """
    True if WSL can execute a trivial Windows program (interop enabled).
    If False, every /mnt/c/.../*.exe fails with Exec format error from Linux.
    """
    global _wsl_windows_interop
    if not _is_wsl():
        return False
    if _wsl_windows_interop is not None:
        return _wsl_windows_interop

    whoami = "/mnt/c/Windows/System32/whoami.exe"
    ok = False
    if os.path.isfile(whoami):
        try:
            p = subprocess.run(
                [whoami],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
            # ENOEXEC / missing interop often surfaces as 126/127, not always OSError.
            ok = p.returncode == 0
        except OSError:
            ok = False
        except subprocess.TimeoutExpired:
            ok = True
    _wsl_windows_interop = ok
    return ok


def print_browser_open_hints() -> None:
    """If WSL cannot run Windows .exe helpers, explain how to fix or use a Linux browser."""
    if not _is_wsl() or _wsl_windows_interop_available():
        return
    print(
        "bnetlauncher: WSL cannot run Windows programs (rundll32, PowerShell, etc.) — "
        'usually "Exec format error" when interop is disabled.\n'
        "  Enable it: add under /etc/wsl.conf:\n"
        "    [interop]\n"
        "    enabled=true\n"
        "  Then in Windows (PowerShell or cmd): wsl --shutdown  — and reopen Ubuntu.\n"
        "  Or install a browser in WSL: sudo apt install firefox\n",
        file=sys.stderr,
        flush=True,
    )


def _open_url_via_windows_host(url: str) -> bool:
    """
    Hand a URL to Windows from WSL. Tries several launchers; avoids relying on
    Linux webbrowser/xdg when the goal is the Windows default browser.

    Uses start_new_session=False — WSL interop has been observed to fail for
    some Windows executables when start_new_session=True.
    """
    roots = _windows_fs_roots()
    if not roots:
        return False

    ps_sq = url.replace("'", "''")
    attempts: list[list[str]] = []
    for root in roots:
        sys32 = os.path.join(root, "System32")
        ps = os.path.join(sys32, "WindowsPowerShell", "v1.0", "powershell.exe")
        r32 = os.path.join(sys32, "rundll32.exe")
        wow = os.path.join(root, "SysWOW64", "rundll32.exe")
        cmd = os.path.join(sys32, "cmd.exe")
        explorer = os.path.join(root, "explorer.exe")

        attempts.append([r32, "url.dll,FileProtocolHandler", url])
        if wow != r32:
            attempts.append([wow, "url.dll,FileProtocolHandler", url])
        attempts.append(
            [
                ps,
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                f"Start-Process -FilePath '{ps_sq}'",
            ]
        )
        attempts.append(
            [
                ps,
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                f"Invoke-Item -LiteralPath '{ps_sq}'",
            ]
        )
        attempts.append([cmd, "/c", "start", "", url])
        attempts.append([explorer, url])

    popen_kw = dict(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=False,
    )
    for argv in attempts:
        exe = argv[0]
        if not os.path.isfile(exe):
            continue
        try:
            subprocess.Popen(argv, **popen_kw)
            return True
        except OSError:
            continue
    return False


def _open_url_linux_desktop(url: str, popen_kw: dict) -> bool:
    """Try GTK/standard Linux handlers and common browser binaries."""
    handlers: list[list[str]] = []
    xdg = shutil.which("xdg-open")
    if xdg:
        handlers.append([xdg, url])
    gio = shutil.which("gio")
    if gio:
        handlers.append([gio, "open", url])
    for name in (
        "firefox",
        "firefox-esr",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "microsoft-edge-stable",
    ):
        b = shutil.which(name)
        if b:
            handlers.append([b, url])

    for argv in handlers:
        try:
            subprocess.Popen(argv, **popen_kw)
            return True
        except OSError:
            continue
    return False


def open_default_browser(url: str) -> bool:
    """
    Open a URL in the user's default browser. On WSL with Windows interop,
    tries the Windows host first. Otherwise uses webbrowser, wslview, and
    Linux desktop helpers (xdg-open, gio, firefox, chromium, …).
    Only webbrowser.open() returning True counts as success (None is not OK).
    """
    popen_kw = dict(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=False,
    )

    if _is_wsl() and _wsl_windows_interop_available() and _open_url_via_windows_host(url):
        return True

    try:
        if webbrowser.open(url) is True:
            return True
    except (OSError, TypeError, webbrowser.Error):
        pass

    wslview = shutil.which("wslview")
    if wslview:
        try:
            subprocess.Popen([wslview, url], **popen_kw)
            return True
        except OSError:
            pass

    if _open_url_linux_desktop(url, popen_kw):
        return True

    return False


def _oauth_creds(cfg) -> tuple[str, str]:
    cid = (cfg.get("bnet_client_id") or "").strip()
    csec = (cfg.get("bnet_client_secret") or "").strip()
    return cid, csec


def _make_callback_handler(
    expected_state: str,
    done_event: threading.Event,
    result: dict,
):
    """Factory: per-auth-run state (thread-safe enough for single-threaded serve)."""

    class _CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)

            if "code" in params:
                got_state = (params.get("state") or [None])[0]
                if got_state != expected_state:
                    result["error"] = (
                        "OAuth state mismatch (try signing in again). "
                        "If this persists, another app may be using the same port."
                    )
                    body = (
                        b"<html><body><h2>Sign-in error</h2>"
                        b"<p>State check failed. Close this tab and retry from the launcher.</p>"
                        b"</body></html>"
                    )
                else:
                    result["code"] = params["code"][0]
                    body = (
                        b"<html><body><h2>Authentication successful.</h2>"
                        b"<p>You can close this tab.</p></body></html>"
                    )
            elif "error" in params:
                err = (params.get("error") or ["unknown"])[0]
                desc = (params.get("error_description") or [err])[0]
                if isinstance(desc, str) and desc.startswith("["):
                    desc = err
                result["error"] = f"{err}: {desc}"
                body = (
                    b"<html><body><h2>Authentication failed</h2>"
                    b"<p>Return to the launcher for details.</p></body></html>"
                )
            else:
                body = b"<html><body><p>Waiting for sign-in...</p></body></html>"

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

            if result.get("code") or result.get("error"):
                done_event.set()

        def log_message(self, *args) -> None:  # silence access logs
            pass

    return _CallbackHandler


class AuthError(Exception):
    pass


class BNetAuth:
    def __init__(self) -> None:
        self.cfg = get_config()

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def is_authenticated(self) -> bool:
        token = self.cfg.get("access_token")
        expiry = self.cfg.get("token_expiry", 0)
        return bool(token) and time.time() < expiry - 60

    def get_access_token(self) -> Optional[str]:
        if self.is_authenticated():
            return self.cfg.get("access_token")
        return None

    def clear_tokens(self) -> None:
        self.cfg.set("access_token", "")
        self.cfg.set("token_expiry", 0)

    # ------------------------------------------------------------------
    # Authorization Code Flow
    # ------------------------------------------------------------------

    def start_auth_flow(
        self,
        on_success: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        """
        Non-blocking: spawns a thread that opens the browser and waits for
        the OAuth callback. Calls on_success(access_token) or on_error(msg).
        """
        client_id, _ = _oauth_creds(self.cfg)
        if not client_id:
            on_error(
                "No Battle.net client ID configured.\n"
                "Register an application at https://develop.battle.net "
                "and enter the credentials in Settings."
            )
            return

        state = secrets.token_urlsafe(16)
        params = {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
        }
        auth_url = AUTH_URL + "?" + urllib.parse.urlencode(params)

        thread = threading.Thread(
            target=self._auth_thread,
            args=(auth_url, state, on_success, on_error),
            daemon=True,
        )
        thread.start()

    def _auth_thread(
        self,
        auth_url: str,
        expected_state: str,
        on_success: Callable,
        on_error: Callable,
    ) -> None:
        done = threading.Event()
        result: dict = {}
        server: HTTPServer | None = None

        try:
            handler_cls = _make_callback_handler(expected_state, done, result)
            server = HTTPServer((LISTEN_HOST, REDIRECT_PORT), handler_cls)
        except OSError as e:
            on_error(
                f"Could not listen on port {REDIRECT_PORT}: {e}\n"
                "Close any other app using that port, or sign out of other "
                "Battle.net OAuth tools using the same redirect URL."
            )
            return

        server.timeout = 1.0

        try:
            # Brief delay so the socket is definitely accepting (helps WSL/browser races).
            time.sleep(0.15)
            if not open_default_browser(auth_url):
                print("Open this URL in a browser to sign in:\n" + auth_url, file=sys.stderr)
                print_browser_open_hints()
                # Keep the callback server running — user may paste the URL manually.

            deadline = time.time() + 120
            while not done.is_set() and time.time() < deadline:
                server.handle_request()

            if result.get("error"):
                on_error(result["error"])
                return

            if not result.get("code"):
                on_error(
                    "Authentication timed out (no callback received).\n\n"
                    "If you use WSL: keep using http://localhost:6547/callback in the "
                    "Battle.net app settings, ensure Windows can forward localhost to WSL "
                    "(Windows 11 / recent WSL2), and try signing in again.\n"
                    "If the browser shows 'connection refused', run the launcher in "
                    "native Linux or fix WSL localhost forwarding."
                )
                return

            try:
                token_data = self._exchange_code(result["code"])
                self._store_tokens(token_data)
                on_success(token_data["access_token"])
            except AuthError as e:
                on_error(str(e))
        except Exception as e:  # noqa: BLE001
            on_error(f"Unexpected error during sign-in: {e}")
        finally:
            if server is not None:
                try:
                    server.server_close()
                except OSError:
                    pass

    def _exchange_code(self, code: str) -> dict:
        client_id, client_secret = _oauth_creds(self.cfg)
        if not client_secret:
            raise AuthError(
                "Client secret is empty. Paste it in Settings → Authentication and save."
            )

        post_data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
        }).encode()

        req = urllib.request.Request(TOKEN_URL, data=post_data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("User-Agent", _USER_AGENT)

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                err_body = json.loads(raw)
                msg = (
                    err_body.get("error_description")
                    or err_body.get("error")
                    or raw
                )
            except json.JSONDecodeError:
                msg = raw or str(e)
            raise AuthError(f"Token exchange failed ({e.code}): {msg}") from e
        except urllib.error.URLError as e:
            raise AuthError(f"Token exchange failed (network): {e}") from e

        if "access_token" not in data:
            raise AuthError(f"No access_token in response: {data}")

        return data

    # ------------------------------------------------------------------
    # Client Credentials Flow (for API calls that don't need user identity)
    # ------------------------------------------------------------------

    def fetch_client_token(self) -> Optional[str]:
        """
        Fetches a client-credentials token for Blizzard Game Data APIs.
        Does not require user interaction.
        """
        client_id, client_secret = _oauth_creds(self.cfg)
        if not client_id or not client_secret:
            return None

        region = self.cfg.get("bnet_region", "us")
        token_url = f"https://{region}.battle.net/oauth/token"

        post_data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }).encode()

        req = urllib.request.Request(token_url, data=post_data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("User-Agent", _USER_AGENT)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            self._store_tokens(data)
            return data.get("access_token")
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _store_tokens(self, data: dict) -> None:
        self.cfg.set("access_token", data.get("access_token", ""))
        expires_in = int(data.get("expires_in", 86400))
        self.cfg.set("token_expiry", int(time.time()) + expires_in)
