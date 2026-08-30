(function () {
  "use strict";

  const root = document.getElementById("district-map-editor");
  if (!root) return;

  const select = document.getElementById("district-map-select");
  const colorsBlock = document.getElementById("district-map-colors-block");
  const colorsTitle = document.getElementById("district-map-colors-title");
  const colorsHint = document.getElementById("district-map-colors-hint");
  const strokeColorInput = document.getElementById("district-map-stroke-color");
  const strokeHexInput = document.getElementById("district-map-stroke-hex");
  const fillColorInput = document.getElementById("district-map-fill-color");
  const fillHexInput = document.getElementById("district-map-fill-hex");
  const drawButton = document.getElementById("district-map-draw");
  const editButton = document.getElementById("district-map-edit");
  const deleteButton = document.getElementById("district-map-delete");
  const saveButton = document.getElementById("district-map-save");
  const status = document.getElementById("district-map-status");
  const dirtyLabel = document.getElementById("district-map-dirty");
  const versionLabel = document.getElementById("district-map-version");
  const initial = readJson("district-map-initial-geojson", { type: "FeatureCollection", features: [] });
  const districts = readJson("district-map-catalog", []);
  const districtById = new Map(districts.map((item) => [String(item.id), item]));
  const districtColors = new Map();
  const polygons = new Map();
  const featureIds = new Map();
  let map = null;
  let selectedId = "";
  let dirty = false;
  let drawingId = "";

  function readJson(id, fallback) {
    const node = document.getElementById(id);
    if (!node) return fallback;
    try { return JSON.parse(node.textContent); } catch (_) { return fallback; }
  }

  function setStatus(message, kind) {
    if (!status) return;
    status.textContent = message;
    status.classList.toggle("is-error", kind === "error");
    status.classList.toggle("is-success", kind === "success");
  }

  function markDirty() {
    dirty = true;
    if (dirtyLabel) dirtyLabel.hidden = false;
  }

  function markClean() {
    dirty = false;
    if (dirtyLabel) dirtyLabel.hidden = true;
  }

  function defaultColors(district) {
    const isActive = Boolean(district && district.is_active);
    return {
      stroke: isActive ? "#2563eb" : "#64748b",
      fill: isActive ? "#60a5fa" : "#94a3b8",
    };
  }

  function getColors(districtId) {
    const custom = districtColors.get(String(districtId));
    if (custom && custom.stroke && custom.fill) return custom;
    const fallback = defaultColors(districtById.get(String(districtId)));
    return {
      stroke: (custom && custom.stroke) || fallback.stroke,
      fill: (custom && custom.fill) || fallback.fill,
    };
  }

  function selectedPolygon() { return selectedId ? polygons.get(selectedId) : null; }

  function updateButtons() {
    const hasSelection = Boolean(selectedId && districtById.has(selectedId));
    const hasPolygon = Boolean(selectedPolygon());
    if (drawButton) {
      drawButton.disabled = !hasSelection;
      drawButton.textContent = hasPolygon ? "Перерисовать границы" : "Нарисовать границы";
    }
    if (editButton) editButton.disabled = !hasPolygon;
    if (deleteButton) deleteButton.disabled = !hasPolygon;
  }

  function stopEditors(exceptId) {
    polygons.forEach((polygon, districtId) => {
      if (districtId !== exceptId && polygon.editor) polygon.editor.stopEditing();
      const colors = getColors(districtId);
      polygon.options.set({
        strokeColor: colors.stroke,
        fillColor: colors.fill,
        strokeWidth: districtId === exceptId ? 4 : 2,
        fillOpacity: districtId === exceptId ? 0.28 : 0.16,
      });
    });
  }

  function syncColorInputs(colors, enabled) {
    const isEnabled = Boolean(enabled);
    if (strokeColorInput) {
      strokeColorInput.value = colors.stroke;
      strokeColorInput.disabled = !isEnabled;
    }
    if (strokeHexInput) {
      strokeHexInput.value = colors.stroke.toUpperCase();
      strokeHexInput.disabled = !isEnabled;
    }
    if (fillColorInput) {
      fillColorInput.value = colors.fill;
      fillColorInput.disabled = !isEnabled;
    }
    if (fillHexInput) {
      fillHexInput.value = colors.fill.toUpperCase();
      fillHexInput.disabled = !isEnabled;
    }
    if (colorsBlock) colorsBlock.classList.toggle("is-disabled", !isEnabled);
  }

  function selectDistrict(id, startEditing) {
    selectedId = String(id || "");
    if (select) select.value = selectedId;
    stopEditors(selectedId);
    const polygon = selectedPolygon();
    if (polygon && startEditing) polygon.editor.startEditing();
    const district = districtById.get(selectedId);
    if (!district) {
      setStatus("Выберите район в списке.");
      if (colorsTitle) colorsTitle.textContent = "Цвета района";
      if (colorsHint) colorsHint.textContent = "Выберите район в списке выше";
      syncColorInputs({ stroke: "#2563eb", fill: "#60a5fa" }, false);
    } else {
      if (colorsTitle) colorsTitle.textContent = `Цвета: ${district.name}`;
      if (colorsHint) colorsHint.textContent = "Измените цвет краев или заливки";
      syncColorInputs(getColors(selectedId), true);
      if (polygon) setStatus(`Район «${district.name}»: границы можно редактировать, перетаскивая точки.`);
      else setStatus(`Район «${district.name}» пока не нарисован.`);
    }
    updateButtons();
  }

  function updateSelectedColors(stroke, fill) {
    if (!selectedId) return;
    const current = getColors(selectedId);
    const newStroke = stroke !== undefined ? stroke : current.stroke;
    const newFill = fill !== undefined ? fill : current.fill;
    districtColors.set(selectedId, { stroke: newStroke, fill: newFill });
    syncColorInputs({ stroke: newStroke, fill: newFill });
    const polygon = selectedPolygon();
    if (polygon) {
      polygon.options.set({
        strokeColor: newStroke,
        fillColor: newFill,
      });
    }
    markDirty();
  }

  function yandexCoordinates(geometry) {
    if (!geometry || geometry.type !== "Polygon" || !Array.isArray(geometry.coordinates)) return [];
    return geometry.coordinates.map((ring) => ring.map((point) => [Number(point[1]), Number(point[0])]));
  }

  function geoJsonCoordinates(polygon) {
    const coordinates = polygon.geometry.getCoordinates() || [];
    return coordinates.map((ring) => {
      const converted = ring.map((point) => [Number(point[1]), Number(point[0])]);
      if (converted.length && !samePoint(converted[0], converted[converted.length - 1])) converted.push(converted[0].slice());
      return converted;
    });
  }

  function samePoint(a, b) { return a && b && Math.abs(a[0] - b[0]) < 1e-12 && Math.abs(a[1] - b[1]) < 1e-12; }

  function createPolygon(districtId, coordinates, featureId, strokeColor, fillColor) {
    const district = districtById.get(String(districtId));
    if (!district) return null;
    const defaults = defaultColors(district);
    const stroke = strokeColor || (districtColors.get(String(districtId)) || {}).stroke || defaults.stroke;
    const fill = fillColor || (districtColors.get(String(districtId)) || {}).fill || defaults.fill;
    districtColors.set(String(districtId), { stroke, fill });
    const polygon = new ymaps.Polygon(
      coordinates,
      { hintContent: district.name, balloonContent: district.name },
      {
        fillColor: fill,
        fillOpacity: 0.16,
        strokeColor: stroke,
        strokeWidth: 2,
        editorDrawingCursor: "crosshair",
        editorMaxPoints: 2500,
      }
    );
    polygon.events.add("click", function () { selectDistrict(String(districtId), true); });
    polygon.geometry.events.add("change", function () {
      markDirty();
      validateAndReport(false);
    });
    map.geoObjects.add(polygon);
    polygons.set(String(districtId), polygon);
    featureIds.set(String(districtId), featureId || `district-${districtId}`);
    return polygon;
  }

  function loadPolygons() {
    (initial.features || []).forEach((feature) => {
      const properties = feature.properties || {};
      let districtId = properties.district_tariff_id;
      if (districtId == null) {
        const found = districts.find((item) => String(item.name).trim().toLowerCase() === String(properties.name || "").trim().toLowerCase());
        districtId = found && found.id;
      }
      if (districtId == null || feature.geometry?.type !== "Polygon") return;
      createPolygon(
        String(districtId),
        yandexCoordinates(feature.geometry),
        feature.id,
        properties.stroke_color,
        properties.fill_color
      );
    });
  }

  function allBounds() {
    let bounds = null;
    polygons.forEach((polygon) => {
      const current = polygon.geometry.getBounds();
      if (!current) return;
      if (!bounds) bounds = [current[0].slice(), current[1].slice()];
      else {
        bounds[0][0] = Math.min(bounds[0][0], current[0][0]);
        bounds[0][1] = Math.min(bounds[0][1], current[0][1]);
        bounds[1][0] = Math.max(bounds[1][0], current[1][0]);
        bounds[1][1] = Math.max(bounds[1][1], current[1][1]);
      }
    });
    return bounds;
  }

  function startDrawing() {
    if (!selectedId) return;
    const existing = selectedPolygon();
    if (existing) {
      existing.editor.stopEditing();
      map.geoObjects.remove(existing);
      polygons.delete(selectedId);
    }
    stopEditors(selectedId);
    const colors = getColors(selectedId);
    const polygon = createPolygon(selectedId, [], featureIds.get(selectedId), colors.stroke, colors.fill);
    drawingId = selectedId;
    polygon.editor.startDrawing();
    markDirty();
    setStatus("Ставьте точки по границе района. Завершите рисунок двойным кликом.");
    updateButtons();
  }

  function deleteSelected() {
    const polygon = selectedPolygon();
    if (!polygon) return;
    polygon.editor.stopEditing();
    map.geoObjects.remove(polygon);
    polygons.delete(selectedId);
    featureIds.delete(selectedId);
    markDirty();
    updateButtons();
    setStatus("Границы удалены. Нажмите «Сохранить», чтобы применить изменение.");
  }

  function outerRing(districtId) {
    const polygon = polygons.get(districtId);
    const rings = polygon ? polygon.geometry.getCoordinates() : [];
    return Array.isArray(rings) && Array.isArray(rings[0]) ? rings[0] : [];
  }

  function orientation(a, b, c) {
    const value = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1]);
    if (Math.abs(value) < 1e-12) return 0;
    return value > 0 ? 1 : 2;
  }

  function onSegment(a, b, c) {
    return b[0] <= Math.max(a[0], c[0]) + 1e-12 && b[0] >= Math.min(a[0], c[0]) - 1e-12 && b[1] <= Math.max(a[1], c[1]) + 1e-12 && b[1] >= Math.min(a[1], c[1]) - 1e-12;
  }

  function segmentsIntersect(a, b, c, d) {
    const o1 = orientation(a, b, c), o2 = orientation(a, b, d), o3 = orientation(c, d, a), o4 = orientation(c, d, b);
    if (o1 !== o2 && o3 !== o4) return true;
    return (o1 === 0 && onSegment(a, c, b)) || (o2 === 0 && onSegment(a, d, b)) || (o3 === 0 && onSegment(c, a, d)) || (o4 === 0 && onSegment(c, b, d));
  }

  function closedRing(ring) {
    if (!ring.length) return [];
    const copy = ring.map((point) => [Number(point[0]), Number(point[1])]);
    if (!samePoint(copy[0], copy[copy.length - 1])) copy.push(copy[0].slice());
    return copy;
  }

  function pointInRing(point, ring) {
    let inside = false;
    const closed = closedRing(ring);
    for (let index = 0; index < closed.length - 1; index += 1) {
      const a = closed[index], b = closed[index + 1];
      if (orientation(a, point, b) === 0 && onSegment(a, point, b)) return true;
      const crosses = (a[1] > point[1]) !== (b[1] > point[1]) && point[0] < ((b[0] - a[0]) * (point[1] - a[1])) / ((b[1] - a[1]) || 1e-30) + a[0];
      if (crosses) inside = !inside;
    }
    return inside;
  }

  function ringsIntersect(first, second) {
    const a = closedRing(first), b = closedRing(second);
    for (let i = 0; i < a.length - 1; i += 1) for (let j = 0; j < b.length - 1; j += 1) if (segmentsIntersect(a[i], a[i + 1], b[j], b[j + 1])) return true;
    return (a[0] && pointInRing(a[0], b)) || (b[0] && pointInRing(b[0], a));
  }

  function validationError() {
    const ids = Array.from(polygons.keys());
    for (const id of ids) {
      if (outerRing(id).length < 3) return `Завершите рисование района «${districtById.get(id)?.name || id}».`;
    }
    for (let i = 0; i < ids.length; i += 1) {
      for (let j = i + 1; j < ids.length; j += 1) {
        if (ringsIntersect(outerRing(ids[i]), outerRing(ids[j]))) return `Районы «${districtById.get(ids[i]).name}» и «${districtById.get(ids[j]).name}» пересекаются.`;
      }
    }
    return "";
  }

  function validateAndReport(showSuccess) {
    const error = validationError();
    if (error) { setStatus(error, "error"); return false; }
    if (showSuccess) setStatus("Границы проверены. Пересечений нет.", "success");
    return true;
  }

  function collection() {
    const features = [];
    polygons.forEach((polygon, districtId) => {
      const district = districtById.get(districtId);
      const colors = getColors(districtId);
      features.push({
        type: "Feature",
        id: featureIds.get(districtId) || `district-${districtId}`,
        properties: {
          kind: "district", name: district.name, district_tariff_id: Number(districtId),
          min_zoom: 10, stroke_width: 3, stroke_color: colors.stroke,
          fill_color: colors.fill, fill_opacity: 0.16,
        },
        geometry: { type: "Polygon", coordinates: geoJsonCoordinates(polygon) },
      });
    });
    return { type: "FeatureCollection", features };
  }

  function csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  async function save() {
    polygons.forEach((polygon) => polygon.editor.stopEditing());
    drawingId = "";
    if (!validateAndReport(false)) return;
    if (!polygons.size) { setStatus("Нарисуйте границы хотя бы одного района.", "error"); return; }
    saveButton.disabled = true;
    setStatus("Сохраняем и публикуем районы…");
    try {
      const response = await fetch(root.dataset.publishUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken(), "Accept": "application/json" },
        body: JSON.stringify({ geojson: collection(), base_geojson: null }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error((payload.errors || ["Не удалось сохранить карту."]).join(" "));
      markClean();
      if (versionLabel) versionLabel.textContent = `Опубликовано · версия ${payload.version}`;
      setStatus("Районы сохранены и уже доступны в приложении.", "success");
    } catch (error) {
      setStatus(error.message || "Не удалось сохранить карту.", "error");
    } finally {
      saveButton.disabled = false;
    }
  }

  function init() {
    map = new ymaps.Map("district-map-canvas", { center: [42.8746, 74.5698], zoom: 11, controls: ["zoomControl", "searchControl", "geolocationControl", "fullscreenControl"] }, { searchControlProvider: "yandex#search" });
    loadPolygons();
    const bounds = allBounds();
    if (bounds) map.setBounds(bounds, { checkZoomRange: true, zoomMargin: 48 });
    if (select) select.addEventListener("change", () => selectDistrict(select.value, false));
    if (strokeColorInput) {
      strokeColorInput.addEventListener("input", (e) => updateSelectedColors(e.target.value, undefined));
    }
    if (strokeHexInput) {
      strokeHexInput.addEventListener("input", (e) => {
        let hex = e.target.value.trim();
        if (!hex.startsWith("#")) hex = "#" + hex;
        if (/^#[0-9a-fA-F]{6}$/.test(hex)) updateSelectedColors(hex, undefined);
      });
      strokeHexInput.addEventListener("blur", (e) => {
        let hex = e.target.value.trim();
        if (!hex.startsWith("#")) hex = "#" + hex;
        if (/^#[0-9a-fA-F]{6}$/.test(hex)) updateSelectedColors(hex, undefined);
        else e.target.value = getColors(selectedId).stroke.toUpperCase();
      });
    }
    if (fillColorInput) {
      fillColorInput.addEventListener("input", (e) => updateSelectedColors(undefined, e.target.value));
    }
    if (fillHexInput) {
      fillHexInput.addEventListener("input", (e) => {
        let hex = e.target.value.trim();
        if (!hex.startsWith("#")) hex = "#" + hex;
        if (/^#[0-9a-fA-F]{6}$/.test(hex)) updateSelectedColors(undefined, hex);
      });
      fillHexInput.addEventListener("blur", (e) => {
        let hex = e.target.value.trim();
        if (!hex.startsWith("#")) hex = "#" + hex;
        if (/^#[0-9a-fA-F]{6}$/.test(hex)) updateSelectedColors(undefined, hex);
        else e.target.value = getColors(selectedId).fill.toUpperCase();
      });
    }
    if (drawButton) drawButton.addEventListener("click", startDrawing);
    if (editButton) editButton.addEventListener("click", () => { const polygon = selectedPolygon(); if (polygon) { stopEditors(selectedId); polygon.editor.startEditing(); setStatus("Перетаскивайте вершины района, затем нажмите «Сохранить»."); } });
    if (deleteButton) deleteButton.addEventListener("click", deleteSelected);
    if (saveButton) saveButton.addEventListener("click", save);
    window.addEventListener("beforeunload", (event) => { if (!dirty) return; event.preventDefault(); event.returnValue = ""; });
    setStatus(polygons.size ? "Выберите район, чтобы изменить его границы." : "Выберите район и нажмите «Нарисовать границы»." );
    updateButtons();
    syncColorInputs(selectedId ? getColors(selectedId) : { stroke: "#2563eb", fill: "#60a5fa" }, Boolean(selectedId));
  }

  let attempts = 0;
  (function waitForYandex() {
    if (window.ymaps && typeof window.ymaps.ready === "function") { window.ymaps.ready(init); return; }
    attempts += 1;
    if (attempts > 100) { setStatus("Yandex Maps не загрузились. Проверьте API-ключ и доступ к интернету.", "error"); return; }
    window.setTimeout(waitForYandex, 100);
  })();
})();
