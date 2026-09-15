"""F. API 契约与鲁棒性（P0）。

启动真实 uvicorn（``.venv/bin/python run.py``）逐条走查 A1~A15，
并验证串行约束、abort 资源回收、端口检测、auto 降级、异常输入返回结构化中文错误。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _harness import PROJECT_ROOT, Suite

PY = sys.executable
SERVER_PORT = 8799
LLAMA_PORT = 8080


def _wait_health(client, timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = client.get("/api/health")
            if r.status_code == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.25)
    return False


def _models(n=1):
    return [
        {"model_name": f"QA-Model-{i}", "model_size": "2B", "gguf_path": f"/tmp/qa{i}.gguf",
         "precision": "w8a8", "selected": True}
        for i in range(n)
    ]


def _small_cfg(out_dir):
    return {
        "ctx_levels": [8000, 16000], "input_levels": [250, 500, 1000, 2000, 4000, 8000],
        "runner_mode": "mock", "warmup_runs": 0, "repeat_runs": 1,
        "output_dir": out_dir, "auto_open_overview": False, "skip_after_fails": 2,
    }


def run() -> Suite:
    s = Suite("F. API 契约与鲁棒性")
    import httpx

    cfg_path = PROJECT_ROOT / "config.json"
    cfg_backup = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else None
    tmp_out = tempfile.mkdtemp(prefix="ggufbench_qa_api_")

    proc = subprocess.Popen(
        [PY, str(PROJECT_ROOT / "run.py"), "--port", str(SERVER_PORT), "--no-browser",
         "--log-level", "warning"],
        cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    client = httpx.Client(base_url=f"http://127.0.0.1:{SERVER_PORT}", timeout=30.0)
    try:
        if not _wait_health(client):
            s.check("F0", "后端可启动", False, "health 探测超时")
            return s
        s.check("F0", "后端可启动并响应 /api/health", True)

        # ---- A1 health ----
        r = client.get("/api/health")
        b = r.json()
        s.eq("F-A1", "A1 /api/health 200", r.status_code, 200)
        s.check("F-A1b", "A1 含 ok/python_version/llama_server_found/version",
                b.get("ok") is True and "python_version" in b and "llama_server_found" in b and "version" in b,
                f"body={b}")

        # ---- A2/A3 config ----
        r = client.get("/api/config")
        s.eq("F-A2", "A2 /api/config 200", r.status_code, 200)
        s.check("F-A2b", "A2 返回 BenchConfig 键", "ctx_levels" in r.json() and "input_levels" in r.json())
        r = client.put("/api/config", json={"threads": 8})
        s.eq("F-A3", "A3 PUT /api/config 200", r.status_code, 200)
        s.eq("F-A3b", "A3 更新生效", r.json()["config"]["threads"], 8)

        # ---- A4 scan ----
        missing = str(Path(tmp_out) / "nope")
        r = client.post("/api/scan", json={"dir": missing, "recursive": True})
        body = r.json()
        s.eq("F-A4", "A4 不存在目录 → 400", r.status_code, 400)
        s.check("F-A4b", "A4 错误体为 {ok:false,error:{code,message}} 且中文",
                body.get("ok") is False and body.get("error", {}).get("code") == "E_DIR_NOT_FOUND"
                and any("\u4e00" <= c <= "\u9fff" for c in body.get("error", {}).get("message", "")),
                f"body={body}")

        scan_dir = Path(tmp_out) / "models"
        scan_dir.mkdir(parents=True, exist_ok=True)
        (scan_dir / "Good-2B-Q4_K_M.gguf").write_bytes(b"x")
        (scan_dir / "mmproj-f16.gguf").write_bytes(b"x")
        r = client.post("/api/scan", json={"dir": str(scan_dir), "recursive": True})
        b = r.json()
        s.eq("F-A4c", "A4 有效目录 200", r.status_code, 200)
        s.check("F-A4d", "A4 返回 models 且过滤 mmproj",
                len(b.get("models", [])) == 1 and b.get("ignored") == ["mmproj-f16.gguf"],
                f"body={b}")

        # ---- A5 port-check ----
        r = client.post("/api/port-check", json={"port": LLAMA_PORT})
        s.eq("F-A5", "A5 空闲端口 → in_use false", r.json().get("in_use"), False)
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", LLAMA_PORT))
        holder.listen(1)
        try:
            r = client.post("/api/port-check", json={"port": LLAMA_PORT})
            s.eq("F-A5b", "A5 占用端口 → in_use true", r.json().get("in_use"), True)
        finally:
            holder.close()

        # A5 非法端口（越界/负数）→ 期望结构化 400（而非 500）
        for bad_port in (70000, -1):
            r = client.post("/api/port-check", json={"port": bad_port})
            ok = r.status_code == 400 and r.json().get("error", {}).get("code") == "E_BAD_REQUEST"
            s.check("F-A5c", f"A5 非法端口 {bad_port} → 结构化 400", ok,
                    f"实际 status={r.status_code} body={r.text[:200]}")

        # ---- A6 tokenize ----
        r = client.post("/api/tokenize", json={"text": "hello world 你好"})
        s.eq("F-A6", "A6 tokenize 200", r.status_code, 200)
        s.check("F-A6b", "A6 返回整数 token_count", isinstance(r.json().get("token_count"), int))

        # ---- A7 preview（非法档位鲁棒性见 F-A3c）----
        r = client.post("/api/tasks/preview", json={"models": _models(2), "config": _small_cfg(tmp_out)})
        s.eq("F-A7", "A7 preview 200", r.status_code, 200)
        s.eq("F-A7b", "A7 每模型点数一致", len({pm["points"] for pm in r.json()["per_model"]}), 1)

        # ---- A8/A9/A12/A13/A14 全链路 ----
        models = _models(8)
        r = client.post("/api/tasks", json={"models": models, "config": _small_cfg(tmp_out)})
        s.eq("F-A8", "A8 创建任务 200", r.status_code, 200)
        task_id = r.json().get("task_id", "")
        s.check("F-A8b", "A8 返回非空 task_id", bool(task_id), f"body={r.text[:200]}")

        # A8 空模型 → 400
        r = client.post("/api/tasks", json={"models": [], "config": _small_cfg(tmp_out)})
        s.eq("F-A8c", "A8 空模型 → 400", r.status_code, 400)

        # 等待进入 running（用于串行约束）
        running = False
        deadline = time.time() + 5
        while time.time() < deadline:
            st = client.get(f"/api/tasks/{task_id}").json()
            if st.get("state") == "running":
                running = True
                break
            if st.get("state") in ("done", "error"):
                break
            time.sleep(0.02)

        # ---- F25 串行约束：任务运行中再次创建 → 拒绝 ----
        if running:
            r2 = client.post("/api/tasks", json={"models": _models(1), "config": _small_cfg(tmp_out)})
            s.check("F25", "运行中重复创建任务被拒绝（409/400）", r2.status_code in (409, 400),
                    f"实际 status={r2.status_code} body={r2.text[:200]}")
        else:
            # 任务过快结束：退化为单元级验证（见 F25b）
            s.note("F25 在线竞态窗口未捕获（mock 任务过快），改由 F25b 单元验证")

        # ---- A9 状态 ----
        r = client.get(f"/api/tasks/{task_id}")
        s.eq("F-A9", "A9 状态查询 200", r.status_code, 200)
        s.check("F-A9b", "A9 返回 TaskStatus 字段", "state" in r.json() and "points_total" in r.json())

        # 等待完成
        deadline = time.time() + 30
        while time.time() < deadline:
            st = client.get(f"/api/tasks/{task_id}").json()
            if st.get("state") in ("done", "error"):
                break
            time.sleep(0.1)
        st = client.get(f"/api/tasks/{task_id}").json()
        s.check("F-A9c", "A9 任务最终 done", st.get("state") == "done", f"state={st.get('state')} msg={st.get('message')}")
        s.eq("F-A9d", "A9 完成时 percent=100", st.get("percent"), 100.0)
        s.eq("F-A9e", "A9 points_total == 8×点数", st.get("points_total"), st.get("points_done"))

        # ---- A12 points ----
        r = client.get(f"/api/tasks/{task_id}/points")
        s.eq("F-A12", "A12 拉取数据点 200", r.status_code, 200)
        pts = r.json()["points"]
        s.check("F-A12b", "A12 返回非空 points 且字段齐全",
                pts and "prefill_tps" in pts[0] and "fail_reason" in pts[0], f"n={len(pts)}")
        r = client.get(f"/api/tasks/{task_id}/points", params={"model": "QA-Model-0"})
        s.check("F-A12c", "A12 按模型过滤生效",
                all(p["model_name"] == "QA-Model-0" for p in r.json()["points"]) and len(r.json()["points"]) > 0)

        # ---- A13 reports ----
        r = client.get("/api/reports")
        s.eq("F-A13", "A13 报告列表 200", r.status_code, 200)
        s.check("F-A13b", "A13 退回 /reports 路径",
                all(rep["path"].startswith("/reports/") for rep in r.json().get("reports", [])))

        # ---- A14 手动重建总览 ----
        r = client.post("/api/reports/overview/build", json={"task_id": task_id})
        s.eq("F-A14", "A14 重建总览 200", r.status_code, 200)
        s.check("F-A14b", "A14 返回 overview.html 路径",
                r.json().get("path", "").endswith("overview.html"), f"body={r.text[:200]}")

        # ---- A10 SSE ----
        try:
            with client.stream("GET", f"/api/tasks/{task_id}/events") as resp:
                s.eq("F-A10", "A10 SSE 200", resp.status_code, 200)
                line = ""
                for chunk in resp.iter_lines():
                    if chunk:
                        line = chunk
                        break
                s.check("F-A10b", "A10 首帧为 data: {...}", line.startswith("data:"), f"line={line[:120]}")
        except Exception as exc:  # noqa: BLE001
            s.check("F-A10", "A10 SSE 可订阅", False, repr(exc))

        # ---- A11 abort + 资源回收 ----
        r = client.post("/api/tasks", json={"models": _models(8), "config": _small_cfg(tmp_out)})
        tid2 = r.json()["task_id"]
        deadline = time.time() + 5
        while time.time() < deadline:
            if client.get(f"/api/tasks/{tid2}").json().get("state") == "running":
                break
            time.sleep(0.02)
        r = client.post(f"/api/tasks/{tid2}/abort")
        s.eq("F-A11", "A11 中断 200", r.status_code, 200)

        # 等待停止
        stopped = False
        deadline = time.time() + 15
        while time.time() < deadline:
            stt = client.get(f"/api/tasks/{tid2}").json()
            if stt.get("state") in ("done", "error"):
                stopped = True
                break
            time.sleep(0.1)
        s.check("F-A11b", "A11 中断后任务停止", stopped, f"state={stt.get('state')}")

        # 中断后无残留 llama-server 进程 & 端口释放
        pg = subprocess.run(["pgrep", "-fl", "llama-server"], capture_output=True, text=True)
        s.check("F-A11c", "中断后无残留 llama-server 进程", pg.stdout.strip() == "",
                f"pgrep={pg.stdout.strip()}")
        free = True
        try:
            t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            t.bind(("127.0.0.1", LLAMA_PORT))
            t.close()
        except OSError:
            free = False
        s.check("F-A11d", f"中断后 llama 端口 {LLAMA_PORT} 已释放", free)

        # 已结束任务再中断 → 409
        r = client.post(f"/api/tasks/{task_id}/abort")
        s.check("F-A11e", "已结束任务再中断 → 409", r.status_code == 409, f"status={r.status_code}")

        # 不存在任务 → 404
        r = client.get("/api/tasks/no-such-task")
        s.eq("F-A9f", "不存在任务 → 404", r.status_code, 404)

        # ---- A2c 非法档位（负数/超大）→ 期望结构化 400 ----
        for bad_levels in ({"ctx_levels": [-1]}, {"input_levels": [-5]}, {"ctx_levels": [10 ** 12]}):
            r = client.put("/api/config", json=bad_levels)
            ok = r.status_code == 400 and r.json().get("error", {}).get("code") == "E_BAD_REQUEST"
            s.check("F-A3c", f"非法档位 {bad_levels} → 结构化 400", ok,
                    f"实际 status={r.status_code} body={r.text[:160]}")

        # 合法但乱序/重复 → 归一化（去重升序），不应报错
        r = client.put("/api/config", json={"ctx_levels": [16000, 8000, 8000, 4000]})
        body = r.json()
        s.check("F-A3d", "合法档位自动去重升序",
                r.status_code == 200 and body.get("config", {}).get("ctx_levels") == [4000, 8000, 16000],
                f"status={r.status_code} ctx_levels={body.get('config', {}).get('ctx_levels')}")
        # 非法端口（配置）→ 400
        r = client.put("/api/config", json={"port": 99999})
        s.check("F-A3e", "非法端口(配置) → 结构化 400",
                r.status_code == 400 and r.json().get("error", {}).get("code") == "E_BAD_REQUEST",
                f"status={r.status_code} body={r.text[:160]}")

    finally:
        client.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if cfg_backup is not None:
            cfg_path.write_text(cfg_backup, encoding="utf-8")

    # ---- F11 auto 降级（单元级，进程外）----
    from ggufbench.models import BenchConfig, ModelMeta
    from ggufbench.runners import make_runner
    from ggufbench.runners.mock_runner import MockRunner
    from ggufbench.runners.real_runner import RealRunner

    meta = ModelMeta(model_name="M", model_size="2B", gguf_path="/tmp/m.gguf")
    cfg_auto_missing = BenchConfig(runner_mode="auto", llama_server_path="/definitely/not/here/llama-server")
    r = make_runner(cfg_auto_missing, meta, 4000, Path(tmp_out))
    s.check("F11", "auto 且 llama-server 不存在 → 降级 MockRunner", isinstance(r, MockRunner),
            f"got={type(r).__name__}")
    real_exe = "/bin/echo"
    cfg_auto_found = BenchConfig(runner_mode="auto", llama_server_path=real_exe)
    r2 = make_runner(cfg_auto_found, meta, 4000, Path(tmp_out))
    s.check("F11b", "auto 且 llama-server 存在 → RealRunner", isinstance(r2, RealRunner),
            f"got={type(r2).__name__}")
    s.check("F11c", "runner_mode=real 强制 RealRunner",
            isinstance(make_runner(BenchConfig(runner_mode="real"), meta, 4000, Path(tmp_out)), RealRunner))

    # ---- F25b 串行约束（TaskManager 单元级，确定性）----
    from ggufbench.errors import ApiError, ErrorCode
    from ggufbench.models import BenchConfig as BC
    from ggufbench.task_manager import TaskManager, _Task

    tm = TaskManager()
    fake = _Task(task_id="busy", engine=object(), models=[])
    fake.last_status = {"task_id": "busy", "state": "running"}
    tm._tasks["busy"] = fake
    s.check("F25b", "TaskManager.is_busy() 检测到运行中任务", tm.is_busy() is True)
    try:
        tm.create("", [ModelMeta(model_name="M", model_size="2B", gguf_path="/tmp/m.gguf")],
                  BC(runner_mode="mock", output_dir=tmp_out))
        s.check("F25c", "运行中再次 create → 抛 E_TASK_BUSY", False, "未抛异常")
    except ApiError as exc:
        s.check("F25c", "运行中再次 create → 抛 E_TASK_BUSY",
                exc.code == ErrorCode.E_TASK_BUSY and exc.status_code in (409, 400),
                f"code={exc.code} status={exc.status_code}")

    # ---- F12 损坏 points.json（--report-only）----
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "bad.json"
        bad.write_text("{ this is not json", encoding="utf-8")
        out_html = Path(d) / "o.html"
        p = subprocess.run([PY, str(PROJECT_ROOT / "run.py"), "--report-only", str(bad),
                            "--out", str(out_html)], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        has_tb = "Traceback" in p.stderr
        has_cn = ("解析失败" in p.stderr or "结构不正确" in p.stderr) and "E_BAD_REQUEST" in p.stderr
        # CLI 报错退出非零码是正确的；关键是"结构化中文错误而非堆栈"
        s.check("F12", "损坏 points.json → 结构化中文错误（非堆栈）",
                (not has_tb) and has_cn,
                f"returncode={p.returncode} traceback={has_tb} stderr={p.stderr.strip()[:200]}")

    return s
