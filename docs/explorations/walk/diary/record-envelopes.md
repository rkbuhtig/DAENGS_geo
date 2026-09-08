---
status: exploring
implementation: contract-and-synthetic-examples
last_verified: 2026-09-08
---
# 사용자 산책 기록과 주변 정보 봉투 — 1단위 계약

[일기 입구](README.md) · [제작 계획](plan.md) · [2단위 수집 실험](record-envelope-collection.md)

## 이번 작업의 범위

행동 핀과 사용자가 글·사진으로 남긴 기록을 모두 주변 정보 수집 대상으로 삼는다.
기존 기록을 참조하는 계약, 태그가 달린 정보 봉투, 합성 예시와 오프라인 검증기를 만든다.
실제 API 조회·DB·근처 검색·HTML·App UI·LLM 입력 연결은 아직 구현하지 않는다.
아래 JSON은 운영 데이터나 실측 결과가 아니며 장소명·거리·날씨·좌표 연결은 모두 합성이다.

위 범위는 1단위의 기준이다. 후속 2단위에서 API 수집기를 추가했으며, 이 문서의 합성 예시와
별도로 [실제 응답 결과](../../../research/2026-09-08-record-envelope-collection.md)를 보존한다.

사용자 기록 원본 → 주변 정보 봉투 추가 → 소비할 봉투 선택 → 근처 기억 카드 / LLM 장면 재료.
봉투를 저장하는 행위는 장면 선택·서술·행동 의미 정규화가 아니다.

## 확인한 현재 App와의 접점

App `dev`의 `5062c03`을 읽었다. 설치된 기기 화면이나 production 배포 상태의 검증은 아니다.

| 현재 모델/흐름 | 계약으로 옮길 값 | 보존할 차이 |
|---|---|---|
| `WalkEntry`: 킁킁·배설·짖기 | `content.kind=behavior`, code, pet_id | 사용자가 남긴 행동 기록. GPS나 LLM의 행동 추론이 아님 |
| `WalkEntry`: NOTE / 특별한 순간 | `content.kind=note`, text | 자유 글 원문. 특정 강아지의 행동 코드로 바꾸지 않음 |
| `WalkPhoto` | `content.kind=photo`, media_ref | 사진은 현재 별도 저장 객체. 메모와 한 기록으로 합치지 않음 |
| 기록 시각·선택한 과거 동선 시각 | `event_at`, `time_basis` | 나중에 작성한 글도 선택한 동선의 시각을 대상으로 공간 조회 |
| 좌표·위치 관측 시각·정확도 | `location` | 메모의 위치는 없을 수 있음. 사진은 촬영 때 확정한 위치 |
| 세션의 참여 강아지 | `session_pet_ids` | 메모·사진에 행동 주체를 강제로 배정하지 않음 |

현재 App에는 작성 시각을 따로 보존하는 필드가 없고, 기록 시각의 출처 구분도 모두 저장되지는 않는다.
`authored_at`, `time_basis`, `observation_ref`는 새 계약이 요구하는 구분이지 기존 데이터에
전부 존재하는 필드가 아니다. 새 쓰기 경로에서 확보하고, 기존 자료는 확인 가능한 값만 사용한다.
출처가 불명확하면 `time_basis=recorded_at`; 정확한 route 관측 근거를 확보하지 못한 기록을
`route_observation`으로 꾸미지 않는다. 위치 관측 참조는 원본 entry의 location 필드 참조도
가능하며, 실제 raw-fix ID가 없으면 만들지 않는다.

