"""점령 게임 — 산책 사실을 소비하는 독립 기능 경계.

중립 점령지 읽기 계약, 게임 정책·트랜잭션 연결·PostgreSQL 저장과 DB 독립 시즌
규칙을 소유한다. 공간장·통계·조건별 읽기는 형제 features.territory가 맡고,
검토 HTTP·화면·SQLite 저장은 tools.territory_game이 맡는다.
실제 사진 검증과 회원 인증은 수행하지 않으며 로컬 게임 API를 운영 점유 API로
사용하지 않는다.
"""
