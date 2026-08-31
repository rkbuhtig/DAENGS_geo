# docs — 지도

문서는 한 줄기가 아니라 **갈래**로 자란다. 뭐가 확정이고 뭐가 탐색 중인지 여기서 본다.

## 저장소 역할과 제품 승격 경계

`DAENGS_geo`는 통합 뒤에도 폐기하지 않는다. **산책·공간·검색의 아직 확정되지 않은 가설을
실험하고, 측정과 계약 후보를 검증하는 R&D/검증 원본**으로 계속 쓴다.

다만 운영 코드의 소유권은 이관 결과를 따른다.

- 운영 **Place 검색·Journey 백엔드**의 canonical 구현은 `SAJOYO/DAENGS_dev`다. 운영 버그,
  배포·인프라, 실제 서비스 API 변경은 그 저장소에서 한다.
- 운영 **Android 지도·Place UX**의 canonical 구현은 `SAJOYO/DAENGS_APP`이다. 이 저장소의
  Android 사본은 연구·대조용 기준 구현이지 제품 수정의 원본이 아니다.
- **walk·territory·공간 해석**, 그리고 검색의 새 원천·분류·ranking·추천 같은 아직 검증 중인
  실험은 이 저장소에서 계속 진행한다.

흐름은 **동기화가 아니라 승격**이다. 여기서 실험 → 측정·golden/fixture → 결정으로 근거를 만든 뒤,
제품에 채택할 것만 목적 저장소에 명시적인 PR로 옮긴다. 두 저장소의 같은 코드를 계속 맞춰 두거나
운영 수정사항을 이쪽 사본에 역동기화하지 않는다. 기존 Place/Android 코드가 이 저장소에 남아 있는
것은 walk 연구와 실험이 그 사실·fixture를 참조하기 때문이며, 그 존재가 운영 소유권을 뜻하지 않는다.

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
`exploring` 파는 중 · `adopted` 채택 (decisions/에 한 줄 생김) · `parked` 보류 · `rejected` 기각 (지우지 않음 — 같은 질문 다시 안 하려고)

`status`는 **제품 결정**, 선택적인 `implementation`은 **코드 성숙도**다. 구현돼 있어도 현재
제품 범위에서 빠졌다면 `status: parked`, `implementation: working-skeleton`이 될 수 있다.

## 주제
- [공급자 조립 현황](provider-assembly.md) — 현재 선택·폴백·교체 지점·검증 로그
- [병원 찾기](explorations/hospital-search/README.md) — 장소·거리 코어와 parked 실험을 분리
- [지도 제공사](explorations/map-provider/README.md)
- [문화시설](explorations/facility/README.md) — 기반층을 실제로 쓸 수 있게. 병원과 달리 조건 편집의 오른쪽 항이 있다
- [산책](explorations/walk/README.md) — 코어는 수집 계약, 갈래는 전부 소비자 옵션
- [싸인펜·셀로판·통계층](explorations/walk/cellophane-statistical-layer.md) — 한 산책의 시간 공간장, 산책별 z축 보존, 방문률·체류·공간 이용 분포를 서로 다른 연산으로 분리
- [반복 체류 영역 — 조작적 정의](explorations/walk/repeated-dwell-area.md) — 의미를 안 붙인 채로 "여러 산책에서 반복해 주변보다 우세한 자리" 를 못 박는다
- [판단 가능한 상태로 — Evidence 층](explorations/walk/evidence-layer.md) — 원시 행동을 저장하는 게 목적이 아니라 사람과 AI 가 같은 근거를 읽고 판단하게 만드는 것. 지도는 맨 마지막
- [산책 경험 장면](explorations/walk/experience-scenario.md) — 저녁 산책 직전 화면 한 장이 스펙 전부. 기록·해석·행동 중 무엇이 값어치인지 판정한다
- [모바일 셸](explorations/mobile-shell/README.md) — 폰에서의 제품 화면. 공간 표면 vs 에피소드 표면
- [결정 #51 — 병원은 산책의 모드, 산책이 척추](decisions/2026-08-22-walk-as-spine.md) — 08-19 → 08-22의 사슬과 2026-08-24 채택 범위
- [결정 #65 — Place 우선 장소 발견](decisions/2026-08-26-place-first-discovery.md) — 원천 kind 후보군 → 조건 → 사실 순서, 의미 제안은 선택층
- [결정 #69 — 원좌표 purge 뒤 남기는 공간 형태](decisions/2026-08-26-walk-permanent-spatial-form.md) — 집계 셀 맵 하나. 궤적은 안 남긴다. #57 의 네 번째 층이고 민감도는 장 수가 만든다
- [결정 #71 — 병원은 Place로 찾되 UI에서는 바로 진입](decisions/2026-08-27-hospital-place-entry.md) — 병원 바로가기와 전용 action은 유지하고 검색 identity·순위는 canonical Place로 통일

## 계약
- [반려견 프로필](contracts/dog-profile.md) — 외부에서 받는 형태 + 가상 페르소나 8마리 (축: 지도 위 난점)
- [견주 프로필](contracts/owner-profile.md) — 이동 제약 + 페르소나 5명 (축: 병원의 역할을 아는 정도)
- [Place v2 검색](contracts/place-search-v2.md) — kinds별 그룹, 공통 identity·facts, 주차 사실 선호
- [산책 기록](contracts/walk-record.md) — **우리가 주는 것** (outbound). 사실만, 의미 없음, 테스트로 고정
- [Cellophane GeoJSON](contracts/cellophane-geojson.md) — chain별 선·서버 육각형·Paint v2 질량 진단
- [연속 원 field와 Hex 비교](research/2026-08-31-continuous-hex-comparison.md) — 30회 산책의 4·8·12u 왜곡·질량 영역·수집 간격 측정

## 조사

아래 문서는 제목 날짜의 스냅샷이다. 결론이 뒤 결정에서 바뀌어도 본문을 현재형으로 다시 쓰지
않고, 필요한 경우 `superseded_by` 안내만 추가한다.
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
status: exploring | adopted | parked | rejected
implementation: none | draft | working-skeleton | verified  # 선택
last_verified: YYYY-MM-DD                                   # 현재 상태를 주장할 때
depends-on: (있으면)
---
```
주제 README 표에 한 줄 추가. adopted 되면 `decisions/README.md`에 번호 붙여 한 줄, 갈래 파일은 그대로 둔다.

## 갈래를 닫을 때 (adopted · rejected)
`status`를 바꾸는 것으로 끝이 아니다. 그 갈래의 측정 스파이크 폴더
`scripts/spikes/<갈래>/`도 같이 지운다 — 규칙과 절차는 [scripts/README.md](../scripts/README.md).
갈래 파일과 연구 문서는 남고, 코드는 `## 재현`의 git history 포인터가 대신한다.
`working-skeleton`은 status가 아니라 implementation 값이다.
