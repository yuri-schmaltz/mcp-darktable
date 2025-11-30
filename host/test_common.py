import os
import time
import tempfile
import unittest

from host.common import McpClient


STUB_SERVER = """
import json
import sys
import time

for line in sys.stdin:
    data = json.loads(line)
    method = data.get("method")
    if method == "delay":
        sys.stderr.write("delayed response\\n")
        sys.stderr.flush()
        time.sleep(1)
        payload = {"jsonrpc": "2.0", "id": data["id"], "result": {"ok": True}}
    elif method == "echo":
        payload = {"jsonrpc": "2.0", "id": data["id"], "result": {"echo": data.get("params")}}
    else:
        payload = {"jsonrpc": "2.0", "id": data["id"], "error": {"message": "unknown"}}

    sys.stdout.write(json.dumps(payload) + "\\n")
    sys.stdout.flush()
"""


class McpClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._stub_file = tempfile.NamedTemporaryFile("w", delete=False)
        cls._stub_file.write(STUB_SERVER)
        cls._stub_file.flush()
        cls._stub_file.close()

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls._stub_file.name)
        except OSError:
            pass

    def _new_client(self, **kwargs):
        return McpClient(
            ["python", "-u", self._stub_file.name],
            protocol_version="1.0",
            client_info={"name": "test", "version": "0.0"},
            **kwargs,
        )

    def test_request_timeout_captures_stderr(self):
        with self.assertRaises(TimeoutError) as ctx:
            with self._new_client(response_timeout=0.1) as client:
                client.request("delay")

        message = str(ctx.exception)
        self.assertIn("timeout", message)
        self.assertIn("delayed response", message)

    def test_context_manager_terminates_on_exception(self):
        try:
            with self._new_client() as client:
                client.request("echo", {"ping": True})
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        for _ in range(20):
            if client.proc.poll() is not None:
                break
            time.sleep(0.05)

        self.assertIsNotNone(client.proc.poll(), "Processo Lua não foi encerrado pelo contexto")

    def test_successful_request(self):
        with self._new_client() as client:
            result = client.request("echo", {"foo": "bar"})

        self.assertEqual(result["echo"], {"foo": "bar"})


if __name__ == "__main__":
    unittest.main()
