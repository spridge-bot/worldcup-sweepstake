/* Land Monitor viewer: map + activity-coloured buildings + time-slider. */

const map = L.map("map", { zoomControl: true }).setView([51.849, -1.265], 14);

// --- base layers --------------------------------------------------------- //
const esriSat = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { maxZoom: 19, attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics" }
).addTo(map);

const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "&copy; OpenStreetMap contributors",
});

const osMap = L.tileLayer("/tiles/os/Outdoor/{z}/{x}/{y}.png", {
  maxZoom: 20, attribution: "Contains OS data &copy; Crown copyright",
  errorTileUrl: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
});

L.control.layers(
  { "Satellite (Esri)": esriSat, "OpenStreetMap": osm, "OS map (needs key)": osMap },
  {}, { collapsed: false }
).addTo(map);

// --- activity colour scale (idle -> busy) -------------------------------- //
const STOPS = [
  [0.0, [44, 123, 182]], [0.3, [90, 179, 106]], [0.6, [255, 210, 77]],
  [0.8, [240, 138, 60]], [1.0, [215, 25, 28]],
];
const lerp = (a, b, t) => Math.round(a + (b - a) * t);
function activityColor(v) {
  v = Math.max(0, Math.min(1, v || 0));
  for (let i = 1; i < STOPS.length; i++) {
    if (v <= STOPS[i][0]) {
      const [p0, c0] = STOPS[i - 1], [p1, c1] = STOPS[i];
      const t = (v - p0) / (p1 - p0 || 1);
      return `rgb(${lerp(c0[0], c1[0], t)},${lerp(c0[1], c1[1], t)},${lerp(c0[2], c1[2], t)})`;
    }
  }
  return "rgb(215,25,28)";
}

// --- state --------------------------------------------------------------- //
let geojson, allFeatures = [];
let dates = [], curDate = null;           // global time axis
const chipsById = {};                      // id -> [{date,url}]
const overlays = {};                       // id -> L.imageOverlay
const activeClasses = new Set(["farm_storage", "industrial_storage", "possible_storage"]);

// Data access: live server (fetch) OR a standalone static export (inlined globals).
function getJSON(path) {
  if (window.__STATIC__) {
    if (path === "/api/meta")
      return Promise.resolve({ os_tiles: false, data_source: "static export",
        count: (window.__BUILDINGS__.features || []).length });
    if (path === "/api/buildings") return Promise.resolve(window.__BUILDINGS__);
    const m = path.match(/^\/api\/chips\/(.+)$/);
    if (m) { const id = decodeURIComponent(m[1]);
      return Promise.resolve({ id, chips: window.__CHIPS__[id] || [] }); }
  }
  return fetch(path).then(r => r.json());
}

// timeline = [{d: "2024-01-15", a: 0.42}]; nearest point with d <= date.
function activityAt(props, date) {
  const tl = props.timeline;
  if (!tl || !tl.length || !date) return props.activity_index ?? 0;
  let val = tl[0].a;
  for (const p of tl) { if (p.d <= date) val = p.a; else break; }
  return val;
}
function chipAt(id, date) {
  const cs = chipsById[id];
  if (!cs || !cs.length) return null;
  let pick = cs[0];
  for (const c of cs) { if (c.date <= date) pick = c; else break; }
  return pick.url;
}
function paddedBounds(layer) {
  const c = layer.getBounds().getCenter();
  return [[c.lat - 0.0007, c.lng - 0.0011], [c.lat + 0.0007, c.lng + 0.0011]];
}

// --- popups & polygons --------------------------------------------------- //
function popupHtml(p) {
  const pct = Math.round((p.activity_index ?? 0) * 100);
  const rows = [
    ["Activity (avg)", `<b>${pct}%</b>`],
    ["Class", (p.storage_class || "").replace(/_/g, " ")],
    ["Storage score", p.storage_score?.toFixed?.(2) ?? "–"],
    ["Footprint", p.area_m2 ? `${Math.round(p.area_m2)} m²` : "–"],
    ["SAR mean (dB)", p.mean?.toFixed?.(1) ?? "–"],
    ["SAR range (dB)", p.range?.toFixed?.(1) ?? "–"],
  ].map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  return `<div class="popup"><h3>${p.name || p.id}</h3><table>${rows}</table>
    <div class="sparkwrap"><div class="sparklbl">Activity over time</div>
      <div class="spark" data-id="${p.id}"></div></div>
    <div class="filmstrip" data-id="${p.id}"></div></div>`;
}

