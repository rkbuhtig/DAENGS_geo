---
status: adopted
decision: 83
adopted_at: 2026-09-01
---
# 판단 재료는 닫힌 Context Plane을 통과한다

Spatial Diary는 이미 Trail Context와 Measurement Receipt를 보존하고, 다른 기능은 현재
DogProfile과 장소 사실을 직접 소비한다. 여기서 날씨 API·토지피복·주변 시설·프로필·기억 전기를
각 기능이나 LLM 프롬프트에 바로 연결하면 어떤 값과 시점을 사용했는지, unknown과 false가 왜
갈렸는지, 과거 산책에 현재 프로필이 섞였는지 재현할 수 없다.

반대로 모든 판단 재료를 `Environment` JSON 하나에 넣으면 외부 세계의 관측, 주체 프로필,
측정 품질, 과거 통계의 권위와 수명이 다시 섞인다.

## 결정

독립 도메인 `app/context_plane`을 만들고 판단 재료의 흐름을 다음으로 고정한다.

```text
Provider → typed Atom → derived Facet → purpose Lens → policy/LLM
```

Capability는 닫힌 registry이며 v0는 Trail weather, dog profile, walk measurement 세 가지뿐이다.
Atom은 provider·source authority·observed/as-of/captured time·공간/시간 support와 미상·미호출·실패
상태를 보존한다. Facet은 evidence Atom과 policy version을 가진 재계산 값이다.

Episode Review, Walk Journal, Memory Place Biography, Route Recommendation은 서로 다른 Lens로
필요 capability와 허용 용도를 제한한다. 모든 v0 Lens는 causal claim과 safety gate를 금지한다.
LLM이 capability를 제안하더라도 registry와 Lens가 허용한 Atom만 전달하며, 실제 설명은 bundle·
request fingerprint와 evidence Atom을 영수증으로 남긴다.

과거 기능의 profile은 `walk_time`, 현재 추천은 `current` time basis를 강제한다. 과거 나이는
현재 계산 property를 복사하지 않고 birth date와 사건 시점으로 파생한다.

## 속마음과 객관적 기록

속도·거리·시간·환경·주변 공간 조건·측정 품질·구조화된 프로필 사실은 객관적 원판과 경향으로
유지할 수 있다. 사용자가 일기에 쓴 감정·생각·사적인 해석은 Context Plane에 넣지 않는다.
별도 private 표시라는 이유로 Atom에 저장하는 것도 허용하지 않는다. 따라서 v0 registry와 typed
payload에는 자유 문장 capability가 존재하지 않는다.

이 경계는 사람이나 AI가 일기를 과감하게 쓰지 못하도록 내용까지 심사하는 규칙이 아니다.
작성 중에는 private composition 재료를 사용할 수 있다. 다만 그 문장이 장기 판단 Context,
행동 경향, Subject profile 갱신, Memory Place claim, 다른 산책의 LLM 근거로 승격되지 않는다.

## 패키지와 이행

`context_plane`은 제품 기능 전반이 소비하는 어휘이므로 결정 #67의 도메인층 새 최상위로 둔다.
이 계약은 응용 기능을 import하지 않는다. 기존 `TrailContextSnapshot`·`MeasurementReceipt`·외부
`DogProfile`을 읽는 adapter만 `features/context_plane`에 두어 import 방향을 지킨다.

기존 Capsule 저장물은 바꾸지 않고 adapter로 투영하므로 migration·backfill이 없다. 실제 provider,
world spatial capability, Bundle 영구 저장, LLM 연결은 각각 원천·보관·제품 목적이 정해질 때 별도
작업으로 연다.

상세 상태·Lens·fingerprint 계약은 [Context Plane v0](../contracts/context-plane.md)을 따른다.

