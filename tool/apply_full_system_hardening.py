from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one match in {path}, found {count}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Production configuration that was referenced by code but never loaded.
replace_once(
    "core/settings.py",
    'DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"\n',
    'DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"\n'
    'ENABLE_DEBUG_OTP_ENDPOINT = os.getenv("ENABLE_DEBUG_OTP_ENDPOINT", "0") == "1"\n',
)
replace_once(
    "core/settings.py",
    'OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))\nDEMO_OTP_CODE = os.getenv("DEMO_OTP_CODE", "").strip()\n',
    'OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))\n'
    'OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))\n'
    'DEMO_OTP_CODE = os.getenv("DEMO_OTP_CODE", "").strip()\n'
    'YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "").strip()\n',
)
replace_once(
    "core/settings.py",
    'for item in os.getenv("STATIC_OTP", "996555555555:1111").split(",")\n',
    'for item in os.getenv("STATIC_OTP", "").split(",")\n',
)

# Never expose OTP codes unless explicitly enabled; prevent cross-user profile reads.
replace_once(
    "apps/users/views.py",
    'from django.shortcuts import render\n',
    'from django.shortcuts import render\nfrom django.conf import settings\nfrom django.http import Http404\n',
)
replace_once(
    "apps/users/views.py",
    '    def post(self, request, *args, **kwargs):\n        ser = self.get_serializer(data=request.data)\n',
    '    def post(self, request, *args, **kwargs):\n'
    '        if not getattr(settings, "ENABLE_DEBUG_OTP_ENDPOINT", False):\n'
    '            raise Http404\n'
    '        ser = self.get_serializer(data=request.data)\n',
)
replace_once(
    "apps/users/views.py",
    '        if pk is None:\n            return self._self_profile()            \n        return self.get_queryset().get(pk=pk)     \n',
    '        if pk is None:\n'
    '            return self._self_profile()\n'
    '        obj = self.get_queryset().get(pk=pk)\n'
    '        if not (self.request.user.is_staff or obj.user_id == self.request.user.id):\n'
    '            raise PermissionDenied("profile_access_denied")\n'
    '        return obj\n',
)

# Restoreable shipment state for both client and carrier applications.
replace_once(
    "apps/delivery/serializer.py",
    '            "service_type",\n            "description",\n            "stops",\n',
    '            "service_type",\n'
    '            "description",\n'
    '            "client_id",\n'
    '            "carrier_id",\n'
    '            "current_stop_index",\n'
    '            "stops",\n',
)

# Shipment status invariants and carrier-only nearby feed.
replace_once(
    "apps/delivery/views.py",
    'from apps.notification.events import notify_shipment_status\n',
    'from apps.notification.events import notify_shipment_offer_for_carrier, notify_shipment_status\n',
)
replace_once(
    "apps/delivery/views.py",
    '            shipment = serializer.save()\n            _broadcast(shipment)\n            logger.info(\n',
    '            shipment = serializer.save()\n'
    '            _broadcast(shipment)\n'
    '            notify_shipment_offer_for_carrier(shipment)\n'
    '            logger.info(\n',
)
replace_once(
    "apps/delivery/views.py",
    '        if new_status == Shipment.Status.COMPLETED:\n            _complete_shipment_if_needed(s)\n        else:\n            s.status = new_status\n            s.save(update_fields=["status"])\n            if new_status != old_status:\n                notify_shipment_status(s)\n',
    '        if new_status == Shipment.Status.COMPLETED:\n'
    '            _complete_shipment_if_needed(s)\n'
    '            _increment_carrier_rating(s)\n'
    '            notify_shipment_status(s)\n'
    '        else:\n'
    '            s.status = new_status\n'
    '            update_fields = ["status"]\n'
    '            if new_status == Shipment.Status.PENDING:\n'
    '                s.carrier = None\n'
    '                update_fields.append("carrier")\n'
    '            s.save(update_fields=update_fields)\n'
    '            if new_status != old_status:\n'
    '                notify_shipment_status(s)\n',
)
replace_once(
    "apps/delivery/views.py",
    '    def nearby(self, request):\n        rid = _rid(request)\n        try:\n',
    '    def nearby(self, request):\n'
    '        rid = _rid(request)\n'
    '        if getattr(request.user, "role", None) != User.Roles.CARRIER:\n'
    '            return response.Response({"detail": "only_for_carrier"}, status=status.HTTP_403_FORBIDDEN)\n'
    '        try:\n',
)

