from django.test import override_settings
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
