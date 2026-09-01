---
status: adopted
decision: 78
adopted_at: 2026-09-01
---
# Memory Place v0는 명시적 distinct-walk Pin 승격과 capability-aware biography다

결정 #77로 한 산책의 low-motion 후보가 사용자 증언을 거쳐 Episode Pin으로 남았다. 이번 결정은
서로 다른 산책의 Pin을 한 안정 장소에 연결하고, 그 장소에서 선택 산책이 무엇을 관측했으며
무엇은 판정할 수 없는지를 biography로 읽는 첫 수직 경로다.

## 안정 identity와 membership

v0는 서로 다른 산책의 Pin 두 개 이상을 사용자가 명시적으로 선택할 때 Memory Place를 만든다.
지도 marker cluster, 현재 필터, 매번 다시 계산한 거리 군집은 장소 identity가 아니다. 자동
그룹핑 반경은 실데이터 없이 박지 않는다.

Memory Place는 walk_session FK 아래 두지 않는다. 산책 삭제는 Pin과 membership을 cascade로
지우지만 장소 identity와 생성 당시 footprint를 지우지 않는다. Pin 하나는 한 장소에만 속하고,
후속 Pin은 같은 dog이며 현재 footprint와 겹쳐야 연결된다. 초기 footprint는 seed Pin의 사건
circle을 모두 덮는 보수적 circle이다.

## biography 분모

각 선택 산책을 다음 순서로 판정한다.

1. Cellophane으로 장소의 macro exposure를 `exposed / uncertain / not_exposed`로 분리한다.
2. Manifest가 현재 `low_motion` generation을 보존했는지 확인한다.
3. drift suspected가 아니며 clear exposure와 capability가 있을 때만 slow observation의
   `observed / not_observed`를 판정한다.
4. 나머지는 이유가 있는 `unjudgeable`로 남긴다.

`not_observed`는 “그 산책에서 이 장소의 현재 관측 규칙이 사건을 찾지 못했다”는 뜻일 뿐이며,
Pin이 없다는 뜻도 사용자 증언의 부재도 아니다. Entry Selector는 장소 timeline과 claim count만
바꾸고 위 산책 분모는 바꾸지 않는다. 결과는 비율 점수 대신 모든 분자·분모 count와 산책별
reading, 정책 지문을 함께 반환한다.

## 강수 첫 비교

비와 비 없음은 같은 base selector에서 precipitation facet만 `rain`과 `dry`로 갈라 두 biography를
나란히 반환한다. 문맥 미상은 dry로 간주하지 않고 별도 제외 수로 남긴다. 이 비교는
`observational`이며 행동 차이의 원인을 비라고 주장하지 않는다.

상세 계약은 [Memory Place biography](../contracts/memory-place-biography.md)에 있다.

## 다음으로 미룬 것

- 자동 장소 후보 grouping과 임계값 측정
- footprint revision과 병합·분리·rename 역사
- 사진·자유작성·수동 Pin 생성
- 외부 시설 Place와 Memory Place의 연결
- 통계적 효과 추정과 인과 서술

