# 산책 일기·장면·기억

[산책 전체 입구](../README.md) · [공간 분석](../spatial/README.md)

작업 재개는 **[일기 제작 계획](plan.md)**에서 시작한다.
입력의 값·계산 정의·확보 범위와 공간 경향 추출 정책은 **[자료 카탈로그](evidence-catalog.md)**를 읽는다.

[LLM층 아키텍처 초안](llm-architecture.md)은 전체 구성·장면 작성·주장 검증의 책임과
실행/지도/편집 계약을 제안한다. 설계 단계이며 기존 제작 계획과 실험 결과를 연결한다.

[장면 중심 생성과 공통 배경 조립](scene-pipeline.md)이 현재 구현 경로다.
사용자 기록만으로 중심을 만들고, [부족분 보충 정책](action-background.md)에 따라 관측 중심을 더한 뒤
두 출처에 같은 배경 조립기를 적용한다. 동선 없이도 기록은 보존되며 위치가 있으면 저장된 공간·날씨 응답을 붙일 수 있다.
Geo 오프라인 어댑터와 저장·재생까지 구현했고, 실제 provider 수집과 LLM 작성 연결은 후속 작업이다.
[스탬프 생성 툴과 카드 소비 경계](stamp-tool.md)는 공통 조회·저장 인터페이스와 앞선 기록형 정책을 설명한다.
카드는 스탬프 버전을 참조한다. 아래 HOW 조립·작성 비교는 이전 정책의 보존 실험이다.
[HOW 움직임 재료](how-materials.md)는 정제된 동선에서 체류·직선·큰 회전·되짚기 후보를 계산한다.
[HOW 스탬프 조립](how-stamps.md)은 같은 동선에 사진·메모를 다르게 놓아 중심과 맥락을 구성한 후속 오프라인 실험이다.
[작성용 조각 투영](how-writing.md)은 같은 스탬프를 고정해 전체 입력과 짧은 딕셔너리를 비교한다. 모델 호출 없이 입력 크기·연결 보존을 확인했다.
후속 [실제 HOW 작성 A/B](../../../research/2026-09-08-how-writing-gemini.md)는 6회 호출에서 입력 토큰 61.6% 감소와 구조 통과 6/6을 확인했다. 기록 시각·움직임 순서·문체 문제는 남았으며 원본 출력과 별도 검토 메모를 보존했다.
실제 수집·이동 전환 어댑터와 운영 작성 연결은 아직 남아 있다.
[LLM층 청사진](llm-blueprint.md)은 앞선 구성 비교의 단계·조건·완료 기준을 보존한다.
첫 [실제 구성 A/B 결과](../../../research/2026-09-08-event-scene-gemini-ab.md)는 구조 통과 0/6이었다. 지도 검토 전에 모드별 출력 스키마와 시스템의 시각 복원 계약부터 개선한다.
후속 [ID 기반 계약과 실제 2차 비교](../../../research/2026-09-08-event-scene-gemini-ab-v2.md)에서 이를 구현해 3/6이 구조를 통과했다. 남은 실패는 생략·제목 참조 모순과 GPS 공백을 넘는 맥락 연결이다. 편집 품질과 문구의 사실성 승인은 별도다.
이후 [슬롯·스탬프 전처리 실험](../../../research/2026-09-08-slot-stamp-gemini.md)은 공간·액션 후보를 분리하고 시스템이 찍은 스탬프를 선택·서술했다. 6회 구조 통과와 세 조건의 짧은 카드 결과를 보존했으며, 반복 선정과 의미 과장은 남았다.

셀로판 UI에서 공공 공간 조각·Gemini 1~3차로 이어진 별도 로컬 실험은
[2026-09-07 종합 보고서](../../../research/2026-09-07-walk-diary-experiment-report.md)에 있다.
실제 입출력·실패 사례·설계 판단을 보존한 문서이며, 위 제작 계획 전체의 구현이나 제품 채택 선언은 아니다.

| 탐색 | 문서 |
|---|---|
| 행동·글·사진과 주변 API 봉투 | [기록·봉투 계약](record-envelopes.md), [수집 실험](record-envelope-collection.md) |
| 동네 구간과 장면 재료 | [스토리보드와 구간](storyboard-and-regions.md) |
| 순서 있는 일기 경로와 보호 경계 | [일기 동선](walk-diary-route.md) |
| 관찰 증언과 의미 판단 | [행동 책갈피](behavior-anchor.md), [미시 판정](micro-judgment.md) |
| 기억 구조의 배경 | [기억 엔진](memory-engine.md) |
| 행동 Pin에서 개인화로 | [행동 프로필·개인화](behavior-profile-and-personalization.md) |
| 보류한 산책 루프 | [루프와 밸런스](loop-and-balance.md) |

LLM 실험의 실행·검토·재개 명령은 [diary_storyboard 안내](../../../../scripts/spikes/diary_storyboard/README.md),
지역 장면 비교는 [storyboard_and_regions 안내](../../../../scripts/spikes/storyboard_and_regions/README.md)에 있다.
재사용 구현은 [storyboard](../../../../app/features/storyboard/)와
[spatial_diary](../../../../app/features/spatial_diary/)에서 찾는다.

제품 연결은 [실데이터 이식 계약](../../../contracts/walk-storyboard-live.md),
[장면 교환 v2](../../../contracts/walk-storyboard-candidates-v2.md),
[결정 #74](../../../decisions/2026-09-01-spatial-diary.md), [승격 원장](../../../promotion-ledger.toml)을 따른다.
실행 결과는 [골격](../../../research/2026-09-06-diary-storyboard-skeleton.md),
[계산 입력](../../../research/2026-09-06-diary-geo-observed-inputs.md),
[근거 대조 비교](../../../research/2026-09-06-diary-claim-comparison.md)에 남긴다.
