"""Predeclared synthetic inputs, independent expectations and explicit fault seeds."""

import json

TEXTS = [
    ("ascii", "A short response."), ("cyrillic", "Проверка потока"),
    ("emoji", "Route 🧭 → ready ✅"), ("combining", "Cafe\u0301"),
    ("composed", "Café"), ("quotes", 'Say "ready".'),
    ("backslash", r"C:\temp\new"), ("literal-escape", r"literal \n stays literal"),
    ("newline", "first\nsecond\tthird"), ("html", '</script><img src=x onerror="alert(1)">'),
    ("rtl", "مرحبا"), ("cjk", "日本語 中文"), ("zwj", "👩‍💻"),
    ("flags", "🇫🇮🇯🇵"), ("nul", "left\x00right"), ("empty", ""),
    ("spaces", "  preserve  "), ("paragraphs", "a\r\nb\rc"),
    ("astral", "𝄞 𐐷"), ("json", '{"ok": true, "n": 2}'),
]


def suite():
    cases = [{"id": f"text-{name}", "kind": "stream", "text": text,
              "expected_text": text, "read_size": 1 if name in ("emoji", "cyrillic", "zwj") else 17}
             for name, text in TEXTS]
    for name, extra in (("lf", {}), ("crlf", {"newline": "\r\n"}),
                        ("cr", {"newline": "\r"}), ("multiline", {"multiline": True}),
                        ("comments", {"comments": True}), ("bom", {"bom": True}),
                        ("usage", {"usage": True})):
        cases.append({"id": f"frame-{name}", "kind": "stream", "text": "Framing ✓",
                      "expected_text": "Framing ✓", "read_size": 1, **extra})
    for name, args in (("simple", {"ready": True}), ("nested", {"room": {"label": "北 🧭"}}),
                       ("escaping", {"path": r"a\b", "quote": '"'}), ("empty", {})):
        cases.append({"id": f"tool-{name}", "kind": "stream", "text": "", "tool_args": args,
                      "expected_tool": args, "read_size": 7})
    for name, code in (("truncated", "truncated"), ("invalid-utf8", "invalid_utf8"),
                       ("bad-json", "invalid_json"), ("explicit", "remote_error"),
                       ("length", "incomplete_finish"), ("no-finish", "missing_finish"),
                       ("tool-json", "invalid_tool_json"), ("after-done", "after_done"),
                       ("cancel", "cancelled")):
        cases.append({"id": f"reject-{name}", "kind": "stream", "text": "A response",
                      "malformed": name, "expected_error": code, "read_size": 13})
    reranks = [
        ("ordinary", ["blue", "green", "red"], 3, [2, 0, 1], [8, 4, 2]),
        ("duplicates", ["same", "other", "same"], 3, [2, 0, 1], [9, 8, 1]),
        ("top-one", ["one", "two", "three"], 1, [1, 2, 0], [3, 2, 1]),
        ("top-zero", ["one"], 0, [0], [1]), ("empty", [], 3, [], []),
        ("oversized", ["one", "two"], 10, [1, 0], [1, 0]),
        ("signed", ["one", "two"], 2, [1, 0], [-2, -10]),
        ("ties", ["one", "two"], 2, [0, 1], [0.5, 0.5]),
        ("unicode", ["東京", "Привет", "🧭"], 3, [2, 1, 0], [30, 20, 10]),
        ("empty-doc", ["", "b"], 2, [1, 0], [2, 1]),
        ("document-echo", ["A", "B"], 2, [1, 0], [1000, 1]),
    ]
    for name, docs, top_n, order, scores in reranks:
        cases.append({"id": f"rank-{name}", "kind": "rerank", "documents": docs,
                      "top_n": top_n, "order": order, "scores": scores})
    return cases


CASES = {case["id"]: case for case in suite()}
SEEDS = {
    "text-emoji": "decode_utf8_per_chunk", "text-literal-escape": "unescape_twice",
    "frame-crlf": "drop_done", "tool-nested": "drop_tool_fragment",
    "reject-explicit": "swallow_provider_error", "rank-duplicates": "rebuild_duplicate_index",
    "rank-top-one": "ignore_top_n", "rank-signed": "nonfinite_score",
}
SEED_RULES = {
    "text-emoji": "text_mismatch", "text-literal-escape": "text_mismatch", "frame-crlf": "truncated",
    "tool-nested": "invalid_tool_json", "reject-explicit": "missing_expected_error",
    "rank-duplicates": "duplicate_index", "rank-top-one": "cardinality", "rank-signed": "invalid_json",
}


