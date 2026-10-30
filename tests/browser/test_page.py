"""Browser tests for web/index.html: what reviews have been checking by hand.

Runs the real page in headless Chromium against the committed library
(web/live). Layout tests use the Demo locality on a fixed date, so results
don't depend on today's date or the latest orbits.
"""

import json
import re
import sys
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

from conftest import WEB

sys.path.insert(0, str(WEB.parent / "python"))
import export_payload as ep  # noqa: E402

DAY = "2026-10-28"
ABSTRACTED = "/index.html?matrix=abstracted&locality=demo&date=%s" % DAY
SIMPLIFIED = "/index.html?matrix=simplified&locality=demo&date=%s" % DAY


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
    assert "locality" in query(page) and "date" in query(page)
    assert query(page)["locality"] != "demo"
    assert texts(page, "#sm-matrix option") == ["Abstracted Sync Matrix", "Simplified Sync Matrix"]
    expect(page.locator("#sm-icod-badge")).not_to_contain_text("DEMO DATA")
    assert texts(page, ".sm-legend text") == []  # one status (Predicted): no legend
    assert page.locator("#sm-source").count() == 0  # no Data switch: Demo is a locality
    assert errors == []


def demo_day_after_switch(current: str, today: str) -> str:
    """The day the page lands on when switching to Demo: the same order as select() in sync_matrix.js."""
    workflow = json.loads((WEB.parent / "config" / "workflow.json").read_text())
    days = sorted((d["date"] for d in workflow["libraries"]["demo"]["days"]), reverse=True)
    return current if current in days else today if today in days else days[0]


def test_demo_day_fallback_order():
    # The cases test_demo_is_a_locality meets depending on the calendar.
    assert demo_day_after_switch("2026-10-31", "2026-10-31") == "2026-12-21"  # neither is a demo day: newest
    assert demo_day_after_switch("2026-10-29", "2026-10-28") == "2026-10-28"  # today is a demo day
    assert demo_day_after_switch("2026-12-21", "2026-12-20") == "2026-12-21"  # the current day is one


@pytest.mark.parametrize("frozen", [None, "2026-10-28T15:00:00Z"], ids=["today", "on-a-demo-day"])
def test_demo_is_a_locality(page, base_url, errors, frozen):
    if frozen:
        page.clock.set_fixed_time(frozen)  # the page's "today" is a demo day
    open_page(page, base_url + "/index.html?matrix=simplified&locality=mid-north-40-n")
    current = query(page)["date"]
    today = page.evaluate("new Date().toISOString().slice(0, 10)")  # the page's own "today" (UTC)
    page.locator("#sm-locality").select_option("demo")
    expect(page.locator("#sm-icod-badge")).to_contain_text("DEMO DATA")
    assert query(page)["matrix"] == "simplified" and query(page)["locality"] == "demo"
    assert query(page)["date"] == demo_day_after_switch(current, today)
    assert texts(page, "#sm-locality option")[-1] == "Demo (generated sample)"
    page.locator("#sm-locality").select_option("london")
    expect(page.locator("#sm-icod-badge")).not_to_contain_text("DEMO DATA")
    assert errors == []


def test_abstracted_layout(page, base_url, errors):
    open_page(page, base_url + ABSTRACTED)
    expect(page.locator(".sm-title")).to_have_text("Abstracted Sync Matrix")
    expect(page.locator(".sm-subtitle")).to_have_text("Demo · 28 October 2026")
    assert texts(page, ".sm-group-label") == ["EO", "IR", "SAR", "RF"]
    assert page.locator(".sm-row-label").count() == 61
    hours = texts(page, ".sm-axis .tick text")
    assert hours[0] == "0000Z" and hours[-1] == "2300Z" and len(hours) == 24
    assert errors == []


