import os
import json
import pika
from flask import Flask, request, jsonify

app = Flask(__name__)

# Конфигурация RabbitMQ
RABBITMQ_HOST = os.environ.get('RABBITMQ_HOST', 'localhost')
RABBITMQ_USER = os.environ.get('RABBITMQ_USER', 'admin')
RABBITMQ_PASS = os.environ.get('RABBITMQ_PASS', 'admin')

def get_rabbitmq_connection():
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials
    )
    return pika.BlockingConnection(parameters)

@app.route('/send', methods=['POST'])
def send_message():
    data = request.json
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    queue = data.get('queue', 'default_queue')
    message = data.get('message', '')
    exchange = data.get('exchange', '')
    routing_key = data.get('routing_key', queue)
    
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        
        # Создаем очередь, если она не существует
        if not exchange:
            channel.queue_declare(queue=queue, durable=True)
        
        # Публикуем сообщение
        channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # Делает сообщение persistent
            )
        )
        
        connection.close()
        return jsonify({"status": "Message sent successfully"}), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/create_exchange', methods=['POST'])
def create_exchange():
    data = request.json
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    exchange = data.get('exchange', '')
    exchange_type = data.get('type', 'direct')
    
    if not exchange:
        return jsonify({"error": "Exchange name is required"}), 400
    
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        
        channel.exchange_declare(
            exchange=exchange,
            exchange_type=exchange_type,
            durable=True
        )
        
        connection.close()
        return jsonify({"status": f"Exchange '{exchange}' created successfully"}), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
