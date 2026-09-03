# 모바일 셸 — 탐색 갈래

실제 서비스가 폰에서 어떤 모양이 되는가. `/dev`만 있던 시점에서 시작했고 현재 Android 기준
지도 셸이 착지했다.

| 갈래 | status | implementation | 한 줄 |
|---|---|---|---|
| [mobile-map-shell](mobile-map-shell.md) | adopted | working-skeleton | Android 위치→검색→지도·카드→action·전화가 착지. 산책 service와 업로드는 미구현 |
| [map-purpose-display-policy](map-purpose-display-policy.md) | exploring | working-skeleton | 장소 검색·산책·점령이 같은 지도에서 데이터는 공유하지 않고, 목적별 허용 레이어만 합성한다. 최종 소유자는 app 저장소 |
