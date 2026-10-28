"""Browser tests for web/index.html: what reviews have been checking by hand.

Runs the real page in headless Chromium against the committed demo data.
Dates are passed explicitly, so results don't depend on today's date.
"""

import re
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, expect

DAY = "2026-10-28"
ABSTRACTED = "/index.html?source=demo&matrix=abstracted&locality=mid-north-40-n&date=%s" % DAY
SIMPLIFIED = "/index.html?source=demo&matrix=simplified&locality=mid-north-40-n&date=%s" % DAY


def open_page(page: Page, path: str):
    page.goto(path)
    page.wait_for_selector("svg.sm-root .sm-event")


def texts(page: Page, selector: str):
    return page.locator(selector).all_text_contents()


def query(page: Page):
    return {k: v[0] for k, v in parse_qs(urlparse(page.url).query).items()}

################################################################################
## Loading and layout
################################################################################

def test_default_view_is_the_predicted_library(page, base_url, errors):
    open_page(page, base_url + "/index.html")
    assert query(page)["matrix"] == "abstracted"
    assert "locality" in query(page) and "date" in query(page) and "source" not in query(page)
    assert texts(page, "#sm-matrix option") == ["Abstracted Sync Matrix", "Simplified Sync Matrix"]
    expect(page.get_by_role("radio", name="Predicted")).to_have_attribute("aria-checked", "true")
    expect(page.locator("#sm-icod-badge")).not_to_contain_text("DEMO DATA")
    assert "Predicted" in texts(page, ".sm-legend text")
    assert errors == []


def test_data_switch_between_predicted_and_demo(page, base_url, errors):
    open_page(page, base_url + "/index.html?matrix=simplified&locality=mid-north-40-n")
    page.get_by_role("radio", name="Demo").click()
    expect(page.locator("#sm-icod-badge")).to_contain_text("DEMO DATA")
    assert query(page)["source"] == "demo"
    assert query(page)["matrix"] == "simplified" and query(page)["locality"] == "mid-north-40-n"  # kept
    page.get_by_role("radio", name="Predicted").click()
    expect(page.locator("#sm-icod-badge")).not_to_contain_text("DEMO DATA")
    assert "source" not in query(page)
    assert errors == []


def test_explicit_manifest_hides_the_data_switch(page, base_url, errors):
    open_page(page, base_url + "/index.html?manifest=data/index.json")
    expect(page.locator("#sm-source")).to_be_hidden()
    assert errors == []


def test_abstracted_layout(page, base_url, errors):
    open_page(page, base_url + ABSTRACTED)
    expect(page.locator(".sm-title")).to_have_text("Abstracted Sync Matrix")
    expect(page.locator(".sm-subtitle")).to_have_text("Mid-north 40°N · 28 October 2026")
    assert texts(page, ".sm-group-label") == ["EO", "IR", "SAR"]
    assert page.locator(".sm-row-label").count() == 28
    hours = texts(page, ".sm-axis .tick text")
    assert hours[0] == "0000Z" and hours[-1] == "2300Z" and len(hours) == 24
    assert errors == []


def test_localities_run_north_to_south(page, base_url, errors):
    open_page(page, base_url + ABSTRACTED)
    names = [re.sub(r" \(.*\)$", "", t) for t in texts(page, "#sm-locality option")]
    assert names == ["High Arctic 78°N", "Arctic 70°N", "Subarctic 65°N", "London", "Kiev", "Assisi",
                     "Mid-north 40°N", "Tokyo", "Tehran", "Cairo", "Kathmandu", "Gao",
                     "Equator 0°", "Mid-south 40°S", "Antarctic 78°S"]
    assert errors == []


def test_icod_badge_shows_demo_data(page, base_url, errors):
    open_page(page, base_url + ABSTRACTED)
    badge = page.locator("#sm-icod-badge")
    expect(badge).to_contain_text("ICOD 28 Oct 1200Z")
    expect(badge).to_contain_text("DEMO DATA")
    assert page.locator(".sm-icod").count() == 0  # no footer copy while the toolbar is shown
    assert errors == []

################################################################################
## Controls
################################################################################

def test_group_by_provider_regroups_the_same_events(page, base_url, errors):
    open_page(page, base_url + ABSTRACTED)
    events_before = sorted(page.locator(".sm-event").evaluate_all("els => els.map(e => e.getAttribute('aria-label'))"))
    page.get_by_role("radio", name="Provider").click()
    assert texts(page, ".sm-group-label") == ["Capella", "Copernicus", "NASA FIRMS", "Vantor"]
    assert query(page)["group"] == "provider"
    events_after = sorted(page.locator(".sm-event").evaluate_all("els => els.map(e => e.getAttribute('aria-label'))"))
    assert events_after == events_before
    page.get_by_role("radio", name="Phenomenology").click()
    assert "group" not in query(page)
    assert errors == []


