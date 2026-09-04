# 산책 시나리오 → 주변 문맥 → 스토리보드

[탐색 갈래](../../../docs/explorations/walk/storyboard-and-regions.md)의 개발용 스파이크.
공공데이터는 실제 응답이고, 산책·Pin·게임 결과는 합성이다. 운영 앱·DB에는 쓰지 않는다.

## 준비와 실행

Python 3.12와 프로젝트의 `uv` 환경을 사용한다. geometry 의존성은 운영 패키지에 추가하지
않고 `--with pyshp --with shapely --with pyproj`로 실행한다.

1. SGIS에서 서울 센서스용 읍면동 경계 ZIP을 직접 신청·다운로드한다. 2025년 2분기 파일로
   확인했다. `.shp/.shx/.dbf/.prj/.cpg`가 있어야 한다. EPSG:5179 및 그 ESRI:102080 별칭만
   허용하며, `.cpg`의 인코딩을 따른다. 이번 파일은 UTF-8이다.
2. 키는 `DAENGS_DATA_GO_KR_SERVICE_KEY` 환경변수 또는 Git에서 제외된 `.env.storyboard`에
   같은 이름으로 둔다. 포털이 준 인코딩 키는 한 번 decode하고 요청 시 한 번 encode한다.
3. 저장소 밖에 source cache 및 HTML output 디렉터리를 지정한다.

처음 수집하거나 없는 cache를 채울 때:

```bash
uv run --with pyshp --with shapely --with pyproj python -m scripts.spikes.storyboard_and_regions.build --boundary-zip /path/bnd_dong_11_2025_2Q.zip --cache-dir /path/private-cache --out /path/storyboard --env-file .env.storyboard --fetch
```

이후에는 `--fetch --env-file .env.storyboard`를 빼고 같은 명령을 실행한다. 키와 네트워크가
필요 없다. cache가 없으면 실패하며 몰래 재조회하지 않는다. 실패한 응답도 cache에 남으므로
재조회는 `--fetch --refresh`를 명시한다. 세 원천의 페이지 수는 각각 최대 12로 제한한다.

`index.html`은 JSON·CSS·JS를 내장하며 외부 지도 타일·폰트·이미지·LLM 호출이 없다.
더블클릭해서 열거나 다음과 같이 로컬에서 제공한다.

```bash
uv run python -m http.server 8767 --bind 127.0.0.1 --directory /path/storyboard
```

산출물:

- `index.html`: 기본·관측 공백·Pin 없는 산책 비교, 게임 표시 스위치, 재생·직접 넘기기.
- `storyboard.json`: 시나리오, 장면의 근거, 순서 있는 동 구간, source receipt, fingerprint.

원본 cache는 기관 연락처 등 비표시 필드를 포함할 수 있다. 커밋하지 않는다. HTML/JSON은
공원명·대표점·자료일자, 상가 업종 집계, 하천 형상, 지역 구간만 선별한다. API 키·전화번호·
상가 원본 목록·SGIS 신청 개인정보는 산출물에 넣지 않는다. 합성 경로는 산출물에 들어간다.

## 파이프라인과 선택한 규칙

`sources.py`는 세 API 전체 페이지와 보조 EGIS 형상을 수집한다. 성공한 0건과 조회 실패,
부분 수집·형식 오류·중복 페이지를 구분한다. 요청 조건(키 제외), 수집 시각, 페이지 hash와
snapshot hash를 남긴다. 전 페이지 수집 중 변경되는 원천을 원자적 snapshot으로 보장하지는
못한다. EGIS는 최대 300개 형상을 받고 한도 도달 시 `partial`로 표시한다.

`geometry.py`는 SGIS polygon을 EPSG:5179 미터 좌표로 읽는다. 기존 `CanonicalTrail.segments`
하나씩 경계 교점에서 분할한다. 동일 동이어도 시각이 끊기거나 chain이 다르면 합치지 않는다.
중복 polygon hit는 첫 번째를 선택하지 않고 불확실로 남긴다. 경계 근처는 분할 구간의 중점과
양 끝점의 큰 accuracy 값을 비교한다. 이는 실험 휴리스틱이며 확률적 정확도 모델이 아니다.
분할 시각은 관측점 사이 선형 보간이다. 유효 형상이 아니면 자동 repair하지 않고 중단한다.

`build.py`는 기존 `scripts.sim.walk` 생성기와 Walk 계산기를 사용한다. 손으로 정한 경유점은
실제 도로·교량을 따른 경로라는 보장이 없다. 화면에 길 안내로 제시하지 않는다.
60초 이상 이어지는 안정적 지역 구간을 챕터 후보로 사용한다. 짧은 구간과 불확실 구간은
JSON에 남고, 모든 경계 통과가 장면이 되지는 않는다. 같은 동으로 돌아오는 순서도 남긴다.
공원은 관측점에서 대표점 250m 이내, 상가는 반경 125m로 제한한다. 상가 원천 질의인
중심 반경 1,200m가 후보 반경 전체를 덮는 경우만 완전한 근접 집계로 취급한다.
하천은 보조 EGIS 형상의 최근접 거리 250m 이내를 쓴다. 이것은 산책로 이용 증거가 아니다.

나레이션은 명시적 근거의 템플릿이다. 주변 가게를 방문했다거나 공원에 입장했다는 내용을
추가하지 않는다. 현재 영업·반려견 출입·날씨·행사·개인의 첫 방문은 이 자료가 제공하지 않는다.
게임 결과는 독립 fixture로 주어지며 좌표로 보상을 만들지 않는다.

## 좁은 검증

```bash
uv run --with shapely --with pyproj pytest tests/test_storyboard_sources.py tests/test_storyboard_regions.py -q
uv run pytest tests/test_script_imports.py -k storyboard_and_regions -q
uv run ruff check scripts/spikes/storyboard_and_regions tests/test_storyboard_sources.py tests/test_storyboard_regions.py
```

실제 API 키와 SGIS 파일을 쓰는 테스트는 없다. geometry 테스트는 선택 의존성이 없으면
skip되므로 위 `--with` 명령으로 확인해야 한다. 운영 저장·개인 이력·행사 검색·LLM narrator
통합은 이 실험 범위에 포함되지 않는다.
