import os
import base64
import json
import pika
import threading
import time
import tempfile
from contextlib import closing
from flask import Flask, jsonify, request
from werkzeug.exceptions import BadRequest, HTTPException

app = Flask(__name__)
RABBITMQ_HOST = os.environ.get('RABBITMQ_HOST', 'localhost')
RABBITMQ_USER = os.environ.get('RABBITMQ_USER', 'admin')
RABBITMQ_PASS = os.environ.get('RABBITMQ_PASS', 'admin')
ACTIVE_QUEUES_FILE = '/app/active_queues.json'
MESSAGES_FILE = '/app/received_messages.json'
received_messages = {}
active_queues = set()
consumers = {}
message_lock = threading.Lock()


def save_json(path, data):
    # Замена атомарна: незавершённая запись не повреждает прежнее состояние
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=os.path.dirname(path), delete=False) as f:
            temporary = f.name
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def save_active_queues():
    save_json(ACTIVE_QUEUES_FILE, sorted(active_queues))


def save_messages():
    save_json(MESSAGES_FILE, received_messages)


def load_active_queues():
    global active_queues
    if not os.path.exists(ACTIVE_QUEUES_FILE):
        return False
    with open(ACTIVE_QUEUES_FILE) as f:
        data = json.load(f)
    if not isinstance(data, list) or any(not isinstance(q, str) or not q for q in data):
        raise ValueError('Invalid active queues file')
    active_queues = set(data)
    return True


def load_messages():
    global received_messages
    if not os.path.exists(MESSAGES_FILE):
        return False
    with open(MESSAGES_FILE) as f:
        data = json.load(f)
    if not isinstance(data, dict) or any(not isinstance(v, list) for v in data.values()):
        raise ValueError('Invalid messages file')
    received_messages = data
    return True


def get_rabbitmq_connection():
    return pika.BlockingConnection(pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS),
        heartbeat=60, blocked_connection_timeout=10, socket_timeout=5,
        stack_timeout=10,
    ))


def record_message(body, queue_name):
    encoding = None
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError:
        content = base64.b64encode(body).decode('ascii')
        encoding = 'base64'
    else:
        try:
            content = json.loads(text)
        except json.JSONDecodeError:
            content = text
    message = {'message': content, 'timestamp': time.time(),
               'received_at': time.strftime('%Y-%m-%d %H:%M:%S')}
    if encoding:
        message['encoding'] = encoding
    with message_lock:
        messages = received_messages.setdefault(queue_name, [])
        messages.append(message)
        try:
            save_messages()
        except Exception:
            messages.pop()
            raise


def consume_messages(queue_name, stop_event):
    try:
        while not stop_event.is_set():
            try:
                with closing(get_rabbitmq_connection()) as connection:
                    channel = connection.channel()
                    channel.queue_declare(queue=queue_name, durable=True)
                    channel.basic_qos(prefetch_count=1)
                    for method, properties, body in channel.consume(queue_name, inactivity_timeout=0.5):
                        if stop_event.is_set():
                            break
                        if method is None:
                            continue
                        # При ошибке записи соединение закроется без ack, брокер вернёт сообщение
                        record_message(body, queue_name)
                        channel.basic_ack(delivery_tag=method.delivery_tag)
                    channel.cancel()
            except Exception:
                app.logger.exception('Consumer failed for queue %s', queue_name)
                stop_event.wait(3)
    finally:
        with message_lock:
            consumers.pop(queue_name, None)


def launch_consumer(queue_name):
    # Вызывается под message_lock: параллельные запросы не создадут второй поток
    event = threading.Event()
    thread = threading.Thread(target=consume_messages, args=(queue_name, event), daemon=True)
    consumers[queue_name] = (thread, event)
    try:
        thread.start()
    except Exception:
        consumers.pop(queue_name, None)
        raise


@app.errorhandler(BadRequest)
def bad_request(error):
    return jsonify(error=error.description), 400


