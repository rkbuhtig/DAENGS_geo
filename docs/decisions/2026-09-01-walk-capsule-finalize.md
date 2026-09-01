---
status: adopted
decision: 75
adopted_at: 2026-09-01
---
# 산책 finalize는 8u Cellophane과 원시 영수증·문맥을 봉인한 뒤에만 원좌표를 지운다

결정 #69는 원좌표 purge 뒤 남길 공간 형태를 산책별 `occupancy + peak` Cellophane으로
정했지만, 격자와 붓이 결정 문서로 서기 전에는 실사용 저장을 열지 말라는 게이트를 남겼다.
결정 #74는 Capsule manifest와 MeasurementReceipt·TrailContext의 객체 경계를 정했지만 실제
finish 트랜잭션과 DB 형태는 정하지 않았다. 이 결정이 두 경계를 실제 쓰기 경로로 닫는다.

## 결정 1 — 첫 영구 Paint 세대는 `8u + NARROW_STEP`

```text
paint_version   2
grid_version    hex-v1
radius_u        8.0
profile         NARROW_STEP = 계단 3·8·20m
sample_step_m   1.5
paint_fp        위 실제 값들의 지문
```

8u는 취향으로 고른 값이 아니다.

- [연속 Field 비교](../research/2026-08-31-continuous-hex-comparison.md)에서 4u는 8u보다 Cell 수가
  약 4배였고, 12u는 상위 질량 영역 경계가 더 무뎠다. 8u는 비용과 왜곡의 중간점이었다.
- [보수적 복원 holdout](../research/2026-09-01-conservative-hex-reconstruction.md)에서 8u는 고정
  `1.75 cell` 표시 복원으로 `normalized L1 <= 0.18`, 50% 영역 IoU `>= 0.70`을 재튜닝 없이
  통과했다.
- [센서 오염 평가](../research/2026-09-01-sensor-robustness.md)는 같은 8u에서 질량·support
  불변식을 지켰다. 동시에 drift는 고치지 못한다는 한계도 확인했다.

따라서 8u는 drift 보정값이나 실제 위치 정확도 주장이 아니다. 실제 기기 자료가 이 선택을
뒤집으면 옛 장을 다시 칠하지 않고 새 `paint_fp` 세대로 쌓는다. 표시용 보수적 복원 Field도
영구 저장하지 않는다.

canonical painter의 코드 소유권은 `features.walk.paint`다. 원좌표 생존 구간과 purge를 소유한
생산자만 영구 장을 만들 수 있기 때문이다. `features.territory.paint`는 기존 읽기 표면을
재수출하고, territory는 봉인된 장을 겹치는 downstream 소비자로 남는다. 이 방향은 결정 #67의
형제 기능 DAG(`territory → walk`)를 거꾸로 만들지 않는다.

## 결정 2 — Capsule은 자식 행과 마지막 manifest다

DB 저장 형태는 다음이다.

```text
walk_session
├─ walk_facts / motion_event / encounter / micro_observation
├─ walk_cellophane_sheet
│  └─ walk_cellophane_cell[]       q, r, occupancy_s, peak
├─ walk_measurement_receipt
├─ walk_trail_context
└─ walk_capsule_manifest           마지막 seal
```

Cellophane을 JSON bundle 하나로 넣지 않는다. 장의 계산 identity와 셀 값을 분리해 여러 장의
공간 질의를 다시 할 수 있게 한다. 모든 테이블은 `walk_session ON DELETE CASCADE` 자식이다.

manifest의 `capabilities`는 현재 generation이 `low_motion`·`gap`을 다시 읽을 재료를
보존했다는 선언이다. 실제 관측 행이 0개여도 capability는 존재한다. `0개 관측`과
`그 generation을 지원하지 않음`을 구별하기 위해서다.

## 결정 3 — finalize와 purge는 한 DB 트랜잭션이다

순서는 고정한다.

