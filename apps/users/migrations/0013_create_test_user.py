from django.db import migrations

def create_test_user(apps, schema_editor):
    User = apps.get_model('users', 'User')
    User.objects.get_or_create(
        phone_number='996555555555',
        defaults={
            'role': 'client',
            'is_verify': True,
            'is_active': True,
            'otp': '1111',
            'first_name': 'Test',
            'last_name': 'User',
        }
    )

class Migration(migrations.Migration):

    dependencies = [
        ('users', '0012_userprofile_client_rate_count'),
    ]

    operations = [
        migrations.RunPython(create_test_user),
    ]
