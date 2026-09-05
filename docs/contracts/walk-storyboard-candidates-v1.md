# geo → app 장면 후보 계약 v1

> 이 문서의 최초 연결은 lab JSON 교환이다. 이후 동일 bundle을 운영 분석 API에서도
> 사용하도록 연결했다. [실데이터 이식](walk-storyboard-live.md)과
> [공간 일기 제작 계획](../explorations/walk/diary-storyboard-plan.md)에서 최신 연결 상태를 확인한다.

산책의 사실 조각을 전달한다. 완성된 AI 일기나 사용자 편집본을 전달하지 않는다.
정식 HTTP API가 아닌 lab JSON 교환 계약이며, 스키마는 같은 폴더의
`walk-storyboard-candidates-v1.schema.json`이다. app의 `GeoStoryboardBundle`이 읽는다.

| 단위 | 필드와 의미 |
| --- | --- |
| 묶음 | format, session_id, source_revision, synthetic, 시간순 scenes |
| 장면 | id, revision, started_at/ended_at, route, reasons, title, facts, sources |
| route | 수용된 경로의 누적 start_m/end_m, 연속 관측 block_id. 위치 불명은 null |
| facts | id, kind, text, source_ids. 관찰·환경·이동·자료 공백을 구별 |
| sources | id, provider, status, captured_at, url. 캐시 조회 시각은 산책 당시 환경을 보증하지 않음 |

선택 이유는 session_boundary/action/note/profile_change/session_speed/distance_fill/
observation_gap이다. 환경 지점의 action은 **선택 이유**이며 새 행동 관찰이 아니다.
행동 수는 action 종류의 fact에 대해서만 논의하며, 횟수가 아닌 기록된 장면 수다.

장면 ID는 세션과 원본 정체성으로 만든다. 핀·메모는 기록 ID, 환경 후보는 연속 관측
블록과 관측 시각, 공백은 양 끝 시각으로 식별한다. 배열 순서나 문구 변경은 ID를
바꾸지 않는다. 재분석으로 지점·블록 자체가 달라지면 새 장면이다. 근접 장면 자동 대응은
아직 하지 않는다. 내용·출처가 바뀌면 장면 revision과 묶음 source_revision이 달라진다.

app은 사용자 제목·본문·숨김·확인한 원본 fingerprint를 별도로 보관한다. 같은 ID의
원본이 바뀌면 편집을 남기고 재확인을 요구한다. 없어진 원본의 사용자 문구는 보존하되
현재 검토본에서 제외한다. 검토 완료는 포함된 장면의 원본 payload까지 동결하며,
마지막 검토본 하나를 보관한다. AI 호출이나 과거 검토본 자동 덮어쓰기는 없다.

## 고정 실험

`tests/fixtures/storyboard`의 다섯 JSON은 **합성 GPS + 실제 공공데이터 캐시**로 만들었다.
핀 없음, 450~480초 핀 쏠림, 400~600초 GPS 공백, 300m에서 40초 정지, 같은 세션의
메모 정정·짖기 삭제를 포함한다. 캐시가 없으면 미확인 사실로 출력하므로 같은 파일을
재현하려면 같은 캐시가 필요하다. 공공데이터 키와 원본 응답은 저장소에 포함하지 않는다.

```powershell
.venv\Scripts\python.exe -X utf8 -m scripts.spikes.walk_record_lab.export_app_fixtures --cache-dir C:/private/walk-lab/cache --out C:/private/walk-lab/app-fixtures
```

명시적으로 조회할 때만 `--fetch --env-file C:/private/walk-lab/private.env`를 더한다.
lab의 `산책 종료 · 결과 만들기` 후 `app 장면 JSON 저장`으로 다른 실험도 내보낼 수 있다.
app debug의 지난 산책 → geo 스토리보드 실험 → JSON 불러오기로 검토한다.
운영 산책 DB와 분리하며 synthetic=true만 받는다. 파일은 1MB 이하, 최대 250장면이다.

현재 과거 대비 이동은 과거 세션의 전체 속도 중앙값을 비교하는 실험값이다.
공간별 셀로판 프로필이나 운영 개인화 정책, 서버 동기화, AI 생성은 이 계약 작업에 포함하지 않는다.
