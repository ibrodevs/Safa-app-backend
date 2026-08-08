from django.contrib import admin

from apps.delivery.map_models import MarketMapRevision
from apps.delivery.models import Bazar, Container, DeliveryDistrict, Passage


def _field_names(model, *, obj=None):
    model_admin = admin.site._registry[model]
    fieldsets = model_admin.get_fieldsets(request=None, obj=obj)
    return [field for _, options in fieldsets for field in options.get("fields", ())]


def _build_add_form(model):
    """Build the exact form Django admin uses on /add/ pages."""
    model_admin = admin.site._registry[model]
    form_class = model_admin.get_form(request=None, obj=None)
    return form_class()


def test_district_add_form_only_shows_simple_fields():
    assert _field_names(DeliveryDistrict) == ["name", "fixed_price", "is_active"]

    form = _build_add_form(DeliveryDistrict)
    assert list(form.fields) == ["name", "fixed_price", "is_active"]
    assert form.fields["name"].widget.__class__.__name__ != "Select"
    assert form.fields["name"].label == "Название района"


def test_bazar_add_form_hides_legacy_coordinates_and_prices():
    assert _field_names(Bazar) == ["name", "district_tariff", "fixed_price"]

    form = _build_add_form(Bazar)
    assert list(form.fields) == ["name", "district_tariff", "fixed_price"]


def test_passage_add_form_is_only_bazar_and_number():
    assert _field_names(Passage) == ["bazar", "number"]

    form = _build_add_form(Passage)
    assert list(form.fields) == ["bazar", "number"]


def test_container_add_form_keeps_only_business_fields_and_location():
    assert _field_names(Container) == ["passage", "number", "title", "lat", "lon"]

    form = _build_add_form(Container)
    assert list(form.fields) == ["passage", "number", "title", "lat", "lon"]


def test_technical_market_revision_is_hidden_from_admin_index():
    model_admin = admin.site._registry[MarketMapRevision]
    assert model_admin.get_model_perms(request=None) == {}
