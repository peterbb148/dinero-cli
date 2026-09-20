"""Bounded OAuth callback collection with no request logging or credential output."""

import hmac
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dinero_cli.config import Settings
from dinero_cli.errors import CLIError
from dinero_cli.storage import atomic_write, read_private

LIMIT = 65536


def authorization_code(raw: bytes, state: str) -> str:
    """Validate URL-encoded callback state before accepting a code or denial."""
    try:
        if len(raw) > LIMIT:
            raise ValueError("Too large")
        fields = parse_qs(
            raw.decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=20,
            errors="strict",
        )
        if any(len(values) != 1 for values in fields.values()):
            raise ValueError("Duplicate parameter")
        received = fields.get("state", [""])[0]
        if not hmac.compare_digest(received.encode(), state.encode()):
            raise ValueError("State mismatch")
    except (ValueError, UnicodeError) as error:
        raise CLIError("Invalid OAuth callback or state mismatch.", code=3) from error
    if "error" in fields:
        raise CLIError("Visma authorization was denied or failed.", code=3)
    code = fields.get("code", [""])[0]
    if not code or any(ord(char) < 32 for char in code):
        raise CLIError("OAuth callback did not contain a valid code.", code=3)
    return code


def begin_browser(url: str, *, no_browser: bool, url_file: Path | None) -> None:
    """Write an explicitly requested private authorization link or open the browser."""
    if no_browser and url_file is None:
        raise CLIError("--no-browser requires --authorization-url-file for the consent link.")
    if url_file is not None:
        atomic_write(url_file, (url + "\n").encode())
    if not no_browser and not webbrowser.open(url):
        raise CLIError(
            "Could not open a browser; use --no-browser with --authorization-url-file.", code=3
        )


def collect(
    settings: Settings,
    url: str,
    state: str,
    *,
    timeout: float,
    no_browser: bool = False,
    url_file: Path | None = None,
    callback_file: Path | None = None,
) -> str:
    """Collect a registered loopback callback or a private file from a registered HTTPS handler.

    External handlers write only the original URL-encoded callback parameters into a private
    file. The collector owns neither an external HTTP server nor server-side TLS credentials.
    File polling is explicit, bounded and does not turn arbitrary errors into retries.
    """
    redirect = urlsplit(settings.redirect_uri)
    if redirect.scheme == "https" and callback_file is None:
        raise CLIError("An HTTPS redirect requires --callback-file from your registered handler.")
    if no_browser and url_file is None:
        raise CLIError("--no-browser requires --authorization-url-file for the consent link.")
    if callback_file is not None:
        if callback_file.exists() or callback_file.is_symlink():
            raise CLIError("Callback file already exists; choose a fresh path for this login.")
        begin_browser(url, no_browser=no_browser, url_file=url_file)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = read_private(callback_file)
            except FileNotFoundError:
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
                continue
            return authorization_code(raw, state)
        raise CLIError("Authorization timed out.", code=3)

    result: list[str | CLIError] = []
    deadline = time.monotonic() + timeout

    class Handler(BaseHTTPRequestHandler):
        """Handle only the registered callback and never log URLs or bodies."""

        def log_message(self, format: str, *args: object) -> None:
            pass

        def send_error(
            self, code: int, message: str | None = None, explain: str | None = None
        ) -> None:
            self.reply(code)

        def setup(self) -> None:
            self.request.settimeout(min(5, max(0.001, deadline - time.monotonic())))
            super().setup()

        def do_GET(self) -> None:
            self.callback("query")

        def do_POST(self) -> None:
            self.callback("form_post")

        def callback(self, mode: str) -> None:
            path = urlsplit(self.path)
            if path.path != redirect.path or self.headers.get("Host") != redirect.netloc:
                self.reply(404)
                return
            if mode != settings.response_mode:
                self.reply(405)
                return
            try:
                if mode == "query":
                    raw = path.query.encode("utf-8")
                else:
                    length = int(self.headers.get("Content-Length", "0"))
                    if (
                        not 0 < length <= LIMIT
                        or self.headers.get_content_type() != "application/x-www-form-urlencoded"
                        or self.headers.get("Transfer-Encoding")
                    ):
                        raise ValueError("Invalid callback body")
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise ValueError("Incomplete callback")
                result.append(authorization_code(raw, state))
            except CLIError as error:
                result.append(error)
            except (OSError, ValueError, UnicodeError):
                result.append(CLIError("Invalid OAuth callback.", code=3))
            self.reply(400 if isinstance(result[-1], CLIError) else 200)

        def reply(self, status: int) -> None:
            content = b"Return to the terminal for the authorization result."
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Callback validation is complete; browser disconnect does not replay it.

    class Server(HTTPServer):
        def handle_error(self, request: object, client_address: object) -> None:
            result.append(CLIError("OAuth callback connection failed.", code=3))

    with Server(("127.0.0.1", redirect.port or 0), Handler) as server:
        begin_browser(url, no_browser=no_browser, url_file=url_file)
        while not result and time.monotonic() < deadline:
            server.timeout = min(0.25, max(0, deadline - time.monotonic()))
            server.handle_request()
    if not result:
        raise CLIError("Authorization timed out.", code=3)
    if isinstance(result[0], CLIError):
        raise result[0]
    return result[0]