def test_localities_run_north_to_south(page, base_url, errors):
    open_page(page, base_url + ABSTRACTED)
    names = [re.sub(r" \(.*\)$", "", t) for t in texts(page, "#sm-locality option")]
    # Every locality in config/workflow.json, sorted north to south, then Demo.
    workflow = json.loads((WEB.parent / "config" / "workflow.json").read_text())
    by_lat = sorted(workflow["localities"], key=lambda l: -float(l["point"].split()[-1].rstrip(")")))
    assert names == [l["name"] for l in by_lat] + [workflow["libraries"]["demo"]["locality"]["name"]]
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
    assert texts(page, ".sm-group-label") == ["Capella", "Copernicus", "HawkEye 360", "NASA FIRMS", "Unseenlabs", "Vantor"]
    assert query(page)["group"] == "provider"
    events_after = sorted(page.locator(".sm-event").evaluate_all("els => els.map(e => e.getAttribute('aria-label'))"))
    assert events_after == events_before
    page.get_by_role("radio", name="Phenomenology").click()
    assert "group" not in query(page)
    assert errors == []


def test_simplified_is_always_phenomenology(page, base_url, errors):
    open_page(page, base_url + SIMPLIFIED + "&group=provider")
    expect(page.locator("#sm-grouping")).to_be_hidden()
    assert texts(page, ".sm-group-label") == ["EO", "IR", "SAR", "RF"]  # the matrix's groups, in its order
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


def open_payload(page: Page, base_url: str, payload: dict, toolbar: bool = False):
    """A payload built here, so tests don't depend on the library's dates.

    Single-file mode (no toolbar) by default; with toolbar=True a one-entry
    manifest serves it, so the toolbar and its ICOD badge show.
    """
    page.route(base_url + "/fixture.json", lambda route: route.fulfill(json=payload))
    if not toolbar:
        open_page(page, base_url + "/index.html?data=fixture.json")
        return
    manifest = {"version": 1, "matrices": [{"id": "abstracted", "label": payload["title"], "title": payload["title"],
                "localities": [{"id": "london", "name": "London", "lat": 51.5,
                                "dates": [{"date": "2026-10-28", "file": "fixture.json", "events": 1}]}]}]}
    page.route(base_url + "/fixture-index.json", lambda route: route.fulfill(json=manifest))
    open_page(page, base_url + "/index.html?manifest=fixture-index.json")


def high_arctic(day: str) -> dict:
    config = ep.load_config(WEB.parent / "config" / "matrix.json", "abstracted")
    return ep.build_payload(config, day=date.fromisoformat(day), demo_count=1, icod=day + "T12:00:00Z",
                            locality={"name": "High Arctic 78°N", "point": "POINT(16 78)"})


def test_polar_night_is_shaded_all_day(page, base_url, errors):
    open_payload(page, base_url, high_arctic("2026-12-21"))
    assert min(stop_opacities(page)) > 0.5
    assert errors == []


def test_midnight_sun_is_never_shaded(page, base_url, errors):
    open_payload(page, base_url, high_arctic("2026-06-21"))
    assert max(stop_opacities(page)) == 0
    assert errors == []

################################################################################
## ICOD age
################################################################################

ICOD = "2026-10-28T06:00:00Z"


def dated_payload(**changes) -> dict:
    """A real-data (not demo) payload with ICOD 28 Oct 0600Z and the committed matrix's ageing thresholds."""
    config = ep.load_config(WEB.parent / "config" / "matrix.json", "abstracted")
    payload = ep.build_payload(config, [{"row": "Legion-3", "start": "2026-10-28T08:00:00Z",
                                         "end": "2026-10-28T08:10:00Z", "status": "Predicted"}],
                               day=date(2026, 10, 28), icod=ICOD, icod_source="celestrak",
                               locality={"name": "London", "point": "POINT(-0.1278 51.5074)"})
    payload.update(changes)
    return payload


@pytest.mark.parametrize("now, state, word", [
    ("2026-10-28T16:00:00Z", "fresh", None),       # 10 h: under 30 h
    ("2026-10-29T22:00:00Z", "ageing", "AGEING"),  # 40 h: from 30 h
    ("2026-10-30T18:00:00Z", "stale", "STALE"),    # 60 h: from 54 h
])
def test_icod_badge_shows_the_age(page, base_url, errors, now, state, word):
    page.clock.set_fixed_time(now)
    open_payload(page, base_url, dated_payload(), toolbar=True)
    badge = page.locator("#sm-icod-badge")
    expect(badge).to_have_attribute("data-state", state)
    for other in ("AGEING", "STALE"):
        (expect(badge).to_contain_text if other == word else expect(badge).not_to_contain_text)(other)
    expect(badge).to_have_attribute("title", re.compile("Fresh under 30 h, ageing from 30 h, stale from 54 h"))
    assert errors == []


