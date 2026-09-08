"""Bounded data.go.kr collection; raw successful pages stay in a private cache.

No retry, redirect, implicit fetch, or exception URL logging. Provider query
coordinates/times are public synthetic experiment inputs in the checked-in run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scripts.spikes.storyboard_and_regions.sources import ENDPOINTS, SOURCE_PAGES, parse_page

from .record_envelopes import payload_hash

URLS = {**ENDPOINTS, "weather": (
    "https://apis.data.go.kr/1360000/AsosHourlyInfoService/getWthrDataList"
)}
PAGES = {**SOURCE_PAGES, "weather": "https://www.data.go.kr/data/15057210/openapi.do"}


class PublicDataReader:
    def __init__(self, cache: Path, *, fetch=False, refresh=False, key="",
                 max_requests=12, max_pages=3, client=None):
        if not 1 <= max_requests <= 30 or not 1 <= max_pages <= 6:
            raise ValueError("request/page limit outside experiment bounds")
        if refresh and not fetch:
            raise ValueError("refresh requires explicit fetch")
        self.cache, self.fetch, self.refresh, self.key = cache, fetch, refresh, key
        self.max_requests, self.max_pages = max_requests, max_pages
        self.client = client
        self.requests = 0
        self.memory = {}
        self.cache_hits = 0

    def read(self, source: str, query: dict) -> dict:
        identity = {"source": source, "query": query, "max_pages": self.max_pages,
                    "collector_version": "record-source-v1"}
        signature = payload_hash(identity)
        if signature in self.memory:
            return self.memory[signature]
        path = self.cache / f"{source}-{signature}.json"
        if path.exists() and not self.refresh:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            expected = receipt.pop("sha256")
            if payload_hash(receipt) != expected or receipt["identity"] != identity:
                raise ValueError("source cache integrity mismatch")
            receipt["sha256"] = expected
            self.cache_hits += 1
        else:
            receipt = self._fetch(identity)
            receipt["sha256"] = payload_hash(receipt)
            # Cache misses/budget skips are not durable failed provider responses.
            if receipt["status"] != "not_requested":
                self.cache.mkdir(parents=True, exist_ok=True)
                serialized = json.dumps(receipt, ensure_ascii=False, indent=2)
                archive = self.cache / "receipts" / f"{receipt['sha256']}.json"
                archive.parent.mkdir(exist_ok=True)
                if not archive.exists():
                    archive.write_text(serialized, encoding="utf-8")
                path.write_text(serialized, encoding="utf-8")
        self.memory[signature] = receipt
        return receipt

    def _fetch(self, identity):
        source, query = identity["source"], identity["query"]
        receipt = {"identity": identity, "endpoint": URLS[source], "source_url": PAGES[source],
                   "retrieved_at": None, "status": "not_requested", "reason": None,
                   "pages": [], "rows": [], "reported_total": None}
        if not self.fetch:
            receipt["reason"] = "cache_missing"
            return receipt
        if not self.key:
            receipt["reason"] = "credential_missing"
            return receipt
        if self.requests >= self.max_requests:
            receipt["reason"] = "request_budget_exhausted"
            return receipt
        owned = self.client is None
        client = self.client or httpx.Client(timeout=20, follow_redirects=False)
        receipt.update(status="unavailable", retrieved_at=datetime.now(UTC).isoformat())
        seen = set()
        try:
            for page in range(1, self.max_pages + 1):
                if self.requests >= self.max_requests:
                    receipt.update(status="partial", reason="request_budget_exhausted")
                    break
                params = {**query, "pageNo": page, "numOfRows": 1000, "serviceKey": self.key}
                params["dataType" if source == "weather" else "type"] = "JSON" if source == "weather" else "json"
                self.requests += 1
                response = client.get(URLS[source], params=params)
                # Only fixed reason codes leave this function; response errors may echo credentials.
                if response.status_code != 200:
                    receipt["reason"] = f"http_{response.status_code}"
                    break
                body = response.json()
                code, rows, total = parse_page(body)
                if code not in {"00", "03"}:
                    receipt["reason"] = "provider_rejected"
                    break
                # Even successful response text must not copy the supplied credential to disk.
                serialized = json.dumps(body, ensure_ascii=False)
                if self.key and self.key in serialized:
                    receipt["reason"] = "credential_echo_rejected"
                    break
                receipt["pages"].append({"page": page, "body": body, "sha256": payload_hash(body)})
                signature = payload_hash({"rows": rows})
                if rows and signature in seen:
                    receipt.update(status="partial", reason="repeated_page")
                    break
                seen.add(signature)
                if receipt["reported_total"] is not None and total != receipt["reported_total"]:
                    receipt.update(status="partial", reason="total_changed")
                    break
                receipt["reported_total"] = total
                receipt["rows"].extend(rows)
                if len(receipt["rows"]) == total:
                    receipt.update(status="known" if total else "empty", reason=None)
                    break
                if not rows or len(receipt["rows"]) > total:
                    receipt.update(status="partial", reason="pagination_mismatch")
                    break
            else:
                receipt.update(status="partial", reason="page_budget_exhausted")
        except httpx.HTTPError:
            receipt["reason"] = "transport_failed"
        except (ValueError, KeyError, TypeError):
            receipt["reason"] = "invalid_provider_response"
        finally:
            if owned:
                client.close()
        if receipt["rows"] and receipt["status"] == "unavailable":
            receipt["status"] = "partial"
        return receipt
