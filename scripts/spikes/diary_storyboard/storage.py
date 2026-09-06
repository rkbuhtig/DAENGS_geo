"""Local checkpoints. One process owns a run; outputs belong outside the repository."""

import hashlib
import json
from pathlib import Path

from .contracts import State


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
