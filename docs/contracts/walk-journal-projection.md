# Walk Journal Projection v0

`WalkJournalProjection`은 저장된 일기 원본이 아니다. 한 산책의 봉인된 Capsule 사실과 당시
TrailContext, 사용자가 저장한 Episode Pin·Attestation을 현재 narration policy로 다시 읽은 시간
투영이다.

```text
WalkFacts + TrailContextSnapshot + EpisodePin/WalkAttestation
→ WalkJournalProjection
```

## 응답

```text
GET /spatial-diary/walks/{session_id}/journal

session_id / dog_id
facts                 시작·종료·시간·이동거리·정지 사실
context               동결된 원시 TrailContext
context_facets        precipitation / daylight + policy version
title / summary       현재 정책의 결정론적 문장
entries[]             event_at 순 Pin + Attestation + 문장
receipt               projection/context/narration/capsule version, 생성 시각, Pin 수
```

일기 날짜와 장면 시각은 `Asia/Seoul` 달력으로 표시한다. 시각이 approximate이면 `쯤`을 붙이고,
unknown이면 시각을 추측하지 않는다. 시간순 정렬은 unknown 시각을 뒤에 둔다.

## 문장 권한

- 산책 시간·이동거리는 `WalkFacts`를 `기록상`이라는 한계와 함께 말한다.
- 비·낮밤은 동결된 context 원자를 context policy v1으로 분류한 경우에만 말한다.
- 문맥 미상은 맑음·비 없음·낮으로 보충하지 않고 문장에서 생략한다.
- Episode 문장은 저장 Pin과 실제 Attestation만 사용한다. Candidate·Offer 노출·무응답은 일기
  장면이 아니다.
- 사용자 meaning code는 Attestation 구조에 그대로 반환한다. 승인된 제품 어휘표가 없으므로 v0
  문장이 임의의 한국어 행동명으로 번역하지 않는다.
- `uncertain` 증언은 확정형으로 바꾸지 않고 불확실성을 문장에 남긴다.

## 수명과 재현

Projection과 자동 문장은 저장하지 않는다. 같은 원판도 narration/context policy가 바뀌면 새
문장으로 재생성될 수 있으므로 receipt에 버전을 남긴다. 사용자가 제목·요약·대표 장면을 고정하면
결정 #80의 별도 [`PublishedJournalSnapshot`](published-journal-snapshot.md)으로 보존한다. 외부 공유는
그 객체의 v0 범위에도 포함하지 않는다.

조회는 인증 principal이 소유한 Capsule만 한 repeatable-read snapshot에서 조립한다. 봉인 manifest가
있는데 WalkFacts 또는 TrailContext가 없으면 빈 일기를 만들지 않고 무결성 오류로 실패한다. v0는
한 산책 최대 100개 Entry를 허용하며 초과분을 잘라 반환하지 않는다.
