---
status: exploring
implementation: provider-collector-and-offline-replay
last_verified: 2026-09-08
---
# 기록 봉투 2단위 — 공공데이터 수집

[1단위 계약](record-envelopes.md) · [실제 실행 결과](../../../research/2026-09-08-record-envelope-collection.md)

행동·자유 글·사진을 같은 수집 경로로 읽는다. 기존 `walk_record_lab.ContextReader`는 메모를
제외하므로 그대로 연결하지 않는다. 새 collector는 기록 종류로 수집을 생략하지 않으며,
위치 없음/실험 범위 밖일 때만 위치 조회를 건너뛴다. 원본 글·ID·버전·시각·좌표는 보존한다.

## 수집 정책 v1

합성 산책 범위는 경도 127.041~127.061, 위도 37.480~37.493의 실험 사각형이다.
행정구역 포함 판정이나 전국 지원 범위가 아니다. 예시의 반경 250m와 최대 30개 결과는
수집 실험용 값이며 근접 카드 표시 반경·LLM 중요도·장면 개수 정책으로 사용하지 않는다.

| 봉투 | 원천 질의 | 선별·계산 | 실제 확인 범위 |
|---|---|---|---|
| 공원 | 도시공원 표준 API, 강남구 제공 자료 | 대표점까지 250m, 원본 관리번호·이름·분류·자료일자 | 경계/공원 내부를 판정하지 않음 |
| 하천 | 하천 표준 API, 페이지 상한 내 전국 목록 | 하천 시점까지 250m, 원본 코드·이름·좌표·자료일자 | 형상이나 하천 산책로가 아님. 좌표 누락은 불완전 자료 |
| 시설 | 상가 API, 기록 좌표 반경 250m | 등록 좌표까지 거리, 원본 대·중·소분류·ID·이름 | 방문/현재 영업/행동 원인이 아님 |
| 날씨 | KMA ASOS 시간자료, 서울 108 관측소, 사건이 속한 KST 시간 | 원본 tm·ta·rn·hm·ws, 관측 시각 차이 | 지정 관측소 자료. 핀 현장·정확히 동일 시각 관측으로 확대하지 않음 |

기존 sources 모듈의 고정 endpoint·공식 출처·응답 파서를 재사용한다. 새 수집기는 성공 응답
페이지를 private cache에 보존하고 실제 HTTP 페이지 요청 수를 센다. 같은 조건의 행동·글·사진은
동일 응답을 공유하지만, 각 기록에 붙은 봉투 ID와 원본 참조는 각각 유지한다.

기본 상한은 실행당 HTTP 12회, 조회 그룹당 3페이지(페이지당 1,000행)다. 옵션으로 요청은
최대 30회, 페이지는 최대 6까지 허용한다. 재시도·redirect는 하지 않는다. 파싱 불가, 페이지 중복,
totalCount 변경, 상한 도달, 성공한 빈 결과를 구분한다. 조회 성공 뒤 로컬 선별에서 좌표가 없는
행이 있거나 결과 30개 상한을 넘으면 해당 봉투는 partial이며 read/matched/returned 수를 남긴다.

API 필드 이름을 유지하며 공개할 필드만 선별한다. 기관 전화번호·주소 등 이 실험에 불필요한
필드는 공개 snapshot에 포함하지 않는다. 원본 응답 해시와 선별 후 payload 해시는 별개다.
`source_receipt_sha256`과 `page_sha256`로 private cache 원본을 대조할 수 있다.
공간 거리는 Haversine 구면 근사이며 source geometry 종류와 계산 버전을 함께 둔다.
상가 응답의 기준년월 stdrYm도 보존한다. 조회 시각을 과거 시설 상태의 관측일로 바꾸지 않는다.

날씨는 글을 쓴 시각이 아니라 `event_at`으로 질의한다. 공급자 관측 tm을 `source_observation`과
valid_time에 보존하고, 핀 시각과 관측 시각의 차이를 payload에 둔다. 강수의 빈 문자열을 0으로
바꾸지 않는다. 공급자별 단위/관측 구간의 최종 LLM 어댑터는 후속이며 이 단계에서 해석 문장을 만들지 않는다.

