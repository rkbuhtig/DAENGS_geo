# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright>=1.50,<2"]
# ///
"""Browser checks for the standalone lab; use an already-installed Chrome/Edge.

Start the static server from docs/explorations/facility/place-ui-web.md, then:
uv run scripts/verify/place_ui_lab_browser.py --browser-path /path/to/chrome
Optional --screenshots writes desktop/mobile captures outside the repository.
"""

import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-path", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8765/")
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser_path, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        expect(page.locator(".card")).to_have_count(24)
        expect(page.get_by_role("button", name="현재 앱", exact=True)).to_have_attribute(
            "aria-pressed", "true"
        )
        for region, count in (("gangnam", 24), ("seongsu", 14), ("haeundae", 5), ("jeju", 1)):
            page.select_option("#region", region)
            for dog in ("large", "small", "baseline"):
                page.select_option("#dog", dog)
                for _ in range(2):
                    expect(page.locator(".card")).to_have_count(count)
                    page.locator("#parking").click()
        page.locator("#rooftop-example").click()
        expect(page.locator("#selected-name")).to_have_text("구욱희씨")
        expect(page.locator(".card.selected")).to_contain_text("입장 조건상 가능")
        expect(page.locator(".card.selected .restrictions")).to_have_count(0)
        page.get_by_role("button", name="제한사항 보완안", exact=True).click()
        expect(page.locator(".card.selected")).to_contain_text("루프탑 외 입장 불가")
        expect(page.locator(".card.selected")).to_contain_text("크기·체중 조건상 가능")
        assert page.locator(".panel").evaluate("panel => panel.scrollTop") == 0
        if args.screenshots:
            args.screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.screenshots / "place-ui-desktop.png"), full_page=True)
        page.locator(".map-marker").first.click()
        expect(page.locator(".card").first).to_have_class("card selected")
        for scenario in ("loading", "empty", "error", "permission"):
            page.select_option("#scenario", scenario)
            expect(page.locator(".card")).to_have_count(0)
            expect(page.locator(".map-marker")).to_have_count(0)
        page.select_option("#scenario", "error")
        page.locator("#retry").click()
        expect(page.locator(".card")).to_have_count(14)
        page.locator('[data-kind="restaurant"]').click()
        expect(page.locator("#results")).to_contain_text("결과를 찾지 못했습니다")
        page.locator('[data-kind="pet_shop"]').click()
        expect(page.locator("#results")).to_contain_text("수집하지 않았습니다")
        page.locator("#outdoor-example").click()
        page.select_option("#dog", "baseline")
        expect(page.locator(".card").first).not_to_contain_text("크기·체중 조건상 가능")
        # Server strings must remain text even when markup is supplied.
        page.evaluate("""() => {
            fixtures.cases['gangnam-baseline'].groups[0].results[0].place.name =
                '<img src=x onerror="window.__injected=true">'; render();
        }""")
        expect(page.locator(".card img")).to_have_count(0)
        assert page.evaluate("window.__injected === undefined")
        page.reload()
        expect(page.locator(".card")).to_have_count(24)
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#rooftop-example").click()
        page.get_by_role("button", name="제한사항 보완안", exact=True).click()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if args.screenshots:
            page.screenshot(path=str(args.screenshots / "place-ui-mobile.png"), full_page=True)
        assert not errors, errors
        browser.close()
    print("Browser checks passed: recorded controls, selection, modes, states, escaping, mobile width")


if __name__ == "__main__":
    main()