# ModelViewSet DELETE must not erase financial/order history.
insert_before = '    @extend_schema(\n        tags=["Shipments"],\n        summary="Курьер принимает посылку",\n'
replacement = '''    def destroy(self, request, *args, **kwargs):
        shipment = self.get_object()
        if shipment.client_id != request.user.id and not request.user.is_staff:
            return response.Response({"detail": "only_for_client"}, status=status.HTTP_403_FORBIDDEN)
        if shipment.status in (Shipment.Status.COMPLETED, Shipment.Status.CANCELED):
            return response.Response({"detail": "terminal_shipment"}, status=status.HTTP_409_CONFLICT)
        shipment.status = Shipment.Status.CANCELED
        shipment.save(update_fields=["status"])
        notify_shipment_status(shipment)
        _broadcast(shipment)
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=["Shipments"],
        summary="Курьер принимает посылку",
'''
replace_once("apps/delivery/views.py", insert_before, replacement)

# Current shipment model no longer has legacy segment/size/quantity/fragile fields.
replace_once(
    "apps/notification/events.py",
    '    body = f"{shipment.title} · {shipment.estimated_fare} с"\n',
    '    body = f"{shipment.title} · {shipment.estimated_fare} сом"\n',
)
replace_once(
    "apps/notification/events.py",
    '        "segment": shipment.segment.slug,\n        "segment_name": shipment.segment.name,\n        "estimated_fare": str(shipment.estimated_fare),\n        "size": shipment.size,\n        "quantity": str(shipment.quantity),\n        "fragile": "1" if shipment.fragile else "0",\n',
    '        "service_type": shipment.service_type,\n'
    '        "estimated_fare": str(shipment.estimated_fare),\n',
)
replace_once(
    "apps/notification/events.py",
    '    if shipment.carrier_id:\n        _send_to_user(\n            shipment.carrier_id,\n            data,\n            ttl="15s",\n            collapse_key=collapse_key,\n        )\n',
    '    carrier_ids = (\n'
    '        FCMToken.objects.filter(user__role=User.Roles.CARRIER, is_active=True)\n'
    '        .values_list("user_id", flat=True)\n'
    '        .distinct()\n'
    '    )\n'
    '    for carrier_id in carrier_ids:\n'
    '        if carrier_id == shipment.client_id:\n'
    '            continue\n'
    '        _send_to_user(carrier_id, dict(data), ttl="15s", collapse_key=collapse_key)\n',
)

# Deployment example: no live/demo secrets by default and all used variables documented.
replace_once(
    ".env.example",
    'DJANGO_DEBUG=0\n',
    'DJANGO_DEBUG=0\nENABLE_DEBUG_OTP_ENDPOINT=0\n',
)
replace_once(
    ".env.example",
    'STATIC_OTP=996555555555:1111\n',
    'STATIC_OTP=\nOTP_MAX_ATTEMPTS=5\nGOOGLE_MAPS_BROWSER_API_KEY=\n',
)
replace_once(
    ".env.example",
    'FINIK_CALLBACK_URL=\n',
    'FINIK_CALLBACK_URL=\n# Finik webhook signature verification still requires the official public key integration.\n',
)

