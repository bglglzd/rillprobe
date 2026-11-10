"""Task-owned loopback HTTP simulation. It never performs model inference."""

import json
import threading
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .fixtures import CASES, SEEDS, rerank_payload, stream_wire


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > 1024 * 1024:
            self.send_error(413)
            return
        body = self.rfile.read(size)
        case = CASES.get(self.headers.get("X-Rillprobe-Case"))
        parts = self.path.strip("/").split("/")
        if case is None or len(parts) < 2 or parts[0] not in ("direct", "gateway"):
            self.send_error(404)
            return
        route = parts[0]
        broken = route == "gateway" and self.server.broken and case["id"] in SEEDS
        if route == "gateway":
            url = f"http://127.0.0.1:{self.server.server_port}/direct/" + "/".join(parts[1:])
            request = urllib.request.Request(url, body, {"Content-Type": "application/json",
                                                       "X-Rillprobe-Case": case["id"]})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=5) as response:
                wire = response.read()
        else:
            wire = (stream_wire(case) if case["kind"] == "stream" else
                    json.dumps(rerank_payload(case), ensure_ascii=False).encode())
        if broken:
            wire = (stream_wire(case, True) if case["kind"] == "stream" else
                    json.dumps(rerank_payload(case, True), ensure_ascii=False).encode())
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if case["kind"] == "stream" else "application/json")
        self.send_header("Content-Length", str(len(wire)))
        self.send_header("X-Rillprobe-Synthetic", "true")
        self.end_headers()
        try:
            self.wfile.write(wire)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


@contextmanager
def sandbox(broken=True):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.broken = broken
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
