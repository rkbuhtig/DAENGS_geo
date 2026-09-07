---
status: implemented-in-geo
implementation: postgres-reference-skeleton; dev-app-promotion-pending
last_verified: 2026-09-06
---

# 산책·점령 통계 PostgreSQL — 저장, 처리, 재시작 계약

[순수 코어](activity-statistics-core.md)에 DB 저장을 연결하는 S3 구현이다.
[전체 설계](../explorations/walk/statistics/activity-statistics-skeleton.md)의 작은 흐름을 PostgreSQL에서
검증한다. DEV의 실제 산책 분석/점령 API와 APP에는 아직 연결하지 않았다.

## 1. 구현 파일과 저장 단위

| 파일 | 책임 |
|---|---|
| [0034 migration](../../alembic/versions/0034_activity_statistics.py) | 세션 연결, 원본 변경, 결과·영수증과 DB 제약 |
| [postgres_store.py](../../app/features/activity_statistics/postgres_store.py) | 입력 저장, 세대 등록, 처리, 결과/근거/반영 상태 조회 |
| [geo_policy.py](../../app/features/activity_statistics/geo_policy.py) | Geo 점령 확정·시즌 종료와 통계 변경의 원자적 연결, 기준점 생성 |
| [codec.py](../../app/features/activity_statistics/codec.py) | 확정 값 객체의 명시적 JSON 저장/복원 |
| [test_postgres.py](../../tests/activity_statistics/test_postgres.py) | 실제 DB와 별도 프로세스 복원 검증 |

`activity_session_source`는 owner/client UUID/kind별 현재 원본을 저장한다. 같은 연결의 WALK/GAME
두 행을 코어 resolver가 합쳐 읽으므로 늦은 도착과 메타데이터 충돌을 표현할 수 있다.
`UNIQUE(kind, server_id)`로 다른 회원이나 산책에 서버 ID를 재사용할 수 없다. 단말 UUID만으로
연결하지 않는다. 최초 INSERT 경쟁도 transaction advisory lock과 UNIQUE로 보호한다.

변경은 `activity_stat_stream`과 `activity_stat_change`에 저장한다. WALK는 서버 walk ID별,
TERRITORY는 시즌 ID별 스트림이며 revision은 해당 행 잠금 아래에서 연속으로 확정된다.
DB sequence의 최댓값을 처리 완료 cursor로 쓰지 않는다. 원본 변경 payload는 UPDATE를 금지한다.
이 저장에는 GPS 배열·사진·CanonicalTrail을 넣지 않는다.

`activity_stat_generation`은 통계 계약 버전과 지원 분석 버전을 계산 세대에 불변으로 연결한다.
세대별 `activity_walk_contribution`, `activity_holding_period`에 결과를 저장하고,
`activity_stat_applied`와 `activity_stat_checkpoint`에 반영 근거와 확정 시점을 남긴다.
보유 구간의 시간 순서와 한 장소의 열린 구간 단일성을 DB에서도 검사한다.

## 2. transaction과 잠금 순서

모든 어댑터는 이미 열린 `AsyncSession` transaction을 받는다. 내부에서 commit하지 않는다.
어댑터 인스턴스를 다른 transaction에서 재사용하면 거절한다. **어댑터 예외를 잡고 같은
transaction을 commit하지 않는다.** 호출자는 예외를 transaction context 밖으로 전파해야 한다.

- 점령 생산자: 기존 season barrier → 통계 스트림 잠금. 점유·점수·정책 영수증·통계 변경을 함께 확정한다.
- 산책 생산자: walk 스트림 잠금 → 세션 연결 잠금. 호스트의 분석/head 확정 transaction에서 `append_walk`를 호출한다.
- 통계 처리/읽기: generation 잠금 → 필요한 스트림 잠금. 생산자는 generation 잠금을 잡지 않는다.
- 처리 결과·영수증·checkpoint는 한 transaction에 저장한다. 실패하면 이전 결과가 그대로 남는다.

처리기 두 개가 같은 작업을 발견해도 generation 잠금 뒤 최신 checkpoint를 확인해 한 번만 갱신한다.
입력 저장 실패는 원본 확정을 rollback한다. 계산 작업 실패는 이미 commit된 원본을 취소하지 않으며,
다음 실행에서 그 스트림이 다시 pending으로 발견된다.

