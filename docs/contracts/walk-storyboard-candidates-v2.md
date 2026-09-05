# 장면 후보 v2 — 기록 귀속과 조회 한계도 검토 근거로 남기기

v1의 시각·장면 ID·사실/출처·revision 경계는 유지하고 `scene.entry`와 `bundle.selection`을
추가한다. [JSON Schema](walk-storyboard-candidates-v2.schema.json)가 구조의 기준이다.
AI 일기나 개인화 정책을 추가하는 계약은 아니다.

## 기록 근거

모든 장면에 `entry` 필드가 있다. 직접 남긴 행동·메모에만 객체를 넣고, 시작·종료·환경 조회
지점·속도 변화·공백은 null이다. 환경 지점의 선택 이유가 action이어도 사용자 행동이 아니다.

| 필드 | 의미 |
|---|---|
| entry_id | 원본 행동/메모의 ID. 같은 원본을 수정해도 장면 ID는 유지 |
| revision | 현재 서버 기록 버전, 1 이상. 서버 버전이 없는 합성 lab에서만 null 허용 |
| pet_id | 행동의 대상 강아지 ID. 미지정 또는 산책 전체 메모면 null |

귀속과 버전을 장면 fingerprint 계산 및 사본의 원본 payload에 포함한다. A→B, 대상 해제,
같은 대상의 새 원본 revision 모두 장면 변경이다. 앱은 사용자 제목·본문·숨김을 보존하면서
재확인을 요구한다. 새 검토 완료본에는 정정된 귀속/버전이 들어가며 이전 완료본을 자동 수정하지 않는다.
현재 강아지 이름은 UI에서 ID로 조회해 표시한다. 이름 표시가 원본의 귀속 ID를 바꾸지 않는다.

## 조회 상태

`selection`은 지점 선정의 진단이며 시설 검색 성공률이나 최종 장면 수가 아니다.

| 필드 | 의미 |
|---|---|
| minimum_target / selected_count | 최소 조회 목표와 실제 선택한 지점 수 |
| minimum_met / shortfall_reason | 목표 달성 여부. 달성이면 null, 미달이면 insufficient_distinct_valid_route |
| coverage_met | 선택 지점 사이의 빈 경로 구간을 목표 안으로 보충했는지 |
| longest_unread_m / max_unread_m | 남은 최장 빈 경로 거리와 목표. 거리는 selector의 반올림된 값 |
| max_anchors | 조회 지점 상한, 현재 8 |
| deferred_action_count | 상한 때문에 환경 조회를 보류한 행동 기록 수. 원본 행동의 삭제/생략 수가 아님 |

목표 미달은 서로 떨어진 유효 관측 구간이 충분하지 않다는 뜻이다. 짧은 경로·관측 공백·
지점 간격 조건 중 어느 하나를 개별 원인으로 확정하지 않는다. 긴 공백 보충 실패와 조회
예산 초과는 별도로 표시한다. 조회한 곳에서 시설이 검색됐어도 구간 목표는 미달할 수 있고,
지점 목표를 달성했어도 환경 자료는 미확인일 수 있다.

같은 설명을 종료 장면의 coverage facts에도 남겨 검토 완료 사본 및 v1 소비자에도 전달한다.
조회 요약을 바꾸면 종료 장면 revision과 bundle source_revision이 바뀐다. 지점을 억지로
추가하거나 GPS 공백을 이동/정지로 채우지 않는다. 기존 선정 우선순위·문턱값은 바꾸지 않는다.

## 운영 호환과 배포 순서

- dev는 canonical v2 bundle 하나를 기존 JSONB에 저장한다. 정책 버전을 올려 기존 v1 분석은
  다음 요청에서 재생성한다. 새 SQL이나 geo 운영 프로세스는 필요 없다.
- POST의 `bundle_format`, GET의 같은 이름 query가 v2이면 v2를 응답한다. 생략하면 v1이다.
  v1 변환은 추가 필드를 제거하되 정정된 장면 revision과 조회 진단 facts를 유지한다.
  표현 형식만 바꾸는 요청은 generation을 올리거나 외부 조회를 다시 하지 않는다.
- **서버를 먼저 반영하고 앱을 업데이트한다.** 새 앱은 v2를 요청하지만 저장돼 있던 v1도 읽는다.
  기존 서버는 새 요청 필드를 거절할 수 있으므로 새 앱부터 배포하는 순서는 지원하지 않는다.
- v1에는 구조화된 귀속/선택 상태가 없으며 앱이 이전 JSON에서 추측해서 보충하지 않는다.

## 재현

`tests/fixtures/storyboard/v2-{before,after,short,budget}.json`은 실제 관측만 흉내 낸 합성 자료다.
네 JSON을 dev 계약 테스트와 app 검토 테스트에도 같은 바이트로 복사했다. 이전 다섯 v1
fixture는 호환성 검증용으로 유지한다. 이 생성기는 키·실제 사용자 기록·외부 API를 사용하지 않는다.

```powershell
.venv/Scripts/python.exe -X utf8 -m scripts.spikes.walk_record_lab.export_evidence_fixtures --out tests/fixtures/storyboard
```

연결 PR: [geo #240](https://github.com/rkbuhtig/DAENGS_geo/pull/240),
[dev #267](https://github.com/SAJOYO/DAENGS_dev/pull/267),
[app #163](https://github.com/SAJOYO/DAENGS_APP/pull/163).
