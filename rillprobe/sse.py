"""Incremental SSE framing and a deliberately narrow chat-completions contract."""

import codecs
from collections.abc import Iterable

from .errors import ContractError
from .contracts import parse_json

MAX_BYTES = 8 * 1024 * 1024


class SSEDecoder:
    def __init__(self):
        self.decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
        self.line = []
        self.data = []
        self.event_type = "message"
        self.after_cr = False
        self.size = 0

    def feed(self, chunk: bytes, final=False) -> list[tuple[str, str]]:
        self.size += len(chunk)
        if self.size > MAX_BYTES:
            raise ContractError("stream_limit", "Stream exceeds the 8 MiB safety limit")
        try:
            decoded = self.decoder.decode(chunk, final=final)
        except UnicodeDecodeError as exc:
            raise ContractError("invalid_utf8", "Stream is not valid UTF-8") from exc
        events = []
        for char in decoded:
            if self.after_cr and char == "\n":
                self.after_cr = False
                continue
            self.after_cr = False
            if char in "\r\n":
                event = self._line("".join(self.line))
                self.line = []
                self.after_cr = char == "\r"
                if event is not None:
                    events.append(event)
            else:
                self.line.append(char)
        # SSE does not dispatch an event without a blank terminating line.
        return events

    def _line(self, line):
        if not line:
            event = (self.event_type or "message", "\n".join(self.data)) if self.data else None
            self.data = []
            self.event_type = "message"
            return event
        if line.startswith(":"):
            return None
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "data":
            self.data.append(value)
        elif field == "event":
            self.event_type = value
        return None


def parse_chat(chunks: Iterable[bytes], cancel_after: int | None = None) -> dict:
    decoder = SSEDecoder()
    state = {"text": "", "tools": {}, "finish_reason": None, "done": False, "events": 0,
             "reported_models": []}
    text_fragments = []

    def accept(event):
        event_type, data = event
        if event_type == "error":
            raise ContractError("remote_error", "Provider returned an explicit error event")
        if state["done"]:
            raise ContractError("after_done", "Data was emitted after [DONE]")
        state["events"] += 1
        if data == "[DONE]":
            if state["finish_reason"] is None:
                raise ContractError("missing_finish", "[DONE] arrived without a finish reason")
            state["done"] = True
            return
        payload = parse_json(data)
        if event_type == "error" or (isinstance(payload, dict) and "error" in payload):
            raise ContractError("remote_error", "Provider returned an explicit error event")
        if not isinstance(payload, dict) or not isinstance(payload.get("choices"), list):
            raise ContractError("invalid_event", "Expected a chat-completions choices array")
        if isinstance(payload.get("model"), str) and payload["model"] not in state["reported_models"]:
            state["reported_models"].append(payload["model"])
        choices = payload["choices"]
        if not choices and "usage" in payload:
            return
        if (len(choices) != 1 or not isinstance(choices[0], dict) or
                type(choices[0].get("index")) is not int or choices[0]["index"] != 0):
            raise ContractError("invalid_choice", "This profile requires exactly choice index 0")
        choice = choices[0]
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            raise ContractError("invalid_event", "A choice delta must be an object")
        if state["finish_reason"] is not None:
            raise ContractError("after_finish", "A choice was emitted after it finished")
        content = delta.get("content")
        if content is not None:
            if not isinstance(content, str):
                raise ContractError("invalid_content", "Content delta must be a string or null")
            text_fragments.append(content)
        calls = delta.get("tool_calls", [])
        if not isinstance(calls, list):
            raise ContractError("invalid_tool", "tool_calls must be an array")
        for call in calls:
            if not isinstance(call, dict):
                raise ContractError("invalid_tool", "Tool call must be an object")
            index = call.get("index")
            if type(index) is not int or not 0 <= index < 128:
                raise ContractError("invalid_tool", "Tool index must be an integer from 0 to 127")
            tool = state["tools"].setdefault(index, {"id": [], "name": [], "arguments": []})
            function = call.get("function", {})
            if not isinstance(function, dict):
                raise ContractError("invalid_tool", "Tool function must be an object")
            for key, value in (("id", call.get("id", "")), ("name", function.get("name", "")),
                               ("arguments", function.get("arguments", ""))):
                if not isinstance(value, str):
                    raise ContractError("invalid_tool", "Tool fragments must be strings")
                tool[key].append(value)
        finish = choice.get("finish_reason")
        if finish is not None:
            if finish not in ("stop", "tool_calls"):
                raise ContractError("incomplete_finish", f"Non-success finish reason: {finish}")
            state["finish_reason"] = finish

    for chunk_index, chunk in enumerate(chunks):
        if cancel_after is not None and chunk_index >= cancel_after:
            raise ContractError("cancelled", "Caller cancelled; no successful completion recorded")
        for event in decoder.feed(chunk):
            accept(event)
    for event in decoder.feed(b"", final=True):
        accept(event)
    if not state["done"]:
        raise ContractError("truncated", "Stream ended before a complete [DONE] event")
    tools = []
    tool_ids = set()
    for index, tool in sorted(state["tools"].items()):
        tool = {key: "".join(fragments) for key, fragments in tool.items()}
        if not tool["id"] or not tool["name"]:
            raise ContractError("invalid_tool", "Tool call needs a nonempty ID and function name")
        if tool["id"] in tool_ids:
            raise ContractError("duplicate_tool_id", "Each tool call must have a distinct ID")
        tool_ids.add(tool["id"])
        try:
            arguments = parse_json(tool["arguments"])
        except ContractError as exc:
            raise ContractError("invalid_tool_json", "Assembled tool arguments are not valid JSON") from exc
        if not isinstance(arguments, dict):
            raise ContractError("invalid_tool_json", "Tool arguments must be a JSON object")
        tools.append({"index": index, **tool, "parsed_arguments": arguments})
    if bool(tools) != (state["finish_reason"] == "tool_calls"):
        raise ContractError("tool_finish", "Tool calls and finish reason disagree")
    state["text"] = "".join(text_fragments)
    return {**state, "tools": tools}
