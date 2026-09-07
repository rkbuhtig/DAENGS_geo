---
status: proposed
implementation: postgres-adapter
last_verified: 2026-09-06
---

# 점령 정책 PostgreSQL 어댑터

Geo 구현의 목적과 DEV·APP으로 옮길 파일/연결 지점은
[게임 인수인계](../explorations/walk/game/territory-game-handoff.md)를 먼저 읽는다.
현재 DB는 [동네·칭호 초안](territory-ranking-titles.md)의 지급 원장이나 지역 계약을 포함하지 않는다.

Geo에서 [정책 연결 계약](territory-policy-integration.md)을 실제 SQLAlchemy `AsyncSession`과
PostgreSQL 테이블로 구현한다. Alembic `0033`이 저장 구조를 만들고
`app/features/territory/game/postgres_store.py`가 같은 트랜잭션에서 소유권·점수·기록을 반영한다.
운영 API·GPS·사진 인증·DEV 서버 연결은 이 어댑터의 호출자 책임이다.

## 저장 구조와 Geo/DEV 매핑

| 테이블 | 저장·제약 |
|---|---|
| `territory_policy_season` | 범위별 ACTIVE 하나, 시작/종료 시각, 계약 버전, 전체 Rules. 설정 변경 금지 |
| `territory_policy_site` | Geo `territory_site.site_id` FK, 시즌별 소유권·버전·보호 시작 시각·원래 가져온 점령 시각 |
| `territory_policy_account` | 시즌/강아지 PK, 정확한 점수 분자와 보유 시간 `NUMERIC(60,0)`, 현재/점수 대상/최대 보유 수, 정산 시각 |
| `territory_policy_attempt` | 시도 ID에 원래 시즌·장소·강아지·세션을 고정. 시즌을 바꾼 재사용 거부 |
| `territory_policy_receipt` | 시즌/원본 사건 ID PK, 원래 후보와 처리 결과 전체. 현재 지도와 별개 |
| `territory_policy_event` | 실제 변경 계획과 전후 상태. 해당 영수증 FK, 함께 커밋 |
| `territory_policy_bonus` | 시즌/강아지/장소/UTC 일자 UNIQUE 지급 키 |
| `territory_policy_result` | 종료 시 정확한 점수·순위·전체 Score. 당시 보유 수를 유지 |

시도·영수증·사건·지급 키·종료 성적은 UPDATE/DELETE를 거부하는 DB trigger로 보존한다.
시즌 설정도 생성 이후 변경할 수 없다. 점수 카운터는 CHECK와 현재 소유권 집계 대조로 검증한다.
점수 계정 삭제도 거부해, 점령 영수증 없이 초기 반영한 강아지가 모든 영역을 잃어도 누적 점수를 보존한다.
장소 갱신에는 버전 조건을 사용하며 영향 행이 0개면 실패한다.

Geo에는 DEV #260의 계정·사진·점령 테이블이 없다. 따라서 이번 소유권 테이블은 **Geo 안의
정규화된 실제 DB 구현**이다. DEV 승격 시 `lock_site`/`save_site`/소유권 집계/종료 초기화는
#260의 실제 소유권을 읽고 쓰도록 매핑하고, `register_attempt`는 #260 claim의 시즌 귀속에
연결한다. 두 소유권 테이블을 동시에 운영하는 방식으로 옮기지 않는다. 정책 계산과 실행 서비스,
계정·영수증·시즌 기록 계약 및 실제 DB 검증 사례는 재사용한다.

## 마이그레이션과 테스트

명시적으로 선택한 **격리된 개발 DB**에 Geo의 전체 migration을 먼저 적용한다. URL은 예시이며
대상 DB를 미리 생성해야 한다. 기존 앱 `.env`에 의존하지 않도록 명령 실행 환경에 지정한다.

```powershell
$env:DAENGS_DATABASE_URL = 'postgresql+asyncpg://daengs:daengs@127.0.0.1:5432/territory_policy_test'
uv run alembic upgrade head
$env:DAENGS_POLICY_TEST_URL = $env:DAENGS_DATABASE_URL
uv run pytest -q tests/territory/test_policy_postgres.py
```

`0033`은 기존 Geo 장소를 변경하지 않고 정책 테이블을 추가한다. 활성 시즌·점유 데이터는
자동으로 만들지 않는다. `alembic downgrade 0032`는 이 기능의 테이블·기록을 제거하므로
개발 DB의 되돌리기 검증용이며 운영 기록을 유지하는 롤백은 기능 비활성화로 설계한다.

DB 테스트는 매 사례마다 UUID가 포함된 별도 schema를 만들고, 실제 `territory_site` 구조를
복사한 뒤 **원본 0033 upgrade/downgrade**를 실행한다. 테스트 검색 경로에는 public을 넣지 않아
자기 schema에 테이블이 없으면 public의 기존 테이블로 넘어가지 않는다. 정리 대상은 테스트가
직접 생성한 schema뿐이다. 명시한 테스트 URL이 없으면 로컬에서만 skip하고, URL이 있는데
접속이나 migration이 실패하면 테스트 실패다. CI는 PostGIS에 전체 migration을 적용하고 이 URL을
항상 지정한다.

## 호출 예시

