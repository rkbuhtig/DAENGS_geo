"""Three frozen stamp cases, optional selection then short writing, six attempts maximum."""

import argparse
import json
from functools import partial
from pathlib import Path
from typing import Literal

from pydantic import Field, create_model

from .contracts import Contract
from .provider import Provider
from .selection_demo import ARCHIVE
from .stamp_materials import build_stamps, compact_stamp
from .storage import digest, read, save

MODEL = "gemini-3.1-flash-lite"
SETTINGS = {"temperature": 0.2, "maxOutputTokens": 4096}
CASES = ("movement", "actions", "gap")
PROMPTS = {
    "stamp_select": "필수 스탬프는 이미 선택됐다. 추가로 읽을 가치가 있는 스탬프 ID만 "
    "남은 카드 수 이내로 골라라. 겹치는 배경 설명을 반복하지 말고 공간 관계의 전개를 고려하라. "
    "스탬프 내부를 수정하거나 병합하지 않는다. 추가 선택이 없으면 빈 배열이다.",
    "stamp_write": "제공된 스탬프마다 한국어 제목과 한 문장 기록, 전체 제목을 써라. "
    "현재 공간과 과거 공간을 구별하고 near는 인근으로 표현한다. "
    "elapsed_s는 두 관측의 시간차이며 행동 지속시간이 아니다. "
    "기록된 행동·공간 관계·변화 순서를 유지하고 감정·목적·익숙함·시설 진입을 추가하지 않는다.",
}


