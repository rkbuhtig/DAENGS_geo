# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.51,<2"]
# ///
"""Local browser regression for the territory production-plan spike.

uv run scripts/spikes/territory_production_plan/browser_check.py --channel msedge
Imports have no browser/server side effects; Playwright is a script-only dependency.
"""

import argparse
import functools
import http.server
import tempfile
import threading
from pathlib import Path


def main() -> None:
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default=None)
    parser.add_argument(
        "--app-copy", action="store_true", help="Check the Android walk screen copy"
    )
    parser.add_argument(
        "--output", type=Path, default=Path(tempfile.gettempdir()) / "territory-play-lab"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(Path(__file__).parent)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=args.channel, headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.on("pageerror", lambda error: errors.append(str(error)))
            if args.app_copy:
                from browser_copy_cases import check_app_copy

                page.goto(f"{url}/app-copy.html")
                check_app_copy(page, args.output, expect)
                assert not errors, errors
                browser.close()
                print(f"PASS: walk app copy UI and layout checks. Screenshots: {args.output}")
                return
            page.goto(url)
            expect(page.locator("html")).to_have_attribute("data-tests", "passed")
            expect(page.locator("#mark")).to_be_disabled()
            page.locator("#approach").click()
            page.locator("#mark").click()
            expect(page.locator("#owner")).to_have_text("보리의 영역 · 미인증")
            page.locator("#photograph").click()
            page.locator("#shutter").click()
            expect(page.locator("#pending-count")).to_contain_text("1건")
            page.locator("#visibility").click()
            page.locator("#leave").click()
            expect(page.locator("#walk-label")).to_contain_text("기록 중")
            expect(page.locator("#pending-count")).to_contain_text("0건", timeout=5000)
            page.locator("#visibility").click()
            expect(page.locator("#owner")).to_have_text("보리의 영역 · 인증")
            page.locator("#pet").select_option("p2")
            page.locator("#new-session").click()
            page.locator("#approach").click()
            expect(page.locator("#mark")).to_be_disabled()
            page.locator("#verdict").select_option("REJECTED")
            page.locator("#photograph").click()
            page.locator("#shutter").click()
            expect(page.locator("#owner")).to_have_text("보리의 영역 · 인증")
            expect(page.locator("#photograph")).to_have_text("다시 촬영", timeout=5000)
            page.locator("#verdict").select_option("RETRYABLE_FAILURE")
            page.locator("#photograph").click()
            page.locator("#shutter").click()
            retry = page.get_by_role("button", name="기존 사진으로 재시도")
            expect(retry).to_be_visible(timeout=5000)
            capture = retry.locator("..").get_attribute("data-capture")
            retry.click()
            expect(page.locator(f'[data-capture="{capture}"]')).to_contain_text(
                "인증 완료", timeout=5000
            )
            expect(page.locator("#owner")).to_have_text("두부의 영역 · 인증")
            expect(page.locator("#photograph")).to_be_disabled()
            page.locator("#target").select_option("B")
            page.locator("#approach").click()
            page.locator("#photograph").click()
            page.locator("#cancel").click()
            expect(page.locator("#mark")).to_be_enabled()
            page.locator("#photograph").click()
            # GPS can change underneath an open camera independently of user input.
            page.evaluate("document.getElementById('stale').checked = true")
            page.locator("#shutter").click()
            expect(page.locator("#camera-error")).to_contain_text("촬영할 수 없어요")
            page.locator("#cancel").click()
            page.locator("#stale").uncheck()
            page.locator("#mark").click()
            expect(page.locator("#owner")).to_have_text("두부의 영역 · 미인증")
            page.locator("#pause").click()
            expect(page.locator("#photograph")).to_be_disabled()
            page.locator("#pause").click()
            page.locator("#untrusted").check()
            expect(page.locator("#photograph")).to_be_disabled()
            page.locator("#untrusted").uncheck()
            page.screenshot(path=str(args.output / "desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(args.output / "mobile.png"), full_page=True)
            assert not errors, errors
            print("PASS: 20 shared steps + 6 boundaries; UI strengthening/takeover/reshoot/retry;")
            print(
                "toggle + movement during pending; cancelled/stale shutter; multi-site; pause/mock; mobile overflow."
            )
            print(f"Screenshots: {args.output}")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