## 3. Geo 점령 연결

기존 시즌 생성은 [정책 PostgreSQL 계약](territory-policy-postgres.md)의 `create_season`을 사용한다.
새 시즌 생성과 같은 transaction에서 `StatisticsPolicyTransaction.activate_statistics`를 호출할 수 있다.
기존 ACTIVE 시즌에 켤 때는 현재 서버 시각과 전체 소유 목록을 잠금 아래에서 baseline으로 기록한다.

```python
async with sessions.begin() as session:
    # create_season(...)을 이 transaction에서 실행한 새 시즌의 경우
    tx = StatisticsPolicyTransaction(session)
    await tx.activate_statistics(season_id, coverage_start_ms=season.starts_ms)

async with sessions.begin() as session:
    receipt = await apply_ownership_in_transaction(
        StatisticsPolicyTransaction(session), authenticated_candidate,
    )
```

위 코드는 기존 호스트의 `sessions`, 시즌 및 인증된 candidate를 사용하는 연결 예다. 공개 요청을
바로 통계 어댑터에 넣는 API가 아니다. 기존 시즌의 활성화는 `coverage_start_ms`를 생략한다.
명시적 시즌 시작 baseline은 기존 점령 사건이 없는 경우에만 허용한다. 활성화는 일회성이고,
이미 있는 스트림을 삭제하거나 덮어써 재활성화하지 않는다.

활성화 뒤에는 **해당 시즌의 모든 점령/시즌 종료 쓰기를 `StatisticsPolicyTransaction`으로 한다.**
0034의 지연 제약 trigger는 활성화한 시즌에서 정책 사건이나 시즌 종료의 통계 변경이 빠지면
commit을 거절한다. 따라서 이전 어댑터를 잘못 섞어 쓰는 경우 조용히 통계를 누락하지 않는다.
활성화하지 않은 기존 시즌은 이 제약으로 새 통계 행을 요구하지 않는다.

실제 변경은 `policy:` + 기존 event ID로 기록하고, 초기화/종료는 각각 `initialized`, `season-closed`다.
정책의 UNCHANGED 영수증 재시도는 통계 사건을 추가하지 않는다. 이미 확정한 소유권/보너스를
통계 처리기가 다시 실행하는 경로는 없다. 초기화는 IMPORTED 구간을 열며 점령 횟수를 늘리지 않는다.

`capture_statistics_cut`은 같은 시즌 barrier 아래에서 서버 시각과 revision을 함께 기록한다.
시즌 종료 시각을 지났다면 시즌 확정 및 보유 구간 종료 근거를 먼저 같은 transaction에 남긴다.
그 뒤의 소유권 사건은 이전 확정 시각보다 과거이면 거절한다. 시계 역전 때 시간을 지어내지 않는다.
`confirm_territory`는 이 연결부가 사용하는 하위 포트다. 제품 요청이 임의 시각으로 호출하면 안 된다.

## 4. 산책 입력 연결

`append_walk(WalkSelection(...))`는 서버가 선택한 확정 분석을 저장하는 포트다. 원본 봉인과
선택 정책은 여전히 호스트 책임이다. Geo의 단일 dog 원본 모델을 DEV 다견 산책 테이블로 바꾸지 않았다.
DB 시나리오는 실제 정책 흐름과 정규화된 다견 산책 fixture를 사용하며, 실제 DEV 분석 생산자 연결은 S4다.

동일 revision/동일 값은 성공한 재시도로 처리하고, 다른 값과 revision 누락은 거절한다.
분석 교체는 새 revision이며 이전 기여분을 대체한다. 참여견 정정은 최신 연결 snapshot도 갱신한다.
옛 revision 재전송이 현재 참여 관계를 되돌리지 않는다. `source=None` 철회 뒤에는 기여분을 제거하고
이전 입력 재전달로 부활하지 않게 한다.

이 철회는 개인정보 물리 삭제 기능이 아니다. 과거 변경/근거와 연결 snapshot은 남는다.
DEV 이식 때 계정·반려견·산책 삭제 정책에 맞는 원본 제거와 재생 제외를 반드시 연결해야 한다.
0034는 무조건 불변 DELETE trigger를 추가하지 않았으나, FK 순서에 맞춘 실제 삭제 처리는 후속이다.

## 5. 처리, 조회, 재계산

