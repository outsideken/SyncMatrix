"""Browser tests for web/index.html: what reviews have been checking by hand.

Runs the real page in headless Chromium against the committed demo data.
Dates are passed explicitly, so results don't depend on today's date.
"""

import re
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, expect

DAY = "2026-10-28"
ABSTRACTED = "/index.html?matrix=abstracted&locality=mid-north-40-n&date=%s" % DAY
PARTNER = "/index.html?matrix=partner&locality=mid-north-40-n&date=%s" % DAY


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

def test_default_view_loads_from_the_manifest(page, base_url, errors):
    open_page(page, base_url + "/index.html")
    assert query(page)["matrix"] == "abstracted"
    assert "locality" in query(page) and "date" in query(page)
    assert texts(page, "#sm-matrix option") == ["Abstracted Sync Matrix", "Partner Sync Matrix"]
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
    assert names == ["High Arctic 78°N", "Arctic 70°N", "Subarctic 65°N", "Mid-north 40°N",
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


def test_partner_is_always_phenomenology(page, base_url, errors):
    open_page(page, base_url + PARTNER + "&group=provider")
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
    open_page(page, base_url + "/index.html?matrix=abstracted&locality=high-arctic-78-n&date=2026-12-21")
    assert min(stop_opacities(page)) > 0.5
    assert errors == []


def test_midnight_sun_is_never_shaded(page, base_url, errors):
    open_page(page, base_url + "/index.html?matrix=abstracted&locality=high-arctic-78-n&date=2026-06-21")
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
    open_page(page, base_url + PARTNER + "&title=0")
    with page.expect_download() as info:
        page.locator("#sm-export button[data-format=svg]").click()
    download = info.value
    assert download.suggested_filename == "partner_mid-north-40-n_2026-10-28.svg"
    path = tmp_path / download.suggested_filename
    download.save_as(path)
    svg = path.read_text()
    assert "PARTNER Sync Matrix" in svg  # title added even with title=0
    assert "ICOD: 28 Oct 2026 @ 1200Z" in svg and "DEMO DATA" in svg
    assert "Data: /data/partner/mid-north-40-n/2026-10-28.json" in svg
    assert "var(--" not in svg  # self-contained
    assert errors == []

################################################################################
## Embedding
################################################################################

def test_single_file_mode_shows_icod_in_footer(page, base_url, errors):
    open_page(page, base_url + "/index.html?data=data/partner/mid-north-40-n/%s.json" % DAY)
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
    page.locator("#sm-matrix").select_option("partner")
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
    open_page(page, base_url + "/index.html?manifest=live/index.json&matrix=partner&locality=mid-north-40-n")
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
