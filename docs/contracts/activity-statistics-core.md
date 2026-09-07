---
status: implemented-in-geo
implementation: pure-core; geo-postgres-available; dev-app-adapters-pending
contract_version: activity-statistics.v1
last_verified: 2026-09-06
---

# 산책·점령 통계 코어 — 입력 계약과 이관 경계

[working skeleton 설계](../explorations/walk/statistics/activity-statistics-skeleton.md)의 S1·S2를 구현했다.
기존 ID 연결과 산책/점령의 순수 계산·재생까지 실행할 수 있다. S3의 저장·처리·Geo 정책
연결은 [PostgreSQL 계약](activity-statistics-postgres.md)에 추가했다. DEV의 실제 산책 분석/점령
생산자와 HTTP 조회·APP 표시는 아직 없다. 이 코어만 배포해서 제품 기능이 활성화되는 것은 아니다.

## 1. 파일과 책임

| 파일 | 구현한 것 |
|---|---|
| [common.py](../../app/features/activity_statistics/common.py) | 통계 버전/generation, 안정된 오류 코드, ID·정수 검증 |
| [sessions.py](../../app/features/activity_statistics/sessions.py) | 기존 산책/게임 snapshot의 연결과 충돌 판정 |
| [walk.py](../../app/features/activity_statistics/walk.py) | 확정 분석 head 선택, 기여분 교체/철회, 기간·참여견별 합산 |
| [territory.py](../../app/features/activity_statistics/territory.py) | 초기 소유권·획득·인증·탈취·종료 재생, 보유 구간과 시즌 통계 |
| [fixtures.py](../../tests/activity_statistics/fixtures.py) | 다견 산책, 지연 업로드, 점령 시간 흐름의 정규화 입력 |
| [test_scenario.py](../../tests/activity_statistics/test_scenario.py) | 기존 점령 정책 계산 결과와 두 통계/연결을 함께 검증 |

코어는 표준 라이브러리만 사용한다. 산책과 점령 projector는 서로 또는 기존 원본 생산자를
import하지 않는다. 테스트의 정책 결과 변환은 연결 형태의 검증이며 운영 어댑터 구현이 아니다.

입력은 인증된 서버 어댑터가 만드는 불변 dataclass다. **APP JSON을 직접 받는 검증기나 권한
검사기가 아니다.** 반환된 근거에는 owner·pet·세션 ID가 있으므로 API에서 그대로 외부 공개하지 않는다.

## 2. 세션 연결

`resolve_session_links(sources)`에 각 원본의 현재 `SessionSource`를 넣는다.

- 필드: `kind=WALK|GAME`, owner ID, client 산책 UUID, 서버 세션 ID, 시작 UTC epoch ms, 참여 pet 집합.
- client UUID는 표준 문자열로 정규화하며 기존 UUID 값을 교체하지 않는다. 서버 ID와 pet ID는
  어댑터가 검증한 불투명 문자열로 유지한다.
- `(owner_id, client_walk_session_id)`로 연결한다. 같은 client UUID라도 owner가 다르면 다른 활동이다.
- 게임만 있으면 `WAITING_FOR_WALK`, 산책만 있으면 `WALK_ONLY`, 양쪽이 일치하면 `LINKED`다.
- 시작 시각/참여견이 다르면 두 원본을 보존한 `CONFLICT`와 원인을 반환한다. 합집합으로 보정하지 않는다.
- 같은 종류의 서버 ID를 다른 연결에 재사용하거나, 한 연결에 같은 종류의 서버 ID 두 개를 넣으면
  `session_id_conflict` 또는 `session_link_conflict`로 실패한다. 동일 입력의 재전달은 결과를 늘리지 않는다.

이 함수는 현재 snapshot들의 결정론적 비교다. 변경 이력 저장, 동시 INSERT의 UNIQUE 보장,
원본 수정 후 link revision 갱신은 S3/S4 어댑터 책임이다. 같은 원본의 수정 전/후 snapshot을
동시에 넣어 자동으로 최신 것을 고르도록 사용하지 않는다. timestamp 비교는 epoch ms로 정규화한
정확한 일치이며, 근거 없는 오차 허용이나 시작 시각 추정은 하지 않는다.

## 3. 산책 입력과 분석 선택

`WalkStatSource`는 `WALK` 세션 snapshot에 아래 확정 근거를 결합한다.

| 입력 | 어댑터가 보장해야 할 의미 |
|---|---|
| `ended_ms` | 완료 산책 종료 시각 |
| `analysis_id`, `input_fingerprint` | 서버가 확정한 분석과 입력의 불변 identity |
| `AnalysisVersions(facts, calculation, receipt, capsule)` | 실제 선택한 원본 버전. fixture의 버전 숫자를 운영 기본값으로 복사하지 않음 |
| `receipt_id` | 해당 측정 receipt의 안정된 참조. 별도 DB PK가 없으면 분석 ID 기반으로 namespace를 정함 |
| `evidence_origin` | 원본의 device/mock/mixed/unknown 표식 |
| `WalkMetrics` 또는 `None` | canonical 이동거리(m), 이동시간(s), 정지횟수, 정지시간(s). 관측 불가면 None |
| `observation_reason` | 관측 불가일 때 필수인 receipt 기반 원인 코드 |

