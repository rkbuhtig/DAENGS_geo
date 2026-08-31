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

측정은 다음 읽기 전용 명령으로 재현한다.

```bash
uv run python scripts/source_fact_coverage.py
```

## fixture와 실패 규칙

무작위 몇 행이 아니라 의미 경계를 fixture로 고정한다.

- KCISA: 야외만 허용 문화시설, 플래그/제한문 충돌, 명시적 불허, kg+요금, 고양이 전용
- KTO: 전구역, 일부구역+kg+amenity, 상세 미조회, 해석 불가 자유문장, 잘못된 taxonomy 계층
- 모르는 값은 비우지 않는다. raw와 `parse_failed`/`raw_only`를 남긴다.
- parser가 추측 없이 실패하는 것은 허용하지만, 원문을 잃거나 projector가 예외로 중단하는 것은
  허용하지 않는다.

## PR1 종료 조건과 후속 순서

PR1 종료 조건은 다음과 같다.

- source-facts 모델과 두 projector가 DB·HTTP 없이 순수하게 동작
- 실제 KTO 저장 행 전체 projection 실패 0
- 외부 `app/place/contracts.py`, OpenAPI, 검색 결과, ingest, schema 변경 0

후속 PR은 이 순서다.

1. ingest acquisition 상태와 원천 snapshot을 보존하는 shadow 저장소를 설계한다.
2. projector 결과를 적재하지 않고 dual-read로 비교해 차이와 결측을 계측한다.
3. purpose 후보 생성과 거리/공간 제약을 별도 단계로 둔 검색 실험을 한다.
4. 데이터가 수백~천 건이면 PostGIS 필터 + 결정론적 predicate + 필요 시 텍스트 embedding
   rerank부터 검증한다. spatial RAG는 이 작은 후보군에서 성능 근거가 생길 때만 검토한다.