근거: [기록 모델](https://github.com/SAJOYO/DAENGS_APP/blob/5062c03/app/src/main/java/com/daengs/app/walk/WalkEntry.kt),
[사진 모델](https://github.com/SAJOYO/DAENGS_APP/blob/5062c03/app/src/main/java/com/daengs/app/walk/WalkPhoto.kt),
[산책 중 작성](https://github.com/SAJOYO/DAENGS_APP/blob/5062c03/app/src/main/java/com/daengs/app/ui/walk/WalkRoute.kt#L218),
[지난 동선에 기록](https://github.com/SAJOYO/DAENGS_APP/blob/5062c03/app/src/main/java/com/daengs/app/ui/walk/WalkDiaryMapScreen.kt#L107).

## 1. 원본 기록을 참조하는 Record

원본 저장소는 유지한다. `ref.store + ref.id`가 원본 식별자이고 `ref.version`이 참조 버전이다.
같은 좌표·시각의 행동과 글도 ID가 다르면 다른 기록이다. 지도 마커 ID를 원본 ID로 사용하지 않는다.

| 필드 | 의미 |
|---|---|
| `ref` | walk_entry / walk_photo, 원본 ID, version, version_kind |
| `owner_id`, `session_id` | 소유 계정과 산책. 단일 스냅샷은 한 계정의 기록만 포함 |
| `session_pet_ids` | 해당 산책 참여 강아지. 근처 조회에서 글·사진을 누락시키지 않는 연결 |
| `event_at` | 기록이 연결된 시각. 글에 등장하는 모든 사건이 이때 발생했다는 의미는 아님 |
| `time_basis` | recorded_at / photo_capture / route_observation / session_fallback |
| `authored_at` | 실제 작성·촬영 시각을 아는 경우만 입력. 모르면 null |
| `location` | 관측 point, captured_at, accuracy_m, basis, observation_ref. 위치 없는 글은 null |
| `content` | behavior / note / photo 구분 공용체. 글은 text, 사진은 media_ref |

수정 버전이 있는 entry는 원본 revision을 사용한다. 아직 revision이 없는 로컬 기록이나
사진은 어댑터가 정한 원본 projection의 SHA-256을 사용할 수 있다. 원본 ID를 매번 새로
만들지 않고, 미디어 내용이 바뀌면 버전에도 반영한다. 서버 ACK 전후의 버전 연결은 Dev/App
이식 단위에서 정의한다. `photo` 예시는 가상 media_ref만 있으며 이미지 파일이나 업로드는 없다.
예시 사진 버전은 ref를 제외한 합성 Record projection의 해시다.

자유 글 원문에는 사용자의 감상·해석도 있을 수 있다. 봉투에 담긴 외부 관측과 출처를 구분한다.
수집기가 문장을 행동 코드로 정규화하거나 원문을 요약문으로 덮어쓰지 않는다. 사진에는 임의의
캡션이나 비전 모델의 추론을 추가하지 않는다. 실제 media_ref는 인증된 원본 접근 참조이며
외부 공개 URL·서명 토큰·기기 절대 경로를 LLM에 전달하는 필드가 아니다.

### 시각과 위치의 예외

- 현장에서 남긴 글: 저장된 기록 시각과 현재 관측 위치. 작성 시각도 확인될 때만 채운다.
- 다음 날 작성한 글: 어제 선택한 route 관측의 시각·좌표가 event/location이고 작성 시각은 오늘이다.
- 기존 자료의 작성 시각 미상: null. session 시작 시각이나 서버 수신 시각으로 대신하지 않는다.
- 위치 없는 글: 일기·장면 재료에는 남고 근접 노출과 위치 기반 봉투 조회에서는 제외한다.
- 경로 없는 산책에 시작 시각을 대신 넣은 메모: `session_fallback`. 그 시각의 현장 사건으로 해석하지 않는다.
- 같은 지점을 여러 번 지나감: 좌표가 같아도 선택한 관측 시각과 참조를 유지한다.

작성 시각과 사건 시각의 단순 대소만으로 과거 기록을 판정하지 않는다. 작성 시각이 없거나
기기 시계 오차가 있을 수 있다. v1 검증기는 timezone과 route 시각 연결을 검사하며, 시계 보정은 하지 않는다.

## 2. 태그가 붙은 Envelope

| 필드 | 의미 |
|---|---|
| `id` | 한 번 얻은 자료의 식별자. 이미 저장한 같은 ID의 내용을 덮어쓰지 않음 |
| `target.record` | 정확한 원본 ID와 버전 |
| `target.event_at`, `point`, `radius_m` | 원본 기록의 대상 시각·좌표와 실제 조회 반경. 임의의 대표점으로 바꾸지 않음 |
| `tags` | 현재는 space.park / space.river / space.facility / environment.weather / movement.window |
| `status`, `reason` | known / partial / empty / unavailable / not_requested와 제한·실패 이유 |
| `provenance` | provider, operation, retrieved_at, temporal_basis, valid_time, policy_version, synthetic |
| `payload_format`, `payload` | 응답 형식 ID와 공급자별 JSON 본문. LLM이 재작성한 자료가 아님 |
| `payload_sha256` | canonical JSON 해시. 저장한 본문이 바뀌었는지 확인 |
| `supersedes` | 같은 원본 버전·조회 범위·태그·공급자·operation의 이전 봉투 ID |

`payload`는 공급자별 JSON을 보존하는 자리다. 요청 인증 헤더·키·사용자 토큰은 넣지 않는다.
가져온 JSON은 자료일 뿐 실행 지시가 아니며, 소비기가 임의 URL을 자동 방문하지 않는다.
본문 해시는 sorted keys / UTF-8 / compact separators / ensure_ascii=False의 JSON으로 계산한다.
응답 전송 바이트 자체의 해시와 구분한다. 해시는 출처의 진실성을 증명하는 서명이 아니다.

이 단계의 태그는 자료 분류다. ‘좋아하는 곳’, ‘행복’, ‘특별함’, ‘방문함’은 자동 부착하지 않는다.
공원 대표점까지의 거리와 공원 경계 내부 여부, 같은 장소 유형과 같은 장소 ID를 구분한다.
동시에 공원·하천이 가까우면 양쪽 봉투를 유지한다. 단일 대표 배경 우선순위를 만들지 않는다.
공간 관계 계산을 추가할 때는 원천 응답 참조·사용 형상·단위·계산 버전을 보존해야 한다.
이번 예시의 거리는 합성값이며 실제 경계 연산은 2단위의 작업이다.

### 조회 실패와 시점

- `empty`: 그 범위·종류의 조회가 성공했고 결과가 비었음. 주변에 아무것도 없다는 뜻은 아님.
- `partial`: 일부 자료만 얻었음. 제한 사유를 함께 둔다.
- `unavailable`: 조회/해석 실패로 사용할 자료가 없음. 성공한 빈 결과로 바꾸지 않는다.
- `not_requested`: 조회하지 않음. 조회 시각·본문은 null이며 사유를 남긴다.
- `event_observation`: valid_time이 기록 시각을 포함하는 관측. 예: 해당 시간대 날씨.
- `source_observation`: 공급자 관측의 시각을 그대로 보존. 핀 시각과 일치하거나 핀에서 측정했다는 뜻은 아님.
- `lookup_snapshot`: 조회 시점의 자료. 과거 사건 당시에도 같았다고 주장하지 않는다.
- `unknown`: 원자료의 적용 시점을 모름. retrieved_at은 자료를 얻은 시각일 뿐이다.

현재 수집 주제들은 관측 위치를 필요로 한다. 위치 없는 글의 envelope는 not_requested만 허용한다.
세션 전체의 날씨를 참고할 수는 있지만 핀 위치의 환경으로 복사하지 않는다. 그런 세션 조각은
기존 Evidence 경로에서 별도로 참조한다. 날씨의 관측 지점·격자, 시설의 종류·검색 반경은 payload
또는 공급자별 다음 계약에 보존한다. 1단위의 generic validator는 공급자 JSON의 의미를 검증하지 않는다.

## 3. Append와 소비 스냅샷

`RecordEnvelopeSnapshot`은 한 계정의 원본 기록 버전 목록, 봉투 이력, `selected_envelope_ids`를 갖는다.
`synthetic`은 사용자 기록이 합성인지, `context_mode=synthetic|provider`는 봉투의 자료 출처를 뜻한다.
합성 산책에 실제 API를 조회한 결과는 `synthetic=true`, `context_mode=provider`, 봉투의
`provenance.synthetic=false`다. 기존 합성 예시는 기본 context_mode=synthetic을 유지한다.
봉투 배열은 추가 순서로 둔다. supersedes는 먼저 존재한 동일 조회 범위의 봉투만 참조한다.
스냅샷이 읽을 봉투는 선택 목록으로 명시하고 같은 조회 범위의 두 결과를 동시에 선택하지 않는다.
선택 목록이 비어 있는 초기 상태도 유효하다. 새 응답이 실패했을 때 이전 성공 자료를 계속 읽을지는
수집 정책이 정하며 이 계약이 ‘최신이면 무조건 사용’으로 결정하지 않는다.

원본 글을 편집하면 새 원본 버전이다. 이전 버전에 붙은 봉투는 그대로 현재 버전 자료라고
재사용하지 않는다. 같은 위치·시각이라 재사용 가능하더라도 이후 수집기는 새 참조와 근거를 남긴다.
과거 스냅샷은 별도 실행 자료로 보존할 수 있지만, append를 삭제 불가능한 사용자 데이터 정책으로
해석하지 않는다. 삭제·권한 회수 시 활성 조회/캐시에서 제외하고 원본 참조를 끊는 작업은 4~6단위다.

현재 검증기는 버전·소유 범위·대상 시각·좌표 일치, 잘못된 대체 연결과 선택을 거부한다.
실제 DB 소유권을 인증하거나 저장을 불변으로 강제하는 구현은 아니다. Python 모델이나 JSON을
수정한 뒤 같은 snapshot이라고 주장할 수 없도록 저장 지문·원자적 저장은 이식 시 연결한다.

## 4. LLM과 근처 카드의 소비 경계

| 소비자 | 사용할 자료 | 이번 단계 상태 |
|---|---|---|
| 근처 기억 카드 | 좌표 있는 행동·글·사진 원본, 선택된 짧은 환경 정보 | 검색·노출 정책과 UI 미구현 |
| LLM Evidence | 원문, 원본 참조, 선택 봉투의 관련 필드와 출처/시각/상태 | 기존 Piece 어댑터 연결 미구현 |
| SceneComposition | Evidence를 통해 연결된 사건들을 편집상 묶음 | 별도 진행 중인 LLM 워크트리의 설계이며 본 PR에 포함하지 않음 |

‘현재 강아지의 행동’만 필터링해 같은 세션의 메모·사진을 잃지 않는다. 메모는 pet_id가 없어도
정상적인 기록이다. 근처 카드용 우선순위와 장면 편집의 중요도 판단은 같은 정책으로 고정하지 않는다.
자료가 없다는 이유로 사용자 글을 제거하지 않고, 봉투 수를 장면 수로 바꾸지도 않는다.

현재 Candidate의 action/transition/connection은 과거 실험의 역할이다. 메모·사진을 강제로
behavior code로 바꾸어 넣지 않는다. 후속 어댑터가 기록 종류와 편집 역할을 분리해 연결한다.
현재 Geo `app/context_plane`의 Atom/시간·공간 support와 provenance 개념을 참고했으나
운영 registry나 enum을 확장하지 않았다. 예를 들어 empty는 성공한 빈 payload이고,
unavailable은 사유에 따라 fetch_failed/parse_failed에 대응할 수 있다. 승격 때 중복 계약을 정리한다.

## 5. 검토용 예시와 실행

[JSON 예시](../../../../scripts/spikes/diary_storyboard/fixtures/record_envelopes.json)는 6개 기록과
8개 봉투, 선택된 봉투 7개를 포함한다. 5개 기록에 위치가 있다.

| 원본 ID | 의도한 검토 상황 |
|---|---|
| behavior-01 | 두부의 킁킁. 같은 공원 조회의 이전/새 봉투를 모두 보존하고 새 버전만 선택 |
| note-01 | 행동과 같은 시각·좌표에 남긴 자유 글. 공원으로 배경을 고정하지 않고 하천/시설 정보를 함께 보존 |
| photo-01 | 별도 사진 원본 참조. 시설 검색의 성공한 빈 결과 |
| note-later | 다음 날 작성했지만 전날 동선의 시각·좌표에 붙인 글. 전날 날씨 관측을 참조 |
| note-unlocated | 위치 없는 글. 공간 조회를 하지 않았다는 상태를 보존 |
| note-legacy | 기존 자료라 작성 시각을 모르는 글. 날씨 실패를 빈 결과로 바꾸지 않음 |

Geo 루트에서 기존 Python 3.12 개발 환경으로 실행한다. DB·키·네트워크는 사용하지 않는다.

```powershell
uv run python -m scripts.spikes.diary_storyboard.record_envelopes
uv run python -m scripts.spikes.diary_storyboard.record_envelopes path/to/snapshot.json
uv run python -m scripts.spikes.diary_storyboard.record_envelopes --schema
uv run pytest tests/spikes/diary_storyboard/test_record_envelopes.py -q
```

[Pydantic 계약과 CLI](../../../../scripts/spikes/diary_storyboard/record_envelopes.py)가 구조의 원본이다.
JSON Schema는 --schema로 생성한다. 교차 참조·hash·시간 일치 등 model validator의 검사는
JSON Schema만으로 대체되지 않으므로 실제 입력은 CLI/Pydantic 검사도 통과해야 한다.
[계약 검사](../../../../tests/spikes/diary_storyboard/test_record_envelopes.py)는 잘못된 버전·주인·좌표·
작성 시각 사용, 원문 변형, payload 변조, 실패/빈 결과 혼동, 대체 봉투 선택 등을 다룬다.

다음 2단위에서 공급자별 payload와 수집 정책을 확정하고 실제 응답을 이 계약에 붙인다.
3단위에서 근처 기록 카드 재생, 4~6단위에서 Dev/App 연결, 7단위에서 LLM 재료 소비를 검증한다.

### 이번 작업의 검증 결과

2026-09-08, 기존 `work/DAENGS_geo/.venv/Scripts/python.exe` 환경을 재사용하여 위의 단일
테스트 파일을 실행했다. **28개 통과**, 새 계약/테스트 파일 Ruff 통과, 예시 JSON 검증 통과.
문서의 로컬 링크도 확인했다. 전체 테스트·DB·API·LLM·실기기 검증은 이번 범위가 아니다.
이번 작업의 외부 데이터/API 호출은 0회이며 합성 자료만으로 계약 경계를 확인했다.
