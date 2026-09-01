# Pin Attestation correction

Episode Pin을 만든 최초 Attestation은 당시 Offer에 사용자가 실제로 답한 역사다. 사용자가 나중에
의미를 고쳐도 그 행과 `EpisodePin.created_by_attestation_id`를 덮어쓰지 않는다. 정정은 같은 Pin에
귀속되는 새 `WalkAttestation`이며 현재 head를 `supersedes_attestation_id`로 가리킨다.

## API

```text
PUT /spatial-diary/pins/{pin_id}/attestations/{attestation_id}
GET /spatial-diary/pins/{pin_id}/attestations
```

PUT body:

```text
supersedes_attestation_id   caller가 마지막으로 읽은 현재 head
review_disposition          confirmed | uncertain
claims[0..16]
```

`confirmed`는 claim이 하나 이상 필요하다. `uncertain`은 claim이 없어도 된다. correction의
`elicitation_mode`는 `pin_correction`, `pin_id`는 route의 안정 Pin, `offer_id`는 null,
`memory_action`은 `save`로 서버가 고정한다.
`rejected`와 `dismiss`는 기존 Pin을 기억에서 빼는 별도 lifecycle이므로 이 API가 받지 않는다.

caller가 정한 correction ID와 같은 body의 재시도는 기존 행을 반환한다. 같은 ID에 다른 내용을
보내거나 현재 head가 아닌 과거 Attestation을 supersede하려 하면 `409`다. Pin row lock과
`supersedes_attestation_id` unique constraint로 하나의 head에서 두 correction이 갈라지지 않게 한다.
동시에 도착한 같은 ID·같은 body도 새 repeatable-read transaction에서 한 번 재검증해 같은 행을
반환한다. 다른 ID가 같은 head를 경쟁하면 승자 하나만 저장되고 나머지는 `409`다.

Correction의 `pin_id`는 응답과 history에도 포함된다. Journal·Memory Place 계약은 이 값을 실제
Entry의 `EpisodePin.pin_id`와 대조하므로, 같은 산책의 다른 Pin correction을 유효 의미로 끼울 수 없다.

## 읽기 권위

```text
Offer review
→ 최초 Offer-linked Attestation

Pin overlay / Walk Journal / Memory Place
→ Pin의 생성 Attestation에서 이어진 correction chain의 현재 head

Pin Attestation history
→ 생성 Attestation부터 현재 head까지 전부
```

따라서 정정 뒤에도 Offer가 무엇을 물었고 사용자가 처음 무엇이라 답했는지는 남는다. 현재
Journal 문장, Entry Selector, Memory Place timeline과 claim count만 새 의미로 재계산된다.
사용자가 이미 확정한 `PublishedJournalSnapshot`의 제목·요약·Pin 선택과 저장 당시 표현에는
소급 적용하지 않는다.

모든 endpoint는 Pin이 속한 dog의 principal을 확인한다. 타인의 Pin과 존재하지 않는 Pin은 모두
`404`로 보인다. 한 Pin의 history는 v0에서 최대 100개다.

## 수명

Correction은 source walk session 삭제를 따라간다. Pin ID·좌표·생성 Attestation은 정정으로
바뀌지 않는다. Pin retirement/restore, Memory Place label 정정, 자유 메모 편집은 이 계약 밖이다.
