"""Deterministic invariants; retrieval quality is measured separately."""

import json
import math
import unicodedata

from .errors import ContractError


def parse_json(value):
    """Reject nonfinite values anywhere, including unvalidated response metadata."""
    def finite_float(text):
        parsed = float(text)
        if not math.isfinite(parsed):
            raise ValueError("Nonfinite number")
        return parsed

    def reject_constant(_):
        raise ValueError("Nonfinite constant")

    try:
        return json.loads(value, parse_float=finite_float, parse_constant=reject_constant)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ContractError("invalid_json", "Response data must be valid finite JSON") from exc


def compare_text(actual: str, expected: str, policy="preserve"):
    if policy not in ("preserve", "nfc"):
        raise ContractError("invalid_policy", "Normalization policy must be preserve or nfc")
    if policy == "nfc":
        actual, expected = (unicodedata.normalize("NFC", value) for value in (actual, expected))
    if actual != expected:
        raise ContractError("text_mismatch", f"Expected {expected!r}; received {actual!r} ({policy})")


def validate_rerank(payload, documents, top_n):
    if not isinstance(documents, list) or any(not isinstance(doc, str) for doc in documents):
        raise ContractError("invalid_input", "documents must be an array of strings")
    if type(top_n) is not int or top_n < 0:
        raise ContractError("invalid_input", "top_n must be a nonnegative integer")
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ContractError("invalid_results", "Expected a results array")
    results = payload["results"]
    if len(results) != min(top_n, len(documents)):
        raise ContractError("cardinality", "Result count must equal min(top_n, document count)")
    seen = set()
    prior = math.inf
    for result in results:
        if not isinstance(result, dict):
            raise ContractError("invalid_result", "Each result must be an object")
        index = result.get("index")
        if type(index) is not int or not 0 <= index < len(documents):
            raise ContractError("source_index", "Index must identify an original input position")
        if index in seen:
            raise ContractError("duplicate_index", f"Original position {index} was returned more than once")
        seen.add(index)
        score = result.get("relevance_score")
        try:
            finite = type(score) in (int, float) and math.isfinite(score)
        except OverflowError:
            finite = False
        if not finite:
            raise ContractError("invalid_score", "Scores must be finite numbers; no shared scale is required")
        if score > prior:
            raise ContractError("score_order", "Results must be sorted by descending relevance score")
        prior = score
        if "document" in result:
            returned = result["document"]
            if isinstance(returned, dict):
                returned = returned.get("text")
            if returned != documents[index]:
                raise ContractError("document_mismatch", f"Returned document does not match source position {index}")
    return results


def retrieval_metrics(indices, relevance):
    """MRR and nDCG@k use original indices, never raw score magnitudes."""
    if (any(type(i) is not int or not 0 <= i < len(relevance) for i in indices) or
            len(indices) != len(set(indices))):
        raise ContractError("source_index", "Quality evaluation requires unique valid source indices")
    if any(type(label) is not int or not 0 <= label <= 3 for label in relevance):
        raise ContractError("invalid_relevance", "Relevance labels must be integers from 0 to 3")
    mrr = next((1 / rank for rank, index in enumerate(indices, 1) if relevance[index] > 0), 0.0)
    dcg = sum((2 ** relevance[index] - 1) / math.log2(rank + 1)
              for rank, index in enumerate(indices, 1))
    ideal = sum((2 ** label - 1) / math.log2(rank + 1)
                for rank, label in enumerate(sorted(relevance, reverse=True)[:len(indices)], 1))
    return {"mrr": mrr, "ndcg": dcg / ideal if ideal else 0.0, "k": len(indices)}
