# 산책 일기·장면·기억

[산책 전체 입구](../README.md) · [공간 분석](../spatial/README.md)

작업 재개는 **[일기 제작 계획](plan.md)**에서 시작한다.
입력의 값·계산 정의·확보 범위와 공간 경향 추출 정책은 **[자료 카탈로그](evidence-catalog.md)**를 읽는다.

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
