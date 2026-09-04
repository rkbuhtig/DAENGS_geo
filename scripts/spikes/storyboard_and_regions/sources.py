"""Explicit, bounded public-data collection. Credentials never enter receipts or errors.

Uses the user-authorized data.go.kr services. Reading a cache never makes network calls.
Successful zero results, incomplete pagination, and provider failure stay distinct.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote

import httpx

ENDPOINTS = {
    "commerce": "https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius",
    "parks": "https://api.data.go.kr/openapi/tn_pubr_public_cty_park_info_api",
    "rivers": "https://api.data.go.kr/openapi/tn_pubr_public_river_info_api",
}
SOURCE_PAGES = {
    "commerce": "https://www.data.go.kr/data/15012005/openapi.do",
    "parks": "https://www.data.go.kr/data/15012890/standard.do",
    "rivers": "https://www.data.go.kr/data/15139206/standard.do",
}


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def service_key(env_file: Path | None = None) -> str:
    value = os.environ.get("DAENGS_DATA_GO_KR_SERVICE_KEY", "")
    if not value and env_file and env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("DAENGS_DATA_GO_KR_SERVICE_KEY="):
                value = line.split("=", 1)[1].strip()
    if not value:
        raise ValueError("Set DAENGS_DATA_GO_KR_SERVICE_KEY or provide a private --env-file")
    # The portal supplies encoded or decoded keys. httpx applies the one wire encoding.
    return unquote(value)


def parse_page(data: dict) -> tuple[str, list[dict], int]:
    if not isinstance(data, dict):
        raise TypeError("invalid response root")
    root = data.get("response", data)
    if not isinstance(root, dict) or not isinstance(root.get("header"), dict):
        raise TypeError("invalid response header")
    code = str(root.get("header", {}).get("resultCode", "missing"))
    if code == "03":
        return code, [], 0
    if code != "00":
        return code, [], 0
    body = root.get("body")
    if not isinstance(body, dict):
        raise TypeError("missing body")
    items = body.get("items", []) or []
    if isinstance(items, dict):
        items = items.get("item", []) or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
        raise ValueError("invalid item shape")
    total = int(body["totalCount"])
    if total < 0:
        raise ValueError("negative total")
    return code, items, total


def collect(
    source: str, params: dict, *, key: str, cache_dir: Path,
    refresh: bool = False, client: httpx.Client | None = None, max_pages: int = 12,
) -> dict:
    endpoint = ENDPOINTS[source]
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{source}-{fingerprint(params)[:16]}.json"
    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    result = {
        "source": source, "source_url": SOURCE_PAGES[source], "endpoint": endpoint,
        "query": params, "captured_at": datetime.now(UTC).isoformat(),
        "status": "fetch_failed", "rows": [], "pages": 0, "reported_total": None,
        "page_fingerprints": [], "failure": None,
    }
    owned = client is None
    transport = client or httpx.Client(timeout=25, follow_redirects=False)
    seen_pages = set()
    try:
        for page in range(1, max_pages + 1):
            # Never call raise_for_status/log the request: query contains the secret.
            response = transport.get(endpoint, params={
                **params, "pageNo": page, "numOfRows": 1000, "type": "json", "serviceKey": key,
            })
            result["pages"] += 1
            if response.status_code != 200:
                result["failure"] = f"http_{response.status_code}"
                break
            code, rows, total = parse_page(response.json())
            if code not in {"00", "03"}:
                result["failure"] = "provider_rejected"
                break
            result["page_fingerprints"].append(hashlib.sha256(response.content).hexdigest())
            page_signature = fingerprint(rows)
            if rows and page_signature in seen_pages:
                result["status"] = "partial"
                result["failure"] = "repeated_page"
                break
            seen_pages.add(page_signature)
            if result["reported_total"] is not None and total != result["reported_total"]:
                result["status"] = "partial"
                result["failure"] = "total_changed_during_pagination"
                break
            result["reported_total"] = total
            result["rows"].extend(rows)
            if len(result["rows"]) == total:
                result["status"] = "known"
                break
            if not rows or len(result["rows"]) > total:
                result["status"] = "partial"
                result["failure"] = "pagination_mismatch"
                break
        else:
            result["status"] = "partial"
            result["failure"] = "page_budget_exhausted"
    except (ValueError, KeyError, TypeError):
        result["status"] = "parse_failed"
        result["failure"] = "invalid_provider_response"
    except httpx.HTTPError:
        result["failure"] = "transport_failed"
    finally:
        if owned:
            transport.close()
    if result["rows"] and result["status"] == "fetch_failed":
        result["status"] = "partial"
    result["snapshot_fingerprint"] = fingerprint(result)
    # Response bodies can contain provider contact info: this cache is local, not committed.
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def collect_defaults(cache_dir: Path, key: str, *, refresh: bool = False) -> dict:
    out = {}
    for source, params in (
        ("parks", {"instt_nm": "서울특별시 강남구"}),
        ("rivers", {}),
        ("commerce", {"cx": 127.052, "cy": 37.487, "radius": 1200}),
    ):
        out[source] = collect(source, params, key=key, cache_dir=cache_dir, refresh=refresh)
    return out


def collect_water_geometry(cache_dir: Path, *, refresh: bool = False) -> dict:
    """Supplementary EGIS geometry, explicitly separate from the river standard dataset."""
    from pyproj import Transformer

    path = cache_dir / "egis-water-receipt.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    x, y = Transformer.from_crs(4326, 3857, always_xy=True).transform(127.052, 37.487)
    params = {
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
        "typeNames": "me:adm_river", "outputFormat": "application/json", "count": 300,
        "srsName": "EPSG:3857",
        "bbox": f"{x-3000},{y-3000},{x+3000},{y+3000},urn:ogc:def:crs:EPSG::3857",
    }
    receipt = {"source": "EGIS 하천 경계", "source_url": "https://egis.me.go.kr/",
               "endpoint": "https://api.mcee.go.kr/geoserver/wfs", "query": params,
               "captured_at": datetime.now(UTC).isoformat(), "status": "fetch_failed",
               "features": []}
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(receipt["endpoint"], params=params)
        if response.status_code == 200:
            payload = response.json()
            features = payload["features"]
            if isinstance(features, list):
                receipt["features"] = features
                receipt["status"] = "known" if len(features) < 300 else "partial"
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    receipt["snapshot_fingerprint"] = fingerprint(receipt)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    return receipt
