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

MATRIX_CONFIG = WEB.parent / "config" / "matrix.json"

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
    config = ep.load_config(MATRIX_CONFIG, "abstracted")
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
    config = ep.load_config(MATRIX_CONFIG, "abstracted")
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

################################################################################
## Security labels
################################################################################

def labelled_payload(*labels, ceiling="RESTRICTED") -> dict:
    """One Legion-3 window per label, an hour apart (temporary fixture: never written under web/ or data/)."""
    payload = dated_payload()
    payload["events"] = [{"row": "Legion-3", "start": "2026-10-28T%02d:00:00Z" % (8 + i),
                          "end": "2026-10-28T%02d:10:00Z" % (8 + i), "status": "Predicted", "seclab": label,
                          "label": "%s pass" % label} for i, label in enumerate(labels)]
    payload["seclabs"] = ep.published_seclabs(ep.load_config(MATRIX_CONFIG), ceiling)
    return payload


def test_seclab_banner_is_at_the_very_top_and_bottom(page, base_url, errors):
    open_page(page, base_url + ABSTRACTED)
    assert texts(page, ".sm-seclab text") == ["UNCLASSIFIED", "UNCLASSIFIED"]
    svg = page.locator("svg.sm-root").bounding_box()
    top, bottom = (page.locator(".sm-seclab rect").nth(i).bounding_box() for i in (0, 1))
    assert top["y"] == svg["y"] and top["width"] == svg["width"]
    assert bottom["y"] + bottom["height"] == pytest.approx(svg["y"] + svg["height"])
    assert top["y"] + top["height"] <= page.locator(".sm-title").bounding_box()["y"]
    assert page.locator(".sm-seclab rect").first.get_attribute("fill") == "#1a9850"  # from the payload
    page.locator(".sm-event").first.hover()
    chip = page.locator(".sm-tooltip .sm-tooltip-seclab")
    expect(chip).to_have_text("UNCLASSIFIED")
    # Centred across the top of the popup, before anything else in it.
    assert page.locator(".sm-tooltip > *").first.get_attribute("class") == "sm-tooltip-seclab"
    tip, band = page.locator(".sm-tooltip").bounding_box(), chip.bounding_box()
    assert band["y"] == pytest.approx(tip["y"], abs=1) and band["width"] == pytest.approx(tip["width"], abs=1)
    assert chip.evaluate("el => getComputedStyle(el).textAlign") == "center"
    assert errors == []


def test_banner_shows_the_highest_label_and_each_popup_its_own(page, base_url, errors):
    open_payload(page, base_url, labelled_payload("UNCLASSIFIED", "RESTRICTED", "UNCLASSIFIED"))
    assert texts(page, ".sm-seclab text") == ["RESTRICTED", "RESTRICTED"]
    assert page.locator(".sm-seclab rect").first.get_attribute("fill") == "#f46d43"
    expect(page.locator(".sm-seclab title").first).to_contain_text("highest label among the accesses shown")
    for i, label in enumerate(["UNCLASSIFIED", "RESTRICTED", "UNCLASSIFIED"]):
        page.locator(".sm-event").nth(i).hover()
        expect(page.locator(".sm-tooltip .sm-tooltip-seclab")).to_have_text(label)
    assert errors == []


def test_banner_ranks_by_position_not_spelling(page, base_url, errors):
    # Swap the order: with UNCLASSIFIED listed last, it is the higher label.
    payload = labelled_payload("RESTRICTED", "UNCLASSIFIED", ceiling="UNCLASSIFIED")
    payload["seclabs"]["labels"] = ep.load_config(MATRIX_CONFIG)["seclabs"][::-1]
    open_payload(page, base_url, payload)
    assert texts(page, ".sm-seclab text") == ["UNCLASSIFIED", "UNCLASSIFIED"]
    assert errors == []


def test_chart_without_accesses_shows_the_ceiling(page, base_url, errors):
    payload = labelled_payload(ceiling="UNCLASSIFIED")
    page.route(base_url + "/fixture.json", lambda route: route.fulfill(json=payload))
    page.goto(base_url + "/index.html?data=fixture.json")
    page.wait_for_selector("svg.sm-root .sm-seclab")
    assert texts(page, ".sm-seclab text") == ["UNCLASSIFIED", "UNCLASSIFIED"]
    expect(page.locator(".sm-seclab title").first).to_contain_text("ceiling (no accesses shown)")
    assert errors == []


