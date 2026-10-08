"""Serve an anonymous native Limn comparison without opening an instance or manuscript.

Only an explicit static allowlist is served on loopback. An optional --public-host
accepts one exact tailnet HTTPS authority when a local Tailscale Serve proxy is used.
Browser API effects stay in native-fixture.js; the server refuses mutations and API reads.
Run with ``uv run python tools/ux-poc/serve.py --port 5174`` from the repository.
"""

import argparse
import json
import mimetypes
import re
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from limn.viewer.assemble import default_pdfjs_dir, default_pretendard_dir, read_viewer, run_page


@dataclass(frozen=True)
class PublicHost:
    """One canonical tailnet DNS authority with an explicit HTTPS port.

    This grants anonymous demo access only; it establishes no production identity.
    Construction rejects URLs, wildcard hosts, ambiguous ports, and foreign DNS suffixes.
    """

    authority: str

    def __post_init__(self) -> None:
        """Reject anything outside lowercase DNS labels, .ts.net, and port 1 through 65535."""
        pattern = r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+ts\.net:([1-9][0-9]{0,4})"
        match = re.fullmatch(pattern, self.authority) if len(self.authority) <= 259 else None
        if match is None or len(self.authority.rpartition(":")[0]) > 253 or int(match.group(1)) > 65535:
            raise ValueError("public host must be a lowercase .ts.net DNS name with an explicit port from 1 to 65535")


def parse_public_host(value: str) -> PublicHost:
    """Convert one CLI authority into a validated demo capability or an argparse error."""
    try:
        return PublicHost(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def static_assets(directory: Path) -> dict[str, tuple[bytes, str]]:
    """Load only authored demo assets and packaged font/PDF.js leaf files.

    No caller-controlled path reaches a filesystem read. A missing required demo
    asset fails startup; native.js and native.css are optional during construction.
    """
    assets = {}
    media = {".mjs": "text/javascript", ".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2"}
    for route, name in {
        "/native-fixture.js": "native-fixture.js",
        "/sample.pdf": "sample.pdf",
        "/pdf": "sample.pdf",
        "/sample.png": "sample.png",
        "/sample-2.png": "sample-2.png",
        "/sample-3.png": "sample-3.png",
        "/native-pdf.mjs": "native-pdf.mjs",
        "/reading.json": "native-reading.json",
    }.items():
        file = directory / name
        assets[route] = (
            file.read_bytes(),
            media.get(file.suffix) or mimetypes.guess_type(name)[0] or "application/octet-stream",
        )
    for library, root, suffixes in (
        ("pdfjs", default_pdfjs_dir(), {".mjs"}),
        ("pretendard", default_pretendard_dir(), {".css", ".woff2"}),
    ):
        for file in root.iterdir():
            if file.is_file() and not file.is_symlink() and file.suffix in suffixes:
                assets[f"/vendor/{library}/{file.name}"] = (file.read_bytes(), media[file.suffix])
    for build in ("demo-build-1", "demo-build-2"):
        for page in range(1, 4):
            asset = "/sample.png" if page == 1 else f"/sample-{page}.png"
            assets[f"/pages/{build}/page-{page}.png"] = assets[asset]
    return assets


def demo_page(template: str, reading: bytes, proposal: bool) -> bytes:
    """Assemble the real viewer and add only the isolated fixture and proposal.

    The fixture precedes every original script so preferences and API requests
    cannot touch a real instance. The baseline receives no proposal CSS or JS.
    """
    page = run_page(template, "샘플 원고", "#718096", "ko")
    data = json.dumps(json.loads(reading), ensure_ascii=False).replace("</", "<\\/")
    injection = f'<script>window.LimnDemoReading={data};</script><script src="/native-fixture.js"></script>'
    page = page.replace("<script>", injection + "<script>", 1)
    if proposal:
        page = page.replace("</head>", '<link rel="stylesheet" href="/native.css"></head>', 1)
        page = page.replace("</body>", '<script src="/native.js"></script></body>', 1)
    return page.encode("utf-8")


def make_handler(
    directory: Path,
    pages: Mapping[str, bytes],
    assets: Mapping[str, tuple[bytes, str]],
    port: int,
    public_host: PublicHost | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Bind closed resources and optional exact tailnet authority to a loopback handler.

    Every route checks Host first; no request can select a file or write method.
    The two proposal leaves are read by fixed name to support bounded iteration.
    The caller may grant one validated public Host for its trusted local proxy.
    """
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if public_host is not None:
        allowed_hosts.add(public_host.authority)

    class DemoHandler(BaseHTTPRequestHandler):
        """Serve allowlisted anonymous resources; reject all other effects."""

        def log_message(self, format: str, *args: object) -> None:
            """Keep routine requests quiet and avoid logging URL query payloads."""

        def respond(self, status: int, body: bytes, media: str, head: bool = False) -> None:
            """Write a bounded asset response with no cache and no MIME sniffing."""
            self.send_response(status)
            self.send_header("Content-Type", media)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head and self.command != "HEAD":
                with suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(body)

        def allowed_host(self) -> bool:
            """Require a single exact allowed Host before any resource or method is handled."""
            hosts = self.headers.get_all("Host", [])
            return len(hosts) == 1 and hosts[0] in allowed_hosts

        def do_GET(self) -> None:
            """Serve the viewer variant or an exact allowlisted static route."""
            if not self.allowed_host():
                self.respond(403, b"Host refused", "text/plain")
                return
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                variant = parse_qs(parsed.query).get("variant", ["proposal"])
                if len(variant) != 1 or variant[0] not in pages:
                    self.respond(400, b"Unknown comparison variant", "text/plain")
                    return
                self.respond(200, pages[variant[0]], "text/html; charset=utf-8", self.command == "HEAD")
                return
            resource = assets.get(parsed.path)
            if parsed.path in {"/native.js", "/native.css"}:
                file = directory / parsed.path[1:]
                if file.is_file() and not file.is_symlink():
                    resource = (file.read_bytes(), "text/javascript" if file.suffix == ".js" else "text/css")
            if resource is None:
                self.respond(404, b"Resource not in demo allowlist", "text/plain")
                return
            self.respond(200, resource[0], resource[1], self.command == "HEAD")

        def do_HEAD(self) -> None:
            """Use the same allowlist as GET without returning an asset body."""
            self.do_GET()

        def do_POST(self) -> None:
            """Check Host, then refuse every mutation; demo effects stay in browser memory."""
            if not self.allowed_host():
                self.respond(403, b"Host refused", "text/plain")
                return
            self.respond(405, b"Demo HTTP mutations are disabled", "text/plain")

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

    return DemoHandler


def main() -> None:
    """Parse the optional proxy authority, bind only loopback, and close on interruption."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5174)
    parser.add_argument(
        "--public-host",
        type=parse_public_host,
        metavar="DNS:PORT",
        help="allow one exact lowercase .ts.net HTTPS authority for a local Tailscale Serve proxy",
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    directory = Path(__file__).resolve().parent
    assets = static_assets(directory)
    files = read_viewer()
    for route, icon in files.icons.items():
        assets[route] = (icon.body, icon.content_type)
    assets["/sw.js"] = (files.service_worker.encode("utf-8"), "text/javascript")
    pages = {
        name: demo_page(files.template, assets["/reading.json"][0], name == "proposal")
        for name in ("current", "proposal")
    }
    with ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_handler(directory, pages, assets, args.port, args.public_host)
    ) as server:
        print(f"Native Limn comparison: http://127.0.0.1:{args.port}/", flush=True)
        with suppress(KeyboardInterrupt):
            server.serve_forever()


if __name__ == "__main__":
    main()
