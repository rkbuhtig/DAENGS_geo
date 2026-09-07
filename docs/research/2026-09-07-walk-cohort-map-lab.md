# 계절·강수 cohort 지도 실험 — 2단계

> 이 문서는 Geo `185747f` 기반 로컬 실험의 당시 기록이다. 본문의 코드 경로·실행 명령·localhost 주소는 해당 실험 작업 공간을 가리킨다. 이 문서 PR에는 실험 실행 코드와 원천 캐시를 포함하지 않는다. [종합 보고서](2026-09-07-walk-diary-experiment-report.md)에서 최신 검토 결론과 이전 정책을 대체한 단계를, [보존 자료 안내](2026-09-07-walk-diary-evidence/README.md)에서 저장소만으로 확인할 수 있는 범위를 확인한다.

2026-09-07, Geo 185747f 기반 `experiment/walk-cohort-season-weather`의 로컬 실험.
Dev·App 이식 판단 전이며, 운영 API/DB/LLM 변경은 없다.

## 확인할 질문

같은 길의 서로 다른 기록을 하나의 배경에 겹친 뒤, 위치 묶음 → 시간순 장면 → 원본 산책
경로로 이어갈 수 있는가? 선택한 장면 때문에 배경의 산책 집합이나 분모가 달라지는가?

## 구현

- 첫 단계의 계절·강수 정책, canonical 경로·paint·원본 방문율을 재사용한다.
- 수기 장면 대체: 합성 기록을 Geo `select_nodes`, `build_storyboard`에 전달해 실제 v2 계약의
  번들을 만든다. 합성 8회 중 기본 가을+비는 동일 경로 2회와 우회 1회다.
- 기본 결과는 산책 3회, 장면 24개, 임시 위치 묶음 7개. 이 중 좌표 없는 시작/끝 장면 6개는
  목록에만 존재한다. 생성된 장면을 날짜별로 합쳐 새 장면으로 만들지 않는다.
- `lab.py`가 산책별 bundle과 관측 좌표를 어댑트한다. 장면 ID·revision·entry·source_revision
  보존. 원본 bundle에 좌표를 억지로 추가하거나 route=null을 최근접 위치로 바꾸지 않는다.
- 필터는 서버 cohort를 다시 계산한다. 지도 숫자/장면 선택은 클라이언트 범위를 좁힐 뿐이다.
- 원본 Hex의 방문율과 표시용 복원 raster를 분리한다. 산책별 질량 보존 복원 후 표시 density를
  고정하고 같은 분모로 평균한다. 따라서 색을 방문율 퍼센트로 읽으면 안 된다.
- 브라우저 표시를 부드럽게 확대하는 bilinear 보간은 계산 evidence로 되돌리지 않는다.
  복원 raster의 원래 support 보존 검증과 화면상의 보간을 구분한다.

## 검증 결과

실행 환경: 기존 Geo Python 3.12 venv, 로컬 HTTP 서버, Windows Edge headless.

```text
python -m pytest tests/spikes/test_walk_cohort.py tests/spikes/test_walk_cohort_lab.py \
  tests/tools/test_lab_server.py::test_common_api_import_never_loads_review_code_or_creates_local_data -q
45 passed (7.45s)

python -m ruff check scripts/spikes/walk_cohort tests/spikes/test_walk_cohort.py \
  tests/spikes/test_walk_cohort_lab.py tools/lab_server.py tests/tools/test_lab_server.py
All checks passed
```

전체 테스트 스위트는 실행하지 않았다. 기존 Starlette/httpx 사용 중단 예고 경고 1건이 있다.

브라우저 검증: 위치 묶음에서 장면 선택, 동일 경로와 우회 경로 교체, 배경 이미지/결과 지문
불변, 계절·강수 OR/AND, 빈 집합, 날씨 정보 없음, 좌표 없는 기록, 흔적 토글,
320/360/430/760/1120px 가로 넘침 없음, API 실패 시 이전 결과/조건 일치 복구,
지도 라이브러리 실패 시 목록 유지. JavaScript 예외 없음. 최초 실행 타일 29개 응답 성공.

## 화면에서 확인된 후속 과제

1. 브러시 내부는 이어지지만 외곽에 셀 굴곡이 보인다. 계산 support·고정 농도를 유지하면서
   외곽 표현을 다듬는 실험이 필요하다. 지금 모습을 완성된 그림판 브러시로 보지 않는다.
2. 지도 숫자는 장면 수다. 자동 생성한 경로 장면과 사용자가 남긴 기록이 같은 위치에 모인다.
   사용자가 남긴 기록을 기본으로 볼지, 두 종류를 모두 볼지 실제 조작 후 결정할 수 있다.
3. 모바일에서 조건·지도·목록이 세로로 이어진다. 지도와 선택 카드의 동시 노출 높이를
   다음 화면 검토에서 조정할 수 있다. Android 네이티브 시트 동작을 검증한 것은 아니다.
4. 실제 관측 로그/과거 bundle 이관/원시 GPS 삭제 후 경로 이용 가능성/실기기 메모리와
   프레임 성능은 검증하지 않았다. fixture에 없는 불완전 원본을 정상 자료로 간주하지 않는다.

실행: `python -m tools.lab_server --tool walk-cohort --port 8766`,
`http://127.0.0.1:8766/walk-cohort-lab`.

## 외곽 개선 후속 — 표시용 번짐 v2

첫 화면의 Hex 외곽이 거슬린다는 검토에 따라 `display.py`를 추가했다.
원본 support를 표시 단계까지 강제하면 테두리의 셀 모양이 남으므로, 복원된 산책별 질량에
sigma=5m Gaussian을 적용하고 표시 단계에서는 원본 Hex 마스크로 다시 자르지 않는다.
2m raster, 각 축 ±8pixel(16m)로 잘린 합계 1의 kernel을 사용한다. 질량은 보존하며,
피크 기준 재정규화 없이 기존 고정 density·cohort 분모로 색을 계산한다.

이 번짐은 표시용 확장이다. 원본 셀과 방문율, 장면, 선택 산책 경로는 변경하지 않는다.
인접한 흔적이 시각적으로 이어질 수 있으므로 표시 raster를 방문/연결성 판정에 쓰지 않는다.
지도 아래 비교 버튼으로 같은 집합과 지도 범위에서 이전 외곽과 새 브러시를 전환할 수 있다.

검증: `pytest tests/spikes/test_walk_cohort_lab.py -q` → 10 passed (4.99s),
관련 세 Python 파일 Ruff 통과. 브라우저에서 표현 전환 시 배경 이미지 차이 및 결과 지문
불변을 확인했고 기존 클릭·필터·빈 결과·반응형 검사도 통과했다.
실제 캡처를 보고 각진 외곽이 부드러운 번짐으로 바뀐 것을 확인했다.
실기기 성능과 대규모 산책 집합은 여전히 검증 범위 밖이다.
