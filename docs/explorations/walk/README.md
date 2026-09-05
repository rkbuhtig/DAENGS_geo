# 산책 — 탐색 갈래

**담당: 사용자.**

산책 점령 게임 제작은 [2026-09-05 제작 계획](territory-production-plan.md)을 먼저 읽는다.
사진 없는 점유와 인증 우선권을 반영한 최신 작업 기준이며, 첫 묶음은 지도·촬영·페이크 판정이다.

다른 컴퓨터/새 대화에서 이 작업을 이어받을 때는
[2026-09-04 인수인계](../../research/2026-09-04-walk-personalization-handoff.md)를 먼저 읽는다.
실제 스토리보드 실험과 아직 미구현인 행동 프로필 구상을 구분하고, 로컬 데이터 복구 방법을 안내한다.

수집 코어는 탐색이 아니라 사실 계약이다 — [`contracts/walk-record.md`](../../contracts/walk-record.md),
`app/features/walk/models.py`, `tests/test_walk_contract.py`. `WalkFacts` 자체에는 의미를 섞지 않는다.
다만 finalize 뒤에는 Capsule·Context Plane·Spatial Diary가 그 사실을 별도 수명과 권위 경계에서
소비한다. 파생 해석이나 사용자 증언을 다시 `WalkFacts`로 되밀지 않는 것이 현재 경계다.

`session-engine-draft`는 초기 세션 흐름과 소비자 아이디어를 함께 적었던 초안이다. 이후 수집 코어의
상당 부분(start/fixes/finish, Android foreground tracking, Room 원본 저장)은 구현됐고, 트리거·서술
절과 `loop-and-balance`는 산책 사실을 **소비하는 옵션**으로 parked다.