@app.errorhandler(Exception)
def server_error(error):
    if isinstance(error, HTTPException):
        return jsonify(error=error.description), error.code
    app.logger.exception('Request failed')
    return jsonify(error=str(error)), 500


@app.route('/start_consumer/<queue_name>', methods=['POST'])
def start_consumer(queue_name):
    if len(queue_name.encode('utf-8')) > 255 or queue_name.startswith('amq.'):
        raise BadRequest('Invalid queue name')
    with message_lock:
        if queue_name in consumers:
            stopping = consumers[queue_name][1].is_set()
            return jsonify(status='Consumer stopping' if stopping else 'Consumer already exists'), 409 if stopping else 200
        active_queues.add(queue_name)
        try:
            save_active_queues()
            launch_consumer(queue_name)
        except Exception:
            active_queues.discard(queue_name)
            save_active_queues()
            raise
    return jsonify(status=f'Consumer started for queue: {queue_name}'), 200


@app.route('/stop_consumer/<queue_name>', methods=['POST'])
def stop_consumer(queue_name):
    with message_lock:
        if queue_name not in active_queues:
            return jsonify(status=f'No active consumer for queue: {queue_name}'), 404
        active_queues.remove(queue_name)
        try:
            save_active_queues()
        except Exception:
            active_queues.add(queue_name)
            raise
        worker = consumers.get(queue_name)
        if worker:
            worker[1].set()
    if worker:
        worker[0].join(timeout=5)
        if worker[0].is_alive():
            return jsonify(status=f'Consumer stopping for queue: {queue_name}'), 202
    return jsonify(status=f'Consumer stopped for queue: {queue_name}'), 200


@app.route('/bind_queue', methods=['POST'])
def bind_queue():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest('Expected a JSON object')
    queue = data.get('queue')
    exchange = data.get('exchange', '')
    routing_key = data.get('routing_key', '')
    for key, value in [('queue', queue), ('exchange', exchange), ('routing_key', routing_key)]:
        if not isinstance(value, str) or len(value.encode('utf-8')) > 255:
            raise BadRequest(f'Invalid {key}')
    if not queue or queue.startswith('amq.'):
        raise BadRequest('Invalid queue name')
    with closing(get_rabbitmq_connection()) as connection:
        channel = connection.channel()
        channel.queue_declare(queue=queue, durable=True)
        if exchange:
            channel.queue_bind(exchange=exchange, queue=queue, routing_key=routing_key)
    return jsonify(status=f"Queue '{queue}' created and bound" if exchange else f"Queue '{queue}' created successfully"), 200


@app.route('/purge_queue/<queue_name>', methods=['POST'])
def purge_queue(queue_name):
    with closing(get_rabbitmq_connection()) as connection:
        result = connection.channel().queue_purge(queue=queue_name)
    return jsonify(status=f'Queue purged: {queue_name}', count=result.method.message_count), 200


@app.route('/messages/<queue_name>', methods=['GET'])
def get_messages(queue_name):
    with message_lock:
        messages = list(received_messages.get(queue_name, []))
    return jsonify(messages=messages, count=len(messages)), 200


@app.route('/clear_messages/<queue_name>', methods=['POST'])
def clear_messages(queue_name):
    with message_lock:
        if queue_name in received_messages:
            previous = received_messages[queue_name]
            received_messages[queue_name] = []
            try:
                save_messages()
            except Exception:
                received_messages[queue_name] = previous
                raise
    return jsonify(status=f'Messages cleared for queue: {queue_name}'), 200


@app.route('/active_queues', methods=['GET'])
def get_active_queues():
    with message_lock:
        queues = sorted(active_queues)
    return jsonify(active_queues=queues), 200


def restore_state():
    load_messages()
    load_active_queues()
    with message_lock:
        for queue_name in active_queues:
            launch_consumer(queue_name)


if __name__ == '__main__':
    restore_state()
    app.run(host='0.0.0.0', port=5001, debug=False)