def test_simplified_is_always_phenomenology(page, base_url, errors):
    open_page(page, base_url + SIMPLIFIED + "&group=provider")
    expect(page.locator("#sm-grouping")).to_be_hidden()
    assert texts(page, ".sm-group-label") == ["COM", "IR", "SAR", "EO"]
    assert page.locator(".sm-row-label").count() == 0  # group bars only
    assert errors == []


def test_day_night_switch(page, base_url, errors):
    open_page(page, base_url + ABSTRACTED)
    assert page.locator(".sm-daylight").count() == 1
    page.locator(".sm-switch").click()
    assert page.locator(".sm-daylight").count() == 0
    assert query(page)["daylight"] == "0"
    assert errors == []


def stop_opacities(page):
    return [float(v) for v in page.locator("#sm-daylight stop").evaluate_all(
        "els => els.map(e => e.getAttribute('stop-opacity'))")]


def test_polar_night_is_shaded_all_day(page, base_url, errors):
    open_page(page, base_url + "/index.html?source=demo&matrix=abstracted&locality=high-arctic-78-n&date=2026-12-21")
    assert min(stop_opacities(page)) > 0.5
    assert errors == []


def test_midnight_sun_is_never_shaded(page, base_url, errors):
    open_page(page, base_url + "/index.html?source=demo&matrix=abstracted&locality=high-arctic-78-n&date=2026-06-21")
    assert max(stop_opacities(page)) == 0
    assert errors == []

################################################################################
## Export
################################################################################

def test_export_png(page, base_url, errors, tmp_path):
    open_page(page, base_url + ABSTRACTED + "&group=provider")
    with page.expect_download() as info:
        page.locator("#sm-export button[data-format=png]").click()
    download = info.value
    assert download.suggested_filename == "abstracted_mid-north-40-n_2026-10-28_provider.png"
    path = tmp_path / download.suggested_filename
    download.save_as(path)
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert errors == []


def test_export_svg_carries_provenance(page, base_url, errors, tmp_path):
    open_page(page, base_url + SIMPLIFIED + "&title=0")
    with page.expect_download() as info:
        page.locator("#sm-export button[data-format=svg]").click()
    download = info.value
    assert download.suggested_filename == "simplified_mid-north-40-n_2026-10-28.svg"
    path = tmp_path / download.suggested_filename
    download.save_as(path)
    svg = path.read_text()
    assert "Simplified Sync Matrix" in svg  # title added even with title=0
    assert "ICOD: 28 Oct 2026 @ 1200Z" in svg and "DEMO DATA" in svg
    assert "Data: /data/simplified/mid-north-40-n/2026-10-28.json" in svg
    assert "var(--" not in svg  # self-contained
    assert errors == []

################################################################################
## Embedding
################################################################################

def test_single_file_mode_shows_icod_in_footer(page, base_url, errors):
    open_page(page, base_url + "/index.html?data=data/simplified/mid-north-40-n/%s.json" % DAY)
    expect(page.locator(".sm-toolbar")).to_be_hidden()
    expect(page.locator(".sm-icod")).to_contain_text("ICOD: 28 Oct 2026 @ 1200Z")
    assert errors == []


def test_dashboard_iframe_receives_clicks(page, base_url, errors):
    page.goto(base_url + "/demo_dashboard.html")
    frame = page.frame_locator("#matrix")
    frame.locator(".sm-event").first.click()
    expect(page.locator("#log")).to_contain_text("event-click")
    expect(page.locator("#log")).to_contain_text("sync-matrix:ready")
    assert errors == []

################################################################################
## Predicted passes (web/live)
################################################################################

def test_predicted_pass_library(page, base_url, errors):
    open_page(page, base_url + "/index.html?manifest=live/index.json&matrix=abstracted&locality=mid-north-40-n")
    badge = page.locator("#sm-icod-badge")
    expect(badge).to_contain_text("ICOD")
    expect(badge).not_to_contain_text("DEMO DATA")  # real orbit data, not demo
    labels = page.locator(".sm-event").evaluate_all("els => els.map(e => e.getAttribute('aria-label'))")
    assert labels and all(" pass" in l for l in labels)
    assert "Predicted" in texts(page, ".sm-legend text")
    page.locator("#sm-matrix").select_option("simplified")
    page.wait_for_selector("svg.sm-root .sm-event")
    assert any(re.search(r"\d+ (EO|IR|SAR) pass", l) for l in
               page.locator(".sm-event").evaluate_all("els => els.map(e => e.getAttribute('aria-label'))"))
    assert errors == []