원본 분석/캡슐이 실제로 봉인됐는지, 관측이 가능한지와 참여견 소유 관계는 어댑터가 확인한다.
코어에서 GPS 필터나 새로운 관측 임계값을 만들지 않는다. 숫자는 canonical Facts와 같은
비음수 정수이며 이동·정지 시간 합이 반올림한 wall seconds를 넘을 수 없다.

`project_walks(selections, identity=..., expected_versions=...)`는 `WalkSelection`의 명시적 head
선택을 재생한다. revision은 owner/walk마다 1부터 연속인 **선택 스트림 번호**다. 분석 생성 시각,
분석 ID 정렬 순서, SQL sequence를 대신 넣지 않는다. 동일 revision에 동일 입력은 중복 제거하고,
다른 payload는 충돌로 처리한다. 빠진 revision이 있으면 부분 통계를 반환하지 않는다.

새 분석 선택은 이전 기여분을 대체한다. 참여견 정정은 같은 분석과 수정된 참여 snapshot을 새
revision으로 보낸다. 같은 analysis ID의 수치·버전·receipt·측정 기간을 변경하면 거절한다.
새 분석 ID여도 같은 walk의 owner/client UUID/시작·종료 시각을 묵시적으로 바꾸지는 못한다.

`source=None`은 해당 walk의 최종 철회다. 이후 같은 generation에서 복구 선택을 받지 않으며,
이전 선택이 재전달돼도 철회가 유지된다. 이는 개인정보 물리 삭제 구현이 아니다. 현재 재생 입력과
결과의 `selections`에는 과거 근거가 남는다. S3/S4에서는 기존 삭제 정책에 따라 원본·기여분을
제거하고 재생 대상에서도 제외해야 한다. 복구가 필요하면 별도 계약을 추가한다.

관측 집계는 `expected_versions`와 정확히 같은 버전, device 원본, 관측 가능한 metrics만 사용한다.
다른 입력도 완료 기록 수에는 남기며 `unsupported_analysis_versions`, `non_device_evidence`,
관측 원인 코드로 제외 건수를 반환한다. 판단 우선순위는 버전 → origin → 관측 가능 여부다.

`summarize_walks`는 owner, 선택적 pet, `[from_ms, to_ms)`의 **종료 시각**으로 산책을 고른다.
owner 합계는 다견 산책도 한 번이다. pet 합계는 그 강아지가 참여한 같은 측정을 참조한다.
관측 가능한 산책이 없으면 거리/시간/정지값은 null, 유효 관측이 0이면 숫자 0이다.
평균은 합산 거리/합산 이동시간이며 분모가 0이면 null이다. 버전, 제외 사유, 선택 revision과
원본 근거가 함께 반환된다. 이 결과만으로 업로드 누락이나 전체 최신 상태를 증명하지 않는다.

## 4. 점령 입력, 초기화와 확정 시점

`project_territory(events, identity=..., coverage=..., cut=...)`에 아래 세 가지를 전달한다.

1. `TerritoryCoverage`: 시즌 ID/시작/종료, 통계 관측 시작 `coverage_start_ms`, baseline 이전 revision.
2. `TerritoryStatEvent`: 시즌 내 연속 revision, 안정된 원본 event ID, 확정 시각, 사건 종류와 관계.
3. `ConfirmedCut`: 원본이 보증하는 시즌 revision과 `through_ms` 쌍.

사건은 covered stream 전체를 전달하며 순서가 섞이거나 중복돼도 된다. revision 누락,
동일 revision/event ID의 payload 충돌, 시각 역전, 이전 소유자 불일치는 실패한다.
cut보다 나중 사건을 같이 넣으면 `event_outside_cut`이다. 조회할 cut까지 잘라 읽는 일은 어댑터 책임이다.

| 종류 | 필수 근거/효과 |
|---|---|
| `INITIALIZED` | 첫 revision, coverage 시작 시각, 전체 초기 소유 목록(비어도 명시). IMPORTED 구간을 열고 획득 횟수는 늘리지 않음 |
| `OWNERSHIP_CHANGED` | 장소, 새 pet, 이전 pet 또는 None, 게임/claim ID, 결과 인증 상태. 이전 구간을 닫고 새 구간을 열며 획득/탈취 집계 |
| `CERTIFIED` | 현재 pet/이전 pet 일치, 인증 결과 true. 같은 보유 구간의 최초 인증 시각만 추가 |
| `UNCHANGED` | 현재 소유자와 인증 결과가 기존 상태와 같음. 보유 구간·횟수 변화 없음 |
| `SEASON_CLOSED` | 정확한 시즌 종료 시각. 모든 열린 구간을 닫으며 이후 사건은 거절 |

