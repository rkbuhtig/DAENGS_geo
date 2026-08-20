-- 행정안전부 동물병원/동물약국 OpenAPI 동기화 메타데이터.
ALTER TABLE place ADD COLUMN IF NOT EXISTS source_updated_at   TIMESTAMPTZ;
ALTER TABLE place ADD COLUMN IF NOT EXISTS license_status_code TEXT;
ALTER TABLE place ADD COLUMN IF NOT EXISTS license_status_name TEXT;
ALTER TABLE place ADD COLUMN IF NOT EXISTS coordinate_source   TEXT;
ALTER TABLE place ADD COLUMN IF NOT EXISTS raw_data            JSONB;

CREATE INDEX IF NOT EXISTS place_source_updated_idx
    ON place (source, source_updated_at);

CREATE TABLE IF NOT EXISTS ingest_state (
    source      TEXT PRIMARY KEY,
    watermark   TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