@pytest.mark.parametrize("title", ["1", "0"], ids=["page-title", "export-title"])
def test_export_is_marked_at_its_top_and_bottom(page, base_url, errors, tmp_path, title):
    # With the page's title, and with title=0 (the export adds the title under the top banner).
    open_payload(page, base_url, labelled_payload("UNCLASSIFIED", "RESTRICTED"), toolbar=True)
    page.goto(page.url + "&title=" + title)
    page.wait_for_selector("svg.sm-root .sm-event")
    with page.expect_download() as info:
        page.locator("#sm-export button[data-format=svg]").click()
    path = tmp_path / "x.svg"
    info.value.save_as(path)
    svg = path.read_text()
    assert svg.count(">RESTRICTED</text>") == 2 and ">UNCLASSIFIED</text>" not in svg
    assert "Security label: RESTRICTED (highest among accesses shown)" in svg
    height = float(re.search(r'<svg[^>]* height="([\d.]+)"', svg).group(1))
    offsets = [float(y) for y in re.findall(r'class="sm-seclab" transform="translate\(0,([\d.]+)\)"', svg)]
    assert offsets == [0, height - 18]
    assert errors == []

################################################################################
## Collection request (demonstration)
################################################################################

PASS = {"peak": "2026-10-28T08:05:00Z", "elevation": 71.4, "azimuth": 192.3,
        "sun_elevation": 18.2, "sun_azimuth": 141.7}
BEFORE_PASS = "2026-10-28T07:00:00Z"


def request_payload(**event) -> dict:
    """dated_payload's Legion-3 window (08:00-08:10Z on 28 Oct) as a predicted pass of one satellite."""
    payload = dated_payload()
    payload["events"][0].update({"id": "Legion-3-58001-0805Z", "norad": 58001, "label": "LEGION-3 pass",
                                 "seclab": "UNCLASSIFIED", "pass": PASS, **event})
    return payload


def open_in_parent(page: Page, base_url: str, payload: dict):
    """The chart in an iframe whose parent records every message it is sent."""
    page.route(base_url + "/fixture.json", lambda route: route.fulfill(json=payload))
    parent = """<!doctype html><meta charset="utf-8"><body><script>
      window.received = [];
      window.addEventListener("message", (ev) => { if (ev.origin === location.origin) window.received.push(ev.data); });
    </script><iframe id="matrix" style="width:1100px;height:700px"
      src="index.html?data=fixture.json&origin=%s"></iframe></body>""" % base_url
    page.route(base_url + "/parent.html", lambda route: route.fulfill(body=parent, content_type="text/html"))
    page.goto(base_url + "/parent.html")
    frame = page.frame_locator("#matrix")
    frame.locator("svg.sm-root .sm-event").first.wait_for()
    return frame


def test_clicking_an_access_pins_its_popup_with_the_request_link(page, base_url, errors):
    page.clock.set_fixed_time(BEFORE_PASS)
    open_payload(page, base_url, request_payload())
    tip = page.locator(".sm-tooltip")
    page.locator(".sm-event").first.hover()
    expect(tip.locator(".sm-request-hint")).to_have_text("Click to request collection")
    expect(tip.locator(".sm-request-link")).to_have_count(0)  # a hovered popup moves with the pointer
    page.locator(".sm-event").first.click()
    expect(tip).to_have_class(re.compile(r"\bpinned\b"))
    expect(tip.locator(".sm-request-link")).to_have_text("Submit Collection Request")
    page.mouse.move(5, 5)  # leaving the access no longer closes it
    expect(tip).to_be_visible()
    page.keyboard.press("Escape")
    expect(tip).to_be_hidden()
    page.locator(".sm-event").first.click()
    tip.locator(".sm-tooltip-close").click()
    expect(tip).to_be_hidden()
    page.locator(".sm-event").first.click()
    page.locator(".sm-title").click()  # a click elsewhere closes it too
    expect(tip).to_be_hidden()
    assert errors == []


