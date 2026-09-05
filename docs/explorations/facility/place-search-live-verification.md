# 프로필 시설 검색 연결 검증 — 2026-09-05

## 결론

개발 서버 배포와 실제 Kotlin PlaceApi → 공개 서버 → 응답 파싱/평가 문구 변환을 확인했다.
계정 토큰 없이 합성 반려견 값으로 수행했으며, 실제 계정 프로필·실기기 검증은 완료하지 않았다.
출시 도메인은 아직 dogs를 echo하지 않아 신규 다견 검색 지원을 확인할 수 없다.

## 코드와 배포

- 앱 [#147](https://github.com/SAJOYO/DAENGS_APP/pull/147): 병합 완료,
  merge `7e0899a1af17122b9fa85757976aab9fdd2f8e23`. 실행한 앱 코드 `0d08ef6`.
- 서버 [#253](https://github.com/SAJOYO/DAENGS_dev/pull/253): 병합 완료,
  merge `d279cdcbae2fe7a53f2d1a19aeef1e6bb975498e`. 해당 커밋 deploy 워크플로 성공 확인.
- 수정 후 [PostGIS CI](https://github.com/SAJOYO/DAENGS_dev/actions/runs/33963413066)와
  [backend CI](https://github.com/SAJOYO/DAENGS_dev/actions/runs/33963413050) 성공.
- 공개 응답 관측 시각: 2026-09-05 11:52 UTC 무렵. 배포 성공 표시만으로 계약 지원을 추정하지 않고 직접 조회했다.

## 실제 Kotlin 클라이언트 조회

[선택 실행용 검증 코드](../../../scripts/verify/PlaceProfileLiveProbe.kt)를 앱 테스트 폴더에 임시로
복사하고 기존 Gradle 환경에서 실행했다. PlaceApi·requireDogEcho·searchPlaceBatches·overviewHits·
dogEvaluationLabel을 실제 앱 코드 그대로 호출한다. 테스트 종료 후 앱의 임시 소스는 제거했다.
앱/서버의 기능 코드는 이번 검증에서 변경하지 않았다.

실행: `gradlew.bat :app:testDebugUnitTest --tests '*PlaceProfileLiveProbe*' --no-daemon`.
결과: 1개 네트워크 통합 시나리오 통과, 내부 실제 검색 요청 10개. 최초 검증 코드의 생성자 인자
지정 오류를 수정한 뒤 컴파일과 실행이 통과했다. 자동 CI에 외부 서버 의존 테스트를 추가하지 않았다.

기본 중심 성수 37.5446,127.0559, 카페, 3km, 업종별 limit 20이다. 이는 앱 일반 요청의 limit 50보다
작은 검증용 상한이다. profile-a는 9kg/2세, profile-b는 신체 정보 미상이며 모두 가상 식별자다.

| 시나리오 | 결과 |
|---|---|
| 선택 없음 | 카페 14곳, 다견 평가 없음 |
| 한 마리 | 14곳, 동일 스냅샷 echo·각 hit 평가 확인 |
| 두 마리 | 14곳, 개별 ref 순서 확인·선택 전과 시설 ID 목록 동일 |
| 9kg/v1 → 11kg/v2 값 변경 | 새 값/버전 echo와 평가 수신. 실제 계정 수정은 아님 |
| 중심 이동 + 5km | 20곳, truncated=true |
| 시설명 구욱희씨 | 1곳, 두 마리 각각 ‘크기 조건 충족 · 추가 조건 확인 필요’로 변환 |
| 선택 해제 | 14곳, 다견 평가 없음 |
| 전체보기 18종/3묶음/5km/주차 우선 | 모두 성공, 그룹 순서·동일 스냅샷·중복 제거 확인. 통합 67곳, 일부 업종 truncated |

체중 값을 바꾸었다고 평가 결과가 반드시 바뀌어야 하는 것은 아니다. 크기 제한 없음인 곳은
동일하게 크기 축을 충족한다. 명시 kg 경계에서 결과가 달라지는 동작은 기존 순수/HTTP 테스트에서
확인했으며, 이번 실제 지역 표본으로 체중 제한 데이터의 전국 커버리지를 입증하지 않는다.

## 개발/출시 도메인 비교

| 경로 | 개발 daengback | 출시 daengapi |
|---|---|---|
| POST /v2/places/search + dogs | 200, dogs echo 있음 | 200, dogs echo 없음 |
| GET /app/pets, 인증 없음 | 401 | 401 |

개발 도메인은 `http://daengback.weareithero.cloud`, 출시 도메인은
`https://daengapi.weareithero.cloud`다. Kotlin 클라이언트는 dogs echo가 없는 성공 응답을
정상 평가로 처리하지 않도록 이미 검증한다. 출시 도메인의 내부 배포 커밋은 확인하지 않았다.
401은 익명 접근 차단 확인이며 실제 계정 소유권이나 목록 내용의 정상 조회 확인이 아니다.

## 남은 확인과 실행 방법

- 실제 로그인 세션에서 목록 읽기 → 복수 선택 → 프로필 편집/삭제 → 재조회까지 확인 필요.
- 로그아웃·계정 변경·늦은 응답·상태 전환·Compose 선택 동작은 이전 로컬 테스트로 검증했다.
  이번 공개 서버 검증에서는 계정 데이터를 만들거나 수정하지 않았다.
- 폰에서 카드 가독성/터치/스크롤, GPS·지도·전화·길찾기·키보드·큰 글자 확인 필요.
- release 기본 화면 전환 전 출시 도메인의 계약 지원을 다시 확인해야 한다.

재현 시 위 Kotlin 파일을 형제 DAENGS_app의
`app/src/test/java/com/daengs/app/place/PlaceProfileLiveProbe.kt`에 복사한다. 기존 파일이 있으면
덮어쓰지 않는다. `DAENGS_PROFILE_PROBE_OUTPUT` 환경 변수에 결과 JSON의 절대 경로를 설정하고
JDK/SDK 환경을 지정한 뒤 위 Gradle 명령을 실행한다. 생성 결과는 공개 조회 개수·합성 값·라벨만 담는다.
검증 완료 후 복사한 파일만 제거한다. 서버의 시설 데이터 변화로 개수나 이름 표본은 달라질 수 있다.