| 갈래 | status | implementation | 한 줄 |
|---|---|---|---|
| [territory-production-plan](territory-production-plan.md) | exploring | draft | 미인증 점유·인증 우선권·세션당 장소별 한 번을 기준으로 앱 한 사이클 → 온라인 공유 → 시즌·실제 판정 제작. 1·2단계 구현 PR과 검증 기록 연결 |
| [behavior-profile-and-personalization](behavior-profile-and-personalization.md) | exploring | none | 행동 Pin의 현재 증언을 상황별로 요약해 프로필과 다음 산책에 쓰는 후보. 귀속·분모·정정/삭제·근거 회수부터 실험 |
| [storyboard-and-regions](storyboard-and-regions.md) | exploring | working-skeleton | SGIS·상가·공원·하천과 합성 산책으로 로컬 스토리보드 비교. 지역 구간은 챕터 후보, 게임 성과는 독립 fixture. 운영 저장·나레이터는 미구현 |
| [memory-engine](memory-engine.md) | exploring | none | **왜 반복 체류 검출에서 기억 엔진으로 옮겼나.** M2 부정 결과 → 미시/거시 분리 → 공간적 일기장 → Walk Capsule 까지의 사슬. 원칙 10개는 아직 결정 아님 |
| [micro-judgment](micro-judgment.md) | exploring | none | **미시 판정층 — 결정 #7 의 확장.** 관측→통계→룰→escalation 4층. 룰은 발언 가능성을 판정하고, LLM 은 의미적 애매함만 받으며 출력은 편집층 전용. 문턱값은 실패 지도를 그린 뒤 |
| [behavior-anchor](behavior-anchor.md) | exploring | none | **행동 책갈피.** 일기를 쓰는 행위가 증언(attested)이 되고, 사건 단위 확정 문장은 증언에서만 나온다. 선택이지 전제가 아님 — 안 눌러도 전부 동작 |
| [session-engine-draft](session-engine-draft.md) | exploring | draft | 초기 start/locations/finish 흐름과 소비자 아이디어. 구현 현황은 Android README/계약이 더 최신 |
| [session-continuity-and-dwell](session-continuity-and-dwell.md) | exploring | partial | 이미 있는 pause/chain/unfinished-session 위에서 세션 연속성·복구·체류·territory 의미를 정리 |
| [territory-paint](territory-paint.md) | exploring | working-skeleton | 산책 점을 붓으로 지도를 칠한다. 산책 한 번 = 셀로판 한 장, 조건으로 골라 겹친다. §A(영구 형태)는 [결정 #69](../../decisions/2026-08-26-walk-permanent-spatial-form.md) 로 닫혔고 §B·§C 는 열려 있다 |
| [territory-site-game](territory-site-game.md) | proposed | working-skeleton | 검증된 산책 접촉 → 세션 내 촬영 → 비동기 VLM 판정 → 사용자 증언 → 유효 점령의 권위·안전 가설. 중립 점령지 읽기만 구현됨 |
| [territory-season-scoring](territory-season-scoring.md) | proposed | none | 현재 점령 상태를 정기 정산해 점령 점수를 누적하고, 단일 정산의 최대 동시 점령량을 정복 기록으로 따로 랭킹화한 뒤 시즌마다 초기화 |
| [cellophane-statistical-layer](cellophane-statistical-layer.md) | exploring | working-skeleton | **싸인펜 생성 연산 → 산책별 셀로판 표본 → z축 적층 → 통계 질의**를 분리한다. 방문률·총 시간·방문당 체류·두 이용 분포의 통계 코어는 구현됐고, 50·80·95% 영역과 Raw/Adjusted 집 편향, 실험 B/C는 열려 있다 |
| [continuous-brush-reference](continuous-brush-reference.md) | exploring | working-skeleton | 같은 canonical Segment를 연속 원 field와 Hex Cellophane에 넣는 독립 비교 기준선 |
| [simulator-core](simulator-core.md) | exploring | working-skeleton | latent truth와 제품 관측을 분리한 결정론적 산책·센서 시뮬레이터 |
| [android-replay-adapter](android-replay-adapter.md) | exploring | working-skeleton | 같은 observed capture를 Android replay JSON·GPX·ADB 시간축으로 변환하는 손실 명시 어댑터 |
| [cellophane-device-replay](cellophane-device-replay.md) | exploring | working-skeleton | Android export를 canonical Paint 경로에 재생하는 로컬·비커밋 검증 절차 |
| [repeated-dwell-area](repeated-dwell-area.md) | exploring | draft | **반복 체류 영역의 조작적 정의.** 의미어 없이 — 국소 적분 · 산책당 · 경로 대비. M2 이후 M3 의 첫 일은 문턱을 고르는 것이 아니라 **문턱을 걸 수 있는 지표를 찾는 것**이다 |
| [evidence-layer](evidence-layer.md) | exploring | draft | **원시 행동 → 판단 가능한 상태.** 사람과 AI 가 같은 근거 계약을 다른 표현으로 읽는다. 지도는 그 인간용 투영이고 맨 마지막이다 |
| [experience-scenario](experience-scenario.md) | exploring | draft | 저녁 산책 직전 화면 한 장. 셀로판이 기록·해석·행동 중 **어떤 가치를 만드는지** 가장 싼 형태로 검증한다. 금지 목록과 판정 기준이 여기 있다 |
| [speed-colored-trail](speed-colored-trail.md) | parked | none | **속도에 따른 세 단계 잉크색 동선.** 로컬 UX 방향은 GO지만 체류와 의미를 분리하고, 실제 속도 문턱·dev 시각화·장시간 렌더링 검증 전에는 구현하지 않는다 |
| [walk-diary-route](walk-diary-route.md) | exploring | dev-lab-spike | **단일 산책의 순서 있는 일기 선.** 앞뒤 거리 절단의 재방문 노출을 확인했고 공간 보호·단절·양자화 후보를 Lab에서 비교한다. 결정 #85에 따라 서버 영속은 아직 닫혀 있다 |
| [drawn-region](drawn-region.md) | parked | working | 사용자가 면을 그리고 그 안의 체류를 잰다. 붓 모델로 대체 — 5배 규칙은 남는다 |
| [loop-and-balance](loop-and-balance.md) | parked | none | 3단 루프 · 케어 밸런스. 데이터 수집 전에는 결정하지 않음 |

`territory-site-game`은 점령지에 접근하고 강아지 사진으로 서명해 **현재 점령을 바꾸기까지의
증거 경계**를 맡는다. `territory-season-scoring`은 그 현재 상태만 정기적으로 읽어 점령 점수의
합계와 정복 최고 기록을 만드는 **온라인 시즌 점수판**을 맡는다. 현재 온라인 가설은 연결망이나
포위 계산을 요구하지 않으며, 그것들은 개인형·후속 게임 후보로 보류한다.

`territory-paint`는 서버가 확정한 `Segment[]`를 소비해 공간을 칠하는 갈래다. 셀 격자는
`app/geo/cells.py`로 `territory_sites.py`·Android `LocalHexCellIndexer`와 공유한다. 무엇을 영구히
남길지는 [결정 #69](../../decisions/2026-08-26-walk-permanent-spatial-form.md)가 산책별 셀 맵으로
닫았다(칸마다 `occupancy`와 `peak`, 겹치기는 질의지 저장이 아니다). 남은 §B·§C는 그 위에서
무엇을 어떻게 읽을지다.

`cellophane-statistical-layer`는 그 “어떻게 읽을지”의 단계 경계를 고정한다. 싸인펜은
`Segment[] → occupancy·peak` 생성 연산, 셀로판은 산책별 영구 표본, 적층은 장 경계를 유지한
선택 집합, 통계층은 방문률·시간·조건부 체류·공간 이용 분포를 만드는 질의다. 같은 색의
진하기로 이 축들을 미리 접지 않으며, UI보다 통계 이름과 분모 계약을 먼저 만든다.

`memory-engine`은 이 갈래들이 **왜 한 번 흔들렸는지**를 남긴다. M2 대조군이 정답지를 이기면서
(`research/2026-08-27-latent-dwell-synthesis.md`) 문제가 검출기가 아니라 저장 경계였다는 쪽으로
옮겨갔고, 거기서 미시/거시 분리·Walk Capsule·진실성 층이 나왔다. 셀로판은 그 구조에서 **거시
기억판**으로 역할이 좁아지고, 미시는 셀로판이 아니라 사건 원장이 담당한다. 아직 결정이 아니므로
다른 갈래 문서는 이 문서로 자동으로 갱신되지 않는다 — 채택할 때 손댄다.

2026-09-01에 [결정 #74](../../decisions/2026-09-01-spatial-diary.md)가 이 탐색 전체가 아니라
제품 한 바퀴에 필요한 좁은 부분을 채택했다. Capsule manifest, 원시 MeasurementReceipt,
Candidate→Offer→Attestation→Pin 경계, Walk/Entry Selector 분리와 자동 Journal projection이 그
범위다. Place 형성 알고리즘·행동 어휘·나레이션·백업은 여전히 이 갈래의 열린 항목이다.

`session-continuity-and-dwell`은 이 수집/paint 사이의 **제품 의미**를 정리한다. 한 사용자 산책 안에
여러 client/derived continuity chain이 있을 수 있고, chain 사이 관측 공백은 붓으로 연결하지 않는다.
또 현재 `occupancy`가 이미 시간 가중 spatial exposure라는 점을 명시하고, 반복 방문(`walks`)·공간
노출(`occupancy`)·실제 정지 사건(dwell)을 하나의 "진함"으로 섞지 않는 방향을 검토한다.

병원 찾기 쪽에서 나온 것 중 산책에도 쓰이는 것: 반경 검색(`app/geo/search.py`), 단발 경로 스냅샷(`app/journey`).
대화로 조건 편집하는 루프(`../hospital-search/refine-loop.md`)는 parked — 편집할 조건이 없었다.
