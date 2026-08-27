# 병원 대화 응답 계약

마지막 코드 대조: 2026-08-27.

공용 장소 발견은 [`POST /v2/places/search`](place-search-v2.md) 한 곳에서 `PlaceResult`를
반환한다. 과거 `GET /places/search`, `GET /pharmacy/search`, `GET /facility/search`가 반환하던
`SearchOut` HTTP 표면은 소비자 전환 뒤 제거했다. 내부 의료·시설 resolver는 canonical 검색과
아래 병원 대화 기능이 계속 사용한다.

## 기존 병원 검색·편집

`POST /hospital/search`는 병원 후보와 상태 편집, 추정 이동정보와 안전·복구 표면을 묶은
`HospitalSearchOut`을 반환한다. Android의 기존 병원 대화 화면이 아직 소비하므로 남아 있지만,
공용 장소 발견 입구로 새 소비자를 붙이지 않는다.

```jsonc
{
  "state": { "state_version": 4, "lat", "lng", "time_intent", "urgency",
             "target", "journey", "sort", "history" },
  "results": [
    { "...PlaceOut", "transport", "boost" }
  ],
  "map": { "preview_url", "deeplink", "web_url" },
  "changes": [],
  "changes_by_policy": { "context": [], "target": [], "journey": [], "view": [] },
  "applied": [],
  "question": null,
  "reply": "...",
  "resolution": [],
  "show_call_cta": false,
  "call_reasons": [],
  "actions": []
}
```

- `transport=estimate`가 기본이며 목록에서는 실제 provider를 호출하지 않는다. 실측은 목적지를
  선택한 뒤 `POST /journey`에서 요청한다.
- `resolution[]`은 서버 사실이 사용자 설정을 덮은 경우의 추적 정보다.
- `actions[]`는 자동 실행 명령이 아니라 사용자가 선택할 수 있는 `edits[]` 묶음이다.
- 자연어 refine 과 suggested actions 는 구현과 계약을 유지하지만 결정 #51 이후 제품 코어에서는
  parked다. 커뮤니티 근거(`evidence[]`)는 결정 #63 으로 계약에서 **제거**됐다 — parked 가 아니다.

구현: `app/geo/schemas.py`, `app/features/hospital/api.py`,
`app/features/hospital/actions.py`, `app/discovery/refine/actions.py`.
