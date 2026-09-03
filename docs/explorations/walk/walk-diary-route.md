---
status: exploring
implementation: dev-lab-spike
last_verified: 2026-09-03
decision: ../../decisions/2026-09-03-walk-diary-route-privacy.md
research: ../../research/2026-09-03-walk-diary-route-privacy.md
---
# 단일 산책 일기 동선 — 선은 필요하지만 익명화됐다고 부르지 않는다

조건별 여러 산책은 Cellophane 면의 중첩으로 읽고, 날짜로 고른 한 산책은 시작·종료·사건 순서가
있는 선으로 읽는다. 이 둘은 비슷한 지도 위에 올라가도 질문과 개인정보 수명이 다르다.

단일 산책 선은 속도 같은 미시 흐름과 Pin의 순서를 보여 줄 수 있다. 반대로 현관에서 시작하는
좌표열이라 주거지 추론 위험도 가장 직접적이다. 단순화·양자화한 선을 `Cellophane보다 가벼운
좌표`라는 이유로 영구 저장하면 결정 #57과 #69의 경계를 이름만 바꿔 우회하게 된다.

## 현재 Lab

`/walk-trace-lab`은 같은 CanonicalTrail에 네 후보를 적용해 원본과 겹쳐 본다.

- `canonical-detail`: 비교 기준. 저장 후보가 아니다.
- `trim-60m`: 앞뒤의 누적 경로 거리만 자른다. 루프·왕복의 중간 재방문을 못 가린다.
- `zone-60m-q5-s5`: 시작·종료점 반경 60m와 교차하는 모든 선을 자른 뒤 조각을 분리한다.
- `zone-100m-q10-s8`: 더 큰 보호권과 더 거친 표시를 비교한다.

수치는 제품 기본값이 아니다. 두 반경은 작동 모양과 정보 손실을 비교하는 실험점이다. 상대
속도색도 한 세션 안의 분포를 보기 위한 실험값이며 행동 분류나 강아지 간 비교가 아니다.

Lab은 표시 점·JSON 바이트·남은 거리·P95 선 오차·시작점 최근접 거리·표시 조각 수를 함께
보여 준다. 보호권 때문에 전부 사라진 결과는 빈 산책으로 만들지 않고 `unavailable`로 둔다.

## 살아 있는 후보 계약

영속 여부를 다시 열게 되면 형태는 다음 조건부터 출발한다.

```text
WalkDiaryRoute candidate
  session_id
  source_calculation_version
  privacy_profile_version
  fragments[]
    source_chain_index
    points[lat, lng, elapsed_offset]
    speed_band_per_edge
  gaps[] = canonical gap | endpoint redaction | unavailable
```

- Canonical gap, accuracy 거부, jump, pause chain을 직선으로 잇지 않는다.
- 시작·종료 보호는 순서상 앞뒤만 자르는 것이 아니라 공간 교차를 전부 잘라야 한다.
- 보호권 중심 좌표는 저장물에 싣지 않는다. Lab에만 비교를 위해 나타난다.
- 절대 시각 대신 세션 시작 기준 경과 시간을 우선한다.
- 좌표 양자화와 Douglas–Peucker 단순화는 용량·표시 디테일 축소이지 익명화가 아니다.
- 이 선으로 Cellophane 통계나 권위 있는 점령 접촉을 판정하지 않는다.

## 아직 닫힌 부분

서버 DB·API·Capsule 필수 자식은 열지 않는다. 합성 경로는 기하 실패를 찾을 수 있지만 사용자가
어느 정도의 잘림을 받아들이는지, 실제 반복 산책에서 보호권의 빈 중심을 얼마나 쉽게 역추론할
수 있는지, 며칠 보관할지를 답하지 못한다. 다음 실험은 Android의 종료 직후 로컬 미리보기에서
실제 기기 trace로 반경·단순화 후보를 비교하는 것이다.
