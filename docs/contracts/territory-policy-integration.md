---
status: proposed
implementation: policy-and-transaction-contract
last_verified: 2026-09-06
---

# 점령 정책 연결 계약 v1

전체 개발 이유·저장소별 상태·이관 작업은 [게임 인수인계](../explorations/walk/game/territory-game-handoff.md)를 읽는다.
동네 순위·칭호는 이 계약의 구현 범위가 아니며 [별도 초안](territory-ranking-titles.md)에 있다.

운영 DB 적용 전에도 구현·검증할 수 있는 정책과 저장 경계를 정의한다. Geo에는 계산 코드,
트랜잭션 인터페이스, 실행 서비스와 테스트 어댑터를 구현했다. 후속으로
[Geo PostgreSQL 어댑터와 Alembic 0033](territory-policy-postgres.md)을 추가했다.
DEV #260의 실제 테이블 매핑과 운영 반영은 아직 하지 않았다. 이 문서는 공통 입력 계약이다.

기준은 [DEV #260](https://github.com/SAJOYO/DAENGS_dev/pull/260)의
`5b2c8a4c57cdf593c8e5be9f11225ffaab599413`이다. 이후 변경되면 연결 위치를 다시 대조한다.
배점과 제품 미결 사항은 [게임 문서](../explorations/walk/game/territory-season-game.md)를 따른다.

## 구현 경계

| 모듈 | 책임 |
|---|---|
| `app/features/territory/game/policy.py` | 불변 입력으로 보호·보유 구간·소유권 변경·시즌 종료 결과 계산. 표준 라이브러리만 사용 |
| `policy_ports.py` | 호출자가 연 동일 DB 트랜잭션의 조회·잠금·저장 인터페이스 `PolicyTransaction` |
| `policy_service.py` | `apply_ownership_in_transaction`, `finalize_in_transaction`. 커밋은 호출자 책임 |
| `postgres_store.py` | Geo PostgreSQL 실제 저장, 시즌 생성/점유 초기 반영, 일관된 점수 조회 |
| `season.py` | 같은 계산 모듈을 사용하는 합성 세션·사진·게임판 체험 |
| `tests/territory/policy_memory_adapter.py` | 롤백·재전송·경쟁 요청 계약을 실행하는 테스트 전용 어댑터 |

운영 어댑터가 `Game` 전체 상태나 로컬 SQLite에 의존할 필요는 없다. 로컬 HTTP의 `advance`,
`resolve`, `finalize` 명령을 실제 앱 API로 옮기지 않는다.

## 입력과 결과

계약 버전은 `territory-policy.v1`이다. ID는 비어 있지 않은 문자열이며 DEV의 UUID를 문자열로
전달한다. 모든 시각은 UTC epoch 정수 밀리초다. 저장 시각 변환에서 반올림 규칙을 통일한다.

| 입력 | 필드와 의미 |
|---|---|
| `SeasonContext` | `season_id`, `starts_ms`, `ends_ms`, `status`, 변경 불가능한 `Rules` snapshot |
| `SiteSnapshot` | `season_id`, `site_id`, 단조 증가 `version`, 현재 `owner` 또는 중립 `None` |
| `Ownership` | `pet_id`, `session_id`, `attempt_id`, `certification`, 실제 확정 시각 `occupied_ms` |
| `OwnershipCandidate` | 시즌·장소·대표견·세션·시도 ID, `expected_version`, `event_id`, `cause`, `certification` |
| `Score` | 보너스, 점유 점수 분자, 영역 보유 시간 합, 현재/점수 대상 보유 수, 최대 보유 수, 점령/탈취 횟수, 마지막 정산 시각 |

Candidate는 **서버 내부의 승인된 소유권 변경 후보**다. 로그인 사용자·반려견 소유권·참여견·
산책/접촉·사진과 verified visit 연결을 검증한 #260 서비스만 생성한다. 클라이언트가 이 구조를
그대로 전송해서 점령하거나 점수를 받을 수 없다. 허용 조합은 `MARK + UNVERIFIED`와
`PHOTO_VERIFIED + VERIFIED`다. 정책 커널은 GPS와 사진의 진위를 판단하지 않는다.

`event_id`는 `mark:<claim UUID>` 또는 `photo:<photo UUID>`처럼 원본 사건과 처리 단계를
고정한다. 시각·재시도 횟수를 포함하지 않는다. `expected_version`과 나머지 후보 필드도 원래
시도에 저장한 값으로 재구성한다. 재요청 때 현재 버전으로 바꾸면 동일 요청이 아니다.

`OwnershipPlan`은 변경 전후 소유권, 영향받는 강아지 계정, 실제 지급 보너스, 일별 지급 키를
반환한다. 보유 수가 바뀌기 직전에 **양쪽 강아지의 모든 영역에 대한 이전 구간**을 정산한다.
자기 영역 인증 강화는 최초 점령 시각·시도·세션을 유지하며 보너스를 추가하지 않는다.

`Receipt`는 원본 후보·적용 시각·적용 당시 장소 버전·보너스·결과 종류를 저장한 영수증이다.
같은 사건은 시즌 종료나 다른 강아지의 후속 탈취 이후에도 같은 영수증을 반환한다. 이것은
**당시 처리 결과**이며 현재 소유권이 아니다. 지도 응답은 최신 소유권을 별도로 조회한다.
같은 사건 ID에 다른 후보가 오면 `event_identity_conflict`로 거절한다.

## #260 연결 위치와 트랜잭션

`territory_ownership.py`의 다음 경계에 어댑터를 연결한다.

| #260 경로 | 연결 |
|---|---|
| `mark` | 승인된 중립 점령 결과와 claim ID를 만든 뒤 후보를 전달. PHOTO_REQUIRED/REJECTED에는 점수 지급 없음 |
| `bind_photo` → `_apply_photo` | 이미 판정된 사진을 연결할 때 인증 강화/탈취 후보 전달 |
| `apply_photo_decision` → `_apply_photo` | 워커 사진 판정 트랜잭션 안에서 같은 서비스 호출. 별도 커밋 금지 |

`PolicyTransaction.save_site`가 #260의 실제 소유권과 버전을 저장한다. 기존 `_save_site`와
정책 서비스가 각각 덮어쓰는 구조를 만들지 않는다. 시도·사진 판정·verified visit·소유권·양쪽
점수·지급 키·사건·영수증은 **같은 세션/연결의 한 트랜잭션**에서 함께 커밋한다.

처음 구현할 잠금 순서는 다음과 같다.

```text
사진 행(기존 판정 경로에서 필요할 때)
  → 시즌 행 배타 잠금
    → 기존 claim/session 잠금
      → 장소 행 잠금
        → 영향받는 pet ID 오름차순 계정 잠금
          → 처리 시각 취득 → 계산 → 저장 → 호출자 commit
```

시즌 잠금은 **기존 #260 코드가 세션·장소를 잠그기 전에** 먼저 취득한다. 뒤쪽 확정 함수에
호출 한 줄만 추가하면 잠금 순서가 역전될 수 있다. 정책 서비스가 동일 시즌 행을 다시 잠그는
것은 같은 트랜잭션 안에서 허용한다. 잠금 대기 후 서버 처리 시각을 사용하며, PostgreSQL의
트랜잭션 시작 시각으로 고정되는 `now()` 대신 실제 처리 시각을 취득하는 방식을 사용한다.

이 초기 계약은 한 시즌의 변경을 직렬화한다. 시즌 종료와 다중 장소의 동일 강아지 점수 경쟁을
막는 명확한 출발점이며 대규모 처리 성능을 보증하지 않는다. 추후 잠금 범위를 줄일 때는
PostgreSQL 동시성 테스트와 시즌 종료 장벽을 함께 바꾼다.

시즌 종료는 시즌 장벽 아래 전체 계정·장소를 처리한다. **사진·claim/session 행을 잠그지
않는다.** 지연 사진은 시도에 저장된 원래 `season_id`로 판단한다. 종료된 시즌의 사진을 현재
시즌으로 옮기지 않으며, 새 시즌은 별도 ID·0점·중립 상태로 시작한다.

`protected`, `site_changed`, `new_session_required`, `season_ended`는 정책 저장 전에 발생하는
업무상 거절이다. #260이 기존 `site_changed`를 처리하듯 사진 서비스에서 이 코드만 명시적으로
처리해 사진 인증·verified visit은 보존하고 점유 거절 사유를 기록할 수 있다. DB 오류, 계정
불일치, 미지원 계약은 전부 롤백한다. 모든 예외를 잡아 소유권만 커밋해서는 안 된다.

## 후속 마이그레이션 저장 계약

아래는 제안 논리 구조다. 실제 테이블명·SQL·FK는 DEV의 모델과 migration 방식으로 구현한다.
Geo SQLite의 시즌 JSON snapshot을 운영 저장 구조로 복사하지 않는다.

| 구조 | 필수 데이터·제약 |
|---|---|
| 시즌 | ID, 시작/종료 시각(`start < end`), ACTIVE/FINALIZED, 계약/규칙 버전, 전체 규칙 snapshot. 게임 범위별 ACTIVE 하나 |
| 시즌 점수 계정 | PK `(season_id, pet_id)`, `Score` 전체. 정확한 분자/누계는 범위를 충분히 검증한 정수 또는 `NUMERIC(..., 0)`. `0 ≤ scoring_count ≤ current_count ≤ peak` |
| 소유권 연결 | #260 실제 장소 소유권을 원본으로 사용. 시즌 ID와 버전, 점령 시각, owner pet/session/attempt 매핑 |
| 시도 시즌 귀속 | #260 claim에 변경 불가능한 season ID. 재시도·사진 callback은 해당 ID를 사용 |
| 사건·영수증 | UNIQUE `(season_id, event_id)`, 원본 후보 전체, 변경 전후, 처리 시각, 적용 결과/버전. UNCHANGED도 영수증 보존 |
| 일별 보너스 키 | UNIQUE `(season_id, pet_id, site_id, utc_day)`. 해당 규칙일 때만 사용, 지급과 같은 트랜잭션 |
| 종료 성적 | PK `(season_id, pet_id)`, 정확한 총점/공동 순위, 종료 당시 전체 Score와 규칙 snapshot. 이후 덮어쓰기 금지 |

`save_site`는 잠금에 더해 버전 조건으로 갱신하고 영향 행 0개를 실패 처리한다. UNIQUE 충돌도
부분 성공으로 취급하지 않고 전체 트랜잭션을 롤백한 뒤 재시도한다. 종료 시 결과를 먼저 봉인하고
현재 보유 카운터와 해당 시즌 점유를 초기화한다. 과거 점수·사건·시도·사진은 삭제하지 않는다.

기존 소유권이 있는 DB에서 활성화할 때는 먼저 귀속 정책을 정하고 backfill한다. 이 계약의
`occupied_ms`는 시즌 내 시각이므로 기존 점유를 이어받는다면 시즌 시작/활성화 시각으로 옮긴
정책용 점령 시각을 두고 원래 #260 점령 시각은 기록으로 보존한다. 소유권에서 현재/점수 대상
보유 수를 재계산해 계정을 채우고 `last_ms`를 시작 시각으로 맞춘다. 이전 기간 점수나 점령
보너스를 소급 지급하지 않는다. 이러한 초기화 없이 존재하는 소유자의 누락 계정을 0으로
만들면 안 된다. 새 참여견 계정만 현재 처리 시각의 0점으로 초기화할 수 있다.

## 조회 응답과 활성화 경계

서버 조회용 제안 필드는 `season_id`, `rule_version`, `as_of_ms`, `protected_until_ms`,
`total_units`, `point_denominator`다. 정확한 총점은
`bonus × 36,000,000,000 + holding_units`이며 HTTP의 `total_units`는 십진 문자열이다.
화면용 소수는 표시 값이다. 조회는 마지막 정산 상태의 복사본을 시즌 종료 시각 이내로 투영하며
점수 지급을 일으키지 않는다. 종료 시즌은 봉인된 성적을 읽는다. 기존 #260 응답의 점유 정보와
정책 필드를 함께 설계하되 영수증으로 최신 점유를 덮어쓰지 않는다.

권장 준비 순서는 어댑터·migration 구현 → 격리된 PostGIS에 #260/후속 migration 적용과
backfill/동시성 검증 → 대상 DB 준비 확인 → 서버 배포 → 기능 활성화다. 정책 비활성 상태에서는
기존 점령 기능을 명시적으로 유지할 수 있다. **정책이 활성화된 상태에서 테이블이 없거나 쓰기가
실패하면 요청을 실패시킨다.** 점수 저장을 조용히 생략하거나 테스트 어댑터로 전환하지 않는다.

## 현재 검증과 남은 검증

```powershell
uv run pytest -q tests/territory/test_policy_integration.py tests/territory/test_season_game.py tests/tools/territory_game/test_season_store.py
```

가짜 트랜잭션에서 외부 커밋 책임, 중간 오류 전체 롤백, 중복 callback 한 번 지급, 두 장소의
동일 강아지 정산, 경쟁 탈취의 버전 충돌, 10분 경계, 늦은 영수증 재생, 시즌 종료 원자성을 검증한다.
로컬 체험도 동일 계산 코드를 실행한다. 후속 `test_policy_postgres.py`는 Geo 실제 PostgreSQL
연결로 중복/경쟁 요청·잠금 대기·UNIQUE·CAS·migration 전후·초기 점유 반영을 검증한다.
DEV 승격 시 #260 실제 테이블 매핑에도 같은 사례를 적용해야 운영 연결 준비가 끝난다.
