# 실제 프로필·다견 시설 검색 조사

조사일: 2026-09-05. 앱·서버 코드, 저장된 공개 응답, 순수 평가 함수 7개 입력을 확인했다.
이번 작업은 조사이며 프로필 API·검색 기능·운영 DB·배포를 변경하지 않았다.

## 결론

실제 반려견 목록과 인증은 재사용 가능하다. 다만 복수 선택 UI만 연결해서는 다견 검색이
완성되지 않는다. 현재 Place는 한 마리의 값만 평가하며 프로필 ID·소유권·수정 버전을 모른다.
프로필에는 체중과 생일이 있지만 크기 등급은 없다. 마릿수 제한은 일부 원문에서 구조화되어
있으나 객실별 제한 등의 적용 범위를 더 보존해야 자동 평가할 수 있다.

권장 순서는 **프로필 공급/선택 상태 → 인증된 프로필 해석과 다견 응답 계약 → 서버 평가 →
카드 연결**이다. 크기/체중 평가와 추가 조건, 함께 데려갈 마릿수 평가는 별도로 보여준다.
필터의 첫 버전은 확인된 불일치만 선택적으로 숨기고 미상은 남기는 방향을 제안한다.
이 정책과 아래 API 이름은 구현 제안이며 확정·구현된 계약이 아니다.

## 확인 기준과 재현

