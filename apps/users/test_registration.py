import pytest
from rest_framework.test import APIClient

from apps.users.models import User


@pytest.mark.django_db
def test_register_existing_phone_is_rejected():
    User.objects.create_user(
        phone_number="996700555111",
        password="oldpass123",
        first_name="Existing",
        is_verify=True,
    )

    client = APIClient()
    response = client.post(
        "/api/users/register/",
        {
            "phone_number": "996700555111",
            "first_name": "New Name",
            "role": User.Roles.CLIENT,
            "password": "newpass123",
            "password_confirm": "newpass123",
        },
        format="json",
    )

    assert response.status_code == 400
    assert User.objects.get(phone_number="996700555111").first_name == "Existing"
