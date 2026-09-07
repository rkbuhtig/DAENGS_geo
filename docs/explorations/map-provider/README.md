# 지도 제공사 — 탐색과 구현 입구

지도 렌더링은 제공사 SDK가 맡고, Geo는 장소·산책 증거와 지도에 전달할 데이터를 소유한다.
현재 표면별 선택·설정·폴백·검증 기록은 **[공급자 조립 현황](../../provider-assembly.md)**에서 관리한다.
운영 백엔드와 앱의 적용 범위는 [승격 원장](../../promotion-ledger.toml)을 함께 확인한다.

## 코드에서 찾기

[MapProvider](../../../app/providers/base.py)는 `static_map_url`, `geocode`,
`reverse_geocode`, `route`의 **4메서드** 계약이다. `route_modes`로 실제 구현한 경로 수단을
선언한다. [registry](../../../app/providers/registry.py)는 제공사를 만들고,
[사용량 조립](../../../app/usage/composition.py)이 실제 외부 호출의 Gate를 연결한다.

TMAP 도보 어댑터는 구현돼 있지만 기본 경로 설정은 `fake`다. 어댑터 구현·로컬 설정·실제
운영 채택은 서로 다른 상태다. 설정 가능한 이름만으로 실측 지원을 판단하지 않는다.
검색 후보는 [Place v2](../../contracts/place-search-v2.md)가 PostGIS에서 구하며,
지도 SDK 선택이 장소 검색·지오코딩·각 이동수단의 제공사를 함께 정하지 않는다.

## 화면과 검증

현재 시설 지도는 Geo 루트에서 `uv run python -m tools.lab_server --tool facility`로
실행한 서버의 `/facility-map`에서 연다. PostGIS 준비·키·폴백 조건은
[도구 안내](../../../tools/README.md)와 공급자 조립 문서를 따른다.
공용 `app.main`은 검토 화면을 열지 않는다. 과거 단일 `/dev` 콘솔은 제거됐다.
Android 지도는 [연구·대조 구현](../../../android/README.md)에서 확인한다.

제공사 계약·경로 진실성·설정 검증은 Geo 루트에서 실행한다.

```bash
uv run pytest tests/providers -q
```

위 테스트는 실제 키·타일·제공사 API의 정상 동작을 대신 확인하지 않는다.
[2026-08-19 요금·쿼터 조사](../../research/2026-08-19-map-provider-pricing.md)는 당시 기록이다.
현재 설정 안내와 과거 가격·SDK 선택 근거를 구분해 읽는다.
