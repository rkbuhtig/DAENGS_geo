# 산책 일기 실험 보존 자료

[종합 보고서](../2026-09-07-walk-diary-experiment-report.md)의 숫자와 생성 문장을 저장소에서 검토하기 위한 자료다. 2026-09-07 로컬 실험 산출물을 문서 PR에서 추출했다. 문서화를 위해 Gemini를 재호출하지 않았다.

## Gemini 입력·출력

| 파일 | 정책 | 조건 |
| --- | --- | --- |
| [gemini-01.json](gemini-01.json) | raw 누가·무엇을·어디서 | movement / actions / gap |
| [gemini-02.json](gemini-02.json) | 공간 배경·거리 관계·사건 분리 | 동일 세 조건 |
| [gemini-03.json](gemini-03.json) | 행동·전환·연결 역할과 중심 근거 | 동일 세 조건 |

각 파일은 실제 요청의 `system_instruction`, `generation_config`와 조건별 다음 필드를 보존한다.

- `input`: 실제 모델에 전달한 구조화 조각. 원천 공간 캐시와 좌표 감사 자료 전체는 제외했다.
- `output`: 응답에서 파싱한 JSON 원문 값. 제목·본문·요약·선정/생략 이유·한계 설명을 편집하지 않았다. API 응답 envelope 전체나 응답 ID는 넣지 않았다.
- `input_sha256`, `prompt_sha256`: 기존 실행 영수증의 해시.
- `output_sha256`: 아래 정규화 방식으로 산출한 출력 해시. 2·3차 `editorial_review.output_sha256`는 당시 검토 해시다. 1차 검토는 당시 비교 화면의 `review`를 가져왔다.
- `usage`, `seconds`, `model`, `model_version`, `validation`: 당시 성공 호출의 사용량·시간·모델·구조 검사 결과.
- `editorial_review`: Gemini 원문과 분리한 Codex 검토 의견. 사용자 평가나 독립 심사 결과가 아니다. 검토의 `quote` 필드는 원문 발췌 외에 ‘전환 후보 7개 전부 선택’ 같은 관찰 요약도 포함한다.

해시의 정규화는 `sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8'))`다. `prompt_sha256`의 value는 `system_instruction.parts[0].text` 문자열이다. 입력이나 출력 JSON 파일의 바이트 해시와는 다르다.

2차 생성 시도는 4회, 성공 응답은 3건이다. 응답 없는 첫 요청의 사용량은 알 수 없고 합계에서 제외했다. 9개 성공 응답의 총 토큰 89,999를 실제 청구 총액이나 실패 요청까지 포함한 사용량이라고 읽지 않는다.

이 자료로 입력 후보·생성 문구·ID·생략 이유·사용량·검토 해시를 대조할 수 있다. 모델 호출이나 외부 원천을 다시 수집하지 않고 읽을 수 있다. 원자료의 기하 계산을 처음부터 재현하거나 구조 검사를 다시 실행하려면 당시 로컬 실험 코드와 공간 캐시가 별도로 필요하다. 이 PR은 실행 패키지를 제공하지 않는다.

## UI 결과와 캡처

| 자료 | 내용 |
| --- | --- |
| [cohort-density-browser-report.json](cohort-density-browser-report.json) | 3·30·100회, 줌별 묶음, 20행 페이지, 모바일 지도/카드 배치 |
| [visit-colour-browser-report.json](visit-colour-browser-report.json) | 2/3·20/30, 체류/누락 불변성, 원본 Hex 조회 |
| [hybrid-browser-report.json](hybrid-browser-report.json) | 혼합 농도 함수 수치와 브라우저 확인 항목 |
| [geo-cohort-hex-edge.png](geo-cohort-hex-edge.png) / [geo-cohort-soft-brush.png](geo-cohort-soft-brush.png) | 초기 외곽 개선 전후. 숫자는 당시 밀집 장면 수 |
| [hybrid-mobile.png](hybrid-mobile.png) | 혼합 농도와 선택 카드. 당시 묶음 수 표시 UI |
| [diary-preview-list-mobile.png](diary-preview-list-mobile.png) | 이후 목록 시안. 경로·출발/도착·시간순 장면 번호 |

브라우저 JSON 3개와 PNG 4개는 로컬 저장본을 그대로 복사했다. 지도는 Leaflet/OpenStreetMap 표기를 유지했다. 입력은 합성 산책이며 일부 캡처의 미래 날짜·제목도 fixture다. 실제 사용자 기록·사진·계정 정보가 아니다. 생성 원본 지도와 브러시 데이터 전체를 보존한 것은 아니므로 PNG만으로 방문 통계를 역산할 수는 없다.

키·인증 헤더·공공데이터 원본 ZIP·실제 사용자 기록은 포함하지 않는다. 단계별 문서의 `outputs/...`와 localhost는 당시 로컬 작업 공간 경로다.
