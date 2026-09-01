---
status: adopted
decision: 82
adopted_at: 2026-09-01
---
# 사용자 의미 정정은 안정 Pin에 붙는 append-only Attestation이다

결정 #77은 `WalkAttestation.supersedes_attestation_id`와 “정정은 update가 아니라 새 행”이라는
계약을 선언했지만, 실제 저장 경로는 Offer당 Attestation 하나만 허용하고 Pin·Journal·Memory
Place가 모두 최초 Attestation만 읽었다. 따라서 사용자가 잘못 고른 의미를 고칠 방법이 없었다.

## 권위와 identity

Offer-linked 최초 Attestation은 실제 제시된 질문에 대한 당시 응답이다. 정정 때문에 이 역사를
덮어쓰거나 Offer에 두 번째 응답을 붙이지 않는다. Episode Pin의 위치와 identity,
`created_by_attestation_id`도 생성 원인으로 고정한다.

정정은 안정 Pin에 귀속되는 새 Attestation이다.

```text
Offer
→ creating Attestation
→ stable Episode Pin
   → correction 1 supersedes creating Attestation
      → correction 2 supersedes correction 1
```

한 correction은 현재 head만 supersede할 수 있다. caller가 예상 head를 요청에 넣고 서버는 Pin을
잠근다. DB는 `supersedes_attestation_id`를 unique로 만들어 한 head에서 두 갈래가 생기지 않게
한다. correction 자체도 `pin_id`를 보존하며 Entry 계약이 실제 Pin과의 일치를 검증한다.
caller-provided correction ID의 동일 요청은 동시 도착까지 한 번의 fresh transaction 재검증으로
멱등이고 다른 내용은 conflict다.

## 서로 다른 읽기

Offer review는 실제 최초 답변을 계속 반환한다. 현재 사용자 의미가 필요한 Pin overlay,
WalkJournalProjection, Memory Place timeline·claim count는 creating Attestation에서 시작한 chain의
현재 head를 읽는다. 전체 history endpoint는 중간 correction을 포함한 모든 행을 순서대로 돌려준다.
현재 의미를 쓰는 이 규칙은 재생성 가능한 읽기 모델에만 적용한다. 사용자가 이미 확정한
`PublishedJournalSnapshot`의 표현은 correction으로 소급 변경하지 않는다.

이 분리는 다음 authority를 보존한다.

```text
무엇을 보여줬는가       Offer snapshot
처음 무엇이라 답했는가  creating Attestation
지금 어떤 의미인가      current correction head
어떤 기억인가           stable Episode Pin
```

## 이 결정에서 열지 않는 것

정정은 Pin을 계속 저장한 상태에서 의미만 고친다. “아무 일 아니었음”으로 바꾸거나 기억에서 빼는
행위는 `rejected/dismiss` correction으로 흉내내지 않는다. 그것은 Pin의 active/retired lifecycle과
Memory Place membership 파급을 함께 정해야 하는 별도 결정이다.

상세 API와 오류 계약은 [Pin Attestation correction](../contracts/pin-attestation-correction.md)을
따른다.
