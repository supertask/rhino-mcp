"""Exercise the Rhino bridge worker without requiring Rhino or IronPython."""
import ast
import json
import os
import socket
import threading
import time
import traceback
import types
import unittest
from pathlib import Path


class IdleEvent:
    def __init__(self):
        self.handlers = []
        self.ready = threading.Event()

    def __iadd__(self, handler):
        self.handlers.append(handler)
        self.ready.set()
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self

    def fire(self):
        self.handlers[0](None, None)


class FakeClient:
    def __init__(self, fail_send=False):
        self.fail_send = fail_send
        self.recv_calls = 0
        self.closed = False
        self.responses = []

    def setsockopt(self, *args):
        pass

    def recv(self, size):
        self.recv_calls += 1
        if self.recv_calls == 1:
            return b'{"type":"get_server_status"}'
        if self.closed:
            raise socket.error(10022, 'socket no longer connected')
        return b''

    def sendall(self, data):
        if self.fail_send:
            raise socket.error(10054, 'client disconnected')
        self.responses.append(json.loads(data.decode('utf-8')))

    def close(self):
        self.closed = True


def load_server(idle, logs):
    path = Path(os.environ.get('RHINO_BRIDGE_TEST_SOURCE', str(Path(__file__).resolve().parents[1] / 'rhino_scripts' / 'rhino_mcp_bridge.py')))
    module = ast.parse(path.read_text(encoding='utf-8'))
    server_class = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'RhinoMCPServer')
    namespace = {'socket': socket, 'threading': threading, 'json': json,
                 'traceback': traceback, 'time': time,
                 'Rhino': types.SimpleNamespace(RhinoApp=types.SimpleNamespace(Idle=idle)),
                 'log_message': logs.append}
    exec(compile(ast.Module(body=[server_class], type_ignores=[]), str(path), 'exec'), namespace)
    server = namespace['RhinoMCPServer']()
    server.running = True
    server.execute_command = lambda command: {'status': 'success'}
    return server


class RhinoClientLifecycleTests(unittest.TestCase):
    def run_worker(self, fail_send):
        idle, logs, client = IdleEvent(), [], FakeClient(fail_send)
        server = load_server(idle, logs)
        worker = threading.Thread(target=server._handle_client, args=(client,), daemon=True)
        worker.start()
        self.assertTrue(idle.ready.wait(1), 'worker did not schedule Rhino idle callback')
        time.sleep(0.05)
        self.assertEqual(client.recv_calls, 1, 'worker read again before response completed')
        idle.fire()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertTrue(client.closed)
        self.assertEqual(idle.handlers, [])
        self.assertFalse(any('Error handling client' in line for line in logs))
        return client, logs

    def test_disconnected_client_is_closed_by_worker_without_another_recv(self):
        client, logs = self.run_worker(fail_send=True)
        self.assertEqual(client.recv_calls, 1)
        self.assertTrue(any('Could not send response' in line for line in logs))

    def test_successful_response_allows_next_recv_and_clean_disconnect(self):
        client, _ = self.run_worker(fail_send=False)
        self.assertEqual(client.responses, [{'status': 'success'}])
        self.assertEqual(client.recv_calls, 2)


if __name__ == '__main__':
    unittest.main()
