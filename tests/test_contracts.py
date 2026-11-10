import json
import math
import tempfile
import unittest
from pathlib import Path

from rillprobe.contracts import compare_text, retrieval_metrics, validate_rerank
from rillprobe.errors import ContractError
from rillprobe.fixtures import CASES, SEEDS, stream_wire
from rillprobe.report import render_html, write_report
from rillprobe.runner import demo, endpoint_url
from rillprobe.sse import SSEDecoder, parse_chat


class StreamTests(unittest.TestCase):
    def test_every_partition_preserves_text_and_tools(self):
        for case_id in ("text-emoji", "text-combining", "tool-nested", "frame-multiline", "frame-bom"):
            case = CASES[case_id]
            wire = stream_wire(case)
            expected = parse_chat([wire])
            for partition in range(1, len(wire)):
                with self.subTest(case=case_id, partition=partition):
                    self.assertEqual(parse_chat([wire[:partition], wire[partition:]]), expected)

    def test_multiline_fixture_has_multiple_data_fields(self):
        self.assertIn(b"data: {\ndata: ", stream_wire(CASES["frame-multiline"]))

    def test_all_negative_fixtures_reject(self):
        for case in CASES.values():
            if "expected_error" not in case:
                continue
            with self.subTest(case=case["id"]):
                wire = stream_wire(case)
                with self.assertRaises(ContractError) as error:
                    parse_chat([wire[:13], wire[13:]], cancel_after=1 if case["id"] == "reject-cancel" else None)
                self.assertEqual(error.exception.code, case["expected_error"])

    def test_error_event_cannot_impersonate_done(self):
        wire = stream_wire(CASES["text-ascii"]).replace(b"data: [DONE]", b"event: error\ndata: [DONE]")
        with self.assertRaises(ContractError) as error:
            parse_chat([wire])
        self.assertEqual(error.exception.code, "remote_error")

    def test_overflow_tool_number_rejects(self):
        # A complete tool call carrying an exponent overflow must not become Infinity.
        payload = {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "a",
                   "function": {"name": "f", "arguments": '{"amount":1e309}'}}]}, "finish_reason": "tool_calls"}]}
        wire = ("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode()
        with self.assertRaises(ContractError) as error:
            parse_chat([wire])
        self.assertEqual(error.exception.code, "invalid_tool_json")

    def test_unterminated_event_is_not_dispatched(self):
        self.assertEqual(SSEDecoder().feed(b"data: unfinished\n", final=True), [])

    def test_normalization_is_explicit(self):
        with self.assertRaises(ContractError):
            compare_text("é", "e\u0301")
        compare_text("é", "e\u0301", "nfc")


class RerankTests(unittest.TestCase):
    def ranked(self, **changes):
        row = {"index": 0, "relevance_score": 4, "document": "a"}
        row.update(changes)
        return {"results": [row]}

    def test_scales_are_not_assumed(self):
        for score in (-2000, 0, 0.1, 90000):
            validate_rerank(self.ranked(relevance_score=score), ["a"], 1)

    def test_malformed_scores_and_indices_have_stable_errors(self):
        for value in (math.nan, math.inf, True, "0.1", 10 ** 400):
            with self.subTest(value=str(value)[:20]), self.assertRaises(ContractError) as error:
                validate_rerank(self.ranked(relevance_score=value), ["a"], 1)
            self.assertEqual(error.exception.code, "invalid_score")
        for value in (-1, 1, False, 0.0):
            with self.assertRaises(ContractError):
                validate_rerank(self.ranked(index=value), ["a"], 1)

    def test_duplicate_document_positions_remain_distinct(self):
        payload = {"results": [{"index": i, "relevance_score": 2 - n, "document": "same"}
                               for n, i in enumerate((1, 0))]}
        validate_rerank(payload, ["same", "same"], 2)
        payload["results"][0]["index"] = 0
        with self.assertRaises(ContractError) as error:
            validate_rerank(payload, ["same", "same"], 2)
        self.assertEqual(error.exception.code, "duplicate_index")

    def test_quality_uses_labels_not_score_scales(self):
        metrics = retrieval_metrics([2, 0, 1], [0, 3, 1])
        self.assertEqual(metrics["mrr"], 1)
        self.assertLess(metrics["ndcg"], 1)
        self.assertEqual(retrieval_metrics([], [0])["ndcg"], 0)


class JourneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.broken = demo()
        cls.fixed = demo(fixed=True)

    def test_correct_routes_and_every_seed(self):
        self.assertGreaterEqual(self.fixed["fixture_count"], 40)
        self.assertEqual(self.fixed["summary"]["failed"], 0)
        self.assertEqual(self.broken["summary"]["detected_defects"], len(SEEDS))
        self.assertEqual(self.broken["summary"]["unexpected_failures"], 0)
        self.assertEqual(self.broken["summary"]["failed"], len(SEEDS))

    def test_report_escapes_hostile_fixture_and_has_provenance(self):
        html = render_html(self.broken)
        self.assertNotIn('</script><img src=x', html)
        self.assertIn('\\u003c/script', html)
        self.assertIn('Synthetic HTTP demo', html)
        with tempfile.TemporaryDirectory() as directory:
            write_report(self.fixed, directory)
            saved = json.loads(Path(directory, "report.json").read_text())
            self.assertEqual(saved, self.fixed)

    def test_endpoint_credentials_cannot_hide_in_urls(self):
        for url in ("ftp://example.org", "https://token@example.org/v1", "https://a/v1?key=secret"):
            with self.assertRaises(ContractError):
                endpoint_url(url)


if __name__ == "__main__":
    unittest.main()
