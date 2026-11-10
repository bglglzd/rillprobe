import json
import http.client
import ipaddress
import os
import platform
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import __version__
from .contracts import compare_text, parse_json, retrieval_metrics, validate_rerank
from .errors import ContractError
from .fixtures import CASES, CORPUS, SEEDS, SEED_RULES
from .sandbox import sandbox
from .sse import MAX_BYTES, parse_chat


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ContractError("redirect_rejected", "Redirect refused; use the final endpoint URL")


def endpoint_url(base):
    try:
        parts = urllib.parse.urlsplit(base)
        _ = parts.port
    except ValueError as exc:
        raise ContractError("invalid_endpoint", "Endpoint has an invalid host or port") from exc
    if any(char.isspace() or unicodedata.category(char) == "Cc" for char in base):
        raise ContractError("invalid_endpoint", "Endpoint must not contain whitespace control characters")
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ContractError("invalid_endpoint", "Use an http(s) URL without embedded credentials")
    if parts.query or parts.fragment:
        raise ContractError("invalid_endpoint", "Endpoint URLs must not contain queries or fragments")
    return base.rstrip("/")


def is_loopback(host):
    if host and host.rstrip(".").lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def post(url, payload, headers=None, timeout=20):
    request = urllib.request.Request(endpoint_url(url), json.dumps(payload, ensure_ascii=False).encode(),
                                     {"Content-Type": "application/json", **(headers or {})})
    try:
        handlers = [NoRedirect]
        if is_loopback(urllib.parse.urlsplit(url).hostname):
            # A loopback HTTP credential must never leave the host via an inherited proxy.
            handlers.append(urllib.request.ProxyHandler({}))
        return urllib.request.build_opener(*handlers).open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise ContractError("http_error", f"Endpoint returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ContractError("connection_error", f"Endpoint connection failed ({type(exc).__name__})") from exc


def chunks(response, size):
    while chunk := response.read(size):
        yield chunk


def environment():
    return {"rillprobe": __version__, "python": platform.python_version(), "platform": platform.platform(),
            "architecture": platform.machine(), "logical_cpus": os.cpu_count(),
            "timestamp": datetime.now(timezone.utc).isoformat()}


def redact(value, secret):
    """Keep known credentials out of reports even if an endpoint reflects them."""
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, dict):
        return {redact(k, secret): redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    return value


def _expected(case):
    if "expected_error" in case:
        return "Reject with " + case["expected_error"]
    if case["kind"] == "stream":
        return "Preserve Unicode text and assemble valid tool arguments; require explicit completion"
    return "Preserve unique original positions, top_n, finite descending scores and document correspondence"


def run_case(base, route, case, seeded=False):
    start = time.perf_counter()
    result = {"case_id": case["id"], "route": route, "kind": case["kind"], "expected": _expected(case),
              "input": {k: case[k] for k in ("text", "documents", "top_n", "tool_args") if k in case},
              "seed": SEEDS.get(case["id"]) if route == "gateway" and seeded else None,
              "reproduce": f"rillprobe demo --case {case['id']}"}
    try:
        endpoint = "chat/completions" if case["kind"] == "stream" else "rerank"
        payload = ({"model": "synthetic-fixture-v1", "stream": True,
                    "messages": [{"role": "user", "content": case.get("text", "")}]} if
                   case["kind"] == "stream" else {"model": "synthetic-fixture-v1", "query": "synthetic",
                   "documents": case["documents"], "top_n": case["top_n"]})
        with post(f"{base}/{route}/v1/{endpoint}", payload, {"X-Rillprobe-Case": case["id"]}) as response:
            if case["kind"] == "stream":
                actual = parse_chat(chunks(response, case.get("read_size", 32)),
                                    cancel_after=1 if case.get("malformed") == "cancel" else None)
                if "expected_text" in case:
                    compare_text(actual["text"], case["expected_text"])
                if "expected_tool" in case and (not actual["tools"] or
                                                actual["tools"][0]["parsed_arguments"] != case["expected_tool"]):
                    raise ContractError("tool_mismatch", "Tool arguments do not preserve the synthetic input")
            else:
                actual = parse_json(response.read(MAX_BYTES + 1))
                validated = validate_rerank(actual, case["documents"], case["top_n"])
                if [r["index"] for r in validated] != case["order"][:case["top_n"]]:
                    raise ContractError("index_correspondence", "Source order differs from the declared fixture")
        if "expected_error" in case:
            raise ContractError("missing_expected_error", "Invalid fixture was accepted as a completed response")
        result.update(status="pass", code="ok", actual=actual)
    except ContractError as exc:
        expected_rejection = case.get("expected_error") == exc.code
        result.update(status="pass" if expected_rejection else "fail", code=exc.code,
                      actual={"code": exc.code, "detail": exc.detail}, expected_rejection=expected_rejection)
    except (ValueError, OSError, TimeoutError, http.client.HTTPException) as exc:
        result.update(status="fail", code="response_error", actual={"detail": type(exc).__name__})
    result["duration_ms"] = round((time.perf_counter() - start) * 1000, 3)
    return result


def demo(fixed=False, case_id=None):
    cases = [CASES[case_id]] if case_id else list(CASES.values())
    started = time.perf_counter()
    with sandbox(broken=not fixed) as base:
        rows = [run_case(base, route, case, seeded=not fixed) for case in cases for route in ("direct", "gateway")]
    failed = [row for row in rows if row["status"] == "fail"]
    expected_seeds = {case["id"] for case in cases if case["id"] in SEEDS} if not fixed else set()
    detected = {row["case_id"] for row in failed if row["route"] == "gateway" and
                row["code"] == SEED_RULES.get(row["case_id"])}
    return {"schema_version": 1, "mode": "synthetic", "scenario": "repaired" if fixed else "seeded-faults",
            "environment": environment(), "fixture_count": len(cases), "rows": rows,
            "summary": {"checks": len(rows), "passed": len(rows) - len(failed), "failed": len(failed),
                        "seeded_defects": len(expected_seeds), "detected_defects": len(detected & expected_seeds),
                        "unexpected_failures": len([r for r in failed if r["route"] == "direct" or
                                                    r["case_id"] not in expected_seeds or
                                                    r["code"] != SEED_RULES.get(r["case_id"])]),
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2)},
            "quality": evaluate_demo_quality(),
            "limits": ["Synthetic HTTP simulation; no model inference.",
                       "Contract pass is not a semantic quality or production reliability claim."]}


