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
```

Backend сам формирует callback URL из публичного адреса запроса. Если внешний
домен отличается от того, который видит Django, задайте его явно:

```dotenv
FINIK_CALLBACK_URL=https://api.example.com/api/payments/finik/callback/
```

В production URL обязан быть публичным HTTPS URL без VPN/Basic Auth. Reverse
proxy должен передавать `Host` и `X-Forwarded-Proto: https`. Callback не требует
JWT: backend сверяет payment ID, уникальный Finik request ID, shipment ID,
сумму и account ID, а затем подтверждает transaction ID через Finik GraphQL.
Только после ответа Finik заказ отмечается оплаченным; повторная доставка
обрабатывается идемпотентно.

## 3. Ключ Finik во Flutter

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

## 4. Проверка после добавления ключей

1. Перезапустите backend и выполните `python manage.py check`.
2. Запросите OTP на номер `996XXXXXXXXX`: WhatsApp должен получить сообщение.
3. Создайте доставку с ненулевой ценой и откройте оплату Finik.
4. Убедитесь, что сумма и получатель верны, затем оплатите тестовым способом.
5. Finik должен вызвать `/api/payments/finik/callback/`; заказ получит
   `is_paid=true`, а приложение покажет успешную оплату после polling.

Сначала полностью проверьте beta-окружение. Не смешивайте beta API key с
production account ID.
