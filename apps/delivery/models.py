from django.db import models
from django.conf import settings

class Bazar(models.Model):
    name = models.CharField(max_length=155, verbose_name='Базар')

    def __str__(self):
        return f"{self.name}"
    class Meta:
        verbose_name='Базар'
        verbose_name_plural='Базары'
class Container(models.Model):
    number = models.CharField(max_length=50)
    passage = models.CharField(max_length=50)
    title = models.CharField(max_length=150, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.title:
            self.title = f"Контейнер {self.number}, {self.passage}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
    

class CargoType(models.Model):
    name = models.CharField(max_length=50)
    description = models.CharField(max_length=200, blank=True)
    icon = models.ImageField(upload_to="cargo_icons/", null=True, blank=True)

    def __str__(self):
        return self.name
    

class Shipment(models.Model):
    STATUS_CHOICES = [
        ("pending", "В ожидании"),
        ("in_transit", "В пути"),
        ("completed", "Завершено"),
        ("canceled", "Отменено"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shipments")
    from_container = models.ForeignKey(Container, on_delete=models.PROTECT, related_name="shipments_from")
    to_container = models.ForeignKey(Container, on_delete=models.PROTECT, related_name="shipments_to")
    cargo_type = models.ForeignKey("CargoType", on_delete=models.PROTECT, related_name="shipments")
    quantity = models.PositiveIntegerField(default=1)
    fragile = models.BooleanField(default=False)
    description = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Посылка №{self.id} ({self.cargo_type.name}, {self.quantity} шт.)"
