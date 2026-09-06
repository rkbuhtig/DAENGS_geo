# 동네 강자 시즌 체험

Geo 루트에서 `uv run python -m scripts.spikes.territory_season.server`를 실행하고
<http://127.0.0.1:8767/>을 연다. 새 시즌·산책을 시작해 영역표시하고 사진 판정을 조작한다.
10분 보호, 점수 누적, 시즌 결과 보존을 같은 지도에서 확인한다.

SQLite 파일을 별도로 사용하므로 PostGIS·Docker·API 키가 필요 없다.
`--db .local/my-game.sqlite3 --port 8768`로 다른 실험을 열 수 있다.

- [규칙·저장·검증·승격 계약](../../../docs/explorations/walk/territory-season-game.md)
- [기존 영역표시 웹 실험](../territory_production_plan/README.md)

```powershell
uv run python -m scripts.spikes.territory_season.simulate --hours 6
uv run --with playwright python -m scripts.spikes.territory_season.browser_check --channel msedge
```