def test_popup_shows_the_phenomenology_provenance(page, base_url, errors):
    open_page(page, base_url + "/index.html?manifest=live/index.json&matrix=abstracted&locality=mid-north-40-n&group=provider")
    page.locator(".sm-event").first.hover()
    tip = page.locator(".sm-tooltip")
    expect(tip).to_contain_text("provenance")
    expect(tip).to_contain_text("Celestrak")
    expect(tip).to_contain_text("predicted pass")
    assert errors == []


def test_strips_use_phenomenology_colours(page, base_url, errors):
    open_page(page, base_url + ABSTRACTED)
    fills = page.locator("svg.sm-root rect[fill]").evaluate_all("els => els.map(e => e.getAttribute('fill'))")
    for colour in ("#08519c", "#cb181d", "#525252"):
        assert colour in fills
    assert errors == []


def test_export_lists_provenance_per_phenomenology(page, base_url, errors, tmp_path):
    open_page(page, base_url + "/index.html?manifest=live/index.json&matrix=simplified&locality=mid-north-40-n")
    with page.expect_download() as info:
        page.locator("#sm-export button[data-format=svg]").click()
    path = tmp_path / "x.svg"
    info.value.save_as(path)
    svg = path.read_text()
    assert "Source: Predicted passes from Celestrak orbits" in svg
    for line in ("EO · ICOD", "IR · ICOD", "SAR · ICOD", "COM · No data source for COM · ICOD not provided"):
        assert line in svg
    assert "fill:#238b45" in svg and "fill:#08519c" in svg  # colour chips
    assert errors == []


def box_colours(page):
    return page.locator(".sm-event").evaluate_all("""els => els.map(g => {
        const r = g.querySelector('rect');
        return [g.getAttribute('aria-label'), r.getAttribute('stroke'), r.getAttribute('stroke-dasharray'), r.getAttribute('fill')];
    })""")


def check_boxes(boxes, expected):
    seen = set()
    for label, stroke, dash, fill in boxes:
        for key, (colour, tint) in expected.items():
            if key in label:
                assert (stroke, fill) == (colour, tint), label
                seen.add(colour)
        assert dash is None             # solid outline
    return seen


def test_boxes_take_the_colour_of_the_group_shown(page, base_url, errors):
    live = base_url + "/index.html?manifest=live/index.json&matrix=abstracted&locality=mid-north-40-n"
    # Phenomenology: EO blue, IR red, SAR grey.
    open_page(page, live)
    seen = check_boxes(box_colours(page), {
        "WorldView": ("#08519c", "#c6dbef"), "Legion": ("#08519c", "#c6dbef"), "MODIS": ("#cb181d", "#fcbba1"),
        "VIIRS": ("#cb181d", "#fcbba1"), "Capella": ("#525252", "#d9d9d9"), "Sentinel-1": ("#525252", "#d9d9d9")})
    assert seen == {"#08519c", "#cb181d", "#525252"}
    # Provider: Vantor purple, Copernicus blue, NASA FIRMS red, Capella grey; strips match.
    page.get_by_role("radio", name="Provider").click()
    seen = check_boxes(box_colours(page), {
        "WorldView": ("#6a51a3", "#dadaeb"), "Legion": ("#6a51a3", "#dadaeb"), "SENTINEL": ("#08519c", "#c6dbef"),
        "MODIS": ("#cb181d", "#fcbba1"), "VIIRS": ("#cb181d", "#fcbba1"), "Capella": ("#525252", "#d9d9d9")})
    assert {"#6a51a3", "#cb181d", "#525252"} <= seen
    strips = page.locator("svg.sm-root rect[fill]").evaluate_all("els => els.map(e => e.getAttribute('fill'))")
    assert "#6a51a3" in strips
    assert errors == []


def test_city_locality_quarter_hour_timezone(page, base_url, errors):
    # Kathmandu is UTC+5:45: its timezone shows in the Locality dropdown and its passes load.
    open_page(page, base_url + "/index.html?manifest=live/index.json&matrix=abstracted&locality=kathmandu")
    expect(page.locator(".sm-subtitle")).to_contain_text("Kathmandu")
    assert "Kathmandu (Asia/Kathmandu)" in texts(page, "#sm-locality option")
    assert page.locator(".sm-event").count() > 0
    assert errors == []
