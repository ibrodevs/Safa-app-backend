
import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Bazar',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=155, verbose_name='Базар')),
            ],
            options={
                'verbose_name': 'Базар',
                'verbose_name_plural': 'Базары',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='CourierSegment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64, unique=True, verbose_name='Название')),
                ('slug', models.SlugField(max_length=32, unique=True, verbose_name='Код')),
                ('is_active', models.BooleanField(default=True, verbose_name='Активен')),
                ('order', models.PositiveSmallIntegerField(default=0, verbose_name='Порядок в UI')),
                ('icon', models.CharField(blank=True, max_length=64, verbose_name='Иконка')),
                ('base_price', models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Посадка')),
                ('per_km_price', models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(0)], verbose_name='Цена за км')),
                ('min_fare', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Минималка')),
                ('fragile_pct', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=5, verbose_name='Хрупкость, %')),
                ('size_s_multiplier', models.DecimalField(decimal_places=2, default=Decimal('1.00'), max_digits=5, verbose_name='×S')),
                ('size_m_multiplier', models.DecimalField(decimal_places=2, default=Decimal('1.00'), max_digits=5, verbose_name='×M')),
                ('size_l_multiplier', models.DecimalField(decimal_places=2, default=Decimal('1.15'), max_digits=5, verbose_name='×L')),
                ('per_unit', models.BooleanField(default=True, verbose_name='Цена за единицу')),
            ],
            options={
                'verbose_name': 'Сегмент тарифа',
                'verbose_name_plural': 'Сегменты тарифа',
                'ordering': ['order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='Container',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.CharField(max_length=50, verbose_name='Номер')),
                ('passage', models.CharField(max_length=50, verbose_name='Проход')),
                ('title', models.CharField(blank=True, max_length=150, verbose_name='Название')),
                ('lat', models.DecimalField(decimal_places=6, max_digits=9, verbose_name='Широта (lat)')),
                ('lon', models.DecimalField(decimal_places=6, max_digits=9, verbose_name='Долгота (lon)')),
                ('bazar', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='containers', to='delivery.bazar', verbose_name='Базар')),
            ],
            options={
                'verbose_name': 'Точка (контейнер)',
                'verbose_name_plural': 'Точки (контейнеры)',
                'ordering': ['title'],
            },
        ),
        migrations.CreateModel(
            name='CourierPosition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lat', models.DecimalField(decimal_places=6, max_digits=9, verbose_name='Широта (lat)')),
                ('lon', models.DecimalField(decimal_places=6, max_digits=9, verbose_name='Долгота (lon)')),
                ('speed_kmh', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True, verbose_name='Скорость, км/ч')),
                ('heading', models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='Курс, °')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Обновлено')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='position', to=settings.AUTH_USER_MODEL, verbose_name='Пользователь')),
            ],
            options={
                'verbose_name': 'Позиция курьера',
                'verbose_name_plural': 'Позиции курьеров',
            },
        ),
        migrations.CreateModel(
            name='Shipment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=155, verbose_name='Название посылки')),
                ('size', models.CharField(choices=[('S', 'Маленькая'), ('M', 'Средняя'), ('L', 'Большая')], default='M', max_length=1, verbose_name='Размер')),
                ('quantity', models.PositiveIntegerField(default=1, verbose_name='Кол-во')),
                ('item_label', models.CharField(blank=True, max_length=32, verbose_name='Тип груза (UI)')),
                ('fragile', models.BooleanField(default=False, verbose_name='Хрупкая')),
                ('description', models.CharField(blank=True, max_length=255, verbose_name='Описание')),
                ('distance_km', models.DecimalField(decimal_places=2, default=0, max_digits=7, verbose_name='Дистанция, км')),
                ('estimated_fare', models.PositiveIntegerField(default=0, verbose_name='Предварительная стоимость')),
                ('final_fare', models.PositiveIntegerField(default=0, verbose_name='Итоговая стоимость')),
                ('status', models.CharField(choices=[('pending', 'В ожидании'), ('assigned', 'Назначен'), ('in_transit', 'В пути'), ('completed', 'Завершено'), ('canceled', 'Отменено')], default='pending', max_length=20, verbose_name='Статус')),
                ('current_stop_index', models.PositiveSmallIntegerField(default=1, verbose_name='Индекс цели')),
                ('eta_to_next_min', models.DecimalField(decimal_places=1, default=0, max_digits=6, verbose_name='ETA, мин')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создано')),
                ('carrier', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='shipments_as_carrier', to=settings.AUTH_USER_MODEL, verbose_name='Курьер')),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shipments_as_client', to=settings.AUTH_USER_MODEL, verbose_name='Клиент')),
                ('segment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='shipments', to='delivery.couriersegment', verbose_name='Тариф')),
            ],
            options={
                'verbose_name': 'Посылка',
                'verbose_name_plural': 'Посылки',
                'ordering': ('-created_at',),
            },
        ),
        migrations.CreateModel(
            name='ShipmentStop',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='Позиция')),
                ('container', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='shipment_stops', to='delivery.container', verbose_name='Точка')),
                ('shipment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stops', to='delivery.shipment', verbose_name='Посылка')),
            ],
            options={
                'verbose_name': 'Остановка',
                'verbose_name_plural': 'Остановки',
                'ordering': ['position'],
                'unique_together': {('shipment', 'position')},
            },
        ),
    ]
