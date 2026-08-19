# 검색 응답 계약

클라이언트(웹·앱·챗봇 카드)가 공통으로 받는 형태. 세 필드는 **같은 `results` 하나에서 파생**된다 — 텍스트·카드·지도가 어긋날 수 없게.

```jsonc
{
  "params":  { "lat", "lng", "radius_m", "kind", "open_now", "night", "limit", "at" },
  "results": [
    { "id", "kind", "name", "lat", "lng", "distance_m",
      "open_now",            // true | false | null(미상) — 미상은 제외하지 않고 표시
      "hours_today", "is_night", "is_24h", "phone", "address" }
  ],
  "map": {
    "preview_url": "정적 지도 (프록시 경로) | null",
    "deeplink":    "daengs://map?lat=..&lng=..&filter=..&ids=..",   // 조건 + 강조 id. 결과 자체 아님
    "web_url":     "https://.../map?..."
  }
}
```

대화 루프가 붙으면 추가될 필드 (탐색 중, `explorations/hospital-search/refine-loop.md`):
- `changes: string[]` — 이전 상태 대비 diff. **서버가 생성** (LLM 아님)
- `reply: string` — 한 줄 응답
- 결과별 `evidence: [{source, text, url}]` — 부스트 근거 (`community-search.md`)

구현: `app/geo/schemas.py`