def test_icod_age_without_thresholds_is_unrated(page, base_url, errors):
    page.clock.set_fixed_time("2026-10-30T18:00:00Z")
    open_payload(page, base_url, dated_payload(icod_ageing=None), toolbar=True)
    expect(page.locator("#sm-icod-badge")).to_have_attribute("data-state", "unrated")
    expect(page.locator("#sm-icod-badge")).not_to_contain_text("STALE")
    assert errors == []


def test_demo_badge_is_grey_whatever_its_age(page, base_url, errors):
    open_page(page, base_url + ABSTRACTED)  # demo ICOD 28 Oct 1200Z, days old by now
    expect(page.locator("#sm-icod-badge")).to_have_attribute("data-state", "demo")
    expect(page.locator("#sm-icod-badge")).not_to_contain_text("STALE")
    assert errors == []


def test_embedded_demo_footer_is_not_red(page, base_url, errors):
    # Demo is grey everywhere: the footer sentence is only red when the ICOD is missing.
    open_page(page, base_url + "/index.html?data=live/abstracted/demo/%s.json" % DAY)
    expect(page.locator(".sm-icod-dot")).to_have_attribute("data-state", "demo")
    expect(page.locator(".sm-icod")).not_to_have_class(re.compile(r"\bwarn\b"))
    expect(page.locator(".sm-icod")).to_contain_text("DEMO DATA")
    assert errors == []


def test_embedded_footer_without_icod_is_red(page, base_url, errors):
    open_payload(page, base_url, dated_payload(icod=None, provenance={}))
    expect(page.locator(".sm-icod")).to_have_class(re.compile(r"\bwarn\b"))
    expect(page.locator(".sm-icod-dot")).to_have_attribute("data-state", "missing")
    assert errors == []


def test_embedded_footer_shows_the_age(page, base_url, errors):
    # Toolbar hidden (single-file mode): the footer carries the ICOD, with a dot in the badge's colour.
    page.clock.set_fixed_time("2026-10-29T22:00:00Z")
    open_payload(page, base_url, dated_payload())
    expect(page.locator(".sm-icod")).to_contain_text("(40h 0m ago · ageing)")
    expect(page.locator(".sm-icod-dot")).to_have_attribute("data-state", "ageing")
    assert errors == []

################################################################################
## Export
################################################################################

def test_export_png(page, base_url, errors, tmp_path):
    open_page(page, base_url + ABSTRACTED + "&group=provider")
    with page.expect_download() as info:
        page.locator("#sm-export button[data-format=png]").click()
    download = info.value
    assert download.suggested_filename == "abstracted_demo_2026-10-28_provider.png"
    path = tmp_path / download.suggested_filename
    download.save_as(path)
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert errors == []


def test_export_svg_carries_provenance(page, base_url, errors, tmp_path):
    open_page(page, base_url + SIMPLIFIED + "&title=0")
    with page.expect_download() as info:
        page.locator("#sm-export button[data-format=svg]").click()
    download = info.value
    assert download.suggested_filename == "simplified_demo_2026-10-28.svg"
    path = tmp_path / download.suggested_filename
    download.save_as(path)
    svg = path.read_text()
    assert "Simplified Sync Matrix" in svg  # title added even with title=0
    assert "ICOD: 28 Oct 2026 @ 1200Z" in svg and "DEMO DATA" in svg
    assert "Data: /live/simplified/demo/2026-10-28.json" in svg
    assert "var(--" not in svg  # self-contained
    assert errors == []

################################################################################
## Embedding
################################################################################

def test_single_file_mode_shows_icod_in_footer(page, base_url, errors):
    open_page(page, base_url + "/index.html?data=live/simplified/demo/%s.json" % DAY)
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
    assert texts(page, ".sm-legend text") == []  # every window is Predicted: nothing to explain
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
    for line in ("EO · ICOD", "IR · ICOD", "SAR · ICOD"):
        assert line in svg
    assert "COM" not in svg  # the dummy COM row is gone
    assert "fill:#cb181d" in svg and "fill:#08519c" in svg  # colour chips
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


