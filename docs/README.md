# docs — 지도

문서는 한 줄기가 아니라 **갈래**로 자란다. 뭐가 확정이고 뭐가 탐색 중인지 여기서 본다.

```
overview.md          컨셉·범위. 거의 안 바뀜
decisions/           확정된 것만. 어느 탐색에서 나왔는지 링크
contracts/           남과의 약속 (프로필 계약, 검색 응답)
explorations/        갈래. 주제별 폴더, 갈래마다 파일. status로 상태 표시
research/            날짜 박힌 사실 조사·실험 로그
backlog.md           갈래에 안 붙는 미결
```

## 갈래 상태
`exploring` 파는 중 · `adopted` 채택 (decisions/에 한 줄 생김) · `parked` 보류 · `rejected` 기각 (지우지 않음 — 같은 질문 다시 안 하려고)

## 주제
- [병원 찾기](explorations/hospital-search/README.md) — 12갈래, 오늘의 초점은 [community-search](explorations/hospital-search/community-search.md)
- [지도 제공사](explorations/map-provider/README.md)
- [산책](explorations/walk/README.md) — 사용자 담당

## 계약
- [반려견 프로필](contracts/dog-profile.md) — 외부에서 받는 형태 + 가상 페르소나 3마리
- [검색 응답](contracts/search-response.md)

## 조사
- [지도 제공사 요금·쿼터·코드](research/2026-08-19-map-provider-pricing.md)
- [리뷰/평가 데이터 출처](research/2026-08-19-review-sources.md)
- [쿼리 재작성 실험](research/2026-08-19-query-rewrite-experiment.md)
- [경로 API 조사 + 네이버 화면 실측](research/2026-08-19-route-apis.md)
- [워킹 스켈레톤 실행 로그](research/2026-08-19-skeleton-run.md)
- [TMAP 실호출 — 문서와 다른 점, 파서 반영](research/2026-08-19-tmap-live.md)
- [Mapillary — 산책 개 합성 재료 조사 (라이선스·API·한국 커버리지)](research/2026-08-19-mapillary.md)
- [dev 콘솔 + spots(반려견 관심 지점)](research/2026-08-19-dev-console.md)

## 새 갈래 만들 때
`explorations/<주제>/<갈래>.md`, 상단에
```
---
status: exploring | adopted | parked | rejected
depends-on: (있으면)
---
```
주제 README 표에 한 줄 추가. adopted 되면 `decisions/README.md`에 번호 붙여 한 줄, 갈래 파일은 그대로 둔다.
