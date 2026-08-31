---
status: exploring
implementation: shadow
---
# Source facts — 목적과 동반 조건을 원천별로 읽는 내부 경계

## 결론

KCISA와 KTO는 둘 다 반려동물 장소를 공급하지만 **같은 종류의 레코드가 아니다.** 공통
`facility.pet` JSON 봉투에 넣는 순간 다음 차이가 가려졌다.

- KCISA는 `카테고리1/2/3`, 동반 가능, 전용, 입장 동물 크기, 실내외 플래그를 한 CSV 행에 준다.
- KTO 목록은 `contenttypeid`와 `lclsSystm1/2/3`로 장소 목적을 주고,
  `detailPetTour2`가 전/일부 구역, 동반 대상, 준비물, 예외, 편의시설을 별도로 준다.
- 같은 장소에 연결될 수 있어도 원천 레코드의 사실은 합치기 전까지 독립적이어야 한다.

PR1은 `app/place/source_facts/`에 **순수 projection 경계**만 만든다. DB, ingest, 검색,
resolver, 외부 Place 응답은 바꾸지 않는다. 이는 spatial RAG나 embedding 도입이 아니라,
그보다 먼저 필요한 “무엇을 의미 검색의 재료로 쓸 수 있는가”를 고정하는 작업이다.

## 전후 구조

| 기존 | PR1 shadow 구조 |
|---|---|
| `ingest/kcisa.py`가 선택한 일부 필드를 `facility` 컬럼과 `pet`에 즉시 평탄화 | 공식 CSV 한 행을 `project_kcisa()`가 원천 의미를 보존한 facts로 투영 |
| KTO 목록은 `raw`, 상세는 KCISA와 키가 다른 `pet`에 저장 | `project_kto(listing, detail)`가 목록 taxonomy와 상세 접근조건을 따로 읽음 |
| `{}`가 미호출·호출실패·무자료 중 무엇인지 모름 | `FactState`로 `not_fetched`, `not_provided`, `parse_failed`, `unknown`을 구분 |
| 목적, 공간, 입장조건을 `kind`/`indoor`/자유문장에서 소비자가 재해석 | `purpose`, `pet_access`, `restrictions`, `amenities`, `operations`로 역할 분리 |
| 원문 충돌이 조용히 덮임 | `evidence`와 `issues`에 원천 필드·parser 버전·충돌을 남김 |

```text
KCISA CSV row ── project_kcisa ─┐
                               ├─ SourceFactProjection (shadow only)
KTO list + detail ─ project_kto ┘

현재 facility/Place API/search ───────────────────── 그대로
```

## 공통 facts는 공통 저장 형태가 아니라 공통 질문이다

| 질문 | 내부 경로 | 넣지 않는 것 |
|---|---|---|
| 이 장소의 목적은 무엇인가 | `purpose.primary`, `taxonomy_path` | 실내/실외, 반려동물 허용 여부 |
| 반려동물과 들어갈 수 있는가 | `pet_access.allowed`, `scope` | 장소 업종 |
| 어느 구역인가 | `pet_access.zone_hints` | `facility_environment` 같은 추정 라벨 |
| 어떤 조건이 붙는가 | `restrictions.predicates`, `raw` | 편의시설과 제공 물품 |
| 무엇이 준비되어 있는가 | `amenities.*` | 입장 필수조건 |

값과 획득 상태도 분리한다. `allowed=false`는 알려진 불허이고 `allowed=null + unknown`은 아직
모르는 것이다.

| `FactState` | 뜻 |
|---|---|
| `known` | 원천 값이 있거나 결정론적으로 해석됨 |
| `not_provided` | 원천 응답은 얻었지만 해당 필드가 없음 |
| `not_fetched` | 상세 endpoint를 아직 호출하지 않음 |
| `not_applicable` | 원천이 해당 없음을 명시함 |
| `parse_failed` | 값은 있지만 허용된 어휘로 읽지 못함 |
| `unknown` | 현행 저장 형태 때문에 위 상태를 복원할 수 없음 |

## KCISA projector