def test_request_is_shown_not_sent_and_offered_to_the_dashboard(page, base_url, errors):
    page.clock.set_fixed_time(BEFORE_PASS)
    frame = open_in_parent(page, base_url, request_payload())
    frame.locator(".sm-event").first.click()
    frame.locator(".sm-request-link").click()
    demo = frame.locator(".sm-request-demo")
    expect(demo).to_be_visible()  # the popup stays open to show it
    expect(demo.locator("strong")).to_have_text("Demonstration — request not sent")
    shown = json.loads(demo.locator("pre").inner_text())
    page.wait_for_function("window.received.some(m => m.type === 'sync-matrix:collection-request')")
    [message] = [m for m in page.evaluate("window.received") if m["type"] == "sync-matrix:collection-request"]
    assert message["demonstration"] is True and message["request"] == shown
    assert shown["version"] == 1 and re.fullmatch(r"[0-9a-f-]{36}", shown["id"])
    assert shown["requested_at"] == BEFORE_PASS  # minted at the click
    assert "requester" not in shown
    assert shown["seclab"] == "UNCLASSIFIED"
    assert shown["access"] == {"id": "Legion-3-58001-0805Z", "satellite": "Legion-3", "norad": 58001,
                               "label": "LEGION-3 pass", "start": "2026-10-28T08:00:00Z",
                               "end": "2026-10-28T08:10:00Z", "status": "Predicted"}
    assert shown["pass"] == PASS
    assert shown["target"] == {"name": "London", "point": "POINT(-0.1278 51.5074)"}
    assert shown["icod"] == ICOD and shown["icod_source"] == "celestrak"
    assert errors == []


def test_keyboard_pins_the_popup_and_escape_returns_to_the_access(page, base_url, errors):
    page.clock.set_fixed_time(BEFORE_PASS)
    open_payload(page, base_url, request_payload())
    page.locator(".sm-event").first.focus()
    page.keyboard.press("Enter")
    expect(page.locator(".sm-tooltip")).to_have_class(re.compile(r"\bpinned\b"))
    expect(page.locator(".sm-request-link")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator(".sm-event").first).to_be_focused()
    expect(page.locator(".sm-tooltip")).not_to_have_class(re.compile(r"\bpinned\b"))
    assert errors == []


def test_request_without_pass_geometry_still_works(page, base_url, errors):
    # Real feeds may not give the peak geometry: the request carries "pass": null.
    page.clock.set_fixed_time(BEFORE_PASS)
    payload = request_payload()
    del payload["events"][0]["pass"]
    open_payload(page, base_url, payload)
    page.locator(".sm-event").first.click()
    page.locator(".sm-request-link").click()
    expect(page.locator(".sm-request-demo pre")).to_be_visible()
    assert json.loads(page.locator(".sm-request-demo pre").inner_text())["pass"] is None
    assert errors == []


@pytest.mark.parametrize("now, payload", [
    ("2026-10-28T08:05:00Z", request_payload()),                  # the access has started
    (BEFORE_PASS, request_payload(norad=None)),                   # no single satellite (e.g. a Simplified bar)
    (BEFORE_PASS, request_payload(seclab=None)),                  # no security label
    (BEFORE_PASS, dict(request_payload(), icod_source="demo")),   # demo data
], ids=["started", "no-norad", "no-seclab", "demo"])
def test_no_request_link_when_the_access_cannot_be_requested(page, base_url, errors, now, payload):
    page.clock.set_fixed_time(now)
    open_payload(page, base_url, payload)
    page.locator(".sm-event").first.hover()
    expect(page.locator(".sm-tooltip")).to_be_visible()
    expect(page.locator(".sm-tooltip .sm-request-hint")).to_have_count(0)
    page.locator(".sm-event").first.click()
    expect(page.locator(".sm-tooltip")).to_have_class(re.compile(r"\bpinned\b"))
    expect(page.locator(".sm-tooltip .sm-request-link")).to_have_count(0)
    assert errors == []


def test_live_simplified_and_demo_offer_no_requests(page, base_url, errors):
    page.clock.set_fixed_time("2026-10-01T00:00:00Z")  # before every committed day, so nothing has started
    for query_string in ("matrix=simplified&locality=tokyo", "matrix=abstracted&locality=demo"):
        open_page(page, base_url + "/index.html?manifest=live/index.json&" + query_string)
        page.locator(".sm-event").first.click()
        expect(page.locator(".sm-tooltip")).to_have_class(re.compile(r"\bpinned\b"))
        expect(page.locator(".sm-tooltip .sm-request-link")).to_have_count(0)
        page.keyboard.press("Escape")
    open_page(page, base_url + "/index.html?manifest=live/index.json&matrix=abstracted&locality=tokyo")
    page.locator(".sm-event").first.click()
    expect(page.locator(".sm-tooltip .sm-request-link")).to_have_count(1)  # a predicted pass of one satellite
    assert errors == []
