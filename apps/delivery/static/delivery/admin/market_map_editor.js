(() => {
  'use strict';

  const state = {
    map: null,
    tool: 'select',
    items: new Map(),
    selectedId: null,
    drawing: [],
    preview: null,
    counter: 0,
  };

  const byId = (id) => document.getElementById(id);
  const root = () => byId('market-map-editor');

  function readJsonScript(id, fallback) {
    const node = byId(id);
    if (!node) return fallback;
    try {
      return JSON.parse(node.textContent || '');
    } catch (_) {
      return fallback;
    }
  }

  function setStatus(message, type = '') {
    const node = byId('market-map-status');
    if (!node) return;
    node.textContent = message;
    node.className = type;
  }

  function csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function featureKindLabel(kind) {
    return {
      bazar: 'Граница базара',
      district: 'Район',
      sector: 'Сектор',
      row: 'Ряд',
      passage: 'Проход',
      container: 'Контейнер',
    }[kind] || kind;
  }

  function geometryFamily(type) {
    if (type === 'Point') return 'point';
    if (type === 'LineString') return 'line';
    if (type === 'Polygon' || type === 'MultiPolygon') return 'polygon';
    return 'unknown';
  }

  function expectedFamily(kind) {
    if (kind === 'container') return 'point';
    if (kind === 'row' || kind === 'passage') return 'line-or-polygon';
    return 'polygon';
  }

  function defaultProperties(kind) {
    const bazarName = root()?.dataset.bazarName || 'Базар';
    const defaults = {
      bazar: { name: bazarName, min_zoom: 10, stroke_width: 3 },
      district: { name: 'Новый район', min_zoom: 13, stroke_width: 2 },
      sector: { name: 'Новый сектор', min_zoom: 14, stroke_width: 2 },
      row: { name: 'Новый ряд', min_zoom: 16, stroke_width: 3 },
      passage: { name: 'Новый проход', min_zoom: 16, stroke_width: 3 },
      container: { name: 'Новый контейнер', min_zoom: 17, stroke_width: 2 },
    }[kind];
    return {
      kind,
      ...defaults,
      bazar_id: Number(root()?.dataset.bazarId || 0),
      stroke_color: '#e47f26',
      fill_color: '#ff8656',
      fill_opacity: kind === 'container' ? 1 : 0.2,
      is_active: true,
    };
  }

  function makeId(kind) {
    state.counter += 1;
    return `${kind}-${Date.now()}-${state.counter}`;
  }

  function normalizeFeature(raw) {
    const feature = JSON.parse(JSON.stringify(raw));
    feature.type = 'Feature';
    feature.id = String(feature.id || makeId(feature.properties?.kind || 'feature'));
    feature.properties = feature.properties || {};
    feature.properties.kind = String(feature.properties.kind || '').toLowerCase();
    feature.properties.name = String(feature.properties.name || feature.properties.number || feature.id);
    feature.geometry = feature.geometry || { type: 'Point', coordinates: [74.6122, 42.8746] };
    return feature;
  }

  function pathToCoordinates(path) {
    const result = [];
    for (let index = 0; index < path.getLength(); index += 1) {
      const point = path.getAt(index);
      result.push([point.lng(), point.lat()]);
    }
    return result;
  }

  function pathsToCoordinates(paths) {
    const result = [];
    for (let index = 0; index < paths.getLength(); index += 1) {
      const ring = pathToCoordinates(paths.getAt(index));
      if (ring.length && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])) {
        ring.push([...ring[0]]);
      }
      result.push(ring);
    }
    return result;
  }

  function overlayStyle(properties, selected) {
    return {
      strokeColor: properties.stroke_color || '#e47f26',
      strokeOpacity: 1,
      strokeWeight: Number(properties.stroke_width || 2) + (selected ? 1 : 0),
      fillColor: properties.fill_color || '#ff8656',
      fillOpacity: selected ? Math.max(Number(properties.fill_opacity ?? 0.2), 0.28) : Number(properties.fill_opacity ?? 0.2),
      clickable: true,
      editable: selected,
      draggable: selected,
      zIndex: selected ? 1000 : Number(properties.z_index || 1),
    };
  }

  function createMarker(feature) {
    const coordinates = feature.geometry.coordinates;
    const marker = new google.maps.Marker({
      map: state.map,
      position: { lat: Number(coordinates[1]), lng: Number(coordinates[0]) },
      title: feature.properties.name,
      draggable: false,
      clickable: true,
    });
    marker.addListener('click', () => selectFeature(feature.id));
    marker.addListener('dragend', () => refreshList());
    return marker;
  }

  function createPolyline(feature) {
    const line = new google.maps.Polyline({
      map: state.map,
      path: feature.geometry.coordinates.map((point) => ({ lat: Number(point[1]), lng: Number(point[0]) })),
      ...overlayStyle(feature.properties, false),
    });
    line.addListener('click', () => selectFeature(feature.id));
    return line;
  }

  function createPolygonOverlay(feature, coordinates) {
    const polygon = new google.maps.Polygon({
      map: state.map,
      paths: coordinates.map((ring) => ring.slice(0, -1).map((point) => ({ lat: Number(point[1]), lng: Number(point[0]) }))),
      ...overlayStyle(feature.properties, false),
    });
    polygon.addListener('click', () => selectFeature(feature.id));
    return polygon;
  }

  function buildOverlays(feature) {
    const type = feature.geometry.type;
    if (type === 'Point') return [createMarker(feature)];
    if (type === 'LineString') return [createPolyline(feature)];
    if (type === 'Polygon') return [createPolygonOverlay(feature, feature.geometry.coordinates)];
    if (type === 'MultiPolygon') {
      return feature.geometry.coordinates.map((polygon) => createPolygonOverlay(feature, polygon));
    }
    return [];
  }

  function addFeature(rawFeature, { select = false } = {}) {
    const feature = normalizeFeature(rawFeature);
    if (state.items.has(feature.id)) removeFeature(feature.id);
    const item = { feature, overlays: buildOverlays(feature) };
    state.items.set(feature.id, item);
    if (select) selectFeature(feature.id);
    refreshList();
    return feature.id;
  }

  function serializeItem(item) {
    const feature = JSON.parse(JSON.stringify(item.feature));
    const type = feature.geometry.type;
    if (type === 'Point') {
      const position = item.overlays[0].getPosition();
      feature.geometry.coordinates = [position.lng(), position.lat()];
    } else if (type === 'LineString') {
      feature.geometry.coordinates = pathToCoordinates(item.overlays[0].getPath());
    } else if (type === 'Polygon') {
      feature.geometry.coordinates = pathsToCoordinates(item.overlays[0].getPaths());
    } else if (type === 'MultiPolygon') {
      feature.geometry.coordinates = item.overlays.map((overlay) => pathsToCoordinates(overlay.getPaths()));
    }
    return feature;
  }

  function collectionSnapshot() {
    return {
      type: 'FeatureCollection',
      features: Array.from(state.items.values()).map(serializeItem),
    };
  }

  function setOverlaySelected(item, selected) {
    item.overlays.forEach((overlay) => {
      if (overlay instanceof google.maps.Marker) {
        overlay.setDraggable(selected);
        overlay.setAnimation(selected ? google.maps.Animation.BOUNCE : null);
        if (selected) window.setTimeout(() => overlay.setAnimation(null), 500);
      } else {
        overlay.setOptions(overlayStyle(item.feature.properties, selected));
      }
    });
  }

  function selectFeature(id) {
    if (state.selectedId && state.items.has(state.selectedId)) {
      setOverlaySelected(state.items.get(state.selectedId), false);
    }
    state.selectedId = state.items.has(id) ? id : null;
    if (!state.selectedId) {
      refreshList();
      return;
    }
    const item = state.items.get(state.selectedId);
    setOverlaySelected(item, true);
    populateForm(item.feature);
    refreshList();
  }

  function removeFeature(id) {
    const item = state.items.get(id);
    if (!item) return;
    item.overlays.forEach((overlay) => overlay.setMap(null));
    state.items.delete(id);
    if (state.selectedId === id) state.selectedId = null;
    refreshList();
  }

  function populateForm(feature) {
    const properties = feature.properties || {};
    byId('market-feature-kind').value = properties.kind || 'district';
    byId('market-feature-name').value = properties.name || '';
    byId('market-feature-passage').value = properties.passage_id ? String(properties.passage_id) : '';
    byId('market-feature-container').value = properties.container_id ? String(properties.container_id) : '';
    byId('market-feature-title').value = properties.title || '';
    byId('market-feature-min-zoom').value = Number(properties.min_zoom ?? 14);
    byId('market-feature-stroke-width').value = Number(properties.stroke_width ?? 2);
    byId('market-feature-stroke').value = String(properties.stroke_color || '#e47f26').slice(0, 7);
    byId('market-feature-fill').value = String(properties.fill_color || '#ff8656').slice(0, 7);
  }

  function applyForm() {
    const item = state.items.get(state.selectedId);
    if (!item) {
      setStatus('Сначала выберите объект на карте', 'error');
      return;
    }
    const kind = byId('market-feature-kind').value;
    const family = geometryFamily(item.feature.geometry.type);
    const expected = expectedFamily(kind);
    if (expected !== family && !(expected === 'line-or-polygon' && (family === 'line' || family === 'polygon'))) {
      setStatus(`Тип «${featureKindLabel(kind)}» не подходит для геометрии ${item.feature.geometry.type}`, 'error');
      return;
    }
    const name = byId('market-feature-name').value.trim();
    if (!name) {
      setStatus('Введите название или номер объекта', 'error');
      return;
    }

    const properties = item.feature.properties;
    properties.kind = kind;
    properties.name = name;
    properties.passage_id = Number(byId('market-feature-passage').value || 0) || null;
    properties.container_id = Number(byId('market-feature-container').value || 0) || null;
    properties.title = byId('market-feature-title').value.trim();
    properties.min_zoom = Math.max(0, Math.min(22, Number(byId('market-feature-min-zoom').value || 0)));
    properties.stroke_width = Math.max(1, Math.min(12, Number(byId('market-feature-stroke-width').value || 2)));
    properties.stroke_color = byId('market-feature-stroke').value;
    properties.fill_color = byId('market-feature-fill').value;
    if (kind === 'container') {
      const selectedOption = byId('market-feature-container').selectedOptions[0];
      properties.number = selectedOption?.dataset.number || name;
      if (!properties.passage_id && selectedOption?.dataset.passageId) {
        properties.passage_id = Number(selectedOption.dataset.passageId);
        byId('market-feature-passage').value = String(properties.passage_id);
      }
    }
    item.overlays.forEach((overlay) => {
      if (overlay instanceof google.maps.Marker) {
        overlay.setTitle(name);
      } else {
        overlay.setOptions(overlayStyle(properties, true));
      }
    });
    refreshList();
    setStatus('Свойства объекта применены', 'success');
  }

  function refreshList() {
    const list = byId('market-feature-list');
    if (!list) return;
    list.innerHTML = '';
    const sorted = Array.from(state.items.values()).sort((a, b) => {
      const ak = a.feature.properties.kind || '';
      const bk = b.feature.properties.kind || '';
      return ak.localeCompare(bk) || String(a.feature.properties.name || '').localeCompare(String(b.feature.properties.name || ''));
    });
    sorted.forEach((item) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = item.feature.id === state.selectedId ? 'active' : '';
      const name = document.createElement('span');
      name.textContent = item.feature.properties.name || item.feature.id;
      const type = document.createElement('small');
      type.textContent = featureKindLabel(item.feature.properties.kind);
      button.append(name, type);
      button.addEventListener('click', () => selectFeature(item.feature.id));
      list.append(button);
    });
    if (!sorted.length) {
      const empty = document.createElement('p');
      empty.className = 'help';
      empty.textContent = 'Объектов пока нет.';
      list.append(empty);
    }
  }

  function clearPreview() {
    if (state.preview) state.preview.setMap(null);
    state.preview = null;
    state.drawing = [];
    const actions = document.querySelector('.market-map-draw-actions');
    if (actions) actions.hidden = true;
  }

  function setTool(tool) {
    clearPreview();
    state.tool = tool;
    document.querySelectorAll('[data-map-tool]').forEach((button) => {
      button.classList.toggle('active', button.dataset.mapTool === tool);
    });
    if (state.map) {
      state.map.setOptions({ draggableCursor: tool === 'select' ? null : 'crosshair' });
    }
    setStatus(tool === 'select' ? 'Выберите объект или инструмент рисования' : 'Ставьте точки кликами по карте');
  }

  function updatePreview() {
    if (!state.preview) {
      state.preview = new google.maps.Polyline({
        map: state.map,
        path: state.drawing,
        strokeColor: '#e47f26',
        strokeWeight: 3,
        strokeOpacity: 0.95,
      });
    } else {
      state.preview.setPath(state.drawing);
    }
    const actions = document.querySelector('.market-map-draw-actions');
    if (actions) actions.hidden = false;
  }

  function mapClick(event) {
    if (state.tool === 'select') {
      selectFeature(null);
      return;
    }
    if (state.tool === 'marker') {
      const properties = defaultProperties('container');
      const id = makeId('container');
      addFeature({
        type: 'Feature',
        id,
        properties,
        geometry: { type: 'Point', coordinates: [event.latLng.lng(), event.latLng.lat()] },
      }, { select: true });
      setTool('select');
      setStatus('Контейнер добавлен. Заполните его свойства.', 'success');
      return;
    }
    state.drawing.push(event.latLng);
    updatePreview();
  }

  function finishDrawing() {
    if (state.tool === 'line' && state.drawing.length < 2) {
      setStatus('Для линии нужно минимум две точки', 'error');
      return;
    }
    if (state.tool === 'polygon' && state.drawing.length < 3) {
      setStatus('Для зоны нужно минимум три точки', 'error');
      return;
    }
    if (state.tool !== 'line' && state.tool !== 'polygon') return;

    const kind = state.tool === 'line' ? 'row' : 'district';
    const coordinates = state.drawing.map((point) => [point.lng(), point.lat()]);
    const geometry = state.tool === 'line'
      ? { type: 'LineString', coordinates }
      : { type: 'Polygon', coordinates: [[...coordinates, [...coordinates[0]]]] };
    const id = makeId(kind);
    addFeature({ type: 'Feature', id, properties: defaultProperties(kind), geometry }, { select: true });
    setTool('select');
    setStatus('Объект добавлен. Уточните название и свойства.', 'success');
  }

  function allBounds() {
    const bounds = new google.maps.LatLngBounds();
    let count = 0;
    const visit = (coordinates) => {
      if (Array.isArray(coordinates) && coordinates.length >= 2 && typeof coordinates[0] === 'number' && typeof coordinates[1] === 'number') {
        bounds.extend({ lat: Number(coordinates[1]), lng: Number(coordinates[0]) });
        count += 1;
      } else if (Array.isArray(coordinates)) {
        coordinates.forEach(visit);
      }
    };
    state.items.forEach((item) => visit(item.feature.geometry.coordinates));
    return count ? bounds : null;
  }

  async function persist(url, publish = false) {
    const button = publish ? byId('market-map-publish') : byId('market-map-save');
    if (!url || !button) return;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = publish ? 'Публикуем…' : 'Сохраняем…';
    setStatus(publish ? 'Проверяем и публикуем карту…' : 'Сохраняем черновик…');
    try {
      const response = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ geojson: collectionSnapshot() }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        const errors = Array.isArray(data.errors) ? data.errors.join(' ') : 'Не удалось сохранить карту';
        throw new Error(errors);
      }
      setStatus(
        publish
          ? `Карта опубликована: версия ${data.version}`
          : `Черновик версии ${data.version} сохранён`,
        'success',
      );
    } catch (error) {
      setStatus(error.message || 'Ошибка сохранения карты', 'error');
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  function bindControls() {
    document.querySelectorAll('[data-map-tool]').forEach((button) => {
      button.addEventListener('click', () => setTool(button.dataset.mapTool));
    });
    byId('market-map-finish')?.addEventListener('click', finishDrawing);
    byId('market-map-cancel')?.addEventListener('click', () => setTool('select'));
    byId('market-feature-apply')?.addEventListener('click', applyForm);
    byId('market-feature-delete')?.addEventListener('click', () => {
      if (!state.selectedId) return;
      if (window.confirm('Удалить выбранный объект?')) removeFeature(state.selectedId);
    });
    byId('market-feature-container')?.addEventListener('change', (event) => {
      const option = event.target.selectedOptions[0];
      if (!option?.value) return;
      byId('market-feature-passage').value = option.dataset.passageId || '';
      byId('market-feature-name').value = option.dataset.number || byId('market-feature-name').value;
    });
    byId('market-map-save')?.addEventListener('click', () => persist(root().dataset.saveUrl, false));
    byId('market-map-publish')?.addEventListener('click', () => {
      if (window.confirm('Опубликовать эту версию карты для мобильного приложения?')) {
        persist(root().dataset.publishUrl, true);
      }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') setTool('select');
      if ((event.key === 'Delete' || event.key === 'Backspace') && state.selectedId && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
        removeFeature(state.selectedId);
      }
    });
  }

  window.initMarketMapEditor = function initMarketMapEditor() {
    const canvas = byId('market-map-canvas');
    if (!canvas || !window.google?.maps) return;
    const initial = readJsonScript('market-map-initial-geojson', { type: 'FeatureCollection', features: [] });
    state.map = new google.maps.Map(canvas, {
      center: { lat: 42.8746, lng: 74.6122 },
      zoom: 15,
      mapTypeControl: true,
      streetViewControl: false,
      fullscreenControl: true,
      clickableIcons: false,
      disableDoubleClickZoom: true,
      gestureHandling: 'greedy',
    });
    state.map.addListener('click', mapClick);
    state.map.addListener('dblclick', () => finishDrawing());
    bindControls();
    (initial.features || []).forEach((feature) => addFeature(feature));
    const bounds = allBounds();
    if (bounds) state.map.fitBounds(bounds, 48);
    refreshList();
    setStatus('Карта готова. Изменения пока находятся в черновике.', 'success');
  };
})();
