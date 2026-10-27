"""Check recovery across a bridge restart without replaying a command."""
import json
import os
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.environ.get('RHINO_TEST_SOURCE', str(Path(__file__).resolve().parents[1] / 'src')))
from rhino_mcp.rhino_tools import RhinoConnection


class Bridge:
    def __init__(self, port=0, drop_response=False):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(('127.0.0.1', port))
        self.listener.listen(10)
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.drop_response = drop_response
        self.commands = []
        self.running = True
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while self.running:
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            with client:
                client.settimeout(2)
                data = client.recv(65536)
                if data:
                    self.commands.append(json.loads(data.decode('utf-8')))
                    if not self.drop_response:
                        client.sendall(b'{"status":"success"}')

    def stop(self):
        self.running = False
        self.thread.join(3)
        self.listener.close()
        if self.thread.is_alive():
            raise RuntimeError('test bridge did not stop')


class ReconnectionTests(unittest.TestCase):
    def test_first_command_after_restart_uses_new_connection(self):
        bridge = Bridge()
        connection = RhinoConnection(host='127.0.0.1', port=bridge.port)
        try:
            self.assertEqual(connection.send_command('get_scene_info')['status'], 'success')
            port = bridge.port
            bridge.stop()
            bridge = Bridge(port)
            self.assertEqual(connection.send_command('get_scene_info')['status'], 'success')
            self.assertIsNone(connection.socket)
            self.assertEqual(len(bridge.commands), 1)
        finally:
            connection.disconnect()
            bridge.stop()

    def test_lost_response_does_not_retry_a_mutating_command(self):
        bridge = Bridge(drop_response=True)
        connection = RhinoConnection(host='127.0.0.1', port=bridge.port)
        try:
            with self.assertRaisesRegex(Exception, 'Connection closed'):
                connection.send_command('execute_code', {'code': 'change model'})
            self.assertIsNone(connection.socket)
            self.assertEqual(len(bridge.commands), 1)
        finally:
            connection.disconnect()
            bridge.stop()

    def test_parallel_commands_do_not_share_a_socket(self):
        bridge = Bridge()
        connection = RhinoConnection(host='127.0.0.1', port=bridge.port)
        errors = []
        def call():
            try:
                self.assertEqual(connection.send_command('get_scene_info')['status'], 'success')
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=call) for _ in range(8)]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(len(bridge.commands), 8)
        finally:
            connection.disconnect()
            bridge.stop()


if __name__ == '__main__':
    unittest.main()
