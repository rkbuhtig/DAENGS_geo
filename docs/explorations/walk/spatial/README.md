# 산책의 공간 분포·조회

[산책 전체 입구](../README.md) · [일기](../diary/README.md) · [세션 통계](../statistics/README.md)

조건별 셀로판·부드러운 브러시·겹 수/비율 혼합 농도와 일기 탐색의 로컬 실험 결과는
[2026-09-07 종합 보고서](../../../research/2026-09-07-walk-diary-experiment-report.md)에 있다.
농도 계수는 시각 실험값이며 통계적으로 추정한 최적값이나 제품 채택 계약이 아니다.

| 작업 | 기준 문서 |
|---|---|
| 붓·산책별 셀로판·통계 질의 | [공간 통계층](cellophane-statistical-layer.md), [territory paint](territory-paint.md) |
| 연속 field 대조 | [연속 붓 기준선](continuous-brush-reference.md) |
| 국소 영역의 반복 체류 지표 | [반복 체류 영역](repeated-dwell-area.md) |
| 계산에서 판단 가능한 근거로 | [Evidence 층](evidence-layer.md), [경험 장면](experience-scenario.md) |
| 보류한 직접 영역 그리기 | [drawn region](drawn-region.md) |

공용 구현은 [app/features/territory](../../../../app/features/territory/),
실험·재현 명령은 [scripts 안내](../../../../scripts/README.md)와 각 갈래의 재현 절에 있다.
게임 규칙은 [별도 입구](../game/README.md)에서 찾는다.

영구 형태는 [결정 #69](../../../decisions/2026-08-26-walk-permanent-spatial-form.md),
읽기 계약은 [Cellophane](../../../contracts/cellophane-geojson.md)과
[Spatial Diary View](../../../contracts/spatial-diary-view.md)를 따른다.
[연속·Hex 비교 기록](../../../research/2026-08-31-continuous-hex-comparison.md)은 당시 실험 결과다.
DEV·APP 채택 기준은 [승격 원장](../../../promotion-ledger.toml)에서 확인한다.
