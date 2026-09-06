# 시설 AI 웹 검토 도구

시설 검색 UI·표본·브라우저 검증은 **geo의 검토 자산**이다.
운영 API·계정 인증·검색 상태 저장·서비스 테스트는
[DAENGS_dev#274](https://github.com/SAJOYO/DAENGS_dev/pull/274)의 구현을 사용한다.
dev가 이 도구를 import하거나 배포하지 않는다.

Android 시설 화면의 로봇 전환·아이콘 카테고리·필터·지도·카드를 웹에서 확인한다.
Compose/네이버 SDK 실행은 아니며 지도는 Leaflet/OpenStreetMap이다.
함께 갈 반려견은 기존 프로필 목록에서 선택한다. 체중·나이를 별도로 입력하지 않는다.

## 실행

명령의 기준 디렉터리는 **DAENGS_geo 루트**다.

```powershell
npm --prefix tools/facility-review ci
uv sync --frozen
uv run python tools/facility-review/serve.py
```

접속은 http://127.0.0.1:8766/ . loopback에만 바인딩한다.
이 실행은 geo 의존성만 사용하며 실제 서버 모드에 dev 체크아웃은 필요 없다.

### 실제 서버 모드

`connection.example.json`을 같은 폴더의 `connection.local.json`으로 복사하고
API 주소와 유효한 앱 계정 access token을 넣는다. 로컬 파일은 git에서 제외된다.
토큰은 서버에만 있고 브라우저 자산·설정 API·요청 trace에는 노출하지 않는다.

기존 `GET /app/pets`로 같은 계정의 프로필을 받아 선택된 아이의 값을 검색 요청에 동봉한다.
`POST /app/places/discovery`, `/app/places/discovery/actions`, `/v2/places/search`를 HTTP로 호출한다.
검색 API의 Backend와 Place 코드가 함께 배포돼 있어야 한다. 서버 오류를 표본으로 대체하지 않는다.
최초 AI 검색은 실제 모델을 호출하고, 후속 선택은 저장된 해석을 이어서 사용한다.

### 저장 표본 통합 검증 모드

이 모드는 **geo가 dev 운영 코드를 검증하는 선택적 통합 도구**다.
dev 서비스 코드를 geo에 복제하지 않고, dev 실행 환경의 패키지를 가져와
모델·DB·Redis만 고정 해석·저장 응답·메모리 저장소로 대체한다.
실제 서버 모드에서 이 의존성을 불러오지 않는다.

두 저장소를 형제 디렉터리에 둔 경우 geo 루트에서 실행한다.
다른 배치라면 `--project`에 실제 dev backend 경로를 지정한다.

```powershell
uv sync --project ../DAENGS_dev/backend --extra place --frozen
uv run --project ../DAENGS_dev/backend python tools/facility-review/serve.py
```

왼쪽에서 ‘저장 표본으로 계약 검증’을 선택한다. dev 패키지가 없는 기본 실행에서
표본 모드를 요청하면 필요한 실행 방법을 안내하며 실제 서버로 대신 요청하지 않는다.

- `싼 카페 → 가까운 곳 → 이 방향으로 검색`으로 보완·확정을 확인한다.
- `fixtures.py`는 dev의 기존 intent/planning, 개별 반려견 평가와 후속 선택 서비스를 실행한다.
  자유 문장 해석은 하지 않으며 고정 예시 외 문장은 오류로 안내한다.
- `places.fixture.json`은 geo `c5d2b7f`의 강남 카페·음식점 공개 응답이다.
  전체 지역·업종·최신 영업 상태를 의미하지 않으며 반경을 넓혀도 표본은 늘지 않는다.
- `profiles.fixture.json`은 PetListResponse 형식의 가상 프로필이다. 대표 반려견을 자동 선택하지 않는다.
  생일만 나이로 계산하고 가족이 된 날·미상 값·크기는 추정하지 않는다.
- 메모리 상태는 TTL 15분·최대 256개이며 HttpOnly 쿠키로 브라우저별로 분리한다.
  이 대체 저장소는 geo에만 있다. dev 운영 경로는 Redis를 사용한다.

## 검증

geo 루트에서:

```powershell
npm --prefix tools/facility-review test
# 위 표본 서버(8766)가 실행 중이어야 한다.
npm --prefix tools/facility-review run test:browser
uv run pytest -q tools/facility-review/test_serve.py
```

브라우저 테스트는 Windows의 기본 설치 Chrome을 사용한다. 캡처는 무시되는
`screenshots/`에 저장한다. `node_modules/`·접속 파일·가상 환경도 커밋하지 않는다.

2026-09-06 geo 이동 후 검증: JS 상태 8 passed, 웹 호스트 3 passed.
Chrome에서 일반/AI 검색·기존 프로필·반경 유지·보완→확정·응답 유실 뒤 재시도·
늦은 후속 응답 무시·미지원 옵션·모바일 배치를 확인했다.
운영 서비스 검증 결과는 [dev API 계약 문서](https://github.com/SAJOYO/DAENGS_dev/blob/dev/docs/place/facility-discovery.md)를 참조한다.
실제 Redis 통합 검증과 Android AI 호출/release 전환은 이 도구의 완료 범위가 아니다.

기존 Gemini 실호출 기록은 [holdout 문서](../../docs/research/2026-09-02-place-intent-gemini-holdout.md)에 있다.