## 실행

Geo 루트에서 Python 3.12 개발 환경을 사용한다. 새 의존성은 없다.
명시적 `--fetch`가 없으면 키를 읽거나 HTTP를 호출하지 않는다. 없는 cache는 not_requested다.
기존 실패 cache도 재사용한다. 키를 바꾸거나 실패를 다시 확인하려면 새 cache 경로를 쓰거나
`--fetch --refresh`를 명시한다. refresh는 기존 성공/실패 응답의 content-addressed archive를
남기고 현재 조회 index만 갱신한다. 원본 cache와 공개 output은 서로 다른, 포함 관계도 없는 디렉터리를 쓴다.

```powershell
# 먼저 오프라인 구조를 확인. 산출물 디렉터리는 매번 새 경로여야 한다.
uv run python -m scripts.spikes.diary_storyboard.collect_record_envelopes --input scripts/spikes/diary_storyboard/fixtures/record_envelopes_gangnam.json --cache ../private-record-cache --out ../record-run-empty

# 외부 호출: 환경변수 또는 private dotenv의 DAENGS_DATA_GO_KR_SERVICE_KEY 사용
uv run python -m scripts.spikes.diary_storyboard.collect_record_envelopes --input scripts/spikes/diary_storyboard/fixtures/record_envelopes_gangnam.json --cache ../private-record-cache --out ../record-run-live --env-file ../private-key.env --fetch --max-requests 12 --max-pages 3

# 저장 응답으로 재생. HTTP 0회, 같은 원본/캐시/정책이면 동일 snapshot.
uv run python -m scripts.spikes.diary_storyboard.collect_record_envelopes --input ../record-run-live/snapshot.json --cache ../private-record-cache --out ../record-run-replay
uv run python -m scripts.spikes.diary_storyboard.record_envelopes ../record-run-replay/snapshot.json
```

성공·실패 모두 새 봉투가 이전 조회를 대체할 수 있다. 이미 존재하는 ID는 다시 append하지 않는다.
현재 v1은 명시적으로 새로 수집한 결과를 선택하므로, 갱신 실패 시 과거 성공 자료로 자동 fallback하지 않는다.
원본을 편집한 새 버전과 이전 버전 봉투를 섞으면 계약 검사가 거부한다. 저장소의 기존 합성 봉투를
provider 자료로 재분류하지 않도록, 실제 수집 입력은 records-only 예시를 별도로 제공한다.

## 산출물과 검증

- `snapshot.json`: 원본 기록 + 선별된 API 필드·관계·출처·시간·상태 봉투. 원본 API 전문은 없음.
- `receipt.json`: 입력/출력 해시, 요청 수, cache hit, source hash, 상태별 봉투 수.
- `README.md`: 기록 종류별 수집 상태. 목록 항목 수는 실제 행동 횟수·방문 횟수가 아님.
- private cache: 성공 원본 페이지와 페이지 해시, 고정 실패 코드, 조건별 cache index, 해시별 receipt 이력.

```powershell
uv run pytest tests/spikes/diary_storyboard/test_record_envelopes.py tests/spikes/diary_storyboard/test_collect_record_envelopes.py tests/test_storyboard_sources.py -q
uv run ruff check scripts/spikes/diary_storyboard/record_envelopes.py scripts/spikes/diary_storyboard/envelope_sources.py scripts/spikes/diary_storyboard/collect_record_envelopes.py tests/spikes/diary_storyboard/test_record_envelopes.py tests/spikes/diary_storyboard/test_collect_record_envelopes.py
```

검사는 HTTP MockTransport를 사용한다. 실제 API 응답에서 선별한 공개 결과는 연구 보고서에
별도로 보존한다. 모델 호출, 움직임 봉투 계산, 하천 형상/SGIS 경계 연결, DB 저장, 근처 카드와
App 연결은 이번 PR에 없다. 하천 시점 데이터만으로 주변 하천을 잘 설명할 수 없다는 실제 한계와
날씨의 403 응답을 성공으로 포장하지 않는다.
