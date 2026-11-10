import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from rillprobe.errors import ContractError
from rillprobe.runner import probe
from rillprobe.sse import parse_chat


class ReflectHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        secret = self.headers.get("Authorization", "none").removeprefix("Bearer ")
        payload = {"model": "reported-test-model", "choices": [{"index": 0,
                   "delta": {"content": secret}, "finish_reason": "stop"}]}
        wire = ("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(wire)))
        self.end_headers()
        self.wfile.write(wire)


class BoundaryTests(unittest.TestCase):
    def test_reflected_known_credential_is_redacted_and_reported_model_retained(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), ReflectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"RILLPROBE_TEST_KEY": "synthetic-credential-not-real"}):
                result = probe(f"http://127.0.0.1:{server.server_port}/v1", "requested-alias",
                               key_env="RILLPROBE_TEST_KEY")
            self.assertNotIn("synthetic-credential-not-real", json.dumps(result))
            self.assertEqual(result["rows"][0]["actual"]["text"], "[REDACTED]")
            self.assertEqual(result["rows"][0]["actual"]["reported_models"], ["reported-test-model"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_empty_event_type_defaults_to_message(self):
        from rillprobe.sse import SSEDecoder
        self.assertEqual(SSEDecoder().feed(b"event:\ndata: value\n\n"), [("message", "value")])

    def test_duplicate_tool_ids_reject(self):
        calls = [{"index": i, "id": "same", "function": {"name": "f", "arguments": "{}"}}
                 for i in (0, 1)]
        payload = {"choices": [{"index": 0, "delta": {"tool_calls": calls}, "finish_reason": "tool_calls"}]}
        wire = ("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode()
        with self.assertRaises(ContractError) as error:
            parse_chat([wire])
        self.assertEqual(error.exception.code, "duplicate_tool_id")

    def test_boolean_choice_index_rejects(self):
        payload = {"choices": [{"index": False, "delta": {}, "finish_reason": "stop"}]}
        wire = ("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode()
        with self.assertRaises(ContractError) as error:
            parse_chat([wire])
        self.assertEqual(error.exception.code, "invalid_choice")
