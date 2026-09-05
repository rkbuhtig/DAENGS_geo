# 2026-09-04 인수인계 — 산책 스토리보드에서 행동 프로필 개인화까지

> 후속 구현과 재개 순서는 [공간 일기 제작 계획](../explorations/walk/diary-storyboard-plan.md)을
> 먼저 읽는다. 아래 내용은 당시 실험과 구상의 기록이며 현재의 미구현 목록이 아니다.

**다른 컴퓨터/새 대화에서 이어받기 위한 시작 문서다.** 대화 기록이나 이전 PC의 localhost에
접근할 수 없어도 현재 결과, 제안의 이유, 코드 위치, 남은 작업을 구분해서 읽을 수 있게 쓴다.
이 문서는 2026-09-04의 스냅샷이다. 이후의 결정·코드가 바뀌면 최신 상태를 먼저 확인한다.

## 0. 먼저 알아야 할 여덟 가지

1. 사용자의 담당 관심사는 **Walk·Journey·Place**다. geo는 공간/산책 연구 저장소로 쓴다.
2. 산책을 ‘일기를 쓰는 문장’보다 **시작→이동→중간 Pin→종료의 연속 장면**으로 보자는
   사용자 방향 전환이 있었다. 이미지 흐름을 먼저 보고 필요한 설명을 붙인다.
3. 점령 게임에 필요한 동네 구별을 스토리보드 소재로도 쓰자는 구상이 나왔다. 공통 지역
   재료를 써도 동 진입·실제 행동·게임 성과는 각각의 근거가 필요하다.
4. 실제 SGIS 경계와 상가·공원·하천 API를 합성 산책에 붙인 **로컬 스토리보드 실험은 구현됐다.**
   코드/문서는 PR #227로 main에 머지됐다. 실제 사용자 행동을 분석한 결과가 아니다.
5. 이어서 사용자가 **행동 Pin으로 강아지의 상황별 경향을 요약하고, 다음 산책에 활용하는
   구조**를 제안했다. 이 기능은 아직 구현하지 않았다.
6. ‘프로필에서 기록된 모습을 먼저 설명하고, 이후 관련 기억/제안을 연결하자’는 진행 순서는
   대화에서 나온 권장안이다. 사용자가 세부 설계·문턱값·운영 계약을 채택한 것은 아니다.
7. 기존 계약상 자유 메모를 자동으로 성격/경향에 승격할 수 없다. **강아지에 귀속된 구조화된
   행동 증언**과 그 근거로 첫 실험을 설계한다. 기존 DogProfile 원본을 자동 수정하지 않는다.
8. 이번 인수인계 PR은 문서만 추가한다. 행동 프로필·추천·모델·운영 API는 새로 만들지 않았다.

바로 이어 읽을 상세 설계:
[행동 Pin → 상황별 프로필·개인화](../explorations/walk/behavior-profile-and-personalization.md).

## 1. Git 상태와 이미 끝난 작업

인수인계 작성 시작 때 `origin/main`은
`2bb0f467e5f3bb5715eb961b7b94766d65ccb8ee`였다. 새 문서 브랜치는
`docs/behavior-profile-handoff`이며 이 main에서 시작했다.

