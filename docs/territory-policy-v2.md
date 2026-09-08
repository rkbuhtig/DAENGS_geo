# 인증 우선 점령 정책 v2

Rules 기본 version은 `certified-protection-v2`다. 명시적으로 저장된 `draft-2026-09-06`은
이전 획득 시각 보호/세션 제한을 그대로 재현한다. 알 수 없는 version은 거절한다.

미인증 owner는 보호하지 않고 사진 인증으로 즉시 탈취 가능하다. 인증 owner는
`certified_ms + 600000`까지 보호한다. 본인 미인증을 강화하면 occupied_ms는 유지하고
certified_ms를 인증 시점으로 기록한다. 보너스는 없으며 이미 인증한 본인 영역은 보호 연장 불가다.
0035 migration은 독립 PostgreSQL policy 테이블의 certified_ms를 추가하고 과거 VERIFIED를
occupied_ms로 backfill한다. 운영 요청/회원 인증/사진 challenge는 DEV #335가 담당한다.
기존 점유를 새 시즌으로 가져올 때 certified_ms가 없는 VERIFIED는 원래 occupied_ms로
인증 시각을 채운다. 점수용 occupied_ms를 시즌 시작으로 바꾸더라도 끝난 보호를 갱신하지 않는다.

로컬 Game은 v2에서 같은 산책/site attempt에 새 capture를 제출하여 다시 도전할 수 있다.
새 제출 때 현재 version과 보호를 확인하고 이전 capture 재사용을 금지한다. 기존 snapshot의
rules.version은 유지하며 구버전 시나리오는 테스트에서 version을 명시한다.

검증: territory_game, tools/territory_game/test_season_store.py, activity_statistics 범위.
새 v2 시나리오와 PostgreSQL 저장·10분 경계·동일 claim 재탈취·영수증 재전송을 포함한다.
