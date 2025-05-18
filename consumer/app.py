import os
import json
import pika
import threading
import time
from flask import Flask, jsonify

app = Flask(__name__)

# Конфигурация RabbitMQ
RABBITMQ_HOST = os.environ.get('RABBITMQ_HOST', 'localhost')
RABBITMQ_USER = os.environ.get('RABBITMQ_USER', 'admin')
RABBITMQ_PASS = os.environ.get('RABBITMQ_PASS', 'admin')

# Пути к файлам для сохранения состояния
ACTIVE_QUEUES_FILE = '/app/active_queues.json'
MESSAGES_FILE = '/app/received_messages.json'

# Хранилище для полученных сообщений
received_messages = {}

# Список активных очередей для потребителей
active_queues = set()

# Блокировка для безопасного доступа
message_lock = threading.Lock()

def save_active_queues():
    """Сохраняет список активных очередей в файл"""
    try:
        with open(ACTIVE_QUEUES_FILE, 'w') as f:
            json.dump(list(active_queues), f)
        print(f"Active queues saved to {ACTIVE_QUEUES_FILE}")
    except Exception as e:
        print(f"Error saving active queues: {str(e)}")

def load_active_queues():
    """Загружает список активных очередей из файла"""
    global active_queues
    try:
        if os.path.exists(ACTIVE_QUEUES_FILE):
            with open(ACTIVE_QUEUES_FILE, 'r') as f:
                active_queues = set(json.load(f))
            print(f"Active queues loaded from {ACTIVE_QUEUES_FILE}: {active_queues}")
            return True
        return False
    except Exception as e:
        print(f"Error loading active queues: {str(e)}")
        return False

def save_messages():
    """Сохраняет историю сообщений в файл"""
    try:
        with open(MESSAGES_FILE, 'w') as f:
            json.dump(received_messages, f)
        print(f"Messages saved to {MESSAGES_FILE}")
    except Exception as e:
        print(f"Error saving messages: {str(e)}")

def load_messages():
    """Загружает историю сообщений из файла"""
    global received_messages
    try:
        if os.path.exists(MESSAGES_FILE):
            with open(MESSAGES_FILE, 'r') as f:
                received_messages = json.load(f)
            print(f"Messages loaded from {MESSAGES_FILE}")
            return True
        return False
    except Exception as e:
        print(f"Error loading messages: {str(e)}")
        return False

def get_rabbitmq_connection():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300
    )
    return pika.BlockingConnection(parameters)

def consume_messages(queue_name):
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        
        # Создаем очередь, если она не существует
        channel.queue_declare(queue=queue_name, durable=True)
        
        # Инициализируем список сообщений для этой очереди
        with message_lock:
            if queue_name not in received_messages:
                received_messages[queue_name] = []
            # Добавляем очередь в список активных
            active_queues.add(queue_name)
            # Сохраняем список активных очередей
            save_active_queues()
        
        def callback(ch, method, properties, body):
            message_id = method.delivery_tag
            print(f"[{queue_name}] Received message #{message_id}")
            
            try:
                # Пробуем декодировать как JSON
                try:
                    message = json.loads(body)
                    message_content = message
                except json.JSONDecodeError:
                    # Если не JSON, декодируем как строку
                    message_content = body.decode('utf-8')
                
                # Создаем объект сообщения
                message_obj = {
                    "message": message_content,
                    "timestamp": time.time(),
                    "received_at": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                
                # Добавляем сообщение в список полученных
                with message_lock:
                    received_messages[queue_name].append(message_obj)
                    # Сохраняем историю сообщений
                    save_messages()
                
                print(f"[{queue_name}] Message content: {message_content}")
                
                # Подтверждаем получение сообщения сразу, без задержки
                ch.basic_ack(delivery_tag=message_id)
                print(f"[{queue_name}] Message #{message_id} acknowledged")
                
            except Exception as e:
                print(f"[{queue_name}] Error processing message #{message_id}: {str(e)}")
                # В случае ошибки все равно подтверждаем сообщение
                ch.basic_ack(delivery_tag=message_id)
        
        # Настраиваем потребление сообщений
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=queue_name, on_message_callback=callback)
        
        print(f"[{queue_name}] Started consuming from queue")
        channel.start_consuming()
    
    except Exception as e:
        print(f"[{queue_name}] Error in consumer thread: {str(e)}")
        # Пробуем восстановить соединение после паузы
        print(f"[{queue_name}] Attempting to reconnect in 5 seconds...")
        time.sleep(5)
        consume_messages(queue_name)

