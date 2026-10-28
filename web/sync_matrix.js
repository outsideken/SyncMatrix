/* Sync Matrix renderer.
 *
 * Draws a payload produced by python/export_payload.py. Built to live in an
 * iframe: fills its frame, redraws on resize, and takes data two ways.
 *
 * Two ways to choose what to draw:
 *   - Library mode (default): read a manifest (data/index.json) listing every
 *     matrix and day, and show Matrix/Date dropdowns.
 *   - Single-file mode: data=<url> draws exactly that payload, no dropdowns.
 *
 * URL parameters
 *   manifest=<url>  Manifest to read in library mode (default: data/index.json).
 *   matrix=<id>     Initial matrix (default: first in the manifest).
 *   locality=<id>   Initial locality (default: first for that matrix). Each
 *                   file is one locality and one day; the Locality dropdown
 *                   only appears when a matrix has more than one.
 *   date=<Y-M-D>    Initial day (default: newest for that locality).
 *   controls=0      Hide the dropdowns (e.g. the dashboard drives selection itself).
 *   daylight=0      Start with day/night shading switched off (toolbar switch).
 *   icodmark=1      Draw the ICOD line and hatch the period after it (off by
 *                   default; ICOD is always shown in the badge and footer).
 *   data=<url>      Single-file mode. Works with a relative path, GitHub Pages
 *                   or raw.githubusercontent.com.
 *   refresh=<sec>   Re-fetch interval in seconds (default 0 = fetch once); in
 *                   library mode new days in the manifest appear in the dropdown.
 *   title=0         Hide the title block (the dashboard panel has its own header).
 *   theme=dark      Dark palette (default light).
 *   origin=<url>    Dashboard origin trusted for postMessage in both directions.
 *                   Without it only same-origin messages are accepted or sent.
 *
 * postMessage protocol
 *   in : {type: "sync-matrix:data", payload: {...}}       replace the data
 *   in : {type: "sync-matrix:select", matrix, locality, date}  choose from the manifest
 *   out: {type: "sync-matrix:ready"}                       sent once on load
 *   out: {type: "sync-matrix:selection", matrix, locality, date}  selection changed
 *   out: {type: "sync-matrix:event-click", event: {...}}  user clicked an event
 */