def test_each_place_shows_only_what_it_evaluates(page, base_url, errors):
    # Same matrix, different data: the groups drawn follow each place's data file.
    open_page(page, base_url + "/index.html?matrix=abstracted&locality=mile-201")
    assert texts(page, ".sm-group-label") == ["RF"]                     # dark-ships example: RF only
    page.get_by_role("radio", name="Provider").click()
    assert texts(page, ".sm-group-label") == ["HawkEye 360", "Unseenlabs"]
    page.locator("#sm-locality").select_option("gulf-of-guinea")      # HE360 only: one provider
    expect(page.locator(".sm-group-label")).to_have_text(["HawkEye 360"])
    page.get_by_role("radio", name="Phenomenology").click()
    expect(page.locator(".sm-group-label")).to_have_text(["RF"])
    assert page.locator(".sm-row-label").count() == 15
    for locality, groups in (("london", ["EO", "SAR"]), ("tokyo", ["EO", "SAR", "RF"]), ("gao", ["IR"]),
                             ("tehran", ["EO", "IR", "SAR", "RF"])):
        page.locator("#sm-locality").select_option(locality)
        expect(page.locator(".sm-group-label")).to_have_text(groups)  # waits for the redraw
    page.locator("#sm-matrix").select_option("simplified")
    page.wait_for_selector("svg.sm-root .sm-event")
    assert texts(page, ".sm-group-label") == ["EO", "IR", "SAR", "RF"]
    assert errors == []


def test_status_legend_only_when_statuses_differ(page, base_url, errors):
    two = dated_payload()
    two["events"].append(dict(two["events"][0], start="2026-10-28T12:00:00Z", end="2026-10-28T12:10:00Z",
                              status="Collected"))
    open_payload(page, base_url, two)
    assert sorted(texts(page, ".sm-legend text")) == ["Collected", "Predicted"]
    assert errors == []


def boxes_overlap(a, b):
    return not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"] or
                a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])


@pytest.mark.parametrize("now", ["2026-10-28T00:03:00Z", "2026-10-28T12:30:00Z", "2026-10-28T23:57:00Z"],
                         ids=["start-of-day", "midday", "end-of-day"])
@pytest.mark.parametrize("width", [1280, 375], ids=["desktop", "phone"])
def test_now_tag_sits_above_the_hour_labels(page, base_url, errors, now, width):
    # The NOW tag has its own slot between the title and the hour labels: it covers neither, and stays over the plot.
    page.set_viewport_size({"width": width, "height": 800})
    page.clock.set_fixed_time(now)
    open_payload(page, base_url, dated_payload(), toolbar=True)
    expect(page.locator(".sm-now-tag")).to_have_text("NOW " + now[11:13] + now[14:16] + "Z")
    page.wait_for_timeout(300)  # let the resize redraw settle before measuring
    expect(page.locator("rect.sm-now-tag-bg")).to_be_visible()
    tag = page.locator("rect.sm-now-tag-bg").bounding_box()
    for selector in (".sm-title", ".sm-subtitle", ".sm-axis .tick text"):
        for i in range(page.locator(selector).count()):
            assert not boxes_overlap(tag, page.locator(selector).nth(i).bounding_box()), (selector, i)
    plot = page.locator(".sm-frame").bounding_box()
    assert plot["x"] - 0.5 <= tag["x"] and tag["x"] + tag["width"] <= plot["x"] + plot["width"] + 0.5
    assert tag["y"] + tag["height"] < min(page.locator(".sm-axis .tick text").nth(i).bounding_box()["y"]
                                          for i in range(page.locator(".sm-axis .tick text").count()))
    assert errors == []


def test_no_now_tag_on_another_day(page, base_url, errors):
    page.clock.set_fixed_time("2026-10-29T12:00:00Z")  # the chart is 28 Oct
    open_payload(page, base_url, dated_payload(), toolbar=True)
    assert page.locator(".sm-now-mark, .sm-now").count() == 0
    assert errors == []


def test_city_locality_quarter_hour_timezone(page, base_url, errors):
    # Kathmandu is UTC+5:45: its timezone shows in the Locality dropdown and its passes load.
    open_page(page, base_url + "/index.html?manifest=live/index.json&matrix=abstracted&locality=kathmandu")
    expect(page.locator(".sm-subtitle")).to_contain_text("Kathmandu")
    assert "Kathmandu (Asia/Kathmandu)" in texts(page, "#sm-locality option")
    assert page.locator(".sm-event").count() > 0
    assert errors == []