```text
session row lock
→ facts / macro / micro 계산
→ context best-effort capture
→ facts·event·encounter·micro 저장
→ Cellophane 저장
→ MeasurementReceipt 저장
→ TrailContextSnapshot 저장
→ WalkCapsuleManifest 저장
→ raw walk_fix 삭제
→ session state = purged
→ commit
```

manifest 쓰기까지 어느 단계에서든 실패하면 트랜잭션 전체를 rollback한다. `walk_fix`는 남고
세션은 `open`으로 돌아간다. manifest가 있는데 필수 자식이 없거나, 자식 일부만 남았는데 fix가
지워지는 상태를 만들지 않는다.

같은 finish 재요청은 이미 저장된 `walk_facts`를 반환하고 다시 칠하거나 외부 문맥을 다시
조회하지 않는다. 이미 purge된 구세대 세션에 Capsule을 복원한 척 backfill하지도 않는다.

## 결정 4 — MeasurementReceipt는 purge 전 transient 집합에서 만든다

`FixQuality.accepted` 숫자만으로 accepted accuracy 분포를 역산하지 않는다. 계산 중 수용된 fix
집합을 transient 값으로 넘겨 다음 둘을 각각 동결한다.

```text
reported accuracy  서버가 받은 fix 중 accuracy를 보고한 분포
accepted accuracy  시간·accuracy 입구를 통과한 fix 중 보고한 분포
```

수용 fix 자체는 저장하지 않는다. count와 p50·p90을 만든 뒤 원좌표와 함께 사라진다. canonical
segment 시간, gap 경과 시간, 세션 벽시계 시간도 비율로 접지 않고 별도 분자로 남긴다. drift는
현재 휴대폰 fix만으로 평가하지 않았으므로 `not_assessed`가 기본이다.

## 결정 5 — 외부 문맥 실패는 Capsule 실패가 아니다

문맥 제공자는 산책 중간 시각과 그 시각에 가장 가까운 수용 fix를 입력으로 받는 주입 경계다.
현재 제품 조립에 제공자가 없으면 `unknown`, 호출 예외·잘못된 세션 응답은 `failed`와 정규화된
오류 종류로 저장한다. 외부 예외 원문은 키·URL·payload를 포함할 수 있어 저장하지 않는다.

```text
unknown  조회 제공자가 조립되지 않았거나 값을 확보하지 않음
failed   조회를 시도했지만 실패함 — provider + provider_error:<ExceptionType>
```

둘 다 `dry`, `clear`, `day`로 해석하지 않는다. 문맥 실패 때문에 raw fix가 무기한 남거나 정상
산책 finish가 실패해서도 안 된다. 실제 날씨 provider와 Usage Gate 조립은 별도 PR이다.

## 외부 API 경계

`WalkFacts` outbound 필드와 `/walk/.../finish` 응답은 바꾸지 않는다. Capsule은 아직 내부 쓰기
모델이다. 다음 일기 PR이 Offer를 만들 때 manifest·micro·context를 내부에서 읽는다. 일기 문장,
행동 의미, Pin은 이 finalize 경로에 넣지 않는다.

## 이 결정이 정하지 않는 것

- 실제 TrailContext 제공자와 외부 API
- Candidate 점수와 Offer 개수
- Attestation·Pin HTTP/DB 계약
- Spatial Diary 조회 API와 지도 UI
- 보관 일수·집 주변 마스킹·외부 공유
- Event Context와 사진·메모

## 이 결정이 바뀌어야 하는 신호

- 실제 기기 산책에서 8u의 비용·왜곡 곡선이 합성 holdout과 다르다
- Cellophane 셀 행 수가 운영 DB 질의·저장 비용을 감당하지 못한다
- finish 중 외부 문맥 조회가 row lock 지연을 실제로 만든다
- p50·p90만으로 품질 정책이 필요한 분포 꼬리를 설명할 수 없다
- 필수 자식 집합이 늘어 manifest seal 순서를 바꿔야 한다
