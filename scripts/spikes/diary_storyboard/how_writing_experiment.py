"""Six single-attempt writing calls over frozen HOW stamps; no scene selection.

One process owns an output directory. Interrupted/failed attempts are never sent
again. Provider receipts retain actual usage; semantic review is a separate file.
"""

import argparse
import json
from pathlib import Path

from .provider import Provider
from .record_envelopes import payload_hash
from .stamp_storyboard import accept_writing, render, writing_request
from .stamp_tool import StampRef, StampTool
from .storage import digest, read, save
from .writing_projection import verify_comparison

MODEL = "gemini-3.1-flash-lite"
SETTINGS = {"temperature": 0.2, "maxOutputTokens": 4096}
CASES = ("all_records", "no_record", "gap")
ARMS = ("baseline", "compact")
# Alternate first arm between cases. This is one sample per arm, not a power study.
ORDER = [(case, arm) for i, case in enumerate(CASES)
         for arm in (ARMS if i % 2 == 0 else ARMS[::-1])]


class WritingProvider(Provider):
    def request(self, stage, payload, contract):
        if stage != "how_write":
            raise ValueError("unsupported writing stage")
        if contract.model_json_schema() != payload["response_schema"]:
            raise ValueError("frozen response schema changed")
        return {
            "systemInstruction": {"parts": [{"text": payload["prompt"]}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(
                payload["input"], ensure_ascii=False, separators=(",", ":"), allow_nan=False
            )}]}],
            "generationConfig": {**SETTINGS, "responseMimeType": "application/json",
                                 "responseJsonSchema": payload["response_schema"]},
        }


def context(root, case, arm):
    tool = StampTool.load(read(root / case / "stamp_book.json"))
    comparison = verify_comparison(tool, read(root / case / "writing_comparison.json"))
    refs = tuple(StampRef.model_validate(r) for r in comparison["manifest"]["stamp_refs"])
    _, contract = writing_request(tool, refs)
    payload = {"prompt": comparison["prompt"], "response_schema": comparison["response_schema"],
               "input": comparison[f"{arm}_input"]}
    return tool, refs, payload, contract


def manifest_for(root):
    files = ("how_writing_experiment.py", "provider.py", "writing_projection.py",
             "stamp_storyboard.py")
    sources, requests = {}, {}
    for case in CASES:
        sources[case] = {name: payload_hash(read(root / case / f"{name}.json"))
                         for name in ("stamp_book", "writing_comparison")}
        for arm in ARMS:
            _, _, payload, contract = context(root, case, arm)
            request = WritingProvider(root, MODEL).request("how_write", payload, contract)
            requests[f"{case}/{arm}"] = digest(request)
    return {
        "version": "how-writing-gemini-v1", "model": MODEL, "settings": SETTINGS,
        "order": [list(pair) for pair in ORDER], "max_attempts": 6, "automatic_retries": 0,
        "observed_token_stop_threshold": 40000, "stop_on_unknown_usage": True,
        "max_request_bytes": 100000, "selection": "all_frozen_stamps",
        "semantic_status": "not_evaluated", "sources": sources, "requests": requests,
        "implementation": {name: payload_hash({"text": Path(__file__).with_name(name)
                                               .read_text(encoding="utf-8")}) for name in files},
    }


def prepare(root, source):
    root, source = Path(root), Path(source)
    if (root / "manifest.json").exists():
        verify(root)
        for case in CASES:
            for name in ("stamp_book", "writing_comparison"):
                if read(root / case / f"{name}.json") != read(source / case / f"{name}.json"):
                    raise ValueError("source differs from frozen experiment")
        return read(root / "manifest.json")
    if root.exists() and any(root.iterdir()):
        raise ValueError("prepare needs an empty output directory")
    # Validate all inputs before creating any partially prepared experiment.
    snapshots = {}
    for case in CASES:
        book = read(source / case / "stamp_book.json")
        comparison = read(source / case / "writing_comparison.json")
        verify_comparison(StampTool.load(book), comparison)
        snapshots[case] = {"stamp_book": book, "writing_comparison": comparison}
    for case, files in snapshots.items():
        for name, value in files.items():
            save(root / case / f"{name}.json", value)
    manifest = manifest_for(root)
    save(root / "manifest.json", manifest)
    for case, arm in ORDER:
        _, _, payload, contract = context(root, case, arm)
        save(root / case / arm / "planned_request.json",
             WritingProvider(root, MODEL).request("how_write", payload, contract))
    report(root)
    return manifest


