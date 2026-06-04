"""
Encrypt secret fields on existing DataDestination rows in place.

Idempotent: the ``enc:`` prefix means already-encrypted values are skipped, and if the
cryptography lib is unavailable the helper is a no-op (rows stay plaintext and still
work via the decrypt passthrough).
"""
from django.db import migrations


def encrypt_existing(apps, schema_editor):
    from apps.core.crypto import encrypt_secrets

    DataDestination = apps.get_model('scraper', 'DataDestination')
    for dest in DataDestination.objects.all():
        new_config = encrypt_secrets(dest.config or {})
        if new_config != dest.config:
            dest.config = new_config
            dest.save(update_fields=['config'])


def decrypt_existing(apps, schema_editor):
    from apps.core.crypto import decrypt_secrets

    DataDestination = apps.get_model('scraper', 'DataDestination')
    for dest in DataDestination.objects.all():
        new_config = decrypt_secrets(dest.config or {})
        if new_config != dest.config:
            dest.config = new_config
            dest.save(update_fields=['config'])


class Migration(migrations.Migration):

    dependencies = [
        ("scraper", "0005_change_detection_and_alerts"),
    ]

    operations = [
        migrations.RunPython(encrypt_existing, decrypt_existing),
    ]
