# 2단계 일반 검색·직접 필터 연결 조사

조사일: 2026-09-05. 코드 조사와 공개 검색 API 조회 8회를 수행했다.
앱·서버 기능 구현, 운영 배포, DB 변경은 하지 않았다.

## 결론

일반 장소명 검색·주차 우선·지도 재검색은 기존 앱/서버 구조를 재사용할 수 있다.
주소·지역명 검색은 별도 기능이며 현재 지원되지 않는다. 전체보기와 반경 선택은 앱의
상태/요청 경계를 확장해야 한다. 특히 출시 서버는 현재 이름 조건을 무시하고 있으므로
개발 서버 연결 성공을 출시 동작 검증으로 간주하면 안 된다.

## 확인 기준

- 서버: [DAENGS_dev@ac106fa](https://github.com/SAJOYO/DAENGS_dev/tree/ac106fad63c96273f9a6bd860ac801ee62b0648a).
- 앱: [DAENGS_APP@51197f3](https://github.com/SAJOYO/DAENGS_APP/tree/51197f370ee4d81805df4913740cbbda984949de).
- 앱 작업 브랜치의 개발 UI는 PR #143. 이번 조사에서는 운영 PlacesViewModel/Coordinator를 기준으로 분석했다.
- 공개 조회는 성수 중심 37.5446,127.0559, 반경 3km, 카페, 종류별 limit 20을 사용했다.
- 공개 서버의 내부 배포 커밋은 확인하지 않았다. 아래 결과는 조회 시점 관측이다.

## 기능별 지원 범위

| 기능 | 서버 | 기존 운영 앱 | 연결 판단 |
|---|---|---|---|
| 장소명 | name_query 부분 일치, 최대 120 Unicode code points | 입력/제출/응답 echo 확인 이미 구현 | 기존 경로 재사용. 출시 반영 확인 필요 |
| 주소 검색 | 이름만 검사하므로 미지원 | 주소 전용 검색 경로 확인되지 않음 | 웹 placeholder의 '주소'를 그대로 약속할 수 없음 |
| 지역명→좌표 | Place 요청은 좌표·반경만 받음, 지오코더 없음 | 지도 중심을 좌표로 전달 | 지역 후보/좌표 해석을 별도 설계 |
| 단일 업종 | 18개 canonical kind | 단일 kind 중심 Action과 UI | 재사용 가능 |
| 전체보기 | 요청당 최대 6종류, all 값 없음 | 기존 '전체 보기'는 업종 선택 메뉴이며 전체 결과가 아님 | categoryScope와 복수 요청 집계 필요 |
| 반경 | 100~20,000m, 기본 3,000m | Request는 지원하나 Controller에서 기본 3km 사용 | Action→Intent→Controller에 반경 상태 전달 추가 |
| 주차 우선 | 500m 거리 구간 내 주차 가능 우선, 결과 제외 안 함 | 기존 요청/표시/병원·약국 예외 처리 | 재사용 가능 |
| 주차 필수·실내 필수 | 공개 요청에 해당 필터 없음 | 미지원 | 지원되지 않은 칩을 적용된 필터처럼 표시하지 않음 |
| 반려견 조건 | 단일 개의 크기·체중·나이 값 평가 | primaryPet을 단일 DogSearchContext로 투영 | 다견은 3단계. 평가 통과만으로 후보를 거르는 기능 아님 |
| 지도 재검색 | 주어진 좌표 기준 검색 | SearchAt·고정 중심·내 위치 복귀·이름 조건 유지 구현 | 재사용 가능 |
| 개수·다음 페이지 | 그룹별 results/limit/truncated, total/cursor 없음 | 종류별 50개 요청 | '반환된 장소 수'이며 전체 DB 일치 수 아님 |
| 전화·길찾기 | Journey는 검색과 별도 | ACTION_DIAL·Journey·Naver handoff 구현 | 검토판의 안내 버튼을 기존 흐름에 연결 |

## 공개 서버 확인 결과

| 요청 | 출시 HTTPS daengapi | 개발 HTTP daengback |
|---|---|---|
| 이름 없음 | 200, 카페 14곳 | 200, 카페 14곳 |
| name_query=구욱희씨 | 200, 카페 14곳, echo 없음 | 200, 구욱희씨 1곳, echo 일치 |
| 존재하지 않는 이름 | 200, 카페 14곳, echo 없음 | 200, 0곳, echo 일치 |
| 업종 7개 | 422, 최대 6개 | 422, 최대 6개 |

출시 서버는 이번 표본에서 이름 조건을 적용하지 않았다. HTTP 200만으로 성공 판정하면
잘못된 결과를 보여준다. 앱 PlaceApi는 비어 있지 않은 nameQuery의 echo가 다르면
SerializationException을 발생시키므로 이 보호 장치를 유지해야 한다.
개발 서버로 기능 연결을 검증할 수 있지만, 출시 활성화 전에는 이름 검색 계약의 배포와
동일 조회 재검증이 필요하다. 이번 조사에서 배포를 수행하지 않았다.

원본 요청/응답 기록은 로컬 facility-audit/stage2-api-probes.json에 저장했다.

## 검색 의미와 데이터 한계

서버 name_query는 최종 canonical 표기 이름에 대해 대소문자를 낮춘 부분 일치다.
주소·설명·보강 원천의 별도 이름은 포함하지 않는다. 입력은 바인딩되며 %, _ 등도
문자 그대로 취급한다. 공간·업종·이름 조건을 LIMIT 전에 적용한다.

웹 검토판은 이미 받아 둔 표본에서 장소명과 주소를 검색한다. 따라서 웹 검색과 실제
API는 의미가 다르다. 2단계의 첫 연결은 '장소명 검색'으로 표시하고, 지역명 검색은
후속 하위 작업에서 좌표 후보 선택과 결합하는 것을 제안한다.

조건의 역할도 구분해야 한다. 주차는 선호 정렬이고, dog_access/restrictions는
시설별 평가다. 현행 시설 검색은 only_dog_ok=False로 후보를 구하며 동반 조건
불일치 장소도 평가와 함께 반환할 수 있다. '내 개가 갈 수 있는 곳만'은 아직 별도 계약이다.

## 전체보기 구현 제안

18종류를 단일 요청으로 보내면 422다. 기존 상한을 무작정 높이지 않고,
앱 저장소 어댑터에서 최대 6종류씩 3개 요청으로 나누는 방법을 먼저 검토한다.
현재 앱 limit 50을 유지하면 이론상 그룹별 합계 상한은 900개다. 이 수치는 UX/성능
검토용 초기 제안이며 전체 장소 수를 보장하지 않는다.

- 3개 요청의 중심·반경·검색어·반려견 조건·세대 ID를 동일하게 고정한다.
- 사용자에게 보이는 검색은 하나의 상태로 관리하고 취소·늦은 응답을 일괄 처리한다.
- 실패한 묶음이 있으면 전부 성공한 전체보기로 표시하지 않는다. 부분 결과 정책을 정한다.
- canonical key로 중복을 접되 업종 분류와 원천·평가는 잃지 않는다.
- 서버는 그룹별 순서만 보장하고 전역 순위를 만들지 않는다. 교차 업종 거리순/주차
  정렬은 별도 화면 정책으로 명시하며 병원·약국의 주차 미제공과 충돌하지 않게 한다.
- 어떤 그룹이라도 truncated면 '더 있음'을 표시한다. 정확한 total·페이지 탐색이
  필요해지면 서버 계약 확장이 필요하다.

장기적으로 서버의 범주 전체 집계 endpoint를 둘 수도 있으나, 첫 연결 전에 필수라고
단정하지 않는다. 앱 어댑터 방식의 호출량·실패 처리·응답 크기를 측정하고 결정한다.

## 추천 작업 순서

1. **운영 상태 흐름에 새 UI 연결:** PlaceSearchLabViewModel을 또 다른 운영 검색 엔진으로
   키우기보다 PlacesViewModel → PlaceSessionCoordinator → PlaceDiscoveryController →
   PlaceRepository/PlaceApi를 재사용한다. 입력과 적용 상태 및 카드 펼침만 새 UI에서 연결한다.
2. **개발 서버 단일 업종 검증:** 이름 검색, 이름 해제, 주차 정렬, 지도 재검색, 오류·재시도.
   출시 서버의 미적용 이름 조건은 계속 감지한다.
3. **반경·전체보기 확장:** 반경 상태 전파와 3묶음 결과 집계, 부분 실패·중복·잘림 표시.
4. **출시 계약 확인:** 배포 담당 흐름에서 이름 검색 반영 후 같은 표본을 재검증한다.
5. **지역 검색 분리 설계:** 장소명 검색과 지역 후보 선택의 구분, 지오코딩 공급자·비용·실패
   처리·좌표 선택을 정한다. 현재 단계에서 AI나 프로필 조회를 끼워 넣지 않는다.

## 근거 코드

- 서버 [search.py](https://github.com/SAJOYO/DAENGS_dev/blob/ac106fad63c96273f9a6bd860ac801ee62b0648a/backend/src/daengs_place/place/search.py): 요청 한도, 반환 그룹, 평가와 정렬.
- 서버 [장소명 계약](https://github.com/SAJOYO/DAENGS_dev/blob/ac106fad63c96273f9a6bd860ac801ee62b0648a/docs/place/name-search.md): 검색 범위, echo, 검증 한계.
- 앱 [PlaceApi.kt](https://github.com/SAJOYO/DAENGS_APP/blob/51197f370ee4d81805df4913740cbbda984949de/app/src/main/java/com/daengs/app/place/PlaceApi.kt): 이름 echo 검사.
- 앱 [PlaceSearchRequest.kt](https://github.com/SAJOYO/DAENGS_APP/blob/51197f370ee4d81805df4913740cbbda984949de/app/src/main/java/com/daengs/app/place/PlaceSearchRequest.kt): 반경·업종·조건 한도.
- 앱 [PlaceDiscoveryController.kt](https://github.com/SAJOYO/DAENGS_APP/blob/51197f370ee4d81805df4913740cbbda984949de/app/src/main/java/com/daengs/app/map/features/places/PlaceDiscoveryController.kt): 50개 상한, 요청 세대·재시도.
- 앱 [PlaceSessionCoordinator.kt](https://github.com/SAJOYO/DAENGS_APP/blob/51197f370ee4d81805df4913740cbbda984949de/app/src/main/java/com/daengs/app/ui/places/PlaceSessionCoordinator.kt): 위치 의도·이름 조건 보존.
