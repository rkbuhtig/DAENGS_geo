# Context Plane v0

Context Plane은 날씨·프로필·측정 품질 같은 판단 재료를 여러 제품 기능이 같은 방식으로
소비하기 위한 경계다. `Environment` 하나에 전부 섞지 않는다. 외부 세계, 주체, 측정은 같은
판단 평면에서 만나지만 출처·시간·권위가 다른 사실이다.

```text
Provider → typed ContextAtom → derived ContextFacet → purpose Lens → policy/LLM
```

이 계약은 `app/context_plane/contract.py`, 닫힌 registry와 Lens는
`app/context_plane/registry.py`가 고정한다. 기존 기능 객체의 변환은 응용층
`app/features/context_plane/adapters.py`가 담당한다.

## v0 capability

| capability | namespace | payload | v0 원천 |
|---|---|---|---|
| `world.dynamic.trail_weather` | `world.dynamic` | 강수·기온·습도·태양고도 | `TrailContextSnapshot` adapter |
| `subject.dog_profile` | `subject` | 최소 동결 snapshot 또는 불변 revision ref | 외부 `DogProfile` adapter |
| `measurement.walk_quality` | `measurement` | fix·거부·break·시간·accuracy·drift 원시값 | `MeasurementReceipt` adapter |

`world.spatial`, `actor_session`, `historical` namespace는 이름만 예약한다. 토지피복·수변·시설·
Memory Place 전기는 각자 타입과 provenance가 확정될 때 capability를 추가한다. 임시
`dict[str, Any]`나 API 응답 원문을 먼저 넣지 않는다.

Capability ID는 enum과 불변 registry의 닫힌 집합이다. 호출자나 LLM이 새 문자열 capability를
등록할 수 없다. payload도 discriminated union이며 모든 모델은 `extra=forbid`, `frozen=true`다.

## Atom

`ContextAtom`은 원천 사실과 그 확보 상태를 보존한다.

```text
atom_id / capability_id / schema_version
target
status / typed payload
provider / source authority / source ref
source_observed_at / source_as_of / captured_at
spatial support / temporal support
bounded failure_code
```

상태는 다음을 합치지 않는다.

| 상태 | 뜻 | payload |
|---|---|---|
| `known` | 등록된 원천값을 확보 | 필수 |
| `partial` | 일부 축만 확보 | 필수 |
| `unknown` | 정상 응답이지만 값 미상 | 없음 |
| `not_fetched` | 호출하지 않음 | 없음 |
| `not_applicable` | 대상에 적용되지 않음 | 없음 |
| `fetch_failed` | 제공자 호출 실패 | 없음 + failure code |
| `parse_failed` | 응답 해석 실패 | 없음 + failure code |
| `conflicted` | 원천 간 충돌 | 없음 |

실패 원문은 Atom에 넣지 않는다. `failure_code`는 등록 가능한 짧은 식별자뿐이다. Provider는
“비 오는 날”이나 “산책하기 좋음”을 반환하지 않고 `precipitation_mm=1.2` 같은 원천값만 준다.

## Facet

Facet은 Atom을 현재 정책으로 분류한 재계산 값이다.

```text
ContextAtom                    frozen
ContextFacet + policy_version  derived
```

v0는 강수 `rain|dry|unknown`, 일광 `day|night|unknown`, 사건 시점 나이, drift 평가 Facet만
등록한다. 각 Facet은 `evidence_atom_ids`를 반드시 가진다. 날씨 기준이나 생애 단계 정책이
바뀌어도 과거 Atom을 수정하지 않는다.

## Profile 시간축

Profile은 현재값으로 과거 산책을 덮어쓰지 않는다.

```text
walk_time  과거 산책·Episode·Journal·Memory Place
current    현재 Route 추천 요청
```

과거 Lens는 `walk_time`, Route Lens는 `current` payload만 허용한다. 동결 snapshot은 이름,
temperament, 자유 서술, 견주 속성을 복사하지 않고 실제 판단에 쓰는 birth date·체중·크기·명시
건강 flag·활동 수준만 가진다. 나이는 저장된 현재 `age_years`가 아니라 `birth_date + event_at`으로
Facet에서 계산한다.

외부 프로필 서비스가 버전별 불변 조회를 보장하면 `SubjectProfileRevisionRefV1`을 쓸 수 있다.
그 보장이 없으면 실제 사용한 최소값을 `SubjectProfileSnapshotV1`로 동결한다.

## Purpose Lens와 용도

| Lens | 필수 | 선택 | 허용 용도 |
|---|---|---|---|
| Episode Review | measurement | weather, walk-time profile | filter, describe |
| Walk Journal | weather | walk-time profile, measurement | describe |
| Memory Place Biography | weather, measurement | walk-time profile | filter, describe, compare |
| Route Recommendation | weather, current profile | 없음 | filter, describe, recommend |

모든 v0 Lens에서 `causal_claim`과 `safety_gate`는 금지한다. Route의 `recommend`는 선택지 조합과
설명을 허용한다는 뜻이지 의료·안전 판정을 LLM에 넘긴다는 뜻이 아니다. 고위험 gate는 별도의
검증된 정책 엔진이 근거를 확인한 뒤 수행해야 한다.

LLM은 capability를 제안할 수 있지만 registry 밖의 정보를 요청할 수 없고, Bundle에 실제로
들어온 Atom만 소비한다. 표시할 설명은 `ContextEvidenceReceipt`로 다음을 남긴다.

```text
bundle_fingerprint / request_fingerprint
registry_version / lens_id / lens_version
use / evidence_atom_ids
```

Bundle fingerprint는 caller의 bundle ID와 입력 순서가 아니라 정규화된 내용으로 계산한다.
같은 재료·Lens·시각이면 같은 지문이 된다.

## 개인의 속마음

속도·거리·시간·날씨·주변 공간 조건·측정 품질·구조화된 프로필 사실은 Context 재료가 될 수
있다. 사용자가 일기에 직접 쓴 감정·생각·사적인 해석은 그렇지 않다.

v0에는 개인 문장, prompt, note, emotion, reflection을 담는 capability나 payload가 아예 없다.
`private_render_only` 상태로 Context Plane에 넣는 우회도 두지 않는다. AI가 일기 작성 요청 안에서
사용자 문장을 다루더라도 그 요청의 private composition 범위를 벗어나 Bundle·경향·프로필 갱신·
Memory Place claim·다른 산책의 판단 재료로 승격하지 않는다.

개인 문장의 편집·삭제는 별도 일기 표현의 수명이며 Capsule의 객관적 사실이나 Context Atom을
삭제하는 뜻이 아니다.

## 기존 저장과 v0 범위

기존 `TrailContextSnapshot`과 `MeasurementReceipt`가 계속 Capsule의 canonical 저장물이다.
PR C는 adapter projection만 추가하므로 DB migration과 backfill이 없다. Profile adapter도 외부
프로필 저장소를 소유하거나 역조회하지 않는다.

다음은 범위 밖이다.

- 실제 날씨·토지피복·수변·시설 provider와 timeout/retry 조립
- Context Bundle 영구 저장 또는 Offer/Journal receipt DB 연결
- LLM tool 호출·프롬프트·문장 생성
- 안전·의료·인과 판정 엔진
- 개인 자유 메모 저장

