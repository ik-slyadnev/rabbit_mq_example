# Руководство по запуску и использованию RabbitMQ проекта

## Обзор проекта

Этот проект представляет собой систему обмена сообщениями на базе RabbitMQ с тремя основными компонентами:

- **Producer (Отправитель)** - сервис для отправки сообщений в очереди RabbitMQ
- **Consumer (Получатель)** - сервис для получения и обработки сообщений из очередей
- **RabbitMQ** - брокер сообщений, который обеспечивает хранение и маршрутизацию сообщений

Система использует Docker и Docker Compose для контейнеризации и оркестрации сервисов.

## Требования

- Docker
- Docker Compose

## Запуск проекта

### Шаг 1: Клонирование репозитория
```
git clone <url-репозитория>
cd <название-репозитория>
```

### Шаг 2: Запуск контейнеров
```
docker-compose up -d
```

Эта команда запустит три контейнера:
- *rabbitmq* - сервер RabbitMQ с Management UI
- *rabbitmq-producer* - сервис для отправки сообщений
- *rabbitmq-consumer* - сервис для получения и обработки сообщений

### Шаг 3: Проверка статуса контейнеров
```
docker-compose ps
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

Для остановки всех контейнеров:
```
docker-compose down
```

Для остановки с удалением всех данных (включая тома):
```
docker-compose down -v
```

## Дополнительная информация

### Структура контейнеров

**rabbitmq** - RabbitMQ сервер с Management UI
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
