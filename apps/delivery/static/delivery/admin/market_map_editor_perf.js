(() => {
  'use strict';

  const originalInit = window.initMarketMapEditor;
  if (typeof originalInit !== 'function') return;

  const perf = {
    installed: false,
    map: null,
    labels: new Set(),
    visibilityFrame: 0,
    restoreTimer: 0,
  };

  function inferLabelMinZoom(options) {
    const zIndex = Number(options?.zIndex || 0);
    if (zIndex >= 100) return 17; // контейнеры
    if (zIndex >= 60) return 16;  // проходы
    if (zIndex >= 20) return 13;  // районы
    return 10;                    // граница базара
  }

  function isFeatureLabel(options) {
    const icon = options?.icon || {};
    return Boolean(
      options?.label &&
      options?.clickable === false &&
      Number(icon.scale || 0) === 0
    );
  }

  function cancelVisibilityWork() {
    if (perf.visibilityFrame) {
      window.cancelAnimationFrame(perf.visibilityFrame);
      perf.visibilityFrame = 0;
    }
    if (perf.restoreTimer) {
      window.clearTimeout(perf.restoreTimer);
      perf.restoreTimer = 0;
    }
  }

  function hideLabelsImmediately() {
    cancelVisibilityWork();
    perf.labels.forEach((marker) => {
      if (marker?.getVisible?.()) marker.setVisible(false);
    });
  }

  function labelShouldBeVisible(marker) {
    const map = perf.map;
    if (!map || !marker?.getPosition) return false;

    const meta = marker.__safaPerfLabelMeta || {};
    const zoom = Number(map.getZoom?.() || 0);
    if (zoom < Number(meta.minZoom || 0)) return false;

    const bounds = map.getBounds?.();
    const position = marker.getPosition();
    return Boolean(position && (!bounds || bounds.contains(position)));
  }

  function restoreLabelsInBatches() {
    cancelVisibilityWork();

    const markers = Array.from(perf.labels);
    let index = 0;
    const batchSize = 80;

    const renderBatch = () => {
      const end = Math.min(index + batchSize, markers.length);
      for (; index < end; index += 1) {
        const marker = markers[index];
        if (!perf.labels.has(marker)) continue;
        const nextVisible = labelShouldBeVisible(marker);
        if (marker.getVisible?.() !== nextVisible) marker.setVisible(nextVisible);
      }
      if (index < markers.length) {
        perf.visibilityFrame = window.requestAnimationFrame(renderBatch);
      } else {
        perf.visibilityFrame = 0;
      }
    };

    perf.visibilityFrame = window.requestAnimationFrame(renderBatch);
  }

  function scheduleLabelRestore(delay = 50) {
    cancelVisibilityWork();
    perf.restoreTimer = window.setTimeout(() => {
      perf.restoreTimer = 0;
      restoreLabelsInBatches();
    }, delay);
  }

  function attachMapPerformanceListeners(map) {
    if (!map || map.__safaPerfListenersInstalled) return;
    map.__safaPerfListenersInstalled = true;

    map.addListener('dragstart', hideLabelsImmediately);
    map.addListener('zoom_changed', hideLabelsImmediately);
    map.addListener('idle', () => scheduleLabelRestore(30));
    map.addListener('tilesloaded', () => scheduleLabelRestore(30));
  }

  function patchOverlayInstance(overlay) {
    if (!overlay || overlay.__safaPerfPatched) return overlay;
    overlay.__safaPerfPatched = true;

    const originalAddListener = overlay.addListener?.bind(overlay);
    if (!originalAddListener) return overlay;

    let geometryFrame = 0;
    overlay.addListener = (eventName, handler) => {
      if ((eventName === 'mouseup' || eventName === 'dragend') && typeof handler === 'function') {
        return originalAddListener(eventName, (...args) => {
          if (geometryFrame) window.cancelAnimationFrame(geometryFrame);
          geometryFrame = window.requestAnimationFrame(() => {
            geometryFrame = 0;
            handler(...args);
          });
        });
      }
      return originalAddListener(eventName, handler);
    };

    originalAddListener('dragstart', hideLabelsImmediately);
    originalAddListener('dragend', () => scheduleLabelRestore(40));
    return overlay;
  }

  function wrapConstructor(originalConstructor, factory) {
    function WrappedConstructor(...args) {
      return factory(originalConstructor, args);
    }
    WrappedConstructor.prototype = originalConstructor.prototype;
    try {
      Object.setPrototypeOf(WrappedConstructor, originalConstructor);
    } catch (_) {
      // Старые браузеры: prototype достаточно для instanceof.
    }
    return WrappedConstructor;
  }

  function installGoogleMapsPerformancePatch() {
    if (perf.installed || !window.google?.maps) return;
    perf.installed = true;

    const maps = window.google.maps;
    const OriginalMap = maps.Map;
    const OriginalMarker = maps.Marker;
    const OriginalPolygon = maps.Polygon;
    const OriginalPolyline = maps.Polyline;

    maps.Map = wrapConstructor(OriginalMap, (Ctor, args) => {
      const [element, options = {}] = args;
      const map = new Ctor(element, {
        ...options,
        gestureHandling: 'greedy',
      });
      perf.map = map;
      attachMapPerformanceListeners(map);
      return map;
    });

    maps.Marker = wrapConstructor(OriginalMarker, (Ctor, args) => {
      const [options = {}] = args;
      const marker = new Ctor({
        ...options,
        optimized: options.optimized !== false,
      });

      if (isFeatureLabel(options)) {
        marker.__safaPerfLabelMeta = {
          minZoom: inferLabelMinZoom(options),
        };
        perf.labels.add(marker);
        marker.setVisible(false);

        const originalSetMap = marker.setMap?.bind(marker);
        if (originalSetMap) {
          marker.setMap = (map) => {
            if (map === null) perf.labels.delete(marker);
            return originalSetMap(map);
          };
        }
        scheduleLabelRestore(0);
      }

      const originalSetAnimation = marker.setAnimation?.bind(marker);
      if (originalSetAnimation) {
        marker.setAnimation = (animation) => {
          if (animation === maps.Animation?.BOUNCE) return undefined;
          return originalSetAnimation(animation);
        };
      }

      return marker;
    });

    maps.Polygon = wrapConstructor(OriginalPolygon, (Ctor, args) => {
      const [options = {}] = args;
      return patchOverlayInstance(new Ctor(options));
    });

    maps.Polyline = wrapConstructor(OriginalPolyline, (Ctor, args) => {
      const [options = {}] = args;
      return patchOverlayInstance(new Ctor(options));
    });
  }

  window.initMarketMapEditor = function initMarketMapEditorOptimized() {
    installGoogleMapsPerformancePatch();
    const result = originalInit();
    scheduleLabelRestore(80);
    return result;
  };
})();