def verify(root):
    manifest = read(root / "manifest.json")
    if manifest != manifest_for(root):
        raise ValueError("experiment changed; use a new output directory")
    for case, arm in ORDER:
        run = root / case / arm
        expected = manifest["requests"][f"{case}/{arm}"]
        if digest(read(run / "planned_request.json")) != expected:
            raise ValueError("planned request changed")
        calls = sorted((run / "calls").glob("*"))
        if len(calls) > 1:
            raise ValueError("single-attempt experiment has extra calls")
        for call in calls:
            request = call / "request.json"
            if request.exists() and digest(read(request)) != expected:
                raise ValueError("sent request changed")
            receipt = call / "receipt.json"
            if receipt.exists():
                data = read(receipt)
                if data["request_sha256"] != expected or data["requested_model"] != MODEL:
                    raise ValueError("receipt belongs to another request/model")
        accepted = run / "accepted.json"
        if accepted.exists():
            if len(calls) != 1:
                raise ValueError("accepted output lacks a single call")
            tool, refs, _, _ = context(root, case, arm)
            answer = read(calls[0] / "response.json")
            if render(tool, accept_writing(tool, refs, answer)) != read(accepted):
                raise ValueError("accepted output changed")
    return manifest


def report(root):
    rows = []
    for case, arm in ORDER:
        run = root / case / arm
        calls = sorted((run / "calls").glob("*"))
        receipt = read(calls[0] / "receipt.json") if calls and (
            calls[0] / "receipt.json").exists() else {}
        usage = receipt.get("usage") or {}
        accepted = run / "accepted.json"
        request = read(run / "planned_request.json")
        rows.append({
            "case": case, "arm": arm, "attempts": len(calls),
            "status": "accepted" if accepted.exists() else receipt.get(
                "status", "interrupted" if calls else "not_sent"),
            "structural_status": receipt.get("validation", "not_evaluated"),
            "semantic_status": "not_evaluated", "usage": usage,
            "unknown_usage": bool(calls) and "totalTokenCount" not in usage,
            "input_json_bytes": len(request["contents"][0]["parts"][0]["text"].encode()),
            "model": receipt.get("model"), "latency_s": receipt.get("latency_s"),
            "finish_reason": receipt.get("finish_reason"),
            "result": read(accepted) if accepted.exists() else None,
        })
    totals = {key: sum(r["usage"].get(key, 0) for r in rows) for key in
              ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "totalTokenCount")}
    result = {"schema_version": "how-writing-results-v1", "rows": rows,
              "attempts": sum(r["attempts"] for r in rows),
              "accepted": sum(r["status"] == "accepted" for r in rows),
              "unknown_usage_attempts": sum(r["unknown_usage"] for r in rows),
              "known_usage_totals": totals, "semantic_status": "not_evaluated"}
    save(root / "results.json", result)
    return result


def execute(root, env_file=None):
    root = Path(root)
    manifest = verify(root)
    for case, arm in ORDER:
        run = root / case / arm
        if list((run / "calls").glob("*")):
            continue  # No retry, including parse/rejection/interruption.
        observed = report(root)
        if (observed["attempts"] >= manifest["max_attempts"]
                or observed["unknown_usage_attempts"]
                or observed["known_usage_totals"]["totalTokenCount"] >=
                manifest["observed_token_stop_threshold"]):
            break
        tool, refs, payload, contract = context(root, case, arm)
        provider = WritingProvider(run, MODEL, env_file)
        request = provider.request("how_write", payload, contract)
        if len(json.dumps(request, ensure_ascii=False).encode()) > manifest["max_request_bytes"]:
            raise ValueError("request byte limit exceeded")
        print(f"{case}/{arm}", flush=True)
        try:
            response = provider.call("how_write", payload, contract)
            accepted = render(tool, accept_writing(tool, refs, response.model_dump(mode="json")))
            save(run / "accepted.json", accepted)
            provider.record_validation()
        except ValueError as exc:
            provider.record_validation(error=exc)
            save(run / "error.json", {"error": str(exc)})
        report(root)
    return report(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--run", action="store_true", help="send up to six Gemini requests")
    args = parser.parse_args()
    prepare(args.out, args.source)
    result = execute(args.out, args.env_file) if args.run else report(args.out)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
