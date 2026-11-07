# Руководство по запуску и использованию RabbitMQ проекта

## Обзор проекта

Этот проект представляет собой систему обмена сообщениями на базе RabbitMQ с тремя основными компонентами:

- **Producer (Отправитель)** - сервис для отправки сообщений в очереди RabbitMQ
- **Consumer (Получатель)** - сервис для получения и обработки сообщений из очередей
- **RabbitMQ** - брокер сообщений, который обеспечивает хранение и маршрутизацию сообщений

Система использует Docker и Docker Compose для контейнеризации и оркестрации сервисов.

## Требования

- Git
- Docker
- Docker Compose с поддержкой `docker compose up --wait`
- Python 3 на компьютере для интеграционной проверки

## Запуск проекта

### Шаг 1: Клонирование репозитория
```
git clone https://github.com/ik-slyadnev/rabbit_mq_example.git
cd rabbit_mq_example
```

### Шаг 2: Запуск контейнеров
```
docker compose up -d --build --wait
```

Эта команда запустит три контейнера:
- *rabbitmq-trainer* - сервер RabbitMQ с Management UI
- *rabbitmq-producer* - сервис для отправки сообщений
- *rabbitmq-consumer* - сервис для получения и обработки сообщений

### Шаг 3: Проверка статуса контейнеров
```
docker compose ps
```
Все контейнеры должны быть в статусе "Up".

## Как использовать систему

### Подключение к RabbitMQ Management UI

1. Откройте браузер и перейдите по адресу: http://localhost:15672/
2. Введите учетные данные:
   - Логин: *admin*
   - Пароль: *admin*

Через Management UI вы можете:
- Просматривать очереди, обменники и сообщения
- Создавать новые очереди и обменники
- Отправлять и получать сообщения вручную
- Мониторить статистику и метрики

### Работа с Producer API

Producer API предоставляет следующие эндпоинты:

#### 1. Отправка сообщения в очередь
```
curl -X POST http://localhost:5002/send -H "Content-Type: application/json" -d '{
  "queue": "my_queue",
  "message": "Привет, это тестовое сообщение!"
}'
```

#### 2. Создание обменника
```
curl -X POST http://localhost:5002/create_exchange -H "Content-Type: application/json" -d '{
  "exchange": "my_exchange",
  "type": "direct"
}'
```

### Работа с Consumer API

Consumer API предоставляет следующие эндпоинты:

#### 1. Создание очереди и привязка к обменнику
```
curl -X POST http://localhost:5001/bind_queue -H "Content-Type: application/json" -d '{
  "queue": "my_queue",
  "exchange": "my_exchange",
  "routing_key": "my_routing_key"
}'
```

Перед привязкой создайте обменник через `/create_exchange`, как показано выше
Для отправки через этот обменник укажите тот же routing key:

```bash
curl -X POST http://localhost:5002/send -H "Content-Type: application/json" -d '{
  "exchange": "my_exchange",
  "routing_key": "my_routing_key",
  "message": "Сообщение через обменник"
}'
```

Если вы хотите создать очередь без привязки к обменнику, просто не указывайте поле exchange:
```
curl -X POST http://localhost:5001/bind_queue -H "Content-Type: application/json" -d '{
  "queue": "my_queue"
}'
```

#### 2. Запуск потребителя для очереди
```
curl -X POST http://localhost:5001/start_consumer/my_queue
```

#### 3. Получение списка сообщений из очереди
```
curl http://localhost:5001/messages/my_queue
```

#### 4. Очистка списка полученных сообщений
```
curl -X POST http://localhost:5001/clear_messages/my_queue
```

#### 5. Получение списка активных очередей
```
curl http://localhost:5001/active_queues
```

#### 6. Остановка потребителя для очереди
```
curl -X POST http://localhost:5001/stop_consumer/my_queue
```

#### 7. Очистка очереди
```
curl -X POST http://localhost:5001/purge_queue/my_queue
```

## Базовый сценарий использования

1. Создайте очередь:
```
curl -X POST http://localhost:5001/bind_queue -H "Content-Type: application/json" -d '{
  "queue": "test_queue"
}'
```

2. Запустите потребителя для этой очереди:
```
curl -X POST http://localhost:5001/start_consumer/test_queue
```

