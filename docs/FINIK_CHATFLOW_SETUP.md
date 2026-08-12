# Подключение Finik и Chatflow

Интеграции уже подключены к приложению. Для запуска нужны только реквизиты
мерчанта Finik, реквизиты Chatflow и публичный HTTPS-адрес backend.

## 1. Ключи Chatflow (backend)

В [Chatflow](https://app.chatflow.kz) подключите WhatsApp-канал, создайте n8n
integration для этого канала и скопируйте:

- API token из **Settings → API Access**;
- Flow ID из созданной n8n integration.

Добавьте в `DoGO/.env`:

```dotenv
CHATFLOW_BASE_URL=https://app.chatflow.kz
CHATFLOW_TOKEN=your-chatflow-api-token
CHATFLOW_FLOW_ID=your-chatflow-flow-id
CHATFLOW_TIMEOUT_SECONDS=15
```

`CHATFLOW_TOKEN` должен находиться только на backend. После изменения `.env`
перезапустите WSGI/ASGI-процесс.

Для старого кабинета `lk.chatflow.kz` поддерживается legacy-конфигурация:

```dotenv
CHATFLOW_BASE_URL=https://lk.chatflow.kz
CHATFLOW_TOKEN=your-legacy-token
CHATFLOW_FLOW_ID=
CHATFLOW_INSTANCE_ID=your-instance-id
```

Новый проект должен использовать `CHATFLOW_FLOW_ID`, а не legacy instance ID.

> В прежней версии проекта Chatflow token был записан прямо в исходный код.
> Его необходимо отозвать в Chatflow и выпустить новый: удаление строки из
> текущего кода не удаляет секрет из истории git.

## 2. Реквизиты Finik

У Finik запросите два значения для одного и того же окружения:

- **API client key** для Flutter SDK — используется приложением;
- **corporate account ID** — счёт, на который зачисляется платёж.

Это не RSA private key от Finik Web SDK. Документация Flutter-пакета:
[finik_sdk](https://pub.dev/packages/finik_sdk).

На backend добавьте account ID и тот же API client key, чтобы backend мог
проверять `transactionId` напрямую у Finik:

```dotenv
FINIK_ACCOUNT_ID=your-corporate-account-id
FINIK_API_KEY=your-flutter-api-client-key
FINIK_BETA=1
FINIK_CURRENCY=KGS
FINIK_TEST_AMOUNT=false
```

Для контролируемого теста всех платежей на 1 сом временно задайте:

```dotenv
FINIK_TEST_AMOUNT=1
```

Backend выставит Finik ровно 1 сом, проверит callback на 1 сом и запишет
тестовое начисление специалисту также от 1 сома. Значения `false`, `0`, `off`
или пустая строка отключают подмену и возвращают реальные итоговые цены.
После теста обязательно установите `FINIK_TEST_AMOUNT=false` и перезапустите
backend. Не оставляйте тестовую сумму включённой в рабочем приложении.

Backend сам формирует callback URL из публичного адреса запроса. Если внешний
домен отличается от того, который видит Django, задайте его явно:

```dotenv
FINIK_CALLBACK_URL=https://api.example.com/api/payments/finik/callback/
```

В production URL обязан быть публичным HTTPS URL без VPN/Basic Auth. Reverse
proxy должен передавать `Host` и `X-Forwarded-Proto: https`. Callback не требует
JWT: backend сверяет payment ID, уникальный Finik request ID, назначение
платежа (`shipment` или `amanat`), ID заказа либо пожертвования/кампании,
сумму и account ID, а затем подтверждает transaction ID через Finik GraphQL.
Только после ответа Finik заказ или пожертвование отмечается оплаченным;
повторная доставка callback обрабатывается идемпотентно.

## 3. Логика завершения заказа и начисления специалисту

Оплата теперь выполняется после оказания услуги:

1. специалист проходит маршрут и нажимает завершение работы;
2. backend фиксирует итоговую цену и переводит заказ в `awaiting_payment`;
3. клиент видит кнопку Finik и оплачивает именно зафиксированную сумму;
4. callback проверяется через API Finik;
5. в одной транзакции заказ получает `completed`, а специалисту создаётся
   единственное начисление суммы за вычетом комиссии.

Прямой переход специалиста в `completed` запрещён. Повторный callback или
повторное нажатие не создают второе начисление. Баланс и последние начисления
специалиста доступны авторизованному специалисту по
`GET /api/payments/carrier/wallet/`.

Пожертвование «Аманат» сначала создаётся со статусом `pending`. В сумму сбора
оно попадает только после проверенного callback Finik. Отмена окна Finik или
один лишь ответ Flutter SDK не считаются подтверждением платежа.

`CarrierSettlement` — внутренний бухгалтерский реестр приложения. Finik
зачисляет платёж клиента на корпоративный счёт `FINIK_ACCOUNT_ID`. Реальный
вывод с корпоративного счёта на банковский счёт/кошелёк специалиста потребует
отдельного payout-продукта провайдера и реквизитов специалиста; merchant API
приёма платежей сам по себе такой перевод не выполняет. У Finik для исходящих
операций существует отдельный
[Payments Gateway API](https://www.finik.kg/documentation/payments-gateway/):
для него нужны отдельный доступ, RSA-подпись и идентификатор получателя.

## 4. Ключ Finik во Flutter

Ключ больше не хранится в asset или git. Передайте его при запуске/сборке:

```bash
cd front
flutter run \
  --dart-define=DOGO_API_BASE_URL=https://api.example.com/api/ \
  --dart-define=FINIK_API_KEY=your-flutter-api-client-key \
  --dart-define=FINIK_BETA=true \
  --dart-define='FINIK_ITEM_NAME_EN=Safa delivery payment'
```

Для production используйте `FINIK_BETA=false` и production API client key:

```bash
flutter build apk --release \
  --dart-define=DOGO_API_BASE_URL=https://api.example.com/api/ \
  --dart-define=FINIK_API_KEY=your-production-api-client-key \
  --dart-define=FINIK_BETA=false
```

В CI сохраните `FINIK_API_KEY` как masked/protected secret и подставляйте его в
аргумент `--dart-define`. Flutter SDK работает на устройстве, поэтому используйте
только выданный Finik mobile/API client key с минимальными разрешениями.

## 5. Применение миграций и проверка

1. Выполните `python manage.py migrate`, затем `python manage.py check` и
   обязательно сделайте **Reload** Web app на PythonAnywhere. Миграция ставит
   ограничение базы данных: неоплаченный заказ физически нельзя сохранить как
   `completed`.
2. До сборки APK откройте диагностический endpoint:

   ```bash
   curl https://safabackend21.pythonanywhere.com/api/payments/finik/config/
   ```

   Должны быть `paymentFlowVersion: 3`,
   `paymentPurposes: ["shipment", "amanat"]`, `configured: true`, нужный `beta` и
   публичный HTTPS `callbackUrl`. `keyFingerprint` — безопасный короткий хеш,
   по которому приложение проверяет, что в APK и backend передан один и тот же
   ключ; сам ключ endpoint не раскрывает.
3. Собирайте APK только через `front/tool/build_apk.sh`. Скрипт до сборки
   обращается к endpoint выше и откажется создавать APK при старом backend,
   несовпавшем ключе/beta или неправильном callback URL. После сборки он
   печатает SHA-256 файла, чтобы не установить старый APK по ошибке.
4. Запросите OTP на номер `996XXXXXXXXX`: WhatsApp должен получить сообщение.
5. Создайте доставку с ненулевой ценой, примите её специалистом и завершите
   маршрут. Оба приложения должны показать `awaiting_payment`.
6. На стороне клиента откройте Finik, проверьте сумму и получателя, затем
   оплатите тестовым способом.
7. Finik должен вызвать `/api/payments/finik/callback/`; заказ получит
   `is_paid=true`, `status=completed`, а в кошельке специалиста появится одно
   начисление чистой суммы.
8. Отдельно сделайте пожертвование в разделе «Аманат»: сумма кампании должна
   увеличиться только после подтверждённого callback от Finik.

Сначала полностью проверьте beta-окружение. Не смешивайте beta API key с
production account ID.