@app.route('/start_consumer/<queue_name>', methods=['POST'])
def start_consumer(queue_name):
    try:
        # Проверяем, не запущен ли уже потребитель для этой очереди
        with message_lock:
            if queue_name in active_queues:
                return jsonify({
                    "status": f"Consumer already exists for queue: {queue_name}"
                }), 200
        
        # Запускаем потребителя в отдельном потоке
        consumer_thread = threading.Thread(
            target=consume_messages,
            args=(queue_name,),
            daemon=True
        )
        consumer_thread.start()
        
        # Инициализируем список сообщений для этой очереди
        with message_lock:
            if queue_name not in received_messages:
                received_messages[queue_name] = []
            active_queues.add(queue_name)
            # Сохраняем список активных очередей и историю сообщений
            save_active_queues()
            save_messages()
        
        return jsonify({
            "status": f"Consumer started for queue: {queue_name}"
        }), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stop_consumer/<queue_name>', methods=['POST'])
def stop_consumer(queue_name):
    try:
        with message_lock:
            if queue_name in active_queues:
                active_queues.remove(queue_name)
                # Сохраняем список активных очередей
                save_active_queues()
                return jsonify({
                    "status": f"Consumer stopped for queue: {queue_name}. Note: The consumer will be fully stopped when the current message processing completes."
                }), 200
            else:
                return jsonify({
                    "status": f"No active consumer for queue: {queue_name}"
                }), 404
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/bind_queue', methods=['POST'])
def bind_queue():
    from flask import request
    data = request.json
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    queue = data.get('queue', '')
    exchange = data.get('exchange', '')
    routing_key = data.get('routing_key', '')
    
    if not queue:
        return jsonify({"error": "Queue name is required"}), 400
    
    if not exchange:
        # Если обменник не указан, создаем только очередь
        try:
            connection = get_rabbitmq_connection()
            channel = connection.channel()
            
            # Создаем очередь, если она не существует
            channel.queue_declare(queue=queue, durable=True)
            
            connection.close()
            return jsonify({
                "status": f"Queue '{queue}' created successfully"
            }), 200
        
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        
        # Создаем очередь, если она не существует
        channel.queue_declare(queue=queue, durable=True)
        
        # Привязываем очередь к обменнику
        channel.queue_bind(
            exchange=exchange,
            queue=queue,
            routing_key=routing_key
        )
        
        connection.close()
        return jsonify({
            "status": f"Queue '{queue}' bound to exchange '{exchange}' with routing key '{routing_key}'"
        }), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/messages/<queue_name>', methods=['GET'])
def get_messages(queue_name):
    with message_lock:
        if queue_name not in received_messages:
            return jsonify({"messages": [], "count": 0}), 200
        
        messages = received_messages[queue_name]
        count = len(messages)
    
    return jsonify({
        "messages": messages,
        "count": count
    }), 200

@app.route('/clear_messages/<queue_name>', methods=['POST'])
def clear_messages(queue_name):
    with message_lock:
        if queue_name in received_messages:
            received_messages[queue_name] = []
            # Сохраняем обновленную историю сообщений
            save_messages()
    
    return jsonify({
        "status": f"Messages cleared for queue: {queue_name}"
    }), 200

@app.route('/active_queues', methods=['GET'])
def get_active_queues():
    return jsonify({
        "active_queues": list(active_queues)
    }), 200

# Функция для автоматического восстановления потребителей при запуске
def restore_state():
    # Загружаем историю сообщений
    load_messages()
    
    # Загружаем и восстанавливаем активные очереди
    if load_active_queues():
        print("Restoring consumers for active queues...")
        for queue_name in list(active_queues):
            try:
                consumer_thread = threading.Thread(
                    target=consume_messages,
                    args=(queue_name,),
                    daemon=True
                )
                consumer_thread.start()
                print(f"Consumer restored for queue: {queue_name}")
            except Exception as e:
                print(f"Error restoring consumer for queue {queue_name}: {str(e)}")

# Запускаем восстановление состояния при старте приложения
if __name__ == '__main__':
    # Восстанавливаем состояние перед запуском сервера
    restore_state()
    # Запускаем сервер
    app.run(host='0.0.0.0', port=5001, debug=True)
