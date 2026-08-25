"""실측 세션을 **개발자가 지정한 폴더**로 모은다 — 기기 원본 + 서버 파생 + 재전송.

보는 것과 디버깅은 다르다. 보고서는 요약이지만, "거리가 왜 이렇게 나왔지"를 파려면 그 세션의
원본 fix 가 파일로 손에 있어야 한다. 서버는 finish 에서 원좌표를 지우므로 원본은 기기 Room
에만 있고, debug 빌드가 종료 시 내부 저장소에 남긴 export(`WalkSessionExporter`)가 그 통로다.

    uv run python -m scripts.walk_bundle pull  --out C:/dev/walks   # 기기 → 폴더 (adb)
    uv run python -m scripts.walk_bundle fetch --out C:/dev/walks   # 서버 파생 → 폴더
    uv run python -m scripts.walk_bundle push  --out C:/dev/walks   # 서버에 없는 세션 재전송

폴더 구조 — 세션 하나가 파일 두 개다:

    <out>/device/walk-<started>-<id8>.json    원본 (기기 export 그대로)
    <out>/server/<session_id>.json            파생 (GET /walk/sessions/{id} 응답 그대로)

`push` 가 업로드 실패의 복구 경로다: 기기엔 있는데 서버가 404 인 세션을 원래 id 로 다시
보낸다. 모든 엔드포인트가 멱등이라(재전송 = duplicates) 이미 올라간 세션에 또 보내도
안전하지만, 불필요한 호출을 안 만들려고 404 확인 뒤에만 보낸다.

주의: 이 폴더에는 원좌표가 있다. 개발 기기의 산책이지만 레포에 커밋하지 않는다 —
`--out` 은 레포 밖을 준다.
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PACKAGE = "com.daengs.geo"
EXPORT_DIR = "files/walk-exports"
BATCH = 2000                      # FixBatchIn.fixes 상한 — 업로더와 같은 값


# ------------------------------------------------------------------ 순수 부분
def session_id_of(export: dict) -> str:
    return export["session"]["id"]


def batches(fixes: list[dict], size: int = BATCH) -> list[list[dict]]:
    return [fixes[i:i + size] for i in range(0, len(fixes), size)]


def facts_summary(derived: dict) -> str:
    """서버 파생 응답 한 줄 요약. 표가 아니라 줄인 이유: 세션 수가 적고 폭이 제각각이다."""
    facts = derived.get("facts")
    if not facts:
        return "사실 없음 (finish 전이거나 계산 실패)"
    parts = [
        f"{facts['duration_s']}s", f"{facts['moving_distance_m']}m(moving)",
        f"정지 {facts['stop_count']}회", f"fix {facts['fix_count']}",
        facts.get("evidence_origin", "?"),
    ]
    encounters = derived.get("encounters") or []
    if encounters:
        parts.append(f"조우 {len(encounters)}건")
    return " · ".join(str(p) for p in parts)


# ------------------------------------------------------------------ adb / http
def adb(args: list[str]) -> bytes:
    result = subprocess.run(["adb", *args], capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"adb {' '.join(args)} 실패: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def http(method: str, url: str, payload: dict | None = None) -> tuple[int, dict | None]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, None


# ------------------------------------------------------------------ 하위 명령
def pull(out: Path) -> list[Path]:
    """기기 export → <out>/device. run-as 로 읽는다 — 내부 저장소는 debug 빌드만 열린다."""
    device = out / "device"
    device.mkdir(parents=True, exist_ok=True)
    listing = adb(["shell", "run-as", PACKAGE, "ls", EXPORT_DIR]).decode().split()
    pulled = []
    for name in sorted(listing):
        if not name.endswith(".json"):
            continue
        content = adb(["exec-out", "run-as", PACKAGE, "cat", f"{EXPORT_DIR}/{name}"])
        target = device / name
        target.write_bytes(content)
        pulled.append(target)
        print(f"  {name}")
    if not pulled:
        print("  기기에 export 가 없다 — debug 빌드로 산책을 종료했는지 확인")
    return pulled


def fetch(out: Path, base: str) -> None:
    """폴더의 각 세션에 대해 서버 파생을 받아 <out>/server 에 둔다. 404 = 미업로드."""
    server = out / "server"
    server.mkdir(parents=True, exist_ok=True)
    for path in sorted((out / "device").glob("*.json")):
        export = json.loads(path.read_text(encoding="utf-8"))
        sid = session_id_of(export)
        status, derived = http("GET", f"{base}/walk/sessions/{sid}")
        if status == 404 or derived is None:
            print(f"  {sid}  서버에 없음 (push 로 재전송 가능)")
            continue
        (server / f"{sid}.json").write_text(
            json.dumps(derived, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {sid}  {facts_summary(derived)}")


def push(out: Path, base: str) -> None:
    """서버가 모르는 세션만 원래 id 로 올린다. 업로드 실패(밖에서 Wi-Fi 끊김 등)의 복구 경로."""
    for path in sorted((out / "device").glob("*.json")):
        export = json.loads(path.read_text(encoding="utf-8"))
        sid = session_id_of(export)
        session = export["session"]
        if session.get("dog_id") is None:
            print(f"  {sid}  dog_id 없음 — 귀속을 모르는 세션은 올리지 않는다 (결정 #58)")
            continue
        status, _ = http("GET", f"{base}/walk/sessions/{sid}")
        if status != 404:
            print(f"  {sid}  이미 서버에 있음")
            continue
        http("POST", f"{base}/walk/sessions", {
            "id": sid, "dog_id": session["dog_id"], "started_at": session["started_at"]})
        for batch in batches(export["fixes"]):
            status, _ = http("POST", f"{base}/walk/sessions/{sid}/fixes", {"fixes": batch})
            if status != 200:
                raise SystemExit(f"  {sid}  fixes 업로드 실패 ({status})")
        status, finished = http("POST", f"{base}/walk/sessions/{sid}/finish",
                                {"ended_at": session["ended_at"]})
        if status != 200 or finished is None:
            raise SystemExit(f"  {sid}  finish 실패 ({status})")
        print(f"  {sid}  전송 완료 · {facts_summary({'facts': finished.get('facts'), 'encounters': finished.get('encounters')})}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("pull", "fetch", "push", "all"))
    parser.add_argument("--out", required=True, type=Path,
                        help="번들 폴더. 원좌표가 담기므로 레포 밖을 줄 것")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    if args.command in ("pull", "all"):
        print("== pull (기기 → 폴더)")
        pull(args.out)
    if args.command in ("push", "all"):
        print("== push (미업로드 재전송)")
        push(args.out, args.base)
    if args.command in ("fetch", "all"):
        print("== fetch (서버 파생 → 폴더)")
        fetch(args.out, args.base)


if __name__ == "__main__":
    sys.exit(main())