# Contract regression tests.
Path("apps/users/test_contracts.py").write_text(
    '''from django.test import override_settings\nfrom rest_framework.test import APITestCase\n\nfrom apps.users.models import User, UserProfile\n\n\nclass UserContractTests(APITestCase):\n    def setUp(self):\n        self.user = User.objects.create_user(\n            phone_number="996700000001", password="password", first_name="One"\n        )\n        self.other = User.objects.create_user(\n            phone_number="996700000002", password="password", first_name="Two"\n        )\n        UserProfile.objects.get_or_create(user=self.user)\n        self.other_profile, _ = UserProfile.objects.get_or_create(user=self.other)\n        self.client.force_authenticate(self.user)\n\n    def test_self_profile_patch_updates_current_user(self):\n        response = self.client.patch(\n            "/api/users/profile/", {"first_name": "Updated", "city": "Bishkek"}, format="json"\n        )\n        self.assertEqual(response.status_code, 200)\n        self.user.refresh_from_db()\n        self.assertEqual(self.user.first_name, "Updated")\n        self.assertEqual(self.user.city, "Bishkek")\n\n    def test_other_profile_is_not_readable(self):\n        response = self.client.get(f"/api/users/profile/{self.other_profile.id}")\n        self.assertEqual(response.status_code, 403)\n\n    @override_settings(ENABLE_DEBUG_OTP_ENDPOINT=False)\n    def test_debug_otp_endpoint_is_hidden_by_default(self):\n        self.client.force_authenticate(user=None)\n        response = self.client.post(\n            "/api/users/debug/request-code/", {"phone": "996700000003"}, format="json"\n        )\n        self.assertEqual(response.status_code, 404)\n''',
    encoding="utf-8",
)

Path("apps/delivery/test_contracts.py").write_text(
    '''from rest_framework.test import APITestCase\n\nfrom apps.delivery.models import Shipment, ShipmentStop\nfrom apps.users.models import User\n\n\nclass ShipmentContractTests(APITestCase):\n    def setUp(self):\n        self.client_user = User.objects.create_user(\n            phone_number="996710000001", password="password", role=User.Roles.CLIENT, first_name="Client"\n        )\n        self.carrier = User.objects.create_user(\n            phone_number="996710000002", password="password", role=User.Roles.CARRIER, first_name="Carrier"\n        )\n        self.shipment = Shipment.objects.create(\n            client=self.client_user, carrier=self.carrier, title="Test", status=Shipment.Status.ASSIGNED\n        )\n        ShipmentStop.objects.create(shipment=self.shipment, position=0, title="A", lat=42.87, lon=74.61)\n        ShipmentStop.objects.create(shipment=self.shipment, position=1, title="B", lat=42.88, lon=74.62)\n\n    def test_return_to_pending_releases_carrier(self):\n        self.client.force_authenticate(self.carrier)\n        response = self.client.post(\n            f"/api/delivery/shipments/{self.shipment.id}/set_status/",\n            {"status": Shipment.Status.PENDING},\n            format="json",\n        )\n        self.assertEqual(response.status_code, 200)\n        self.shipment.refresh_from_db()\n        self.assertEqual(self.shipment.status, Shipment.Status.PENDING)\n        self.assertIsNone(self.shipment.carrier_id)\n\n    def test_detail_contains_persisted_route_progress(self):\n        self.client.force_authenticate(self.carrier)\n        response = self.client.get(f"/api/delivery/shipments/{self.shipment.id}/")\n        self.assertEqual(response.status_code, 200)\n        self.assertIn("current_stop_index", response.data)\n        self.assertEqual(response.data["carrier_id"], self.carrier.id)\n\n    def test_nearby_feed_rejects_client_role(self):\n        self.client.force_authenticate(self.client_user)\n        response = self.client.get("/api/delivery/shipments/nearby/?lat=42.87&lon=74.61")\n        self.assertEqual(response.status_code, 403)\n\n    def test_delete_cancels_without_erasing_record(self):\n        self.client.force_authenticate(self.client_user)\n        response = self.client.delete(f"/api/delivery/shipments/{self.shipment.id}/")\n        self.assertEqual(response.status_code, 204)\n        self.shipment.refresh_from_db()\n        self.assertEqual(self.shipment.status, Shipment.Status.CANCELED)\n''',
    encoding="utf-8",
)

print("Backend hardening patch applied")
