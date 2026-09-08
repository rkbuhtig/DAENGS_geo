"""Local checkpoints. One process owns a run; outputs belong outside the repository."""

import hashlib
import json
from pathlib import Path

from .contracts import Evidence, State


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def latest(run: Path) -> State | None:
    paths = sorted((run / "states").glob("*.json"))
    return State.model_validate(read(paths[-1])) if paths else None


def checkpoint(run: Path, state: State):
    path = run / "states" / f"{state.revision:06d}.json"
    if path.exists():
        raise ValueError("checkpoint already exists; concurrent writers are unsupported")
    save(path, state.model_dump(mode="json"))
    export(run, state)


def export(run: Path, state: State):
    save(run / "storyboard.json", state.model_dump(mode="json"))
    save(run / "revision_log.json", [r.model_dump() for r in state.revisions])
    lines = [
        "# 산책 스토리보드",
        "",
        f"상태: {state.status} / 버전: {state.revision}",
        "",
        "모델 해석과 미확인 내용이 포함된 실험 결과다.",
        "",
        state.understanding.summary,
    ]
    if state.selection is not None:
        if state.selection.title_draft is not None:
            lines += ["", "대표 제목 초안: " + state.selection.title_draft.text]
        lines += ["", "## 후보 선택·생략", ""]
        lines += [
            f"- {d.candidate_id} → {d.scene_id or ('맥락' if d.context_scene_ids else '생략')} "
            f"({d.code}): {d.reason} / 맥락 참조: {', '.join(d.context_scene_ids)}"
            for d in state.selection.decisions
        ]
        if not state.outline:
            lines += ["", "남길 장면이 없는 정상 구성. 지도 동선과 원본 기록은 별도다."]
        if state.selection.compositions:
            from .composition import scene_context

            evidence = Evidence.model_validate(read(run / "evidence_snapshot.json"))
            lines += ["", "## 장면 구성안 · 문구 작성 전에도 확인 가능", ""]
            for item in state.outline:
                context = scene_context(state, item.scene_id, evidence)
                group = context["composition"]
                lines += [f"### {item.scene_id} · 대표 사건 {group['primary_candidate_id']}", "",
                          group["reason"], "", "각 행은 원본 사건의 범위다. 행동 시간을 합치지 않는다.", ""]
                for event in context["events"]:
                    lines += [
                        (f"- {event['candidate_id']} [{event['membership']}] "
                        f"{event['start_at']} → {event['end_at']} / "
                        f"{event['source_text'] or '연결 이동'} / 위치 {event['location_status']}")
                    ]
                lines += [""]
    edits = {e.scene_id: e for e in state.review.edits} if state.review else {}
    outline = {s.scene_id: s for s in state.outline}
    for scene in state.scenes:
        item = outline[scene.scene_id]
        edit = edits.get(scene.scene_id)
        title = edit.title if edit and edit.title is not None else scene.title
        body = edit.text if edit and edit.text is not None else scene.text
        lines += [
            "",
            f"## {title}",
            "",
            f"{scene.scene_id}: {item.start_at.isoformat()} → {item.end_at.isoformat()}",
            "",
        ]
        if edit and not edit.included:
            lines += ["이번 일기에서 숨긴 장면.", ""]
        lines += [body]
        if edit and edit.text is not None:
            lines += ["", "편집 전 모델 문구와 근거는 해당 버전 JSON에 보존된다."]
        else:
            for label, claims in (
                ("관찰로 분류한 내용", scene.observed_facts),
                ("해석으로 분류한 내용", scene.interpretations),
            ):
                lines += ["", f"### {label}", ""]
                lines += [f"- {c.text} [{', '.join(c.evidence_ids)}]" for c in claims]
        lines += ["", "미확인: " + "; ".join(scene.open_questions)]
    lines += ["", "## 재검토 후 남은 확인 사항", ""]
    lines += [f"- {f.text} [{', '.join(f.scene_ids)}]" for f in state.findings]
    (run / "storyboard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
