---
status: adopted
date: 2026-08-19
decision: ../../decisions/README.md #26 #27
---
# journey — "카드를 눌렀을 때" = 공용 이동 서비스

## 왜 분리했나 (사용자)
- 병원 검색 응답에 경로·spots·advice가 다 붙어 있어 "가이드용 지도치고 과하다". 무거운 건 검색이 아니라 **경로 계산이 검색 응답에 붙어 있는 것**
- 지도·경로는 공용으로 빼고, 병원 검색·약국·산책이 그 위에 얹히는 구조가 깔끔하다
- 약국은 대개 **사람 혼자** 간다 — 개 계수·노트가 붙으면 이상함 → `companion`

## 구조
```
app/
├── geo/        검색·영업시간·태깅              공용
├── journey/    route·spots·advice·companion   공용  ← POST /journey
├── providers/  tmap·kakao·naver·fake          공용
├── profile/    DogProfile 소비                 공용
└── features/
    ├── hospital/  refine 루프 + POST /hospital/search  (transport=estimate만, 호출 0)
    ├── pharmacy/  GET /pharmacy/search (얇음, companion 기본 none)
    └── walk/      사용자 담당
```

## companion
| | dog | none |
|---|---|---|
| 도보 시간 | 개 계수(1.2~2.0) × 제공사, `provider_min` 병기 | 제공사 원값 |
| 옵션 비교 | 골목 섞인 추천(0) vs 큰길 위주(4) (+계단제외는 요청 시) | 없음 |
| spots | 전부 + 프로필 노트 | 도착 앵커만 |
| advice | ok/caution/avoid + why | 없음 |
| 대중교통 | small만 | 항상 |
| 프로필 유래 기본값(no_stairs) | 적용 | **무시** |

기본값: 병원 dog, 약국 none. 사용자가 뒤집을 수 있음("나만 감").

## 계단제외·지하도 피함은 왜 뺐나
실측에서 강남 5경로 전부 계단 0, 지하는 출발 역 통로뿐. **안 나오는 장애물을 피하는 옵션**은 실효성 없음.
대신 매번 있는 축: **큰길 비율(`road_mix.big_ratio`)·큰길 횡단 수** — 소음·차·밝기의 대리 지표.
성격(반응성·겁) → 골목 섞인 길, 밤 → 큰길 위주. no_stairs는 노견 프로필 기본값으로만 조용히 남고, 계단이 실제로 있을 때만 spot으로 뜬다.

## 재료가 없어서 안 하는 것 (정직하게)
개 밀도 · 그늘 · 인도 폭 · 노면 · 경사 · 신호등 유무. 서울 실시간 혼잡도(citydata)는 서울 한정이라 **안 함**.

## 실측 관찰 (2026-08-19)
- TMAP 옵션 4(대로우선)는 강남에서 0과 거의 같은 경로. 5개 중 1개만 갈림(38%→54%). 비교축 레버리지 약함 — 지역 따라 다를 수 있어 유지하되 기대는 낮게
- 검색(estimate) 응답 ~2s는 DB·근거 쪽. 실측 5개 배치 ~2.5s (캐시 후 즉시)

## API
```
POST /hospital/search {…, companion, transport: "none"|"estimate"}   → 가벼운 리스트
POST /journey {origin, dests[{id}|{lat,lng,name}], companion, dog_id?, prefs: JourneyPrefs, measured, with_polyline}
   → items[{id,name,lat,lng, transport{walk{min,provider_min,option_label,road_mix,facilities,advice,why,alternatives[{label,delta_min}],spots,polyline,handoff}, car{taxi_fare,handoff}, transit?}}]
GET  /pharmacy/search?lat&lng&radius_m&open_now
```
콘솔: 검색 → 상위 5 `/journey` 배치 → 선. 카드 클릭 → 그 병원 `/journey`(캐시). 동반/나만 감 토글.
