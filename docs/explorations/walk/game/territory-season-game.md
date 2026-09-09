---
status: draft
implementation: local-game
last_verified: 2026-09-06
---

# 동네 강자 — 점령·보유 시간·시즌 게임

> **2026-09-09 후속 기획:** [인증 차등 보상·월간 시즌 합의](territory-monthly-season-rewards.md).
> 아래 배점·반복 보너스·7일 시즌은 기존 로컬 실험 설명이다. 새 합의의 구현 완료나
> 미결 배점의 확정을 뜻하지 않는다. 인증 보호의 변경은 [정책 v2](../../../territory-policy-v2.md)를 따른다.

전체 개발 경위와 DEV·APP 이관은 [게임 인수인계](territory-game-handoff.md)를 먼저 읽는다.
이 문서는 로컬 체험과 현재 점수 규칙을 설명한다. 동네 범위와 칭호는
[미구현 정책/계약 초안](../../../contracts/territory-ranking-titles.md)에서 별도로 다룬다.

2026-09-06 대화에서 정한 방향을 Geo의 실행 가능한 게임 규칙과 로컬 체험으로 구현한다.
목표는 산책하며 영역을 차지하고 **우리 강아지를 동네 강자로 알리는 것**이다.
시즌 이후 칭호·점령 기록은 남기며, 개인 지도·미니룸 꾸미기는 후순위다.

기존 [정기 정산 탐색](territory-season-scoring.md)은 비교안으로 보존한다.
이 구현은 정산 순간의 주인에게 1점씩 주는 방식이 아니라, **점령 보너스 + 실제 보유 시간의
점유 점수**를 합산한다. 기존 [제작 계획](territory-production-plan.md)의 사진·세션 판정 기반을
이어가며, APP/DEV 공유 TSV 원본은 변경하지 않는다.

## 실행

Geo 루트에서 Python 3.12와 uv로 실행한다. PostGIS·Docker·운영 DB·지도 키는 필요 없다.

```powershell
uv sync --frozen
uv run python -m scripts.spikes.territory_season.server
```

<http://127.0.0.1:8767/>에서 새 시즌 → 보리 산책 → A 옆으로 이동 → 영역표시 → 샘플 사진 제출
→ 인증 성공 → 두부 새 산책 → 10분 진행 → 사진 제출·인증 성공으로 탈취한다.
기본 포트가 사용 중이면 `--port 8768`을 지정한다.

시간은 버튼으로 명시적으로 진행한다. 현실의 시간이 흘렀다고 점수가 오르지는 않는다.
`시즌 종료 시각까지 진행`은 시뮬레이션 시계를 종료 시각까지 보내 마지막 구간을 정산한다.
종료된 시즌은 선택 목록에서 다시 읽을 수 있으며 새 시즌은 중립 상태와 0점으로 시작한다.

기본 DB는 `.local/territory-season.sqlite3`이다. 새로고침·서버 재시작 후에도 보존한다.
별도 실험은 `--db .local/another-game.sqlite3`로 분리한다. 기존 데이터를 지울 필요가 없다.
`uv run python -m tools.lab_server --tool territory-season`으로도 `/territory-season-lab/`에서 연다.
기존 공용 앱과 같은 CWD의 `.local/territory-season.sqlite3`를 사용한다. 공용 `app.main`에는 마운트하지 않는다.
기본 앱 전체를 실행하면 기존 앱의 환경 요구사항도 적용되므로 독립 실행 명령을 우선한다.

지도·참여견·접촉·사진 판정은 합성이다. 실제 GPS, 사진 업로드, VLM, 계정·반려견 소유권
인증은 연결하지 않는다. 실제 Android 화면은 변경하지 않는다. 공개 이름·사진 선택과 칭호
부여 정책도 후속이며, 이번 화면의 이름은 샘플이다.

## 정한 방향과 초안값

