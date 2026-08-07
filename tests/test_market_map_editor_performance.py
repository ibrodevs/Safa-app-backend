from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "apps/delivery/templates/admin/delivery/marketmaprevision/map_editor.html"
PERF_JS = ROOT / "apps/delivery/static/delivery/admin/market_map_editor_perf.js"


def test_performance_optimizer_loads_before_google_maps_callback():
    template = TEMPLATE.read_text(encoding="utf-8")

    optimizer = "market_map_editor_perf.js"
    google_maps = "maps.googleapis.com/maps/api/js"
    assert optimizer in template
    assert google_maps in template
    assert template.index(optimizer) < template.index(google_maps)


def test_performance_optimizer_hides_labels_during_map_interaction():
    script = PERF_JS.read_text(encoding="utf-8")

    assert "dragstart" in script
    assert "zoom_changed" in script
    assert "hideLabelsImmediately" in script
    assert "idle" in script
    assert "restoreLabelsInBatches" in script


def test_performance_optimizer_limits_label_work_to_viewport_and_zoom():
    script = PERF_JS.read_text(encoding="utf-8")

    assert "bounds.contains(position)" in script
    assert "zoom < Number(meta.minZoom || 0)" in script
    assert "const batchSize = 80" in script
    assert "requestAnimationFrame" in script


def test_performance_optimizer_avoids_duplicate_geometry_updates():
    script = PERF_JS.read_text(encoding="utf-8")

    assert "eventName === 'mouseup' || eventName === 'dragend'" in script
    assert "cancelAnimationFrame(geometryFrame)" in script
    assert "optimized: options.optimized !== false" in script
