from __future__ import annotations

from pathlib import Path


def replace_required(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing expected block in {path}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Production configuration.
replace_required(
    "core/settings.py",
    'DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"\n',
    'DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"\n'
    'ENABLE_DEBUG_OTP_ENDPOINT = os.getenv("ENABLE_DEBUG_OTP_ENDPOINT", "0") == "1"\n',
)
replace_required(
    "core/settings.py",
    'OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))\nDEMO_OTP_CODE = os.getenv("DEMO_OTP_CODE", "").strip()\n',
    'OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))\n'
    'OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))\n'
    'DEMO_OTP_CODE = os.getenv("DEMO_OTP_CODE", "").strip()\n'
    'YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "").strip()\n',
)
replace_required(
    "core/settings.py",
    'for item in os.getenv("STATIC_OTP", "996555555555:1111").split(",")\n',
    'for item in os.getenv("STATIC_OTP", "").split(",")\n',
)

# Hide debug OTP and restrict profile reads.
replace_required(
    "apps/users/views.py",
    'from django.shortcuts import render\n',
    'from django.shortcuts import render\nfrom django.conf import settings\nfrom django.http import Http404\n',
)
replace_required(
    "apps/users/views.py",
    '''class DebugRequestCodeView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = RequestCodeSerializer

    def post(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
''',
    '''class DebugRequestCodeView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = RequestCodeSerializer

    def post(self, request, *args, **kwargs):
        if not getattr(settings, "ENABLE_DEBUG_OTP_ENDPOINT", False):
            raise Http404
        ser = self.get_serializer(data=request.data)
''',
)
replace_required(
    "apps/users/views.py",
    '''        if pk is None:
            return self._self_profile()            
        return self.get_queryset().get(pk=pk)     
''',
    '''        if pk is None:
            return self._self_profile()
        obj = self.get_queryset().get(pk=pk)
        if not (self.request.user.is_staff or obj.user_id == self.request.user.id):
            raise PermissionDenied("profile_access_denied")
        return obj
''',
)

# Persist enough data to restore active orders after app restart.
replace_required(
    "apps/delivery/serializer.py",
    '''            "service_type",
            "description",
            "stops",
''',
    '''            "service_type",
            "description",
            "client_id",
            "carrier_id",
            "current_stop_index",
            "stops",
''',
)

# Shipment lifecycle invariants.
replace_required(
    "apps/delivery/views.py",
    'from apps.notification.events import notify_shipment_status\n',
    'from apps.notification.events import notify_shipment_offer_for_carrier, notify_shipment_status\n',
)
replace_required(
    "apps/delivery/views.py",
    '''def _increment_carrier_rating(shipment: Shipment) -> None:
    carrier = shipment.carrier
    if not carrier:
        return
    if getattr(carrier, "role", None) != User.Roles.CARRIER:
        return
    try:
        profile, _ = UserProfile.objects.get_or_create(user=carrier)
        profile.rate = int(profile.rate or 0) + 1
        profile.client_rate_count = str(int(profile.client_rate_count or 0) + 1)
        profile.save(update_fields=["rate", "client_rate_count"])
    except Exception as e:
        logger.exception(
            "increment_carrier_rating_failed", 
            extra={"shipment_id": shipment.id, "carrier_id": carrier.id, "error": str(e)}
        )
''',
    '''def _increment_carrier_rating(shipment: Shipment) -> None:
    if shipment.rating_applied:
        return
    try:
        with transaction.atomic():
            locked = (
                Shipment.objects.select_for_update()
                .select_related("carrier")
                .get(pk=shipment.pk)
            )
            if locked.rating_applied:
                shipment.rating_applied = True
                return
            carrier = locked.carrier
            if not carrier or getattr(carrier, "role", None) != User.Roles.CARRIER:
                return
            profile, _ = UserProfile.objects.select_for_update().get_or_create(user=carrier)
            profile.rate = int(profile.rate or 0) + 1
            profile.client_rate_count = str(int(profile.client_rate_count or 0) + 1)
            profile.save(update_fields=["rate", "client_rate_count"])
            locked.rating_applied = True
            locked.save(update_fields=["rating_applied"])
            shipment.rating_applied = True
    except Exception as e:
        logger.exception(
            "increment_carrier_rating_failed",
            extra={"shipment_id": shipment.id, "carrier_id": shipment.carrier_id, "error": str(e)},
        )
''',
)
replace_required(
    "apps/delivery/views.py",
    '''            shipment = serializer.save()
            _broadcast(shipment)
            logger.info(
''',
    '''            shipment = serializer.save()
            _broadcast(shipment)
            notify_shipment_offer_for_carrier(shipment)
            logger.info(
''',
)
replace_required(
    "apps/delivery/views.py",
    '''        if new_status == Shipment.Status.COMPLETED:
            _complete_shipment_if_needed(s)
        else:
            s.status = new_status
            s.save(update_fields=["status"])
            if new_status != old_status:
                notify_shipment_status(s)
''',
    '''        if new_status == Shipment.Status.COMPLETED:
            _complete_shipment_if_needed(s)
            _increment_carrier_rating(s)
            notify_shipment_status(s)
        else:
            s.status = new_status
            update_fields = ["status"]
            if new_status == Shipment.Status.PENDING:
                s.carrier = None
                update_fields.append("carrier")
            s.save(update_fields=update_fields)
            if new_status != old_status:
                notify_shipment_status(s)
''',
)
replace_required(
    "apps/delivery/views.py",
    '''    def nearby(self, request):
        rid = _rid(request)
        try:
''',
    '''    def nearby(self, request):
        rid = _rid(request)
        if getattr(request.user, "role", None) != User.Roles.CARRIER:
            return response.Response({"detail": "only_for_carrier"}, status=status.HTTP_403_FORBIDDEN)
        try:
''',
)
replace_required(
    "apps/delivery/views.py",
    '''    @extend_schema(
        tags=["Shipments"],
        summary="Курьер принимает посылку",
''',
    '''    def destroy(self, request, *args, **kwargs):
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
''',
)

# Repair offer notifications for the current shipment schema.
replace_required(
    "apps/notification/events.py",
    '    body = f"{shipment.title} · {shipment.estimated_fare} с"\n',
    '    body = f"{shipment.title} · {shipment.estimated_fare} сом"\n',
)
replace_required(
    "apps/notification/events.py",
    '''        "segment": shipment.segment.slug,
        "segment_name": shipment.segment.name,
        "estimated_fare": str(shipment.estimated_fare),
        "size": shipment.size,
        "quantity": str(shipment.quantity),
        "fragile": "1" if shipment.fragile else "0",
''',
    '''        "service_type": shipment.service_type,
        "estimated_fare": str(shipment.estimated_fare),
''',
)
replace_required(
    "apps/notification/events.py",
    '''    if shipment.carrier_id:
        _send_to_user(
            shipment.carrier_id,
            data,
            ttl="15s",
            collapse_key=collapse_key,
        )
''',
    '''    carrier_ids = (
        FCMToken.objects.filter(user__role=User.Roles.CARRIER, is_active=True)
        .values_list("user_id", flat=True)
        .distinct()
    )
    for carrier_id in carrier_ids:
        if carrier_id == shipment.client_id:
            continue
        _send_to_user(carrier_id, dict(data), ttl="15s", collapse_key=collapse_key)
''',
)

# Safe deployment example.
replace_required(".env.example", "DJANGO_DEBUG=1\n", "DJANGO_DEBUG=0\nENABLE_DEBUG_OTP_ENDPOINT=0\n")
replace_required(
    ".env.example",
    "OTP_TTL_SECONDS=300\nSTATIC_OTP=996555555555:1111\n",
    "OTP_TTL_SECONDS=300\nOTP_MAX_ATTEMPTS=5\nSTATIC_OTP=\nGOOGLE_MAPS_BROWSER_API_KEY=\n",
)
replace_required(
    ".env.example",
    "FINIK_CALLBACK_URL=\n",
    "FINIK_CALLBACK_URL=\n# Production Finik requires official signed-webhook verification.\n",
)

Path("apps/users/test_contracts.py").write_text(
    '''from django.test import override_settings
from rest_framework.test import APITestCase

from apps.users.models import User, UserProfile


class UserContractTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone_number="996700000001", password="password", first_name="One")
        self.other = User.objects.create_user(phone_number="996700000002", password="password", first_name="Two")
        UserProfile.objects.get_or_create(user=self.user)
        self.other_profile, _ = UserProfile.objects.get_or_create(user=self.other)
        self.client.force_authenticate(self.user)

    def test_self_profile_patch_updates_current_user(self):
        response = self.client.patch("/api/users/profile/", {"first_name": "Updated", "city": "Bishkek"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")
        self.assertEqual(self.user.city, "Bishkek")

    def test_other_profile_is_not_readable(self):
        response = self.client.get(f"/api/users/profile/{self.other_profile.id}")
        self.assertEqual(response.status_code, 403)

    @override_settings(ENABLE_DEBUG_OTP_ENDPOINT=False)
    def test_debug_otp_endpoint_is_hidden_by_default(self):
        self.client.force_authenticate(user=None)
        response = self.client.post("/api/users/debug-code/", {"phone": "996700000003"}, format="json")
        self.assertEqual(response.status_code, 404)
''',
    encoding="utf-8",
)

Path("apps/delivery/test_contracts.py").write_text(
    '''from rest_framework.test import APITestCase

from apps.delivery.models import Shipment, ShipmentStop
from apps.users.models import User


class ShipmentContractTests(APITestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(phone_number="996710000001", password="password", role=User.Roles.CLIENT, first_name="Client")
        self.carrier = User.objects.create_user(phone_number="996710000002", password="password", role=User.Roles.CARRIER, first_name="Carrier")
        self.shipment = Shipment.objects.create(client=self.client_user, carrier=self.carrier, title="Test", status=Shipment.Status.ASSIGNED)
        ShipmentStop.objects.create(shipment=self.shipment, position=0, title="A", lat=42.87, lon=74.61)
        ShipmentStop.objects.create(shipment=self.shipment, position=1, title="B", lat=42.88, lon=74.62)

    def test_return_to_pending_releases_carrier(self):
        self.client.force_authenticate(self.carrier)
        response = self.client.post(f"/api/delivery/shipments/{self.shipment.id}/set_status/", {"status": Shipment.Status.PENDING}, format="json")
        self.assertEqual(response.status_code, 200)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, Shipment.Status.PENDING)
        self.assertIsNone(self.shipment.carrier_id)

    def test_detail_contains_persisted_route_progress(self):
        self.client.force_authenticate(self.carrier)
        response = self.client.get(f"/api/delivery/shipments/{self.shipment.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("current_stop_index", response.data)
        self.assertEqual(response.data["carrier_id"], self.carrier.id)

    def test_nearby_feed_rejects_client_role(self):
        self.client.force_authenticate(self.client_user)
        response = self.client.get("/api/delivery/shipments/nearby/?lat=42.87&lon=74.61")
        self.assertEqual(response.status_code, 403)

    def test_delete_cancels_without_erasing_record(self):
        self.client.force_authenticate(self.client_user)
        response = self.client.delete(f"/api/delivery/shipments/{self.shipment.id}/")
        self.assertEqual(response.status_code, 204)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.status, Shipment.Status.CANCELED)
''',
    encoding="utf-8",
)

print("Backend hardening patch v2 applied")