// Inline SVG sparkline of the per-date activity timeline, with a dot on curDate.
function sparklineSvg(timeline, date) {
  if (!timeline || timeline.length < 2) return "";
  const W = 208, H = 44, pad = 4, n = timeline.length;
  const x = i => pad + (i * (W - 2 * pad)) / (n - 1);
  const y = a => H - pad - a * (H - 2 * pad);
  const pts = timeline.map((p, i) => `${x(i).toFixed(1)},${y(p.a).toFixed(1)}`).join(" ");
  const area = `${pad},${H - pad} ${pts} ${W - pad},${H - pad}`;
  let ci = 0;
  timeline.forEach((p, i) => { if (!date || p.d <= date) ci = i; });
  const cp = timeline[ci];
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
    <polygon points="${area}" fill="rgba(74,144,217,0.15)"/>
    <polyline points="${pts}" fill="none" stroke="#4a90d9" stroke-width="1.5"/>
    <line x1="${x(ci)}" y1="${pad}" x2="${x(ci)}" y2="${H - pad}" stroke="#888" stroke-dasharray="2 2"/>
    <circle cx="${x(ci)}" cy="${y(cp.a)}" r="3.5" fill="${activityColor(cp.a)}" stroke="#fff"/>
    <text x="${W - pad}" y="11" text-anchor="end" font-size="9" fill="#555">${cp.d}: ${Math.round(cp.a * 100)}%</text>
  </svg>`;
}
function renderSpark(id, root) {
  const el = root?.querySelector(`.spark[data-id="${id}"]`);
  const f = allFeatures.find(x => String(x.properties.id) === String(id));
  if (el && f) el.innerHTML = sparklineSvg(f.properties.timeline, curDate);
}
function updateOpenSpark() {
  document.querySelectorAll(".leaflet-popup .spark").forEach(el =>
    renderSpark(el.dataset.id, el.parentElement));
}

function onEach(feature, layer) {
  layer.bindPopup(popupHtml(feature.properties));
  layer.on("popupopen", e => {
    fillFilmstrip(feature.properties.id, layer);
    renderSpark(feature.properties.id, e.popup.getElement());
  });
  feature.__layer = layer;
}
function fillFilmstrip(id, layer) {
  const el = layer.getPopup().getElement()?.querySelector(`.filmstrip[data-id="${id}"]`);
  if (!el) return;
  const cs = chipsById[id];
  if (!cs || !cs.length) {
    el.outerHTML = `<p class="nochips">No image chips yet — run <code>landmon chips</code>
      to view dated imagery here.</p>`;
    return;
  }
  el.innerHTML = cs.map(c =>
    `<figure><img src="${c.url}" loading="lazy"><figcaption>${c.date}</figcaption></figure>`
  ).join("");
}
function styleFor(props, date) {
  return { color: "#10141a", weight: 1.2,
           fillColor: activityColor(activityAt(props, date)), fillOpacity: 0.85 };
}

function render() {
  if (geojson) map.removeLayer(geojson);
  const feats = allFeatures.filter(f => activeClasses.has(f.properties.storage_class));
  geojson = L.geoJSON({ type: "FeatureCollection", features: feats }, {
    style: f => styleFor(f.properties, curDate), onEachFeature: onEach,
  }).addTo(map);
  applyDate(curDate);     // colour + overlays for current date
  buildList(feats, curDate);
}

function buildList(feats, date) {
  const list = document.getElementById("list");
  const sorted = [...feats].sort((a, b) =>
    activityAt(b.properties, date) - activityAt(a.properties, date));
  list.innerHTML = sorted.map(f => {
    const p = f.properties, a = activityAt(p, date), pct = Math.round(a * 100);
    return `<div class="card" data-id="${p.id}">
      <div class="row1">
        <span class="name"><span class="dot" style="background:${activityColor(a)}"></span>${p.name || p.id}</span>
        <span class="pct" style="color:${activityColor(a)}">${pct}%</span>
      </div>
      <div class="meta">${(p.storage_class || "").replace(/_/g, " ")} · ${p.area_m2 ? Math.round(p.area_m2) + " m²" : ""}</div>
    </div>`;
  }).join("");
  list.querySelectorAll(".card").forEach(card => {
    card.onclick = () => {
      const f = allFeatures.find(x => String(x.properties.id) === card.dataset.id);
      if (f && f.__layer) { map.fitBounds(f.__layer.getBounds(), { maxZoom: 18 }); f.__layer.openPopup(); }
    };
  });
}

// --- time animation ------------------------------------------------------ //
function applyDate(date) {
  const showChips = document.getElementById("showchips")?.checked;
  const visibleIds = new Set();
  if (geojson) geojson.eachLayer(layer => {
    const p = layer.feature.properties;
    visibleIds.add(p.id);
    layer.setStyle({ fillColor: activityColor(activityAt(p, date)) });
    const url = date ? chipAt(p.id, date) : null;
    if (showChips && url) {
      if (!overlays[p.id]) {
        overlays[p.id] = L.imageOverlay(url, paddedBounds(layer),
          { className: "chip-overlay", interactive: false, zIndex: 450 }).addTo(map);
      } else { overlays[p.id].setUrl(url); map.addLayer(overlays[p.id]); }
    } else if (overlays[p.id]) { map.removeLayer(overlays[p.id]); }
  });
  // Drop overlays for now-hidden buildings.
  Object.keys(overlays).forEach(id => {
    if (!visibleIds.has(id) && map.hasLayer(overlays[id])) map.removeLayer(overlays[id]);
  });
  const lbl = document.getElementById("datelabel");
  if (lbl && date) lbl.textContent = date;
  updateOpenSpark();      // move the sparkline marker if a popup is open
}

let timer = null;
function setDateIndex(i) {
  curDate = dates[i];
  document.getElementById("slider").value = i;
  applyDate(curDate);
  buildList(allFeatures.filter(f => activeClasses.has(f.properties.storage_class)), curDate);
}
function togglePlay() {
  const btn = document.getElementById("play");
  if (timer) { clearInterval(timer); timer = null; btn.textContent = "▶"; return; }
  btn.textContent = "⏸";
  timer = setInterval(() => {
    let i = (+document.getElementById("slider").value + 1);
    if (i >= dates.length) i = 0;
    setDateIndex(i);
  }, 750);
}

function setupTimebar() {
  if (dates.length < 2) return;
  const bar = document.getElementById("timebar");
  const slider = document.getElementById("slider");
  bar.classList.remove("hidden");
  slider.max = dates.length - 1;
  slider.value = dates.length - 1;       // start at most recent
  curDate = dates[dates.length - 1];
  slider.oninput = () => { if (timer) togglePlay(); setDateIndex(+slider.value); };
  document.getElementById("play").onclick = togglePlay;
  document.getElementById("showchips").onchange = () => applyDate(curDate);
  document.getElementById("datelabel").textContent = curDate;
}

// --- filters ------------------------------------------------------------- //
document.querySelectorAll(".cls").forEach(cb => cb.onchange = () => {
  cb.checked ? activeClasses.add(cb.value) : activeClasses.delete(cb.value);
  render();
});

// --- boot ---------------------------------------------------------------- //
getJSON("/api/meta").then(m => {
  document.getElementById("src").textContent = "source: " + m.data_source;
  document.getElementById("activity-note").textContent = m.os_tiles
    ? "OS basemap available in the layer switcher."
    : "Set OS_API_KEY for the OS basemap layer; satellite imagery shown by default.";
});

getJSON("/api/buildings").then(async fc => {
  allFeatures = fc.features || [];
  // Pull chip lists for every building, then build the global date axis.
  await Promise.all(allFeatures.map(f =>
    getJSON(`/api/chips/${encodeURIComponent(f.properties.id)}`)
      .then(d => { chipsById[f.properties.id] = d.chips || []; }).catch(() => {})
  ));
  const dateSet = new Set();
  allFeatures.forEach(f => {
    (f.properties.timeline || []).forEach(p => dateSet.add(p.d));
    (chipsById[f.properties.id] || []).forEach(c => dateSet.add(c.date));
  });
  dates = [...dateSet].sort();
  if (dates.length) curDate = dates[dates.length - 1];

  render();
  setupTimebar();
  if (allFeatures.length) map.fitBounds(L.geoJSON(fc).getBounds().pad(0.3));
  setTimeout(() => map.invalidateSize(), 300);   // ensure correct map size on load
});

// --- show/hide sidebar; keep the map sized correctly --------------------- //
const sidebarToggle = document.getElementById("sidebar-toggle");
function setCollapsed(collapsed) {
  document.body.classList.toggle("collapsed", collapsed);
  sidebarToggle.textContent = collapsed ? "☰" : "✕";
  setTimeout(() => map.invalidateSize(), 210);   // Leaflet must re-measure
}
sidebarToggle.onclick = () =>
  setCollapsed(!document.body.classList.contains("collapsed"));
setCollapsed(window.innerWidth < 760);           // start hidden on small screens
window.addEventListener("resize", () => map.invalidateSize());
