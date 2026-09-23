"""Run the browser's ApiClient under Node against a server that never answers.

A stubbed fetch would only restate our assumption about how an aborted fetch
rejects; the real one rejects with the abort reason itself, which is the
behavior the timeout message depends on.
"""

import json
import shutil
import socket
import subprocess
import threading
from pathlib import Path

API_JS = Path(__file__).resolve().parent.parent / "vocab_builder" / "mobile" / "static" / "api.js"

SCRIPT = """
globalThis.window = globalThis;
const { ApiClient } = await import(process.argv[1]);
const base = process.argv[2];
const api = new ApiClient(() => null);
const describe = (error) => ({ code: error.code, message: error.message });
const out = {};
try {
  await api.request(`${base}/slow`, {}, { timeout: 100 });
} catch (error) {
  out.timeout = describe(error);
}
const first = api.request(`${base}/slow`, {}, { scope: "same", timeout: 5000 }).catch(describe);
api.request(`${base}/slow`, {}, { scope: "same", timeout: 100 }).catch(() => {});
out.superseded = await first;
console.log(JSON.stringify(out));
process.exit(0);
"""


def _silent_server():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    held = []

    def accept_forever():
        while True:
            try:
                connection, _ = server.accept()
            except OSError:
                return
            held.append(connection)

    threading.Thread(target=accept_forever, daemon=True).start()
    return server, held


def test_timeout_and_supersede_report_their_own_messages():
    node = shutil.which("node")
    assert node, "Node is required to exercise the browser modules"
    server, held = _silent_server()
    try:
        port = server.getsockname()[1]
        result = subprocess.run(
            [node, "--input-type=module", "-e", SCRIPT, API_JS.as_uri(), f"http://127.0.0.1:{port}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        server.close()
        for connection in held:
            connection.close()

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["timeout"] == {
        "code": "request_timeout",
        "message": "The server took too long to respond.",
    }
    assert out["superseded"] == {"code": "request_aborted", "message": "Request superseded."}