원천은 [한국문화정보원 공식 CSV](https://www.data.go.kr/data/15111389/fileData.do?recommendDataYn=Y)다.
공공데이터포털도 사람이 입력·검수한 자료라 오류가 있을 수 있고 `최종작성일`을 확인하라고
명시한다. 따라서 Y/N 플래그를 다른 의미로 다시 이름 붙이지 않고 원문 evidence로 보존한다.

| 원천 필드 | facts | 규칙 |
|---|---|---|
| `카테고리1/2/3` | `purpose.taxonomy_path`, `primary` | 3단계 원문 보존, 기존 공식 kind 매핑 재사용 |
| `반려동물 동반 가능정보` | `pet_access.allowed` | Y/N만 확정, 다른 값은 `parse_failed` |
| `반려동물 전용 정보` | `pet_access.exclusive` | `반려동물 전용`/`해당없음`만 확정 |
| `장소(실내/실외) 여부` | `source_indoor/outdoor`, `zone_hints` | 시설 환경으로 일반화하지 않음 |
| `반려동물 제한사항` | 공통 predicate + raw | 기존 전수 판독표를 사용하고 원문 유지 |
| `입장 가능 동물 크기` | 종/크기 predicate | `geo.pet.derive_axes`의 결정론적 축 재사용 |
| `애견 동반 추가 요금` | `pet_fee` | 무료/없음과 원 단위 숫자만 구조화 |

2025-03-24 CSV 70,650행을 다시 확인한 실내외 조합은 `Y/Y/N` 53,147행,
`Y/Y/Y` 13,591행, `N/N/N` 2,811행, `Y/N/Y` 1,101행이었다
(`allowed/indoor/outdoor` 순). `allowed=N + indoor=Y`는 0행이었다. 반면 동반 가능 박물관·미술관·
문예회관에서 `indoor=N, outdoor=Y`가 실제로 존재하고, `야외만/실외만` 제한문과 실내 Y가
충돌하는 행도 있다. 그래서 두 플래그는 **반려동물 이용 구역 힌트**로 읽되, 명시적인
`zone:outdoor_only` 제한문이 우선하고 충돌은 `zone_flag_conflict`로 노출한다.

현재 DB의 KCISA 21,112행은 ingest 단계에서 `allowed=N`과 개 불가 행이 이미 제외됐으며 원본
`카테고리1/2`, 설명, 실내외 원문을 전부 보관하지 않는다. 그러므로 PR1은 기존 DB를 거꾸로
정답 원천으로 삼지 않고 공식 CSV 형태를 입력 계약으로 삼는다. ingest 변경은 후속 PR이다.

## KTO projector

목록과 상세의 권위는 [한국관광공사 국문 관광정보 서비스](https://www.data.go.kr/tcs/dss/selectApiDataDetailView.do?publicDataPk=15101578)의
`petTourSyncList2`와 `detailPetTour2`다.

| 원천 필드 | facts | 규칙 |
|---|---|---|
| `contenttypeid` | `purpose.primary` | 기존 broad kind 매핑 재사용 |
| `lclsSystm1/2/3` | `purpose.taxonomy_path` | 코드 계층 그대로 보존; label을 추측하지 않음 |
| `acmpyTypeCd` | `pet_access.scope` | 전구역=`full`, 일부구역=`partial` |
| `acmpyNeedMtr` | 필수조건 predicate | 목줄·입마개·이동장·유모차·매너벨트 |
| `acmpyPsblCpam` | 대상 predicate | 품종·크기·예방접종·등록의 안전한 앵커만 추출 |
| `etcAcmpyInfo`, `relaAcdntRiskMtr` | 예외 predicate + raw | 자유문장은 항상 `partial` |
| `rela*Prdlst`, `relaPosesFclty` | `amenities.*` | 입장조건과 분리 |

2026-08-31 로컬 DB shadow 측정 결과:

| 항목 | 결과 |
|---|---:|
| KTO 전체 | 9,692 |
| 상세 JSON이 있는 행 | 248 |
| `acmpyTypeCd` 확정 | 246 (전구역 125, 일부구역 121) |
| taxonomy path 보존 | 9,692 |
| amenity가 있는 행 | 16 |
| projector 예외 | 0 |
| 제한 predicate 보유 | 246 |
| 제한 파싱 | partial 245, raw-only 1 |

상세가 없는 9,444행은 `not_fetched`라고 단정하지 않고 `unknown`이다. 현행 `pet={}`가 미호출,
요청 실패, 정상 no-data를 구분하지 않기 때문이다. 상세 JSON은 있으나 scope가 없는 2행은
`not_provided`다. 이 차이를 보존해야 나중에 수집 재시도와 검색의 “조건 미상”을 혼동하지 않는다.

## PR2 shadow source record

PR2는 `facility_source_record`를 추가한다. 제품 검색 행인 `facility`와 FK로 묶지 않고
`(source, record_ref)`를 PK로 쓴다. `source_ref`는 제품 행과 연결하기 위한 별도 열이다.
KCISA는 이름+좌표가 같은 원천 행이 여럿이라 `source_ref`를 PK로 쓰면 facility의 중복 제거가
원천 기록까지 지운다. KCISA `record_ref`는 전체 원문 행의 결정적 SHA-256 축약 hash이고,
제품 파싱에 실패한 행의 `source_ref`는 `unlinked:<record_ref>`로 격리한다. KTO는 안정
`contentid`를 두 키에 같이 쓴다.

KTO 제품 행은 워터마크 뒤 변경분만 적용하므로 `facility` 정리는 full 실행에서만 한다. 반면
shadow는 매 실행마다 검증된 sync-list 전체를 관측하므로, 성공한 목록 수집 뒤에는 매번
`observed_at` 기준으로 사라진 원천 레코드를 정리한다.

KCISA의 확정 불허 행은 제품 후보에서 계속 제외되지만 필터 전 CSV 원문은 shadow에 남는다.
2025-03-24 CSV 70,650개 물리 행은 23,980개 distinct 원문과 23,914개 제품 연결 키로
나뉘었다. 동일 원문은 한 JSONB로 저장하되 `occurrence_count` 합계가 70,650을 보존한다.
66개 제품 연결 키는 서로 다른 원문 variant를 두 개씩 가지고 있어, 기존 facility 중복 제거만
보면 사라지던 차이다.

실제 dual-read에서 KCISA distinct 원문 23,980개 중 2,802개는 제품 `facility`에 없었다
(`allowed=N` 또는 개 불가). 제품 행과 연결된 원문은 21,178개이며, 이 중 66개는 제품이 고른
원문과 다른 variant였다. 56개는 projector facts가 같았지만 **10개는 facts도 달랐다.** 따라서
후속 resolver가 동일 `source_ref`의 여러 원문을 임의로 첫 행 선택해서는 안 된다는 측정 근거가
생겼다. 플래그와 명시적 구역 제한이 충돌한 distinct 원문도 36개였다.

| 컬럼 | 역할 |
|---|---|
| `listing_raw` | KCISA 전체 CSV 행 또는 KTO `petTourSyncList2` 항목 |
| `occurrence_count` | snapshot 안에서 완전히 같은 원문 행이 반복된 횟수 |
| `detail_raw` | 성공한 KTO `detailPetTour2` payload. 실패/no-data는 NULL |
| `detail_state` | `not_applicable/not_fetched/fetched/no_data/fetch_failed/unknown` |
| `snapshot`, `observed_at` | 어떤 snapshot에서 마지막으로 관측됐는지 |
| `detail_attempted_at`, `detail_fetched_at` | 시도와 성공을 분리한 시각 |

KTO 목록 재적재는 같은 `modifiedtime`에서 이미 얻은 detail과 상태를 보존한다. 버전이
전진하면 `not_fetched`로 되돌려 정책 상세를 다시 얻는다. `showflag=0`처럼 제품에서 숨기는
sync-list 항목도 shadow 목록에는 남기되, 실제 `facility`가 없는 레코드는 상세 수집 대상에서
제외한다. 상세 요청은 다음처럼 전이한다.

```text
not_fetched ─┬─ payload ───> fetched
             ├─ 정상 빈 응답 > no_data
             └─ HTTP/쿼터 ─> fetch_failed ── 재시도 대상

legacy pet={} ─> unknown ── 재시도 대상
```

`no_data`는 자동 재시도 대상에서 제외한다. 정상 응답으로 자료가 없었다는 사실과 일시적 실패를
다시 합치지 않기 위해서다. 운영자가 정책을 정하면 별도 stale 기준으로 재검사할 수 있다.

0021 migration은 기존 KTO `raw/pet`을 shadow로 backfill한다. 비어 있지 않은 detail 248행은
`fetched`, 과거의 빈 `{}` 9,444행은 원인을 복원할 수 없어 `unknown`이다. backfill 직후
dual-read 결과는 다음과 같았다.

| 비교 | 일치/전체 |
|---|---:|
| 목록 원문 | 9,692 / 9,692 |
| 상세 원문 | 9,692 / 9,692 |
| projector facts | 9,692 / 9,692 |

projector 결과 자체는 저장하지 않는다. 아래 측정 명령이 shadow와 현행 `facility.raw/pet`을
같은 projector에 통과시켜 차이를 계산한다.

측정은 다음 읽기 전용 명령으로 재현한다.

```bash
uv run python scripts/source_fact_coverage.py
```

## PR3 candidate fact bundle

PR3는 저장된 shadow 원문을 검색 후보가 읽을 수 있게 하는 **내부 runtime bridge**다. 아직
검색 조건, AI tool, 외부 Place 응답은 바꾸지 않는다. `PlaceRef(source, ref)`에서 KCISA/KTO만
`SourceFactKey(source, source_ref)`로 옮기고, 최대 1,000개 키를 한 SQL로 조회한다.

동일한 `source_ref`에 여러 `record_ref`가 있으면 하나를 대표로 고르지 않는다. 각 원문을 현재
projector로 다시 읽은 `variants`와 물리 중복 수 `occurrence_count`를 모두 보존한다. canonical
section 값이 다르면 `purpose`, `pet_access`, `restrictions`, `amenities`, `pet_fee`, `operations`
단위의 `conflicts`를 명시한다. shadow가 없는 후보도 입력 위치에 `state=missing` bundle로 남겨,
“데이터 미상”이 “필터 탈락”으로 바뀌지 않게 한다.

```text
PlaceRef 후보 (최대 1,000)
        │ source/ref adapter
        ▼
SourceFactKey[] ── one SQL ── facility_source_record[]
                                │ current projectors
                                ▼
CandidateFactBundle[] = variants + conflicts + acquisition state
```

이 층은 충돌을 보여 주지만 해소하지 않는다. 어떤 variant를 믿을지, 미상 조건을 통과시킬지,
AI가 어떤 조건 플래그를 제안할지는 다음 검색 정책 층의 책임이다.

## fixture와 실패 규칙

무작위 몇 행이 아니라 의미 경계를 fixture로 고정한다.

- KCISA: 야외만 허용 문화시설, 플래그/제한문 충돌, 명시적 불허, kg+요금, 고양이 전용
- KTO: 전구역, 일부구역+kg+amenity, 상세 미조회, 해석 불가 자유문장, 잘못된 taxonomy 계층
- 모르는 값은 비우지 않는다. raw와 `parse_failed`/`raw_only`를 남긴다.
- parser가 추측 없이 실패하는 것은 허용하지만, 원문을 잃거나 projector가 예외로 중단하는 것은
  허용하지 않는다.

## 종료 조건과 후속 순서

PR1 종료 조건은 다음과 같다.

- source-facts 모델과 두 projector가 DB·HTTP 없이 순수하게 동작
- 실제 KTO 저장 행 전체 projection 실패 0
- 외부 `app/place/contracts.py`, OpenAPI, 검색 결과, ingest, schema 변경 0

후속 순서는 다음과 같다.

1. PR2: ingest acquisition 상태와 원천 snapshot shadow 저장 — 구현.
2. PR2: projector 결과를 적재하지 않는 dual-read 비교 — 구현.
3. PR3: 후보별 source record variant와 section conflict를 보존하는 runtime bridge — 구현.
4. 다음 PR: purpose 후보 생성과 거리/공간 제약을 별도 단계로 둔 검색 실험을 한다.
5. 이후: 데이터가 수백~천 건이면 PostGIS 필터 + 결정론적 predicate + 필요 시 텍스트 embedding
   rerank부터 검증한다. spatial RAG는 이 작은 후보군에서 성능 근거가 생길 때만 검토한다.
