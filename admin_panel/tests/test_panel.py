import json
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from apps.delivery.models import AmanatCampaign, AmanatCategory, Bazar, Container, DeliveryDistrict, Passage, Shipment
from apps.payments.models import PaymentAttempt
from apps.notification.models import Notification
from apps.users.models import CourierKYC, User


class PanelAccessTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            phone_number="996700000001",
            password="test-password",
            first_name="Admin",
            is_staff=True,
        )

    def test_anonymous_user_is_redirected_to_panel_login(self):
        response = self.client.get(reverse("admin_panel:dashboard"))
        self.assertRedirects(
            response,
            "/panel/login/?next=%2Fpanel%2F",
            fetch_redirect_response=False,
        )

    def test_non_staff_user_gets_forbidden(self):
        user = User.objects.create_user(
            phone_number="996700000002",
            password="test-password",
            first_name="Client",
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("admin_panel:dashboard")).status_code, 403)

    def test_all_primary_pages_render_for_staff(self):
        self.client.force_login(self.staff)
        urls = (
            reverse("admin_panel:dashboard"),
            reverse("admin_panel:orders"),
            reverse("admin_panel:users"),
            reverse("admin_panel:couriers"),
            reverse("admin_panel:kyc_list"),
            reverse("admin_panel:map_list"),
            reverse("admin_panel:bazars"),
            reverse("admin_panel:districts"),
            reverse("admin_panel:passages"),
            reverse("admin_panel:containers"),
            reverse("admin_panel:tariffs"),
            reverse("admin_panel:finance"),
            reverse("admin_panel:amanat"),
            reverse("admin_panel:amanat_create"),
            reverse("admin_panel:settings"),
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class PanelWorkflowTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            phone_number="996700000010",
            password="test-password",
            first_name="Admin",
            is_staff=True,
        )
        self.carrier = User.objects.create_user(
            phone_number="996700000011",
            password="test-password",
            first_name="Courier",
            role=User.Roles.CARRIER,
            is_active=False,
        )
        self.kyc = CourierKYC.objects.create(user=self.carrier)
        self.client.force_login(self.staff)

    def _shipment(self):
        client = User.objects.create_user(
            phone_number="996700000012",
            password="test-password",
            first_name="Customer",
        )
        return Shipment.objects.create(client=client, title="Документы")

    def test_kyc_approval_uses_shared_access_rules(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("admin_panel:kyc_approve", args=(self.kyc.pk,)),
                {"comment": "Документы проверены"},
            )
        self.assertEqual(response.status_code, 302)
        self.carrier.refresh_from_db()
        self.kyc.refresh_from_db()
        self.assertEqual(self.kyc.status, CourierKYC.Status.APPROVED)
        self.assertTrue(self.carrier.is_active)
        self.assertTrue(self.carrier.is_verify)
        notification = Notification.objects.get(
            user=self.carrier,
            type="kyc_status",
        )
        self.assertEqual(notification.data["status"], CourierKYC.Status.APPROVED)

    def test_mutating_endpoints_reject_get(self):
        self.assertEqual(
            self.client.get(reverse("admin_panel:kyc_approve", args=(self.kyc.pk,))).status_code,
            405,
        )

    def test_map_save_runs_existing_validation(self):
        bazar = Bazar.objects.create(name="Test bazar")
        response = self.client.post(
            reverse("admin_panel:map_save", args=(bazar.pk,)),
            data=json.dumps({"geojson": {"type": "FeatureCollection", "features": []}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_map_editor_and_data_details_render(self):
        bazar = Bazar.objects.create(name="Dordoi")
        shipment = self._shipment()
        payment = PaymentAttempt.objects.create(
            shipment=shipment,
            amount=150,
            finik_request_id="test-panel-payment",
        )
        category = AmanatCategory.objects.create(name="Помощь", slug="help")
        campaign = AmanatCampaign.objects.create(
            category=category,
            title="Поможем семье",
            description="Описание",
            needed_amount=1000,
        )
        urls = (
            reverse("admin_panel:map_editor", args=(bazar.pk,)),
            reverse("admin_panel:order_detail", args=(shipment.pk,)),
            reverse("admin_panel:order_quick", args=(shipment.pk,)),
            reverse("admin_panel:user_detail", args=(shipment.client_id,)),
            reverse("admin_panel:kyc_detail", args=(self.kyc.pk,)),
            reverse("admin_panel:payment_detail", args=(payment.pk,)),
            reverse("admin_panel:amanat_detail", args=(campaign.pk,)),
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        map_response = self.client.get(
            reverse("admin_panel:map_editor", args=(bazar.pk,))
        )
        self.assertContains(map_response, 'id="market-map-undo"')
        self.assertContains(map_response, "Ctrl+Z")
        self.assertContains(map_response, "Что нужно создать?")
        self.assertNotContains(map_response, 'id="market-feature-list"')
        self.assertContains(map_response, 'data-container-size-step="width"')

    def test_staff_can_manage_delivery_catalogs(self):
        district_response = self.client.post(
            reverse("admin_panel:district_create"),
            {"name": "Ленинский", "per_km_price": "15.00", "is_active": "on"},
        )
        self.assertEqual(district_response.status_code, 302)
        district = DeliveryDistrict.objects.get(name="Ленинский")

        bazar_response = self.client.post(
            reverse("admin_panel:catalog_bazar_create"),
            {"name": "Ошский", "district_tariff": district.pk, "fixed_price": "100"},
        )
        self.assertEqual(bazar_response.status_code, 302)
        bazar = Bazar.objects.get(name="Ошский")

        passage_response = self.client.post(
            reverse("admin_panel:passage_create"),
            {"bazar": bazar.pk, "number": "7"},
        )
        self.assertEqual(passage_response.status_code, 302)
        passage = Passage.objects.get(bazar=bazar, number="7")

        container_response = self.client.post(
            reverse("admin_panel:container_create"),
            {
                "passage": passage.pk,
                "number": "701",
                "title": "Тест",
                "lat": "42.870000",
                "lon": "74.610000",
                "is_active": "on",
            },
        )
        self.assertEqual(container_response.status_code, 302)
        self.assertTrue(Container.objects.filter(passage=passage, number="701").exists())

    def test_awaiting_payment_order_detail_auto_refreshes_until_paid(self):
        shipment = self._shipment()
        shipment.status = Shipment.Status.AWAITING_PAYMENT
        shipment.save(update_fields=["status"])

        response = self.client.get(
            reverse("admin_panel:order_detail", args=(shipment.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "refreshPaymentState")

    @patch("admin_panel.views.finance.finik_item_matches_attempt", return_value=True)
    @patch("admin_panel.views.finance.find_finik_item_by_request_id")
    def test_staff_can_reconcile_lost_finik_callback(self, find_item, _matches):
        shipment = self._shipment()
        shipment.carrier = self.carrier
        shipment.status = Shipment.Status.AWAITING_PAYMENT
        shipment.final_fare = 10
        shipment.save(update_fields=["carrier", "status", "final_fare"])
        payment = PaymentAttempt.objects.create(
            shipment=shipment,
            amount=10,
            finik_request_id="lost-request-id",
        )
        find_item.return_value = {
            "id": "recovered-item-id",
            "transactionId": "recovered-transaction-id",
        }

        detail = self.client.get(
            reverse("admin_panel:payment_detail", args=(payment.pk,))
        )
        self.assertContains(detail, "Проверить в Finik")
        self.assertNotContains(detail, "window.setTimeout(check")

        response = self.client.post(
            reverse("admin_panel:payment_reconcile", args=(payment.pk,)),
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["paid"])
        payment.refresh_from_db()
        shipment.refresh_from_db()
        self.assertEqual(payment.status, PaymentAttempt.Status.SUCCEEDED)
        self.assertEqual(payment.finik_item_id, "recovered-item-id")
        self.assertEqual(payment.finik_transaction_id, "recovered-transaction-id")
        self.assertTrue(shipment.is_paid)
        self.assertEqual(shipment.status, Shipment.Status.COMPLETED)

    @patch("apps.delivery.operations.broadcast_shipment")
    @patch("apps.delivery.operations.notify_shipment_status")
    def test_order_cancel_uses_post_action(self, notify, broadcast):
        shipment = self._shipment()
        response = self.client.post(
            reverse("admin_panel:order_cancel", args=(shipment.pk,))
        )
        self.assertRedirects(
            response,
            reverse("admin_panel:order_detail", args=(shipment.pk,)),
            fetch_redirect_response=False,
        )
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, Shipment.Status.CANCELED)
        notify.assert_called_once()
        broadcast.assert_called_once()

    def test_post_actions_are_csrf_protected(self):
        shipment = self._shipment()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        response = csrf_client.post(
            reverse("admin_panel:order_cancel", args=(shipment.pk,))
        )
        self.assertEqual(response.status_code, 403)

    def test_publish_rejects_map_without_bazar_boundary(self):
        bazar = Bazar.objects.create(name="Empty map")
        response = self.client.post(
            reverse("admin_panel:map_publish", args=(bazar.pk,)),
            data=json.dumps({"geojson": {"type": "FeatureCollection", "features": []}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_global_search_requires_two_characters(self):
        response = self.client.get(reverse("admin_panel:search"), {"q": "1"})
        self.assertEqual(response.json(), {"groups": []})

    def test_staff_can_create_and_edit_user(self):
        response = self.client.post(
            reverse("admin_panel:user_create"),
            {
                "phone_number": "996700000099",
                "first_name": "New client",
                "role": User.Roles.CLIENT,
                "specialist_type": "",
                "city": "Бишкек",
                "is_active": "on",
            },
        )
        person = User.objects.get(phone_number="996700000099")
        self.assertRedirects(
            response,
            reverse("admin_panel:user_detail", args=(person.pk,)),
            fetch_redirect_response=False,
        )
        self.assertFalse(person.has_usable_password())
        response = self.client.post(
            reverse("admin_panel:user_edit", args=(person.pk,)),
            {
                "phone_number": person.phone_number,
                "first_name": "Updated client",
                "role": User.Roles.CLIENT,
                "specialist_type": "",
                "city": "Ош",
                "is_active": "on",
                "is_verify": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        person.refresh_from_db()
        self.assertEqual(person.first_name, "Updated client")
        self.assertEqual(person.city, "Ош")

    def test_staff_can_create_order_with_route(self):
        customer = User.objects.create_user(
            phone_number="996700000098",
            first_name="Order client",
        )
        response = self.client.post(
            reverse("admin_panel:order_create"),
            {
                "title": "Новый заказ",
                "service_type": Shipment.ServiceType.DELIVERY,
                "description": "Тестовый маршрут",
                "client": customer.pk,
                "carrier": "",
                "status": Shipment.Status.PENDING,
                "final_fare": 0,
                "stops-TOTAL_FORMS": 2,
                "stops-INITIAL_FORMS": 0,
                "stops-MIN_NUM_FORMS": 0,
                "stops-MAX_NUM_FORMS": 1000,
                "stops-0-container": "",
                "stops-0-title": "Точка А",
                "stops-0-lat": "42.870000",
                "stops-0-lon": "74.610000",
                "stops-0-ORDER": 0,
                "stops-1-container": "",
                "stops-1-title": "Точка Б",
                "stops-1-lat": "42.880000",
                "stops-1-lon": "74.620000",
                "stops-1-ORDER": 1,
            },
        )
        shipment = Shipment.objects.get(title="Новый заказ")
        self.assertRedirects(
            response,
            reverse("admin_panel:order_detail", args=(shipment.pk,)),
            fetch_redirect_response=False,
        )
        self.assertEqual(shipment.stops.count(), 2)
        self.assertGreater(shipment.estimated_fare, 0)
        self.assertEqual(
            self.client.get(reverse("admin_panel:order_edit", args=(shipment.pk,))).status_code,
            200,
        )
