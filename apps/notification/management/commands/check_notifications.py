from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.users.models import User
from apps.notification.events import _send_to_user
from apps.notification.fcm_client import fcm_config_status
from apps.notification.models import FCMToken


class Command(BaseCommand):
    help = "Проверяет конфигурацию FCM, активные токены и при необходимости отправляет тестовый push."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=None)
        parser.add_argument(
            "--send-test",
            action="store_true",
            help="Отправить тестовое уведомление пользователю из --user-id.",
        )

    def handle(self, *args, **options):
        status = fcm_config_status()
        configured = bool(status["configured"])
        self.stdout.write(
            self.style.SUCCESS("FCM configuration: OK")
            if configured
            else self.style.ERROR(f"FCM configuration: ERROR — {status['error']}")
        )
        self.stdout.write(f"Project ID: {status['project_id'] or '—'}")
        self.stdout.write(
            "Service account file: "
            + ("found" if status["service_account_exists"] else "missing")
        )

        active_tokens = FCMToken.objects.filter(is_active=True, user__is_active=True)
        self.stdout.write(f"Active device tokens: {active_tokens.count()}")
        self.stdout.write(
            "Clients with tokens: "
            + str(
                active_tokens.filter(user__role=User.Roles.CLIENT)
                .values("user_id")
                .distinct()
                .count()
            )
        )
        self.stdout.write(
            "Cart specialists with tokens: "
            + str(
                active_tokens.filter(
                    user__role=User.Roles.CARRIER,
                    user__specialist_type=User.SpecialistType.CART,
                )
                .values("user_id")
                .distinct()
                .count()
            )
        )
        self.stdout.write(
            "Delivery specialists with tokens: "
            + str(
                active_tokens.filter(
                    user__role=User.Roles.CARRIER,
                    user__specialist_type=User.SpecialistType.DELIVERY,
                )
                .values("user_id")
                .distinct()
                .count()
            )
        )

        if not options["send_test"]:
            return

        user_id = options["user_id"]
        if not user_id:
            raise CommandError("Для --send-test укажите --user-id <ID>.")

        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is None:
            raise CommandError(f"Активный пользователь id={user_id} не найден.")

        app = "carrier" if user.role == User.Roles.CARRIER else "client"
        has_token = FCMToken.objects.filter(user=user, is_active=True).exists()
        if not has_token:
            raise CommandError(
                f"У пользователя id={user_id} нет активного FCM-токена. "
                "Сначала войдите в приложение на его устройстве."
            )

        data = {
            "app": app,
            "type": "system_test",
            "title": "Проверка уведомлений Safa",
            "body": "Если вы видите это сообщение, push-уведомления работают.",
            "channel": "system",
            "deep_link": f"app://{app}/home",
            "silent": "0",
        }
        delivered = _send_to_user(user.id, data, ttl="120s")
        if delivered:
            self.stdout.write(
                self.style.SUCCESS(
                    f"TEST PUSH: Firebase accepted at least one device for user {user.id}."
                )
            )
        else:
            raise CommandError(
                "TEST PUSH failed: Firebase did not accept the push. "
                "Проверьте конфигурацию FCM и активность токена."
            )
