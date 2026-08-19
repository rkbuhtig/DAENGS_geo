-- name-tagging + 인허가 규모 지표
ALTER TABLE place ADD COLUMN IF NOT EXISTS tags        TEXT[]  NOT NULL DEFAULT '{}';
ALTER TABLE place ADD COLUMN IF NOT EXISTS area_m2     NUMERIC;      -- 인허가 면적 (규모 표시용)
ALTER TABLE place ADD COLUMN IF NOT EXISTS staff_count INTEGER;      -- 인허가 종사자수
CREATE INDEX IF NOT EXISTS place_tags_gin ON place USING GIN (tags);