서버가 시작한 하나의 트랜잭션에 어댑터를 생성한다. 어댑터는 엔진·URL을 선택하거나 자체
commit/rollback하지 않는다. 세션의 트랜잭션이 종료되면 해당 어댑터를 재사용할 수 없다.

```python
from app.features.territory.game.policy import OwnershipCandidate
from app.features.territory.game.policy_service import apply_ownership_in_transaction
from app.features.territory.game.postgres_store import PostgresPolicyTransaction

async with session_factory.begin() as session:
    tx = PostgresPolicyTransaction(session)
    # 기존 호스트 서비스의 session/site 잠금을 잡기 전에 먼저 호출한다.
    await tx.lock_season(claim.season_id)
    # 호스트에서 인증·접촉/사진·참여견·세션을 검증한 이후:
    candidate = OwnershipCandidate(
        season_id=claim.season_id,
        event_id=f"photo:{photo.id}",
        site_id=claim.site_id,
        expected_version=claim.expected_version,
        pet_id=claim.pet_id,
        session_id=claim.session_id,
        attempt_id=claim.id,
        certification="VERIFIED",
        cause="PHOTO_VERIFIED",
    )
    receipt = await apply_ownership_in_transaction(tx, candidate)
    # 호스트의 사진/verified visit/claim 저장도 이 session에 수행한다.
```

시즌 행 `FOR UPDATE` → 장소 행 → 정렬한 강아지 계정 순서로 잠근다. 한 시즌의 모든 변경을
직렬화하는 초기 구현이다. 시각은 잠금 대기 이후 PostgreSQL `clock_timestamp()`에서 취득하며
클라이언트 촬영 시각으로 소급하지 않는다. 신규 계정은 계산 중 메모리에만 0점으로 준비해
보호 거절 등의 경우 불필요한 DB 쓰기가 생기지 않는다. 성공할 때만 저장한다.

호스트가 사진 대기 시도를 접수할 때도 같은 시즌 장벽 아래 `register_attempt(...)`를 호출한다.
재시도는 동일한 원본 후보를 사용하고, 지연 callback은 저장한 시도의 시즌을 사용한다. 영수증
저장 때 이 귀속을 다시 검증해 새 시즌으로 바꾼 시도는 전체 트랜잭션을 실패시킨다.

`protected`/`site_changed`/`season_ended` 등 문서에 정한 업무 거절만 호스트가 명시적으로 처리할
수 있다. 이 경우 별도의 사진 인증 사실은 보존할 수 있다. DB 오류·귀속 충돌·계정 불일치는
잡아서 부분 커밋하지 않는다. 어댑터에 테이블 자동 생성이나 SQLite/가짜 저장소 fallback은 없다.

## 시즌 생성·기존 점유 초기 반영

`create_season(session, SeasonContext(...), scope_id, site_ids, initial_owners=...)`를 호출한다.
`site_ids`는 이미 Geo `territory_site`에 존재해야 한다. 활성 시즌 사이의 장소 중복을 거부하고,
동일 범위에서 이전 시즌 종료보다 이른 새 시즌 시작도 거부한다. 생성끼리는 advisory transaction
lock으로 직렬화하고 활성 범위 중복에는 DB UNIQUE도 적용한다.

기본은 중립·0점이다. `initial_owners`에 신뢰할 기존 점유를 명시하면 다음을 한 번에 수행한다.

1. 원래 점령 시각을 `imported_occupied_ms`로 보존하고 정책용 `occupied_ms`는 새 시즌 시작으로 둔다.
2. 현재/점수 대상 보유 수와 최대 보유 수를 집계하고 마지막 정산 시각을 시즌 시작으로 맞춘다.
3. 과거 시간 점수·점령 보너스·점령/탈취 횟수는 추가하지 않는다.
4. 원래 시도·세션·강아지 귀속을 함께 저장한다. 중간 실패는 전부 롤백한다.

시즌 진행 후 누락된 소유자 계정을 초기값으로 복구하지 않는다. 소유권 카운터가 맞지 않으면
오류로 중단한다. 과거 데이터의 변경은 별도 복구 절차가 필요하다.

## 종료와 조회

호출자의 트랜잭션에서 `finalize_in_transaction(tx, season_id)`를 실행한다. 시즌 장벽 아래
전체 계정을 종료 시각까지 정산하고, 결과를 저장한 뒤 현재 보유 카운터와 지도 점유를 초기화하며
시즌을 FINALIZED로 바꾼다. 사진·세션 행은 잠그거나 삭제하지 않는다. 중간 오류는 전부 롤백한다.
동시 종료 요청과 재실행은 같은 결과를 반환한다. 이전 성공 영수증은 종료 이후에도 재생한다.

`tx.projected_scores(season_id)`는 시즌 장벽 아래 일관된 계정을 읽고 현재 시각 또는 시즌
종료 시각까지 계산한 복사본을 반환한다. 조회로 DB 점수를 갱신하지 않는다. 종료 시즌은
봉인된 당시 성적을 반환한다. 현재 소유권은 영수증이 아닌 별도의 장소 조회로 읽는다.

현재 계정 집계와 시즌 종료는 한 시즌 전체를 읽는다. 대규모 부하를 위한 분할 정산·잠금 완화는
별도 검증 대상이다. 로컬 웹 체험은 기존 SQLite를 유지하며 이번 어댑터를 자동 활성화하지 않는다.
