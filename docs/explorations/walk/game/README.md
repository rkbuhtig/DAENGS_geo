# 산책 점령·시즌 게임

[산책 전체 입구](../README.md) · [세션 통계](../statistics/README.md)

작업 재개는 **[게임 구현·이관 인수인계](territory-game-handoff.md)**에서 시작한다.

| 작업 | 기준 문서 |
|---|---|
| 지도·촬영부터 온라인 공유까지 제작 순서 | [제작 계획](territory-production-plan.md) |
| 현재 로컬 시즌 게임의 규칙·실행·검증 | [동네 강자 시즌 게임](territory-season-game.md) |
| 접촉·사진·증언·점령의 증거 경계 | [점령지 게임](territory-site-game.md) |
| 동네 순위·칭호의 미구현 검토 초안 | [순위·칭호 계약 초안](../../../contracts/territory-ranking-titles.md) |
| 이전 정기 정산 가설과 비교 | [시즌 점수](territory-season-scoring.md) |

공용 게임 구현은 [territory_game](../../../../app/features/territory_game/)이 소유한다.
공간장·조건별 공간 읽기는 형제 `features/territory`, 통계 연결은 `features/activity_statistics`,
검토 HTTP·화면·SQLite는 [tools/territory_game](../../../../tools/territory_game/)이 맡는다.
게임 정책·PostgreSQL·순수 시즌 테스트는 [tests/territory_game](../../../../tests/territory_game/),
검토 저장·화면 테스트는 [tests/tools/territory_game](../../../../tests/tools/territory_game/)에 있다.
검토 도구의 실행 조건은 [시즌 서버](../../../../scripts/spikes/territory_season/README.md)와
[지도·촬영 실험](../../../../scripts/spikes/territory_production_plan/README.md)을 따른다.

공용 입력 경계는 [결정 #84](../../../decisions/2026-09-03-canonical-trail-consumer-boundary.md),
연결·저장은 [정책 연결](../../../contracts/territory-policy-integration.md)과
[PostgreSQL 계약](../../../contracts/territory-policy-postgres.md)을 읽는다.
검증 결과와 DEV·APP 파일별 채택 범위는 인수인계 문서에서, 승격 기준 커밋은
[승격 원장](../../../promotion-ledger.toml)에서 확인한다.