| 항목 | 구현 |
|---|---|
| 장소 보호 | 첫 점령·탈취 확정 시점부터 **10분**, 종료 시각과 같으면 도전 가능 |
| 보호와 인증 우선권 | 초안: 미인증 점유도 10분 보호. 타인의 사진 인증도 보호를 무시하지 않음 |
| 첫 점령/탈취 보너스 | 초안: 각각 100점, 독립 설정 가능 |
| 기본 점유 점수 | 초안: 장소당 시간당 10점 |
| 동시 보유 계수 | 초안: 1개 1배, 추가 1개마다 +0.1배, 최대 2배 |
| 반복 보너스 | 기본 초안은 소유권 변경마다 지급. 비교안은 강아지·장소별 UTC 하루 한 번 |
| 미인증 보유 점수 | 기본 초안은 포함. 제외 옵션에서는 인증된 장소 수로 보유 수·계수를 계산 |
| 시즌 길이 | 화면 초안 7일. 새 시즌 시작 시 설정 |
| 순위 | 샘플 게임판 전체, 정확한 총점이 같으면 공동 순위. 같은 점수의 표시 순서는 pet ID |

10분 보호·점령 보너스·동시 보유 배율·기록 보존이 대화에서 정한 방향이다. **100점·10점·0.1·2배·
7일·하루 한 번은 확정 배점이 아니다.** `Rules`와 화면의 새 시즌 설정에서 바꾼다.
진행 중인 시즌은 규칙을 바꾸지 않고, 규칙 버전과 실제 설정값을 결과에 함께 보존한다.
지역 랭킹 경계, 계정 단위 반복 제한, 실제 칭호 종류는 아직 정하지 않았다.

## 점령·사진 규칙

- 한 게임 세션은 참여견 목록을 고정한다. 장소별 시도 하나에 대표견 한 마리를 고정한다.
  같은 세션·장소 재요청은 기존 시도를 반환하며, 다른 대표견으로 바꾸면 충돌한다.
- 중립 장소는 사진 없이 UNVERIFIED 점유. 타인의 VERIFIED는 PHOTO_REQUIRED,
  타인의 UNVERIFIED에 무사진 경쟁은 POLICY_UNDECIDED를 유지한다. 사진 인증으로 도전할 수 있다.
- 보호 중인 타인의 장소는 시도를 생성하지 않는다. 보호 종료 후 같은 산책에서도 첫 시도를 할 수 있다.
- 자기 영역 재방문·인증 강화는 새 소유권이 아니다. 보너스·점령 횟수·보호 시각을 갱신하지 않는다.
- 샘플 접촉도 기록 중·신뢰 가능한 위치·30초 이내·거리+오차 20m 이내를 검사한다.
  이 입력을 실제 방문 증명으로 간주하지 않는다. 실서비스 어댑터가 신뢰할 증거를 제공해야 한다.
- 촬영 ID는 한 시도에만 연결된다. 부적합은 새 촬영, 통신 장애는 같은 촬영으로 재시도한다.
  이미 연결된 사진 판정은 산책 종료 후에도 완료할 수 있다.
- 늦은 성공 판정은 촬영 시각으로 소급하지 않는다. 확정 시점의 장소 버전을 검사한다.
  그사이 다른 점유가 확정됐으면 사진은 VERIFIED로 남기고 `site_changed`로 점유를 거부한다.
  보너스도 지급하지 않는다. 새 산책·새 시도가 필요하다.

## 점수와 저장

`policy.py`는 DB·네트워크·시계·앱 인증과 독립인 보호·점수·시즌 계산 모듈이다.
`policy_service.py`는 저장 인터페이스를 통해 소유권·점수·영수증을 함께 반영한다.
실제 서버 입력·잠금 순서·후속 스키마는 [점령 정책 연결 계약](../../../contracts/territory-policy-integration.md)에 있다.
`season.py`는 같은 계산 모듈을 사용하는 로컬 세션·사진·게임판 흐름이다.
`Game.transition(command, at_ms=...)`는 새 상태와 결과를 반환한다. 실패는 입력 상태를 바꾸지 않는다.