def evaluate_demo_quality():
    rows = []
    for case in CORPUS:
        words = set(case["query"].lower().split())
        order = sorted(range(len(case["documents"])), key=lambda i: (
            -len(words & set(case["documents"][i].lower().split())), i))
        rows.append({"case_id": case["id"], "indices": order, **retrieval_metrics(order, case["relevance"])})
    return {"mode": "synthetic-lexical-baseline", "queries": len(rows),
            "documents": sum(len(c["documents"]) for c in CORPUS), "rows": rows,
            "mean_mrr": sum(r["mrr"] for r in rows) / len(rows),
            "mean_ndcg": sum(r["ndcg"] for r in rows) / len(rows),
            "note": "Authored tiny corpus, no held-out quality claim; lexical baseline is not model inference."}


def probe(base_url, model, kind="chat", repeat=1, key_env=None, timeout=30, server_version=None):
    base = endpoint_url(base_url)
    if not 1 <= repeat <= 20:
        raise ContractError("invalid_input", "repeat must be from 1 to 20")
    headers = {}
    token = None
    if key_env:
        token = os.environ.get(key_env)
        if not token:
            raise ContractError("missing_key", "The named credential environment variable is empty")
        parts = urllib.parse.urlsplit(base)
        if parts.scheme != "https" and not is_loopback(parts.hostname):
            raise ContractError("insecure_endpoint", "Credentials require HTTPS or a loopback endpoint")
        headers["Authorization"] = "Bearer " + token
    rows = []
    for iteration in range(repeat):
        cases = CORPUS if kind == "rerank" else [{"id": "live-stream"}]
        for case in cases:
            started = time.perf_counter()
            row = {"case_id": case["id"], "route": "live", "kind": kind, "iteration": iteration + 1,
                   "expected": "Valid streaming contract; wording may vary" if kind == "chat" else
                               "Rerank transport invariants; quality is reported separately",
                   "reproduce": "Repeat the probe with the same endpoint, model and configuration"}
            try:
                if kind == "chat":
                    payload = {"model": model, "stream": True, "max_tokens": 64, "temperature": 0,
                               "messages": [{"role": "user", "content": "In one short sentence, describe a compass."}]}
                else:
                    payload = {"model": model, "query": case["query"], "documents": case["documents"],
                               "top_n": len(case["documents"]), "return_documents": True}
                with post(base + ("/chat/completions" if kind == "chat" else "/rerank"),
                          payload, headers, timeout) as response:
                    row["server_header"] = response.headers.get("Server", "not reported")
                    if kind == "chat":
                        if response.headers.get_content_type() != "text/event-stream":
                            raise ContractError("content_type", "Expected text/event-stream")
                        actual = parse_chat(chunks(response, 31))
                    else:
                        raw = response.read(MAX_BYTES + 1)
                        if len(raw) > MAX_BYTES:
                            raise ContractError("response_limit", "Response exceeds the 8 MiB limit")
                        actual = parse_json(raw)
                        ranked = validate_rerank(actual, case["documents"], len(case["documents"]))
                        row["quality"] = retrieval_metrics([r["index"] for r in ranked], case["relevance"])
                row.update(status="pass", code="ok", actual=actual)
            except ContractError as exc:
                row.update(status="fail", code=exc.code, actual={"detail": exc.detail})
            except (ValueError, OSError, TimeoutError, http.client.HTTPException) as exc:
                row.update(status="fail", code="response_error", actual={"detail": type(exc).__name__})
            row["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
            rows.append(row)
    passed = sum(r["status"] == "pass" for r in rows)
    return redact({"schema_version": 1, "mode": "live", "scenario": kind, "environment": environment(),
            "configuration": {"endpoint": base, "model": model, "repeat": repeat,
                              "server_version": server_version or "not independently supplied",
                              "credential_source": "environment variable" if key_env else "none"},
            "rows": rows, "summary": {"checks": len(rows), "passed": passed, "failed": len(rows) - passed},
            "limits": ["Only the selected endpoint capability was exercised; no broad provider certification.",
                       "Live text is not compared for exact wording. Tool calling is not exercised by this probe.",
                       "Provider billing is not measured by this tool; check the endpoint's own usage records."]}, token)
