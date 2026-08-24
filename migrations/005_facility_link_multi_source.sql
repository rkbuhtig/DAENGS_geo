-- 기반층 다원천화. facility는 원천별로 통째 교체하고(source 단위),
-- 링크는 특정 테이블 FK가 아니라 (source, source_ref) 쌍으로 어떤 원천이든 받는다.
ALTER TABLE facility ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'kcisa';
ALTER TABLE facility ADD COLUMN IF NOT EXISTS raw    JSONB;
CREATE INDEX IF NOT EXISTS facility_source_idx ON facility (source);

CREATE TABLE IF NOT EXISTS facility_link (
    facility_id BIGINT NOT NULL REFERENCES facility (id) ON DELETE CASCADE,
    source      TEXT NOT NULL,     -- 'mois:place'(의료 인허가) | 'facility'(원천 간 동일 시설) | 이후 원천
    source_ref  TEXT NOT NULL,     -- place.id / facility.id / 원천 고유키 — 문자열로 통일
    method      TEXT NOT NULL,
    distance_m  REAL,
    confidence  REAL,
    matched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (facility_id, source, source_ref)
);
CREATE INDEX IF NOT EXISTS facility_link_ref_idx ON facility_link (source, source_ref);

-- 기존 전용 링크 이전 후 폐기
INSERT INTO facility_link (facility_id, source, source_ref, method, distance_m, matched_at)
SELECT facility_id, 'mois:place', place_id::text, method, distance_m, matched_at
FROM facility_place_link
ON CONFLICT DO NOTHING;
DROP TABLE IF EXISTS facility_place_link;
