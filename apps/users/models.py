from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import RegexValidator
from django.utils import timezone

phone_re = RegexValidator(
    regex=r'^996\d{9}$',
    message="Формат телефона: 996XXXXXXXXX (Кыргызстан)."
)

class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, phone_number, password=None, **extra_fields):
        if not phone_number:
            raise ValueError("Phone number is required")
        user = self.model(phone_number=phone_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone_number, password, **extra_fields)

    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(phone_number, password, **extra_fields)


class User(AbstractUser):   
    username = None
    email = models.EmailField(blank=True, null=True)

    class Roles(models.TextChoices):
        CARRIER = "carrier", "Тачкист"
        CLIENT = "client", "Клиент"

    role = models.CharField(max_length=16, choices=Roles.choices, default=Roles.CLIENT)
    first_name = models.CharField(max_length=155, verbose_name='Имя')
    last_name  = models.CharField(max_length=155, verbose_name='Фамилия')
    phone_number = models.CharField(unique=True, max_length=13, validators=[phone_re])
    avatar = models.ImageField(upload_to='avatars/', verbose_name='Аватарка', null=True, blank=True)
    otp = models.CharField(max_length=6, verbose_name='Код отп', null=True,blank=True)
    is_verify = models.BooleanField(default=False)
    created_at   = models.DateTimeField(auto_now_add=True)
    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return f"{self.phone_number} ({self.get_role_display()})"


def kyc_upload_to(instance, filename):
    return f"kyc/{instance.user_id}/{filename}"


class CourierKYC(models.Model):
    class Status(models.TextChoices):
        PENDING  = "pending", "На проверке"
        APPROVED = "approved", "Подтверждён"
        REJECTED = "rejected", "Отклонён"

    user   = models.OneToOneField(User, on_delete=models.CASCADE, related_name="kyc")
    id_front = models.ImageField(upload_to=kyc_upload_to, blank=True, null=True)
    id_back  = models.ImageField(upload_to=kyc_upload_to, blank=True, null=True)
    selfie_id_card = models.ImageField(upload_to=kyc_upload_to, blank=True, null=True)
    status   = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    comment  = models.TextField(blank=True)
    checked_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"KYC {self.user_id}: {self.status}"



class ClientProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='client')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ClientProfile #{self.user_id}"


class CarrierProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='carrier')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"CarrierProfile #{self.user_id}"