| PR | 내용 | 확인한 상태/기준점 |
|---|---|---|
| [#226](https://github.com/rkbuhtig/DAENGS_geo/pull/226) | 스토리보드와 동네 구간 구상 문서 | MERGED · `0defc3ab402e61df978c803d82dff7a052f66c77` |
| [#227](https://github.com/rkbuhtig/DAENGS_geo/pull/227) | 실제 자료 + 합성 산책 스토리보드 | MERGED · merge `8365284bbfa90bed6ce8a52ad2cdb6ff832eebf5` |
| [#228](https://github.com/rkbuhtig/DAENGS_geo/pull/228) | 시즌 점령전 탐색 | MERGED · merge `2bb0f467e5f3bb5715eb961b7b94766d65ccb8ee` |

스토리보드 구현 자체의 commit은
`d3ab21d5a3d3da237a9493ab79bbb745add9a357`이다. #228의 게임 가설이 추가됐다고
#227의 `영역 2칸 획득` fixture가 실제 시즌 점수 계산으로 바뀐 것은 아니다.

다음 세션에서는 main에 이 인수인계 문서가 있으면 최신 main에서 읽는다. 아직 머지 전이면
이번 문서 PR의 브랜치를 checkout한다. 이 문서가 과거 브랜치로 강제 복귀하라는 의미는 아니다.

## 2. 대화가 여기까지 온 과정

| 순서 | 질문/변화 | 현재 이어받을 의미 |
|---|---|---|
| 1 | geo를 무엇을 하는 레포인지 분석해달라는 요청 | 운영 기능 수정 전 연구/계약/실험의 역할을 파악 |
| 2 | APP와 dev가 원천이므로 함께 봐야 한다는 요청 | geo에 남은 사본을 운영 canonical로 오해하지 않음 |
| 3 | 사용자가 Walk·Journey·Place를 담당한다고 설명 | 산책 경험을 장소와 경로에 연결하는 관점 |
| 4 | 산책 세션을 읽어 주변 정보/이벤트와 요약을 붙이는 서비스의 공백 제기 | 하위 사실 수집 위에 장면 조립·근거·서술 층 필요 |
| 5 | geo의 고민 문서와 dev 오케스트레이션 확인 | 새 기능이 기존 라우팅/실행/응답 집계와 어떻게 만나는지 검토 |
| 6 | ‘일기’ 비유에서 ‘연속 상영하는 스토리보드’로 전환 | 시작·끝·Pin 순서를 유지하고 문장 길이보다 흐름을 먼저 검증 |
| 7 | 점령 게임의 지역 구별을 스토리보드 소재로 재사용 제안 | 지역 카탈로그는 공유 후보, 게임 성과는 독립 증거 |
| 8 | 좌표에서 실제 지역 정보를 얻을 수 있는지 검증 필요 제기 | 행정 경계/이름/공간 문맥을 실자료로 실험 |
| 9 | 상가·공원·하천 API를 모두 넣어 시나리오 스토리보드를 만들어달라는 요청 | 실제 API 수집, SGIS 신청, 합성 경로 3종과 재생 화면 구현 |
| 10 | 구현해본 소감 요청 | 지역 분할보다 장면 선택·압축이 다음 과제로 드러남 |
| 11 | 행동 Pin 기반 프로필/다음 산책 개인화 제안 | 상황별 행동 증거를 여러 산책에 걸쳐 읽는 새 탐색 |
| 12 | PC를 옮기기 전 상세 문서와 PR 요청 | 이 문서와 새 행동 프로필 설계 문서를 남김 |

‘앱에 기록하고 처음 걷는 곳’과 ‘생애 처음 걷는 곳’은 다르다는 점을 사용자가 직접 짚었다.
관련 표현을 만든다면 ‘현재 보관된 기록에서 처음 등장’과 비교 범위를 명시해야 한다.
이벤트 feed는 초기 관심사에 있었지만 이번 공공데이터 실험은 실시간 행사 정보를 수집하지 않았다.

### 이전에 제안됐지만 고정하지 않은 이름/규모

초기 첨부 구상에는 `Walk Narrative Assembly`, `WalkNarrativePacket`, Scene Selector,
Spatial Context Resolver, Claim Policy, Evidence Receipt 같은 후보 이름이 있었다.
그 구조의 의도는 나레이터가 원천 전체를 받아 자유롭게 이야기를 만들기 전에 **허용된 장면과
근거를 조립하자**는 것이었다. 현재 실행 코드에 이 이름들의 완성 타입/API가 있는 것은 아니다.

초기 문장 중심 구상의 ‘장면 0~3개’와 이후 논의한 ‘약 5장 압축판’은 서로 다른 실험 후보다.
3장/5장을 운영 제한으로 고정하지 않는다. 현재 동작하는 기본판은 13장이다.

장면을 먼저 고르고 세부 문맥 조회를 제한하자는 접근도 제안됐다. 이번 spike는 주어진
지역 범위의 원천을 먼저 수집한 뒤 장면을 조립한다. API 공급 범위를 확인하는 실험으로는
유용했지만 운영 호출 순서나 비용 최적화를 증명한 것은 아니다.

## 3. 저장소 역할과 확인 기준

| 저장소 | 이 작업에서의 역할 |
|---|---|
| [DAENGS_geo](https://github.com/rkbuhtig/DAENGS_geo) | 공간/산책 R&D, 근거 계약, 합성 fixture, 측정, 프로토타입 |
| [DAENGS_dev](https://github.com/SAJOYO/DAENGS_dev) | 운영 Place/Journey와 메인 backend, 실제 프로필/인증/오케스트레이션 접점 확인 대상 |
| [DAENGS_APP](https://github.com/SAJOYO/DAENGS_APP) | 실제 Android 지도·Place UX 및 향후 산책 입력/프로필 UI 적용 대상 |

geo→제품은 두 저장소를 계속 동기화하는 방식이 아니라, 실험과 근거를 만든 뒤 필요한 부분을
명시적으로 **승격**하는 흐름이다. 자세한 기준은 [docs 지도](../README.md)와
[promotion ledger](../promotion-ledger.toml)를 읽는다.

dev 오케스트레이션의 이전 확인 기준은
`eb804cc5eda135df88c1c1608a4690253968230e`다. 당시 확인한 경계:

- 결정론적 라우팅과 선택적인 의미 라우팅, 입력 조립, capability adapter 실행, 결정적 집계.
- Walk 능력은 현재 환경의 산책 적합도였다. 저장 산책의 개인 기억/장면 조립/나레이터가 아니었다.
- 대화 저장이 있다고 장기 행동 기억과 개인화 조회가 자동 구현된 것은 아니었다.
- 별도 도메인 기능을 대화 adapter로 연결하거나, 명확한 종료 후 작업은 직접 호출할 수 있다는 제안.

후속 운영 작업 전에
[당시 orchestration](https://github.com/SAJOYO/DAENGS_dev/tree/eb804cc5eda135df88c1c1608a4690253968230e/backend/src/daengs_backend/orchestration)와
[당시 결정 문서](https://github.com/SAJOYO/DAENGS_dev/blob/eb804cc5eda135df88c1c1608a4690253968230e/docs/decisions.md)의
D-044/D-047을 최신 코드와 대조해야 한다. 이 인수인계가 운영 배포 상태를 새로 실측한 것은 아니다.
APP도 이번 문서 작업에서 최신 전체 구현을 재감사하지 않았다.

## 4. 꼭 지켜야 할 기존 경계

1. `WalkFacts`는 시간·거리 등 사실 계약이다. 행동·감정·성격·보상을 되밀지 않는다.
2. `CanonicalTrail`의 gap/jump/accuracy 거부/chain 단절을 화면 때문에 다시 잇지 않는다.
3. measured(관측), captured(확보한 외부 문맥), attested(사용자 증언), edited(표현)를 구분한다.
4. `Attestation`의 confirmed는 보호자의 확인이지 센서가 검증한 행동 진실과 동일하지 않다.
5. `OfferInteraction`의 무응답/dismiss/expire는 행동이 없었다는 증언이 아니다.
6. Pin correction은 현재 의미만 갱신한다. 최초 Offer 응답 역사와 안정 Pin identity는 보존한다.
7. 현재 projection은 정정/삭제를 따라 재계산하지만 확정된 PublishedJournalSnapshot은 별도 수명이다.
8. Context Plane의 capability/Lens는 닫혀 있다. 현재 행동 이력 capability는 등록돼 있지 않다.
9. 자유 메모를 경향/프로필/다른 산책의 판단으로 자동 승격하지 않는다.
10. geo의 #85는 연속 경로의 서버 영구 저장을 열지 않았다. Lab/fixture/기존 원본 수명을
    늘리지 않는 종료 직후 미리보기만 현재 허용 범위다.
11. 이전에 본 dev D-044는 raw 좌표를 삭제까지 보존하는 다른 전제를 갖고 있었다.
    geo의 purge 제약을 운영에 그대로 일반화하거나, dev의 수명을 geo 실험에 역적용하지 않는다.
12. 공원 주변·동 진입·Site 접촉·Capture·시즌 점수는 서로 다른 증거를 소비한다.

## 5. 실제 스토리보드 실험의 구성

상세 실측은 [기존 연구 기록](2026-09-04-storyboard-regions-spike.md)에 있고, 실행 방법은
[spike README](../../scripts/spikes/storyboard_and_regions/README.md)에 있다.

| 파일 | 현재 역할 |
|---|---|
| `scripts/spikes/storyboard_and_regions/sources.py` | 세 API의 bounded pagination/cache/상태/키 분리 및 보조 EGIS 수집 |
| `scripts/spikes/storyboard_and_regions/geometry.py` | SGIS ZIP/CRS 읽기, 유효 구간별 경계 분할, 순서/단절/불확실성 |
| `scripts/spikes/storyboard_and_regions/build.py` | 합성 경로·기존 simulator/Walk 계산·주변 문맥·장면 조립 |
| `scripts/spikes/storyboard_and_regions/viewer.html` | 내장 JSON 기반 지도 컷, 타임라인, 자동 재생, 출처 보기 |
| `scripts/sim/walk/` | 기존 motion truth/관측/전달 분리 시뮬레이터 |
| `tests/test_storyboard_sources.py` | pagination/실패/0건/키 취급의 전용 테스트 |
| `tests/test_storyboard_regions.py` | 순서/공백/귀속 범위/시나리오의 전용 테스트 |

### 실행한 세 시나리오

| 시나리오 | 장면 수(게임 포함) | 계산 이동거리 | 관측 공백 |
|---|---|---|---|
| 기본 산책 | 13 | 2,859m | 없음 |
| 기록이 끊긴 산책 | 13 | 2,622m | 995~1,185초, 190초 |
| Pin 없는 산책 | 12 | 2,859m | 없음 |

기본 산책은 약 38분 49초다. seed는 904, 합성 시작 시각은 2026-09-04 18:00 KST,
속도는 기본 1.25m/s, 관측 간격 5초, 보고 accuracy 3m, 한 hold 35초를 썼다.
입력 dropout 창은 1,000~1,180초지만 남은 양 끝 관측 사이 gap은 995~1,185초다.
입력 오염 창과 관측된 공백 길이가 다른 것은 이 표의 오타가 아니다.

도곡1동 → 도곡2동 → 대치1동 → 개포2동 → 개포1동 → 개포4동 → 도곡2동의 안정 구간을
얻었다. 두 번의 도곡2동은 순서상 별도 구간이다. 출발점 복귀를 증명한 결과는 아니다.
실제 도로·교량 routing을 하지 않은 손으로 정한 좌표 시나리오이며 길 안내로 쓰지 않는다.

Pin 메모와 ‘영역 2칸 획득’은 fixture다. 실제 사진·강아지 행동·증언 DB·게임 판정을 읽지 않는다.
게임 토글은 장면 표시를 바꿀 뿐 기존 영토 엔진을 호출하지 않는다.
나레이션은 템플릿이며 LLM/음성 합성/행사 feed 호출이 없다.

### 현재 실험의 임시 선택값

- 안정 동 구간 60초 이상을 챕터 후보로 삼음. 처음 출발 동은 중복 장면으로 다시 만들지 않음.
- 공원 대표점/하천 형상 근접은 250m 이내 후보.
- 상권 설명은 관측점 반경 125m, 중심 원천 질의는 반경 1,200m.
- 125m 원 전체가 1,200m 수집 원에 들어가는 경우만 완전한 상가 근접 집계로 취급.
- EGIS 요청의 ±3,000m는 EPSG:3857 투영 좌표 상자다. 지상 반경 3km 원이라는 뜻이 아니다.
- 화면 표시용 단순화는 별도이고 공간 판정 polygon 자체를 그 표시 형상으로 대체하지 않음.

이 숫자들은 게임 규칙, 행동 프로필 기준, 전역 추천 문턱으로 채택되지 않았다.

## 6. 실제 데이터의 양과 공백

| 출처 | 확인한 결과 | 이 자료만으로 알 수 없는 것 |
|---|---|---|
| SGIS 서울 읍면동 | 426개 경계, 2025-06-30 기준 | 일상적 동네 체감과의 일치, 타 기관 코드 crosswalk |
| 소상공인시장진흥공단 상가 | 중심 127.052/37.487 반경 1,200m, 4,647건, 5페이지 | 현재 영업·실제 방문·혼잡도 |
| 전국도시공원정보 | 강남구 제공기관 필터, 146건, 1페이지 | 공원 내부 포함·반려견 허용·풀밭 소재 |
| 전국하천표준데이터 | 전국 2,558건, 3페이지, 시점 좌표 보유 194행 | 하천 선형, 모든 지역의 하천 완전성 |
| 보조 EGIS 하천 형상 | 탄천·양재천·세곡천·여의천 4개 | 형상 기준연도, 실제 산책로 이용 |

전국하천 응답에서 **양재천·탄천 이름의 항목을 찾지 못했다.** 조회 실패도, 그 하천이
현실에 없다는 뜻도 아니다. 지도에서는 별도로 받은 EGIS 형상을 사용했다.
공원 예시는 늘벗근린공원이며 대표점 37.48928087/127.0563303, 자료 기준일 2026-01-29였다.

Endpoint는 코드에 있다. 참고로 공원은
`https://api.data.go.kr/openapi/tn_pubr_public_cty_park_info_api`, 하천은
`https://api.data.go.kr/openapi/tn_pubr_public_river_info_api`, 상가는
`https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius`를 썼다.
사용자가 제공한 인증키는 문서와 PR에 넣지 않는다.

### 당시 산출물 식별값

새로 API를 조회하면 데이터·수집 시각이 달라지므로 다른 fingerprint가 정상일 수 있다.
아래 값은 **동일 snapshot을 가져왔는지** 확인하는 비교 기준이지, 새 응답에 강제하는 기대값이 아니다.

```text
bundle:
7dbca8f7a8e11b372ea877770146b17b427fa4fc7527075d4c537cd7fad3c99f

SGIS ZIP SHA-256:
47d946ef51f04aaac7deb00ea0edae1e63ded3a0e976c62c191b53a98c17a62b

parks snapshot:
acdf16640773ab5e8885c85e9dd96c98e47afd5b1b63464cd4d56d8921919a5e
rivers snapshot:
cadb5761662689993b0975fcf0ffeed498d6ccb1f3e07881584d38ae588f769d
commerce snapshot:
b6318b5372b9eef182730ff93e229f6df6741bdfa2fc6b04e27a703091a314bc
EGIS snapshot:
d49caf1776b140b543498696a6cf1099d0c4f535b3d2bfe164a07409828ccd80
```

표준 데이터 수집은 UTC 2026-09-04 06:16대, EGIS는 06:25대였다. 원천 기준일과 수집 시각은
다른 필드다. 인수인계 시 실행 환경에서 확인한 선택 의존성 버전은 pyshp 3.1.6,
Shapely 2.1.2, pyproj 3.7.2, httpx 0.28.1이었다. Python은 프로젝트 요구대로 3.12다.
선택 의존성이 프로젝트 lock에 모두 고정된 것은 아니므로 재현 시 설치 버전도 기록한다.

## 7. UI를 보고 나온 소감과 다음 편집 실험

다음은 사용자 실험으로 입증된 결론이 아니라, 합성 프로토타입을 만든 뒤 대화에서 나온 평가다.

- 동네 이름과 재진입 순서는 Pin 없는 산책에도 설명할 흐름을 준다.
- 동네가 바뀔 때마다 장면을 만들면 비슷한 지도를 반복하게 된다. 기본판 13장은 압축 여지가 있다.
- 공원·물가·사용자가 남긴 Pin처럼 체감되는 변화와 지역 구간을 함께 고려해야 한다.
- 주변 데이터는 장면의 배경을 채우고, Pin은 해당 산책에 남긴 사건의 의미를 제공한다.
- 근거 검증용 화면에는 미확인 설명이 필요하지만 감상 화면은 과도한 설명을 줄일 필요가 있다.
- 근거가 없는 구간을 조용히 넘길 수 있어야 한다. 모든 산책에 특별한 의미를 만들어낼 필요가 없다.

다음 편집 비교군으로 ‘출발·특징 있는 구간·Pin·돌아오는 흐름·마무리’ 정도의 **약 5장**을
제안했다. 실제 복귀가 없으면 돌아오는 흐름을 억지로 만들지 않는다. 5장으로 줄여도 근거와
gap이 남는지, Pin이 없는 경우도 읽히는지 비교한다. 현재 코드에는 그 압축판이 없다.

## 8. 행동 프로필 논의의 정확한 이어받기

사용자는 두 가지 소비를 제안했다.

1. Pin을 바탕으로 개인화 데이터를 만들고 다음 산책의 미시 움직임에 맞춰 제안하기.
2. 우선 프로필에 ‘어디에서 어떤 경향을 보여주는 강아지인지’ 요약해 설명하기.

대화에서 제시한 방향은 두 기능이 **같은 상황별 행동 근거를 읽는 구조**다. 고정 성격을
만들기보다 어느 상황에서 무엇을 기록했는지 먼저 보여준다. ‘프로필부터’는 더 작은 사용자
검증 단위라는 권장이지, 향후 산책 제안을 취소한 결정이 아니다.

예시는 가상이다: 서로 다른 네 번의 산책에 특정 장소의 냄새 탐색 기록이 있으면
“이 장소에서 냄새를 탐색했다는 기록이 네 번의 산책에 있어요”라고 설명하고 근거 Pin으로
연결한다. 여기서 ‘공원을 좋아함’, ‘불안해서 멈춤’, ‘행동 발생률 70%’를 자동 생성하지 않는다.

후속 설계 문서에는 다음을 상세히 정리했다.

- 기존 타입/미구현 기능의 구분과 구조화된 증언의 입력 자격.
- 현재 correction head, dog/owner/joint 귀속, 미지원 어휘와 uncertain 처리.
- Pin 수·산책 수·날짜/장소 다양성의 분리와 행동별 분모 문제.
- 원천 공간 해상도, 사건 시각/입력 시각, 과거/current profile의 구별.
- 파생 projector/근거 참조/fingerprint/cache 후보와 예시 JSON.
- 프로필 표시·관련 기억 회수·다음 산책 선택 제안·미시 확인의 단계.
- 정정/삭제/노후화/피드백 순환/모델 평가의 반례.
- geo→dev→APP 승격 경계와 Context registry 확장에 필요한 별도 결정.

**이 문서 작업에서 행동 프로필 코드, 새 DB/API, 추천 모델은 만들지 않았다.**

## 9. 다른 컴퓨터로 옮길 때 Git에 있는 것과 없는 것

| 대상 | Git/PR에서 받을 수 있나 | 없어도 가능한 일 |
|---|---|---|
| 설명/설계/연구 문서 | 가능 | 전체 구상과 반례 읽기 |
| simulator와 storyboard 코드/테스트 | 가능 | 합성 입력/로직 검토, 선택 의존성 설치 후 전용 테스트 |
| 행동 프로필 구현 | 없음, 아직 미구현 | fixture/projector 새 실험 설계 |
| 완성 `index.html`, `storyboard.json` | 기존 PC 로컬에만 있음 | 없으면 같은 코드로 재생성 필요 |
| 세 API 전체 cache | 기존 PC 로컬에만 있음 | 없으면 키로 재조회; 과거와 동일 snapshot 보장은 없음 |
| SGIS 경계 ZIP | 기존 PC Downloads에만 있음 | SGIS 계정의 신청자료 다운로드에서 다시 받거나 사용자 경로로 이동 |
| 인증키 `.env.storyboard` | Git 제외, 기존 PC에만 있음 | 코드/합성 테스트는 가능; 새 외부 수집에는 별도 키 설정 필요 |
| 이전 브라우저 탭·localhost 서버 | 이전 PC의 프로세스/브라우저 상태 | 새 PC에서 다시 서버를 실행 |

현재 이 문서 PR은 원본 데이터를 업로드하거나 두 PC 사이로 자동 전송하지 않는다.
**Git clone만으로 이전 localhost 화면과 실제 cache가 생기지 않는다.**

### 이전 PC의 위치를 찾는 방법

사용자 홈을 기준으로 한 당시 workspace:

```text
Documents/Codex/2026-09-04/https-github-com-rkbuhtig-daengs-geo/
  work/DAENGS_geo/                         ← Git 저장소
    .env.storyboard                       ← 비공개 인증키 설정
  outputs/walk-storyboard/
    index.html                            ← 단일 파일 뷰어
    storyboard.json                       ← 합성 시나리오/근거 bundle
  outputs/storyboard-source-cache/
    parks-43bfc6a2a0627543.json
    rivers-44136fa355b3678a.json
    commerce-973e2c4f64b55e72.json
    egis-water-receipt.json

Downloads/bnd_dong_11_2025_2Q.zip           ← SGIS 다운로드
```

위 cache 디렉터리에 초기 probe 파일도 있었지만 재생성에는 위 네 receipt 파일이 필요하다.
`parks.json`, `rivers.json`, `commerce.json`, `rivers_all_1.json`, `egis-rivers.json` 같은 초기
조사 파일로 이름을 바꿔 대신 넣지 않는다. build는 질의 fingerprint로 정확한 cache를 읽는다.

`index.html`만 사용자 기기 사이에 옮기면 당시 화면을 볼 수 있다. 완전한 재계산에는 cache와
경계 ZIP도 필요하다. 원본 cache에는 기관 연락처 등 표시하지 않는 필드가 들어갈 수 있으므로
공개 PR 첨부로 올리는 대신 사용자가 관리하는 비공개 전달 경로를 사용한다. 키도 별도로
설정하며, 이 인수인계 문서에 복사하지 않는다.

## 10. 새 컴퓨터에서의 실행 절차

### 10.1 문서와 코드 받기

`git`, `uv`가 준비된 환경에서 새 clone을 만드는 예시다. 기존 checkout이면 그 저장소의
변경분과 branch부터 확인한다. `reset --hard`나 기존 작업 삭제는 재개 절차가 아니다.

```bash
git clone https://github.com/rkbuhtig/DAENGS_geo.git
cd DAENGS_geo
git fetch origin
git status --short
```

main에 인수인계 문서가 아직 없으면 이번 PR을 checkout하거나 아래 브랜치를 쓴다.
브랜치가 이미 머지/삭제됐다면 최신 main의 문서 경로를 확인한다.

```bash
git switch --track origin/docs/behavior-profile-handoff
```

작업할 디렉터리에 적용되는 `CLAUDE.md`를 root부터 찾고, 있으면 전부 읽는다. 이 문서 작성
때 geo 안에서는 없었지만 이후 상태도 없다고 단정하지 않는다. dev/APP에는 별도 지침이 있다.

### 10.2 기존 화면만 보기

옮겨온 `index.html`은 CSS·JS·JSON을 내장해 외부 지도 타일 없이 열 수 있다. 로컬 HTTP로
보고 싶으면 데이터 디렉터리의 절대 경로를 지정한다.

```bash
uv run python -m http.server 8767 --bind 127.0.0.1 --directory /absolute/path/walk-storyboard
```

브라우저에서 `http://127.0.0.1:8767/`을 연다. 이 주소는 **접속한 그 컴퓨터**를 뜻한다.
이전 PC의 8767 서버로 연결하는 주소가 아니다. 포트가 사용 중이면 다른 로컬 포트를 쓴다.

### 10.3 cache로 오프라인 재생성

다음 명령은 geo root에서 실행한다. 경계와 cache/output 경로는 실제 새 PC 경로로 바꾼다.
cache를 모두 옮겼으면 인증키와 외부 API 호출이 필요 없다. 선택 패키지 최초 설치는 인터넷이
필요할 수 있으므로 ‘오프라인’은 빌더의 원천 조회 동작을 말한다.

```bash
uv run --with pyshp --with shapely --with pyproj python -m scripts.spikes.storyboard_and_regions.build --boundary-zip /absolute/path/bnd_dong_11_2025_2Q.zip --cache-dir /absolute/path/storyboard-source-cache --out /absolute/path/walk-storyboard
```

Windows PowerShell에서 별도 데이터 루트를 쓰는 예:

```powershell
$storyLabRoot = Join-Path $env:USERPROFILE 'daengs-storyboard-data'
uv run --with pyshp --with shapely --with pyproj python -m scripts.spikes.storyboard_and_regions.build --boundary-zip "$storyLabRoot/bnd_dong_11_2025_2Q.zip" --cache-dir "$storyLabRoot/storyboard-source-cache" --out "$storyLabRoot/walk-storyboard"
```

위 명령은 파일을 새로 받아주지 않는다. 먼저 ZIP과 네 cache 파일을 해당 위치에 준비한다.
Python 3.12 제약은 프로젝트 설정이 관리한다. `.venv`를 다른 OS에서 복사해 재사용하지 않는다.

### 10.4 cache가 없어서 새로 수집하기

SGIS ZIP은 별도로 준비한다. `.env.storyboard`에
`DAENGS_DATA_GO_KR_SERVICE_KEY=<사용자가 별도로 설정한 키>`를 넣거나 같은 환경변수를 쓴다.
실제 키 값을 커맨드 인자·PR·문서에 넣지 않는다. 인코딩/디코딩 키 처리는 loader가 맡는다.

```bash
uv run --with pyshp --with shapely --with pyproj python -m scripts.spikes.storyboard_and_regions.build --boundary-zip /absolute/path/bnd_dong_11_2025_2Q.zip --cache-dir /absolute/path/storyboard-source-cache --out /absolute/path/walk-storyboard --env-file .env.storyboard --fetch
```

`--fetch`는 없는 cache의 조회를 허용한다. 존재하는 cache까지 새로 받으려면 `--fetch --refresh`다.
이 옵션은 과거 snapshot을 같은 경로에서 대체하므로 이전 결과 비교가 필요하면 **다른 cache
디렉터리**를 지정한다. 키가 같아도 나중의 응답 건수와 fingerprint는 달라질 수 있다.
전용 collector는 dev 운영 Redis 예산 계수기와 통합돼 있지 않은 로컬 spike다. 지속 자동수집이나
대량 지역 조회를 붙이려면 운영 호출 정책과 사용량 관리를 별도로 확인해야 한다.

### 10.5 자료 없이 행동 프로필 설계부터 계속하기

행동 프로필 첫 projector에는 실제 SGIS/API cache가 필수는 아니다. 기존 증언 타입을 따르는
합성 Pin과 작은 명시적 장소/문맥 fixture로 정정·귀속·집계·삭제를 먼저 검증할 수 있다.
키나 ZIP이 없어도 새 기능 설계 전체를 중단할 이유는 없다. 실제 위치/원천 검증은 별도 단계다.

## 11. 테스트와 검증 상태

이전 구현 턴에서 실행하고 통과한 범위:

```bash
uv run --with shapely --with pyproj pytest tests/test_storyboard_sources.py tests/test_storyboard_regions.py -q
# 17 passed

uv run pytest tests/test_script_imports.py -k storyboard_and_regions -q
# 3 passed, 51 deselected (당시 파일 목록 기준)

uv run ruff check scripts/spikes/storyboard_and_regions tests/test_storyboard_sources.py tests/test_storyboard_regions.py
# All checks passed
```

브라우저에서는 기본/공백/Pin 없는 시나리오, 게임 토글, 직접 장면 선택, 자동 재생, 하천 출처
표시를 확인했다. 실제 기기 GPS와 사용자 이해도/재사용 의향은 측정하지 않았다.
이 문서 PR은 기능 코드 변경이 없어 해당 pytest를 재실행하지 않고 문서 링크·참조·차이를 검토한다.

후속 테스트를 실행할 때도 먼저 변경 diff, 영향 경계, 해당 디렉터리의 테스트 지침을 읽고
최소 명령을 정한다. 행동 프로필 코드가 추가되면 새 전용 테스트를 만든다. 기존 storyboard
테스트의 통과를 개인화 기능 검증으로 보고하지 않는다. 전체 suite는 이번 요청의 기본 범위가 아니다.

## 12. 알려진 제한과 재개 시 확인할 지점

- **합성 경로**: 실제 보행 가능성과 개별 행동의 정답이 아니다. 미시 행동 인식 모델도 없다.
- **장면 편집**: 60초 기준은 임시다. 모든 동 전환을 장면으로 보여주지 않으며 탈락 구간은 JSON에 남는다.
- **실제 Pin 미연결**: 현재 build의 Pin/게임 장면은 내부 fixture다. 실제 저장 API에서 읽지 않는다.
- **경계 불확실성**: 중점과 reported accuracy를 사용하는 보수적 휴리스틱이다. 완전한 확률 모델이 아니다.
- **EGIS 완전성**: 최대 300개와 count 기반 partial 표시다. 전역 물길/산책로 완전성 보장이 아니다.
- **원천 실패**: collector는 partial/실패/0건을 구별한다. 운영판의 retry/backoff/예산 공유는 미구현이다.
- **화면의 원천 공백 문구**: 일부 설명이 이번 양재천·탄천 미등재 snapshot에 맞춰져 있다.
  다른 지역/새 원천으로 일반화할 때는 문구도 실제 receipt 상태와 이름 목록을 따르게 확인해야 한다.
- **범용 scenario 입력**: 현재 CLI는 기본 waypoint/세 시나리오를 코드로 조립한다. 임의 지역/경로를
  사용자 입력으로 받아 끝까지 일반화한 서비스가 아니다.
- **재현 범위**: 같은 코드/의존성/원천 snapshot의 재생성과, 지금 API를 다시 조회하는 것은 다르다.
- **프로필 신뢰도**: 기록 수·문맥 자격·선택 편향을 구분해야 한다. 임의 confidence 점수는 아직 없다.
- **개인 메모**: 자유 메모를 자동 행동 프로필 입력에 넣을 수 있다는 예외는 만들지 않았다.
- **UI 목적**: 근거를 비교하기 위한 로컬 연구 화면이다. 완성 앱의 감상 UX나 반응형 전 범위를 검증하지 않았다.

## 13. SGIS 신청과 남은 제출

사용자는 SGIS 서울 읍면동 경계 신청에서 기존 계정 정보 제출, 출처 표시와 완성 결과 사본
제출 조건에 명시적으로 동의했다. 신청은 완료됐고 `bnd_dong_11_2025_2Q.zip`을 내려받았다.
화면에 표시됐던 다운로드 기간은 2026-09-04~2026-10-04였다. 새 PC에서는 자신의 계정에서
신청자료 다운로드 상태를 확인한다. 계정 개인정보와 브라우저 로그인 상태는 이 문서에 없다.

**활용 결과물 등록은 아직 제출하지 않았다.** PR 생성/머지는 SGIS 사본 제출을 대신하지 않는다.
원본 경계나 계정 정보를 포함하지 않는 보고서/결과 URL을 구체적으로 준비한 뒤 제출 범위를
확인할 수 있다. 이 인수인계 작업은 결과물 업로드·계정 정보 전송을 추가 수행하지 않았다.

## 14. 다음 작업의 권장 우선순위

| 순서 | 구체 산출물 | 완료 판단 |
|---|---|---|
| 1 | 문서/현재 main/기존 계약 상태 확인 | 구현/제안/미결을 구별해서 설명 가능 |
| 2 | 여러 산책의 합성 행동 증언 fixture | dog/owner/uncertain/정정/중복/삭제 사례 포함 |
| 3 | 순수 행동 프로필 projector | 현재 head, 입력 자격, distinct walk count, 근거 refs와 제외 이유 |
| 4 | 프로필 카드 ↔ 근거 Pin/장면의 로컬 화면 | 사용자가 설명의 근거를 찾고 정정 전후 차이를 볼 수 있음 |
| 5 | 13장/약 5장 스토리보드 비교 | 장면 수를 줄여도 순서·핵심 Pin·공백 의미 보존 |
| 6 | 다음 산책의 관련 기억 카드 | 새로운 성격/행동을 만들지 않고 지원되는 과거 기록 회수 |
| 이후 | 운영 adapter/Context capability/실시간 제안 | 별도 계약, 권한, 저장/삭제, 사용량, 실제 사용자 평가 후 판단 |

순서 2~4를 하나의 작은 후속 PR 후보로 볼 수 있다. 이 문서는 구현 시작에 대한 자동 지시나
새 운영 계약의 승인서가 아니다. 다음 사용자의 요청과 저장소 지침을 함께 따른다.

## 15. 새 세션에 그대로 붙일 시작 문구

아래 문구와 이번 문서 PR 링크를 함께 주면 이전 대화가 없어도 이어받을 수 있다.

> DAENGS_geo의 `docs/research/2026-09-04-walk-personalization-handoff.md`를 먼저 읽고,
> `docs/explorations/walk/behavior-profile-and-personalization.md`까지 읽어줘.
> 적용되는 CLAUDE.md와 현재 branch/main 상태도 확인해.
> 실제 SGIS·상가·공원·하천을 합성 산책에 붙인 스토리보드는 PR #227로 구현됐고,
> 행동 Pin 기반 프로필/다음 산책 개인화는 아직 설계 단계야.
> 다음에는 강아지에 귀속된 구조화 증언의 현재 correction head를 읽는 합성 fixture와
> 순수 프로필 projector부터 검토하고 싶어. Pin 수와 산책 수, owner claim, uncertain,
> 정정·삭제·문맥 부족을 구분하고 프로필에서 근거 장면으로 돌아가는 흐름을 보자.
> 자유 메모를 자동 성격 데이터로 쓰거나 기존 DogProfile/Context registry/운영 DB를
> 먼저 확장하지 말고, 문서의 제안과 채택된 계약을 구별해서 이어가줘.
> 로컬 데이터가 없으면 합성 fixture로 먼저 진행할 수 있어. 기존 localhost와 API cache가
> 새 컴퓨터에 자동으로 넘어왔다고 가정하지 마.

## 16. 읽을 순서

1. 이 문서: 세션 전체 지도와 환경 복구.
2. [행동 프로필 상세 설계](../explorations/walk/behavior-profile-and-personalization.md): 새 기능의 후보 구조.
3. [스토리보드와 동네](../explorations/walk/storyboard-and-regions.md): 장면/지역/게임 구별.
4. [실제 실험 기록](2026-09-04-storyboard-regions-spike.md)와 [실행 README](../../scripts/spikes/storyboard_and_regions/README.md).
5. [Capsule](../contracts/walk-capsule.md), [Pin 정정](../contracts/pin-attestation-correction.md),
   [Memory Place](../contracts/memory-place-biography.md): 기존 증거와 수명.
6. [Context Plane](../contracts/context-plane.md), [DogProfile](../contracts/dog-profile.md): 재사용과 소유권.
7. [행동 책갈피](../explorations/walk/behavior-anchor.md), [미시 판정](../explorations/walk/micro-judgment.md).
8. [#85 경로 보관 경계](../decisions/2026-09-03-walk-diary-route-privacy.md),
   [시즌 점령전](../explorations/walk/territory-season-scoring.md): 옆 기능과 섞지 않을 경계.
