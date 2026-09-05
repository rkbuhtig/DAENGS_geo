"""Browser cases for the walk screen copy; called by browser_check.py --app-copy."""


def check_app_copy(page, output, expect):
    def shot(name):
        page.locator("#phone").screenshot(path=str(output / f"copy-{name}.png"))

    def select_site(site=None):
        site = site or page.locator("#target").input_value()
        page.locator(f'[data-site="{site}"]').dispatch_event("click")

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
          if (document.getElementById('phone').classList.contains('playing')) {
            const obstacles = ['walk-top', 'hud', 'territory-card', 'primary-row', 'notice'].filter(visible).map(rect);
            const targetId = document.getElementById('target').value;
            const marker = document.querySelector('[data-site="' + targetId + '"]');
            const subjects = [['player', rect('player')]];
            if (marker) subjects.push(['target marker', marker.getBoundingClientRect()]);
            if (visible('target-label')) subjects.push(['target label', rect('target-label')]);
            for (const [name, r] of subjects) {
              if (r.left < surface.left || r.right > surface.right || r.top < surface.top || r.bottom > surface.bottom) errors.push(name + ' outside map');
              if (obstacles.some(o => overlap(r, o))) errors.push(name + ' hidden by controls');
            }
            if (!document.querySelector('.workspace').classList.contains('landscape') && rect('bottom-stack').height / surface.height > .32) errors.push('game occupies over 32% of portrait map');
          }
          return errors;
        }""")
        assert not problems, problems

    expect(page.locator("html")).to_have_attribute("data-tests", "passed")
    # Browsing needs neither a walk nor a claiming dog, even near an occupied pole.
    page.locator("#preset").select_option("rival")
    page.locator("#reset").click()
    page.locator("#toggle").click()
    page.locator("#near").click()
    page.locator('[data-site="A"]').click()
    expect(page.locator("#territory-card")).to_have_attribute("data-phase", "browsing")
    expect(page.locator("#owner")).to_have_text("두부 · 인증")
    expect(page.locator("#site-occupant")).to_contain_text("점유자 두부네")
    expect(page.locator("#claim-pet")).to_be_hidden()
    expect(page.locator("#guidance")).to_be_hidden()
    expect(page.locator("#photograph")).to_be_hidden()
    expect(page.locator('[data-site="A"] circle[r="40"]')).to_have_count(0)
    for width in [320, 390, 1440]:
        page.set_viewport_size({"width": width, "height": 1100})
        layout_check()
        shot(f"browse-{width}")
    page.locator("#gps").select_option("denied")
    expect(page.locator("#site-occupant")).to_be_visible()
    page.locator("#gps").select_option("good")
    page.locator("#start").click()
    expect(page.locator("#site-title")).to_contain_text("A ·")
    expect(page.locator("#territory-card")).to_have_attribute("data-phase", "walking")
    expect(page.locator("#claim-pet")).to_be_visible()
    expect(page.locator("#photograph")).to_be_enabled()
    page.locator("#pause").click()
    page.locator("#browse-paused").click()
    expect(page.locator("#territory-card")).to_have_attribute("data-phase", "paused")
    expect(page.locator("#site-occupant")).to_be_visible()
    expect(page.locator("#claim-pet")).to_be_hidden()
    expect(page.locator("#photograph")).to_be_hidden()
    expect(page.locator("#site-paused")).to_be_visible()
    expect(page.locator('[data-site="A"] circle[r="40"]')).to_have_count(0)
    shot("paused-browse")
    page.locator("#pause").click()
    page.locator("#resume").click()
    expect(page.locator("#territory-card")).to_have_attribute("data-phase", "walking")
    expect(page.locator("#photograph")).to_be_enabled()
    expect(page.locator("#state-inspector")).to_contain_text("점령 시도1건 (시드 포함)")
    page.locator("#preset").select_option("neutral")
    page.locator("#reset").click()
    page.locator(".ready-card summary").click()
    page.locator('[name="pet"][value="p2"]').check()
    page.locator("#start").click()
    expect(page.locator("#moment-dock")).to_be_hidden()
    page.locator("#open-moments").click()
    expect(page.locator("#moment-dock")).to_be_visible()
    page.get_by_role("button", name="⌖ 배변·마킹", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("배변·마킹 기록")
    page.locator("#diary-camera").click()
    expect(page.locator("#camera-title")).to_have_text("산책 사진")
    page.locator("#diary-caption").fill("<b>보리와 두부의 산책</b>")
    page.locator("#near").click()  # The pin belongs to shutter time, not camera-open time.
    page.locator("#shutter").click()
    expect(page.locator("#diary-markers [data-diary]")).to_have_count(1)
    expect(page.locator("#photo-strip")).to_be_hidden()
    expect(page.locator("#state-inspector")).to_contain_text("점령 시도0건")
    page.locator("#open-diary").click()
    expect(page.locator(".diary-entry")).to_have_attribute("data-position", "183,303")
    expect(page.locator(".diary-entry p")).to_have_text("<b>보리와 두부의 산책</b>")
    expect(page.locator(".diary-entry b")).to_have_count(0)
    shot("diary")
    page.locator("#close-diary").click()
    page.locator("#far").click()
    layout_check()
    shot("walk")
    page.locator("#toggle").click()
    if page.locator("#toggle").get_attribute("aria-pressed") == "true":
        expect(page.locator("#territory-card")).to_be_hidden()
        select_site()
    expect(page.locator("#moment-dock")).to_be_hidden()
    expect(page.locator("#mark")).to_be_disabled()
    page.locator("#near").click()
    select_site()
    expect(page.locator("#representative")).to_have_text("영역표시 주체 · 보리")
    expect(page.locator("#mark")).to_be_enabled()
    layout_check()
    shot("ready")
    page.locator("#mark").click()
    expect(page.locator("#owner")).to_have_text("보리 · 미인증")
    expect(page.locator("#target-state")).to_contain_text("발자국을 남겼어요")
    expect(page.locator("#mark")).to_be_hidden()
    layout_check()
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
    select_site()
    expect(page.locator("#open-jobs")).to_contain_text("1건 확인 중")
    layout_check()
    shot("pending")
    expect(page.locator("#diary-markers [data-diary]")).to_have_count(1)
    expect(page.locator("#claim-pet")).to_be_disabled()
    page.locator("#toggle").click()
    if page.locator("#toggle").get_attribute("aria-pressed") == "true":
        expect(page.locator("#territory-card")).to_be_hidden()
        select_site()
    page.locator("#far").click()
    expect(page.locator("#moment-dock")).to_be_hidden()
    expect(page.locator("#diary-camera")).to_be_visible()
    expect(page.locator("#open-jobs")).to_contain_text("인증 완료", timeout=5000)
    page.locator("#toggle").click()
    if page.locator("#toggle").get_attribute("aria-pressed") == "true":
        expect(page.locator("#territory-card")).to_be_hidden()
        select_site()
    expect(page.locator("#owner")).to_have_text("보리 · 인증")
    page.locator("#near").click()
    select_site()
    expect(page.locator("#photograph")).to_be_disabled()

    # The same world survives a completed walk; a different participant starts a new session.
    page.locator("#pause").click()
    page.locator("#finish").click()
    expect(page.locator("#result-text")).to_contain_text("행동 1건")
    page.locator("#next-walk").click()
    page.locator('[name="pet"][value="p1"]').uncheck()
    page.locator("#start").click()
    page.locator("#toggle").click()
    if page.locator("#toggle").get_attribute("aria-pressed") == "true":
        expect(page.locator("#territory-card")).to_be_hidden()
        select_site()
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
    expect(page.locator("#target-state")).to_contain_text("영역을 차지했어요")
    expect(page.locator("#photograph")).to_be_hidden()
    layout_check()
    shot("takeover")

    page.locator("#target").select_option("B")
    page.locator("#near").click()
    select_site()
    layout_check()
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
    expect(page.locator("#gps-status")).to_have_attribute("data-quality", "weak")
    page.locator("#gps-status").click()
    expect(page.locator("#gps-detail")).to_contain_text("30m")
    page.locator("#gps-status").click()
    page.locator("#gps").select_option("good")
    expect(page.locator("#gps-status")).to_have_attribute("data-quality", "good")
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
    if page.locator("#toggle").get_attribute("aria-pressed") == "true":
        expect(page.locator("#territory-card")).to_be_hidden()
        select_site()
    page.locator("#target").select_option("C")
    page.locator("#near").click()
    select_site()
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
    page.locator("#start").click()
    page.locator("#toggle").click()
    if page.locator("#toggle").get_attribute("aria-pressed") == "true":
        expect(page.locator("#territory-card")).to_be_hidden()
        select_site()
    for width in [320, 390, 1440]:
        page.set_viewport_size({"width": width, "height": 1050})
        if width == 1440:
            page.locator("#rotate").click()
        for target in ["A", "B", "C"]:
            page.locator("#target").select_option(target)
            select_site()
            for movement in ["far", "near"]:
                page.locator(f"#{movement}").click()
                layout_check()
            if target == "B":
                shot(f"visible-b-{width}")

    # Different claiming dogs in one multi-dog walk; previous attempts remain pinned.
    page.set_viewport_size({"width": 1440, "height": 1050})
    page.locator("#reset").click()
    page.locator('[name="pet"][value="p1"]').check()
    page.locator("#start").click()
    page.locator("#toggle").click()
    page.locator("#near").click()
    select_site("A")
    page.locator("#claim-pet").select_option("p2")
    page.locator("#mark").click()
    expect(page.locator("#owner")).to_have_text("두부 · 미인증")
    page.locator("#target").select_option("B")
    page.locator("#near").click()
    select_site("B")
    page.locator("#claim-pet").select_option("p1")
    page.locator("#mark").click()
    expect(page.locator("#owner")).to_have_text("보리 · 미인증")
    page.locator("#target").select_option("A")
    page.locator("#near").click()
    select_site("A")
    expect(page.locator("#claim-pet")).to_have_value("p2")
    expect(page.locator("#claim-pet")).to_be_disabled()
    expect(page.locator("#mark")).to_be_hidden()
    page.locator("#photograph").click()
    expect(page.locator("#camera-context")).to_contain_text("두부")
    page.locator("#cancel-camera").click()
    page.locator("#close-site").click()
    expect(page.locator("#territory-card")).to_be_hidden()
    expect(page.locator("#diary-camera")).to_be_visible()
    expect(page.locator("#toggle svg")).to_have_count(1)
    expect(page.locator("#rotate svg")).to_have_count(1)
    shot("compact-map")
