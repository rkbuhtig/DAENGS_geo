---
status: adopted
decision: 67
adopted_at: 2026-08-26
---
# 패키지 축은 넷이다 — 최상위 신설은 결정을 거친다

`app/` 최상위가 패키지 13개(+ 에셋 `static/`)가 됐다. 문제는 개수가 아니라
**나누는 기준이 섞인 것**이다.
`core`·`providers`·`usage`·`api` 는 기술 계층이고, `geo`·`place`·`journey`·`profile` 은
도메인이고, `features/*` 는 수직 기능인데, `planning`·`refine`·`scene`·`ingest` 는 또
워크플로·소비자·ETL 이라는 다른 축이다. 이 넷이 한 레벨에 나란히 서 있다.

기준이 없으면 새 개념이 생겼을 때 "이건 어디 들어가지"에 구조가 답을 못 준다. 그래서
최상위를 하나 더 발급하는 쪽으로 흘렀다. `place`·`planning`·`scene` 이 그렇게 생겼다.
`place` 는 결정 #65 를 업고 917줄의 도메인으로 자랐지만 `planning`(602줄)과
`scene`(54줄)은 그렇지 않다 — 최상위 자리를 받을 만큼의 독립된 책임이 아니었다.

증거가 코드에 남아 있다. `app/planning/plans.py:23` 이다.

```python
Companion = str  # journey.models.Companion 과 같은 값. 순환 import 를 피한다
```

타입을 `str` 로 뭉개서 순환을 피하고 있다. 경계가 틀렸다는 것을 코드가 이미 알고 있었고,
구조를 고치는 대신 타입을 버리는 쪽을 택한 기록이다.

이 결정은 기능을 바꾸지 않는다. 패키지 소유권과 import 방향만 정하고, 그 규칙을 테스트로
잠근다.

## 결정

### 1. 축은 넷이다

| 축 | 패키지 | 무엇인가 |
|---|---|---|
| 기반 | `core` | config·db. 아무도 모른다 |
| 인프라 | `providers` `usage` | 외부 세계의 어댑터와 그 정책 |
| 도메인 | `profile` `geo` `discovery` `place` `journey` | 제품 어휘 |
| 진입점 | `api` `features` `ingest` `wiring` `main` | 바깥에서 안으로 들어오는 문 |

`ingest` 는 인프라가 아니라 **batch 진입점**이다. HTTP 가 `api`·`features` 로 들어오듯
`python -m app.ingest` 로 들어온다. `ingest/anchors.py:29` 가 `geo.cells` 를 쓰는 것은
위반이 아니라 진입점이 도메인을 조립하는 정상 동작이다. 그래서 `ingest` 는 최상위에 남고
`place` 밑으로 내려가지 않는다.

### 2. 화살표는 진입점 → 도메인 → 인프라 → core 한 방향

**이것은 clean architecture 가 아니다.** 도메인이 인프라를 직접 안다 —
`geo/search.py:18` 이 `providers.base` 의 `LatLng`·`MapMarker` 를,
`journey/models.py:12` 가 `Mode`·`RouteStatus` 를 가져간다. 이 규모에서 port/adapter 를
끼우는 것은 과잉이다. 실용적 layered 구조이며, 문서에서 "도메인은 인프라와 무관하다" 같은
말은 하지 않는다.

### 3. `*/contract.py` 는 선언된 잎이다

패키지 간 역방향 에지는 **contract 로 향하는 것만** 허용한다. contract 는 `core` 와 다른
패키지의 contract 만 import 하고 로직을 담지 않는다.

계약의 주인은 그것을 **실행하는 쪽**이다. 지금 `planning/plans.py` 에 세 실행자의 입력이
한 파일에 섞여 있다.

```
SearchPlan · SearchMust · SearchPrefer   → geo.search 가 실행     → geo/contract.py
JourneyPlan · WalkPlan · Companion       → journey.engine 이 실행 → journey/contract.py
RuntimeFacts · ViewPlan                  → resolver 의 입력·출력  → discovery 에 남는다
```

`RuntimeFacts` 는 `now`·`DogProfile`·`OwnerProfile`·`temp_c`·`urgency_signals` 다.
이번 요청에 대해 서버가 아는 것이지 공간 어휘가 아니므로 `geo` 로 보내지 않는다.
`Companion` 은 `Literal["dog", "none"]` 이고 "이번 이동에 개가 동반하는가"를 뜻한다.
프로필 종류가 아니므로 `profile` 로 보내지 않는다 — `none` 프로필은 없다.

이 규칙으로 `discovery ↔ journey` 는 순환이 아니게 된다. `discovery.resolver` 는
`journey.contract` 를 향하고(역방향, contract 이므로 허용), `journey.api` 는
`discovery` 를 향한다(순방향).

### 4. HTTP 엔드포인트 소유

```
features/*/api.py   사용자 워크플로 — 편집·기록·행동을 동반하는 것
app/api/*           공용 조회 어댑터 — places · anchor · static_map
```

`app/api` 를 없애는 것은 목표가 아니다. `place` 는 resolver·contracts 를 가진 도메인
패키지라, 조회 엔드포인트를 `features/place` 로 승격하면 place 가 두 곳으로 찢어지거나
도메인과 기능의 경계가 다시 흐려진다. 목표는 폴더 제거가 아니라 **어떤 엔드포인트가
feature 인가**의 규칙이다.