- 앱 최신 dev: [4a27950](https://github.com/SAJOYO/DAENGS_APP/tree/4a27950400522f3185b5fb4074e4d4af936ab30e).
  반경·전체보기 PR #146이 병합된 상태. 로컬 f5cd8af와 dev의 파일 차이가 없음을 확인했다.
- 서버 최신 dev: [291dad8](https://github.com/SAJOYO/DAENGS_dev/tree/291dad847390b5e0350f98e9d949d4199c3ea164).
- [간이 검증 스크립트](../../../scripts/verify/place_profile_audit.py): Geo에서
  `uv run scripts/verify/place_profile_audit.py`. 형제 폴더 DAENGS_dev와 DAENGS_app을 사용한다.
  Python 3.12와 Pydantic만 필요하며 DB·API·계정에 접근하지 않는다.
- 이번에는 인증된 실제 계정 조회나 공개 서버의 최신 프로필 스키마를 실측하지 않았다.
  소유권/갱신 동작은 코드 확인이고 DB 트리거 실행·실기기 검증과 구분한다.

## 재사용 가능한 구조와 빠진 계약

| 영역 | 확인한 구현 | 추가로 필요한 것 |
|---|---|---|
| 프로필 목록 | GET /app/pets, 등록순 pets와 max_pets. 서버 등록 상한은 현재 5 | 시설 검색용 선택 상태. 등록 상한을 앱에 고정하지 않기 |
| 인증·소유권 | Bearer 앱 토큰, CurrentAppUser, 목록 owner 조건, get_owned/owned_ids | 다견 검색에서도 모든 선택 ID를 현재 계정 소유로 확인 |
| 표시 정보 | id/name/breed, 별도 사진 공급자 | 같은 이름도 ID로 식별. 사진이 없으면 기존 아바타 사용 |
| 평가 정보 | nullable weight_kg, birth_date와 birthday/family_day 구분 | 크기 등급 없음. 품종·체중으로 임의 등급 생성하지 않기 |
| 버전 | DB pets.updated_at 및 UPDATE 트리거 존재 | PetResponse와 앱 Pet에 수정 버전이 노출되지 않음 |
| 배웅한 반려견 | farewell_on이 있어도 목록에 유지 | 동행 선택에서는 제외하고 기록/프로필은 유지하는 정책 제안 |
| 앱 상태 | PetHolder의 pets(null/빈 목록), busy/error, 수정 후 재조회 | 실패·로그아웃·계정 변경·늦은 응답을 구분하는 공급자 경계 |
| 현재 시설 경로 | MainActivity → PlacesRoute(primaryPet) → toPlaceDogContext | 대표견 자동 주입을 명시적 선택 목록으로 교체 |
| Place API | 단일 conditions: dog_size/weight/age, 단일 evaluations | 반려견별 평가 배열, 프로필 버전/평가 시각, 집계 근거 |

근거: 앱 [Pet/PetApi/PetHolder](https://github.com/SAJOYO/DAENGS_APP/tree/4a27950400522f3185b5fb4074e4d4af936ab30e/app/src/main/java/com/daengs/app/pet),
[PlacesScreen](https://github.com/SAJOYO/DAENGS_APP/blob/4a27950400522f3185b5fb4074e4d4af936ab30e/app/src/main/java/com/daengs/app/ui/places/PlacesScreen.kt),
서버 [프로필 응답](https://github.com/SAJOYO/DAENGS_dev/blob/291dad847390b5e0350f98e9d949d4199c3ea164/backend/src/daengs_backend/schemas/pet.py),
[소유권 조회](https://github.com/SAJOYO/DAENGS_dev/blob/291dad847390b5e0350f98e9d949d4199c3ea164/backend/src/daengs_backend/repositories/pet.py),
[DB 정의](https://github.com/SAJOYO/DAENGS_dev/blob/291dad847390b5e0350f98e9d949d4199c3ea164/db/init/05_pets.sql).

## 실제 평가 범위와 데이터 한계

서버에는 서로 다른 두 평가 축이 있다. dog_access는 원천의 강아지 허용·크기·최대 kg를
비교하고 restrictions는 원문에서 파생한 제한 술어를 비교한다. 한쪽 통과를 전체 입장 가능으로
표시하면 안 된다. 현재 검색은 `only_dog_ok=False`로 후보를 유지하며 조건은 평가에만 쓴다.
병원·약국은 이 동반 평가를 생성하지 않는다. 다른 원천에서 미검증 연결로 가져온 restrictions는
`unverified_source_match` 미상으로 유지한다.

| 정보 | 현재 활용 가능한 범위 | 한계 |
|---|---|---|
| 체중 | 명시 max_kg와 비교 | 미만/이하 구분 손실로 정확히 경계 kg면 미상 |
| 크기 | small/medium/large 조건 및 크기별 칩 | 실제 Pet에 size가 없고 체중→크기 자동 변환 없음 |
| 나이 | 숫자가 명시된 firm 연령 제한 | family_day를 나이로 쓰지 않음. 노령견처럼 문턱 없는 말은 미상 |
| 준비물·행동·건강·견종 | 원문과 조건 칩 노출 | 충족 여부를 요청에서 받지 않거나 구체 대상 부족으로 미상 |
| 마릿수 | limit:max_dogs의 max, 복합 limit:max_dogs_by_size | 현재 평가기는 마릿수를 받지 않아 unresolved_condition |
| 객실·구역 | 원문에 표시 가능 | 객실당/시설 전체/크기 조합을 구분하는 평가 계약 부족 |

특히 판독표의 “객실당 최대 2마리”와 “최대 2마리”는 같은 `limit:max_dogs(max=2)`로
투영된다. 방을 여러 개 예약할 수 있는 사용자를 선택 마릿수만으로 불가 처리하면 안 된다.
마릿수 자동 판정 전 scope와 숫자 비교 연산자, 복합 규칙/판독 불완전 상태를 보존해야 한다.
표시용 원문은 계속 필요하다.

저장된 강남·성수·해운대·제주 baseline 카페/음식점 표본을 원천+ID로 중복 제거하면 45곳이다.
45곳 모두 size_class가 있고 max_kg는 0곳, 추가 조건 none_confirmed 40곳/restricted 5곳,
마릿수 칩은 0곳이었다. **이 표본은 전국·전체 업종 커버리지가 아니다.** 숙박을 포함하는
판독표에는 마릿수 제한이 있지만 현재 운영 데이터 중 얼마나 적용되는지는 별도 표본 조사가 필요하다.
현재 앱이 체중만 보내도 이 표본의 크기 축을 충분히 평가할 수 없다는 점은 확인된다.

근거: [검색 hit 평가](https://github.com/SAJOYO/DAENGS_dev/blob/291dad847390b5e0350f98e9d949d4199c3ea164/backend/src/daengs_place/place/search.py),
[원천 축 평가](https://github.com/SAJOYO/DAENGS_dev/blob/291dad847390b5e0350f98e9d949d4199c3ea164/backend/src/daengs_place/place/evaluations.py),
[제한 평가](https://github.com/SAJOYO/DAENGS_dev/blob/291dad847390b5e0350f98e9d949d4199c3ea164/backend/src/daengs_place/place/restriction_projection.py),
[원문 판독표](https://github.com/SAJOYO/DAENGS_dev/blob/291dad847390b5e0350f98e9d949d4199c3ea164/backend/src/daengs_place/place/restriction_map.py).

## 간이 실행에서 확인한 보완점

- max_kg=10에 9/10/11kg를 넣으면 compatible/unknown/incompatible이 나온다.
- size_class=any여도 dog_size가 없으면 missing_dog_size다. ‘크기 제한 없음’에 대한
  평가 순서 개선을 검토할 수 있지만 체중 제한·강아지 불가를 먼저 확인하는 동작은 유지해야 한다.
- max_dogs=2 술어는 현재 선택 마릿수 입력이 없으므로 unresolved_condition이다.
- 합성 입력에서 크기 미상인 deny:size 다음에 확정 deny:species_dog를 놓으면 unknown,
  순서를 바꾸면 incompatible이다. 첫 미상에서 조기 반환하는 동작이다. 실제 원천의 발생 빈도는
  확인하지 않았다. 다견 집계 이전에 **확정 불일치가 뒤에 있어도 수집하도록** 보완할 필요가 있다.

스크립트 실행은 정상 종료했으며 위 7개 입력의 결과를 확인했다. 다견 기능 테스트 통과나
운영 데이터 전체 검증을 의미하지 않는다.

## 권장 연결 구조

Place는 별도 서비스/DB이며 현재 프로필을 소유하지 않는다. Place DB에 프로필을 복제하기보다
인증된 backend가 선택 ID를 해석하고 Place에 값 스냅샷을 전달하는 경계를 제안한다.

1. 앱의 검색용 프로필 공급자가 PetHolder/SessionProvider를 연결한다. 첫 선택은 비움.
   대표견을 자동 선택하지 않고 계정 단위 화면 세션 안에서 ID를 유지한다. 산책 화면의
   ‘모든 개 기본 선택’ 정책은 재사용하지 않는다.
2. 신규 인증 경로(가칭 `/app/place-search`)가 선택 ID의 소유권·삭제·farewell 상태를 확인한다.
   누락 ID를 조용히 제외해 나머지만 검색하지 않고 갱신 가능한 명시적 오류를 반환한다.
3. 같은 요청에서 해석한 프로필 목록을 고정해 전체보기 3묶음에 동일하게 쓴다. 기존처럼
   3묶음마다 별도 해석하면 수정 중 서로 다른 버전으로 평가할 수 있으므로 서버 조율 또는
   버전 확인 계약이 필요하다. 검색 DB 조회는 마릿수마다 반복하지 않는다.
4. Place의 새 명시적 계약이 값 기반 dogs 배열과 요청 내 참조를 받는다. 계정 토큰과 프로필 DB
   접근은 backend에 둔다. 기존 단일 conditions는 호환 유지하고 두 형태 동시 입력은 거부한다.
   현재 최상위 요청은 추가 키 거부가 명시되어 있지 않으므로 미지원 dogs를 조용히 무시하는
   배포 조합을 막을 버전/응답 echo 검증이 필요하다.
5. 응답에는 profile ID/revision, evaluated_at/나이 계산 기준일, 개별 dog_access/restrictions,
   별도 party 평가와 근거를 둔다. 모든 값이 없는 프로필도 평가 대상에서 사라지지 않고 미상으로 남긴다.

revision은 우선 기존 updated_at을 응답에 노출하는 방법을 검토할 수 있다. 사진 변경에도 바뀌는
보수적인 버전이지만 새 컬럼 없이 시작 가능하다. 정확한 동시성 보장은 직렬화 정밀도·DB 트리거·
갱신 직후 조회를 통합 검증해야 한다. 원격 수정은 조회 전까지 알 수 없으므로 ‘항상 최신’이라 하지 않는다.
크기 등급 수집은 사용자 입력 의미부터 정하고, 미입력 상태를 허용한 뒤 별도 스키마 변경으로 다룬다.

앱 SessionProvider는 refresh 직렬화와 세션 generation 방어를 이미 갖춘다. 반면 PetHolder에는
refresh 응답에 대한 계정 generation 확인이 없고 PetApi의 runCatching은 취소도 잡을 수 있다.
검색 공급자에서 오래된 계정/요청 결과를 버리고 취소를 전파하는 테스트가 필요하다.
목록 재조회 실패를 빈 목록으로 바꾸거나 이전 평가를 최신으로 계속 표시하지 않는다.

## 카드·필터 제안

- 접힌 카드의 발자국 표시는 계속 **원천의 동반 등록 상태**다. 선택한 개들의 평가와 혼합하지 않는다.
- 펼친 카드는 ‘보리: 체중 조건 충족’, ‘초코: 크기 정보 필요’처럼 개별 이유와 원문·출처를 함께 표시한다.
- ‘두 마리 함께: 객실당 제한 확인 필요’는 별도 줄이다. 개별 통과만으로 ‘모두 입장 가능’을 만들지 않는다.
- 집계는 축별로 확정 불일치 우선, 없으면 미상, 모두 해결된 경우에만 평가 범위 내 충족이다.
  출처 간 충돌·불완전 판독·미검증 연결은 이유로 보존한다.
- 미상은 기본 포함을 제안한다. ‘확인된 조건 불일치 제외’는 별도 명시 필터이며 현재 구현되지 않았다.
- 프로필 값은 직접 조건·AI가 덮어쓰지 않는다. 별도 직접 조건의 출처와 충돌을 표시한다.

## 구현 단위와 검증 범위

| 단위 | 작업 | 필요한 검증 |
|---|---|---|
| A. 실제 선택 | 공급자/상태, 실제 이름 복수 선택, 대표견 암묵 주입 제거 | 동일 이름, 0/1/여러 마리, 로딩/실패, 삭제/배웅, 계정 변경, 늦은 응답 |
| B. 계약·평가 | 수정 버전, 인증된 해석 경계, 다견 값/응답, 평가 순서 보완 | 타인 ID, 삭제/수정 경합, 미상 프로필, 조건 순열, 3묶음 동일 스냅샷, 이전 클라이언트 호환 |
| C. 카드·필터 | 개별/집계 이유, 원문, 명시적 불일치 제외 | 하나라도 불일치, 전부 미상, 크기/체중 경계, 적용 조건과 결과 수·지도 일치 |
| D. 마릿수 확장 | scope/복합 제한 보존 후 party 평가 | 객실당/시설당, 2마리 이하 경계, 크기 혼합, 여러 객실 정보 없음, partial/soft |

A 단계에서는 복수 선택이 저장된다는 사실과 평가 적용 여부를 구분하고, B·C 이전에는 다견
필터가 작동한다고 표시하지 않는다. 인증 HTTP 테스트는 가짜 프로필 저장소로, 평가·앱 상태는
순수/fixture 테스트로 진행 가능하다. DB revision/소유권 SQL의 실제 실행은 접근 가능한 테스트 DB가
필요한 시점에 별도로 검증한다. **이번 조사나 선택 UI 착수에는 Docker·재부팅·DB 다운로드가 필요 없다.**

관련 문서: [기존 선택 계약 초안](place-search-profile-contract.md), [전체 계획](place-search-implementation-plan.md).
