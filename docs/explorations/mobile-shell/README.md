# 모바일 셸 — 탐색과 기준 구현

Geo의 [Android README](../../../android/README.md)에서 코드·설정·빌드·남은 검증을 확인한다.
이 사본은 연구·대조용이며 운영 앱의 원본은
[DAENGS_APP](https://github.com/SAJOYO/DAENGS_APP)이다.

| 찾는 내용 | 문서 |
|---|---|
| 지도 중심 셸의 초기 선택과 화면 구상 | [mobile-map-shell](mobile-map-shell.md) |
| 장소·산책·점령의 목적별 레이어 경계 | [map-purpose-display-policy](map-purpose-display-policy.md) |
| 현재 위치·Place 검색·Journey·산책 수집 실행 | [Android 기준 구현](../../../android/README.md) |
| 운영 채택 기준점 | [승격 원장](../../promotion-ledger.toml) |

Geo 사본에는 foreground 산책 서비스·Room 원본 저장과 명시적 종료 시
`start → fixes → finish` 업로드가 구현돼 있다. 닫히지 않은 세션의 복구 UI와
자동 재시도 큐는 이 사본의 남은 범위이며, 운영 앱의 구현 여부를 뜻하지 않는다.
초기 셸 문서의 브리핑·트리거·회고 구상을 현재 구현된 화면으로 읽지 않는다.
