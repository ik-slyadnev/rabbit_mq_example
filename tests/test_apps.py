import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / name / 'app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AppTests(unittest.TestCase):
    def setUp(self):
        self.consumer = load('consumer')
        self.producer = load('producer')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.consumer.MESSAGES_FILE = self.tmp.name + '/messages.json'
        self.consumer.ACTIVE_QUEUES_FILE = self.tmp.name + '/queues.json'

    def test_bad_payloads_do_not_connect_to_broker(self):
        for module, endpoint in [(self.producer, '/send'), (self.producer, '/create_exchange'),
                                 (self.consumer, '/bind_queue')]:
            with patch.object(module, 'get_rabbitmq_connection') as connect:
                for data in [None, [], 'text', 12, {'queue': []}, {'queue': 'q', 'exchange': []}]:
                    response = module.app.test_client().post(endpoint, json=data)
                    self.assertEqual(response.status_code, 400, (endpoint, data))
                connect.assert_not_called()

    def test_failed_save_preserves_previous_file_and_memory(self):
        c = self.consumer
        c.record_message(b'"first"', 'q')
        original = Path(c.MESSAGES_FILE).read_text()
        with patch.object(c.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                c.record_message(b'"second"', 'q')
        self.assertEqual(Path(c.MESSAGES_FILE).read_text(), original)
        self.assertEqual(len(c.received_messages['q']), 1)
        self.assertEqual(len(list(Path(self.tmp.name).iterdir())), 1)

    def test_binary_messages_do_not_block_queue_or_lose_bytes(self):
        c = self.consumer
        c.record_message(b'\xff\x00', 'q')
        self.assertEqual(c.received_messages['q'][0]['message'], '/wA=')
        self.assertEqual(c.received_messages['q'][0]['encoding'], 'base64')

    def test_clear_rolls_back_on_disk_error(self):
        c = self.consumer
        c.record_message(b'1', 'q')
        with patch.object(c, 'save_messages', side_effect=OSError('disk full')):
            response = c.app.test_client().post('/clear_messages/q')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(c.received_messages['q']), 1)

    def test_corrupt_state_is_not_silently_overwritten(self):
        c = self.consumer
        Path(c.MESSAGES_FILE).write_text('{broken')
        with self.assertRaises(json.JSONDecodeError):
            c.restore_state()
        self.assertEqual(Path(c.MESSAGES_FILE).read_text(), '{broken')

    def test_failed_persistence_does_not_acknowledge_message(self):
        c = self.consumer
        event = Mock()
        event.is_set.side_effect = [False, False, True]
        connection = Mock()
        channel = connection.channel.return_value
        channel.consume.return_value = iter([(Mock(delivery_tag=1), None, b'1')])
        with patch.object(c, 'get_rabbitmq_connection', return_value=connection), \
             patch.object(c, 'save_messages', side_effect=OSError('disk full')):
            c.consume_messages('q', event)
        channel.basic_ack.assert_not_called()
        connection.close.assert_called_once()
        self.assertEqual(c.received_messages['q'], [])

    def test_unroutable_publish_is_not_reported_as_success(self):
        p = self.producer
        connection = Mock()
        channel = connection.channel.return_value
        channel.basic_publish.side_effect = p.pika.exceptions.UnroutableError([])
        with patch.object(p, 'get_rabbitmq_connection', return_value=connection):
            response = p.app.test_client().post('/send', json={'exchange': 'ex', 'routing_key': 'missing'})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(channel.basic_publish.call_args.kwargs['mandatory'])
        channel.confirm_delivery.assert_called_once()
        connection.close.assert_called_once()

    def test_http_errors_keep_status(self):
        self.assertEqual(self.consumer.app.test_client().get('/missing').status_code, 404)


if __name__ == '__main__':
    unittest.main()
