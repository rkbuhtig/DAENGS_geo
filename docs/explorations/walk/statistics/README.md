# 산책·점령 세션 통계

[산책 전체 입구](../README.md) · [공간 분포 통계](../spatial/README.md) · [점령 게임](../game/README.md)

기준 계획은 **[통계 working skeleton](activity-statistics-skeleton.md)**이다.
여기서는 산책·점령 세션 ID 연결, 원본의 수명, 확정 분석 선택과 보유 구간 재생을 다룬다.
셀로판의 공간 분포 계산은 공간 분석 입구에서 찾는다.

구현은 [app/features/activity_statistics](../../../../app/features/activity_statistics/),
검증은 [tests/activity_statistics](../../../../tests/activity_statistics/)에 있다.
실행·검증 명령과 S1~S3 결과는 [코어 계약](../../../contracts/activity-statistics-core.md)과
[PostgreSQL 저장·처리 계약](../../../contracts/activity-statistics-postgres.md)을 따른다.

Geo → DEV → APP 진행 범위는 기준 계획의 단계별 상태와 계약에서 확인한다.
[승격 원장](../../../promotion-ledger.toml)에 기록된 기준점은 실제 운영 채택 때만 갱신한다.
