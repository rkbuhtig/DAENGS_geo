# Published Journal Snapshot v0

`PublishedJournalSnapshot`은 현재 정책으로 재생성되는 `WalkJournalProjection`과 별개인 사용자
확정본이다. v0는 외부 공유물이 아니라 인증된 소유자만 읽는 비공개 불변 객체다.

## 생성

```text
PUT /spatial-diary/walks/{session_id}/journal-snapshots/{snapshot_id}

{
  "title": "비 온 뒤 냄새 맡던 날",
  "summary": "천천히 오래 머문 장면을 대표 기억으로 고정했다.",
  "selected_pin_ids": ["pin-..."]
}
```

- `snapshot_id`, `session_id`: 1..128자
- `title`: 공백만인 값 금지, 최대 200자
- `summary`: 공백만인 값 금지, 최대 5,000자
- `selected_pin_ids`: 순서를 보존하는 고유 ID 0..100개
- 선택한 ID는 생성 시점에 같은 산책의 Journal Entry여야 한다.

같은 ID와 같은 body의 PUT은 기존 객체를 반환한다. 같은 ID에 다른 title, summary,
selected Pin 순서나 구성을 보내면 `409`다. 서버가 정한 `published_at`은 재시도 때 바뀌지 않는다.

## 응답

```text
snapshot_id / snapshot_version
session_id
visibility = private
title / summary / selected_pin_ids
source_projection_version
source_narration_policy_version
source_context_policy_version
source_capsule_version
published_at
```

source version은 이 불변본이 어느 자동 일기 정책을 보고 만들어졌는지 설명하는 영수증이다.
v0 Snapshot은 Entry 표시본을 포함하지 않으며 `selected_pin_ids`는 저장 당시 선택과 순서만
보존한다. 소비자는 현재 Pin Attestation을 다시 읽어 그것을 저장 당시 Snapshot 내용인 것처럼
표시하면 안 된다. 향후 Snapshot 화면에 Entry 문장이나 의미를 내장할 때는 저장 시점의 표시본을
별도 필드로 동결한다.

Pin Attestation correction은 현재 Pin overlay·자동 Journal Projection·Memory Place에는 반영되지만,
이미 저장된 Snapshot의 제목·요약·Pin 선택이나 저장 당시 표현에는 소급 적용하지 않는다.

## 객관적 기록과 개인의 속마음

WalkFacts, 이동 속도·거리·시간, 동결된 환경, 주변 공간 조건과 그 경향은 Capsule·Context의
객관적 재료로 계속 보존한다. 반면 사용자가 미래 Journal에 직접 쓰는 감정·생각·사적인 해석은
private Journal 표현이며 다음 용도로 승격하지 않는다.

```text
Context capability / 행동 경향 근거 / Subject profile 갱신
Memory Place claim / 다른 산책의 LLM 판단 context
```

AI가 일기 작성을 도울 때 해당 작성 요청 안에서 명시적으로 받은 문장을 다룰 수는 있지만,
그 문장을 장기 판단 재료로 재사용하지 않는다. 개인 문장의 편집·삭제도 별도 Capsule 사실이나
환경 원판을 삭제하는 의미가 아니다.

## 읽기와 삭제

```text
GET /spatial-diary/walks/{session_id}/journal-snapshots
GET /spatial-diary/journal-snapshots/{snapshot_id}
```

세 endpoint 모두 인증 principal의 dog 소유권을 확인하고, 소유하지 않은 객체는 존재 여부를
숨기기 위해 `404`로 보인다. 목록은 `published_at`, `snapshot_id` 순이다.

Snapshot 단독 삭제와 update는 v0에 없다. source 산책 삭제가 Capsule·Pin과 Snapshot을 함께
연쇄 삭제한다. 외부 공유나 공개 visibility는 계약 밖이다.
