from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from apps.delivery.map_models import MarketMapRevision
from apps.delivery.models import Bazar, Container, DeliveryDistrict, Passage


pytestmark = pytest.mark.django_db


def _field_names(model, *, obj=None):
    model_admin = admin.site._registry[model]
    fieldsets = model_admin.get_fieldsets(request=None, obj=obj)
    return [field for _, options in fieldsets for field in options.get("fields", ())]


def _admin_request():
    request = RequestFactory().get("/admin/")
    request.user = AnonymousUser()
    return request


def _build_add_form(model):
    """Build the exact form Django admin uses on /add/ pages."""
    request = _admin_request()
    model_admin = admin.site._registry[model]
    form_class = model_admin.get_form(request=request, obj=None)
    return form_class()


def _district_feature(name: str):
    return {
        "type": "Feature",
        "id": f"district-{name}",
        "properties": {"kind": "district", "name": name},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [74.60, 42.87],
                [74.61, 42.87],
                [74.61, 42.88],
                [74.60, 42.88],
                [74.60, 42.87],
            ]],
        },
    }


def test_district_add_form_selects_district_and_only_asks_price_per_km():
    assert _field_names(DeliveryDistrict) == ["name", "per_km_price", "is_active"]

    bazar = Bazar.objects.create(name="Дордой")
    MarketMapRevision.objects.create(
        bazar=bazar,
        version=1,
        status=MarketMapRevision.Status.DRAFT,
        geojson={"type": "FeatureCollection", "features": [_district_feature("Северный район")]},
    )

    form = _build_add_form(DeliveryDistrict)
    assert list(form.fields) == ["name", "per_km_price", "is_active"]
    assert form.fields["name"].widget.__class__.__name__ == "Select"
    assert form.fields["name"].label == "Район с карты"
    assert ("Северный район", "Северный район") in list(form.fields["name"].choices)
    assert form.fields["per_km_price"].label == "Стоимость за км, сом"
    assert form.fields["per_km_price"].required is True
    assert "fixed_price" not in form.fields
    assert "base_price" not in form.fields
    assert "min_fare" not in form.fields


def test_district_with_existing_tariff_is_not_offered_for_duplicate_creation():
    bazar = Bazar.objects.create(name="Ошский рынок")
    MarketMapRevision.objects.create(
        bazar=bazar,
        version=1,
        status=MarketMapRevision.Status.DRAFT,
        geojson={"type": "FeatureCollection", "features": [_district_feature("Центральный")]},
    )
    DeliveryDistrict.objects.create(name="Центральный", per_km_price=Decimal("80"))

    form = _build_add_form(DeliveryDistrict)
    assert ("Центральный", "Центральный") not in list(form.fields["name"].choices)


def test_saving_district_tariff_clears_old_price_modes():
    district = DeliveryDistrict.objects.create(
        name="Старый район",
        fixed_price=150,
        base_price=Decimal("100"),
        per_km_price=Decimal("75"),
        min_fare=Decimal("120"),
    )
    model_admin = admin.site._registry[DeliveryDistrict]

    model_admin.save_model(_admin_request(), district, form=None, change=True)
    district.refresh_from_db()

    assert district.per_km_price == Decimal("75")
    assert district.fixed_price is None
    assert district.base_price is None
    assert district.min_fare is None


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
