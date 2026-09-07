# 동네 강자 시즌 체험

Python 3.12와 Geo 루트에서 `uv sync --frozen`으로 준비한다.
같은 루트에서 `uv run python -m scripts.spikes.territory_season.server`를 실행하고
<http://127.0.0.1:8767/>을 연다. 새 시즌·산책을 시작해 영역표시하고 사진 판정을 조작한다.
10분 보호, 점수 누적, 시즌 결과 보존을 같은 지도에서 확인한다.

SQLite 파일을 별도로 사용하므로 PostGIS·Docker·API 키가 필요 없다.
`--db .local/my-game.sqlite3 --port 8768`로 다른 실험을 열 수 있다.

- [규칙·저장·검증·승격 계약](../../../docs/explorations/walk/game/territory-season-game.md)
- [기존 영역표시 웹 실험](../territory_production_plan/README.md)

```powershell
uv run python -m scripts.spikes.territory_season.simulate --hours 6
```

브라우저 검증은 임시 서버·SQLite를 직접 만들고 닫는다. 평소 사용하던 DB는 검증에 쓰지 않는다.
Windows에 Edge가 설치돼 있으면 다음을 실행한다.

```powershell
uv run --with playwright python -m scripts.spikes.territory_season.browser_check --channel msedge
```

Edge가 없으면 Playwright Chromium을 설치하고 채널을 명시한다. 이 검사 CLI의 기본 채널은 Edge다.

```bash
uv run --with playwright python -m playwright install chromium
uv run --with playwright python -m scripts.spikes.territory_season.browser_check --channel chromium
```

브라우저 설치에는 다운로드가 필요하다. 캡처 기본 위치는 Geo 루트의 `.local/season-browser`이며
`--output`으로 바꿀 수 있다. 게임 실행의 SQLite·브라우저 저장과 복원 조건은
[도구 안내](../../../tools/README.md#데이터-위치와-기존-도구)를 따른다.