def stream_wire(case, broken=False):
    newline = case.get("newline", "\n")

    def event(payload):
        if isinstance(payload, str):
            data = payload
        else:
            data = json.dumps(payload, ensure_ascii=False)
        if case.get("multiline") and data.startswith("{"):
            data = data.replace('{"choices":', '{\ndata: "choices":')
        return ("data: " + data + newline + newline).encode("utf-8")

    def choice(delta, finish=None):
        return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

    malformed = case.get("malformed")
    if malformed == "invalid-utf8":
        return b"data: \xff\n\n"
    if malformed == "bad-json":
        return b"data: {broken}\n\n"
    if malformed == "explicit":
        if not broken:
            return event({"error": {"message": "Synthetic upstream failure"}})
        return event(choice({"content": ""})) + event(choice({}, "stop")) + event("[DONE]")
    text = case.get("text", "")
    if broken and case["id"] == "text-literal-escape":
        text = text.replace(r"\n", "\n")
    parts = [event(choice({"role": "assistant", "content": ""}))]
    for offset in range(0, len(text), 3):
        parts.append(event(choice({"content": text[offset:offset + 3]})))
    tool_args = case.get("tool_args")
    if tool_args is not None or malformed == "tool-json":
        args = json.dumps(tool_args or {}, ensure_ascii=False)
        if malformed == "tool-json" or (broken and case["id"] == "tool-nested"):
            args = args[:-1]
        parts.append(event(choice({"tool_calls": [{"index": 0, "id": "call_synthetic",
                          "function": {"name": "inspect", "arguments": ""}}]})))
        for offset in range(0, len(args), 2):
            parts.append(event(choice({"tool_calls": [{"index": 0,
                              "function": {"arguments": args[offset:offset + 2]}}]})))
    if malformed != "no-finish":
        finish = "length" if malformed == "length" else "tool_calls" if (
            tool_args is not None or malformed == "tool-json") else "stop"
        parts.append(event(choice({}, finish)))
    if malformed != "truncated" and not (broken and case["id"] == "frame-crlf"):
        parts.append(event("[DONE]"))
    if malformed == "after-done":
        parts.append(event(choice({"content": "late"})))
    wire = b"".join(parts)
    if case.get("comments"):
        wire = b": heartbeat\n\nid: synthetic\n\n" + wire
    if case.get("bom"):
        wire = codecs_bom() + wire
    if broken and case["id"] == "text-emoji":
        wire = "".join(bytes([value]).decode("utf-8", errors="replace") for value in wire).encode("utf-8")
    return wire


def codecs_bom():
    return b"\xef\xbb\xbf"


def rerank_payload(case, broken=False):
    count = len(case["documents"]) if broken and case["id"] == "rank-top-one" else case["top_n"]
    results = []
    for index, score in list(zip(case["order"], case["scores"]))[:count]:
        document = case["documents"][index]
        if broken and case["id"] == "rank-duplicates":
            index = case["documents"].index(document)
        if broken and case["id"] == "rank-signed":
            score = float("nan")
        results.append({"index": index, "relevance_score": score, "document": {"text": document}})
    return {"results": results, "model": "synthetic-fixture-v1"}


# Authored relevance labels are kept outside the protocol runner's ranking logic.
CORPUS = [
    {"id": "retrieval-utf8", "query": "UTF8 stream decoding", "documents": [
        "Rerank scores order documents.", "Incremental UTF8 decoding preserves stream bytes.",
        "UTF8 text has variable width.", "A garden needs water."], "relevance": [0, 3, 1, 0]},
    {"id": "retrieval-index", "query": "duplicate source index", "documents": [
        "Duplicate documents still have separate source index positions.", "Tea is warm.",
        "A source index identifies the original input.", "A stream ends."], "relevance": [3, 0, 2, 0]},
    {"id": "retrieval-sse", "query": "SSE blank line event", "documents": [
        "A JSON object has keys.", "SSE dispatches an event after a blank line.",
        "SSE has data fields.", "A city map."], "relevance": [0, 3, 1, 0]},
    {"id": "retrieval-normalize", "query": "Unicode normalization NFC", "documents": [
        "Streaming delivers chunks.", "NFC is a Unicode normalization form.",
        "Normalization changes some code point sequences.", "A rerank score."], "relevance": [0, 3, 2, 0]},
    {"id": "retrieval-cancel", "query": "cancel stream completion", "documents": [
        "Never record completion after a caller cancels a stream.", "The sky is clear.",
        "A stream can finish or fail.", "Rerank an input."], "relevance": [3, 0, 1, 0]},
]
