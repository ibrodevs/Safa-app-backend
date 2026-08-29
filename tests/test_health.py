import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_is_public_and_checks_database(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "channels": "ok"}
