#!/usr/bin/env python3
"""Local, dependency-free live workflow viewer for local or SSH BoxBench runs.

python3 boxbench_live.py -- ssh user@device 'bash ~/boxbench.sh collect'
python3 boxbench_live.py -- python boxbench_windows.py --all
python3 boxbench_live.py --demo
python3 boxbench_live.py --replay boxbench_live_20261118_103400_xxx.jsonl   # 回放历史测试
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import webbrowser

PREFIX = "@@BOXBENCH_EVENT "
ASSETS = Path(__file__).resolve().parent / "live"
STAGES = [
    ("hardware", "硬件指纹", "A · hardware.scan", "cpu", "识别芯片、内存、存储与加速器。"),
    ("inventory", "环境盘点", "B · environment.scan", "stack-2", "盘点模型权重、推理引擎、容器和服务。"),
    ("classify", "硬件分档", "D1–D5 · classify", "adjustments-horizontal", "匹配硬件档位与可用模型区间。"),
    ("service", "服务就绪", "C1 · model.ready", "box", "检查推理服务；多模型模式记录加载过程。"),
    ("decode", "解码速度", "C2 · decode.tokens", "bolt", "通过真实 API usage 采集解码速度。"),
    ("context", "长上下文", "C4 / C5 · context", "align-left", "采集长输入响应；Windows 同时采集解码衰减。"),
    ("concurrency", "并发测试", "C6 / C7 · concurrent", "arrows-split", "分别测试 2 路、4 路并发请求。"),
    ("tools", "工具调用", "C8 · function.call", "tool", "验证结构化工具调用响应。"),
    ("memory", "多轮记忆", "C9 · conversation", "messages", "验证模型是否记住前文的设备编号。"),
    ("resources", "运行资源", "C10 · accelerator", "chart-dots", "采集显存与可用的加速器运行信息。"),
    ("latency", "首字延迟", "C3 · first.token", "clock", "采集首字延迟；计时口径以原始报告为准。"),
    ("agent", "Agent 集成", "E · openclaw", "shield-check", "OpenClaw 框架集成测试：端到端/工具循环/多步链/输出预算；未装自动跳过。"),
    ("archive", "结果归档", "JSON · results.save", "file-check", "保存原始测试 JSON。HTML 报告另由渲染器生成。"),
]
MODEL_STAGES = {s[0] for s in STAGES[3:-1]}


class RunState:
    def __init__(self, title="设备实测", demo=False, journal=None):
        self.lock = threading.RLock()
        self.journal = journal
        self.data = dict(title=title, demo=demo, started=time.time(), ended=None,
                         status="running", current=None, model="默认模型", models=[],
                         stages=[dict(id=i, name=n, code=c, icon=ic, description=d,
                                      status="pending", started=None, ended=None, detail="")
                                 for i, n, c, ic, d in STAGES], logs=[], sequence=0)

    def event(self, event):
        with self.lock:
            now = time.time()
            if event.get("type") == "plan":
                order = event.get("stages", [])
                if len(order) != len(STAGES) or set(order) != {s[0] for s in STAGES}:
                    return
                by_id = {s["id"]: s for s in self.data["stages"]}
                self.data["stages"] = [by_id[i] for i in order]
            elif event.get("type") == "model":
                # Preserve completed model traces rather than silently overwriting them.
                if any(s["status"] != "pending" for s in self.data["stages"] if s["id"] in MODEL_STAGES):
                    self.data["models"].append(dict(name=self.data["model"], stages=copy.deepcopy(
                        [s for s in self.data["stages"] if s["id"] in MODEL_STAGES])))
                self.data["model"] = str(event.get("name", "未命名模型"))[:200]
                for s in self.data["stages"]:
                    if s["id"] in MODEL_STAGES:
                        s.update(status="pending", started=None, ended=None, detail="")
                self.data["current"] = None
            else:
                stage = next((s for s in self.data["stages"] if s["id"] == event.get("stage")), None)
                status = event.get("status")
                if stage is None or status not in {"running", "done", "failed", "skipped"}:
                    return
                stage.update(status=status, detail=str(event.get("detail", ""))[:1000])
                if status == "running":
                    stage["started"] = stage["started"] or now
                    stage["ended"] = None
                    self.data["current"] = stage["id"]
                else:
                    stage["ended"] = now
                    if self.data["current"] == stage["id"]:
                        self.data["current"] = None
            self.data["sequence"] += 1
            if self.journal:
                with self.journal.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(dict(time=now, **event), ensure_ascii=False) + "\n")

    def line(self, line):
        line = line.rstrip("\r\n")
        if line.startswith(PREFIX):
            try:
                self.event(json.loads(line[len(PREFIX):]))
                return
            except (ValueError, TypeError, AttributeError):
                pass
        if line:
            with self.lock:
                self.data["logs"].append(dict(time=time.time(), text=line[:2000]))
                self.data["logs"] = self.data["logs"][-400:]
                self.data["sequence"] += 1

    def finish(self, code):
        with self.lock:
            now = time.time()
            for s in self.data["stages"]:
                if s["status"] == "running":
                    s.update(status="failed", ended=now, detail="执行中断或未收到完成事件")
                elif s["status"] == "pending":
                    s.update(status="skipped", ended=now, detail="本次运行未执行此步骤")
            self.data.update(status="finished" if code == 0 else "failed", ended=now,
                             current=None, exit_code=code)
            self.data["sequence"] += 1

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data)


def make_server(state, port):
    # A random path isolates concurrent runs. Only loopback is exposed.
    token = secrets.token_urlsafe(18)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            base = "/" + token + "/"
            if not path.startswith(base):
                self.send_error(404)
                return
            name = path[len(base):]
            if name == "api/state":
                body = json.dumps(state.snapshot(), ensure_ascii=False).encode("utf-8")
                mime = "application/json; charset=utf-8"
            else:
                allowed = {"": "index.html", "index.html": "index.html",
                           "app.js": "app.js", "style.css": "style.css"}
                if name in allowed:
                    file = ASSETS / allowed[name]
                elif name.startswith("icons/") and name.endswith(".svg") and Path(name).name == name[6:]:
                    file = ASSETS / name
                else:
                    self.send_error(404)
                    return
                if not file.is_file():
                    self.send_error(404)
                    return
                body = file.read_bytes()
                mime = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}[file.suffix]
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server, "http://127.0.0.1:%d/%s/" % (server.server_port, token)


def replay_run(state, journal, stop, speed=1.0):
    """按真实时间轴回放 journal 中的事件流（v1.11.0 新增）。
    背景：collect 单模型全程约 1 分钟，用户浏览器打开晚只能看到最终静态画面，
    看起来"没有变化"。回放模式让用户随时重看完整过程。
    journal 每行: {"time": <unix秒>, <event>}；事件间隔按 speed 倍速压缩（≤2s/事件）。"""
    try:
        lines = [json.loads(l) for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError) as exc:
        print("无法读取回放文件: %s" % exc, file=sys.stderr)
        state.finish(1)
        return
    if not lines:
        state.finish(1)
        return
    t0 = lines[0].get("time", 0)
    prev_t = t0
    while not stop.is_set():
        # 先重置到初始态再回放
        with state.lock:
            state.data.update(started=time.time(), ended=None, status="running",
                              current=None, logs=[], models=[])
            for s in state.data["stages"]:
                s.update(status="pending", started=None, ended=None, detail="")
            state.data["sequence"] += 1
        prev_t = t0
        for rec in lines:
            if stop.is_set():
                return
            t = rec.pop("time", prev_t)
            delay = min(2.0, max(0.0, (t - prev_t) / max(speed, 0.1)))
            prev_t = t
            if stop.wait(delay):
                return
            if rec.get("type") in ("plan", "model"):
                state.event(rec)
            else:
                state.event(rec)
            state.line("[回放] " + json.dumps(rec, ensure_ascii=False)[:200])
        state.finish(0)
        if stop.wait(8):  # 停在最终态 8 秒后循环重放
            return


def demo_run(state, stop):
    while not stop.is_set():
        with state.lock:
            state.data.update(started=time.time(), ended=None, status="running", current=None, logs=[], models=[])
            for s in state.data["stages"]:
                s.update(status="pending", started=None, ended=None, detail="")
        state.event(dict(type="model", name="Qwen · 演示模型"))
        state.line("演示模式：以下为界面动效示例，不会连接设备，也不生成实测结果。")
        for sid, name, *_ in STAGES:
            if stop.is_set():
                return
            state.event(dict(stage=sid, status="running", detail="正在演示「%s」的执行效果" % name))
            state.line("[DEMO] 正在执行：" + name)
            if stop.wait(5 if sid != "context" else 12):
                return
            state.event(dict(stage=sid, status="done", detail="演示步骤已结束"))
        state.finish(0)
        if stop.wait(6):
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true", help="仅演示动效，不运行测试")
    parser.add_argument("--replay", metavar="JOURNAL", help="回放历史测试的事件记录（boxbench_live_*.jsonl），按真实时间轴重演全过程")
    parser.add_argument("--replay-speed", type=float, default=1.0, help="回放倍速（默认 1.0；2.0 = 两倍速）")
    parser.add_argument("--no-open", action="store_true", help="由 Agent 在内置浏览器打开输出的 URL")
    parser.add_argument("--port", type=int, default=0, help="默认随机空闲端口")
    parser.add_argument("--title", default="AI Box 标准化实测")
    parser.add_argument("--linger", type=float, default=900, help="测试结束后保留网页的秒数，0=立即退出；默认900")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not args.demo and not args.replay and not command:
        parser.error("请在 -- 后提供测试命令，或使用 --demo / --replay <journal>")
    journal = None
    if args.replay:
        journal = Path(args.replay)
        if not journal.is_file():
            parser.exit(2, "回放文件不存在: %s\n" % journal)
    elif not args.demo:
        journal = Path("boxbench_live_%s.jsonl" % dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    state = RunState(args.title, args.demo, journal)
    try:
        server, url = make_server(state, args.port)
    except OSError as exc:
        parser.exit(2, "看板启动失败: %s\n" % exc)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("BOXBENCH_LIVE_URL=" + url, flush=True)
    if not args.no_open:
        webbrowser.open(url)
    stop = threading.Event()
    process = None
    code = 0
    try:
        if args.demo:
            threading.Thread(target=demo_run, args=(state, stop), daemon=True).start()
            while not stop.wait(1):
                pass
        elif args.replay:
            threading.Thread(target=replay_run, args=(state, journal, stop, args.replay_speed), daemon=True).start()
            while not stop.wait(1):
                pass
        else:
            env = dict(os.environ, BOXBENCH_LIVE="1", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            # No shell interpolation. With SSH, scripts emit events unconditionally so
            # no server-side env forwarding or extra port forwarding is required.
            options = dict(start_new_session=True) if os.name != "nt" else dict(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding="utf-8", errors="replace", env=env, **options)
                for line in process.stdout:
                    state.line(line)
                    if not line.startswith(PREFIX):
                        print(line, end="", flush=True)
                code = process.wait()
            except OSError as exc:
                state.line("无法启动测试命令: " + str(exc))
                print("无法启动测试命令: " + str(exc), file=sys.stderr)
                code = 127
            state.finish(code)
            print("测试进程已结束（退出码 %d），看板保留 %g 秒。" % (code, args.linger), flush=True)
            stop.wait(max(0, args.linger))
    except KeyboardInterrupt:
        code = 130
        if process is not None and process.poll() is None:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        state.finish(code)
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
    return code


if __name__ == "__main__":
    sys.exit(main())