class StampProvider(Provider):
    def request(self, stage, payload, contract):
        if stage not in PROMPTS:
            raise ValueError("unsupported stamp stage")
        return {
            "systemInstruction": {"parts": [{"text": PROMPTS[stage]}]},
            "contents": [
                {"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}
            ],
            "generationConfig": {
                **SETTINGS,
                "responseMimeType": "application/json",
                "responseJsonSchema": contract.model_json_schema(),
            },
        }


def selection_request(materials):
    mandatory = [s for s in materials["stamps"] if s["snapshot"]["required"]]
    optional = [s for s in materials["stamps"] if not s["snapshot"]["required"]]
    capacity = materials["max_cards"] - len(mandatory)
    if capacity < 0:
        raise ValueError("mandatory stamps exceed card capacity")
    ids = tuple(s["snapshot"]["id"] for s in optional)
    item = Literal[ids] if ids else str
    contract = create_model(
        "StampSelection",
        __base__=Contract,
        optional_stamp_ids=(list[item], Field(max_length=capacity if ids else 0)),
    )
    payload = {
        "actors": materials["actors"],
        "remaining_cards": capacity,
        "mandatory": [compact_stamp(s) for s in mandatory],
        "optional": [compact_stamp(s) for s in optional],
    }
    return payload, contract


def resolve_selection(materials, response):
    ids = response.optional_stamp_ids
    optional = {s["snapshot"]["id"] for s in materials["stamps"] if not s["snapshot"]["required"]}
    if len(ids) != len(set(ids)) or not set(ids) <= optional:
        raise ValueError("duplicate or unavailable optional stamp")
    selected = [
        s for s in materials["stamps"] if s["snapshot"]["required"] or s["snapshot"]["id"] in ids
    ]
    if len(selected) > materials["max_cards"]:
        raise ValueError("card budget exceeded")
    used = {i for s in selected for i in s["source_event_ids"]}
    return {
        "selected_stamp_ids": [s["snapshot"]["id"] for s in selected],
        "omitted_stamp_ids": [
            s["snapshot"]["id"] for s in materials["stamps"] if s not in selected
        ],
        "used_source_event_ids": sorted(used),
        "selection_explanation": "membership derived by system; model omission reasons not requested",
    }


def writing_request(materials, selection):
    selected = [
        s for s in materials["stamps"] if s["snapshot"]["id"] in selection["selected_stamp_ids"]
    ]
    if not selected:
        raise ValueError("empty selection needs no writing call")
    ids = tuple(selection["selected_stamp_ids"])
    card = create_model(
        "StampCard",
        __base__=Contract,
        stamp_id=(Literal[ids], ...),
        title=(str, Field(min_length=1, max_length=80)),
        text=(str, Field(min_length=1, max_length=350)),
    )
    contract = create_model(
        "StampWriting",
        __base__=Contract,
        title=(str, Field(min_length=1, max_length=100)),
        cards=(list[card], Field(min_length=len(ids), max_length=len(ids))),
    )
    return {
        "actors": materials["actors"],
        "stamps": [compact_stamp(s) for s in selected],
        "source_limits": {
            "space": "archived representative backgrounds; no entry proof",
            "coordinates": None,
            "weather": None,
            "view": None,
        },
    }, contract


def resolve_writing(materials, selection, response):
    cards = {c.stamp_id: c.model_dump(mode="json") for c in response.cards}
    if len(cards) != len(response.cards) or set(cards) != set(selection["selected_stamp_ids"]):
        raise ValueError("writing must cover each selected stamp exactly once")
    sources = {s["snapshot"]["id"]: s for s in materials["stamps"]}
    return {
        "title": response.title,
        "semantic_status": "not_evaluated",
        "cards": [
            {
                **cards[i],
                "source_stamp_sha256": sources[i]["sha256"],
                "anchor": sources[i]["snapshot"]["anchor"],
                "chain": sources[i]["snapshot"]["chain"],
            }
            for i in selection["selected_stamp_ids"]
        ],
    }


def prepare(root, archive=ARCHIVE, provider_type=StampProvider):
    cases = {c["id"]: c for c in read(archive)["cases"]}
    inputs = {name: build_stamps(cases[name]) for name in CASES}
    requests = {}
    for name in CASES:
        payload, contract = selection_request(inputs[name])
        requests[name] = provider_type(root / name / "select", MODEL).request(
            "stamp_select", payload, contract
        )
    manifest = {
        "version": "slot-stamp-experiment-v1",
        "model": MODEL,
        "settings": SETTINGS,
        "max_attempts": 6,
        "automatic_retries": 0,
        "observed_token_stop_threshold": 100000,
        "max_request_bytes": 100000,
        "source_input_sha256": {n: inputs[n]["source_input_sha256"] for n in CASES},
        "materials_sha256": {n: digest(inputs[n]) for n in CASES},
        "select_request_sha256": {n: digest(requests[n]) for n in CASES},
        "prompts_sha256": digest(PROMPTS),
        "implementation_sha256": digest(
            {
                n: Path(__file__).with_name(n).read_text(encoding="utf-8")
                for n in ("stamp_materials.py", "stamp_experiment.py")
            }
        ),
        "note": "Selection and writing differ from v2 planning-only. No direct quality/cost equivalence. "
        "Token threshold checks known usage before next call, not a hard cost ceiling.",
    }
    path = root / "experiment.json"
    if path.exists():
        if read(path) != manifest:
            raise ValueError("experiment changed; use a new output directory")
    elif root.exists() and any(root.iterdir()):
        raise ValueError("new experiment needs empty output directory")
    else:
        save(path, manifest)
    for name in CASES:
        for filename, value in (
            ("source.json", cases[name]),
            ("materials.json", inputs[name]),
            ("select/planned_request.json", requests[name]),
        ):
            path = root / name / filename
            if path.exists() and read(path) != value:
                raise ValueError("stored inputs changed")
            if not path.exists():
                save(path, value)
    return manifest


def usage(root):
    # Explicit stage directories avoid counting report/replay files as actual attempts.
    attempts = [
        p
        for name in CASES
        for stage in ("select", "write")
        for p in (root / name / stage / "calls").glob("*")
    ]
    receipts = [read(p / "receipt.json") for p in attempts if (p / "receipt.json").exists()]
    return {
        "attempts": len(attempts),
        "known_tokens": sum((r.get("usage") or {}).get("totalTokenCount", 0) for r in receipts),
        "unknown_usage_attempts": len(attempts) - sum(r.get("usage") is not None for r in receipts),
    }


def dispatch(root, run, stage, payload, contract, resolve, env_file, provider_type):
    accepted = run / "accepted.json"
    provider = provider_type(run, MODEL, env_file=env_file)
    request = provider.request(stage, payload, contract)
    planned = run / "planned_request.json"
    if planned.exists() and read(planned) != request:
        raise ValueError("stage input changed")
    if accepted.exists():
        # Validate saved response against the current immutable materials before reuse.
        source = next((run / "calls").glob("*/response.json"))
        if read(source.parent / "request.json") != request:
            raise ValueError("recorded request changed")
        response = read(source)
        if resolve(contract.model_validate(response)) != read(accepted):
            raise ValueError("accepted output changed")
        return read(accepted)
    if list((run / "calls").glob("*")):
        return None  # Failed or interrupted attempts are never silently reissued.
    totals = usage(root)
    if totals["attempts"] >= 6 or totals["known_tokens"] >= 100000:
        return None
    if len(json.dumps(request, ensure_ascii=False).encode()) > 100000:
        raise ValueError("request byte bound exceeded")
    save(planned, request)
    try:
        response = provider.call(stage, payload, contract)
        result = resolve(response)
        save(accepted, result)
        provider.record_validation()
        return result
    except ValueError as exc:
        provider.record_validation(exc)
        save(run / "error.json", {"error": str(exc)})
        return None


def report(root):
    totals = usage(root)
    lines = [
        "# 슬롯·스탬프 실험",
        "",
        "구조 통과는 문구의 사실성 승인이 아니다.",
        "",
        f"시도 {totals['attempts']} · 확인 토큰 {totals['known_tokens']} · 사용량 미상 {totals['unknown_usage_attempts']}",
    ]
    for name in CASES:
        lines += ["", f"## {name}", ""]
        selection = root / name / "select/accepted.json"
        output = root / name / "write/accepted.json"
        if selection.exists():
            lines += ["선택: " + ", ".join(read(selection)["selected_stamp_ids"]), ""]
        if output.exists():
            board = read(output)
            lines += [board["title"], ""]
            for card in board["cards"]:
                lines += [
                    f"### {card['stamp_id']} · {card['title']}",
                    "",
                    card["text"],
                    "",
                    f"시스템 원본 범위(초): {card['anchor']['support_s']}",
                    "",
                ]
        for stage in ("select", "write"):
            error = root / name / stage / "error.json"
            if error.exists():
                lines += [f"{stage} 거부: {read(error)['error']}", ""]
    (root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    save(root / "usage.json", totals)
    return totals


def execute(root, archive=ARCHIVE, env_file=None, provider_type=StampProvider):
    prepare(root, archive, provider_type)
    for name in CASES:
        materials = read(root / name / "materials.json")
        payload, contract = selection_request(materials)
        selection = dispatch(
            root,
            root / name / "select",
            "stamp_select",
            payload,
            contract,
            partial(resolve_selection, materials),
            env_file,
            provider_type,
        )
        if selection and selection["selected_stamp_ids"]:
            payload, contract = writing_request(materials, selection)
            dispatch(
                root,
                root / name / "write",
                "stamp_write",
                payload,
                contract,
                partial(resolve_writing, materials, selection),
                env_file,
                provider_type,
            )
        report(root)
        print(f"{name}: {usage(root)}", flush=True)
    return report(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.run:
        execute(args.out, args.archive, args.env_file)
    else:
        prepare(args.out, args.archive)
        report(args.out)
        print("Prepared stamp materials and three selection requests; no API calls")


if __name__ == "__main__":
    main()
