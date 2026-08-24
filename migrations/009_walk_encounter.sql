-- 동선 주변 시설 관측 — 기하값까지만. 판정("지나쳤다/봤다")은 소비자(app/scene)의 일.
-- 밴드 3개를 전부 저장하는 이유: 원좌표는 finish 에서 지워지므로, 판정 반지름을
-- 실측 후 정하려면 후보 반지름들의 답이 미리 계산돼 있어야 한다 (재계산 불가 보상).
-- 폐업·인허가 상태는 필터가 아니라 데이터다(place_active) — 관측층은 큐레이션하지 않는다.
CREATE TABLE IF NOT EXISTS walk_encounter (
    session_id       TEXT NOT NULL REFERENCES walk_session (id) ON DELETE CASCADE,
    event_index      INTEGER NOT NULL,
    facility_source  TEXT NOT NULL,
    facility_ref     TEXT NOT NULL,            -- 안정 키 (source, source_ref). facility.id 아님
    kind             TEXT NOT NULL,
    lat              DOUBLE PRECISION NOT NULL,  -- 시설 대표점 (공개 장소)
    lng              DOUBLE PRECISION NOT NULL,
    place_active     BOOLEAN,                  -- 의료 오버레이 상태. 비의료·미링크는 NULL
    as_of            DATE,
    min_lateral_m    DOUBLE PRECISION NOT NULL,
    offset_m         DOUBLE PRECISION NOT NULL,
    dwell_s_10m      INTEGER NOT NULL,
    dwell_s_30m      INTEGER NOT NULL,
    dwell_s_50m      INTEGER NOT NULL,
    pass_count       INTEGER NOT NULL,
    stop_overlap_10m BOOLEAN NOT NULL,
    stop_overlap_30m BOOLEAN NOT NULL,
    stop_overlap_50m BOOLEAN NOT NULL,
    stop_s_10m       INTEGER NOT NULL DEFAULT 0,
    accuracy_p50_m   REAL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, event_index)
);
CREATE INDEX IF NOT EXISTS walk_encounter_facility_idx
    ON walk_encounter (facility_source, facility_ref);
