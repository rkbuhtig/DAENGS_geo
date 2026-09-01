---
status: adopted
decision: 79
adopted_at: 2026-09-01
---
# WalkJournal v0는 저장 원본이 아니라 현재 증거의 결정론적 시간 투영이다

결정 #77은 한 산책의 장면을 Episode Pin으로 남겼고, #78은 여러 산책의 Pin을 장소 biography로
읽었다. 그러나 지도 Pin을 눌렀을 때 한 산책이 어떤 문맥과 순서의 이야기였는지 읽는 시간 투영은
아직 API로 닫히지 않았다.

## 파생 일기

```text
WalkJournalProjection
= WalkFacts
+ TrailContextSnapshot과 현재 context facet
+ event_at 순 Episode Pin·WalkAttestation
+ narration policy v1
```

별도 Journal 테이블이나 자동 요약 snapshot은 만들지 않는다. 자동 문장은 현재 정책으로 다시 만들 수
있고, 그 원판인 Capsule·Pin·증언은 이미 각자의 수명으로 보존된다. 자연 식별자는 `session_id`다.

## narration policy v1

제목과 장면 시각은 KST로 표현한다. 요약은 `기록상` 시간·이동거리, 알려진 강수·낮밤 facet,
저장 Pin 수만 말한다. unknown context는 반대 상태로 채우지 않고 문장에서 빠진다.

장면 문장은 Pin의 temporal precision과 Attestation의 review disposition·subject role만 자연어로
투영한다. meaning code와 vocabulary version은 구조화 증언으로 그대로 반환하지만, 승인된 제품
어휘가 없으므로 임의의 행동명으로 번역하지 않는다. `uncertain`은 확정 어미로 바꾸지 않는다.

## 읽기 경계

`GET /spatial-diary/walks/{session_id}/journal`은 소유권을 확인하고 한 repeatable-read snapshot에서
manifest·WalkFacts·TrailContext·Pin을 읽는다. 필수 Capsule 자식이 없으면 빈 값으로 완성하지 않고
실패한다. 응답은 현재 projection·narration·context policy와 Capsule version, 생성 시각, Pin 수를
receipt로 반환한다.

## 다음으로 미룬 것

- 사용자 제목·본문·대표 장면 수정과 `PublishedJournalSnapshot`
- 행동 meaning code의 제품 라벨·아이콘 어휘
- 사진·자유 메모·EventContextSnapshot
- LLM 나레이션과 공유용 개인정보 마스킹
