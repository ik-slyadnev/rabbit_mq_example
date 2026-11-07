import os
import json
import pika
import time
from flask import Flask, request, jsonify
from contextlib import closing
from werkzeug.exceptions import BadRequest

app = Flask(__name__)

# Конфигурация RabbitMQ
RABBITMQ_HOST = os.environ.get('RABBITMQ_HOST', 'localhost')
RABBITMQ_USER = os.environ.get('RABBITMQ_USER', 'admin')
RABBITMQ_PASS = os.environ.get('RABBITMQ_PASS', 'admin')

def get_rabbitmq_connection():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials, blocked_connection_timeout=10, socket_timeout=5, stack_timeout=10
    )
    # RabbitMQ может подниматься дольше сервиса, поэтому пробуем подключиться несколько раз
    for attempt in range(1, 11):
        try:
            return pika.BlockingConnection(parameters)
        except pika.exceptions.AMQPConnectionError:
            if attempt == 10:
                raise
            print(f"RabbitMQ недоступен, попытка {attempt}/10, ждём 3 секунды...")
            time.sleep(3)

@app.errorhandler(BadRequest)
def bad_request(error):
    return jsonify(error=error.description), 400


@app.route('/send', methods=['POST'])
def send_message():
    data = request.get_json(silent=True)
    
    if not isinstance(data, dict):
        return jsonify({"error": "No data provided"}), 400
    
    queue = data.get('queue', 'default_queue')
    message = data.get('message', '')
    exchange = data.get('exchange', '')
    routing_key = data.get('routing_key', queue)
    for key, value in [('queue', queue), ('exchange', exchange), ('routing_key', routing_key)]:
        if not isinstance(value, str) or len(value.encode('utf-8')) > 255:
            raise BadRequest(f'Invalid {key}')
    if not exchange and (not queue or queue.startswith('amq.')):
        raise BadRequest('Invalid queue name')
    
    try:
        with closing(get_rabbitmq_connection()) as connection:
            channel = connection.channel()
        
            # Создаем очередь, если она не существует
            if not exchange:
                channel.queue_declare(queue=queue, durable=True)
        
            channel.confirm_delivery()
            # Публикуем сообщение
            channel.basic_publish(
                mandatory=True,
                exchange=exchange,
                routing_key=routing_key,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2,  # Делает сообщение persistent
                )
            )
        

        return jsonify({"status": "Message sent successfully"}), 200
    
    except pika.exceptions.UnroutableError:
        return jsonify(error='Message could not be routed to a queue'), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/create_exchange', methods=['POST'])
def create_exchange():
    data = request.get_json(silent=True)
    
    if not isinstance(data, dict):
        return jsonify({"error": "No data provided"}), 400
    
    exchange = data.get('exchange', '')
    exchange_type = data.get('type', 'direct')
    
    if not isinstance(exchange, str) or not exchange or len(exchange.encode('utf-8')) > 255:
        return jsonify({"error": "Exchange name is required"}), 400
    
    if exchange_type not in ('direct', 'fanout', 'topic', 'headers'):
        raise BadRequest('Invalid exchange type')

    try:
        with closing(get_rabbitmq_connection()) as connection:
            channel = connection.channel()
        
            channel.exchange_declare(
                exchange=exchange,
                exchange_type=exchange_type,
                durable=True
            )
        

        return jsonify({"status": f"Exchange '{exchange}' created successfully"}), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
