-- 지오코딩으로 복구한 좌표의 출처를 남긴다.
--
-- 인허가 원천(행안부)은 CRD_INFO_X/Y 가 공란인 행이 있다. 영업중인데 좌표가 없으면
-- 반경 검색에 아예 안 잡혀서 "없는 병원"이 된다 (실측: 병원 316 · 약국 833곳).
-- 주소는 대부분 남아 있으므로 지오코딩으로 되살리는데, 좌표만 덮어쓰면 나중에
-- 잘못 찍힌 시설을 추적할 수 없다. 무엇을 질의해서 무엇에 매칭됐는지 같이 남긴다.
--
-- {
--   "provider":   "kakao",
--   "tier":       "road" | "road_stripped" | "lot" | "lot_stripped",
--   "query":      실제로 질의한 주소 문자열,
--   "matched":    제공사가 매칭한 주소,
--   "precision":  "ROAD_ADDR" | "REGION_ADDR" | "REGION",   -- REGION 은 동 단위라 오차 큼
--   "at":         처리 시각(ISO8601)
-- }
ALTER TABLE place ADD COLUMN IF NOT EXISTS geocode JSONB;

-- 정밀도가 낮은 행만 뽑아 검수할 수 있게. 지오코딩 안 한 행은 인덱스에 안 들어간다.
CREATE INDEX IF NOT EXISTS place_geocode_precision_idx
    ON place ((geocode ->> 'precision')) WHERE geocode IS NOT NULL;
