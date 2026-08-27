---
status: accepted
date: 2026-08-27
decision: README.md #70
---

# 병원은 Place로 찾되 UI에서는 바로 들어간다

## 문제

병원은 다른 장소보다 빨리 접근할 이유가 있다. 사용자가 병원을 찾으려고 먼저 "시설"을 열고
그 아래 분류를 탐색하게 하면 의도에 비해 단계가 많다. 그렇다고 병원 전용 검색 계약을 유지하면
웹과 Android가 공유해야 할 장소 identity·미상 처리·거리순 의미가 다시 갈라진다.

현재 Android의 `병원 상담` 화면은 `POST /hospital/search`의 별도 결과·선택·검색 위치 상태를
관리한다. 응답의 `reply`, suggested action, 전화 CTA를 표시하지만 제품 앱에는 자연어
`utterance` 입력이 없다. 자연어 refine는 `/dev` 검증 표면에만 있고 결정 #51 이후 parked다.
그러므로 현재 표면은 선택한 병원에 대한 상담이라기보다 **대화형 병원 후보 검색기**다.

분류와 진입 동선을 같은 것으로 보면 두 극단만 남는다.

- 병원을 `facility` 아래에 넣어 공통 장소 어휘를 다시 기반 테이블 구조에 종속한다.
- 병원 바로가기를 없애고 모든 장소를 같은 깊이의 탐색 UI로 강제한다.

둘 다 필요하지 않다. 제품 분류와 바로가기는 서로 다른 축이다.

## 결정

### 1. 병원은 `PlaceKind.HOSPITAL`이다

병원의 검색 후보군, identity, 사실과 순서는 `POST /v2/places/search`가 소유한다. Android와 웹은
병원을 찾을 때 `kinds=["hospital"]`을 명시한다. `facility`는 KCISA/KTO 기반층의 구현 이름이지
제품의 상위 분류가 아니다.

병원도 다음 공통 계약을 바꾸지 않는다.

- 외부 identity는 `(source, ref)`다.
- 카테고리는 원천 분류를 정규화한 `kind`다.
- 기본 정렬과 실제 적용한 정책은 응답 metadata가 말한다.
- 운영시간 등 모르는 사실은 `null`이며 부정으로 바꾸지 않는다.
- 웹과 Android의 같은 검색 의도는 같은 후보군과 의미를 쓴다.

### 2. 병원 바로가기는 탐색 축이 아니라 진입점이다

Android의 지도·홈 표면에는 `동물병원` 직통 진입을 유지한다. 이 버튼은 별도 병원 검색을
호출하지 않고 canonical Place 화면을 `hospital` kind로 연다. 일반 장소의 카테고리 칩에서도
같은 hospital 후보군에 들어갈 수 있다.

```text
일반 장소 둘러보기 ─┐
                    ├─ Place discovery — kind=hospital
동물병원 바로 찾기 ─┘
```

진입점이 둘이어도 검색 세션과 선택 identity는 하나다. 바로가기라는 이유로 병원 전용 위치,
마커, 결과 목록을 다시 만들지 않는다.

### 3. 병원의 차이는 검색이 아니라 결과 action에 둔다

병원 Place를 선택했을 때 전화와 길찾기를 우선 노출하고, 운영시간 미상·출처·기준일을 정직하게
보여줄 수 있다. 이 action은 병원 후보를 고르거나 순위를 바꾸지 않는다.

표현 정책은 kind마다 달라도 된다. 공통이어야 하는 것은 화면 모양이 아니라 장소 사실과 검색
의미다. 카페가 홈페이지·동반 조건을 앞세우고 병원이 전화·운영정보 주의를 앞세워도 같은
Place 계약을 소비할 수 있다.

검증되지 않은 응급 가능 여부, 진료 능력, 과목을 버튼이나 경고 문구가 만들어내지는 않는다.
전화 CTA도 "이 병원이 응급 진료를 한다"는 판정이 아니라 방문 전 직접 확인하는 행동이다.

### 4. legacy 병원 검색기는 퇴역 대상이다

`POST /hospital/search`, Android `HospitalRepository`와 별도 hospital state를 새 이름으로
"상담"이라 포장해 유지하지 않는다. Android의 병원 직통 진입과 병원 action을 canonical Place로
옮긴 뒤 소비자가 없어진 순서대로 제거한다.

미래에 실제 병원 상담 기능을 채택한다면 장소 발견을 다시 소유하지 않는다. 사용자가 고른
`PlaceKey(source, ref)`를 입력으로 받아 그 장소에 대한 후속 capability로 설계하고, 근거 없는
의료 판단을 Place 사실처럼 저장하지 않는다.

## 구현 순서

1. Android의 `병원 상담` 진입을 `동물병원` 바로가기로 바꾸고 canonical Place 검색의
   `hospital` kind를 연다.
2. canonical 병원 카드에 전화와 운영정보 미상 안내를 연결한다. 길찾기는 공용 journey 경계를
   재사용한다.
3. Android의 `HospitalApi`·`HospitalRepository`·별도 결과/선택/검색 위치 상태를 제거한다.
4. 소비자가 없어진 `POST /hospital/search`와 `/dev` 전용 병원 검색 표면을 제거한다.
5. 자연어 refine·suggested actions 등 남은 parked 코드와 테스트는 실제 소비자를 다시 감사한 뒤
   별도 PR에서 제거한다.

각 단계에서 Android 병원 바로가기가 동작하는 동안 서버 계약을 먼저 지우지 않는다.

## 현재 구현 상태

이 문서는 경계를 결정했으며 Android 전환은 아직 구현하지 않았다. 현재 `병원 상담` 탭과
`HospitalRepository`, `POST /hospital/search`는 기존 동작을 유지한다. 다음 PR은 구현 순서 1~2,
즉 직통 진입을 canonical hospital 검색에 연결하고 병원 action을 옮기는 작업이다.

## 하지 않는 것

- 병원을 `facility` 아래 제품 분류로 되돌리지 않는다.
- 병원과 다른 kind를 하나의 전역 순위에서 경쟁시키지 않는다.
- 직통 버튼을 응급도 판정이나 응급 병원 보증으로 표현하지 않는다.
- legacy `/hospital/search`를 경로만 바꿔 상담 API로 선언하지 않는다.
- 이 결정만으로 새로운 의료 상담이나 AI 제안 기능을 채택하지 않는다.

## 기존 결정과의 관계

- 결정 #65의 Place 최상위 도메인과 웹·Android 공통 검색 의미를 유지한다.
- 결정 #46의 첫 Android 병원 전용 절단면 중 전화 action은 보존하지만, 검색·지도 상태는
  canonical Place로 대체한다.
- 결정 #51의 코어 범위를 따른다. 자연어 refine와 suggested actions는 이 결정으로 재채택되지
  않는다.
- 결정 #32의 전화 안전 표면은 진료 능력 판정이 아니라 사용자 확인 action으로만 이어받는다.
