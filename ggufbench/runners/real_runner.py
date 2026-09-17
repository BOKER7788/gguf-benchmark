"""``RealRunner``：真实子进程启停 + httpx 调 ``/health`` ``/tokenize`` ``/completion``。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from ..logging_utils import get_logger
from ..models import BenchConfig, ModelMeta, RunResult
from .base import DEFAULT_READY_TIMEOUT_S, LlamaServerRunner

logger = get_logger("real_runner")

_PROCESS_STOP_TIMEOUT_S = 5.0
_HEALTH_TIMEOUT_S = 2.0
_REQUEST_TIMEOUT_PAD_S = 30.0


class RealRunner(LlamaServerRunner):
    """基于子进程 + HTTP 的真实运行器。"""

    def __init__(
        self,
        config: BenchConfig,
        model: ModelMeta,
        ctx_size: int,
        log_dir: Path,
    ) -> None:
        super().__init__(config, model, ctx_size, log_dir)
        self._proc: subprocess.Popen | None = None
        self._stdout_fh = None
        self._stderr_fh = None
        self._base_url = f"http://{config.host}:{config.port}"

    # ---- 生命周期 ----
    def start(self) -> None:
        """启动 llama-server 子进程，stdout/stderr 重定向到日志文件。"""
        cmd = self.build_cmd()
        logger.info("启动 llama-server: %s", " ".join(cmd))
        stdout_path = self.log_dir / "llama_stdout.log"
        stderr_path = self.log_dir / "llama_stderr.log"
        # 追加模式，便于跨档位汇总
        self._stdout_fh = stdout_path.open("a", encoding="utf-8", errors="replace")
        self._stderr_fh = stderr_path.open("a", encoding="utf-8", errors="replace")
        self._stdout_fh.write(f"\n===== ctx={self.ctx_size} start={time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        self._stdout_fh.flush()

        kwargs: dict = {
            "stdout": self._stdout_fh,
            "stderr": self._stderr_fh,
            "cwd": str(self.log_dir),
        }
        if sys.platform.startswith("win"):
            # Windows：独立进程组，便于整树终止
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True

        self._proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603 - 用户显式配置的可执行文件

    def stop(self) -> None:
        """终止进程（先 terminate，超时后 kill 进程树）。"""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=_PROCESS_STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                self._kill_tree(proc)
            except OSError:  # pragma: no cover - 环境相关
                self._kill_tree(proc)
        self._proc = None
        for fh in (self._stdout_fh, self._stderr_fh):
            if fh is not None:
                try:
                    fh.close()
                except OSError:  # pragma: no cover
                    pass
        self._stdout_fh = None
        self._stderr_fh = None

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        """强制杀进程树。"""
        if sys.platform.startswith("win"):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                )
            except OSError:  # pragma: no cover
                pass
        else:  # pragma: no cover - POSIX
            import signal

            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass

    def is_alive(self) -> bool:
        """进程是否仍在运行。"""
        return self._proc is not None and self._proc.poll() is None

    # ---- 就绪探测 ----
    def wait_ready(self, timeout_s: float = DEFAULT_READY_TIMEOUT_S) -> bool:
        """轮询 ``/health``（架构 §7 ③）。"""
        deadline = time.time() + timeout_s
        with httpx.Client(timeout=_HEALTH_TIMEOUT_S, trust_env=False) as client:
            while time.time() < deadline:
                if not self.is_alive():
                    return False
                try:
                    resp = client.get(f"{self._base_url}/health")
                    if resp.status_code == 200:
                        status = ""
                        try:
                            status = str(resp.json().get("status", ""))
                        except ValueError:
                            status = resp.text
                        if status in ("ok", "no slot available", ""):
                            return True
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
        return False

    # ---- 推理接口 ----
    def tokenize(self, text: str) -> int:
        """POST ``/tokenize`` 返回 token 数。"""
        with httpx.Client(timeout=30.0, trust_env=False) as client:
            resp = client.post(f"{self._base_url}/tokenize", json={"content": text})
            resp.raise_for_status()
            data = resp.json()
        tokens = data.get("tokens")
        if isinstance(tokens, list):
            return len(tokens)
        return int(data.get("n_tokens", 0))

    def complete(self, prompt: str, n_predict: int) -> RunResult:
        """POST ``/completion``（非流式），解析 timings。"""
        payload = {
            "prompt": prompt,
            "n_predict": n_predict,
            "temperature": 0.0,
            "top_k": 1,
            "stream": False,
            # 必须显式关闭 prompt 缓存：llama-server 默认 cache_prompt=true，
            # 而引擎会先做一次「同 prompt」预热，正式测量请求的整段 prompt 会按
            # 最长公共前缀命中上一轮留下的 KV cache，timings.prompt_n 于是只剩
            # 几个新增 token（实测 251 → 4），prefill_tps 被低估约 50 倍。
            "cache_prompt": False,
        }
        timeout = self.config.prefill_timeout_s + _REQUEST_TIMEOUT_PAD_S
        try:
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                resp = client.post(f"{self._base_url}/completion", json=payload)
                if resp.status_code != 200:
                    return RunResult(
                        ok=False,
                        exit_code=resp.status_code,
                        stderr_tail=resp.text[:2000],
                    )
                data = resp.json()
        except httpx.TimeoutException:
            return RunResult(ok=False, timed_out=True, exit_code=-1, stderr_tail="request timeout")
        except httpx.HTTPError as exc:
            return RunResult(ok=False, exit_code=-1, stderr_tail=str(exc))

        timings = data.get("timings", {}) or {}
        return RunResult(
            prompt_tokens=int(timings.get("prompt_n", 0)),
            prompt_ms=float(timings.get("prompt_ms", 0.0)),
            predicted_tokens=int(timings.get("predicted_n", 0)),
            predicted_ms=float(timings.get("predicted_ms", 0.0)),
            exit_code=0,
            timed_out=False,
            stderr_tail="",
            ok=True,
        )


__all__ = ["RealRunner"]
