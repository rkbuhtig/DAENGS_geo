# Place v2 검색 계약

`POST /v2/places/search`는 웹과 Android가 함께 사용할 장소 발견의 canonical 입구다. 기존
`GET /places/search`, `/hospital/search`, `/pharmacy/search`, `/facility/search`는 소비자가
이동할 때까지 유지한다.

## 요청

```json
{
  "lat": 37.556,
  "lng": 126.923,
  "radius_m": 3000,
  "kinds": ["pet_shop", "shopping"],
  "limit_per_kind": 2500
}
```

- `kinds`는 비어 있을 수 없으며 순서와 값이 중복되면 안 된다. 한 요청은 최대 6종이다.
- canonical kind 목록은 OpenAPI `PlaceKind` enum이 권위다. 폐기된 `goods`는 422다.
- `shopping`은 호출자가 명시했을 때만 검색한다. 서버가 임의로 끼우거나 숨기지 않는다.
- 그룹 한도는 최대 3000, 한 요청의 전체 결과 예산은 최대 5000이다. `limit_per_kind`를
  생략하면 `min(3000, floor(5000 / kinds 수))`를 적용한다. 명시한 한도와 kinds 수의 곱이
  5000을 넘으면 422다. 실제 적용한 값은 그룹의 `limit`, 잘렸는지는 `truncated`로 알린다.

## 응답

```jsonc
{
  "groups": [
    {
      "kind": "pet_shop",
      "sort": { "type": "distance", "basis": ["distance_m"] },
      "limit": 2500,
      "truncated": false,
      "results": [/* PlaceResult */]
    },
    {
      "kind": "shopping",
      "sort": { "type": "distance", "basis": ["distance_m"] },
      "limit": 2500,
      "truncated": false,
      "results": []
    }
  ]
}
```

그룹은 요청한 kind 순서다. 각 그룹 안에서만 거리순이며 서로 다른 kind 사이에는 전역 순위를
만들지 않는다. 같은 거리의 반환 결과는 `(source, ref)`로 안정화한다.

`hospital`과 `pharmacy`는 각각의 MOIS 인허가 source만 읽는 MedicalResolver가 존재 권위를
갖고, dev나 임의 source의 같은 kind는 섞지 않는다. 그 밖의 kind는 ref가 있는 KCISA/KTO만
읽는 FacilityResolver가 담당한다. 결과는 모두 `PlaceResult`로 변환되며 내부 DB PK를
identity로 노출하지 않는다.

## 현재 하지 않는 것

- 주차·영업 중·동반 가능 hard filter 또는 선호 정렬
- 태그/이름 추론 및 AI 제안
- 서로 다른 kind 결과의 통합 순위
- 검증되지 않은 `facility_link`를 Place alias로 승격
- 기존 웹·Android 소비자의 자동 전환
