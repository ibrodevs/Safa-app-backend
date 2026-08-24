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
    lastContainerRotation: 0,
    groupSelection: new Set(),
    groupDrag: null,
  };

  const GROUP_HIGHLIGHT_COLOR = '#7c3aed';

  const byId = (id) => document.getElementById(id);
  const root = () => byId('market-map-editor');
  // Порядок слоёв и списка объектов: контейнеры сверху, под ними проходы,
  // районы и граница базара. Так мелкий объект всегда выбирается первым и
  // крупные заливки не перехватывают клик.
  const KIND_ORDER = ['container', 'passage', 'district', 'bazar', 'sector', 'row'];

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
      hint: 'Проведите линию прохода. Двойной клик завершает линию.',
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

  // Номера проходов уникальны внутри района: «1 проход» может быть в каждом
  // районе базара, поэтому проход всегда подписывается вместе со своим районом.
  function districtNameForFeature(feature) {
    const points = iterCoordinatePoints(feature?.geometry?.coordinates || []);
    if (!points.length) return '';
    let bestName = '';
    let bestScore = 0;
    state.items.forEach((item) => {
      const properties = item.feature.properties || {};
      if (properties.kind !== 'district') return;
      const name = String(properties.name || '').trim();
      if (!name) return;
      const score = points.filter((point) => pointInGeometry(point, item.feature.geometry)).length;
      if (score > bestScore) {
        bestScore = score;
        bestName = name;
      }
    });
    return bestName;
  }

  function passageOptionLabel(number, district) {
    return district ? `${number} · ${district}` : String(number);
  }

  function syncPassageOptions(preferredValue = null) {
    const select = byId('market-feature-passage');
    if (!select) return;
    const selected = preferredValue === null ? select.value : String(preferredValue || '');
    const databasePassages = readJsonScript('market-map-passages', []);
    const options = new Map();
    databasePassages.forEach((passage) => {
      options.set(String(passage.id), passageOptionLabel(passage.number, passage.district));
    });
    state.items.forEach((item) => {
      const properties = item.feature.properties || {};
      if (properties.kind !== 'passage') return;
      const name = String(properties.number || properties.name || 'Новый проход').trim();
      const district = districtNameForFeature(item.feature);
      const matchingDatabasePassage = databasePassages.find(
        (passage) => String(passage.number) === name && String(passage.district || '') === district,
      );
      const value = properties.passage_id
        ? String(properties.passage_id)
        : matchingDatabasePassage
          ? String(matchingDatabasePassage.id)
          : `feature:${item.feature.id}`;
      const label = passageOptionLabel(name, district);
      options.set(value, properties.passage_id || matchingDatabasePassage ? label : `${label} · черновик`);
    });
    select.replaceChildren(new Option('Выберите проход', ''));
    options.forEach((label, value) => select.add(new Option(label, value)));
    select.value = options.has(selected) ? selected : '';
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

  const CONTAINER_MIN_SIZE_M = 0.2;
  const CONTAINER_MAX_SIZE_M = 100;
  const CONTAINER_DEFAULT_WIDTH_M = 4;
  const CONTAINER_DEFAULT_HEIGHT_M = 2.5;
  const METERS_PER_LAT_DEGREE = 111320;
  // Углы контейнера по часовой стрелке от левого верхнего: знаки по осям
  // ширины и длины. Порядок совпадает с прежними прямоугольниками карты.
  const CONTAINER_CORNER_SIGNS = [[-1, -1], [1, -1], [1, 1], [-1, 1]];

  function normalizeRotation(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return ((number % 360) + 360) % 360;
  }

  function clampContainerSize(meters) {
    const number = Number(meters);
    if (!Number.isFinite(number)) return CONTAINER_MIN_SIZE_M;
    return Math.max(CONTAINER_MIN_SIZE_M, Math.min(CONTAINER_MAX_SIZE_M, number));
  }

  function safeContainerSize(meters) {
    const number = Number(meters);
    if (!Number.isFinite(number)) return CONTAINER_MIN_SIZE_M;
    return Math.max(CONTAINER_MIN_SIZE_M, number);
  }

  function lngMetersPerDegree(lat) {
    return METERS_PER_LAT_DEGREE * Math.max(0.2, Math.cos((Number(lat) || 0) * Math.PI / 180));
  }

  // Локальные метры с началом в центре контейнера: x — на восток, y — на север.
  // В этой системе поворот считается обычной тригонометрией, без искажений долготы.
  function toLocalMeters(point, center) {
    return [
      (Number(point[0]) - center[0]) * lngMetersPerDegree(center[1]),
      (Number(point[1]) - center[1]) * METERS_PER_LAT_DEGREE,
    ];
  }

  function fromLocalMeters(point, center) {
    return [
      center[0] + point[0] / lngMetersPerDegree(center[1]),
      center[1] + point[1] / METERS_PER_LAT_DEGREE,
    ];
  }

  // rotation — поворот контейнера по часовой стрелке в градусах.
  // 0° — ширина смотрит строго на восток, длина строго на юг.
  function containerAxes(rotation) {
    const radians = normalizeRotation(rotation) * Math.PI / 180;
    const cos = Math.cos(radians);
    const sin = Math.sin(radians);
    return { width: [cos, -sin], height: [-sin, -cos] };
  }

  function ringFromContainerRect(rect) {
    const axes = containerAxes(rect.rotation);
    const halfWidth = safeContainerSize(rect.width) / 2;
    const halfHeight = safeContainerSize(rect.height) / 2;
    const ring = CONTAINER_CORNER_SIGNS.map(([signWidth, signHeight]) => fromLocalMeters([
      signWidth * halfWidth * axes.width[0] + signHeight * halfHeight * axes.height[0],
      signWidth * halfWidth * axes.width[1] + signHeight * halfHeight * axes.height[1],
    ], rect.center));
    return [...ring, [...ring[0]]];
  }

  function containerBboxRect(points) {
    const bounds = rectangleBounds(points);
    const center = [(bounds.left + bounds.right) / 2, (bounds.top + bounds.bottom) / 2];
    return {
      center,
      width: (bounds.right - bounds.left) * lngMetersPerDegree(center[1]),
      height: (bounds.top - bounds.bottom) * METERS_PER_LAT_DEGREE,
      rotation: 0,
    };
  }

  // Контейнер всегда остаётся прямоугольником, поэтому его достаточно описать
  // центром, шириной, длиной и углом поворота. Кольцо неправильной формы
  // (старые данные, ручная правка) сводится к описанной рамке без поворота.
  // Наклон прохода в той же системе координат, что и поворот контейнера:
  // 0° — линия на восток, отсчёт по часовой стрелке. Направление рисования не
  // важно, поэтому угол сводится к диапазону 0–180°.
  function passageAngleDegrees(feature) {
    const points = iterCoordinatePoints(feature?.geometry?.coordinates || []);
    if (points.length < 2) return null;

    const center = points[0];
    let longest = null;
    let longestLength = 0;
    for (let index = 0; index < points.length - 1; index += 1) {
      const from = toLocalMeters(points[index], center);
      const to = toLocalMeters(points[index + 1], center);
      const vector = [to[0] - from[0], to[1] - from[1]];
      const length = Math.hypot(vector[0], vector[1]);
      if (length > longestLength) {
        longestLength = length;
        longest = vector;
      }
    }
    if (!longest || longestLength < 1e-6) return null;

    const angle = normalizeRotation(Math.atan2(-longest[1], longest[0]) * 180 / Math.PI);
    return Math.round((angle % 180) * 10) / 10;
  }

  function containerRectFromRing(ring) {
    const points = (ring || [])
      .filter((point) => Array.isArray(point) && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])))
      .map((point) => [Number(point[0]), Number(point[1])]);
    if (!points.length) return null;

    const closed = points.length === 5
      && points[0][0] === points[4][0]
      && points[0][1] === points[4][1];
    if (points.length !== 4 && !closed) return containerBboxRect(points);

    const corners = points.slice(0, 4);
    const center = [
      corners.reduce((sum, point) => sum + point[0], 0) / corners.length,
      corners.reduce((sum, point) => sum + point[1], 0) / corners.length,
    ];
    const local = corners.map((point) => toLocalMeters(point, center));
    const widthVector = [local[1][0] - local[0][0], local[1][1] - local[0][1]];
    const heightVector = [local[2][0] - local[1][0], local[2][1] - local[1][1]];
    const width = Math.hypot(widthVector[0], widthVector[1]);
    const height = Math.hypot(heightVector[0], heightVector[1]);
    const dot = widthVector[0] * heightVector[0] + widthVector[1] * heightVector[1];
    if (width < 1e-6 || height < 1e-6 || Math.abs(dot) > 0.02 * width * height) {
      return containerBboxRect(points);
    }

    return {
      center,
      width,
      height,
      rotation: normalizeRotation(Math.atan2(-widthVector[1], widthVector[0]) * 180 / Math.PI),
    };
  }

  function containerRect(coordinates) {
    return containerRectFromRing((coordinates || [[]])[0]);
  }

  function containerRectangle(latLng, rotation = 0) {
    return ringFromContainerRect({
      center: [latLng.lng(), latLng.lat()],
      width: CONTAINER_DEFAULT_WIDTH_M,
      height: CONTAINER_DEFAULT_HEIGHT_M,
      rotation,
    });
  }

  // Цвет контейнеров задаётся сразу для всех, поэтому новый контейнер берёт
  // цвет уже стоящих на карте, а не заводской красный.
  function currentContainerColors() {
    let colors = null;
    state.items.forEach((item) => {
      const properties = item.feature.properties || {};
      if (colors || properties.kind !== 'container') return;
      if (properties.fill_color || properties.stroke_color) {
        colors = {
          fill_color: properties.fill_color || KIND_CONFIG.container.fillColor,
          stroke_color: properties.stroke_color || KIND_CONFIG.container.strokeColor,
        };
      }
    });
    return colors;
  }

  function defaultProperties(kind) {
    const config = KIND_CONFIG[kind] || KIND_CONFIG.district;
    const name = typeof config.name === 'function' ? config.name() : config.name;
    const inherited = kind === 'container' ? currentContainerColors() : null;
    return {
      kind,
      name,
      bazar_id: Number(root()?.dataset.bazarId || 0),
      min_zoom: config.minZoom,
      stroke_width: config.strokeWidth,
      stroke_color: inherited?.stroke_color || config.strokeColor,
      fill_color: inherited?.fill_color || config.fillColor,
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

  function resizeContainerCoordinates(coordinates, widthM, heightM, rotationDeg = null) {
    const rect = containerRect(coordinates);
    if (!rect) return coordinates;
    return [ringFromContainerRect({
      center: rect.center,
      width: clampContainerSize(widthM),
      height: clampContainerSize(heightM),
      rotation: rotationDeg === null ? rect.rotation : normalizeRotation(rotationDeg),
    })];
  }

  function setPolygonCoordinates(overlay, coordinates) {
    overlay.setPaths(coordinates.map((ring) => ring.slice(0, -1).map((point) => ({ lat: Number(point[1]), lng: Number(point[0]) }))));
  }

  function syncContainerSizeFields(coordinates) {
    const rect = containerRect(coordinates);
    if (!rect) return;
    byId('market-feature-width-m').value = Math.max(0.2, Math.round(rect.width * 10) / 10);
    byId('market-feature-height-m').value = Math.max(0.2, Math.round(rect.height * 10) / 10);
    const rotationField = byId('market-feature-rotation-deg');
    if (rotationField) rotationField.value = Math.round(normalizeRotation(rect.rotation) * 10) / 10;
  }

  function normalizeContainerItem(item) {
    if (!item || (item.feature.properties || {}).kind !== 'container') return;
    const snapshot = serializeItem(item);
    item.feature.geometry.coordinates = snapshot.geometry.coordinates;
    item.feature.properties.rotation = snapshot.properties.rotation
      ?? item.feature.properties.rotation
      ?? 0;
    item.overlays.forEach((overlay) => {
      if (!(overlay instanceof google.maps.Marker)) {
        setPolygonCoordinates(overlay, item.feature.geometry.coordinates);
        overlay.setOptions(overlayStyle(item.feature.properties, true));
      }
    });
    syncContainerSizeFields(item.feature.geometry.coordinates);
    updateFeatureLabel(item);
    syncContainerResizeHandles(item);
  }

  function featureZIndex(properties, selected = false) {
    const kind = properties.kind || 'district';
    const config = KIND_CONFIG[kind] || KIND_CONFIG.district;
    // Слой задаётся типом объекта, а не сохранённым z_index: иначе старая карта
    // может положить район поверх контейнеров и перехватывать клики.
    return Number(config.zIndex || 1) + (selected ? 1 : 0);
  }

  function overlayStyle(properties, selected) {
    const kind = properties.kind || 'district';
    const config = KIND_CONFIG[kind] || KIND_CONFIG.district;
    const strokeWidth = Number(properties.stroke_width || config.strokeWidth || 2) + (selected ? 1 : 0);
    const linePattern = properties.line_pattern || config.linePattern || 'solid';
    let icons = null;
    if (linePattern === 'dashed') {
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
      // Containers use four larger resize handles below. Native polygon
      // vertices are too small and unreliable to drag on touch screens.
      editable: selected && kind !== 'container',
      draggable: selected,
      // Keep the semantic layer order while selected. Raising a district to
      // 1000 made its fill intercept clicks intended for nested objects.
      zIndex: featureZIndex(properties, selected),
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

  function stopMapClickPropagation(event) {
    if (event?.domEvent?.stopPropagation) event.domEvent.stopPropagation();
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

  const BLANK_LABEL_ICON = {
    path: 'M 0,0',
    scale: 0,
    fillOpacity: 0,
    strokeOpacity: 0,
  };

  function escapeXml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Подпись прохода поворачивается вместе с ним: вертикальный проход — текст
  // вертикально, горизонтальный — горизонтально. Метка Google Maps поворот не
  // поддерживает, поэтому текст рисуется SVG-иконкой маркера.
  function passageLabelIcon(text, angle, color) {
    const fontSize = 13;
    // Угол прохода 0–180° отсчитывается по часовой от востока — как раз система
    // координат SVG. Наклон больше 90° разворачиваем, чтобы текст не читался
    // вверх ногами.
    const textAngle = angle > 90 ? angle - 180 : angle;
    const width = Math.max(String(text).length * fontSize * 0.66 + 12, 26);
    const size = Math.ceil(Math.hypot(width, fontSize + 12));
    const middle = size / 2;
    const svg = [
      `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">`,
      `<g transform="rotate(${textAngle.toFixed(1)} ${middle} ${middle})">`,
      `<text x="${middle}" y="${middle}" text-anchor="middle" dominant-baseline="central"`,
      ` font-family="Inter, Segoe UI, Arial, sans-serif" font-size="${fontSize}" font-weight="800"`,
      ` fill="${escapeXml(color)}" stroke="#ffffff" stroke-width="3" paint-order="stroke">`,
      escapeXml(text),
      '</text></g></svg>',
    ].join('');

    return {
      url: `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`,
      anchor: new google.maps.Point(middle, middle),
      scaledSize: new google.maps.Size(size, size),
    };
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
    if (!item.label) return;
    item.label.setPosition(position);
    const selected = state.selectedId === item.feature.id;
    item.label.setZIndex(featureZIndex(item.feature.properties, selected) + 1);
    const color = kind === 'container' ? '#111827' : (item.feature.properties.stroke_color || '#111827');

    if (kind === 'passage') {
      item.label.setLabel(null);
      item.label.setIcon(passageLabelIcon(text, passageAngleDegrees(item.feature) ?? 0, color));
      return;
    }

    item.label.setIcon(BLANK_LABEL_ICON);
    item.label.setLabel({
      text,
      color,
      fontSize: kind === 'container' ? '12px' : '13px',
      fontWeight: '800',
    });
  }

  function clearContainerResizeHandles(item) {
    (item.resizeHandles || []).forEach((handle) => handle.setMap(null));
    item.resizeHandles = [];
    if (item.rotationHandle) {
      item.rotationHandle.setMap(null);
      item.rotationHandle = null;
    }
  }

  // Угол тянут за противоположный: он остаётся на месте, а стороны меряются
  // вдоль собственных осей контейнера, поэтому поворот при изменении размера
  // не теряется.
  function containerCoordinatesFromCorner(item, cornerIndex, position) {
    const rect = containerRect(item.feature.geometry.coordinates);
    if (!rect) return item.feature.geometry.coordinates;
    const axes = containerAxes(rect.rotation);
    const [signWidth, signHeight] = CONTAINER_CORNER_SIGNS[cornerIndex % 4];
    const anchorPoint = ringFromContainerRect(rect)[(cornerIndex + 2) % 4];
    const anchor = toLocalMeters(anchorPoint, rect.center);
    const pointer = toLocalMeters([position.lng(), position.lat()], rect.center);
    const delta = [pointer[0] - anchor[0], pointer[1] - anchor[1]];
    const width = clampContainerSize(
      (delta[0] * axes.width[0] + delta[1] * axes.width[1]) * signWidth,
    );
    const height = clampContainerSize(
      (delta[0] * axes.height[0] + delta[1] * axes.height[1]) * signHeight,
    );
    const center = fromLocalMeters([
      anchor[0] + signWidth * (width / 2) * axes.width[0] + signHeight * (height / 2) * axes.height[0],
      anchor[1] + signWidth * (width / 2) * axes.width[1] + signHeight * (height / 2) * axes.height[1],
    ], rect.center);
    return [ringFromContainerRect({ center, width, height, rotation: rect.rotation })];
  }

  function containerRotationHandlePosition(rect) {
    const axes = containerAxes(rect.rotation);
    const distance = safeContainerSize(rect.height) / 2 + Math.max(1.5, safeContainerSize(rect.height) / 2);
    return fromLocalMeters([-axes.height[0] * distance, -axes.height[1] * distance], rect.center);
  }

  function syncContainerResizeHandles(item, activeIndex = -1, { skipRotationHandle = false } = {}) {
    if (!item?.resizeHandles?.length && !item?.rotationHandle) return;
    const rect = containerRect(item.feature.geometry.coordinates);
    if (!rect) return;
    const ring = ringFromContainerRect(rect);
    (item.resizeHandles || []).forEach((handle, index) => {
      if (index === activeIndex) return;
      handle.setPosition({ lat: ring[index][1], lng: ring[index][0] });
    });
    if (item.rotationHandle && !skipRotationHandle) {
      const position = containerRotationHandlePosition(rect);
      item.rotationHandle.setPosition({ lat: position[1], lng: position[0] });
    }
  }

  function showContainerResizeHandles(item) {
    clearContainerResizeHandles(item);
    if (
      (item.feature.properties || {}).kind !== 'container'
      || item.feature.geometry.type !== 'Polygon'
    ) return;
    const rect = containerRect(item.feature.geometry.coordinates);
    if (!rect) return;
    const ring = ringFromContainerRect(rect);
    item.resizeHandles = ring.slice(0, 4).map((point, cornerIndex) => {
      const handle = new google.maps.Marker({
        map: state.map,
        position: { lat: point[1], lng: point[0] },
        draggable: true,
        clickable: true,
        cursor: 'nwse-resize',
        title: 'Потяните, чтобы изменить размер контейнера',
        zIndex: featureZIndex(item.feature.properties, true) + 2,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          fillColor: '#ffffff',
          fillOpacity: 1,
          strokeColor: item.feature.properties.stroke_color || '#dc2626',
          strokeWeight: 3,
          scale: 7,
        },
      });
      handle.addListener('click', stopMapClickPropagation);
      handle.addListener('drag', () => {
        item.feature.geometry.coordinates = containerCoordinatesFromCorner(
          item,
          cornerIndex,
          handle.getPosition(),
        );
        item.overlays.forEach((overlay) => {
          if (!(overlay instanceof google.maps.Marker)) {
            setPolygonCoordinates(overlay, item.feature.geometry.coordinates);
          }
        });
        syncContainerSizeFields(item.feature.geometry.coordinates);
        syncContainerResizeHandles(item, cornerIndex);
        updateFeatureLabel(item);
      });
      handle.addListener('dragend', () => {
        syncContainerResizeHandles(item);
        root()?.dispatchEvent(new CustomEvent('market-map:dirty'));
        setStatus('Размер контейнера изменён. Сохраните карту.', 'success');
        recordHistory();
      });
      return handle;
    });
    showContainerRotationHandle(item);
  }

  function showContainerRotationHandle(item) {
    const rect = containerRect(item.feature.geometry.coordinates);
    if (!rect) return;
    const position = containerRotationHandlePosition(rect);
    const handle = new google.maps.Marker({
      map: state.map,
      position: { lat: position[1], lng: position[0] },
      draggable: true,
      clickable: true,
      cursor: 'grab',
      title: 'Потяните, чтобы повернуть контейнер. Shift — шаг 15°',
      zIndex: featureZIndex(item.feature.properties, true) + 3,
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        fillColor: '#ffffff',
        fillOpacity: 1,
        strokeColor: item.feature.properties.stroke_color || '#dc2626',
        strokeWeight: 3,
        scale: 9,
      },
      label: {
        text: '↻',
        color: '#111827',
        fontSize: '13px',
        fontWeight: '900',
      },
    });
    handle.addListener('click', stopMapClickPropagation);
    handle.addListener('drag', (event) => {
      const current = containerRect(item.feature.geometry.coordinates);
      const dragged = handle.getPosition();
      if (!current || !dragged) return;
      const local = toLocalMeters([dragged.lng(), dragged.lat()], current.center);
      if (Math.hypot(local[0], local[1]) < 1e-6) return;
      let angle = normalizeRotation(Math.atan2(local[0], local[1]) * 180 / Math.PI);
      if (event?.domEvent?.shiftKey) angle = normalizeRotation(Math.round(angle / 15) * 15);
      setContainerRotation(item, angle, { record: false, skipRotationHandle: true });
    });
    handle.addListener('dragend', () => {
      syncContainerResizeHandles(item);
      setStatus('Контейнер повёрнут. Сохраните карту.', 'success');
      recordHistory();
    });
    item.rotationHandle = handle;
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
      stopMapClickPropagation(event);
      if (state.tool === 'draw') {
        mapClick(event);
        return;
      }
      handleFeatureClick(feature.id, event);
    });
    marker.addListener('dragstart', () => beginGroupDrag(feature.id));
    marker.addListener('dragend', () => {
      const item = state.items.get(feature.id);
      if (item) {
        const position = item.overlays[0].getPosition();
        item.feature.geometry.coordinates = [position.lng(), position.lat()];
      }
      finishGroupDrag(feature.id);
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
      stopMapClickPropagation(event);
      if (state.tool === 'draw') {
        mapClick(event);
        return;
      }
      handleFeatureClick(feature.id, event);
    });
    line.addListener('mouseup', () => {
      const item = state.items.get(feature.id);
      if (item) updateFeatureLabel(item);
      document.getElementById('market-map-editor')?.dispatchEvent(new CustomEvent('market-map:dirty'));
      recordHistory();
    });
    line.addListener('dragstart', () => beginGroupDrag(feature.id));
    line.addListener('dragend', () => {
      const item = state.items.get(feature.id);
      if (item) {
        item.feature.geometry.coordinates = pathToCoordinates(item.overlays[0].getPath());
        updateFeatureLabel(item);
      }
      finishGroupDrag(feature.id);
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
      stopMapClickPropagation(event);
      if ((feature.properties || {}).readonly) return;
      if (state.tool === 'draw') {
        mapClick(event);
        return;
      }
      handleFeatureClick(feature.id, event);
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
    polygon.addListener('dragstart', () => beginGroupDrag(feature.id));
    polygon.addListener('dragend', () => {
      const item = state.items.get(feature.id);
      if (item) {
        normalizeContainerItem(item);
        updateFeatureLabel(item);
      }
      finishGroupDrag(feature.id);
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
    const item = {
      feature,
      overlays: buildOverlays(feature),
      label: null,
      resizeHandles: [],
      rotationHandle: null,
    };
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
        const rect = containerRect(feature.geometry.coordinates);
        if (rect) {
          feature.geometry.coordinates = [ringFromContainerRect(rect)];
          feature.properties.rotation = Math.round(normalizeRotation(rect.rotation) * 100) / 100;
        }
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
      clearContainerResizeHandles(item);
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
        overlay.setZIndex(featureZIndex(item.feature.properties, selected));
        overlay.setAnimation(selected ? google.maps.Animation.BOUNCE : null);
        if (selected) window.setTimeout(() => overlay.setAnimation(null), 500);
      } else {
        overlay.setOptions(overlayStyle(item.feature.properties, selected));
      }
    });
    if (item.label) {
      item.label.setZIndex(featureZIndex(item.feature.properties, selected) + 1);
    }
    if (selected) showContainerResizeHandles(item);
    else clearContainerResizeHandles(item);
  }

  function featureGroupId(feature) {
    return String((feature?.properties || {}).group || '').trim();
  }

  function groupMemberIds(groupId) {
    const ids = [];
    if (!groupId) return ids;
    state.items.forEach((item) => {
      if (featureGroupId(item.feature) === groupId) ids.push(item.feature.id);
    });
    return ids;
  }

  const CLICK_TOLERANCE_METERS = 3;

  function pointSegmentDistanceMeters(point, start, end) {
    const scale = lngMetersPerDegree(point[1]);
    const toLocal = (item) => [(item[0] - point[0]) * scale, (item[1] - point[1]) * METERS_PER_LAT_DEGREE];
    const a = toLocal(start);
    const b = toLocal(end);
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const lengthSquared = dx * dx + dy * dy;
    if (lengthSquared < 1e-9) return Math.hypot(a[0], a[1]);
    let t = -(a[0] * dx + a[1] * dy) / lengthSquared;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(a[0] + dx * t, a[1] + dy * t);
  }

  function geometryHitsPoint(geometry, point, tolerance) {
    const type = geometry?.type;
    if (!type) return false;
    if (type === 'Polygon' || type === 'MultiPolygon') {
      if (pointInGeometry(point, geometry)) return true;
      // Контейнеры крошечные: даём небольшой допуск вокруг фигуры, иначе на
      // мелком масштабе клик всё время промахивается мимо них.
      const points = iterCoordinatePoints(geometry.coordinates || []);
      return points.some((item) => pointSegmentDistanceMeters(point, item, item) <= tolerance);
    }
    if (type === 'Point') {
      return pointSegmentDistanceMeters(point, geometry.coordinates, geometry.coordinates) <= tolerance;
    }
    const points = iterCoordinatePoints(geometry.coordinates || []);
    for (let index = 0; index < points.length - 1; index += 1) {
      if (pointSegmentDistanceMeters(point, points[index], points[index + 1]) <= tolerance) return true;
    }
    return points.length === 1 && pointSegmentDistanceMeters(point, points[0], points[0]) <= tolerance;
  }

  // Клик по большой заливке района или базара перехватывает контейнер, который
  // лежит под курсором, поэтому объект под точкой ищем сами и берём верхний
  // слой: контейнер важнее прохода, проход важнее района.
  function featureAtLatLng(latLng) {
    if (!latLng) return null;
    const point = [latLng.lng(), latLng.lat()];
    let bestId = null;
    let bestRank = Number.MAX_SAFE_INTEGER;
    // Сначала дешёвая отсечка по рамке сохранённой геометрии, и только для
    // кандидатов берём актуальные координаты с карты.
    const marginLat = 25 / METERS_PER_LAT_DEGREE;
    const marginLon = 25 / lngMetersPerDegree(point[1]);
    state.items.forEach((item) => {
      const properties = item.feature.properties || {};
      if (properties.readonly) return;
      const rank = KIND_ORDER.indexOf(properties.kind);
      if (rank === -1 || rank >= bestRank) return;

      const box = coordinateBbox(item.feature.geometry || {});
      if (!box) return;
      if (point[0] < box[0] - marginLon || point[0] > box[2] + marginLon) return;
      if (point[1] < box[1] - marginLat || point[1] > box[3] + marginLat) return;

      if (geometryHitsPoint(serializeItem(item).geometry, point, CLICK_TOLERANCE_METERS)) {
        bestId = item.feature.id;
        bestRank = rank;
      }
    });
    return bestId;
  }

  // Клик выбирает объект, Ctrl/Shift+клик набирает группу из нескольких объектов.
  function handleFeatureClick(id, event) {
    const domEvent = event?.domEvent;
    if (domEvent && (domEvent.ctrlKey || domEvent.metaKey || domEvent.shiftKey)) {
      toggleGroupSelection(featureAtLatLng(event?.latLng) || id);
      return;
    }
    selectFeature(featureAtLatLng(event?.latLng) || id);
  }

  function setOverlayHighlighted(item, highlighted) {
    item.overlays.forEach((overlay) => {
      if (overlay instanceof google.maps.Marker) {
        overlay.setIcon(markerIcon(item.feature.properties, highlighted));
        return;
      }
      overlay.setOptions({
        ...overlayStyle(item.feature.properties, false),
        editable: false,
        draggable: false,
        strokeColor: highlighted
          ? GROUP_HIGHLIGHT_COLOR
          : (item.feature.properties.stroke_color || overlayStyle(item.feature.properties, false).strokeColor),
        strokeWeight: Number(item.feature.properties.stroke_width || 2) + (highlighted ? 2 : 0),
      });
    });
  }

  function refreshGroupHighlight() {
    state.items.forEach((item) => {
      if (item.feature.id === state.selectedId) return;
      setOverlayHighlighted(item, state.groupSelection.has(item.feature.id));
    });
    updateGroupPanel();
    refreshList();
  }

  function toggleGroupSelection(id) {
    if (!state.items.has(id)) return;
    if (state.groupSelection.has(id)) state.groupSelection.delete(id);
    else state.groupSelection.add(id);
    refreshGroupHighlight();
  }

  function clearGroupSelection() {
    if (!state.groupSelection.size) return;
    state.groupSelection.clear();
    refreshGroupHighlight();
  }

  // Что считается «текущей группой»: набранное Ctrl+кликом выделение, а если
  // его нет — выбранный объект. Любой участник тянет за собой всю свою группу.
  function currentGroupTargets() {
    const seeds = state.groupSelection.size
      ? Array.from(state.groupSelection)
      : (state.selectedId ? [state.selectedId] : []);
    const ids = new Set();
    seeds.forEach((id) => {
      const item = state.items.get(id);
      if (!item) return;
      ids.add(id);
      groupMemberIds(featureGroupId(item.feature)).forEach((memberId) => ids.add(memberId));
    });
    return ids;
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
    if (state.groupSelection.size && !state.groupSelection.has(state.selectedId)) {
      state.groupSelection.clear();
      state.items.forEach((other) => {
        if (other.feature.id !== state.selectedId) setOverlayHighlighted(other, false);
      });
    }
    updateGroupPanel();
    if ((item.feature.properties || {}).kind === 'container') {
      setStatus('Углы меняют размер, круглый маркер ↻ сверху поворачивает контейнер.', 'success');
    }
    refreshList();
  }

  function removeFeature(id) {
    state.groupSelection.delete(id);
    const item = state.items.get(id);
    if (!item) return;
    item.overlays.forEach((overlay) => overlay.setMap(null));
    if (item.label) item.label.setMap(null);
    clearContainerResizeHandles(item);
    state.items.delete(id);
    if (state.selectedId === id) state.selectedId = null;
    refreshList();
  }

  function populateForm(feature) {
    const properties = feature.properties || {};
    const serialized = state.items.has(feature.id) ? serializeItem(state.items.get(feature.id)) : feature;
    const rect = properties.kind === 'container' && serialized.geometry.type === 'Polygon'
      ? containerRect(serialized.geometry.coordinates)
      : null;
    byId('market-feature-kind').value = properties.kind || 'district';
    byId('market-feature-name').value = properties.name || '';
    byId('market-feature-number').value = properties.number || '';
    const passageValue = properties.passage_feature_id
      ? `feature:${properties.passage_feature_id}`
      : properties.passage_id ? String(properties.passage_id) : '';
    syncPassageOptions(passageValue);
    byId('market-feature-container').value = properties.container_id ? String(properties.container_id) : '';
    byId('market-feature-title').value = properties.title || '';
    byId('market-feature-min-zoom').value = Number(properties.min_zoom ?? 14);
    byId('market-feature-stroke-width').value = Number(properties.stroke_width ?? 2);
    byId('market-feature-stroke').value = String(properties.stroke_color || '#e47f26').slice(0, 7);
    byId('market-feature-fill').value = String(properties.fill_color || '#ff8656').slice(0, 7);
    updateDistrictNote(properties.kind, serialized);
    if (rect) {
      byId('market-feature-width-m').value = Math.max(0.2, Math.round(rect.width * 10) / 10);
      byId('market-feature-height-m').value = Math.max(0.2, Math.round(rect.height * 10) / 10);
      const rotationField = byId('market-feature-rotation-deg');
      if (rotationField) rotationField.value = Math.round(normalizeRotation(rect.rotation) * 10) / 10;
    }
    updatePropertyVisibility(properties.kind || 'district');
  }

  function updateDistrictNote(kind, feature) {
    const note = byId('market-feature-district-note');
    if (!note) return;
    if (kind !== 'passage') {
      note.textContent = '';
      return;
    }
    const district = districtNameForFeature(feature);
    const angle = passageAngleDegrees(feature);
    const parts = [
      district
        ? `Район: ${district}. Номер прохода уникален внутри района — в других районах этот же номер можно использовать снова.`
        : 'Проход не попал ни в один район базара. Номер должен быть уникален среди проходов вне районов.',
    ];
    if (angle !== null) {
      parts.push(`Угол наклона: ${angle}°. Тот же угол можно задать контейнерам этого прохода кнопкой «По проходу».`);
    }
    note.textContent = parts.join(' ');
  }

  function updatePropertyVisibility(kind) {
    const isContainer = kind === 'container';
    document.querySelectorAll('[data-kind-scope="passage"]').forEach((row) => {
      row.hidden = kind !== 'passage';
    });
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
      const widthM = Math.max(0.2, Number(byId('market-feature-width-m').value || CONTAINER_DEFAULT_WIDTH_M));
      const heightM = Math.max(0.2, Number(byId('market-feature-height-m').value || CONTAINER_DEFAULT_HEIGHT_M));
      const rotationField = byId('market-feature-rotation-deg');
      const rotation = rotationField
        ? normalizeRotation(rotationField.value)
        : normalizeRotation(properties.rotation);
      serialized.geometry.coordinates = resizeContainerCoordinates(
        serialized.geometry.coordinates,
        widthM,
        heightM,
        rotation,
      );
      item.feature.geometry.coordinates = serialized.geometry.coordinates;
      properties.rotation = Math.round(rotation * 100) / 100;
      state.lastContainerRotation = rotation;
      const passageValue = byId('market-feature-passage').value;
      if (passageValue.startsWith('feature:')) {
        properties.passage_id = null;
        properties.passage_feature_id = passageValue.slice('feature:'.length);
        properties.passage_name = state.items.get(properties.passage_feature_id)?.feature.properties.name || '';
      } else {
        properties.passage_id = Number(passageValue || 0) || null;
        delete properties.passage_feature_id;
        delete properties.passage_name;
      }
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
      if (kind !== 'passage') delete properties.passage_id;
      if (kind === 'passage') properties.number = name;
      delete properties.container_id;
      delete properties.title;
      delete properties.rotation;
      if (kind !== 'passage') delete properties.number;
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
    if (kind === 'container') syncContainerSizeFields(item.feature.geometry.coordinates);
    syncContainerResizeHandles(item);
    updateFeatureLabel(item);
    const shared = applyGroupSharedProperties(item);
    refreshList();
    setStatus(
      shared
        ? `Свойства применены ко всей группе: ${shared + 1} объект(ов)`
        : 'Свойства объекта применены',
      'success',
    );
    recordHistory();
  }

  // Группа меняется целиком: проход, цвета, размер и поворот раздаются всем
  // однотипным участникам. Номер и привязка к записи в БД у каждого свои.
  function applyGroupSharedProperties(sourceItem) {
    const ids = currentGroupTargets();
    if (ids.size < 2 || !ids.has(sourceItem.feature.id)) return 0;

    const source = sourceItem.feature.properties || {};
    const sourceRect = source.kind === 'container'
      ? containerRect(serializeItem(sourceItem).geometry.coordinates)
      : null;

    let changed = 0;
    ids.forEach((id) => {
      if (id === sourceItem.feature.id) return;
      const member = state.items.get(id);
      if (!member) return;
      const properties = member.feature.properties || {};
      if (properties.kind !== source.kind) return;

      properties.stroke_color = source.stroke_color;
      properties.fill_color = source.fill_color;
      properties.stroke_width = source.stroke_width;
      properties.min_zoom = source.min_zoom;

      if (source.kind === 'container') {
        properties.title = source.title;
        if (source.passage_id) {
          properties.passage_id = source.passage_id;
          delete properties.passage_feature_id;
          delete properties.passage_name;
        } else if (source.passage_feature_id) {
          properties.passage_id = null;
          properties.passage_feature_id = source.passage_feature_id;
          properties.passage_name = source.passage_name || '';
        }
        if (sourceRect) {
          const serialized = serializeItem(member);
          serialized.geometry.coordinates = resizeContainerCoordinates(
            serialized.geometry.coordinates,
            sourceRect.width,
            sourceRect.height,
            sourceRect.rotation,
          );
          member.feature.geometry.coordinates = serialized.geometry.coordinates;
          properties.rotation = Math.round(normalizeRotation(sourceRect.rotation) * 100) / 100;
        }
      }

      applyGeometryToOverlays(member);
      member.overlays.forEach((overlay) => {
        if (overlay instanceof google.maps.Marker) overlay.setIcon(markerIcon(properties, false));
        else overlay.setOptions(overlayStyle(properties, false));
      });
      setOverlayHighlighted(member, state.groupSelection.has(id));
      changed += 1;
    });
    return changed;
  }

  function cloneCoordinatesWithOffset(coordinates, deltaLng, deltaLat) {
    if (Array.isArray(coordinates) && coordinates.length >= 2 && typeof coordinates[0] === 'number' && typeof coordinates[1] === 'number') {
      return [coordinates[0] + deltaLng, coordinates[1] + deltaLat];
    }
    return Array.isArray(coordinates)
      ? coordinates.map((item) => cloneCoordinatesWithOffset(item, deltaLng, deltaLat))
      : coordinates;
  }

  // Копия встаёт вплотную вдоль осей самого контейнера: у повёрнутого ряда
  // «справа» означает вдоль ряда, а не строго на восток.
  function adjacentContainerCoordinates(coordinates, direction) {
    const rect = containerRect(coordinates);
    if (!rect) return coordinates;
    const axes = containerAxes(rect.rotation);
    const width = safeContainerSize(rect.width);
    const height = safeContainerSize(rect.height);
    const offsets = {
      right: [axes.width[0] * width, axes.width[1] * width],
      left: [-axes.width[0] * width, -axes.width[1] * width],
      down: [axes.height[0] * height, axes.height[1] * height],
      up: [-axes.height[0] * height, -axes.height[1] * height],
    };
    const offset = offsets[direction] || offsets.right;
    return [ringFromContainerRect({
      center: fromLocalMeters(offset, rect.center),
      width: rect.width,
      height: rect.height,
      rotation: rect.rotation,
    })];
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

  function applyGeometryToOverlays(item) {
    const geometry = item.feature.geometry || {};
    const coordinates = geometry.coordinates || [];
    if (geometry.type === 'Point') {
      item.overlays[0]?.setPosition({ lat: Number(coordinates[1]), lng: Number(coordinates[0]) });
    } else if (geometry.type === 'LineString') {
      item.overlays[0]?.setPath(coordinates.map((point) => ({ lat: Number(point[1]), lng: Number(point[0]) })));
    } else if (geometry.type === 'Polygon') {
      if (item.overlays[0]) setPolygonCoordinates(item.overlays[0], coordinates);
    } else if (geometry.type === 'MultiPolygon') {
      coordinates.forEach((polygon, index) => {
        if (item.overlays[index]) setPolygonCoordinates(item.overlays[index], polygon);
      });
    }
    updateFeatureLabel(item);
    syncContainerResizeHandles(item);
  }

  function geometryBboxCenter(geometry) {
    const points = iterCoordinatePoints(geometry?.coordinates || []);
    if (!points.length) return null;
    const lons = points.map((point) => point[0]);
    const lats = points.map((point) => point[1]);
    return [(Math.min(...lons) + Math.max(...lons)) / 2, (Math.min(...lats) + Math.max(...lats)) / 2];
  }

  // Тянем один объект группы — вместе с ним едет вся группа.
  function beginGroupDrag(id) {
    state.groupDrag = null;
    const item = state.items.get(id);
    if (!item) return;
    const ids = currentGroupTargets();
    if (ids.size < 2 || !ids.has(id)) return;
    const origin = geometryBboxCenter(serializeItem(item).geometry);
    if (!origin) return;
    state.groupDrag = { id, ids: Array.from(ids), origin };
  }

  function finishGroupDrag(id) {
    const drag = state.groupDrag;
    state.groupDrag = null;
    if (!drag || drag.id !== id) return 0;
    const item = state.items.get(id);
    if (!item) return 0;
    const moved = geometryBboxCenter(serializeItem(item).geometry);
    if (!moved) return 0;
    const deltaLon = moved[0] - drag.origin[0];
    const deltaLat = moved[1] - drag.origin[1];
    if (Math.abs(deltaLon) < 1e-9 && Math.abs(deltaLat) < 1e-9) return 0;

    let count = 0;
    drag.ids.forEach((memberId) => {
      if (memberId === id) return;
      const member = state.items.get(memberId);
      if (!member) return;
      const serialized = serializeItem(member);
      member.feature.geometry = {
        ...serialized.geometry,
        coordinates: shiftCoordinates(serialized.geometry.coordinates, deltaLon, deltaLat),
      };
      applyGeometryToOverlays(member);
      count += 1;
    });
    if (count) setStatus(`Группа перемещена: ${count + 1} объект(ов)`, 'success');
    return count;
  }

  function nextGroupName() {
    const used = new Set();
    state.items.forEach((item) => {
      const name = String((item.feature.properties || {}).group_name || '').trim();
      const match = name.match(/^Группа (\d+)$/);
      if (match) used.add(Number(match[1]));
    });
    let index = 1;
    while (used.has(index)) index += 1;
    return `Группа ${index}`;
  }

  function usedContainerNumbers() {
    const numbers = new Set();
    state.items.forEach((item) => {
      const properties = item.feature.properties || {};
      if (properties.kind !== 'container') return;
      const number = String(properties.number || properties.name || '').trim();
      if (number) numbers.add(number);
    });
    return numbers;
  }

  function freeContainerNumber(source, used) {
    let candidate = nextContainerNumber(source);
    let guard = 0;
    while (candidate && used.has(candidate) && guard < 500) {
      candidate = nextContainerNumber(candidate);
      guard += 1;
    }
    return candidate;
  }

  function collectionBbox(features) {
    const points = features.flatMap((feature) => iterCoordinatePoints(feature.geometry.coordinates || []));
    if (!points.length) return null;
    const lons = points.map((point) => point[0]);
    const lats = points.map((point) => point[1]);
    return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
  }

  function shiftCoordinates(coordinates, deltaLon, deltaLat) {
    if (Array.isArray(coordinates) && coordinates.length >= 2
      && typeof coordinates[0] === 'number' && typeof coordinates[1] === 'number') {
      return [coordinates[0] + deltaLon, coordinates[1] + deltaLat];
    }
    return (coordinates || []).map((item) => shiftCoordinates(item, deltaLon, deltaLat));
  }

  function groupSelectedFeatures() {
    const ids = Array.from(currentGroupTargets());
    if (ids.length < 2) {
      setStatus('Отметьте Ctrl+кликом хотя бы два объекта — они станут группой', 'error');
      return;
    }
    const groupId = makeId('group');
    const groupName = nextGroupName();
    ids.forEach((id) => {
      const item = state.items.get(id);
      if (!item) return;
      item.feature.properties.group = groupId;
      item.feature.properties.group_name = groupName;
    });
    state.groupSelection = new Set(ids);
    refreshGroupHighlight();
    recordHistory();
    root()?.dispatchEvent(new CustomEvent('market-map:dirty'));
    setStatus(`«${groupName}»: ${ids.length} объект(ов). Теперь группу можно дублировать целиком.`, 'success');
  }

  function ungroupSelectedFeatures() {
    const ids = Array.from(currentGroupTargets());
    const grouped = ids.filter((id) => featureGroupId(state.items.get(id)?.feature));
    if (!grouped.length) {
      setStatus('Выберите объект из группы, чтобы её разгруппировать', 'error');
      return;
    }
    grouped.forEach((id) => {
      const properties = state.items.get(id).feature.properties;
      delete properties.group;
      delete properties.group_name;
    });
    clearGroupSelection();
    refreshGroupHighlight();
    recordHistory();
    root()?.dispatchEvent(new CustomEvent('market-map:dirty'));
    setStatus(`Группа снята с ${grouped.length} объект(ов).`, 'success');
  }

  // Копия группы встаёт вплотную рядом: сдвиг равен габаритам самой группы,
  // поэтому взаимное расположение объектов внутри копии сохраняется.
  function duplicateGroupSelection() {
    const ids = Array.from(currentGroupTargets());
    if (!ids.length) {
      setStatus('Сначала выберите объекты или группу для дублирования', 'error');
      return;
    }

    const sources = ids
      .map((id) => state.items.get(id))
      .filter(Boolean)
      .map((item) => serializeItem(item))
      // Граница базара на карте всегда одна, копировать её нельзя.
      .filter((feature) => (feature.properties || {}).kind !== 'bazar');
    if (!sources.length) {
      setStatus('Границу базара дублировать нельзя — выберите районы, проходы или контейнеры', 'error');
      return;
    }
    const bbox = collectionBbox(sources);
    if (!bbox) {
      setStatus('У выбранных объектов нет координат', 'error');
      return;
    }

    const [minLon, minLat, maxLon, maxLat] = bbox;
    const gapLon = Math.max((maxLon - minLon) * 0.06, 0.000012);
    const gapLat = Math.max((maxLat - minLat) * 0.06, 0.000008);
    const direction = byId('market-group-direction')?.value || 'right';
    const offsets = {
      right: [(maxLon - minLon) + gapLon, 0],
      left: [-((maxLon - minLon) + gapLon), 0],
      up: [0, (maxLat - minLat) + gapLat],
      down: [0, -((maxLat - minLat) + gapLat)],
    };
    const [deltaLon, deltaLat] = offsets[direction] || offsets.right;

    const groupId = makeId('group');
    const groupName = nextGroupName();
    const used = usedContainerNumbers();
    const idMap = new Map();
    const copies = sources.map((source) => {
      const copy = JSON.parse(JSON.stringify(source));
      copy.id = makeId(copy.properties.kind || 'feature');
      idMap.set(source.id, copy.id);
      copy.geometry.coordinates = shiftCoordinates(copy.geometry.coordinates, deltaLon, deltaLat);
      copy.properties = { ...copy.properties, group: groupId, group_name: groupName };

      if (copy.properties.kind === 'container') {
        const number = freeContainerNumber(source.properties.number || source.properties.name, used);
        if (number) used.add(number);
        copy.properties.number = number || copy.properties.number;
        copy.properties.name = number || copy.properties.name;
        copy.properties.container_id = null;
      }
      if (copy.properties.kind === 'passage') {
        // Копия прохода — новый проход: номер и запись в справочнике будут свои.
        copy.properties.passage_id = null;
        copy.properties.number = `${copy.properties.number || copy.properties.name} копия`;
        copy.properties.name = copy.properties.number;
      }
      return { copy, source };
    });

    // Контейнер, чей проход тоже скопирован, должен встать в новый проход.
    copies.forEach(({ copy, source }) => {
      if (copy.properties.kind !== 'container') return;
      const passageSource = sources.find((item) => (item.properties || {}).kind === 'passage'
        && Number(item.properties.passage_id || 0)
        && Number(item.properties.passage_id) === Number(source.properties.passage_id || 0));
      const passageFeatureId = source.properties.passage_feature_id;
      const mapped = passageSource ? idMap.get(passageSource.id) : idMap.get(passageFeatureId);
      if (mapped) {
        copy.properties.passage_id = null;
        copy.properties.passage_feature_id = mapped;
      }
    });

    copies.forEach(({ copy }) => addFeature(copy));
    state.groupSelection = new Set(copies.map(({ copy }) => copy.id));
    selectFeature(null);
    refreshGroupHighlight();
    recordHistory();
    root()?.dispatchEvent(new CustomEvent('market-map:dirty'));
    setStatus(`«${groupName}»: копия из ${copies.length} объект(ов) поставлена рядом.`, 'success');
  }

  function updateGroupPanel() {
    const counter = byId('market-group-counter');
    const ids = currentGroupTargets();
    if (counter) {
      counter.textContent = ids.size
        ? `Выбрано объектов: ${ids.size}`
        : 'Ctrl+клик по объектам — набрать группу';
    }
    const grouped = Array.from(ids).some((id) => featureGroupId(state.items.get(id)?.feature));
    const createButton = byId('market-group-create');
    const duplicateButton = byId('market-group-duplicate');
    const ungroupButton = byId('market-group-ungroup');
    if (createButton) createButton.disabled = ids.size < 2;
    if (duplicateButton) duplicateButton.disabled = ids.size < 1;
    if (ungroupButton) ungroupButton.disabled = !grouped;
  }

  // Цвет разом для всех контейнеров карты: по одному их перекрашивать долго.
  function applyContainerColorToAll() {
    const fill = byId('market-feature-fill')?.value;
    const stroke = byId('market-feature-stroke')?.value;
    if (!fill || !stroke) return;

    let changed = 0;
    state.items.forEach((item) => {
      const properties = item.feature.properties || {};
      if (properties.kind !== 'container') return;
      properties.fill_color = fill;
      properties.stroke_color = stroke;
      setOverlaySelected(item, item.feature.id === state.selectedId);
      changed += 1;
    });

    if (!changed) {
      setStatus('На карте пока нет контейнеров', 'error');
      return;
    }
    refreshGroupHighlight();
    recordHistory();
    root()?.dispatchEvent(new CustomEvent('market-map:dirty'));
    setStatus(`Цвет применён ко всем контейнерам: ${changed} шт.`, 'success');
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
    // preventScroll: иначе браузер прокручивает инспектор к полю номера, и при
    // быстром дублировании экран прыгает после каждого клика.
    byId('market-feature-number')?.focus({ preventScroll: true });
    setStatus('Контейнер продублирован. Проверьте номер и положение.', 'success');
    recordHistory();
  }

  function refreshList() {
    syncPassageOptions();
    const list = byId('market-feature-list');
    if (!list) return;
    // Список перерисовывается целиком, поэтому его прокрутку возвращаем на место:
    // при дублировании подряд экран не должен уезжать в начало.
    const scroller = list.closest('.market-map-create-panel, .market-map-objects-panel') || list;
    const scrollTop = scroller.scrollTop;
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
        const groupName = String((item.feature.properties || {}).group_name || '').trim();
        if (groupName) {
          const badge = document.createElement('small');
          badge.className = 'market-feature-group-badge';
          badge.textContent = groupName;
          button.append(badge);
        }
        if (state.groupSelection.has(item.feature.id)) button.classList.add('is-group-selected');
        button.addEventListener('click', (event) => {
          if (event.ctrlKey || event.metaKey || event.shiftKey) {
            event.preventDefault();
            toggleGroupSelection(item.feature.id);
            return;
          }
          selectFeature(item.feature.id);
        });
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
    if (scroller.scrollTop !== scrollTop) scroller.scrollTop = scrollTop;
  }

  function setContainerRotation(item, rotation, { record = true, status = '', skipRotationHandle = false } = {}) {
    const rect = containerRect(item.feature.geometry.coordinates);
    if (!rect) return;
    const angle = normalizeRotation(rotation);
    item.feature.geometry.coordinates = [ringFromContainerRect({ ...rect, rotation: angle })];
    item.feature.properties.rotation = Math.round(angle * 100) / 100;
    state.lastContainerRotation = angle;
    item.overlays.forEach((overlay) => {
      if (!(overlay instanceof google.maps.Marker)) {
        setPolygonCoordinates(overlay, item.feature.geometry.coordinates);
      }
    });
    syncContainerSizeFields(item.feature.geometry.coordinates);
    syncContainerResizeHandles(item, -1, { skipRotationHandle });
    updateFeatureLabel(item);
    root()?.dispatchEvent(new CustomEvent('market-map:dirty'));
    if (status) setStatus(status, 'success');
    if (record) recordHistory();
  }

  function rotateSelectedContainer({ delta = 0, value = null } = {}) {
    const item = state.items.get(state.selectedId);
    if (!item || (item.feature.properties || {}).kind !== 'container') {
      setStatus('Сначала выберите контейнер', 'error');
      return;
    }
    const rect = containerRect(item.feature.geometry.coordinates);
    if (!rect) return;
    const angle = value === null
      ? normalizeRotation(rect.rotation + Number(delta || 0))
      : normalizeRotation(value);
    setContainerRotation(item, angle, {
      status: `Контейнер повёрнут на ${Math.round(angle * 10) / 10}°`,
    });
  }

  // Угол прохода, к которому привязан контейнер: сначала ищем сам проход на
  // карте, затем берём сохранённый угол из справочника проходов.
  function passageAngleForContainer(properties) {
    const featureId = properties.passage_feature_id;
    if (featureId && state.items.has(featureId)) {
      const angle = passageAngleDegrees(state.items.get(featureId).feature);
      if (angle !== null) return angle;
    }

    const passageId = Number(properties.passage_id || 0) || null;
    if (!passageId) return null;

    let drawn = null;
    state.items.forEach((item) => {
      const itemProperties = item.feature.properties || {};
      if (itemProperties.kind === 'passage' && Number(itemProperties.passage_id || 0) === passageId) {
        drawn = item.feature;
      }
    });
    if (drawn) {
      const angle = passageAngleDegrees(drawn);
      if (angle !== null) return angle;
    }

    const stored = readJsonScript('market-map-passages', [])
      .find((passage) => Number(passage.id) === passageId);
    const storedAngle = stored ? Number(stored.angle) : NaN;
    return Number.isFinite(storedAngle) ? storedAngle : null;
  }

  function rotateSelectedContainerAlongPassage() {
    const item = state.items.get(state.selectedId);
    if (!item || (item.feature.properties || {}).kind !== 'container') {
      setStatus('Сначала выберите контейнер', 'error');
      return;
    }
    const angle = passageAngleForContainer(item.feature.properties || {});
    if (angle === null) {
      setStatus('Сначала выберите проход контейнера — угол берётся у него', 'error');
      return;
    }
    rotateSelectedContainer({ value: angle });
  }

  function resizeSelectedContainer(dimension, delta) {
    const item = state.items.get(state.selectedId);
    if (!item || (item.feature.properties || {}).kind !== 'container') {
      setStatus('Сначала выберите контейнер', 'error');
      return;
    }
    const widthInput = byId('market-feature-width-m');
    const heightInput = byId('market-feature-height-m');
    const input = dimension === 'height' ? heightInput : widthInput;
    const currentValue = Number(input.value);
    const safeValue = Number.isFinite(currentValue) ? currentValue : 0.2;
    input.value = Math.max(0.2, Math.min(100, safeValue + Number(delta || 0))).toFixed(1);
    const serialized = serializeItem(item);
    serialized.geometry.coordinates = resizeContainerCoordinates(
      serialized.geometry.coordinates,
      Math.max(0.2, Number(widthInput.value || 4)),
      Math.max(0.2, Number(heightInput.value || 2.5)),
    );
    item.feature.geometry.coordinates = serialized.geometry.coordinates;
    item.overlays.forEach((overlay) => {
      if (!(overlay instanceof google.maps.Marker)) setPolygonCoordinates(overlay, serialized.geometry.coordinates);
    });
    syncContainerResizeHandles(item);
    updateFeatureLabel(item);
    root()?.dispatchEvent(new CustomEvent('market-map:dirty'));
    setStatus('Размер контейнера изменён', 'success');
    recordHistory();
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
      // Ряд контейнеров обычно стоит под одним углом, поэтому новый объект
      // повторяет поворот предыдущего.
      const rotation = normalizeRotation(state.lastContainerRotation);
      properties.rotation = Math.round(rotation * 100) / 100;
      const id = makeId(kind);
      addFeature({
        type: 'Feature',
        id,
        properties,
        geometry: { type: 'Polygon', coordinates: [containerRectangle(event.latLng, rotation)] },
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

  // Сервер при сохранении заводит проходы и контейнеры и возвращает карту с
  // проставленными id. Без этого редактор продолжал бы считать проход новым, и
  // переименование заводило бы вторую запись, отвязывая от неё контейнеры.
  const IDENTITY_KEYS = ['passage_id', 'container_id', 'district', 'angle', 'number', 'name'];

  function mergeServerIdentity(geojson) {
    const features = geojson?.features;
    if (!Array.isArray(features)) return;

    let touched = false;
    features.forEach((feature) => {
      const item = state.items.get(String(feature?.id || ''));
      if (!item) return;
      const source = feature.properties || {};
      const target = item.feature.properties || {};
      IDENTITY_KEYS.forEach((key) => {
        if (source[key] !== undefined && source[key] !== target[key]) {
          target[key] = source[key];
          touched = true;
        }
      });
      // Контейнер, привязанный к черновой фигуре прохода, после сохранения
      // держится уже за реальную запись прохода.
      if (source.passage_feature_id === undefined && target.passage_feature_id !== undefined) {
        delete target.passage_feature_id;
        delete target.passage_name;
        touched = true;
      }
      updateFeatureLabel(item);
    });

    if (touched) {
      refreshList();
      if (state.selectedId && state.items.has(state.selectedId)) {
        populateForm(state.items.get(state.selectedId).feature);
      }
    }
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
      mergeServerIdentity(data.geojson);
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
    byId('market-feature-color-all')?.addEventListener('click', applyContainerColorToAll);
    byId('market-group-create')?.addEventListener('click', groupSelectedFeatures);
    byId('market-group-duplicate')?.addEventListener('click', duplicateGroupSelection);
    byId('market-group-ungroup')?.addEventListener('click', ungroupSelectedFeatures);
    byId('market-group-clear')?.addEventListener('click', () => {
      clearGroupSelection();
      setStatus('Выделение группы снято', 'success');
    });
    document.querySelectorAll('[data-container-size-step]').forEach((button) => {
      button.addEventListener('click', () => resizeSelectedContainer(
        button.dataset.containerSizeStep,
        Number(button.dataset.delta || 0),
      ));
    });
    byId('market-feature-width-m')?.addEventListener('change', () => resizeSelectedContainer('width', 0));
    byId('market-feature-height-m')?.addEventListener('change', () => resizeSelectedContainer('height', 0));
    document.querySelectorAll('[data-container-rotate-step]').forEach((button) => {
      button.addEventListener('click', () => rotateSelectedContainer({
        delta: Number(button.dataset.containerRotateStep || 0),
      }));
    });
    document.querySelectorAll('[data-container-rotate-passage]').forEach((button) => {
      button.addEventListener('click', rotateSelectedContainerAlongPassage);
    });
    document.querySelectorAll('[data-container-rotate-set]').forEach((button) => {
      button.addEventListener('click', () => rotateSelectedContainer({
        value: Number(button.dataset.containerRotateSet || 0),
      }));
    });
    byId('market-feature-rotation-deg')?.addEventListener('change', (event) => {
      rotateSelectedContainer({ value: event.target.value });
    });
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
      if (command && event.key.toLowerCase() === 'd') {
        // Браузер по Ctrl+D открывает добавление в закладки — забираем сочетание себе.
        event.preventDefault();
        duplicateSelectedFeature();
        return;
      }
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
