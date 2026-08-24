(() => {
  'use strict';

  const originalInit = window.initMarketMapEditor;
  if (typeof originalInit !== 'function') return;

  const containerPolygons = [];
  const resizeHandles = [];
  const polygonAngles = new WeakMap();
  let selectedPolygon = null;
  let rotationHandle = null;
  let capturedMap = null;
  let patched = false;

  const METERS_PER_DEGREE = 111320;
  const byId = (id) => document.getElementById(id);

  function normalizeAngle(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) return 0;
    return ((number % 360) + 360) % 360;
  }

  function shortestAngle(value) {
    const normalized = normalizeAngle(value);
    return normalized > 180 ? normalized - 360 : normalized;
  }

  function ringFromPolygon(polygon) {
    const path = polygon?.getPath?.();
    if (!path || path.getLength() < 4) return [];
    const ring = [];
    for (let index = 0; index < path.getLength(); index += 1) {
      const point = path.getAt(index);
      ring.push([point.lng(), point.lat()]);
    }
    return ring.slice(0, 4);
  }

  function ringCenter(ring) {
    if (!ring.length) return null;
    const sum = ring.reduce((acc, point) => [acc[0] + point[0], acc[1] + point[1]], [0, 0]);
    return [sum[0] / ring.length, sum[1] / ring.length];
  }

  function localScale(centerLat) {
    return Math.max(0.2, Math.cos(Number(centerLat || 0) * Math.PI / 180));
  }

  function toLocal(point, center) {
    return [
      (point[0] - center[0]) * METERS_PER_DEGREE * localScale(center[1]),
      (point[1] - center[1]) * METERS_PER_DEGREE,
    ];
  }

  function fromLocal(point, center) {
    return [
      center[0] + point[0] / (METERS_PER_DEGREE * localScale(center[1])),
      center[1] + point[1] / METERS_PER_DEGREE,
    ];
  }

  function distanceMeters(first, second, center) {
    const a = toLocal(first, center);
    const b = toLocal(second, center);
    return Math.hypot(b[0] - a[0], b[1] - a[1]);
  }

  function polygonAngle(polygon) {
    const ring = ringFromPolygon(polygon);
    const center = ringCenter(ring);
    if (!center || ring.length < 2) return 0;
    const first = toLocal(ring[0], center);
    const second = toLocal(ring[1], center);
    return normalizeAngle(Math.atan2(second[1] - first[1], second[0] - first[0]) * 180 / Math.PI);
  }

  function setPolygonRing(polygon, ring) {
    if (!polygon || ring.length < 4) return;
    polygon.setPath(ring.map((point) => ({ lng: Number(point[0]), lat: Number(point[1]) })));
  }

  function rotateRing(ring, targetAngle) {
    const center = ringCenter(ring);
    if (!center || ring.length < 4) return ring;
    const current = (() => {
      const first = toLocal(ring[0], center);
      const second = toLocal(ring[1], center);
      return Math.atan2(second[1] - first[1], second[0] - first[0]) * 180 / Math.PI;
    })();
    const delta = (normalizeAngle(targetAngle) - normalizeAngle(current)) * Math.PI / 180;
    const cos = Math.cos(delta);
    const sin = Math.sin(delta);
    return ring.map((point) => {
      const [x, y] = toLocal(point, center);
      return fromLocal([x * cos - y * sin, x * sin + y * cos], center);
    });
  }

  function rotatePolygonTo(polygon, targetAngle) {
    const ring = ringFromPolygon(polygon);
    if (ring.length < 4) return;
    const angle = normalizeAngle(targetAngle);
    setPolygonRing(polygon, rotateRing(ring, angle));
    polygonAngles.set(polygon, angle);
  }

  function polygonDimensions(polygon) {
    const ring = ringFromPolygon(polygon);
    const center = ringCenter(ring);
    if (!center || ring.length < 4) return null;
    return {
      width: distanceMeters(ring[0], ring[1], center),
      height: distanceMeters(ring[1], ring[2], center),
    };
  }

  function syncSizeFields() {
    if (!selectedPolygon) return;
    const dimensions = polygonDimensions(selectedPolygon);
    if (!dimensions) return;
    const width = byId('market-feature-width-m');
    const height = byId('market-feature-height-m');
    if (width) width.value = Math.max(0.2, Math.round(dimensions.width * 10) / 10);
    if (height) height.value = Math.max(0.2, Math.round(dimensions.height * 10) / 10);
  }

  function rotationInput() {
    return byId('market-feature-rotation-deg');
  }

  function syncRotationInput() {
    if (!selectedPolygon) return;
    const angle = polygonAngle(selectedPolygon);
    polygonAngles.set(selectedPolygon, angle);
    const input = rotationInput();
    if (input) input.value = String(Math.round(normalizeAngle(angle) * 10) / 10);
  }

  function markDirty(message = 'Поворот контейнера изменён. Сохраните карту.') {
    document.getElementById('market-map-editor')?.dispatchEvent(new CustomEvent('market-map:dirty'));
    const status = byId('market-map-status');
    if (status) {
      status.textContent = message;
      status.className = 'success';
    }
  }

  function rotationHandlePosition(polygon) {
    const ring = ringFromPolygon(polygon);
    const center = ringCenter(ring);
    if (!center || ring.length < 4) return null;
    const topMid = [(ring[0][0] + ring[1][0]) / 2, (ring[0][1] + ring[1][1]) / 2];
    const local = toLocal(topMid, center);
    const length = Math.hypot(local[0], local[1]) || 1;
    const extra = 2.2;
    const point = fromLocal([
      local[0] + local[0] / length * extra,
      local[1] + local[1] / length * extra,
    ], center);
    return { lng: point[0], lat: point[1] };
  }

  function updateRotationHandle() {
    if (!rotationHandle || !selectedPolygon) return;
    const position = rotationHandlePosition(selectedPolygon);
    if (position) rotationHandle.setPosition(position);
  }

  function ensureRotationHandle() {
    if (!capturedMap || !selectedPolygon || !window.google?.maps) return;
    if (!rotationHandle) {
      rotationHandle = new google.maps.Marker({
        map: capturedMap,
        draggable: true,
        clickable: true,
        cursor: 'grab',
        title: 'Потяните, чтобы повернуть контейнер',
        zIndex: 10000,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          fillColor: '#ffffff',
          fillOpacity: 1,
          strokeColor: '#111827',
          strokeWeight: 2,
          scale: 10,
        },
        label: {
          text: '↻',
          color: '#111827',
          fontSize: '14px',
          fontWeight: '900',
        },
      });
      rotationHandle.addListener('click', (event) => event?.domEvent?.stopPropagation?.());
      rotationHandle.addListener('drag', () => {
        if (!selectedPolygon) return;
        const ring = ringFromPolygon(selectedPolygon);
        const center = ringCenter(ring);
        const position = rotationHandle.getPosition();
        if (!center || !position) return;
        const local = toLocal([position.lng(), position.lat()], center);
        const normalAngle = Math.atan2(local[1], local[0]) * 180 / Math.PI;
        const target = normalizeAngle(normalAngle - 90);
        rotatePolygonTo(selectedPolygon, target);
        syncRotationInput();
        syncSizeFields();
        updateRotationHandle();
      });
      rotationHandle.addListener('dragend', () => markDirty());
    } else {
      rotationHandle.setMap(capturedMap);
    }
    updateRotationHandle();
  }

  function hideRotationHandle() {
    rotationHandle?.setMap(null);
  }

  function hideNativeResizeHandlesWhenRotated() {
    if (!selectedPolygon) return;
    if (Math.abs(shortestAngle(polygonAngle(selectedPolygon))) < 0.05) return;
    resizeHandles.forEach((handle) => {
      if (handle.getMap?.() === capturedMap) handle.setMap(null);
    });
  }

  function selectContainerPolygon(polygon) {
    selectedPolygon = polygon;
    syncRotationInput();
    syncSizeFields();
    ensureRotationHandle();
    window.setTimeout(hideNativeResizeHandlesWhenRotated, 0);
  }

  function applyRotation(value, { dirty = true } = {}) {
    if (!selectedPolygon) return;
    rotatePolygonTo(selectedPolygon, value);
    syncRotationInput();
    syncSizeFields();
    updateRotationHandle();
    hideNativeResizeHandlesWhenRotated();
    if (dirty) markDirty();
  }

  function installRotationControls() {
    if (rotationInput()) return;
    const widthInput = byId('market-feature-width-m');
    const grid = widthInput?.closest('.market-map-grid-fields');
    if (!grid) return;

    const row = document.createElement('div');
    row.className = 'form-row';
    row.dataset.kindScope = 'container';
    row.innerHTML = `
      <label for="market-feature-rotation-deg">Поворот, °</label>
      <div class="map-size-stepper">
        <button type="button" data-container-rotate-step="-15" aria-label="Повернуть на 15 градусов влево">↶</button>
        <input id="market-feature-rotation-deg" type="number" min="0" max="359.9" step="1" value="0">
        <button type="button" data-container-rotate-step="15" aria-label="Повернуть на 15 градусов вправо">↷</button>
      </div>
      <small>Можно задать любой угол или потянуть маркер ↻ над контейнером.</small>
    `;
    grid.insertAdjacentElement('afterend', row);

    row.querySelectorAll('[data-container-rotate-step]').forEach((button) => {
      button.addEventListener('click', () => {
        if (!selectedPolygon) return;
        applyRotation(polygonAngle(selectedPolygon) + Number(button.dataset.containerRotateStep || 0));
      });
    });
    rotationInput()?.addEventListener('change', (event) => applyRotation(event.target.value));
  }

  function isContainerPolygonOptions(options) {
    return Number(options?.zIndex || 0) >= 100 && Number(options?.fillOpacity ?? 0) >= 0.9;
  }

  function patchGoogleConstructors() {
    if (patched || !window.google?.maps) return;
    patched = true;

    const NativePolygon = google.maps.Polygon;
    google.maps.Polygon = function PatchedPolygon(options = {}) {
      const polygon = new NativePolygon(options);
      if (options?.map) capturedMap = options.map;
      if (isContainerPolygonOptions(options)) {
        containerPolygons.push(polygon);
        polygonAngles.set(polygon, polygonAngle(polygon));
        polygon.addListener('click', () => window.setTimeout(() => selectContainerPolygon(polygon), 0));

        const preserveRotation = () => {
          const ring = ringFromPolygon(polygon);
          if (ring.length < 4) return;
          const angle = polygonAngles.get(polygon) ?? polygonAngle(polygon);
          window.setTimeout(() => {
            setPolygonRing(polygon, ring);
            polygonAngles.set(polygon, angle);
            if (selectedPolygon === polygon) {
              syncRotationInput();
              syncSizeFields();
              updateRotationHandle();
              hideNativeResizeHandlesWhenRotated();
            }
          }, 0);
        };
        polygon.addListener('mouseup', preserveRotation);
        polygon.addListener('dragend', preserveRotation);
      }
      return polygon;
    };
    google.maps.Polygon.prototype = NativePolygon.prototype;
    Object.setPrototypeOf(google.maps.Polygon, NativePolygon);

    const NativeMarker = google.maps.Marker;
    google.maps.Marker = function PatchedMarker(options = {}) {
      const marker = new NativeMarker(options);
      if (String(options?.title || '').includes('изменить размер контейнера')) {
        resizeHandles.push(marker);
      }
      return marker;
    };
    google.maps.Marker.prototype = NativeMarker.prototype;
    Object.setPrototypeOf(google.maps.Marker, NativeMarker);
  }

  function polygonCenter(polygon) {
    return ringCenter(ringFromPolygon(polygon));
  }

  function featureCenter(feature) {
    const ring = feature?.geometry?.coordinates?.[0] || [];
    if (!ring.length) return null;
    return ringCenter(ring.slice(0, 4));
  }

  function centerDistanceSquared(first, second) {
    if (!first || !second) return Number.POSITIVE_INFINITY;
    const scale = localScale((first[1] + second[1]) / 2);
    const dx = (first[0] - second[0]) * scale;
    const dy = first[1] - second[1];
    return dx * dx + dy * dy;
  }

  function rewriteContainerGeometry(payload) {
    const features = payload?.geojson?.features;
    if (!Array.isArray(features)) return payload;
    const available = containerPolygons.filter((polygon) => polygon.getMap?.());
    const used = new Set();

    features.forEach((feature) => {
      if ((feature.properties || {}).kind !== 'container' || feature.geometry?.type !== 'Polygon') return;
      const center = featureCenter(feature);
      let bestIndex = -1;
      let bestDistance = Number.POSITIVE_INFINITY;
      available.forEach((polygon, index) => {
        if (used.has(index)) return;
        const distance = centerDistanceSquared(center, polygonCenter(polygon));
        if (distance < bestDistance) {
          bestDistance = distance;
          bestIndex = index;
        }
      });
      if (bestIndex < 0) return;
      used.add(bestIndex);
      const polygon = available[bestIndex];
      const ring = ringFromPolygon(polygon);
      if (ring.length < 4) return;
      feature.geometry.coordinates = [[...ring, [...ring[0]]]];
      feature.properties.rotation = Math.round(normalizeAngle(polygonAngle(polygon)) * 100) / 100;
    });
    return payload;
  }

  function patchFetch() {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input, init = {}) => {
      try {
        const url = typeof input === 'string' ? input : String(input?.url || '');
        if (/\/panel\/map\/\d+\/(save|publish)\/?$/.test(url) && typeof init.body === 'string') {
          const payload = JSON.parse(init.body);
          rewriteContainerGeometry(payload);
          init = { ...init, body: JSON.stringify(payload) };
        }
      } catch (_) {
        // Keep the editor's original request intact if payload inspection fails.
      }
      return nativeFetch(input, init);
    };
  }

  function bindAfterInit() {
    installRotationControls();
    patchFetch();

    document.querySelectorAll('[data-container-size-step]').forEach((button) => {
      button.addEventListener('click', () => {
        if (!selectedPolygon) return;
        const angle = polygonAngles.get(selectedPolygon) ?? polygonAngle(selectedPolygon);
        window.setTimeout(() => applyRotation(angle, { dirty: false }), 0);
      });
    });
    ['market-feature-width-m', 'market-feature-height-m'].forEach((id) => {
      byId(id)?.addEventListener('change', () => {
        if (!selectedPolygon) return;
        const angle = polygonAngles.get(selectedPolygon) ?? polygonAngle(selectedPolygon);
        window.setTimeout(() => applyRotation(angle, { dirty: false }), 0);
      });
    });

    byId('market-feature-apply')?.addEventListener('click', () => {
      if (!selectedPolygon) return;
      const angle = polygonAngles.get(selectedPolygon) ?? polygonAngle(selectedPolygon);
      window.setTimeout(() => applyRotation(angle, { dirty: false }), 0);
    });

    let duplicateSourceAngle = null;
    byId('market-feature-duplicate')?.addEventListener('pointerdown', () => {
      duplicateSourceAngle = selectedPolygon ? polygonAngle(selectedPolygon) : null;
    }, true);
    byId('market-feature-duplicate')?.addEventListener('click', () => {
      if (duplicateSourceAngle === null) return;
      window.setTimeout(() => {
        const newest = containerPolygons[containerPolygons.length - 1];
        if (!newest) return;
        selectContainerPolygon(newest);
        applyRotation(duplicateSourceAngle, { dirty: false });
      }, 0);
    });

    capturedMap?.addListener('click', () => {
      window.setTimeout(() => {
        const kind = byId('market-feature-kind')?.value;
        const visibleContainerFields = Array.from(document.querySelectorAll('[data-kind-scope="container"]'))
          .some((node) => !node.hidden);
        if (kind !== 'container' || !visibleContainerFields) hideRotationHandle();
      }, 0);
    });
  }

  window.initMarketMapEditor = function initMarketMapEditorWithRotation(...args) {
    patchGoogleConstructors();
    const result = originalInit.apply(this, args);
    bindAfterInit();
    return result;
  };
})();
