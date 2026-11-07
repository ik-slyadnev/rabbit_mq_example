"""Run on the host after docker compose up; restarts the trainer containers."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4

queue = 'smoke-' + uuid4().hex
exchange = queue + '-exchange'


def request(port, path, data=None, method=None):
    body = None if data is None else json.dumps(data).encode()
    headers = {'Content-Type': 'application/json'}
    if port == 15672:
        headers['Authorization'] = 'Basic ' + base64.b64encode(b'admin:admin').decode()
    req = Request(f'http://127.0.0.1:{port}{path}', data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as response:
            return response.status, json.load(response) if response.status != 204 else None
    except HTTPError as error:
        return error.code, error.read().decode()


def wait_until(check, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.3)
    raise AssertionError('Timed out waiting for trainer state')


def post(port, path, data=None):
    status, result = request(port, path, data, 'POST')
    assert status in (200, 202), (status, result)
    return result


def queue_info():
    return request(15672, '/api/queues/%2F/' + queue)[1]


try:
    post(5001, '/bind_queue', {'queue': queue})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: post(5001, '/start_consumer/' + queue), range(8)))
    wait_until(lambda: queue_info().get('consumers') == 1)
    post(5002, '/send', {'queue': queue, 'message': {'id': 1}})
    wait_until(lambda: request(5001, '/messages/' + queue)[1]['count'] == 1)
    post(5001, '/stop_consumer/' + queue)
    wait_until(lambda: queue_info().get('consumers') == 0)
    post(5002, '/send', {'queue': queue, 'message': 'while stopped'})
    wait_until(lambda: queue_info().get('messages_ready') == 1)
    assert request(5001, '/messages/' + queue)[1]['count'] == 1
    assert post(5001, '/purge_queue/' + queue)['count'] == 1
    post(5002, '/create_exchange', {'exchange': exchange, 'type': 'direct'})
    assert request(5002, '/send', {'exchange': exchange, 'routing_key': 'missing', 'message': 'lost'}, 'POST')[0] == 400
    post(5001, '/bind_queue', {'queue': queue, 'exchange': exchange, 'routing_key': 'qa'})
    post(5001, '/start_consumer/' + queue)
    post(5002, '/send', {'exchange': exchange, 'routing_key': 'qa', 'message': 'routed'})
    wait_until(lambda: request(5001, '/messages/' + queue)[1]['count'] == 2)
    subprocess.run(['docker', 'stop', 'rabbitmq-consumer'], check=True, timeout=30)
    post(5002, '/send', {'queue': queue, 'message': 'sent while container stopped'})
    wait_until(lambda: queue_info().get('messages_ready') == 1)
    subprocess.run(['docker', 'start', 'rabbitmq-consumer'], check=True, timeout=30)
    wait_until(lambda: request(5001, '/messages/' + queue)[1]['count'] == 3)
    assert request(5001, '/messages/' + queue)[1]['messages'][-1]['message'] == 'sent while container stopped'
    wait_until(lambda: queue_info().get('consumers') == 1)
    subprocess.run(['docker', 'restart', 'rabbitmq-trainer'], check=True, timeout=45)
    wait_until(lambda: queue_info().get('consumers') == 1)
    post(5002, '/send', {'queue': queue, 'message': 'after reconnect'})
    wait_until(lambda: request(5001, '/messages/' + queue)[1]['count'] == 4)
    post(5001, '/clear_messages/' + queue)
    assert request(5001, '/messages/' + queue)[1]['count'] == 0
    post(5001, '/stop_consumer/' + queue)
    assert queue not in request(5001, '/active_queues')[1]['active_queues']
    print('PASS: concurrent start, stop, purge, routing, send while container stopped, restore backlog and history, broker reconnect, clear')
finally:
    request(5001, '/stop_consumer/' + queue, method='POST')
    request(15672, '/api/queues/%2F/' + queue, method='DELETE')
    request(15672, '/api/exchanges/%2F/' + exchange, method='DELETE')
