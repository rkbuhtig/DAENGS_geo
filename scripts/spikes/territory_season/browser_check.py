"""Browser integration against a real temporary SQLite store, with a disposable server.

uv run --with playwright python -m scripts.spikes.territory_season.browser_check --channel msedge
"""

import argparse
import socket
import tempfile
import threading
import time
from pathlib import Path


def main():
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from tools.territory_game.season_lab import build_app

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="msedge")
    parser.add_argument("--output", type=Path, default=Path(".local/season-browser"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="territory-season-") as folder:
        app = build_app(Path(folder) / "test.sqlite3")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started, "server startup timed out"
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel=args.channel)
                page = browser.new_page(viewport={"width": 1280, "height": 1100})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}/")

                def lose_response(route):
                    route.fetch()
                    route.abort()

                page.route("**/api/seasons", lose_response, times=1)
                page.locator("#create").click()
                expect(page.locator("#retry")).to_be_visible()
                page.reload()
                expect(page.locator("#retry")).to_be_visible()
                page.locator("#retry").click()
                expect(page.locator("#retry")).to_be_hidden()
                expect(page.locator("#status")).to_have_text("진행 중")
                assert page.locator("#seasons option").count() == 1
                page.locator("#new-session").click()
                page.locator("#approach").click()
                page.locator("#mark").click()
                expect(page.locator("#owner")).to_have_text("보리의 영역 · 미인증")
                expect(page.locator("#protection")).to_contain_text("10분")
                page.locator("#photo").click()
                page.get_by_role("button", name="인증 성공", exact=True).click()
                expect(page.locator("#owner")).to_have_text("보리의 영역 · 인증")
                page.locator("#target").select_option("B")
                page.locator("#approach").click()
                page.locator("#mark").click()
                expect(page.locator("#standings")).to_contain_text("2곳 · ×1.1")
                page.locator("#pet").select_option("p2")
                page.locator("#new-session").click()
                page.locator("#target").select_option("A")
                page.locator("#approach").click()
                expect(page.locator("#photo")).to_be_disabled()
                page.locator('[data-minutes="10"]').click()
                expect(page.locator("#photo")).to_be_enabled()
                page.locator("#photo").click()
                page.get_by_role("button", name="통신 장애", exact=True).click()
                page.get_by_role("button", name="기존 사진 재시도", exact=True).click()
                page.get_by_role("button", name="인증 성공", exact=True).click()
                expect(page.locator("#owner")).to_have_text("두부의 영역 · 인증")
                season_id = page.locator("#seasons").input_value()
                page.reload()
                expect(page.locator("#owner")).to_have_text("두부의 영역 · 인증")
                expect(page.locator("#walk-label")).to_contain_text("두부")
                page.screenshot(path=str(args.output / "desktop.png"), full_page=True)

                # Simulate a committed command whose HTTP response is lost, then retry it.
                pattern = "**/commands"
                page.route(pattern, lose_response, times=1)
                page.locator('[data-minutes="60"]').click()
                expect(page.locator("#retry")).to_be_visible()
                expect(page.locator('[data-minutes="60"]')).to_be_disabled()
                page.locator("#retry").click()
                expect(page.locator("#retry")).to_be_hidden()
                assert "01:10" in page.locator("#clock").inner_text()
                page.locator("#finish").click()
                expect(page.locator("#status")).to_have_text("시즌 결과")
                previous_points = page.locator("#standings").inner_text()
                page.locator("#create").click()
                expect(page.locator("#status")).to_have_text("진행 중")
                expect(page.locator("#owner")).to_contain_text("아직 누구")
                page.locator("#seasons").select_option(season_id)
                expect(page.locator("#status")).to_have_text("시즌 결과")
                assert page.locator("#standings").inner_text() == previous_points
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(args.output / "mobile.png"), full_page=True)
                assert not errors, errors
                browser.close()
                print(
                    "PASS: ownership, protection, photo retry, persistence, lost response retry, "
                    "season rollover/history, desktop/mobile layout"
                )
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()


if __name__ == "__main__":
    main()
