"""Behavior checks for the live viewer; no real device or inference engine needed."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "scripts"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


live = module("boxbench_live", SCRIPTS / "boxbench_live.py")
windows = module("boxbench_windows", SCRIPTS / "boxbench_windows.py")


class LiveTests(unittest.TestCase):
    def test_model_history_and_interruption_preserve_evidence(self):
        s = live.RunState()
        s.event(dict(type="model", name="model-one"))
        s.event(dict(stage="service", status="done"))
        s.event(dict(stage="decode", status="failed", detail="HTTP 500"))
        s.event(dict(type="model", name="model-two"))
        self.assertEqual(s.snapshot()["models"][0]["stages"][1]["status"], "failed")
        self.assertEqual(next(x for x in s.snapshot()["stages"] if x["id"] == "decode")["status"], "pending")
        s.event(dict(stage="decode", status="running"))
        s.finish(23)
        snap = s.snapshot()
        self.assertEqual(snap["status"], "failed")
        self.assertEqual(next(x for x in snap["stages"] if x["id"] == "decode")["status"], "failed")
        self.assertTrue(all(x["status"] != "pending" for x in snap["stages"]))
        s.line(live.PREFIX + "not-json")
        self.assertIn("not-json", s.snapshot()["logs"][-1]["text"])

    def test_loopback_server_assets_and_path_isolation(self):
        s = live.RunState()
        server, url = live.make_server(s, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            for name in ("", "app.js", "style.css", "icons/cpu.svg", "api/state"):
                with urllib.request.urlopen(url + name) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("no-store", response.headers["Cache-Control"])
                    self.assertTrue(response.read())
            for name in ("../boxbench_live.py", "icons/../../boxbench_live.py", "api/unknown"):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(url + name)
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_wrapper_preserves_child_exit_code_and_emits_journal(self):
        child = "import sys; print('@@BOXBENCH_EVENT {\"stage\":\"hardware\",\"status\":\"running\"}', file=sys.stderr); print('visible log'); sys.exit(7)"
        with tempfile.TemporaryDirectory() as folder:
            r = subprocess.run([sys.executable, str(SCRIPTS / "boxbench_live.py"), "--no-open", "--linger", "0", "--", sys.executable, "-c", child], cwd=folder, capture_output=True, text=True, timeout=15)
            self.assertEqual(r.returncode, 7, r.stderr)
            self.assertIn("BOXBENCH_LIVE_URL=", r.stdout)
            self.assertIn("visible log", r.stdout)
            journals = list(Path(folder).glob("boxbench_live_*.jsonl"))
            self.assertEqual(len(journals), 1)
            self.assertEqual(json.loads(journals[0].read_text())["stage"], "hardware")

    def test_linux_unready_service_events_do_not_contaminate_json(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"not_ready"}')
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            source = (SCRIPTS / "boxbench.sh").read_text().split("# ---------- 主流程 ----------")[0]
            with tempfile.TemporaryDirectory() as folder:
                source += '\nAPI="http://127.0.0.1:%d"\nphase_collect\ncat "$TMPD/phasec_fragment.json"\n' % server.server_port
                r = subprocess.run(["bash"], input=source, text=True, cwd=folder, capture_output=True, timeout=10)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(json.loads(r.stdout)["skipped"], "service_not_ready")
                s = live.RunState()
                for line in r.stderr.splitlines():
                    s.line(line)
                stages = {s["id"]: s["status"] for s in s.snapshot()["stages"]}
                self.assertEqual(stages["service"], "skipped")
                self.assertEqual(stages["decode"], "skipped")
        finally:
            server.shutdown()
            server.server_close()

    def test_windows_real_http_collection_and_error_events(self):
        class API(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream" if data.get("stream") else "application/json")
                self.end_headers()
                if data.get("stream"):
                    for token in ("BX-", "7788"):
                        self.wfile.write(("data: " + json.dumps({"choices": [{"delta": {"content": token}}]}) + "\n\n").encode())
                        self.wfile.flush()
                        time.sleep(.01)
                    self.wfile.write(b'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":80}}\n\ndata: [DONE]\n\n')
                else:
                    time.sleep(.02)  # Keep real timings above the collector's 0.01s precision.
                    # Deliberately omit tool_calls to test a failed test within a successful run.
                    body = {"choices": [{"message": {"content": "BX-7788"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 100, "completion_tokens": 80}}
                    self.wfile.write(json.dumps(body).encode())
        api = ThreadingHTTPServer(("127.0.0.1", 0), API)
        threading.Thread(target=api.serve_forever, daemon=True).start()
        capture = io.StringIO()
        try:
            with patch.object(windows, "gpu_runtime_sample", return_value=None), patch.object(windows, "nvidia_smi", return_value=[]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(capture):
                result = windows.PhaseC("http://127.0.0.1:%d" % api.server_port, "fixture-model", "none").run()
            self.assertEqual(result["c2_short_decode"]["completion_tokens"], 80)
            self.assertEqual(result["c6c7_conc4"]["ok"], 4)
            self.assertEqual(result["c9_multiturn"]["ok"], 1)
            s = live.RunState()
            for line in capture.getvalue().splitlines():
                s.line(line)
            stages = {s["id"]: s["status"] for s in s.snapshot()["stages"]}
            self.assertEqual(stages["tools"], "failed")
            self.assertEqual(stages["memory"], "done")
            self.assertEqual(stages["resources"], "skipped")
            self.assertEqual(stages["context"], "done", result.get("c5_ctx_decode"))
        finally:
            api.shutdown()
            api.server_close()


if __name__ == "__main__":
    unittest.main()
