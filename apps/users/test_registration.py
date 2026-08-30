import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.users.models import CourierKYC, User


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


@pytest.mark.django_db
@override_settings(DEBUG=True, STATIC_OTP_CODE="1111")
def test_static_otp_never_auto_approves_specialist():
    image_data = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(image_data, format="PNG")
    image = image_data.getvalue()
    response = APIClient().post(
        "/api/users/register/",
        {
            "phone_number": "996700555112",
            "first_name": "Pending specialist",
            "role": User.Roles.CARRIER,
            "specialist_type": User.SpecialistType.DELIVERY,
            "password": "secret123",
            "password_confirm": "secret123",
            "id_front": SimpleUploadedFile(
                "front.png", image, content_type="image/png"
            ),
            "id_back": SimpleUploadedFile(
                "back.png", image, content_type="image/png"
            ),
        },
        format="multipart",
    )

    assert response.status_code == 201
    carrier = User.objects.get(phone_number="996700555112")
    assert carrier.is_verify is True
    assert carrier.is_active is False
    assert carrier.kyc.status == CourierKYC.Status.PENDING


@pytest.mark.django_db
def test_specialist_id_photo_exceeding_10mb_is_rejected():
    image_data = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(image_data, format="JPEG")
    small_image = image_data.getvalue()

    # Valid JPEG image padded to > 10 MB (10 MB + 1 KB)
    large_image = small_image + b"\x00" * (10 * 1024 * 1024 + 1024)

    client = APIClient()
    response = client.post(
        "/api/users/register/",
        {
            "phone_number": "996700555113",
            "first_name": "Oversized Front",
            "role": User.Roles.CARRIER,
            "specialist_type": User.SpecialistType.DELIVERY,
            "password": "secret123",
            "password_confirm": "secret123",
            "id_front": SimpleUploadedFile("front.jpg", large_image, content_type="image/jpeg"),
            "id_back": SimpleUploadedFile("back.jpg", small_image, content_type="image/jpeg"),
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert "10 МБ" in str(response.json())


@pytest.mark.django_db
def test_specialist_selfie_exceeding_10mb_is_rejected():
    from apps.users.enrollment import make_kyc_enrollment_token

    carrier = User.objects.create_user(
        phone_number="996700555114",
        password="secret123",
        first_name="Carrier",
        role=User.Roles.CARRIER,
        is_verify=True,
    )
    token = make_kyc_enrollment_token(carrier)

    image_data = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(image_data, format="JPEG")
    small_image = image_data.getvalue()
    large_image = small_image + b"\x00" * (10 * 1024 * 1024 + 1024)

    client = APIClient()
    response = client.post(
        "/api/users/selfie/",
        {
            "phone": "996700555114",
            "kyc_token": token,
            "selfie_id_card": SimpleUploadedFile("selfie.jpg", large_image, content_type="image/jpeg"),
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert "10 МБ" in str(response.json())
