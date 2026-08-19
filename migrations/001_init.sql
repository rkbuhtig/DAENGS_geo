-- DAENGS_geo 초기 스키마. docker-compose 첫 기동 시 자동 실행.
CREATE EXTENSION IF NOT EXISTS postgis;

-- 병원/약국 POI. 원천은 공공데이터(지방행정 인허가). 제공사 로컬검색 결과 저장 금지.
CREATE TABLE IF NOT EXISTS place (
    id            BIGSERIAL PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('hospital', 'pharmacy')),
    name          TEXT NOT NULL,
    address       TEXT,
    phone         TEXT,
    location      geography(Point, 4326) NOT NULL,
    is_night      BOOLEAN NOT NULL DEFAULT FALSE,   -- 야간 진료 표방 (영업시간과 별개 플래그)
    is_24h        BOOLEAN NOT NULL DEFAULT FALSE,
    hours         JSONB,                             -- app/geo/hours.py 형식. NULL = 미상
    source        TEXT NOT NULL,                     -- 'public:localdata' 등
    source_id     TEXT,                              -- 원천 식별자 (중복 적재 방지)
    active        BOOLEAN NOT NULL DEFAULT TRUE,     -- 폐업 = FALSE
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS place_location_gix ON place USING GIST (location);
CREATE INDEX IF NOT EXISTS place_kind_idx     ON place (kind) WHERE active;