기존 정책의 `OwnershipPlan.kind`, before/after와 candidate의 원본 ID를 변환할 수 있다.
**verified는 요청의 인증 요구가 아니라 after 소유권의 결과 상태**다. 보호 시간과 사진 판정은
원본 정책이 이미 검증한 것으로 받아들이며 통계가 재판정하거나 점수를 지급하지 않는다.
기존 Geo 정책 어댑터 자체는 이 스트림을 만들지 않는다. S3의 `StatisticsPolicyTransaction`이
초기화/종료를 같은 transaction으로 연결하며, DEV 생산자 연결은 S4에서 별도로 구현한다.

보유 구간 ID는 `(season_id, start_event_id, site_id)`다. 인증 강화에도 획득 당시 game/claim과
구간 ID를 유지한다. 인증 사건은 projection의 원본 사건 목록에서 추적한다. IMPORTED에는 새
획득 game/claim을 지어내지 않는다. 과거 소유 시간도 coverage 시작 이전으로 확장하지 않는다.

cut은 caller가 현재 시각과 마지막 처리 ID를 조합해서 만들면 안 된다. 생산자 transaction의
시즌 barrier 아래에서 확정한 일관된 기준점이어야 한다. 코어는 그 revision까지 사건이 모두
있는지 확인하지만 **기준점 자체의 진실성은 검증할 수 없다.** Geo의 기준점 생성/저장은
[S3 연결부](activity-statistics-postgres.md)에서 제공하며 코어 함수 자체가 원본 잠금을 잡지는 않는다.

`summarize_territory`는 coverage 시작부터 확정 cut까지의 pet/season 획득·탈취·보유·인증 보유·
현재/최대 동시 보유를 반환한다. 시즌 종료 후 열린 구간은 없고 현재 수는 0이다. coverage가
시즌 중간부터면 peak도 그 관측 범위의 최대값이며 과거 시즌 전체 최대라고 표시하지 않는다.
동일 ms의 사건은 revision 순서로 적용한다. `holding_time`은 개별 구간의 `[from,to)` 교집합
계산 도구이며, 열린 구간의 to에는 확인된 cut 이하의 시각만 전달해야 한다.

## 5. 실행과 검증

```powershell
uv run pytest -q tests/activity_statistics
uv run pytest -q tests/activity_statistics tests/territory_game/test_policy_integration.py tests/walk/test_walk_contract.py tests/walk/test_canonical_trail_boundary.py tests/test_import_direction.py tests/test_script_imports.py
uv run ruff check .
```

2026-09-06 로컬 검증: 신규 60개 및 관련 회귀/경계 테스트 포함 **167개 통과**, ruff 전체 통과.
첫 시나리오는 실제 기존 정책 함수의 결과를 통계 입력으로 변환해 P1 보유 10분/인증 8분,
P2 보유 8분, 완료 산책 한 번/400m를 확인한다. 중복·역순 재생, 다견/무견, 분석 교체·철회,
관측 제외, baseline·시즌 종료, 같은 시각의 사건 순서와 누락된 cut을 검증한다.

이 결과는 메모리 순수 계산의 검증이다. PostgreSQL transaction, 재시작 복원, producer 동시성,
운영 권한/삭제와 APP 동작을 검증했다는 의미가 아니다.

## 6. 저장 구현과 제품 이식 시 해야 할 일

아래 S3는 [PostgreSQL 구현](activity-statistics-postgres.md)에서 진행했다. S4/S5는 아직 후속이며,
원본 권한·삭제와 운영 규모의 처리 최적화는 Geo의 DB 테스트로 대체하지 않는다.

- S3: 세션 연결 UNIQUE, 원본 변경/기여분/보유 구간/처리 영수증 저장, migration, 어댑터와 runner.
  원본 변경 기록과 producer 확정을 묶고, projection·영수증·checkpoint도 원자적으로 저장한다.
  generation ID에 통계 버전/expected analysis versions/coverage를 불변으로 연결한다.
- S3: 전체 재생 함수로 작은 기준 결과를 만든 뒤 DB 처리 결과를 대조한다. 현재 함수는 전체
  이력을 메모리에서 정렬하는 reference 구현이므로 대규모 매 요청 재생으로 운영하지 않는다.
- S3: 실제 PostgreSQL에서 중복 전달·중간 실패·재시작·새 generation 재생과 cut 생성/반영을 검증한다.
- S4: DEV의 확정 분석/캡슐을 읽는 다견 어댑터, #260 확정 소유권 흐름, baseline/종료 근거를 연결한다.
  현재 함수에 원본 JSON이나 Geo 단일 dog Facts를 그대로 전달할 수 있다고 가정하지 않는다.
- S4/S5: 권한·개인정보 삭제·source 생존 검사, DB 읽기와 반영 상태 API, APP 표시를 구현한다.

이 범위에서 아직 제공하지 않는 것: 활동 시간대별 거리/활동일, 행동 해석, 지역 비교,
랭킹 snapshot, 칭호 수여와 제품 API. DB 반영 상태와 checkpoint 영속화는 S3에서 추가했다.
