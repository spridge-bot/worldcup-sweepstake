/* Land Monitor viewer: map + activity-coloured tagged buildings. */

const map = L.map("map", { zoomControl: true }).setView([51.849, -1.265], 14);

// --- base layers --------------------------------------------------------- //
const esriSat = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { maxZoom: 19, attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics" }
).addTo(map);

const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "&copy; OpenStreetMap contributors",
});

// OS Maps via the server proxy (only renders if OS_API_KEY is set; blank otherwise).
const osMap = L.tileLayer("/tiles/os/Outdoor/{z}/{x}/{y}.png", {
  maxZoom: 20, attribution: "Contains OS data &copy; Crown copyright",
  errorTileUrl: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
});

const baseLayers = { "Satellite (Esri)": esriSat, "OpenStreetMap": osm, "OS map (needs key)": osMap };
L.control.layers(baseLayers, {}, { collapsed: false }).addTo(map);

// --- activity colour scale (idle -> busy) -------------------------------- //
// Blue -> green -> yellow -> orange -> red. Matches the CSS legend gradient.
const STOPS = [
  [0.0, [44, 123, 182]],
  [0.3, [90, 179, 106]],
  [0.6, [255, 210, 77]],
  [0.8, [240, 138, 60]],
  [1.0, [215, 25, 28]],
];
function lerp(a, b, t) { return Math.round(a + (b - a) * t); }
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

function style(feature) {
  const a = feature.properties.activity_index ?? 0;
  return { color: "#10141a", weight: 1.2, fillColor: activityColor(a), fillOpacity: 0.85 };
}

// --- data ---------------------------------------------------------------- //
let geojson, allFeatures = [];
const activeClasses = new Set(["farm_storage", "industrial_storage", "possible_storage"]);

function popupHtml(p) {
  const pct = Math.round((p.activity_index ?? 0) * 100);
  const rows = [
    ["Activity", `<b>${pct}%</b>`],
    ["Class", (p.storage_class || "").replace(/_/g, " ")],
    ["Storage score", p.storage_score?.toFixed?.(2) ?? "–"],
    ["Footprint", p.area_m2 ? `${Math.round(p.area_m2)} m²` : "–"],
    ["SAR mean (dB)", p.mean?.toFixed?.(1) ?? "–"],
    ["SAR range (dB)", p.range?.toFixed?.(1) ?? "–"],
    ["Trend / day", p.trend_per_day != null ? p.trend_per_day.toFixed(4) : "–"],
  ].map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  return `<div class="popup"><h3>${p.name || p.id}</h3>
    <table>${rows}</table>
    <div class="filmstrip" data-id="${p.id}"></div></div>`;
}

function onEach(feature, layer) {
  layer.bindPopup(popupHtml(feature.properties));
  layer.on("popupopen", () => loadChips(feature.properties.id, layer));
  feature.__layer = layer;
}

function loadChips(id, layer) {
  fetch(`/api/chips/${encodeURIComponent(id)}`).then(r => r.json()).then(d => {
    const el = layer.getPopup().getElement()?.querySelector(`.filmstrip[data-id="${id}"]`);
    if (!el) return;
    if (!d.chips?.length) {
      el.outerHTML = `<p class="nochips">No image chips yet. Generate a time series of
        chips with the pipeline (see README) to view dated imagery here.</p>`;
      return;
    }
    el.innerHTML = d.chips.map(c =>
      `<figure><img src="${c.url}" loading="lazy"><figcaption>${c.date}</figcaption></figure>`
    ).join("");
  }).catch(() => {});
}

function render() {
  if (geojson) map.removeLayer(geojson);
  const feats = allFeatures.filter(f => activeClasses.has(f.properties.storage_class));
  geojson = L.geoJSON({ type: "FeatureCollection", features: feats },
    { style, onEachFeature: onEach }).addTo(map);
  buildList(feats);
}

function buildList(feats) {
  const list = document.getElementById("list");
  const sorted = [...feats].sort((a, b) =>
    (b.properties.activity_index ?? 0) - (a.properties.activity_index ?? 0));
  list.innerHTML = sorted.map(f => {
    const p = f.properties, pct = Math.round((p.activity_index ?? 0) * 100);
    return `<div class="card" data-id="${p.id}">
      <div class="row1">
        <span class="name"><span class="dot" style="background:${activityColor(p.activity_index)}"></span>${p.name || p.id}</span>
        <span class="pct" style="color:${activityColor(p.activity_index)}">${pct}%</span>
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

document.querySelectorAll(".cls").forEach(cb => cb.onchange = () => {
  cb.checked ? activeClasses.add(cb.value) : activeClasses.delete(cb.value);
  render();
});

fetch("/api/meta").then(r => r.json()).then(m => {
  document.getElementById("src").textContent = "source: " + m.data_source;
  document.getElementById("activity-note").textContent = m.os_tiles
    ? "OS basemap available in the layer switcher."
    : "Set OS_API_KEY for the OS basemap layer; satellite imagery shown by default.";
});

fetch("/api/buildings").then(r => r.json()).then(fc => {
  allFeatures = fc.features || [];
  render();
  if (allFeatures.length) {
    const tmp = L.geoJSON(fc);
    map.fitBounds(tmp.getBounds().pad(0.3));
  }
});
