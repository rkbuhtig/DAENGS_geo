# 산책 점령·시즌 게임

[산책 전체 입구](../README.md) · [세션 통계](../statistics/README.md)

작업 재개는 **[게임 구현·이관 인수인계](territory-game-handoff.md)**에서 시작한다.

| 작업 | 기준 문서 |
|---|---|
| 지도·촬영부터 온라인 공유까지 제작 순서 | [제작 계획](territory-production-plan.md) |
| 현재 로컬 시즌 게임의 규칙·실행·검증 | [동네 강자 시즌 게임](territory-season-game.md) |
| 접촉·사진·증언·점령의 증거 경계 | [점령지 게임](territory-site-game.md) |
| 이전 정기 정산 가설과 비교 | [시즌 점수](territory-season-scoring.md) |

현재 구현은 [territory/game](../../../../app/features/territory/game/)에 있다.
검토 도구의 실행 조건은 [시즌 서버](../../../../scripts/spikes/territory_season/README.md)와
[지도·촬영 실험](../../../../scripts/spikes/territory_production_plan/README.md)을 따른다.

공용 입력 경계는 [결정 #84](../../../decisions/2026-09-03-canonical-trail-consumer-boundary.md),
연결·저장은 [정책 연결](../../../contracts/territory-policy-integration.md)과
[PostgreSQL 계약](../../../contracts/territory-policy-postgres.md)을 읽는다.
검증 결과와 DEV·APP 파일별 채택 범위는 인수인계 문서에서, 승격 기준 커밋은
[승격 원장](../../../promotion-ledger.toml)에서 확인한다.