```text
점유 점수 = Σ (구간 ms × 점수 대상 보유 수 × 시간당 기본점 × 계수 bps)
             / (3,600,000 × 10,000)
총점 = 점령 보너스 + 점유 점수
```

소유권 변경 직전에 양쪽 강아지의 이전 구간을 정산하고, 변경 후 수를 갱신한다. 한 장소만
정산하는 것이 아니라 해당 강아지의 모든 점수 대상 영역에 바뀐 계수가 적용된다.
조회는 복사본에서 현재 시각까지 투영하므로 DB를 쓰지 않는다. 정산 횟수에 따른 오차를
막기 위해 분자 정수 전체를 보존한다. HTTP의 정확한 분자는 문자열이고 소수 점수는 표시용이다.

`local_store.py`는 별도 SQLite 파일의 로컬 어댑터다. **Geo의 기본 PostGIS 스키마 원본은
계속 Alembic**이며 이 실험 파일을 그 DB로 연결하지 않는다. SQLite 스키마는
`local_schema.sql`, `PRAGMA user_version=1`로 관리하며 미지원 버전은 거부한다.

| 저장 | 용도 |
|---|---|
| `seasons` | 초기 설정·현재 게임 상태·종료 성적 snapshot·revision. ACTIVE 시즌 하나만 허용 |
| `commands` | 시즌·request ID별 명령 내용과 처리 결과. 다른 내용으로 ID를 재사용하면 충돌 |
| `events` | 소유권 변경·인증 강화·점유 거절·시즌 종료 원장 |

`BEGIN IMMEDIATE`에서 상태·양쪽 점수·사건·요청 영수증을 함께 커밋한다. SQLite의 단일 쓰기
잠금으로 서로 다른 프로세스도 직렬화된다. 실패하면 모두 롤백한다. 같은 요청의 응답이
유실되면 같은 ID로 결과를 복구하고, 현재 지도는 최신 상태로 반환한다. 웹 화면은 미확인
요청을 localStorage에 보관하고 재시도할 때까지 새 변경 요청을 막는다. 시즌 생성도 동일 ID와
설정으로 재전송하면 기존 시즌을 반환한다.

로컬 저장은 작은 합성 게임판을 위한 시즌 JSON snapshot이다. 온라인 대규모 DB 설계가 아니다.
전체 사건과 시도를 메모리에 읽으므로 대규모 부하·장기 데이터 수명은 DEV 승격 때 설계해야 한다.

## 시즌 종료

종료 시각은 제외 경계다. 그 시각의 새 점령은 허용하지 않으며 기존 점유는 종료 시각까지만 정산한다.
정확한 총점·공동 순위·점령/탈취 횟수·최대 동시 보유·영역별 보유 시간 합·종료 시 보유 수를
결과로 보존한다. `held_site_ms`는 여러 영역의 보유 시간을 합한 값이지 산책 시간이 아니다.
지도 점유는 중립으로 돌리고, 진행 중 사진에는 `season_ended`를 남긴다.

다음 시즌은 별도 ID를 쓰며 이전 시즌 요청·사진은 새 시즌에 접근할 수 없다. 새 시즌 생성은
앞선 시즌 종료 이후만 가능하다. 종료 결과를 수정하거나 이전 점수를 새 시즌에 복사하지 않는다.
칭호를 부여할 근거는 보존하지만 칭호 정책·배지 UI 자체는 이번 범위가 아니다.

## API (로컬 전용)

| 경로 | 동작 |
|---|---|
| `GET /api/seasons` | 시즌 목록 |
| `POST /api/seasons` | season_id, starts_ms, duration_ms, rules, pets, site_ids로 생성 |
| `GET /api/seasons/{id}` | 현재 지도·시도·점수 또는 봉인된 결과 |
| `POST /api/seasons/{id}/commands` | request_id와 타입별 command |

명령은 `start_session`, `phase`, `mark`, `submit`, `resolve`, `advance`, `finalize`다.
잘못된 필드·알 수 없는 필드는 422, 게임 상태 충돌은 409와 안정적인 오류 코드를 반환한다.
`advance`와 `finalize`는 **실험 시간 조작**이며 운영 클라이언트에 노출할 API가 아니다.

