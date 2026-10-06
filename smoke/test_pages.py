"""Every page renders and the main flow works, in a real browser."""


def test_replay_holds_the_write_and_approve_plays_the_recorded_outcome(page, base_url, errors):
    page.goto(base_url + "/")
    page.wait_for_selector(".held")
    assert page.locator("#replay-badge").is_visible()
    page.click("#approve")
    page.wait_for_selector(".held", state="detached")
    statuses = page.locator(".call .st").all_inner_texts()
    assert "201" in statuses
    assert errors == []


def test_pages_render_after_handing_over_to_a_live_session(page, base_url, errors):
    page.goto(base_url + "/")
    page.wait_for_selector(".held")
    page.click('.ni[data-view="calls"]')                       # hands over: replay stops, AeroTrack ingests live
    page.wait_for_function("() => !!state.sessionId")
    assert page.locator("#calls-panel").is_visible()
    assert page.locator("#calls-empty").is_visible()

    page.click('.ni[data-view="endpoints"]')
    assert page.locator("#endpoints-panel .erow").count() == 11
    page.click('#endpoints-panel .erow[data-k="POST /shipments"]')
    assert "origin_city" in page.inner_text("#ep-detail")

    page.click('.ni[data-view="export"]')
    page.wait_for_function("() => document.getElementById('x-name').textContent.endsWith('_mcp.py')")
    assert "@mcp.tool()" in page.inner_text("#x-code")
    assert errors == []


def test_start_screen_lists_the_example_apis(page, base_url, errors):
    page.goto(base_url + "/?start")
    assert page.locator("#view-start").is_visible()
    assert page.locator("#preset-grid .preset").count() == 4
    assert errors == []


def test_monitor_renders(page, base_url, errors):
    page.goto(base_url + "/monitor")
    page.wait_for_load_state("networkidle")
    assert page.title()
    assert errors == []


def test_phone_width_has_no_sideways_scroll(page, base_url, errors):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base_url + "/")
    page.wait_for_selector(".held")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert errors == []
