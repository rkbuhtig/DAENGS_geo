"""운영 표면별 마지막 승격 기준 뒤의 관련 변경을 보고한다.

이 명령은 동기화기도 게이트도 아니다. `pending`은 아직 운영 채택 여부를 검토하지 않은
변경이 있다는 뜻이고, R&D 차이를 이유로 실패하지 않는다. 잘못된 원장(없는 커밋,
현재 HEAD의 조상이 아닌 기준점, 위험한 경로)만 오류로 다룬다.

    uv run python -m scripts.promotion_status
    uv run python -m scripts.promotion_status --surface place-search
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "docs" / "promotion-ledger.toml"


class LedgerError(ValueError):
    """원장이 안전한 비교 기준을 만들지 못할 때."""


@dataclass(frozen=True)
class Surface:
    id: str
    title: str
    source_commit: str
    target_repo: str
    target_branch: str
    target_path: str
    target_commit: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class SurfaceStatus:
    surface: Surface
    commits: int
    committed_files: tuple[str, ...]
    working_files: tuple[str, ...]

    @property
    def pending(self) -> bool:
        return bool(self.committed_files or self.working_files)


def _git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise LedgerError(f"git {' '.join(args)} 실패: {detail}")
    return result.stdout.strip()


def _lines(value: str) -> tuple[str, ...]:
    return tuple(line for line in value.splitlines() if line)


def _safe_path(value: object, surface_id: str) -> str:
    if not isinstance(value, str) or not value:
        raise LedgerError(f"{surface_id}: paths에는 빈 문자열이 아닌 경로만 올 수 있다")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith("."):
        raise LedgerError(f"{surface_id}: 저장소 상대 경로가 아니다: {value}")
    return value


def load_surfaces(path: Path = LEDGER) -> tuple[Surface, ...]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LedgerError(f"승격 원장을 읽을 수 없다: {exc}") from exc
    if data.get("version") != 1:
        raise LedgerError("지원하는 promotion ledger version은 1이다")

    rows = data.get("surface")
    if not isinstance(rows, list) or not rows:
        raise LedgerError("승격 원장에 [[surface]]가 하나 이상 필요하다")

    surfaces: list[Surface] = []
    seen: set[str] = set()
    required = (
        "id",
        "title",
        "source_commit",
        "target_repo",
        "target_branch",
        "target_path",
        "target_commit",
        "paths",
    )
    for row in rows:
        if not isinstance(row, dict):
            raise LedgerError("[[surface]]는 TOML table이어야 한다")
        missing = [key for key in required if key not in row]
        if missing:
            raise LedgerError(f"surface에 필드가 없다: {', '.join(missing)}")
        surface_id = row["id"]
        if not isinstance(surface_id, str) or not surface_id:
            raise LedgerError("surface id는 빈 문자열일 수 없다")
        if surface_id in seen:
            raise LedgerError(f"surface id가 중복됐다: {surface_id}")
        seen.add(surface_id)
        values = {key: row[key] for key in required if key != "paths"}
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise LedgerError(f"{surface_id}: 모든 문자열 필드는 비어 있지 않아야 한다")
        raw_paths = row["paths"]
        if not isinstance(raw_paths, list) or not raw_paths:
            raise LedgerError(f"{surface_id}: paths가 하나 이상 필요하다")
        paths = tuple(_safe_path(value, surface_id) for value in raw_paths)
        if len(paths) != len(set(paths)):
            raise LedgerError(f"{surface_id}: paths가 중복됐다")
        surfaces.append(Surface(paths=paths, **values))
    return tuple(surfaces)


def validate_source_commits(surfaces: tuple[Surface, ...]) -> None:
    for surface in surfaces:
        exists = subprocess.run(
            ["git", "-C", str(REPO), "cat-file", "-e", f"{surface.source_commit}^{{commit}}"],
            capture_output=True,
            check=False,
        )
        if exists.returncode != 0:
            raise LedgerError(
                f"{surface.id}: source commit을 찾을 수 없다: {surface.source_commit}. "
                "CI checkout은 fetch-depth: 0이어야 한다"
            )
        ancestor = subprocess.run(
            [
                "git",
                "-C",
                str(REPO),
                "merge-base",
                "--is-ancestor",
                surface.source_commit,
                "HEAD",
            ],
            capture_output=True,
            check=False,
        )
        if ancestor.returncode != 0:
            raise LedgerError(
                f"{surface.id}: source commit이 현재 HEAD의 조상이 아니다: "
                f"{surface.source_commit}"
            )


def collect_status(surface: Surface) -> SurfaceStatus:
    pathspec = ["--", *surface.paths]
    committed = _lines(
        _git("diff", "--name-only", f"{surface.source_commit}..HEAD", *pathspec)
    )
    commits_text = _git(
        "rev-list", "--count", f"{surface.source_commit}..HEAD", *pathspec
    )
    unstaged = set(_lines(_git("diff", "--name-only", *pathspec)))
    staged = set(_lines(_git("diff", "--cached", "--name-only", *pathspec)))
    untracked = set(
        _lines(_git("ls-files", "--others", "--exclude-standard", *pathspec))
    )
    return SurfaceStatus(
        surface=surface,
        commits=int(commits_text or "0"),
        committed_files=committed,
        working_files=tuple(sorted(unstaged | staged | untracked)),
    )


def report(statuses: tuple[SurfaceStatus, ...], *, file_limit: int = 8) -> str:
    head = _git("rev-parse", "--short", "HEAD")
    lines = [
        f"승격 상태 — DAENGS_geo@{head}",
        "pending은 자동 이관 지시가 아니라 운영 채택 검토가 남았다는 표식이다.",
        "",
    ]
    for status in statuses:
        surface = status.surface
        # target와 파일이 같다는 뜻은 아니다. source 기준점 뒤 새 검토분이 없다는 뜻만 말한다.
        label = "PENDING" if status.pending else "NO_PENDING"
        lines.append(f"[{label}] {surface.title} ({surface.id})")
        lines.append(
            f"  target: {surface.target_repo}@{surface.target_branch}:"
            f"{surface.target_path} ({surface.target_commit[:7]})"
        )
        lines.append(f"  source: {surface.source_commit[:7]}")
        lines.append(
            f"  committed: {status.commits} commits / {len(status.committed_files)} files"
        )
        if status.working_files:
            lines.append(f"  working tree: {len(status.working_files)} files")
        files = (*status.committed_files, *status.working_files)
        for name in files[:file_limit]:
            lines.append(f"    - {name}")
        if len(files) > file_limit:
            lines.append(f"    - ... {len(files) - file_limit} more")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _github_notice(status: SurfaceStatus) -> str:
    surface = status.surface
    state = "pending" if status.pending else "aligned"
    message = (
        f"{surface.title}: {state}; source {surface.source_commit[:7]} 이후 "
        f"{status.commits} commits / {len(status.committed_files)} files"
    )
    return f"::notice title=Promotion {surface.id}::{message}"


def main(argv: list[str] | None = None) -> int:
    # Windows 기본 콘솔(cp949)은 문서와 보고서의 em dash 등을 출력하지 못한다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--surface", action="append", default=[], help="보고할 surface id")
    parser.add_argument(
        "--github-summary",
        action="store_true",
        help="GitHub Actions notice와 step summary에도 기록",
    )
    args = parser.parse_args(argv)

    try:
        surfaces = load_surfaces()
        if args.surface:
            wanted = set(args.surface)
            known = {surface.id for surface in surfaces}
            unknown = sorted(wanted - known)
            if unknown:
                raise LedgerError(f"모르는 surface: {', '.join(unknown)}")
            surfaces = tuple(surface for surface in surfaces if surface.id in wanted)
        validate_source_commits(surfaces)
        statuses = tuple(collect_status(surface) for surface in surfaces)
        output = report(statuses)
    except LedgerError as exc:
        parser.error(str(exc))

    print(output, end="")
    if args.github_summary:
        for status in statuses:
            print(_github_notice(status))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as handle:
                handle.write("## DAENGS_geo 승격 상태\n\n```text\n")
                handle.write(output)
                handle.write("```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
