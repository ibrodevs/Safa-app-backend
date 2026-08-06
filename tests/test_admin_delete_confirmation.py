import pytest
from django.contrib.auth.models import Group
from django.urls import reverse


@pytest.mark.django_db
def test_bulk_delete_confirmation_has_submit_button(admin_client):
    """The admin bulk-delete confirmation must expose the final delete button."""
    group = Group.objects.create(name="Temporary admin test group")

    response = admin_client.post(
        reverse("admin:auth_group_changelist"),
        {
            "action": "delete_selected",
            "_selected_action": [str(group.pk)],
        },
    )

    assert response.status_code == 200
    assert b'name="post"' in response.content
    assert b'type="submit"' in response.content