`main.py:11·14-17` 이 지금 세 곳에서 라우터를 가져온다. 이 규칙을 적용하면
`journey/api.py` 하나가 위반으로 남는다 — 도메인 패키지 안의 워크플로 엔드포인트다.
알려진 위반으로 기록하고 별도 PR 에서 처리한다.

### 5. 최상위 패키지 신설은 결정 문서를 거친다

새 최상위는 위 네 축 중 하나에 속함을 증명해야 만들 수 있다. 이 조항이 없으면 정리 직후
다시 13 → 14 → 15 로 는다.

## 목표 구조

```
app/
├── core/          config · db                          아무도 모름
├── providers/     base(계약) · kakao · naver · tmap · fake
├── usage/         gate · policy · ledger · metered · http
├── profile/
├── geo/           contract.py(SearchPlan 계열) · search · cells · ranking …
├── discovery/     state · facts · semantics · resolver · trace
│   └── refine/    engine · tools · diff · actions · labels · nl(parked)
├── place/
├── journey/       contract.py(Companion · WalkPlan · JourneyPlan) · engine · models …
├── features/      hospital/ · pharmacy/ · walk/ · scene/
├── ingest/        batch 진입점
├── api/           공용 조회 어댑터
├── wiring.py      composition root — 모두를 안다
└── main.py        wiring 을 호출한다
```

`planning` 과 `refine` 은 다른 bounded context 가 아니라 한 컨텍스트를 읽기/쓰기로 찢어
놓은 것이다. README 가 이미 `refine/` 을 "state(target/journey/view) · tools · nl · diff"
한 덩어리로 서술하는데 `state.py` 는 `planning/` 에 있다. 합치고 `discovery` 로 부른다 —
`search` 가 아닌 이유는 `EditableState` 에 `journey`·`view` 가 함께 들어 있고
`/journey` 도 같은 resolver 를 쓰기 때문이다. 결정 #65 의 place-first discovery 와도
어휘가 맞는다.

`scene` 은 `features/` 로 내려가되 `walk` 와 **형제로 남는다.** `features/walk/__init__.py`
가 "수집한다. 판정·보상·서술·알림은 하지 않는다"고 못 박은 경계는 결정 #51 의 산물이다.
54줄이라고 `walk/judgment.py` 로 넣으면 파일은 줄지만 생산자와 소비자의 경계가 흐려진다.

`wiring.py` 는 `core/` 안이 아니라 최상위다. core 는 아무도 모르는 층인데 composition
root 는 모두를 알아야 한다 — `core/wiring.py` 로 두면 import 방향 테스트에 예외를 하나
달고 시작하게 된다.

```
core            아무도 모름
infra · domain  core 를 앎
wiring          모두를 앎
main            wiring 을 호출
```

## 이행 순서

| PR | 내용 | 완료 조건 |
|---|---|---|
| 1 | `providers.registry` 의 조립을 `app/wiring.py` 로 | `git grep 'from app.usage' app/providers/` 0건 |
| 2 | 계약 소유권 분할 (§3) | `plans.py:23` 의 `Companion = str` 별칭·주석 삭제 |
| 3 | `planning` + `refine` → `discovery` | `git grep 'app\.planning\|app\.refine'` 전체 0건 |
| 4 | `scene` → `features/scene` | — |
| 5 | import 방향 테스트로 잠금 | 아래 게이트 통과 |
| 6 | API 소유 집행 (§4) | 별도 트랙 |

순서가 강제인 이유: 계약이 먼저 빠져야 3의 diff 가 순수 이동으로 읽히고, 방향 테스트는
위반이 0일 때만 넣을 수 있다.

모든 PR 은 **행동 변화가 0**이다. 테스트가 import 경로 갱신 외의 수정 없이 통과하는 것이
각 PR 의 기본 완료 조건이고, 테스트 본문을 고쳐야 통과한다면 이동에 변경이 섞인 것이다.

### 검증 게이트

`pytest` 는 실행되지 않는 CLI·문서·문자열 module path 를 보지 못한다. 이번 조사에서
`ingest/anchors.py` 가 import 그래프 분석에서 빠졌던 것과 같은 사각지대다.

```
uv run pytest -q
uv run ruff check .
python -m compileall -q app
uv run python -m app.ingest --help
git grep -n 'app\.planning\|app\.refine\|app\.scene'   # docs · tools 포함 전체
```

## 하지 않는 것

- **port/interface 분리** — §2. 이 규모에서 과잉이다
- **`app/api` 소멸** — §4. 규칙이 목표이지 폴더 제거가 목표가 아니다
- **`usage` 를 `providers` 밑으로** — usage 는 "돈 드는 외부 호출의 정책·계량"이고 지도
  provider 전용이 아니다. `refine/nl.py`·`journey/engine.py`·`features/hospital/api.py`·
  `api/static_map.py` 가 직접 쓴다. providers 가 usage 의 부모가 될 관계가 아니다
- **`RuntimeFacts` → `geo`, `Companion` → `profile`** — §3. 순환만 보고 옮기면 새 구조가
  처음부터 거짓말을 한다
- **패키지 병합으로 개수 줄이기** — 9개인데 소유권이 틀린 것보다 11개라도 기준이 명확한
  편이 낫다
