"""Project saved Kakao geography responses, retaining query scope and source dates."""

from app.features.territory.dwell import metres_between

from .contracts import Piece
from .storage import digest


def project_snapshots(snapshots: list[dict], anchors: list[dict], match_m: float) -> list[Piece]:
    pieces = []
    for snapshot in snapshots:
        query = snapshot.get("query", {})
        centre = (float(query["y"]), float(query["x"]))
        related = [
            {
                "anchor_id": a["id"],
                "distance_to_query_centre_m": metres_between((a["lat"], a["lng"]), centre),
            }
            for a in anchors
            if metres_between((a["lat"], a["lng"]), centre) <= match_m
        ]
        if not related:
            continue
        status = "cached_response" if snapshot.get("http_status") == 200 else "source_failed"
        documents = snapshot.get("data", {}).get("documents", [])
        meta = snapshot.get("data", {}).get("meta", {})
        value = {
            "query_centre": {"lat": centre[0], "lng": centre[1]},
            "query_radius_m": query.get("radius"),
            "provider_meta": meta,
            "returned_document_count": len(documents),
        }
        if "coord2address" in snapshot.get("endpoint", ""):
            value["addresses"] = [
                {
                    "address": (d.get("address") or {}).get("address_name"),
                    "road_address": (d.get("road_address") or {}).get("address_name"),
                    "building_name": (d.get("road_address") or {}).get("building_name"),
                }
                for d in documents
            ]
        else:
            value["category_group_code"] = query.get("category_group_code")
            value["facilities"] = [
                {
                    "id": d["id"],
                    "name": d["place_name"],
                    "category": d.get("category_name"),
                    "point": {"lat": float(d["y"]), "lng": float(d["x"])},
                    "provider_distance_to_query_centre_m": d.get("distance"),
                }
                for d in documents
            ]
            if status == "cached_response" and meta.get("is_end") is False:
                status = "partial_cached_response"
        pieces.append(
            Piece(
                id="env-" + snapshot["name"],
                kind="environment",
                session_links={"anchors": related},
                value=value,
                meaning="저장된 지도 공급자 응답. 공간 범위는 원래 질의 중심·반경이다. "
                "연결된 관측점의 정확한 주소·시설 방문·현재 영업·동반 허용·산책 당시 환경을 "
                "보장하지 않는다. 조회 시각과 원천 상태를 함께 읽는다.",
                provenance={
                    "endpoint": snapshot["endpoint"],
                    "query": {
                        k: query[k]
                        for k in ("x", "y", "radius", "category_group_code", "page", "size", "sort")
                        if k in query
                    },
                    "fetched_at": snapshot["fetched_at"],
                    "recorded_response_sha256": snapshot.get("response_sha256"),
                    "cached_snapshot_sha256": digest(snapshot),
                },
                measurement_status=status,
            )
        )
    covered = {r["anchor_id"] for p in pieces for r in p.session_links["anchors"]}
    for anchor in anchors:
        if anchor["id"] not in covered:
            pieces.append(
                Piece(
                    id="env-missing-" + anchor["id"],
                    kind="environment",
                    session_links={"anchor_id": anchor["id"]},
                    value={"reason": "설정한 연결 거리 안에 저장된 환경 질의가 없음"},
                    meaning="시설이 없다는 결과가 아니라 이 실험에 연결할 환경 자료가 없음.",
                    provenance={"environment_match_m": match_m},
                    measurement_status="no_source",
                )
            )
    return pieces
