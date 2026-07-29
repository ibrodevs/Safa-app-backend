(() => {
  'use strict';

  const state = {
    map: null,
    tool: 'select',
    drawingKind: null,
    items: new Map(),
    selectedId: null,
    drawing: [],
    preview: null,
    counter: 0,
  };

  const byId = (id) => document.getElementById(id);
  const root = () => byId('market-map-editor');
  const KIND_ORDER = ['bazar', 'district', 'sector', 'row', 'passage', 'container'];

  const KIND_CONFIG = {
    bazar: {
      label: 'Граница базара',
      family: 'polygon',
      name: () => root()?.dataset.bazarName || 'Базар',
      minZoom: 10,
      strokeWidth: 4,
      strokeColor: '#ff6b35',
      fillColor: '#ff6b35',
      fillOpacity: 0.12,
      zIndex: 10,
      hint: 'Нарисуйте внешний контур всего базара.',
    },
    district: {
      label: 'Район',
      family: 'polygon',
      name: 'Новый район',
      minZoom: 13,
      strokeWidth: 3,
      strokeColor: '#2563eb',
      fillColor: '#60a5fa',
      fillOpacity: 0.16,
      zIndex: 20,
      hint: 'Обведите крупный район внутри базара.',
    },
    sector: {
      label: 'Сектор',
      family: 'polygon',
      name: 'Новый сектор',
      minZoom: 14,
      strokeWidth: 2,
      strokeColor: '#16a34a',
      fillColor: '#4ade80',
      fillOpacity: 0.18,
      zIndex: 30,
      hint: 'Обведите сектор меньшего уровня.',
    },
    row: {
      label: 'Ряд',
      family: 'line',
      name: 'Новый ряд',
      minZoom: 16,
      strokeWidth: 3,
      strokeColor: '#7c3aed',
      fillColor: '#a78bfa',
      fillOpacity: 0,
      zIndex: 50,
      linePattern: 'dashed',
      hint: 'Проведите линию ряда по центру прохода.',
    },
    passage: {
      label: 'Проход',
      family: 'line',
      name: 'Новый проход',
      minZoom: 16,
      strokeWidth: 5,
      strokeColor: '#d97706',
      fillColor: '#fbbf24',
      fillOpacity: 0,
      zIndex: 60,
      linePattern: 'solid',
      hint: 'Проведите основную линию прохода.',
    },
    container: {
      label: 'Контейнер',
      family: 'point',
      name: 'Новый контейнер',
      minZoom: 17,
      strokeWidth: 2,
      strokeColor: '#dc2626',
      fillColor: '#ef4444',
      fillOpacity: 1,
      zIndex: 100,
      hint: 'Поставьте точку в центре контейнера.',
    },
  };

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
    return KIND_CONFIG[kind]?.label || kind;
  }

  function existingFeatureByKind(kind) {
    for (const item of state.items.values()) {
      if (item.feature.properties.kind === kind) return item.feature.id;
    }
    return null;
  }

  function geometryFamily(type) {
    if (type === 'Point') return 'point';
    if (type === 'LineString') return 'line';
    if (type === 'Polygon' || type === 'MultiPolygon') return 'polygon';
    return 'unknown';
  }

  function expectedFamily(kind) {
    return KIND_CONFIG[kind]?.family || 'polygon';
  }

  function defaultProperties(kind) {
    const config = KIND_CONFIG[kind] || KIND_CONFIG.district;
    const name = typeof config.name === 'function' ? config.name() : config.name;
    return {
      kind,
      name,
      bazar_id: Number(root()?.dataset.bazarId || 0),
      min_zoom: config.minZoom,
      stroke_width: config.strokeWidth,
      stroke_color: config.strokeColor,
      fill_color: config.fillColor,
      fill_opacity: config.fillOpacity,
      z_index: config.zIndex,
      line_pattern: config.linePattern || 'solid',
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
    const kind = properties.kind || 'district';
    const config = KIND_CONFIG[kind] || KIND_CONFIG.district;
    const strokeWidth = Number(properties.stroke_width || config.strokeWidth || 2) + (selected ? 1 : 0);
    const linePattern = properties.line_pattern || config.linePattern || 'solid';
    const icons = linePattern === 'dashed'
      ? [{
          icon: { path: 'M 0,-1 0,1', strokeOpacity: 1, scale: 3 },
          offset: '0',
          repeat: '14px',
        }]
      : null;
    return {
      strokeColor: properties.stroke_color || config.strokeColor,
      strokeOpacity: linePattern === 'dashed' ? 0 : 1,
      strokeWeight: strokeWidth,
      fillColor: properties.fill_color || config.fillColor,
      fillOpacity: selected
        ? Math.max(Number(properties.fill_opacity ?? config.fillOpacity), 0.28)
        : Number(properties.fill_opacity ?? config.fillOpacity),
      icons,
      clickable: true,
      editable: selected,
      draggable: selected,
      zIndex: selected ? 1000 : Number(properties.z_index || config.zIndex || 1),
    };
  }

  function markerIcon(properties, selected = false) {
    const fill = properties.fill_color || KIND_CONFIG.container.fillColor;
    const stroke = properties.stroke_color || KIND_CONFIG.container.strokeColor;
    return {
      path: google.maps.SymbolPath.CIRCLE,
      fillColor: fill,
      fillOpacity: 1,
      strokeColor: stroke,
      strokeWeight: selected ? 3 : 2,
      scale: selected ? 9 : 7,
    };
  }

  function createMarker(feature) {
    const coordinates = feature.geometry.coordinates;
    const marker = new google.maps.Marker({
      map: state.map,
      position: { lat: Number(coordinates[1]), lng: Number(coordinates[0]) },
      title: feature.properties.name,
      icon: markerIcon(feature.properties),
      label: {
        text: String(feature.properties.number || '').slice(0, 4),
        color: '#ffffff',
        fontSize: '10px',
        fontWeight: '700',
      },
      draggable: false,
      clickable: true,
      zIndex: Number(feature.properties.z_index || KIND_CONFIG.container.zIndex),
    });
    marker.addListener('click', (event) => {
      if (state.tool === 'draw') {
        mapClick(event);
        return;
      }
      selectFeature(feature.id);
    });
    marker.addListener('dragend', () => refreshList());
    return marker;
  }

  function createPolyline(feature) {
    const line = new google.maps.Polyline({
      map: state.map,
      path: feature.geometry.coordinates.map((point) => ({ lat: Number(point[1]), lng: Number(point[0]) })),
      ...overlayStyle(feature.properties, false),
    });
    line.addListener('click', (event) => {
      if (state.tool === 'draw') {
        mapClick(event);
        return;
      }
      selectFeature(feature.id);
    });
    return line;
  }

  function createPolygonOverlay(feature, coordinates) {
    const polygon = new google.maps.Polygon({
      map: state.map,
      paths: coordinates.map((ring) => ring.slice(0, -1).map((point) => ({ lat: Number(point[1]), lng: Number(point[0]) }))),
      ...overlayStyle(feature.properties, false),
    });
    polygon.addListener('click', (event) => {
      if (state.tool === 'draw') {
        mapClick(event);
        return;
      }
      selectFeature(feature.id);
    });
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
        overlay.setIcon(markerIcon(item.feature.properties, selected));
        overlay.setZIndex(selected ? 1000 : Number(item.feature.properties.z_index || KIND_CONFIG.container.zIndex));
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
      updatePropertyVisibility(null);
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
    updatePropertyVisibility(properties.kind || 'district');
  }

  function updatePropertyVisibility(kind) {
    const isContainer = kind === 'container';
    document.querySelectorAll('[data-kind-scope="container"]').forEach((row) => {
      row.hidden = !isContainer;
    });
  }

  function applyForm() {
    const item = state.items.get(state.selectedId);
    if (!item) {
      setStatus('Сначала выберите объект на карте', 'error');
      return;
    }
    const kind = item.feature.properties.kind;
    const family = geometryFamily(item.feature.geometry.type);
    const expected = expectedFamily(kind);
    if (expected !== family) {
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
    properties.min_zoom = Math.max(0, Math.min(22, Number(byId('market-feature-min-zoom').value || 0)));
    properties.stroke_width = Math.max(1, Math.min(12, Number(byId('market-feature-stroke-width').value || 2)));
    properties.stroke_color = byId('market-feature-stroke').value;
    properties.fill_color = byId('market-feature-fill').value;
    properties.fill_opacity = KIND_CONFIG[kind]?.fillOpacity ?? properties.fill_opacity ?? 0.2;
    properties.z_index = KIND_CONFIG[kind]?.zIndex ?? properties.z_index ?? 1;
    properties.line_pattern = KIND_CONFIG[kind]?.linePattern || properties.line_pattern || 'solid';
    if (kind === 'container') {
      properties.passage_id = Number(byId('market-feature-passage').value || 0) || null;
      properties.container_id = Number(byId('market-feature-container').value || 0) || null;
      properties.title = byId('market-feature-title').value.trim();
      const selectedOption = byId('market-feature-container').selectedOptions[0];
      properties.number = selectedOption?.dataset.number || name;
      if (!properties.passage_id && selectedOption?.dataset.passageId) {
        properties.passage_id = Number(selectedOption.dataset.passageId);
        byId('market-feature-passage').value = String(properties.passage_id);
      }
    } else {
      delete properties.passage_id;
      delete properties.container_id;
      delete properties.title;
      delete properties.number;
    }
    item.overlays.forEach((overlay) => {
      if (overlay instanceof google.maps.Marker) {
        overlay.setTitle(name);
        overlay.setIcon(markerIcon(properties, true));
        overlay.setLabel({
          text: String(properties.number || '').slice(0, 4),
          color: '#ffffff',
          fontSize: '10px',
          fontWeight: '700',
        });
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
      const ai = KIND_ORDER.indexOf(ak);
      const bi = KIND_ORDER.indexOf(bk);
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi) ||
        String(a.feature.properties.name || '').localeCompare(String(b.feature.properties.name || ''));
    });
    KIND_ORDER.forEach((kind) => {
      const group = sorted.filter((item) => item.feature.properties.kind === kind);
      if (!group.length) return;
      const heading = document.createElement('div');
      heading.className = 'market-feature-group';
      heading.textContent = featureKindLabel(kind);
      list.append(heading);
      group.forEach((item) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = item.feature.id === state.selectedId ? 'active' : '';
        button.dataset.kind = item.feature.properties.kind || '';
        const name = document.createElement('span');
        name.textContent = item.feature.properties.name || item.feature.id;
        const type = document.createElement('small');
        type.textContent = item.feature.geometry.type;
        button.append(name, type);
        button.addEventListener('click', () => selectFeature(item.feature.id));
        list.append(button);
      });
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

  function setTool(tool, kind = null) {
    clearPreview();
    if (tool === 'draw' && kind === 'bazar') {
      const existing = existingFeatureByKind('bazar');
      if (existing) {
        selectFeature(existing);
        setStatus('Граница базара уже есть. Отредактируйте её или удалите перед созданием новой.', 'error');
        return;
      }
    }
    state.tool = tool;
    state.drawingKind = tool === 'draw' ? kind : null;
    document.querySelectorAll('[data-map-tool]').forEach((button) => {
      const active = tool === 'select'
        ? button.dataset.mapTool === 'select'
        : button.dataset.mapTool === 'draw' && button.dataset.mapKind === kind;
      button.classList.toggle('active', active);
    });
    document.querySelectorAll('.market-kind-section').forEach((section) => {
      const button = section.querySelector('[data-map-kind]');
      section.classList.toggle('active', tool === 'draw' && button?.dataset.mapKind === kind);
    });
    if (state.map) {
      state.map.setOptions({ draggableCursor: tool === 'select' ? null : 'crosshair' });
    }
    const config = KIND_CONFIG[kind];
    setStatus(tool === 'select' ? 'Выберите объект или инструмент рисования' : config?.hint || 'Ставьте точки кликами по карте');
  }

  function updatePreview() {
    const properties = defaultProperties(state.drawingKind || 'district');
    if (!state.preview) {
      state.preview = new google.maps.Polyline({
        map: state.map,
        path: state.drawing,
        ...overlayStyle(properties, false),
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
    const kind = state.drawingKind || 'district';
    if (kind === 'bazar' && existingFeatureByKind('bazar')) {
      selectFeature(existingFeatureByKind('bazar'));
      setTool('select');
      setStatus('На карте может быть только одна граница базара.', 'error');
      return;
    }
    const family = expectedFamily(kind);
    if (family === 'point') {
      const properties = defaultProperties(kind);
      const id = makeId(kind);
      addFeature({
        type: 'Feature',
        id,
        properties,
        geometry: { type: 'Point', coordinates: [event.latLng.lng(), event.latLng.lat()] },
      }, { select: true });
      setTool('select');
      setStatus(`${featureKindLabel(kind)} добавлен. Заполните его свойства.`, 'success');
      return;
    }
    state.drawing.push(event.latLng);
    updatePreview();
  }

  function finishDrawing() {
    const kind = state.drawingKind;
    const family = expectedFamily(kind);
    if (family === 'line' && state.drawing.length < 2) {
      setStatus('Для линии нужно минимум две точки', 'error');
      return;
    }
    if (family === 'polygon' && state.drawing.length < 3) {
      setStatus('Для площади нужно минимум три точки', 'error');
      return;
    }
    if (state.tool !== 'draw' || !kind || family === 'point') return;

    const coordinates = state.drawing.map((point) => [point.lng(), point.lat()]);
    const geometry = family === 'line'
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
      button.addEventListener('click', () => setTool(button.dataset.mapTool, button.dataset.mapKind || null));
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