```python
async with sessions.begin() as session:
    await PostgresStatisticsTransaction(session).register_generation(identity, analysis_versions)

await run_pending(sessions, identity.generation_id, limit=100)

async with sessions.begin() as session:
    tx = PostgresStatisticsTransaction(session)
    result = await tx.read(identity.generation_id, "TERRITORY", season_id)
    progress = await tx.progress(identity.generation_id, "TERRITORY", season_id)
```

`run_pending`은 한 번 실행하는 작업 함수다. 자체 daemon·스케줄러·공개 HTTP endpoint는 없다.
선택한 최대 개수의 스트림을 각각 별도 transaction에서 처리하고 갱신한 스트림 수를 반환한다.
중간 실패는 호출자에게 전파되며, 앞서 완료한 다른 스트림은 유지된다. 호스트가 오류를 기록하고
재시도/문제 입력 조사 정책을 붙여야 한다.

`read`는 저장된 기여분/보유 구간과 checkpoint에 해당하는 원본 근거를 읽는다. 읽을 때 통계를
재계산하지 않는다. 아직 결과가 없으면 None이다. `progress`는 영속 원본과 결과를 비교해
PENDING/STALE/READY와 source/applied revision을 반환한다. TERRITORY의 확인 시점은 보유 시간의
상한이며, WALK의 시간 필드 0은 측정 freshness가 아니다. 산책은 revision으로 반영 여부를 본다.
단말에서 아직 업로드하지 않은 산책까지 READY가 보증하지 않는다.

다른 generation을 등록하고 `run_pending`을 실행하면 기존 결과를 유지한 채 원본으로 재계산한다.
호출자가 검증한 generation ID를 명시해 읽는다. 제품의 기본 generation을 선택·공개하는 API는 S4/S5에서 정한다.

현재 runner는 한 walk/season의 전체 이력을 재생하는 **검증용 기준 구현**이다. 처리 중 해당
스트림의 생산자가 잠시 기다릴 수 있고, 한 generation의 작업도 직렬화된다. 대규모 운영에
그대로 매 요청 실행하지 않는다. 실제 데이터 규모에 맞춘 증분 처리/잠금 축소는 이 결과를
기준으로 대조하며 추가할 수 있다. 새 서비스나 메시지 브로커는 이 골격의 필수 조건이 아니다.

## 6. 검증 및 배포 순서

테스트는 기존 정책 DB fixture를 사용한다. 지정된 테스트 DB 안에 임의 이름의 schema를 만들고,
실제 Geo 장소 테이블 구조와 0033/0034를 적용한다. 종료 시 그 테스트 schema만 제거한다.

```powershell
# DAENGS_POLICY_TEST_URL은 명시적으로 선택한, 마이그레이션된 격리 테스트 DB URL이어야 한다.
uv run pytest -q tests/activity_statistics/test_postgres.py
uv run pytest -q tests/activity_statistics tests/territory/test_policy_integration.py tests/test_import_direction.py
uv run ruff check .
```

테스트 URL이 없으면 실제 DB 테스트는 skip하며, 설정했는데 연결/마이그레이션이 실패하면 실패한다.
CI는 PostGIS 서비스와 URL을 항상 제공하고 먼저 전체 Alembic migration을 수행한다.
이번 로컬 환경은 Docker 서버 오류로 실제 DB를 실행하지 못했으므로 실제 DB 통과 근거는 PR의 CI 결과로 남긴다.

실제 DB 테스트는 마이그레이션 왕복, 늦은 업로드, 원본/처리기 rollback, 잘못된 점령 writer의
commit 거절, 다중 연결 재시도, 지연 조회, baseline/시즌 종료, 새 generation 재생, 분석 교체/철회,
동시 세션 연결, 미commit 스트림의 다음 처리 발견, 원본 불변성을 확인한다. 별도 Python 프로세스가
새 DB 연결로 저장된 보유 구간을 읽어 동일 값을 반환하는 것도 검증한다.

운영 순서는 여전히 DB 준비·검증 → 서버의 생산자/처리기 연결 → APP 기능 활성화다.
DEV에는 기존 #260 및 산책 분석 테이블에 맞춘 FK/삭제/권한/확정 분석 어댑터를 별도로 구현한다.
0034를 운영 DEV DB에 그대로 실행하거나 Geo 실험 입력을 제품의 인증된 입력으로 간주하지 않는다.
