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
  },
  "actions": [
    {
      "id": "widen_radius",
      "label": "반경 4km로 넓히기",
      "kind": "edits",
      "source": "policy",       // policy | assistant. v0는 policy만 생성
      "edits": [{"tool": "set_radius", "args": {"m": 4000}}]
    }
  ]
}
```

`actions[]`는 실행 명령이 아니라 **사용자가 선택할 수 있는 제안**이다. 버튼 하나가 여러 편집을
묶을 수 있으므로 `edits[]`이며, 누르면 기존 `/hospital/search` 요청의 `edits`로 그대로
돌아간다. 따라서 툴 검증·정책별 diff·턴 단위 undo를 새 엔진 없이 재사용한다.

v0는 결과 0곳 복구와 불명확한 질문의 선택지를 코드로만 조립한다. 전체 `reset`은 검색과
무관한 도보 제약까지 지우므로 제안하지 않고, 실제로 결과를 좁힌 조건만 구체적으로 푼다.
전화는 후보마다 대상이 다르므로 검색 전체 action이 아니라 결과 카드의 기본 행동이다.

대화 루프가 붙으면 추가될 필드 (탐색 중, `explorations/hospital-search/refine-loop.md`):
- `changes: string[]` — 이전 상태 대비 diff. **서버가 생성** (LLM 아님)
- `reply: string` — 한 줄 응답
- 결과별 `evidence: [{source, text, url}]` — 부스트 근거 (`community-search.md`)

구현: `app/features/hospital/api.py`, `app/features/hospital/actions.py`, `app/refine/actions.py`
