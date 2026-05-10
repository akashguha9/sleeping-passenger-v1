"""
Phase E.1 — Local reverse proxy: 127.0.0.1:80 -> 127.0.0.1:3000 (Next.js).
Standard library only. Advisory frontend mirror. No financial logic.
"""

import http.client
import http.server
import logging
import sys

LISTEN_HOST   = "127.0.0.1"
LISTEN_PORT   = 80
UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 3000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("sleepingpassenger_proxy")

_STRIP_HEADERS = frozenset({"host", "connection", "transfer-encoding", "keep-alive"})


class ProxyHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):  # noqa: N802
        log.info("%s - %s", self.client_address[0], fmt % args)

    def _forward(self):
        method = self.command
        path   = self.path
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length > 0 else None

        headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in _STRIP_HEADERS
        }
        headers["Host"] = f"{UPSTREAM_HOST}:{UPSTREAM_PORT}"

        conn = None
        try:
            conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=30)
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()

            self.send_response(resp.status)
            for hdr, val in resp.getheaders():
                if hdr.lower() in _STRIP_HEADERS:
                    continue
                self.send_header(hdr, val)
            self.end_headers()

            data = resp.read()
            if data:
                self.wfile.write(data)
        except Exception as exc:
            log.error("Upstream error: %s", exc)
            try:
                self.send_error(502, f"Upstream error: {exc}")
            except Exception:
                pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _forward


def main():
    try:
        server = http.server.HTTPServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler)
    except PermissionError:
        print(
            f"\n[sleepingpassenger_proxy] Cannot bind to {LISTEN_HOST}:{LISTEN_PORT}.\n"
            "Port 80 requires Administrator privileges on Windows.\n"
            "\nOptions:\n"
            "  1. Re-run PowerShell as Administrator and start this script again.\n"
            f"  2. Fallback: access the frontend directly at http://localhost:{UPSTREAM_PORT}\n"
        )
        sys.exit(1)
    except OSError as exc:
        print(f"\n[sleepingpassenger_proxy] Cannot start: {exc}\n")
        sys.exit(1)

    log.info(
        "Listening on http://%s:%s -> http://%s:%s",
        LISTEN_HOST, LISTEN_PORT, UPSTREAM_HOST, UPSTREAM_PORT,
    )
    log.info("Advisory frontend mirror. No financial logic.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Proxy stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
