"""Browser cases for the walk screen copy; called by browser_check.py --app-copy."""


def check_app_copy(page, output, expect):
    def shot(name):
        page.locator("#phone").screenshot(path=str(output / f"copy-{name}.png"))

    def layout_check():
        problems = page.evaluate("""() => {
          const rect = id => document.getElementById(id).getBoundingClientRect();
          const visible = id => document.getElementById(id).getClientRects().length > 0;
          const overlap = (a, b) => a.left < b.right - 1 && a.right > b.left + 1 && a.top < b.bottom - 1 && a.bottom > b.top + 1;
          const errors = [];
          const surface = rect('walk-surface');
          for (const id of ['walk-top', 'hud', 'bottom-stack']) {
            const r = rect(id);
            if (r.top < surface.top - 1 || r.bottom > surface.bottom + 1 || r.left < surface.left - 1 || r.right > surface.right + 1) errors.push(id + ' outside map');
          }
          const game = visible('territory-card') ? rect('territory-card') : null;
          if (game && overlap(game, rect('hud'))) errors.push('game overlaps HUD');
          if (game && (game.left < surface.left || game.right > surface.right || game.top < surface.top || game.bottom > surface.bottom)) errors.push('game outside map');
          if (game && overlap(game, rect('primary-row'))) errors.push('game overlaps walk control');
          if (overlap(rect('hud'), rect('walk-top'))) errors.push('HUD overlaps top controls');
          if (document.documentElement.scrollWidth > innerWidth) errors.push('page horizontal overflow');
          if (document.getElementById('phone').scrollWidth > document.getElementById('phone').clientWidth) errors.push('phone horizontal overflow');
          return errors;
        }""")
        assert not problems, problems

    expect(page.locator("html")).to_have_attribute("data-tests", "passed")
    page.locator('[name="pet"][value="p2"]').check()
    page.locator("#start").click()
    expect(page.locator("#moment-dock")).to_be_visible()
    page.get_by_role("button", name="⌖ 배변·마킹", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("배변·마킹 기록")
    layout_check()
    shot("walk")
    page.locator("#toggle").click()
    expect(page.locator("#moment-dock")).to_be_hidden()
    expect(page.locator("#mark")).to_be_disabled()
    page.locator("#near").click()
    expect(page.locator("#representative")).to_have_text("영역표시 주체 · 보리")
    expect(page.locator("#mark")).to_be_enabled()
    layout_check()
    shot("ready")
    page.locator("#mark").click()
    expect(page.locator("#owner")).to_have_text("보리 · 미인증")
    page.locator("#photograph").click()
    expect(page.locator("#walk-surface")).to_have_attribute("inert", "")
    shot("camera")
    page.locator("#gps").select_option("stale")
    page.locator("#shutter").click()
    expect(page.locator("#camera-error")).to_contain_text("촬영할 수 없어요")
    page.locator("#gps").select_option("good")
    page.locator("#target").select_option("B")  # Camera remains pinned to A; no movement yet.
    page.locator("#shutter").click()
    expect(page.locator("#camera")).to_be_hidden()
    page.locator("#target").select_option("A")
    expect(page.locator("#open-jobs")).to_contain_text("1건 확인 중")
    layout_check()
    shot("pending")
    page.locator("#toggle").click()
    page.locator("#far").click()
    expect(page.locator("#moment-dock")).to_be_visible()
    expect(page.locator("#open-jobs")).to_contain_text("인증 완료", timeout=5000)
    page.locator("#toggle").click()
    expect(page.locator("#owner")).to_have_text("보리 · 인증")
    page.locator("#near").click()
    expect(page.locator("#photograph")).to_be_disabled()

    # The same world survives a completed walk; a different participant starts a new session.
    page.locator("#pause").click()
    page.locator("#finish").click()
    expect(page.locator("#result-text")).to_contain_text("행동 1건")
    page.locator("#next-walk").click()
    page.locator('[name="pet"][value="p1"]').uncheck()
    page.locator("#start").click()
    page.locator("#toggle").click()
    expect(page.locator("#state-inspector")).to_contain_text("행동 기록0건")
    expect(page.locator("#owner")).to_have_text("보리 · 인증")
    expect(page.locator("#mark")).to_be_disabled()
    page.locator("#verdict").select_option("REJECTED")
    page.locator("#photograph").click()
    page.locator("#cancel-camera").click()
    expect(page.locator("#photograph")).to_be_enabled()
    page.locator("#photograph").click()
    page.locator("#shutter").click()
    expect(page.locator("#photograph")).to_have_text("다시 촬영", timeout=5000)
    expect(page.locator("#owner")).to_have_text("보리 · 인증")
    shot("rejected")
    page.locator("#verdict").select_option("RETRYABLE_FAILURE")
    page.locator("#photograph").click()
    page.locator("#shutter").click()
    expect(page.locator("#open-jobs")).to_contain_text("확인 필요", timeout=5000)
    page.locator("#open-jobs").click()
    retry = page.get_by_role("button", name="같은 사진으로 재시도")
    capture = retry.locator("..").get_attribute("data-capture")
    shot("retry")
    retry.click()
    expect(page.locator(f'[data-capture="{capture}"]')).to_contain_text("인증 완료", timeout=5000)
    page.locator("#close-jobs").click()
    expect(page.locator("#owner")).to_have_text("두부 · 인증")
    shot("takeover")

    page.locator("#target").select_option("B")
    page.locator("#near").click()
    page.locator("#mark").click()
    expect(page.locator("#owner")).to_have_text("두부 · 미인증")
    for mode in ["loading", "empty", "error"]:
        page.locator("#board").select_option(mode)
        expect(page.locator("#photograph")).to_be_disabled()
        layout_check()
    page.locator("#board").select_option("ready")
    for gps in ["stale", "mock", "denied", "inaccurate"]:
        page.locator("#gps").select_option(gps)
        expect(page.locator("#photograph")).to_be_disabled()
    page.locator("#gps").select_option("good")
    page.locator("#verdict").select_option("DELAY")
    page.locator("#photograph").click()
    page.locator("#shutter").click()
    for width in [390, 360, 320]:
        page.set_viewport_size({"width": width, "height": 950})
        layout_check()
        shot(f"width-{width}")
    page.set_viewport_size({"width": 1440, "height": 1050})
    page.locator("#rotate").click()
    layout_check()
    shot("landscape")
    for mode in ["loading", "empty", "error"]:
        page.locator("#board").select_option(mode)
        layout_check()
    page.locator("#board").select_option("ready")
    # Finish while pending, then observe the same job complete with the walk stopped.
    page.locator("#pause").click()
    page.locator("#finish").click()
    page.locator("#next-walk").click()
    expect(page.locator("#open-jobs")).to_contain_text("인증 완료", timeout=20000)
    expect(page.locator("#start")).to_be_visible()
    assert page.locator("#pause").is_hidden()
    # Long guidance and camera error controls must remain reachable in either orientation.
    page.locator("#start").click()
    page.locator("#toggle").click()
    page.locator("#target").select_option("C")
    page.locator("#near").click()
    layout_check()
    page.locator("#photograph").click()
    page.locator("#gps").select_option("denied")
    page.locator("#shutter").click()
    expect(page.locator("#camera-error")).to_contain_text("촬영할 수 없어요")
    shot("landscape-camera-error")
    page.locator("#cancel-camera").click()
    page.locator("#gps").select_option("good")
    page.set_viewport_size({"width": 320, "height": 950})
    page.locator("#photograph").click()
    page.locator("#gps").select_option("stale")
    page.locator("#shutter").click()
    expect(page.locator("#camera-error")).to_contain_text("촬영할 수 없어요")
    shot("narrow-camera-error")
    page.locator("#cancel-camera").click()
    # A reset while a fake verdict is pending must not write into the next world.
    page.locator("#gps").select_option("good")
    page.locator("#verdict").select_option("ACCEPTED")
    page.locator("#photograph").click()
    page.locator("#shutter").click()
    page.locator("#reset").click()
    page.wait_for_timeout(2200)  # Cross the cancelled verdict's 2-second deadline.
    expect(page.locator("#photo-strip")).to_be_hidden()
    expect(page.locator("#owner")).to_have_text("미점유")
