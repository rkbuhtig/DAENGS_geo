-- 시설별 세션 합계(v1)를 연속 진입 occurrence(v2)로 바꾼다.
-- 기존 v1 행은 원좌표가 이미 삭제돼 분할할 수 없으므로 occurrence_version=1로 남긴다.
ALTER TABLE walk_encounter
    ADD COLUMN IF NOT EXISTS occurrence_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS occurrence_index INTEGER,
    ADD COLUMN IF NOT EXISTS entered_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS exited_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS entry_observed BOOLEAN,
    ADD COLUMN IF NOT EXISTS exit_observed BOOLEAN,
    ADD COLUMN IF NOT EXISTS entered_offset_m DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS exited_offset_m DOUBLE PRECISION;

DO $$ BEGIN
    ALTER TABLE walk_encounter ADD CONSTRAINT walk_encounter_occurrence_version_check
        CHECK (occurrence_version >= 1);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE walk_encounter ADD CONSTRAINT walk_encounter_occurrence_v2_check
        CHECK (
            occurrence_version < 2 OR (
                occurrence_index IS NOT NULL AND occurrence_index >= 0
                AND entered_at IS NOT NULL AND exited_at IS NOT NULL
                AND entered_at <= exited_at
                AND entry_observed IS NOT NULL AND exit_observed IS NOT NULL
                AND entered_offset_m IS NOT NULL AND entered_offset_m >= 0
                AND exited_offset_m IS NOT NULL AND exited_offset_m >= entered_offset_m
                AND pass_count = 1
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS walk_encounter_occurrence_uidx
    ON walk_encounter (session_id, facility_source, facility_ref, occurrence_index)
    WHERE occurrence_version >= 2;
