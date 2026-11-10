import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from rillprobe.cli import main
from rillprobe.report import write_report
from rillprobe.runner import demo, probe


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests += 1
        if 'documents' in data:
            payload = {'results': [{'index': i, 'relevance_score': len(data['documents']) - i}
                                   for i in range(len(data['documents']))]}
            wire = (json.dumps(payload)[:-1] + ',"meta":{"unexpected":' + self.server.number + '}}').encode()
            content_type = 'application/json'
        else:
            payload = {'model': 'synthetic', 'choices': [{'index': 0, 'delta': {'content': 'ok'},
                                                         'finish_reason': 'stop'}]}
            wire = ('data: ' + json.dumps(payload) + '\n\ndata: [DONE]\n\n').encode()
            content_type = 'text/event-stream'
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(wire)))
        self.end_headers()
        self.wfile.write(wire)


@contextlib.contextmanager
def provider():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    server.requests = 0
    server.number = 'NaN'
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f'http://127.0.0.1:{server.server_port}/v1'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class ReviewRegressions(unittest.TestCase):
    def test_nonfinite_nested_rerank_metadata_produces_failure_report(self):
        with provider() as (server, url):
            for number in ('NaN', 'Infinity', '1e400'):
                server.number = number
                result = probe(url, 'synthetic', kind='rerank')
                self.assertEqual(result['summary']['failed'], 5)
                self.assertTrue(all(row['code'] == 'invalid_json' for row in result['rows']))
                with tempfile.TemporaryDirectory() as directory:
                    write_report(result, directory)

    def test_loopback_credentials_and_sandbox_bypass_inherited_proxy(self):
        with provider() as (target, url), provider() as (proxy, proxy_url):
            environment = {k: v for k, v in os.environ.items() if 'proxy' not in k.lower()}
            environment.update(HTTP_PROXY=proxy_url, RILLPROBE_TEST_KEY='synthetic-only-key')
            with patch.dict(os.environ, environment, clear=True):
                result = probe(url, 'synthetic', key_env='RILLPROBE_TEST_KEY')
                sandbox_result = demo(fixed=True, case_id='text-emoji')
            self.assertEqual(result['summary']['failed'], 0)
            self.assertEqual(sandbox_result['summary']['failed'], 0)
            self.assertEqual(target.requests, 1)
            self.assertEqual(proxy.requests, 0)

    def test_deep_metadata_with_credential_is_bounded_before_redaction(self):
        with provider() as (server, url):
            server.number = '[' * 600 + '0' + ']' * 600
            with patch.dict(os.environ, {'RILLPROBE_TEST_KEY': 'synthetic-depth-key'}):
                result = probe(url, 'synthetic', kind='rerank', key_env='RILLPROBE_TEST_KEY')
            self.assertEqual(result['summary']['failed'], 5)
            self.assertTrue(all(row['code'] == 'json_nesting' for row in result['rows']))
            with tempfile.TemporaryDirectory() as directory:
                write_report(result, directory)

    def test_malformed_url_is_configuration_error_without_traceback(self):
        for url in ('http://[::1/v1', 'http://localhost:999999/v1', ' http://localhost/v1',
                    'http://bad host/v1', 'http://bad\x1bhost/v1'):
            with self.subTest(url=url), contextlib.redirect_stderr(io.StringIO()) as output:
                code = main(['probe', '--base-url', url, '--model', 'synthetic'])
            self.assertEqual(code, 2)
            self.assertIn('invalid_endpoint', output.getvalue())
            self.assertNotIn('Traceback', output.getvalue())

    def test_unrelated_failure_does_not_count_as_detected_seed(self):
        def wrong_failure(base, route, case, **kwargs):
            return {'case_id': case['id'], 'route': route, 'status': 'fail' if route == 'gateway' else 'pass',
                    'code': 'connection_error' if route == 'gateway' else 'ok'}
        with patch('rillprobe.runner.run_case', wrong_failure):
            result = demo(case_id='text-emoji')
        self.assertEqual(result['summary']['detected_defects'], 0)
        self.assertEqual(result['summary']['unexpected_failures'], 1)

    def test_fixed_report_does_not_claim_a_fault_was_injected(self):
        self.assertTrue(all(row['seed'] is None for row in demo(True, 'rank-duplicates')['rows']))
