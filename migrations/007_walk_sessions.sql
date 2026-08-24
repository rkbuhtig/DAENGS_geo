-- 산책 수집 코어. 계약은 docs/contracts/walk-record.md — 사실만, 판정·서술 없음.
--
-- walk_fix 는 **세션 진행 중에만** 존재한다. finish 가 사실을 계산하고 나면 그 자리에서
-- 지운다. 궤적 영구 보관은 프라이버시 정책(절삭·보관 기간)이 서기 전까지 하지 않는다 —
-- 시작·종료 좌표는 집 주소다. 삭제는 영구 방침이 아니라 정책 결정 전의 안전 기본값이다.

CREATE TABLE IF NOT EXISTS walk_session (
    id             TEXT PRIMARY KEY,          -- 클라이언트 생성(UUID). 오프라인 시작 + 멱등 재전송
    dog_id         TEXT NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL,
    ended_at       TIMESTAMPTZ,               -- NULL = 진행 중
    fix_count      INTEGER NOT NULL DEFAULT 0,  -- 수신 원본 수 (거부 포함)
    mock_fix_count INTEGER NOT NULL DEFAULT 0,  -- 재생·가짜 위치 수. 사실이 아니라 운영 표식
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS walk_session_dog_idx ON walk_session (dog_id, started_at);

CREATE TABLE IF NOT EXISTS walk_fix (
    session_id TEXT NOT NULL REFERENCES walk_session (id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,              -- 수신 순서. 측정 시각(at)과 둘 다 보존한다
    at         TIMESTAMPTZ NOT NULL,
    lat        DOUBLE PRECISION NOT NULL,
    lng        DOUBLE PRECISION NOT NULL,
    accuracy_m REAL,
    is_mock    BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (session_id, seq)
);

CREATE TABLE IF NOT EXISTS walk_facts (
    session_id        TEXT PRIMARY KEY REFERENCES walk_session (id) ON DELETE CASCADE,
    record_version    INTEGER NOT NULL,
    dog_id            TEXT NOT NULL,
    started_at        TIMESTAMPTZ NOT NULL,
    ended_at          TIMESTAMPTZ NOT NULL,
    duration_s        INTEGER NOT NULL,
    distance_m        INTEGER NOT NULL,
    moving_distance_m INTEGER NOT NULL,
    moving_s          INTEGER NOT NULL,
    stop_count        INTEGER NOT NULL,
    stop_s            INTEGER NOT NULL,
    avg_speed_mps     DOUBLE PRECISION,     -- REAL 은 왕복에서 값이 변한다 (1.398 → 1.3980000019)
    fix_count         INTEGER NOT NULL,
    quality           JSONB NOT NULL,         -- 수신/수용/거부 사유별 계수. 계약 밖 운영 데이터
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