(function () {
  "use strict";

  //============================================================================
  // CONFIGURATION
  //============================================================================

  const params = new URLSearchParams(window.location.search);
  const options = {
    dataUrl: params.get("data"),
    manifestUrl: params.get("manifest") || "data/index.json",
    showControls: params.get("controls") !== "0",
    showDaylight: params.get("daylight") !== "0",
    showIcodMark: params.get("icodmark") === "1",
    refreshSeconds: Math.max(0, Number(params.get("refresh")) || 0),
    showTitle: params.get("title") !== "0",
    trustedOrigin: params.get("origin") || window.location.origin,
  };
  if (params.get("theme")) document.documentElement.dataset.theme = params.get("theme");

  const LAYOUT = {
    titleHeight: 42,
    axisHeight: 22,
    groupStripWidth: 18,
    labelGap: 8,
    marginRight: 14,
    rowMin: 18,
    rowMax: 44,
    bannerHeight: 24,
    footerHeight: 26,
    minLabelSpacing: 44,
  };
  const FALLBACK_EVENT_COLOR = "#ff8c00";

  const parseTime = d3.utcParse("%Y-%m-%dT%H:%M:%SZ");
  const formatTick = d3.utcFormat("%H%MZ");
  const formatFull = d3.utcFormat("%d %b %Y %H%MZ");
  const formatIcod = d3.utcFormat("%d %b %Y @ %H%MZ");
  const formatIcodShort = d3.utcFormat("%d %b %H%MZ");
  const ICOD_MEANING = "ICOD (Information Cut-Off Date): when the data was grabbed. " +
    "Anything received after it is not reflected in this matrix.";

  const container = d3.select("#sync-matrix");
  const statusEl = container.select(".sm-status");
  const tooltip = d3.select(".sm-tooltip");

  const toolbar = d3.select(".sm-toolbar");
  const matrixSelect = d3.select("#sm-matrix");
  const localitySelect = d3.select("#sm-locality");
  const localityPicker = d3.select("#sm-locality-picker");
  const dateSelect = d3.select("#sm-date");
  const olderButton = d3.select("#sm-older");
  const newerButton = d3.select("#sm-newer");
  const formatDateOption = d3.utcFormat("%a %d %b %Y");
  const parseDay = d3.utcParse("%Y-%m-%d");

  let current = null;     // last good payload, already parsed
  let manifest = null;    // library mode only
  let selection = { matrix: params.get("matrix"), locality: params.get("locality"), date: params.get("date") };
  let dataUrl = options.dataUrl;

  //============================================================================
  // DATA
  //============================================================================

  function parsePayload(raw) {
    if (!raw || !raw.window || !Array.isArray(raw.groups)) {
      throw new Error("Payload is missing window or groups");
    }
    const t = (s) => {
      const d = parseTime(s);
      if (!d) throw new Error("Bad timestamp: " + s);
      return d;
    };
    return {
      ...raw,
      window: { ...raw.window, start: t(raw.window.start), end: t(raw.window.end) },
      icod: raw.icod ? t(raw.icod) : null,
      events: (raw.events || []).map((e) => ({ ...e, start: t(e.start), end: t(e.end) })),
      daylight: raw.daylight && raw.daylight.elevations ? {
        ...raw.daylight,
        sun: Object.fromEntries(Object.entries(raw.daylight.sun || {}).map(([k, v]) => [k, t(v)])),
      } : null,
      markers: (raw.markers || []).map((m) => ({ ...m, time: t(m.time) })),
      banners: (raw.banners || []).map((b) => ({ ...b, start: t(b.start), end: t(b.end) })),
      status_colors: raw.status_colors || {},
    };
  }

  function setPayload(raw) {
    try {
      current = parsePayload(raw);
      setStatus("");
      render();
    } catch (err) {
      showError("Could not read payload: " + err.message);
    }
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }

  async function fetchPayload() {
    if (!dataUrl) return;
    const requested = dataUrl;
    try {
      const raw = await fetchJson(requested);
      // Ignore a slow response for a selection the user has already left.
      if (requested === dataUrl) setPayload(raw);
    } catch (err) {
      showError("Could not load " + requested + " (" + err.message + ")");
    }
  }

  //============================================================================
  // LIBRARY MODE: MANIFEST + DROPDOWNS
  //============================================================================

  async function loadManifest() {
    const raw = await fetchJson(options.manifestUrl);
    if (!raw || !Array.isArray(raw.matrices) || !raw.matrices.length) {
      throw new Error("manifest lists no matrices");
    }
    manifest = raw;
  }

  function matrixById(id) {
    return manifest.matrices.find((m) => m.id === id) || manifest.matrices[0];
  }

  function localityById(matrix, id) {
    return matrix.localities.find((l) => l.id === id) || matrix.localities[0];
  }

  // Each file is one matrix, one locality, one day. Changing one choice keeps
  // the others where that combination exists, else falls back to the first
  // locality / newest day.
  function select(want, { notify = true } = {}) {
    const matrix = matrixById(want.matrix);
    const locality = localityById(matrix, want.locality);
    const day = locality.dates.find((d) => d.date === want.date) || locality.dates[0];
    selection = { matrix: matrix.id, locality: locality.id, date: day.date };

    // Manifest paths are relative to the manifest, not to this page.
    dataUrl = new URL(day.file, new URL(options.manifestUrl, window.location.href)).href;

    updateControls();
    rememberSelection();
    if (notify) postToParent({ type: "sync-matrix:selection", ...selection });
    fetchPayload();
  }

  function currentDates() {
    return localityById(matrixById(selection.matrix), selection.locality).dates;
  }

  function updateControls() {
    if (!manifest) return;
    const matrix = matrixById(selection.matrix);
    const dates = currentDates();

    matrixSelect.selectAll("option").data(manifest.matrices, (m) => m.id).join("option")
      .attr("value", (m) => m.id)
      .text((m) => m.label || m.title);
    matrixSelect.property("value", matrix.id);

    localitySelect.selectAll("option").data(matrix.localities, (l) => l.id).join("option")
      .attr("value", (l) => l.id)
      .text((l) => l.name + (l.timezone ? " (" + l.timezone + ")" : ""));
    localitySelect.property("value", selection.locality);
    // Only worth a dropdown when this matrix has more than one locality.
    localityPicker.attr("hidden", matrix.localities.length > 1 ? null : true);

    const today = new Date().toISOString().slice(0, 10);
    dateSelect.selectAll("option").data(dates, (d) => d.date).join("option")
      .attr("value", (d) => d.date)
      .text((d) => formatDateOption(parseDay(d.date)) + (d.date === today ? " (today)" : "") +
        " · " + d.events + " events" +
        (d.icod ? " · ICOD " + formatIcodShort(parseTime(d.icod)) : " · no ICOD"));
    dateSelect.property("value", selection.date);

    // Dates are newest first, so "older" moves down the list.
    const i = dates.findIndex((d) => d.date === selection.date);
    olderButton.property("disabled", i >= dates.length - 1);
    newerButton.property("disabled", i <= 0);
  }

  function stepDate(delta) {
    const dates = currentDates();
    const i = dates.findIndex((d) => d.date === selection.date) + delta;
    if (i >= 0 && i < dates.length) select({ ...selection, date: dates[i].date });
  }

  function rememberSelection() {
    // Reflect the choice in the URL so a reload or shared link opens the same view.
    const url = new URL(window.location.href);
    for (const key of ["matrix", "locality", "date"]) url.searchParams.set(key, selection[key]);
    window.history.replaceState(null, "", url);
  }

  matrixSelect.on("change", (ev) => select({ ...selection, matrix: ev.target.value }));
  localitySelect.on("change", (ev) => select({ ...selection, locality: ev.target.value }));
  dateSelect.on("change", (ev) => select({ ...selection, date: ev.target.value }));
  olderButton.on("click", () => stepDate(1));
  newerButton.on("click", () => stepDate(-1));

  async function refresh() {
    if (manifest) {
      try {
        await loadManifest();
        updateControls(); // new days appear; the current view stays put
      } catch (err) {
        showError("Could not reload " + options.manifestUrl + " (" + err.message + ")");
      }
    }
    fetchPayload();
  }

  function setStatus(text) {
    statusEl.classed("error-banner", false).text(text);
  }

  function showError(text) {
    // Keep drawing the last good payload; just flag the failure in a corner.
    statusEl.classed("error-banner", Boolean(current)).text(text);
    console.error("[sync-matrix]", text);
  }

  //============================================================================
  // RENDER
  //============================================================================

  function measureLabelWidth(labels, className = "sm-row-label") {
    const probe = container.append("svg").attr("width", 0).attr("height", 0);
    let max = 0;
    probe.selectAll("text").data(labels).join("text")
      .attr("class", className).text((d) => d)
      .each(function () { max = Math.max(max, this.getBBox().width); });
    probe.remove();
    return Math.ceil(max);
  }

  function render() {
    if (!current) return;
    const p = current;
    const node = container.node();
    const width = node.clientWidth;
    const height = node.clientHeight;
    if (width < 50 || height < 50) return;

    container.select("svg.sm-root").remove();

    //--------------------------------------------------------------------------
    // Layout
    //--------------------------------------------------------------------------

    const rows = p.groups.flatMap((g) => g.rows.map((r) => ({ ...r, group: g })));
    const bannerLevels = p.banners.length ? d3.max(p.banners, (b) => b.level) + 1 : 0;

    // Group-only matrices (e.g. Partner: one row per group) show just the group
    // bar with a horizontal label; sub-group matrices (Abstracted) show a narrow
    // rotated group strip plus a label per row.
    const groupOnly = p.groups.every((g) => g.rows.length === 1);
    const stripWidth = groupOnly
      ? measureLabelWidth(p.groups.map((g) => g.label), "sm-group-label") + 2 * LAYOUT.labelGap
      : LAYOUT.groupStripWidth;

    const top = (options.showTitle ? LAYOUT.titleHeight : 6) + LAYOUT.axisHeight;
    const left = stripWidth + LAYOUT.labelGap +
      (groupOnly ? 0 : measureLabelWidth(rows.map((r) => r.label)) + LAYOUT.labelGap);
    const right = LAYOUT.marginRight;
    const bottom = bannerLevels * LAYOUT.bannerHeight + LAYOUT.footerHeight;

    const rowHeight = Math.max(LAYOUT.rowMin,
      Math.min(LAYOUT.rowMax, (height - top - bottom) / Math.max(rows.length, 1)));
    const plotWidth = Math.max(100, width - left - right);
    const plotHeight = rowHeight * rows.length;
    const svgHeight = top + plotHeight + bottom;

    const x = d3.scaleUtc().domain([p.window.start, p.window.end]).range([0, plotWidth]);
    const rowY = new Map(rows.map((r, i) => [r.id, i * rowHeight]));

    const svg = container.append("svg")
      .attr("class", "sm-root")
      .attr("width", width)
      .attr("height", svgHeight)
      .attr("role", "img")
      .attr("aria-label", (p.title || "Sync Matrix") + ", " + p.events.length + " events");

    //--------------------------------------------------------------------------
    // Title
    //--------------------------------------------------------------------------

    if (options.showTitle) {
      const title = svg.append("g").attr("transform", `translate(${left + plotWidth / 2},0)`);
      title.append("text").attr("class", "sm-title").attr("text-anchor", "middle").attr("y", 17).text(p.title || "");
      title.append("text").attr("class", "sm-subtitle").attr("text-anchor", "middle").attr("y", 33).text(p.subtitle || "");
    }

    const plot = svg.append("g").attr("transform", `translate(${left},${top})`);

    //--------------------------------------------------------------------------
    // Time axis (labels thinned to fit the width)
    //--------------------------------------------------------------------------

    const tickMinutes = p.window.tick_minutes || 30;
    const ticks = d3.utcMinute.every(tickMinutes).range(p.window.start, p.window.end);
    const pxPerTick = plotWidth / ticks.length;
    const labelEvery = Math.max(1, Math.ceil(LAYOUT.minLabelSpacing / pxPerTick));
    const labelled = ticks.filter((_, i) => i % labelEvery === 0);

    plot.append("g").attr("class", "sm-axis")
      .call(d3.axisTop(x).tickValues(labelled).tickFormat(formatTick).tickSize(4).tickPadding(3));

    //--------------------------------------------------------------------------
    // Background: night/twilight shading, grid, group dividers
    //--------------------------------------------------------------------------

    plot.append("rect").attr("class", "sm-plot-bg").attr("width", plotWidth).attr("height", plotHeight);
    updateDaylightToggle(p);
    if (p.daylight && options.showDaylight) drawDaylight(svg, plot, p, x, plotWidth, plotHeight);

    // After ICOD the picture may be incomplete: hatch from the ICOD to the window end.
    // Off by default to keep the chart simple; ICOD stays in the badge and footer.
    const afterIcod = options.showIcodMark && p.icod && p.icod < p.window.end;
    if (afterIcod) {
      const hatch = svg.append("defs").append("pattern")
        .attr("id", "sm-hatch").attr("patternUnits", "userSpaceOnUse")
        .attr("width", 8).attr("height", 8).attr("patternTransform", "rotate(45)");
      hatch.append("line").attr("class", "sm-hatch-line").attr("x1", 0).attr("x2", 0).attr("y1", 0).attr("y2", 8);
      const hx = Math.max(0, x(p.icod));
      plot.append("rect")
        .attr("x", hx).attr("width", plotWidth - hx)
        .attr("y", 0).attr("height", plotHeight)
        .attr("fill", "url(#sm-hatch)")
        .append("title").text("After ICOD: data received after " + formatIcod(p.icod) + " is not reflected.");
    }

    const grid = plot.append("g").attr("class", "sm-grid");
    grid.selectAll("line.v").data(ticks).join("line")
      .attr("class", (d) => "v" + (d.getUTCMinutes() === 0 ? " hour" : ""))
      .attr("x1", (d) => x(d)).attr("x2", (d) => x(d))
      .attr("y1", 0).attr("y2", plotHeight);
    grid.selectAll("line.h").data(d3.range(1, rows.length)).join("line")
      .attr("class", "h")
      .attr("x1", 0).attr("x2", plotWidth)
      .attr("y1", (i) => i * rowHeight).attr("y2", (i) => i * rowHeight);

    let offset = 0;
    const groupSpans = p.groups.map((g) => {
      const span = { group: g, y: offset * rowHeight, h: g.rows.length * rowHeight };
      offset += g.rows.length;
      return span;
    });

    plot.append("g").selectAll("line").data(groupSpans.slice(1)).join("line")
      .attr("class", "sm-divider")
      .attr("x1", groupOnly ? -LAYOUT.labelGap : -LAYOUT.groupStripWidth - LAYOUT.labelGap).attr("x2", plotWidth)
      .attr("y1", (d) => d.y).attr("y2", (d) => d.y);

    //--------------------------------------------------------------------------
    // Row labels and group strips
    //--------------------------------------------------------------------------

    if (!groupOnly) {
      plot.append("g").selectAll("text").data(rows).join("text")
        .attr("class", "sm-row-label")
        .attr("text-anchor", "end")
        .attr("dominant-baseline", "central")
        .attr("x", -LAYOUT.labelGap)
        .attr("y", (r) => rowY.get(r.id) + rowHeight / 2)
        .text((r) => r.label);
    }

    const stripX = -left;
    const strips = plot.append("g").selectAll("g").data(groupSpans).join("g")
      .attr("transform", (d) => `translate(${stripX},${d.y})`);
    strips.append("rect")
      .attr("width", stripWidth).attr("height", (d) => d.h)
      .attr("fill", (d) => d.group.color || "#525252");
    strips.append("title").text((d) => d.group.label);
    strips.append("text")
      .attr("class", "sm-group-label")
      .attr("text-anchor", "middle").attr("dominant-baseline", "central")
      .attr("transform", (d) => groupOnly
        ? `translate(${stripWidth / 2},${d.h / 2})`
        : `translate(${stripWidth / 2},${d.h / 2}) rotate(-90)`)
      .attr("fill", (d) => readableInk(d.group.color || "#525252"))
      .text((d) => d.group.label)
      .each(function (d) {
        // Hide the rotated label when the group is too short to hold it.
        if (!groupOnly && this.getComputedTextLength() > d.h - 4) d3.select(this).remove();
      });

    //--------------------------------------------------------------------------
    // Events
    //--------------------------------------------------------------------------

    const pad = Math.min(4, rowHeight * 0.15);
    const colorOf = (e) => p.status_colors[e.status] || FALLBACK_EVENT_COLOR;
    // Name events by what the Y-axis shows: the group (e.g. COM) in group-only
    // matrices, else the row. e.row stays the data's row id (e.g. CIRCUS).
    const rowById = new Map(rows.map((r) => [r.id, r]));
    const visibleEvents = p.events.filter((e) => rowY.has(e.row)).map((e) => {
      const r = rowById.get(e.row);
      return { ...e, group: r.group.label, where: groupOnly ? r.group.label : r.label };
    });

    const events = plot.append("g").selectAll("g").data(visibleEvents).join("g")
      .attr("class", "sm-event")
      .attr("tabindex", 0)
      .attr("role", "button")
      .attr("aria-label", (e) => `${e.label || "Event"}, ${e.where}, ${formatFull(e.start)} to ${formatTick(e.end)}`);

    events.append("rect")
      .attr("x", (e) => x(Math.max(e.start, p.window.start)) + 1.5)
      .attr("y", (e) => rowY.get(e.row) + pad)
      .attr("width", (e) => Math.max(6, x(Math.min(e.end, p.window.end)) - x(Math.max(e.start, p.window.start)) - 3))
      .attr("height", rowHeight - pad * 2)
      .attr("rx", 2)
      .attr("stroke", colorOf)
      .attr("fill", colorOf)
      .attr("fill-opacity", 0.14);

    events
      .on("mouseenter focus", (ev, e) => showTooltip(ev, e))
      .on("mousemove", (ev) => moveTooltip(ev))
      .on("mouseleave blur", hideTooltip)
      .on("click", (ev, e) => notifyClick(e))
      .on("keydown", (ev, e) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); notifyClick(e); } });

    //--------------------------------------------------------------------------
    // Markers: end of local day, now
    //--------------------------------------------------------------------------

    plot.append("g").selectAll("line").data(p.markers.filter((m) => m.kind === "end_of_local_day")).join("line")
      .attr("class", "sm-eod")
      .attr("x1", (m) => x(m.time)).attr("x2", (m) => x(m.time))
      .attr("y1", 0).attr("y2", plotHeight)
      .append("title").text((m) => m.label + " — " + formatFull(m.time));

    if (options.showIcodMark && p.icod && p.icod >= p.window.start && p.icod <= p.window.end) {
      const ix = x(p.icod);
      const flip = ix > plotWidth - 80;
      const icodMark = plot.append("g").attr("class", "sm-icod-mark");
      icodMark.append("line").attr("class", "sm-icod-line").attr("x1", ix).attr("x2", ix).attr("y1", 0).attr("y2", plotHeight);
      const tag = icodMark.append("text").attr("class", "sm-icod-tag")
        .attr("x", flip ? ix - 4 : ix + 4).attr("y", 11)
        .attr("text-anchor", flip ? "end" : "start")
        .text("ICOD " + formatTick(p.icod));
      const box = tag.node().getBBox();
      icodMark.insert("rect", "text").attr("class", "sm-icod-tag-bg")
        .attr("x", box.x - 2).attr("y", box.y - 1).attr("width", box.width + 4).attr("height", box.height + 2);
      icodMark.append("title").text(ICOD_MEANING);
    }

    const now = new Date();
    if (now >= p.window.start && now <= p.window.end) {
      const nx = x(now);
      plot.append("line").attr("class", "sm-now").attr("x1", nx).attr("x2", nx).attr("y1", 0).attr("y2", plotHeight);
      plot.append("text").attr("class", "sm-now-tag")
        .attr("x", nx + 3).attr("y", plotHeight - 4)
        .attr("text-anchor", nx > plotWidth - 60 ? "end" : "start")
        .attr("dx", nx > plotWidth - 60 ? -6 : 0)
        .text("NOW " + formatTick(now));
    }

    plot.append("rect").attr("class", "sm-frame").attr("width", plotWidth).attr("height", plotHeight);

    //--------------------------------------------------------------------------
    // Banners
    //--------------------------------------------------------------------------

    const banners = plot.append("g").attr("transform", `translate(0,${plotHeight})`)
      .selectAll("g").data(p.banners).join("g")
      .attr("class", "sm-banner")
      .attr("transform", (b) => `translate(${x(b.start)},${b.level * LAYOUT.bannerHeight})`);
    banners.append("rect")
      .attr("width", (b) => Math.max(0, x(b.end) - x(b.start)))
      .attr("height", LAYOUT.bannerHeight)
      .attr("fill", (b) => b.fill);
    banners.append("text")
      .attr("x", (b) => (x(b.end) - x(b.start)) / 2).attr("y", LAYOUT.bannerHeight / 2)
      .attr("text-anchor", "middle").attr("dominant-baseline", "central")
      .attr("fill", (b) => b.text_color || "#ffffff")
      .text((b) => b.text);

    //--------------------------------------------------------------------------
    // Footer: ICOD and status legend
    //--------------------------------------------------------------------------

    const footerY = plotHeight + bannerLevels * LAYOUT.bannerHeight + 17;
    // ICOD is provenance: always shown, and flagged when missing or demo. It
    // lives in the toolbar badge; the footer carries it only when the toolbar
    // is hidden (controls=0 or single-file mode), so it is never lost.
    updateIcodBadge(p);
    let icodWidth = 0;
    if (toolbar.property("hidden")) {
      const icodText = plot.append("text").attr("class", "sm-icod").attr("y", footerY)
        .classed("warn", !p.icod || p.icod_source === "demo")
        .text(icodLabel(p));
      icodText.append("title").text(ICOD_MEANING);
      icodWidth = icodText.node().getComputedTextLength();
    }

    const usedStatuses = Array.from(new Set(p.events.map((e) => e.status))).filter(Boolean);
    const legendItems = usedStatuses.map((s) => ({ label: s, color: p.status_colors[s] || FALLBACK_EVENT_COLOR }));
    if (afterIcod) legendItems.unshift({ label: "After ICOD", hatch: true });

    const legend = plot.append("g").attr("class", "sm-legend").attr("transform", `translate(${plotWidth},${footerY})`);
    let lx = 0;
    legendItems.slice().reverse().forEach((d) => {
      const item = legend.append("g");
      const text = item.append("text").attr("x", 14).text(d.label);
      const w = 14 + text.node().getComputedTextLength();
      lx -= w;
      item.attr("transform", `translate(${lx},0)`);
      const swatch = item.insert("rect", "text").attr("y", -9).attr("width", 10).attr("height", 10).attr("rx", 2);
      if (d.hatch) {
        swatch.attr("fill", "url(#sm-hatch)").attr("stroke", "var(--sm-icod)").attr("stroke-width", 1);
        item.append("title").text(ICOD_MEANING);
      } else {
        swatch.attr("stroke", d.color).attr("stroke-width", 2).attr("fill", d.color).attr("fill-opacity", 0.14);
      }
      lx -= 14;
    });

    // Narrow frames: drop the legend to its own line instead of overlapping the ICOD.
    if (icodWidth && plotWidth + lx < icodWidth + 16) {
      legend.attr("transform", `translate(${plotWidth},${footerY + 18})`);
      svg.attr("height", svgHeight + 18);
    }
  }

  //============================================================================
  // DAYLIGHT
  //============================================================================

  // Sun elevation (degrees) -> darkness 0..1. Each twilight stage steps darker:
  // civil (0 to -6), nautical (to -12), astronomical (to -18), then full night.
  const darkness = d3.scaleLinear().domain([-18, -12, -6, 0]).range([1, 0.8, 0.5, 0]).clamp(true);

  const daylightToggle = d3.select("#sm-daylight-toggle");

  function updateDaylightToggle(p) {
    // A payload without daylight data (config "Show Sunrise/Sunset?": false): grey the switch out.
    const available = Boolean(p.daylight);
    daylightToggle.property("checked", options.showDaylight).property("disabled", !available);
    d3.select(daylightToggle.node().parentNode)
      .classed("disabled", !available)
      .attr("title", available ? "Show or hide day/night shading for this locality"
                               : "This matrix has no day/night data");
  }

  daylightToggle.on("change", (ev) => {
    options.showDaylight = ev.target.checked;
    // Remember the choice in the URL alongside the selection.
    const url = new URL(window.location.href);
    if (options.showDaylight) url.searchParams.delete("daylight");
    else url.searchParams.set("daylight", "0");
    window.history.replaceState(null, "", url);
    render();
  });

  function drawDaylight(svg, plot, p, x, plotWidth, plotHeight) {
    const { elevations, step_minutes: step, sun } = p.daylight;
    const gradient = svg.append("defs").append("linearGradient")
      .attr("id", "sm-daylight").attr("gradientUnits", "userSpaceOnUse")
      .attr("x1", 0).attr("x2", plotWidth).attr("y1", 0).attr("y2", 0);

    gradient.selectAll("stop").data(elevations).join("stop")
      .attr("offset", (_, i) => x(d3.utcMinute.offset(p.window.start, i * step)) / plotWidth)
      .attr("stop-opacity", (e) => darkness(e))
      .style("stop-color", "var(--sm-night)");

    const times = ["dawn", "sunrise", "sunset", "dusk"]
      .filter((k) => sun[k]).map((k) => k[0].toUpperCase() + k.slice(1) + " " + formatTick(sun[k]));
    const loc = p.locality || {};
    const where = (loc.name ? " " + loc.name : "") +
      (loc.lat !== undefined ? ` (${loc.lat.toFixed(2)}, ${loc.lon.toFixed(2)})` : "");

    plot.append("rect").attr("class", "sm-daylight")
      .attr("width", plotWidth).attr("height", plotHeight)
      .attr("fill", "url(#sm-daylight)")
      .append("title")
      .text(`Daylight at${where}: ${times.join(" · ") || "no sunrise/sunset this day"}. ` +
        "Darker = sun further below the horizon (civil, nautical, astronomical twilight, night).");
  }

  //============================================================================
  // TOOLTIP
  //============================================================================

  function showTooltip(ev, e) {
    const parts = [
      `<strong>${escapeHtml(e.label || "Event")}</strong>`,
      `${escapeHtml(e.where || e.row)}${e.status ? " · " + escapeHtml(e.status) : ""}`,
      `<span class="muted">${formatFull(e.start)} – ${formatTick(e.end)}</span>`,
    ];
    if (e.notes) parts.push(`<span class="muted">${escapeHtml(e.notes)}</span>`);
    tooltip.html(parts.join("<br>")).attr("hidden", null);
    moveTooltip(ev);
  }

  function moveTooltip(ev) {
    const tip = tooltip.node();
    // Keyboard focus has no pointer position; anchor to the element instead.
    let cx = ev.clientX, cy = ev.clientY;
    if (cx === undefined || ev.type === "focus") {
      const box = ev.currentTarget.getBoundingClientRect();
      cx = box.right; cy = box.top;
    }
    const pad = 12;
    let tx = cx + pad, ty = cy + pad;
    // Keep the tooltip inside the iframe; flip to the other side when needed.
    if (tx + tip.offsetWidth > window.innerWidth - 4) tx = cx - tip.offsetWidth - pad;
    if (ty + tip.offsetHeight > window.innerHeight - 4) ty = cy - tip.offsetHeight - pad;
    tooltip.style("left", Math.max(4, tx) + "px").style("top", Math.max(4, ty) + "px");
  }

  function hideTooltip() {
    tooltip.attr("hidden", true);
  }

  //============================================================================
  // ICOD
  //============================================================================

  function formatAge(from) {
    const minutes = Math.round((Date.now() - from) / 60000);
    if (minutes < 0) return "in the future";
    if (minutes < 60) return minutes + "m ago";
    const hours = Math.floor(minutes / 60);
    if (hours < 48) return hours + "h " + (minutes % 60) + "m ago";
    return Math.floor(hours / 24) + "d " + (hours % 24) + "h ago";
  }

  function icodLabel(p) {
    if (!p.icod) return "ICOD: not provided — data currency unknown";
    return "ICOD: " + formatIcod(p.icod) + " (" + formatAge(p.icod) + ")" +
      (p.icod_source === "demo" ? " · DEMO DATA" : "");
  }

  function updateIcodBadge(p) {
    d3.select("#sm-icod-badge")
      .text(p.icod ? "ICOD " + formatIcodShort(p.icod) + " · " + formatAge(p.icod) +
                     (p.icod_source === "demo" ? " · DEMO DATA" : "")
                   : "ICOD not provided")
      .classed("warn", !p.icod || p.icod_source === "demo")
      .attr("title", ICOD_MEANING + (p.icod_source ? " Source: " + p.icod_source + "." : ""));
  }

  function readableInk(background) {
    // Dark text on light fills (e.g. yellow), white text on dark fills.
    return d3.lab(background).l > 65 ? "#252525" : "#ffffff";
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  //============================================================================
  // DASHBOARD MESSAGING
  //============================================================================

  function postToParent(message) {
    if (window.parent === window) return;
    window.parent.postMessage(message, options.trustedOrigin);
  }

  function notifyClick(e) {
    postToParent({
      type: "sync-matrix:event-click",
      event: { ...e, start: e.start.toISOString(), end: e.end.toISOString() },
      icod: current && current.icod ? current.icod.toISOString() : null,
      icod_source: current ? current.icod_source || null : null,
    });
  }

  window.addEventListener("message", (ev) => {
    if (ev.origin !== options.trustedOrigin) return;
    if (!ev.data) return;
    if (ev.data.type === "sync-matrix:data") setPayload(ev.data.payload);
    if (ev.data.type === "sync-matrix:select" && manifest) {
      const { matrix, locality, date } = ev.data;
      select({ matrix: matrix || selection.matrix, locality: locality || selection.locality,
               date: date || selection.date }, { notify: false });
    }
  });

  //============================================================================
  // STARTUP
  //============================================================================

  let pending = null;
  new ResizeObserver(() => {
    cancelAnimationFrame(pending);
    pending = requestAnimationFrame(render);
  }).observe(container.node());

  setInterval(render, 60 * 1000); // keep the NOW line moving between refreshes

  async function start() {
    setStatus("Loading…");
    if (options.dataUrl) {
      fetchPayload(); // single-file mode: no manifest, no dropdowns
    } else {
      try {
        await loadManifest();
        toolbar.attr("hidden", options.showControls ? null : true);
        select(selection, { notify: false });
      } catch (err) {
        showError("Could not load " + options.manifestUrl + " (" + err.message + ")");
      }
    }
    if (options.refreshSeconds) setInterval(refresh, options.refreshSeconds * 1000);
    postToParent({ type: "sync-matrix:ready" });
  }

  start();
})();
