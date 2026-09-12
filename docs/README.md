# docs — 문서 지도

계획·현재 계약·결정·당시 실험 결과를 문서 유형별로 찾는다. 실행 명령은
[루트 빠른 실행](../README.md#빠른-실행)과 각 도구 README에서 확인한다.

## 저장소 역할과 제품 승격 경계

[저장소 실행 경계 #86](decisions/2026-09-07-repository-execution-boundaries.md)은
`app / tools / scripts`의 책임을 정의한다. 이행 중 예외는 3차에서 제거했다.
현재 위치와 기준선 대조는 [구조 정리 결과](research/2026-09-07-repository-reorganization.md),
실행은 [tools](../tools/README.md)·[scripts](../scripts/README.md)·[Alembic](../alembic/README.md)·[seed](../seeds/README.md) 안내를 따른다.

`DAENGS_geo`는 통합 뒤에도 폐기하지 않는다. **산책·공간·검색의 아직 확정되지 않은 가설을
실험하고, 측정과 계약 후보를 검증하는 R&D/검증 원본**으로 계속 쓴다.

다만 운영 코드의 소유권은 이관 결과를 따른다.

- 운영 **Place 검색·Journey 백엔드**의 canonical 구현은 `SAJOYO/DAENGS_dev`다. 운영 버그,
  배포·인프라, 실제 서비스 API 변경은 그 저장소에서 한다.
- 운영 **Android 지도·Place UX**의 canonical 구현은 `SAJOYO/DAENGS_app`이다. 이 저장소의
  Android 사본은 연구·대조용 기준 구현이지 제품 수정의 원본이 아니다.
- **walk·territory·공간 해석**, 그리고 검색의 새 원천·분류·ranking·추천 같은 아직 검증 중인
  실험은 이 저장소에서 계속 진행한다.

흐름은 **동기화가 아니라 승격**이다. 여기서 실험 → 측정·golden/fixture → 결정으로 근거를 만든 뒤,
제품에 채택할 것만 목적 저장소에 명시적인 PR로 옮긴다. 두 저장소의 같은 코드를 계속 맞춰 두거나
운영 수정사항을 이쪽 사본에 역동기화하지 않는다. 기존 Place/Android 코드가 이 저장소에 남아 있는
것은 walk 연구와 실험이 그 사실·fixture를 참조하기 때문이며, 그 존재가 운영 소유권을 뜻하지 않는다.

승격 기준점은 [promotion-ledger.toml](promotion-ledger.toml)에 기계가 읽을 수 있게 기록한다.
`uv run python -m scripts.promotion_status`는 각 기준점 뒤의 관련 변경을 보여 주며 CI에도 notice를
남긴다. 차이는 실험의 정상 상태이므로 실패 조건이 아니다. 운영 PR이 머지된 뒤에만 원장의 source와
target 커밋을 함께 옮겨, "어디까지 채택됐나"를 추측하지 않게 한다.

현재 제품 범위의 기준은 [결정 #51](decisions/2026-08-22-walk-as-spine.md), 장소 발견의 다음
제품 축은 [결정 #65](decisions/2026-08-26-place-first-discovery.md), 병원 진입 정책은
[결정 #71](decisions/2026-08-27-hospital-place-entry.md), 현재 구현 조립의 기준은
[provider-assembly.md](provider-assembly.md)다. 날짜가 파일명에 들어간 `research/`는 당시
관찰 기록이며 현재 상태 문서로 읽지 않는다.

```
overview.md          컨셉·범위. 거의 안 바뀜
provider-assembly.md 현재 어떤 공급자가 어느 표면에 조립됐는지 + 교체 실험 로그
decisions/           확정된 것만. 어느 탐색에서 나왔는지 링크
contracts/           남과의 약속 (프로필 계약, 검색 응답)
explorations/        갈래. 주제별 폴더, 갈래마다 파일. status로 상태 표시
research/            날짜 박힌 사실 조사·실험 로그
backlog.md           갈래에 안 붙는 미결
```

## 갈래 상태

`proposed` 도입 후보 · `exploring` 파는 중 · `adopted` 채택 (decisions/에 한 줄 생김) · `parked` 보류 · `rejected` 기각 (지우지 않음 — 같은 질문 다시 안 하려고)

`status`는 **제품 결정**, 선택적인 `implementation`은 **코드 성숙도**다. 구현돼 있어도 현재
제품 범위에서 빠졌다면 `status: parked`, `implementation: working-skeleton`이 될 수 있다.

## 주제별 작업 입구

| 작업 | 입구 |
|---|---|
| 장소·시설 검색과 검토 UI | [시설](explorations/facility/README.md) |
| 병원 검색의 배경·보류 실험 | [병원 찾기](explorations/hospital-search/README.md) |
| 지도·경로 어댑터와 현재 조립 | [지도 제공사](explorations/map-provider/README.md), [공급자 조립](provider-assembly.md) |
| 모바일 기준 구현과 화면 정책 | [모바일 셸](explorations/mobile-shell/README.md) |
| 산책 전체·수집·공간 분석 | [산책](explorations/walk/README.md), [기록](explorations/walk/recording/README.md), [공간](explorations/walk/spatial/README.md) |
| 독립 장면·별도 일기 생성 기획과 재료·실험 | [일기](explorations/walk/diary/README.md) |
| 점령 정책·시즌·구현 이관 | [게임](explorations/walk/game/README.md) |
| 산책·점령 세션의 통계 | [통계](explorations/walk/statistics/README.md) |

## 주요 결정

전체 번호와 당시 판단은 [결정 목록](decisions/README.md)에 있다. 아래는 주요 경계의 바로가기다.

- [결정 #51 — 병원은 산책의 모드, 산책이 척추](decisions/2026-08-22-walk-as-spine.md) — 08-19 → 08-22의 사슬과 2026-08-24 채택 범위
- [결정 #65 — Place 우선 장소 발견](decisions/2026-08-26-place-first-discovery.md) — 원천 kind 후보군 → 조건 → 사실 순서, 의미 제안은 선택층
- [결정 #69 — 원좌표 purge 뒤 남기는 공간 형태](decisions/2026-08-26-walk-permanent-spatial-form.md) — 집계 셀 맵 하나. 궤적은 안 남긴다. #57 의 네 번째 층이고 민감도는 장 수가 만든다
- [결정 #71 — 병원은 Place로 찾되 UI에서는 바로 진입](decisions/2026-08-27-hospital-place-entry.md) — 병원 바로가기와 전용 action은 유지하고 검색 identity·순위는 canonical Place로 통일
- [결정 #74 — Capsule에서 공간 일기로](decisions/2026-09-01-spatial-diary.md) — 산책 증거를 봉인하고 실제 Offer·증언·Pin을 분리해 조건별 공간 일기로 다시 읽는다
- [결정 #75 — Capsule finalize](decisions/2026-09-01-walk-capsule-finalize.md) — 8u Cellophane·원시 영수증·문맥·manifest를 한 트랜잭션으로 봉인한 뒤 raw fix를 지운다
- [결정 #76 — SpatialDiaryView v0](decisions/2026-09-01-spatial-diary-view-v0.md) — 기간·강수·낮밤으로 Capsule을 골라 visit rate 또는 산책 동등가중 field로 읽는다
- [결정 #77 — Candidate에서 Episode Pin으로](decisions/2026-09-01-spatial-diary-episode-pin-v0.md) — low-motion 후보를 실제 Offer·사용자 증언을 거쳐 안정 Pin으로 승격하고 조건별 지도에 겹친다
- [결정 #78 — Memory Place v0](decisions/2026-09-01-spatial-diary-memory-place-v0.md) — 서로 다른 산책의 Pin을 안정 장소로 묶고 노출·판정 가능성·강수 비교를 전기로 읽는다
- [결정 #79 — WalkJournalProjection v0](decisions/2026-09-01-spatial-diary-walk-journal-v0.md) — 한 산책의 사실·문맥·Pin을 저장 원본 없이 결정론적 시간 일기로 다시 읽는다
- [결정 #80 — PublishedJournalSnapshot v0](decisions/2026-09-01-spatial-diary-published-journal-v0.md) — 사용자가 제목·요약·대표 Pin을 고정한 비공개 불변 일기를 별도 수명으로 보존한다
- [결정 #81 — 부정적 공간 주장 자격](decisions/2026-09-01-negative-spatial-claim-eligibility.md) — `not_observed`는 평가 방법이 있는 drift `not_suspected`일 때만 허용한다
- [결정 #82 — Pin Attestation 정정](decisions/2026-09-01-spatial-diary-attestation-correction.md) — 최초 Offer 응답과 Pin identity는 보존하고 현재 의미만 append-only correction head로 바꾼다
- [결정 #83 — Context Plane v0](decisions/2026-09-01-context-plane-v0.md) — 날씨·프로필·측정 재료를 typed Atom·Facet·Lens로 분리하고 개인의 속마음은 registry 밖에 둔다
- [결정 #84 — CanonicalTrail consumer boundary](decisions/2026-09-03-canonical-trail-consumer-boundary.md) — canonical 산책 증거는 finalize 중 한 번만 만들고 일기·점령은 각자 자격과 수명으로 소비한다. 점령 v0는 단일 `claiming_pet_id` 가계약

## 주요 계약

계약 문서가 초안인지 채택·구현된 범위인지 해당 문서에서 확인한다.

- [산책·점령 통계 코어](contracts/activity-statistics-core.md) — 세션 연결·확정 분석·보유 구간 재생
- [통계 PostgreSQL 저장·처리](contracts/activity-statistics-postgres.md) — 저장·재처리·복원
- [점령 정책 연결](contracts/territory-policy-integration.md) · [PostgreSQL 저장](contracts/territory-policy-postgres.md) — 입력·잠금·멱등성과 DB 어댑터
- [스토리보드 장면 후보 v2](contracts/walk-storyboard-candidates-v2.md) — 대상 강아지·원본 기록 버전과 조회 목표/한계를 보존하며 v1 소비자와 호환
- [반려견 프로필](contracts/dog-profile.md) — 외부에서 받는 형태 + 가상 페르소나 8마리 (축: 지도 위 난점)
- [견주 프로필](contracts/owner-profile.md) — 이동 제약 + 페르소나 5명 (축: 병원의 역할을 아는 정도)
- [Place v2 검색](contracts/place-search-v2.md) — kinds별 그룹, 공통 identity·facts, 주차 사실 선호
- [산책 기록](contracts/walk-record.md) — **우리가 주는 것** (outbound). 사실만, 의미 없음, 테스트로 고정
- [Cellophane GeoJSON](contracts/cellophane-geojson.md) — chain별 선·서버 육각형·Paint v2 질량 진단
- [Walk Capsule과 기억 경계](contracts/walk-capsule.md) — Capsule·Offer·Interaction·Attestation·Pin의 불변/파생/append-only 수명
- [Spatial Diary View](contracts/spatial-diary-view.md) — Walk Selector 분모와 Entry Selector overlay, 품질·통계·결과 영수증
- [Memory Place biography](contracts/memory-place-biography.md) — 장소 identity·membership과 노출·관측 가능성·부정적 공간 주장 자격
- [Pin Attestation correction](contracts/pin-attestation-correction.md) — 사용자 의미 정정 chain과 최초 응답·현재 projection의 권위 분리
- [Walk Journal Projection](contracts/walk-journal-projection.md) — Capsule 사실·문맥·Pin에서 재생성하는 한 산책의 결정론적 일기
- [CanonicalTrail consumers](contracts/canonical-trail-consumers.md) — transient canonical 입력, 소비자별 eligibility, 점령 `claiming_pet_id` 가계약
- [Published Journal Snapshot](contracts/published-journal-snapshot.md) — 사용자가 확정한 제목·요약·대표 Pin과 원본 정책 영수증을 보존하는 비공개 불변본
- [Context Plane v0](contracts/context-plane.md) — 닫힌 capability·typed Atom·파생 Facet·목적 Lens와 fingerprint/evidence 경계

## 조사

- [산책 지도 일기 실험 종합](research/2026-09-07-walk-diary-experiment-report.md) — 셀로판·혼합 브러시·탐색 UI에서 공공 공간 조각과 Gemini 1~3차까지. 단계별 결과·실패·회고·보존 입출력

아래 문서는 제목 날짜의 스냅샷이다. 결론이 뒤 결정에서 바뀌어도 본문을 현재형으로 다시 쓰지
않고, 필요한 경우 `superseded_by` 안내만 추가한다.

- [연속 원 field와 Hex 비교](research/2026-08-31-continuous-hex-comparison.md) — 30회 산책의 4·8·12u 왜곡·질량 영역·수집 간격 측정
- [Hex Cellophane의 보수적 연속 Field 복원](research/2026-09-01-conservative-hex-reconstruction.md) — 저장 계약을 바꾸지 않는 A/B/C 복원·누출·양방향 질량 비교
- [GPS 오염에서 Cellophane과 복원 Field](research/2026-09-01-sensor-robustness.md) — dropout·outlier·drift·accuracy를 수집→canonical→Cellophane→Field 단계별로 분리한 paired 평가
- [일기 스켈레톤 실행](research/2026-09-06-diary-storyboard-skeleton.md)
- [일기 계산 입력 연결](research/2026-09-06-diary-geo-observed-inputs.md)
- [일기 근거 대조 비교](research/2026-09-06-diary-claim-comparison.md)
- [산책 기록 lab](research/2026-09-05-walk-record-lab.md)
- [지도 제공사 요금·쿼터·코드](research/2026-08-19-map-provider-pricing.md)
- [리뷰/평가 데이터 출처](research/2026-08-19-review-sources.md)
- [쿼리 재작성 실험](research/2026-08-19-query-rewrite-experiment.md)
- [경로 API 조사 + 네이버 화면 실측](research/2026-08-19-route-apis.md)
- [워킹 스켈레톤 실행 로그](research/2026-08-19-skeleton-run.md)
- [TMAP 실호출 — 문서와 다른 점, 파서 반영](research/2026-08-19-tmap-live.md)
- [Mapillary — 산책 개 합성 재료 조사 (라이선스·API·한국 커버리지)](research/2026-08-19-mapillary.md)
- [네이버 파노라마 — 약관 원문(제7조 ⑨⑪), 정적 API 없음, Android 없음](research/2026-08-19-naver-panorama.md)
- [국내 반려견 앱 경쟁 조사 — 서비스 유형 × 리뷰 불만, 우리 설계와 연결](research/2026-08-19-competitor-reviews.md)
- [산책 데이터 — 논문 근거와 신뢰도 등급 (GPS 오차·목걸이 가속도계·활동량 표준)](research/2026-08-19-walk-data-evidence.md)
- [dev 콘솔 + spots(반려견 관심 지점)](research/2026-08-19-dev-console.md)
- [facility.pet 커버리지 — 필터로 쓸 수 있나](research/2026-08-24-facility-pet-coverage.md)
- [TMAP 보행자 옵션 조사 — 288경로, 계단 0, 옵션 71~91% 동일, 단발 99% 일치](research/2026-08-22-tmap-option-survey.md)
- [셀로 면 체류를 근사할 수 있나 — 면÷셀 4~5배가 손익분기, 다이얼 범위 실제 22~91m](research/2026-08-26-region-cell-fidelity.md)
- [붓 감쇠 — 이진 도장은 구별 0, 심 반경은 3·8·20 (실제 OSM 도로망 24회 산책)](research/2026-08-26-brush-falloff.md)
- [셀로판 회수 실험 — 정답 심은 1년치 7명, 6 기준 통과. 연간 누적이 같은 두 사람이 계절 조건에서 정반대로 갈린다](research/2026-08-26-cellophane-recovery.md)
- [복구한 맥락이 지도에서 읽히나 — 전체 장면에선 지문까지 같고 계절 버튼 하나로 갈린다](research/2026-08-26-layer-viewer.md)
- [OSM 산책 후보 도로망에 잠재 미시 행동을 심는다 — 대조군 셋. 아무것도 안 심은 대조군의 통행 길목이 심은 자리 전부를 이긴다](research/2026-08-27-latent-dwell-synthesis.md)
- [occupancy 는 시간이 아니었다 — 격자 밀도가 섞여 있었다. 정규화하면 1초가 1초로 쌓인다](research/2026-08-27-mass-conserving-kernel.md)
- [멈춤이 물감이 되는가 — 된다, 그런데 성긴 격자에선 5회 통과가 2분 체류를 이긴다](research/2026-08-27-dwell-becomes-paint.md)
- [원좌표를 지우면 무엇을 남기나 — 궤적 후보는 추정의 14배(대부분 GPS 지터), 집계만 남겨도 경로 topology 가 우연의 18배로 샌다](research/2026-08-26-storage-candidates.md)
- [테스트 재점검 — 구조 재편이 남긴 격차의 지도와 pass 별 진행](research/2026-08-27-test-suite-audit.md)
- [rebuild_links 가 2억 쌍을 훑어 107행을 만든다 — 공간 인덱스가 안 쓰이는 이유와 선택지](research/2026-08-27-link-rebuild-cost.md)
- [M2 사건 자리에서 진짜 세계가 얼마나 읽히나 — DB 명사 0/3, crossing 6/6, 미시 원인 층(나무·벤치·풀)은 OSM 에 0](research/2026-08-28-world-context-readout.md)
- [3축 Context Signature — 피복·업종·하천으로 DB 명사 0/3 이 원천 명사 3/3, A·D 자리 쌍 3/3 구분](research/2026-08-28-context-signature-readout.md)

## 새 갈래 만들 때

`explorations/<주제>/<갈래>.md`, 상단에
```
---
status: proposed | exploring | adopted | parked | rejected
implementation: none | draft | working-skeleton | verified  # 선택
last_verified: YYYY-MM-DD                                   # 현재 상태를 주장할 때
depends-on: (있으면)
---
```
주제 README 표에 한 줄 추가. adopted 되면 `decisions/README.md`에 번호 붙여 한 줄, 갈래 파일은 그대로 둔다.

산책은 [주제별 입구](explorations/walk/README.md)에 따라
`explorations/walk/{recording,spatial,diary,game,statistics}/` 아래에 둔다.
계약·결정·날짜별 연구 기록은 문서 유형별 기존 위치를 유지하고 주제 README에서 연결한다.

## 갈래를 닫을 때 (adopted · rejected)

종료 시 코드 유지·제거 기준과 재현 경로 처리는 [scripts 안내](../scripts/README.md#갈래를-닫을-때)를 따른다.
갈래의 채택·기각만으로 실험 코드를 자동 삭제하지 않는다. 결정과 날짜별 연구 기록은 보존한다.

## README를 갱신할 때

루트 README는 저장소 목적과 작업 입구, 이 문서는 문서 유형과 주제 연결을 맡는다.
주제 README는 기준 계획·구현·실행·검증·운영 채택 기록을 연결하고, 도구·실험 README는
준비 조건·명령·출력·저장·복구를 소유한다. 같은 상태표와 실행 절차를 여러 입구에 복제하지 않는다.
현재 구현 설명을 바꿀 때는 코드·설정·테스트와 대조하고, 과거 검증 날짜를 새 날짜로 바꾸지 않는다.
