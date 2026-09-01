---
status: adopted
decision: 80
adopted_at: 2026-09-01
---
# PublishedJournalSnapshot v0는 사용자가 고정한 비공개 불변본이다

결정 #79의 `WalkJournalProjection`은 현재 Capsule·Context·Pin과 정책으로 매번 다시 만드는
자동 일기다. 사용자가 제목과 요약을 다듬고 대표 장면을 골랐을 때도 같은 객체를 덮어쓰면,
재생성 가능한 시스템 문장과 사용자가 보존하기로 한 기록의 경계가 사라진다.

## 고정하는 것

`PublishedJournalSnapshot`은 한 봉인 산책에만 속하며 다음을 처음 PUT한 모습 그대로 보존한다.

```text
사용자 제목 / 사용자 요약 / 순서 있는 대표 Episode Pin id
원본 projection / narration / context / Capsule version
published_at / visibility=private
```

대표 Pin은 0개도 허용한다. 그러면 한 산책 전체를 한 편의 요약 일기로 고정할 수 있다. Pin을
고르면 모두 그 산책의 현재 `WalkJournalProjection` Entry여야 하며, 다른 산책이나 존재하지 않는
Pin을 섞을 수 없다. v0는 최대 100개를 허용하고 중복 ID는 거절한다.

## 불변성과 수명

caller가 정한 `snapshot_id`의 첫 PUT만 생성한다. 같은 내용의 재시도는 같은 `published_at`을 가진
기존 객체를 돌려주고, 제목·요약·Pin 선택 중 하나라도 다르면 conflict다. 정정은 update가 아니라
새 snapshot id로 새 버전을 만든다.

Snapshot은 source Pin의 증거를 복제하지 않고 안정 ID와 생성 당시 정책 영수증만 고정한다.
Episode Pin과 Snapshot 모두 source session 수명을 따르므로 산책 삭제 시 함께 삭제된다.

## 비공개 경계

이름의 `Published`는 자동 파생본을 사용자가 확정했다는 뜻이지 인터넷 공개를 뜻하지 않는다.
v0의 visibility는 `private` 하나뿐이며 모든 생성·목록·단건 읽기는 source Capsule의 dog 소유권을
검사한다. 공유 URL, 공개 ACL, 다른 사용자 전달용 payload, 위치 마스킹은 열지 않는다.

## API

```text
PUT /spatial-diary/walks/{session_id}/journal-snapshots/{snapshot_id}
GET /spatial-diary/walks/{session_id}/journal-snapshots
GET /spatial-diary/journal-snapshots/{snapshot_id}
```

세부 필드와 오류 경계는
[Published Journal Snapshot 계약](../contracts/published-journal-snapshot.md)을 따른다.

## 다음으로 미룬 것

- 공유 링크와 수신자 ACL
- 공유용 위치·시간·개 식별자 마스킹 projection
- 사진·자유 메모 원본
- Snapshot끼리의 편집 lineage와 supersedes 관계
- 여러 산책을 합친 한 권의 일기