## 검증과 비교

```powershell
uv run pytest -q tests/territory_game/test_policy_integration.py tests/territory_game/test_season_game.py tests/tools/territory_game/test_season_store.py tests/test_import_direction.py tests/test_script_imports.py tests/walk/test_canonical_trail_boundary.py
uv run --with playwright python -m scripts.spikes.territory_season.browser_check --channel msedge
uv run python -m scripts.spikes.territory_season.simulate --hours 6
```

Edge가 없으면 `uv run --with playwright python -m playwright install chromium` 후
같은 검증 명령에 `--channel chromium`을 지정한다. 기본 검증은 Windows Edge headless다.
브라우저 테스트는 임시 SQLite와 loopback 서버를 만들고 종료한다. 캡처는 `.local/season-browser/`다.

2026-09-06 로컬 검증: 위 pytest 묶음 **128개 통과, skip 없음**. 정책 연결·새 시즌 규칙·실제 SQLite
동시 쓰기/롤백·HTTP 계약과 기존 import/CanonicalTrail 경계를 함께 선택했다. Starlette의
기존 httpx 사용 중단 예정 경고 1개가 있다. 변경 Python의 Ruff 검사와 JS 구문 검사 통과.
Edge에서 점령·인증·10분 보호·재시도·새로고침 복구·시즌 생성/명령의 응답 유실 후 재전송·
시즌 결과·390px 레이아웃을 확인했다. 초기 PR의 PostGIS/Android CI도 통과했다. 실제 기기는 실행하지 않았다.

6시간·초안 기본 배점으로 같은 커널을 실행한 비교:

| 전략 | 실제 소유권 변경 | 매번 보너스일 때 선두 | 하루 한 번일 때 선두 |
|---|---:|---:|---:|
| 한 곳 유지 | 1회 | 160점 | 160점 |
| 세 곳 유지 | 3회 | 516점 | 516점 |
| 두 강아지가 10분마다 한 곳 교환 | 36회 | 1,830점 | 130점 |

이 수치는 초안 100점 보너스에서 반복 탈취가 강해진다는 검토 근거다. 하루 제한을 확정한
결과가 아니며 실제 사용자 분포·위치·사진 비용을 모델링한 밸런스 검증도 아니다.

## APP·DEV 승격

Geo에서 이 사이클을 개발하는 데 #260 마이그레이션이나 GCP 접속은 필요 없다.
DEV로 옮길 때는 [연결 계약](../../../contracts/territory-policy-integration.md)의 `PolicyTransaction`을
실제 DB 어댑터로 구현한다. `Game` 전체 JSON DB나 로컬 API를 복사하지 않고 다음을 연결한다.

1. 실제 세션·참여견 소유권·접촉·사진 판정은 기존 인증된 서비스에서 제공한다.
2. 점령 확정 경계에서 보호 검사·점수 정산을 호출하고, #260 소유권 변경과 같은 트랜잭션으로 묶는다.
   장소뿐 아니라 양쪽 강아지 점수의 잠금 순서·멱등성·시즌 경계도 함께 검증한다.
3. 점수·시즌·지급 원장은 DEV의 init SQL 및 후속 migration으로 구현한다.
4. 대상 DB에 #260과 후속 migration·검증을 먼저 적용한 뒤 해당 서버와 APP을 반영한다.
   Windows 개발 DB와 GCP 운영 DB의 적용은 별개다.

로컬 체험 외에 [Geo PostgreSQL 어댑터와 0033](../../../contracts/territory-policy-postgres.md)도 구현했다.
웹 체험은 계속 SQLite를 사용한다. PostgreSQL 체험 연결은 DEV 승격의 필수 조건이 아니다.
실제 #260 테이블 매핑·APP 확장·운영 적용은 [이관 작업표](territory-game-handoff.md)에 남긴다.
