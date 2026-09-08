"""Second bounded planning comparison: distinct ID-only model contracts, source resolution."""

import argparse
from pathlib import Path

from .composition_experiment import (
    COMMON_EXPERIMENT,
    MODEL,
    SETTINGS,
    execute,
    prepare,
    summarize,
)
from .contracts import Evidence
from .editorial_contract import resolve_plan, resolved_scopes, wire_contract
from .provider import Provider
from .selection_demo import ARCHIVE
from .storage import digest, save

EDITORIAL_COMMON = """전체 산책을 이해하고 읽을 장면의 구성만 제안한다. 본문은 쓰지 않는다.
원본은 evidence_snapshot.context.candidate_catalog다. 사건 ID를 참조한다.
시각·좌표·근거 ID·scene_id는 시스템이 원본에서 복원한다. 출력에 직접 쓰지 않는다.
understanding의 observed_flow/interpretations와 title_draft는 text와 candidate_ids로 근거를 참조한다.
title_draft는 구성에 남긴 사건에서만 고른다. 이해·제목·focus·reason에도 사실성 원칙이 적용된다.
장면 상한 max_scenes는 목표 개수가 아니다. 자료가 부족하면 적게 만들거나 빈 scenes도 가능하다.
required 행동 기록은 반드시 포함한다. 후반부에도 별도로 남길 정보가 있는지 살펴본다.
omissions에는 구성에서 완전히 제외한 card_eligible=true 사건만 한 번씩 적는다.
카드 비대상 연결 사건은 시스템이 자동 처리하므로 omissions에 적지 않는다.
budget은 실제 장면 상한에 도달했을 때만 쓴다. 생략 이유는 반환 구성과 일치해야 한다.
focus는 함께 읽었을 때 전달할 내용, reason은 별도 장면 대비 새 정보·반복·묶음의 연결 근거다.
장면 수 감소 자체는 개선이 아니다. 시간상 이어진다는 이유만으로 긴 후반을 한 장면에 몰지 않는다.
"""
INDIVIDUAL = """A 조건: scenes의 각 항목은 candidate_id 하나와 focus, reason이다.
카드 자격이 있는 사건 하나를 독립 장면 하나로 선택한다. 다른 사건을 배경으로 묶지 않는다.
"""
GROUPED = """B 조건: scenes의 각 항목은 primary_candidate_id, included_candidate_ids,
context_candidate_ids, focus, reason이다. 대표 사건은 포함 사건 중 하나다.
포함 사건은 카드 자격이 있어야 하며 하나의 장면만 소유한다. required를 맥락에만 숨기지 않는다.
맥락은 다른 장면에서도 공유할 수 있다. 같은 장면에서 포함과 맥락에 중복하지 않는다.
연결 이동은 맥락으로만 사용 가능하다. 다른 GPS chain이나 GPS 공백을 가로질러 묶지 않는다.
각 묶음은 사건을 함께 읽을 구체적인 연결 이유가 있어야 한다. 따로 남기거나 생략하는 것도 가능하다.
"""


class EditorialProvider(Provider):
    EXPERIMENT_VERSION = "event-scene-planning-ab-v2"

    @staticmethod
    def experiment_metadata():
        return {
            "resolution_sha256": digest(
                Path(__file__).with_name("editorial_contract.py").read_text(encoding="utf-8")
            )
        }

    def request(self, stage, payload, contract):
        if stage not in ("select", "compose"):
            raise ValueError("experiment permits planning only")
        mode = payload["evidence_snapshot"]["context"]["candidate_catalog"]["composition_mode"]
        if stage != ("select" if mode == "individual" else "compose"):
            raise ValueError("stage and editorial mode differ")
        request = super().request(stage, payload, wire_contract(mode))
        request["systemInstruction"]["parts"][0]["text"] = (
            EDITORIAL_COMMON + (INDIVIDUAL if mode == "individual" else GROUPED) + COMMON_EXPERIMENT
        )
        request["generationConfig"].update(SETTINGS)
        return request

    def call(self, stage, payload, contract):
        evidence = Evidence.model_validate(payload["evidence_snapshot"])
        mode = evidence.context["candidate_catalog"]["composition_mode"]
        proposal = super().call(stage, payload, wire_contract(mode))
        plan = resolve_plan(proposal, evidence)
        save(self.run / "resolved_plan.json", plan.model_dump(mode="json"))
        save(self.run / "resolved_scene_scopes.json", resolved_scopes(plan, evidence))
        return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.run:
        execute(args.out, args.archive, args.model, args.env_file, EditorialProvider)
    else:
        prepare(args.out, args.archive, args.model, EditorialProvider)
        summarize(args.out)
        print("Prepared six ID-based planning requests; no API calls")


if __name__ == "__main__":
    main()