3. Отправьте сообщение в очередь:
```
curl -X POST http://localhost:5002/send -H "Content-Type: application/json" -d '{
  "queue": "test_queue",
  "message": "Привет, RabbitMQ!"
}'
```

4. Проверьте, что сообщение было получено:
```
curl http://localhost:5001/messages/test_queue
```

## Тестирование сценария с остановкой и запуском контейнера

1. Создайте очередь и запустите потребителя:
```
curl -X POST http://localhost:5001/bind_queue -H "Content-Type: application/json" -d '{"queue": "test_queue"}'
curl -X POST http://localhost:5001/start_consumer/test_queue
```

2. Остановите контейнер consumer:
```
docker stop rabbitmq-consumer
```

3. Отправьте сообщение в очередь:
```
curl -X POST http://localhost:5002/send -H "Content-Type: application/json" -d '{"queue": "test_queue", "message": "Сообщение отправлено при остановленном потребителе"}'
```

4. Проверьте RabbitMQ Management UI - сообщение должно быть в очереди

5. Запустите контейнер consumer:
```
docker start rabbitmq-consumer
```

6. Подождите несколько секунд и проверьте, что сообщение было обработано:
```
curl http://localhost:5001/messages/test_queue
```

## Остановка проекта

Для остановки всех контейнеров этого проекта:
```
docker compose down
```

Для остановки с удалением тома RabbitMQ, очередей, обменников и сообщений брокера:
```
docker compose down -v
```

История `consumer/received_messages.json` и список активных очередей `consumer/active_queues.json` остаются на компьютере: каталог `consumer` подключён в контейнер как папка с хоста
Для полного сброса удалите эти два файла вручную после остановки контейнеров
Если оставить список активных очередей, consumer создаст их снова при следующем запуске

## Дополнительная информация

### Структура контейнеров

**rabbitmq-trainer** - RabbitMQ сервер с Management UI (сервис Compose называется `rabbitmq`)
- Порты: 5672 (AMQP), 15672 (Management UI)
- Учетные данные: admin/admin

**rabbitmq-producer** - Сервис для отправки сообщений
- Порт: 5002
- API: REST API для отправки сообщений

**rabbitmq-consumer** - Сервис для получения и обработки сообщений
- Порт: 5001
- API: REST API для управления потребителями и очередями

## Особенности реализации
- Сервис consumer сохраняет состояние (список активных очередей и историю сообщений) в файлы, что позволяет восстанавливать потребителей после перезапуска контейнера
- При остановке контейнера consumer, все неподтвержденные сообщения возвращаются в очередь
- При запуске контейнера consumer, потребители автоматически восстанавливаются и начинают обрабатывать сообщения из своих очередей

## Заключение
Эта система предоставляет простой интерфейс для изучения работы с RabbitMQ через REST API. Вы можете использовать ее для изучения принципов работы систем обмена сообщениями.


## Проверка исправлений

После запуска стенда выполните с компьютера из корня репозитория:

```bash
docker compose run --rm --no-deps -v "$PWD:/repo" -w /repo consumer python -m unittest discover -s tests -v
python3 tests/smoke.py
```

Интеграционная проверка создаёт временную очередь и обменник, перезапускает контейнеры `rabbitmq-consumer` и `rabbitmq-trainer`, затем удаляет тестовую очередь и обменник.

Порты стенда доступны только на локальном компьютере.
`/send` возвращает успех после подтверждения брокера, а для сообщения без подходящей очереди возвращает HTTP 400.
`/stop_consumer` возвращает HTTP 200 после остановки потока или HTTP 202, если поток ещё завершает работу.
`/purge_queue` удаляет ожидающие сообщения из брокера, `/clear_messages` очищает сохранённую историю.
Повреждённый файл состояния останавливает запуск, чтобы его содержимое не было затёрто пустой историей.

Подтверждение получения отправляется после сохранения сообщения на диск.
При разрыве соединения между сохранением и подтверждением возможна повторная доставка.
История рассчитана на небольшой учебный стенд с одним процессом consumer: при каждом сообщении JSON-файл переписывается целиком.

Сообщения, которые не декодируются как UTF-8, сохраняются в Base64 с полем `encoding: "base64"`.
