(() => {
  'use strict';

  const state = {
    map: null,
    tool: 'select',
    drawingKind: null,
    items: new Map(),
    contextItems: [],
    selectedId: null,
    drawing: [],
    preview: null,
    counter: 0,
    history: [],
    historyIndex: -1,
    restoringHistory: false,
  };

  const byId = (id) => document.getElementById(id);
  const root = () => byId('market-map-editor');
  const KIND_ORDER = ['bazar', 'district', 'passage', 'container', 'sector', 'row'];

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
      label: 'Граница района',
      family: 'polygon',
      name: 'Новый район',
      minZoom: 13,
      strokeWidth: 3,
      strokeColor: '#2563eb',
      fillColor: '#60a5fa',
      fillOpacity: 0.16,
      zIndex: 20,
      hint: 'Нарисуйте внешний контур района внутри базара.',
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
      hint: 'Проведите длинную стрелку прохода. Двойной клик завершает линию.',
    },
    container: {
      label: 'Контейнер',
      family: 'polygon',
      name: 'Новый контейнер',
      minZoom: 17,
      strokeWidth: 2,
      strokeColor: '#dc2626',
      fillColor: '#ef4444',
      fillOpacity: 1,
      zIndex: 100,
      hint: 'Кликните по центру контейнера — редактор создаст прямоугольник.',
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

  function containerRectangle(latLng) {
    const halfWidth = 0.000018;
    const halfHeight = 0.000012;
    const lng = latLng.lng();
    const lat = latLng.lat();
    return [
      [lng - halfWidth, lat + halfHeight],
      [lng + halfWidth, lat + halfHeight],
      [lng + halfWidth, lat - halfHeight],
      [lng - halfWidth, lat - halfHeight],
      [lng - halfWidth, lat + halfHeight],
    ];
  }

  function metersToLat(meters) {
    return Number(meters || 0) / 111320;
  }

  function metersToLng(meters, lat) {
    const cos = Math.max(0.2, Math.cos((Number(lat) || 0) * Math.PI / 180));
    return Number(meters || 0) / (111320 * cos);
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

  function rectangleFromRing(ring) {
    const points = ring || [];
    const lons = points.map((point) => point[0]);
    const lats = points.map((point) => point[1]);
    if (!lons.length || !lats.length) return ring;
    const left = Math.min(...lons);
    const right = Math.max(...lons);
    const bottom = Math.min(...lats);
    const top = Math.max(...lats);
    return [
      [left, top],
      [right, top],
      [right, bottom],
      [left, bottom],
      [left, top],
    ];
  }

  function rectangleBounds(ring) {
    const rectangle = rectangleFromRing(ring);
    const lons = rectangle.map((point) => point[0]);
    const lats = rectangle.map((point) => point[1]);
    return {
      left: Math.min(...lons),
      right: Math.max(...lons),
      bottom: Math.min(...lats),
      top: Math.max(...lats),
    };
  }

  function rectangleFromBounds(bounds) {
    return [
      [bounds.left, bounds.top],
      [bounds.right, bounds.top],
      [bounds.right, bounds.bottom],
      [bounds.left, bounds.bottom],
      [bounds.left, bounds.top],
    ];
  }

  function resizeContainerCoordinates(coordinates, widthM, heightM) {
    const ring = rectangleFromRing(coordinates?.[0] || []);
    const bounds = rectangleBounds(ring);
    const centerLon = (bounds.left + bounds.right) / 2;
    const centerLat = (bounds.top + bounds.bottom) / 2;
    const halfWidth = metersToLng(widthM, centerLat) / 2;
    const halfHeight = metersToLat(heightM) / 2;
    return [rectangleFromBounds({
      left: centerLon - halfWidth,
      right: centerLon + halfWidth,
      bottom: centerLat - halfHeight,
      top: centerLat + halfHeight,
    })];
  }

  function setPolygonCoordinates(overlay, coordinates) {
    overlay.setPaths(coordinates.map((ring) => ring.slice(0, -1).map((point) => ({ lat: Number(point[1]), lng: Number(point[0]) }))));
  }

  function syncContainerSizeFields(coordinates) {
    const bounds = rectangleBounds(rectangleFromRing((coordinates || [[]])[0]));
    const centerLat = (bounds.top + bounds.bottom) / 2;
    byId('market-feature-width-m').value = Math.max(0.5, Math.round((bounds.right - bounds.left) * 111320 * Math.cos(centerLat * Math.PI / 180) * 10) / 10);
    byId('market-feature-height-m').value = Math.max(0.5, Math.round((bounds.top - bounds.bottom) * 111320 * 10) / 10);
  }

  function normalizeContainerItem(item) {
    if (!item || (item.feature.properties || {}).kind !== 'container') return;
    const snapshot = serializeItem(item);
    snapshot.geometry.coordinates = [rectangleFromRing((snapshot.geometry.coordinates || [[]])[0])];
    item.feature.geometry.coordinates = snapshot.geometry.coordinates;
    item.overlays.forEach((overlay) => {
      if (!(overlay instanceof google.maps.Marker)) {
        setPolygonCoordinates(overlay, item.feature.geometry.coordinates);
        overlay.setOptions(overlayStyle(item.feature.properties, true));
      }
    });
    syncContainerSizeFields(item.feature.geometry.coordinates);
    updateFeatureLabel(item);
  }

  function overlayStyle(properties, selected) {
    const kind = properties.kind || 'district';
    const config = KIND_CONFIG[kind] || KIND_CONFIG.district;
    const strokeWidth = Number(properties.stroke_width || config.strokeWidth || 2) + (selected ? 1 : 0);
    const linePattern = properties.line_pattern || config.linePattern || 'solid';
    let icons = null;
    if (kind === 'passage') {
      icons = [{
        icon: {
          path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
          strokeOpacity: 1,
          fillOpacity: 1,
          scale: 3,
        },
        offset: '100%',
      }];
    } else if (linePattern === 'dashed') {
      icons = [{
        icon: { path: 'M 0,-1 0,1', strokeOpacity: 1, scale: 3 },
        offset: '0',
        repeat: '14px',
      }];
    }
    return {
      strokeColor: properties.stroke_color || config.strokeColor,
      strokeOpacity: linePattern === 'dashed' ? 0 : 1,
      strokeWeight: strokeWidth,
      fillColor: properties.fill_color || config.fillColor,
      fillOpacity: selected
        ? Math.max(Number(properties.fill_opacity ?? config.fillOpacity), 0.28)
        : Number(properties.fill_opacity ?? config.fillOpacity),
      icons,
      clickable: !properties.readonly,
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

  function containerLabelText(properties) {
    return String(properties.number || properties.name || '').trim();
  }

  function featureLabelText(feature) {
    const properties = feature.properties || {};
    if (properties.kind === 'container') return containerLabelText(properties);
    if (properties.kind === 'bazar' || properties.kind === 'district' || properties.kind === 'passage') {
      return String(properties.name || '').trim();
    }
    return '';
  }

  function geometryCenter(geometry) {
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
    visit(geometry.coordinates);
    return count ? bounds.getCenter() : null;
  }

  function overlayCenter(overlay) {
    if (overlay instanceof google.maps.Marker) return overlay.getPosition();
    const bounds = new google.maps.LatLngBounds();
    const path = overlay.getPath?.();
    if (path) {
      for (let i = 0; i < path.getLength(); i += 1) {
        bounds.extend(path.getAt(i));
      }
      return bounds.isEmpty() ? null : bounds.getCenter();
    }
    const paths = overlay.getPaths?.();
    if (!paths) return null;
    for (let i = 0; i < paths.getLength(); i += 1) {
      const path = paths.getAt(i);
      for (let j = 0; j < path.getLength(); j += 1) {
        bounds.extend(path.getAt(j));
      }
    }
    return bounds.isEmpty() ? null : bounds.getCenter();
  }

  function createFeatureLabel(feature) {
    const kind = (feature.properties || {}).kind;
    if (!['bazar', 'district', 'passage', 'container'].includes(kind)) return null;
    const text = featureLabelText(feature);
    if (!text) return null;
    const position = geometryCenter(feature.geometry);
    if (!position) return null;
    const color = kind === 'container' ? '#111827' : (feature.properties.stroke_color || '#111827');

    return new google.maps.Marker({
      map: state.map,
      position,
      clickable: false,
      zIndex: Number(feature.properties.z_index || KIND_CONFIG.container.zIndex) + 1,
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: 0,
        fillOpacity: 0,
        strokeOpacity: 0,
      },
      label: {
        text,
        color,
        fontSize: kind === 'container' ? '12px' : '13px',
        fontWeight: '800',
      },
    });
  }

  function updateFeatureLabel(item) {
    const kind = (item.feature.properties || {}).kind;
    if (!['bazar', 'district', 'passage', 'container'].includes(kind)) {
      if (item.label) item.label.setMap(null);
      item.label = null;
      return;
    }

    const text = featureLabelText(item.feature);
    const position = overlayCenter(item.overlays[0]) || geometryCenter(item.feature.geometry);
    if (!text || !position) {
      if (item.label) item.label.setMap(null);
      item.label = null;
      return;
    }

    if (!item.label) {
      item.label = createFeatureLabel(item.feature);
    }
    item.label.setPosition(position);
    item.label.setZIndex(Number(item.feature.properties.z_index || KIND_CONFIG.container.zIndex) + 1);
    item.label.setLabel({
      text,
      color: kind === 'container' ? '#111827' : (item.feature.properties.stroke_color || '#111827'),
      fontSize: kind === 'container' ? '12px' : '13px',
      fontWeight: '800',
    });
  }

  function createMarker(feature) {
    const coordinates = feature.geometry.coordinates;
    const marker = new google.maps.Marker({
      map: state.map,
      position: { lat: Number(coordinates[1]), lng: Number(coordinates[0]) },
      title: feature.properties.name,
      icon: markerIcon(feature.properties),
      label: {
        text: containerLabelText(feature.properties),
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
    marker.addListener('dragend', () => {
      refreshList();
      document.getElementById('market-map-editor')?.dispatchEvent(new CustomEvent('market-map:dirty'));
      recordHistory();
    });
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
    line.addListener('mouseup', () => {
      const item = state.items.get(feature.id);
      if (item) updateFeatureLabel(item);
      document.getElementById('market-map-editor')?.dispatchEvent(new CustomEvent('market-map:dirty'));
      recordHistory();
    });
    line.addListener('dragend', () => {
      const item = state.items.get(feature.id);
      if (item) updateFeatureLabel(item);
      document.getElementById('market-map-editor')?.dispatchEvent(new CustomEvent('market-map:dirty'));
      recordHistory();
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
      if ((feature.properties || {}).readonly) return;
      if (state.tool === 'draw') {
        mapClick(event);
        return;
      }
      selectFeature(feature.id);
    });
    polygon.addListener('mouseup', () => {
      const item = state.items.get(feature.id);
      if (item) {
        normalizeContainerItem(item);
        updateFeatureLabel(item);
      }
      document.getElementById('market-map-editor')?.dispatchEvent(new CustomEvent('market-map:dirty'));
      recordHistory();
    });
    polygon.addListener('dragend', () => {
      const item = state.items.get(feature.id);
      if (item) {
        normalizeContainerItem(item);
        updateFeatureLabel(item);
      }
      document.getElementById('market-map-editor')?.dispatchEvent(new CustomEvent('market-map:dirty'));
      recordHistory();
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
    const item = { feature, overlays: buildOverlays(feature), label: null };
    state.items.set(feature.id, item);
    updateFeatureLabel(item);
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
      if ((feature.properties || {}).kind === 'container') {
        feature.geometry.coordinates = [rectangleFromRing(feature.geometry.coordinates[0])];
      }
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

  function updateHistoryControls() {
    const undoButton = byId('market-map-undo');
    const redoButton = byId('market-map-redo');
    if (undoButton) undoButton.disabled = state.historyIndex <= 0;
    if (redoButton) redoButton.disabled = state.historyIndex >= state.history.length - 1;
  }

  function recordHistory(force = false) {
    if (state.restoringHistory || !state.map) return;
    const snapshot = collectionSnapshot();
    const serialized = JSON.stringify(snapshot);
    const current = state.history[state.historyIndex];
    if (!force && current?.serialized === serialized) return;
    state.history = state.history.slice(0, state.historyIndex + 1);
    state.history.push({ snapshot, serialized });
    if (state.history.length > 80) state.history.shift();
    state.historyIndex = state.history.length - 1;
    updateHistoryControls();
  }

  function restoreHistory(index) {
    const entry = state.history[index];
    if (!entry) return;
    state.restoringHistory = true;
    selectFeature(null);
    state.items.forEach((item) => {
      item.overlays.forEach((overlay) => overlay.setMap(null));
      if (item.label) item.label.setMap(null);
    });
    state.items.clear();
    (entry.snapshot.features || []).forEach((feature) => addFeature(feature));
    state.historyIndex = index;
    state.restoringHistory = false;
    refreshList();
    updateHistoryControls();
    root()?.dispatchEvent(new CustomEvent('market-map:dirty'));
  }

  function undoHistory() {
    if (state.tool === 'draw' && state.drawing.length) {
      state.drawing.pop();
      if (state.drawing.length) {
        state.preview?.setPath(state.drawing);
      } else {
        if (state.preview) state.preview.setMap(null);
        state.preview = null;
        const actions = document.querySelector('.market-map-draw-actions');
        if (actions) actions.hidden = true;
      }
      setStatus('Последняя точка рисунка удалена · Ctrl+Z', 'success');
      return;
    }
    if (state.historyIndex <= 0) return;
    restoreHistory(state.historyIndex - 1);
    setStatus('Последнее изменение отменено · Ctrl+Z', 'success');
  }

  function redoHistory() {
    if (state.historyIndex >= state.history.length - 1) return;
    restoreHistory(state.historyIndex + 1);
    setStatus('Изменение возвращено · Ctrl+Shift+Z', 'success');
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
    if (item.label) {
      item.label.setZIndex(selected ? 1001 : Number(item.feature.properties.z_index || KIND_CONFIG.container.zIndex) + 1);
    }
  }

  function selectFeature(id) {
    if (state.selectedId && state.items.has(state.selectedId)) {
      setOverlaySelected(state.items.get(state.selectedId), false);
    }
    state.selectedId = state.items.has(id) ? id : null;
    const focus = focusedKind();
    if (state.selectedId && focus && state.items.get(state.selectedId).feature.properties.kind !== focus) {
      state.selectedId = null;
      setStatus(`В этом разделе редактируются только: ${featureKindLabel(focus)}`, 'error');
    }
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
    if (item.label) item.label.setMap(null);
    state.items.delete(id);
    if (state.selectedId === id) state.selectedId = null;
    refreshList();
  }

  function populateForm(feature) {
    const properties = feature.properties || {};
    const serialized = state.items.has(feature.id) ? serializeItem(state.items.get(feature.id)) : feature;
    const containerBounds = properties.kind === 'container'
      ? rectangleBounds(rectangleFromRing((serialized.geometry.coordinates || [[]])[0]))
      : null;
    const centerLat = containerBounds ? (containerBounds.top + containerBounds.bottom) / 2 : 42.8746;
    byId('market-feature-kind').value = properties.kind || 'district';
    byId('market-feature-name').value = properties.name || '';
    byId('market-feature-number').value = properties.number || '';
    byId('market-feature-passage').value = properties.passage_id ? String(properties.passage_id) : '';
    byId('market-feature-container').value = properties.container_id ? String(properties.container_id) : '';
    byId('market-feature-title').value = properties.title || '';
    byId('market-feature-min-zoom').value = Number(properties.min_zoom ?? 14);
    byId('market-feature-stroke-width').value = Number(properties.stroke_width ?? 2);
    byId('market-feature-stroke').value = String(properties.stroke_color || '#e47f26').slice(0, 7);
    byId('market-feature-fill').value = String(properties.fill_color || '#ff8656').slice(0, 7);
    if (containerBounds) {
      byId('market-feature-width-m').value = Math.max(0.5, Math.round((containerBounds.right - containerBounds.left) * 111320 * Math.cos(centerLat * Math.PI / 180) * 10) / 10);
      byId('market-feature-height-m').value = Math.max(0.5, Math.round((containerBounds.top - containerBounds.bottom) * 111320 * 10) / 10);
    }
    updatePropertyVisibility(properties.kind || 'district');
  }

  function updatePropertyVisibility(kind) {
    const isContainer = kind === 'container';
    document.querySelectorAll('[data-kind-scope="container"]').forEach((row) => {
      row.hidden = !isContainer;
    });
    document.querySelectorAll('[data-kind-scope="not-container"]').forEach((row) => {
      row.hidden = isContainer;
    });
    document.querySelectorAll('[data-kind-scope="advanced-container"]').forEach((row) => {
      row.hidden = true;
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
    if (expected !== family && !(kind === 'container' && family === 'point')) {
      setStatus(`Тип «${featureKindLabel(kind)}» не подходит для геометрии ${item.feature.geometry.type}`, 'error');
      return;
    }
    const containerNumber = byId('market-feature-number').value.trim();
    const name = item.feature.properties.kind === 'container'
      ? containerNumber
      : byId('market-feature-name').value.trim();
    if (!name) {
      setStatus(kind === 'container' ? 'Введите номер или название контейнера' : 'Введите название объекта', 'error');
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
      const serialized = serializeItem(item);
      const widthM = Math.max(0.5, Number(byId('market-feature-width-m').value || 4));
      const heightM = Math.max(0.5, Number(byId('market-feature-height-m').value || 2.5));
      serialized.geometry.coordinates = resizeContainerCoordinates(serialized.geometry.coordinates, widthM, heightM);
      item.feature.geometry.coordinates = serialized.geometry.coordinates;
      properties.passage_id = Number(byId('market-feature-passage').value || 0) || null;
      properties.container_id = Number(byId('market-feature-container').value || 0) || null;
      properties.title = byId('market-feature-title').value.trim();
      const selectedOption = byId('market-feature-container').selectedOptions[0];
      properties.number = containerNumber || selectedOption?.dataset.number || name;
      properties.name = properties.number;
      byId('market-feature-name').value = properties.name;
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
          text: containerLabelText(properties),
          color: '#ffffff',
          fontSize: '10px',
          fontWeight: '700',
        });
      } else {
        if (kind === 'container' && item.feature.geometry.type === 'Polygon') {
          setPolygonCoordinates(overlay, item.feature.geometry.coordinates);
        }
        overlay.setOptions(overlayStyle(properties, true));
      }
    });
    updateFeatureLabel(item);
    refreshList();
    setStatus('Свойства объекта применены', 'success');
    recordHistory();
  }

  function cloneCoordinatesWithOffset(coordinates, deltaLng, deltaLat) {
    if (Array.isArray(coordinates) && coordinates.length >= 2 && typeof coordinates[0] === 'number' && typeof coordinates[1] === 'number') {
      return [coordinates[0] + deltaLng, coordinates[1] + deltaLat];
    }
    return Array.isArray(coordinates)
      ? coordinates.map((item) => cloneCoordinatesWithOffset(item, deltaLng, deltaLat))
      : coordinates;
  }

  function adjacentContainerCoordinates(coordinates, direction) {
    const bounds = rectangleBounds(rectangleFromRing(coordinates?.[0] || []));
    const width = bounds.right - bounds.left;
    const height = bounds.top - bounds.bottom;
    const next = { ...bounds };
    switch (direction) {
      case 'left':
        next.left = bounds.left - width;
        next.right = bounds.left;
        break;
      case 'up':
        next.bottom = bounds.top;
        next.top = bounds.top + height;
        break;
      case 'down':
        next.bottom = bounds.bottom - height;
        next.top = bounds.bottom;
        break;
      case 'right':
      default:
        next.left = bounds.right;
        next.right = bounds.right + width;
        break;
    }
    return [rectangleFromBounds(next)];
  }

  function nextContainerNumber(value) {
    const raw = String(value || '').trim();
    const match = raw.match(/^(.*?)(\d+)$/);
    if (!match) return raw ? `${raw}-copy` : '';
    const prefix = match[1];
    const digits = match[2];
    const next = String(Number(digits) + 1).padStart(digits.length, '0');
    return `${prefix}${next}`;
  }

  function suggestedContainerNumber() {
    const numbers = Array.from(state.items.values())
      .filter((item) => (item.feature.properties || {}).kind === 'container')
      .map((item) => item.feature.properties.number || item.feature.properties.name)
      .filter(Boolean);
    return numbers.length ? nextContainerNumber(numbers[numbers.length - 1]) : '';
  }

  function duplicateSelectedFeature() {
    const item = state.items.get(state.selectedId);
    if (!item) {
      setStatus('Сначала выберите контейнер для дублирования', 'error');
      return;
    }
    if ((item.feature.properties || {}).kind !== 'container') {
      setStatus('Дублировать можно только контейнеры', 'error');
      return;
    }

    item.feature.properties.passage_id = Number(byId('market-feature-passage').value || 0) || null;
    item.feature.properties.title = byId('market-feature-title').value.trim();
    const currentNumber = byId('market-feature-number').value.trim();
    if (currentNumber) {
      item.feature.properties.name = currentNumber;
      item.feature.properties.number = currentNumber;
    }

    const source = serializeItem(item);
    const number = nextContainerNumber(source.properties.number || source.properties.name);
    const copy = JSON.parse(JSON.stringify(source));
    copy.id = makeId('container');
    copy.properties = {
      ...copy.properties,
      name: number || 'Новый контейнер',
      number,
      container_id: null,
    };
    const direction = byId('market-feature-duplicate-direction')?.value || 'right';
    copy.geometry.coordinates = adjacentContainerCoordinates(copy.geometry.coordinates, direction);

    addFeature(copy, { select: true });
    populateForm(state.items.get(state.selectedId).feature);
    byId('market-feature-number')?.focus();
    setStatus('Контейнер продублирован. Проверьте номер и положение.', 'success');
    recordHistory();
  }

  function refreshList() {
    const list = byId('market-feature-list');
    if (!list) return;
    list.innerHTML = '';
    const focus = focusedKind();
    const sorted = Array.from(state.items.values()).sort((a, b) => {
      const ak = a.feature.properties.kind || '';
      const bk = b.feature.properties.kind || '';
      const ai = KIND_ORDER.indexOf(ak);
      const bi = KIND_ORDER.indexOf(bk);
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi) ||
        String(a.feature.properties.name || '').localeCompare(String(b.feature.properties.name || ''));
    });
    KIND_ORDER.forEach((kind) => {
      if (focus && kind !== focus) return;
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
    const visibleCount = focus
      ? sorted.filter((item) => item.feature.properties.kind === focus).length
      : sorted.length;
    if (!visibleCount) {
      const empty = document.createElement('p');
      empty.className = 'help';
      empty.textContent = focus ? `В разделе «${featureKindLabel(focus)}» объектов пока нет.` : 'Объектов пока нет.';
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
      const button = section.matches('[data-map-kind]') ? section : section.querySelector('[data-map-kind]');
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
    if (kind === 'container') {
      const properties = defaultProperties(kind);
      const number = suggestedContainerNumber();
      if (number) {
        properties.name = number;
        properties.number = number;
      }
      const id = makeId(kind);
      addFeature({
        type: 'Feature',
        id,
        properties,
        geometry: { type: 'Polygon', coordinates: [containerRectangle(event.latLng)] },
      }, { select: true });
      setTool('select');
      setStatus(`${featureKindLabel(kind)} добавлен. Заполните его свойства.`, 'success');
      recordHistory();
      return;
    }
    if (family === 'point') return;
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
    recordHistory();
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
    state.contextItems.forEach((item) => visit(item.feature.geometry.coordinates));
    return count ? bounds : null;
  }

  function iterCoordinatePoints(coordinates, out = []) {
    if (Array.isArray(coordinates) && coordinates.length >= 2 && typeof coordinates[0] === 'number' && typeof coordinates[1] === 'number') {
      out.push([coordinates[0], coordinates[1]]);
      return out;
    }
    if (Array.isArray(coordinates)) coordinates.forEach((item) => iterCoordinatePoints(item, out));
    return out;
  }

  function coordinateBbox(geometry) {
    const points = iterCoordinatePoints(geometry.coordinates || []);
    if (!points.length) return null;
    const lons = points.map((point) => point[0]);
    const lats = points.map((point) => point[1]);
    return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
  }

  function orientation(a, b, c) {
    const value = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1]);
    if (Math.abs(value) < 1e-12) return 0;
    return value > 0 ? 1 : 2;
  }

  function onSegment(a, b, c) {
    return Math.min(a[0], c[0]) - 1e-12 <= b[0] && b[0] <= Math.max(a[0], c[0]) + 1e-12 &&
      Math.min(a[1], c[1]) - 1e-12 <= b[1] && b[1] <= Math.max(a[1], c[1]) + 1e-12;
  }

  function segmentsIntersect(a, b, c, d) {
    const o1 = orientation(a, b, c);
    const o2 = orientation(a, b, d);
    const o3 = orientation(c, d, a);
    const o4 = orientation(c, d, b);
    if (o1 !== o2 && o3 !== o4) return true;
    return (o1 === 0 && onSegment(a, c, b)) ||
      (o2 === 0 && onSegment(a, d, b)) ||
      (o3 === 0 && onSegment(c, a, d)) ||
      (o4 === 0 && onSegment(c, b, d));
  }

  function pointInRing(point, ring) {
    let inside = false;
    const [x, y] = point;
    for (let index = 0; index < ring.length - 1; index += 1) {
      const a = ring[index];
      const b = ring[index + 1];
      if (orientation(a, point, b) === 0 && onSegment(a, point, b)) return true;
      const intersects = (a[1] > y) !== (b[1] > y) && x < (b[0] - a[0]) * (y - a[1]) / ((b[1] - a[1]) || 1e-30) + a[0];
      if (intersects) inside = !inside;
    }
    return inside;
  }

  function pointInGeometry(point, geometry) {
    const coordinates = geometry.coordinates || [];
    const polygons = geometry.type === 'Polygon' ? [coordinates] : geometry.type === 'MultiPolygon' ? coordinates : [];
    return polygons.some((polygon) => polygon[0] && pointInRing(point, polygon[0]) && !polygon.slice(1).some((ring) => pointInRing(point, ring)));
  }

  function geometrySegments(geometry) {
    const coordinates = geometry.coordinates || [];
    const polygons = geometry.type === 'Polygon' ? [coordinates] : geometry.type === 'MultiPolygon' ? coordinates : [];
    const segments = [];
    polygons.forEach((polygon) => {
      polygon.forEach((ring) => {
        for (let index = 0; index < ring.length - 1; index += 1) {
          segments.push([ring[index], ring[index + 1]]);
        }
      });
    });
    return segments;
  }

  function geometriesIntersect(first, second) {
    const firstBox = coordinateBbox(first);
    const secondBox = coordinateBbox(second);
    if (!firstBox || !secondBox) return false;
    if (firstBox[2] < secondBox[0] || firstBox[0] > secondBox[2] || firstBox[3] < secondBox[1] || firstBox[1] > secondBox[3]) return false;
    if (iterCoordinatePoints(first.coordinates).some((point) => pointInGeometry(point, second))) return true;
    if (iterCoordinatePoints(second.coordinates).some((point) => pointInGeometry(point, first))) return true;
    const firstSegments = geometrySegments(first);
    const secondSegments = geometrySegments(second);
    return firstSegments.some(([a, b]) => secondSegments.some(([c, d]) => segmentsIntersect(a, b, c, d)));
  }

  function clientValidationMessage(snapshot) {
    const boundary = (snapshot.features || []).find((feature) => (feature.properties || {}).kind === 'bazar');
    const districts = (snapshot.features || []).filter((feature) => (feature.properties || {}).kind === 'district');
    if (!boundary) {
      return districts.length ? 'Сначала нарисуйте границу базара, потом границы районов внутри неё.' : '';
    }
    for (const district of districts) {
      const points = iterCoordinatePoints(district.geometry.coordinates || []);
      if (!points.length || points.some((point) => !pointInGeometry(point, boundary.geometry))) {
        return `Граница района «${district.properties.name || 'без названия'}» выходит за границу базара. Нарисуйте её внутри базара.`;
      }
    }
    for (let index = 0; index < districts.length; index += 1) {
      for (let next = index + 1; next < districts.length; next += 1) {
        if (geometriesIntersect(districts[index].geometry, districts[next].geometry)) {
          return `Границы районов «${districts[index].properties.name || 'без названия'}» и «${districts[next].properties.name || 'без названия'}» пересекаются.`;
        }
      }
    }
    for (const item of state.contextItems) {
      if ((item.feature.properties || {}).kind !== 'bazar') continue;
      if (geometriesIntersect(boundary.geometry, item.feature.geometry)) {
        return `Граница пересекается с базаром «${item.feature.properties.name || 'другой базар'}». Измените форму территории.`;
      }
    }
    return '';
  }

  function addContextFeature(rawFeature) {
    const feature = normalizeFeature(rawFeature);
    feature.properties.readonly = true;
    const item = { feature, overlays: buildOverlays(feature), label: null };
    item.overlays.forEach((overlay) => {
      if (overlay.setOptions) overlay.setOptions({ clickable: false, editable: false, draggable: false });
    });
    updateFeatureLabel(item);
    state.contextItems.push(item);
  }

  async function persist(url, publish = false) {
    const button = publish ? byId('market-map-publish') : byId('market-map-save');
    if (!url || !button) return;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = publish ? 'Публикуем…' : 'Сохраняем…';
    setStatus(publish ? 'Проверяем и публикуем карту…' : 'Сохраняем черновик…');
    try {
      const snapshot = collectionSnapshot();
      const clientError = clientValidationMessage(snapshot);
      if (clientError) throw new Error(clientError);
      const response = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ geojson: snapshot }),
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
      if (!state.selectedId) {
        setStatus('Сначала выберите объект, который нужно удалить', 'error');
        return;
      }
      if (window.confirm('Удалить выбранный объект?')) {
        removeFeature(state.selectedId);
        recordHistory();
      }
    });
    byId('market-map-undo')?.addEventListener('click', undoHistory);
    byId('market-map-redo')?.addEventListener('click', redoHistory);
    byId('market-feature-duplicate')?.addEventListener('click', duplicateSelectedFeature);
    byId('market-feature-container')?.addEventListener('change', (event) => {
      const option = event.target.selectedOptions[0];
      if (!option?.value) return;
      byId('market-feature-passage').value = option.dataset.passageId || '';
      byId('market-feature-name').value = option.dataset.number || byId('market-feature-name').value;
      byId('market-feature-number').value = option.dataset.number || byId('market-feature-number').value;
    });
    byId('market-feature-number')?.addEventListener('input', (event) => {
      const item = state.items.get(state.selectedId);
      if (!item || (item.feature.properties || {}).kind !== 'container') return;
      byId('market-feature-name').value = event.target.value;
    });
    byId('market-map-save')?.addEventListener('click', () => persist(root().dataset.saveUrl, false));
    byId('market-map-publish')?.addEventListener('click', () => {
      if (window.confirm('Опубликовать эту версию карты для мобильного приложения?')) {
        persist(root().dataset.publishUrl, true);
      }
    });
    document.addEventListener('keydown', (event) => {
      const editingText = ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName);
      const command = event.ctrlKey || event.metaKey;
      if (command && !editingText && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        if (event.shiftKey) redoHistory();
        else undoHistory();
        return;
      }
      if (command && !editingText && event.key.toLowerCase() === 'y') {
        event.preventDefault();
        redoHistory();
        return;
      }
      if (event.key === 'Escape') setTool('select');
      if ((event.key === 'Delete' || event.key === 'Backspace') && state.selectedId && !editingText) {
        removeFeature(state.selectedId);
        recordHistory();
      }
    });
  }

  function focusedKind() {
    const kind = root()?.dataset.focusKind || '';
    return KIND_CONFIG[kind] ? kind : '';
  }

  function applyFocusedSection() {
    const kind = focusedKind();
    if (!kind) return;

    document.querySelectorAll('[data-section-kind]').forEach((link) => {
      link.classList.toggle('active', link.dataset.sectionKind === kind);
    });
    document.querySelectorAll('.market-kind-section').forEach((section) => {
      const button = section.matches('[data-map-kind]') ? section : section.querySelector('[data-map-kind]');
      section.hidden = button?.dataset.mapKind !== kind;
    });
  }

  window.initMarketMapEditor = function initMarketMapEditor() {
    const canvas = byId('market-map-canvas');
    if (!canvas || !window.google?.maps) return;
    const initial = readJsonScript('market-map-initial-geojson', { type: 'FeatureCollection', features: [] });
    const context = readJsonScript('market-map-context-geojson', { type: 'FeatureCollection', features: [] });
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
    applyFocusedSection();
    (context.features || []).forEach((feature) => addContextFeature(feature));
    (initial.features || []).forEach((feature) => addFeature(feature));
    recordHistory(true);
    const bounds = allBounds();
    if (bounds) state.map.fitBounds(bounds, 48);
    refreshList();
    const kind = focusedKind();
    if (kind) {
      setTool('draw', kind);
      const help = byId('market-map-mode-help');
      if (help) {
        help.textContent = kind === 'bazar'
          ? 'Нарисуйте границу выбранного базара. Серые области — другие опубликованные базары, пересекаться с ними нельзя.'
          : kind === 'district'
            ? 'Нарисуйте границу района внутри выбранного базара так же, как рисуется граница базара.'
            : kind === 'passage'
              ? 'Нарисуйте проход внутри выбранного базара. Граница базара и районы остаются видимыми для ориентира.'
              : 'Рисуйте контейнеры прямоугольниками. Граница базара, районы и проходы остаются видимыми для ориентира.';
      }
    } else {
      setStatus('Карта готова. Изменения пока находятся в черновике.', 'success');
    }
  };
})();
