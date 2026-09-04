"""Local SGIS boundaries and ordered, gap-preserving route attribution.

Optional geometry packages are loaded at invocation, never at script import time.
SGIS codes stay in their own namespace; they are not MOIS administrative codes.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from itertools import pairwise
from pathlib import Path


class Regions:
    def __init__(self, records: list[dict], receipt: dict):
        from pyproj import Transformer
        from shapely.geometry import shape

        self.forward = Transformer.from_crs(4326, 5179, always_xy=True).transform
        self.reverse = Transformer.from_crs(5179, 4326, always_xy=True).transform
        self.records = records
        self.receipt = receipt
        self.polygons = [(row, shape(row["geometry"])) for row in records]
        if any(not polygon.is_valid for _, polygon in self.polygons):
            raise ValueError("Invalid boundary geometry; inspect the source before attribution")

    @classmethod
    def from_zip(cls, path: Path) -> Regions:
        import shapefile
        from pyproj import CRS

        with zipfile.ZipFile(path) as archive:
            stem = next(n[:-4] for n in archive.namelist() if n.endswith(".shp"))
            source_crs = CRS.from_wkt(archive.read(stem + ".prj").decode())
            # This SGIS delivery uses the ESRI alias of Korea 2000 Unified (UTM-K).
            if not any(source_crs.equals(CRS.from_user_input(crs), ignore_axis_order=True)
                       for crs in ("EPSG:5179", "ESRI:102080")):
                raise ValueError("Expected SGIS EPSG:5179, not an unverified CRS")
            encoding = archive.read(stem + ".cpg").decode().strip()
            reader = shapefile.Reader(
                **{ext: io.BytesIO(archive.read(stem + "." + ext))
                   for ext in ("shp", "shx", "dbf")}, encoding=encoding,
            )
            records = []
            for item in reader.iterShapeRecords():
                props = item.record.as_dict()
                records.append({
                    "id": "sgis:" + props["ADM_CD"], "name": props["ADM_NM"],
                    "base_date": props["BASE_DATE"], "geometry": item.shape.__geo_interface__,
                })
        return cls(records, {
            "source": "SGIS 센서스용 행정구역경계(읍면동)",
            "source_url": "https://sgis.mods.go.kr/view/pss/openDataIntrcn",
            "crs": "EPSG:5179", "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "base_dates": sorted({r["base_date"] for r in records}), "count": len(records),
        })

    def locate(self, lng: float, lat: float, accuracy_m: float = 0) -> dict:
        from shapely.geometry import Point

        point = Point(self.forward(lng, lat))
        hits = [row for row, polygon in self.polygons if polygon.covers(point)]
        near = any(polygon.boundary.distance(point) <= accuracy_m
                   for _, polygon in self.polygons)
        status = "known" if len(hits) == 1 and not near else "boundary_uncertain"
        if not hits:
            status = "outside_coverage"
        return {"status": status, "regions": [{"id": r["id"], "name": r["name"]}
                                               for r in hits]}

    def ordered_runs(self, segments, started_at) -> list[dict]:
        """Partition each canonical segment, never bridge missing/invalid observations.

        Polygon-edge intersection is exact in projected coordinates. Within-segment time is
        linearly interpolated. Accuracy bands are conservative at segment midpoint; this is
        an experimental chapter heuristic, not a GPS uncertainty model or game adjudicator.
        """
        from shapely.geometry import LineString, Point

        out: list[dict] = []
        for segment in segments:
            line = LineString([self.forward(segment.a.lng, segment.a.lat),
                               self.forward(segment.b.lng, segment.b.lat)])
            if line.length < 0.001:
                cuts = [0.0, 1.0]
            else:
                distances = [0.0, 1.0]
                for _, polygon in self.polygons:
                    if not polygon.intersects(line):
                        continue
                    crossing = line.intersection(polygon.boundary)

                    def add(geom, line=line, distances=distances):
                        if geom.is_empty:
                            return
                        if hasattr(geom, "geoms"):
                            for child in geom.geoms:
                                add(child)
                        else:
                            for coord in geom.coords:
                                distances.append(line.project(Point(coord)) / line.length)

                    add(crossing)
                cuts = sorted(set(distances))
            for lo, hi in pairwise(cuts):
                if hi - lo < 1e-9:
                    continue
                middle = line.interpolate((lo + hi) / 2, normalized=True)
                lng, lat = self.reverse(middle.x, middle.y)
                match = self.locate(lng, lat, max(segment.a.accuracy_m or 0,
                                                segment.b.accuracy_m or 0))
                begin = (segment.a.at - started_at).total_seconds() + segment.dt * lo
                end = begin + segment.dt * (hi - lo)
                run = {**match, "start_s": begin, "end_s": end,
                       "distance_m": segment.dist * (hi - lo), "chain": segment.chain_index,
                       "focus": [lng, lat]}
                if (out and out[-1]["regions"] == run["regions"]
                        and out[-1]["status"] == run["status"]
                        and out[-1]["chain"] == run["chain"]
                        and abs(out[-1]["end_s"] - begin) < 1e-6):
                    out[-1]["end_s"] = end
                    out[-1]["distance_m"] += run["distance_m"]
                else:
                    out.append(run)
        return out

    def display_features(self, bounds: tuple[float, float, float, float]) -> list[dict]:
        from shapely.geometry import box, mapping
        from shapely.ops import transform

        west, south, east, north = bounds
        window = box(*self.forward(west, south), *self.forward(east, north))
        return [{"type": "Feature", "properties": {k: r[k] for k in ("id", "name")},
                 "geometry": mapping(transform(self.reverse,
                                               p.intersection(window).simplify(3)))}
                for r, p in self.polygons if p.intersects(window)]
