"""``TaskManager``：任务生命周期、TaskStatus 快照、abort、SSE 订阅广播。"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

from .errors import ApiError, ErrorCode
from .logging_utils import get_logger
from .models import BenchConfig, BenchmarkPoint, ModelMeta, TaskStatus

logger = get_logger("task_manager")


@dataclass
class _Task:
    """运行期任务记录。"""

    task_id: str
    engine: object
    models: list[ModelMeta]
    last_status: dict = field(default_factory=dict)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    thread: threading.Thread | None = None
    finished: bool = False


class TaskManager:
    """全局单任务管理器（架构决策：串行）。"""

    def __init__(self) -> None:
        self._tasks: dict[str, _Task] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """绑定事件循环，用于从工作线程安全投递 SSE 消息。"""
        self._loop = loop

    # ---- 查询 ----
    def is_busy(self) -> bool:
        """是否存在正在运行/中断中的任务。"""
        with self._lock:
            return any(
                t.last_status.get("state") in ("running", "aborting") for t in self._tasks.values()
            )

    def get(self, task_id: str) -> TaskStatus:
        """获取任务状态快照。"""
        task = self._get_task(task_id)
        if task.last_status:
            return TaskStatus(**task.last_status)
        return TaskStatus(task_id=task_id, state="idle")

    def points(self, task_id: str, model: str | None = None) -> list[BenchmarkPoint]:
        """获取已采集数据点（可选按模型过滤）。"""
        task = self._get_task(task_id)
        engine = task.engine
        all_points: list[BenchmarkPoint] = getattr(engine, "points", [])
        if model:
            return [p for p in all_points if p.model_name == model]
        return list(all_points)

    def reports(self, task_id: str) -> list[str]:
        """获取任务生成报告路径列表。"""
        task = self._get_task(task_id)
        return [str(p) for p in getattr(task.engine, "reports", [])]

    def engine_of(self, task_id: str) -> object:
        """获取任务对应的引擎实例（A14 重建总览用）。"""
        return self._get_task(task_id).engine

    def models_of(self, task_id: str) -> list[ModelMeta]:
        """获取任务本次执行选择的模型列表。"""
        return list(self._get_task(task_id).models)

    def current_runner(self):
        """返回当前运行中的运行器（A6 tokenize 代理用），无则 None。"""
        with self._lock:
            tasks = list(self._tasks.values())
        for task in tasks:
            if task.last_status.get("state") in ("running", "aborting"):
                runner = getattr(task.engine, "_current_runner", None)
                if runner is not None:
                    return runner
        return None

    # ---- 创建 / 中断 ----
    def create(self, task_id: str, models: list[ModelMeta], config: BenchConfig) -> str:
        """创建并后台启动任务，返回 task_id（签名遵循架构 §3.2）。"""
        from .engine import BenchEngine

        if self.is_busy():
            raise ApiError(ErrorCode.E_TASK_BUSY, "已有任务正在运行，请先等待完成或中断")

        tid = task_id or uuid.uuid4().hex[:12]

        def _on_event(payload: dict) -> None:
            self._on_event(tid, payload)

        engine = BenchEngine(config, on_event=_on_event)
        engine.status.task_id = tid

        task = _Task(task_id=tid, engine=engine, models=list(models))
        with self._lock:
            self._tasks[tid] = task

        # 立即写入初始快照，避免首帧为空
        self._apply_event(tid, {"type": "state", "status": engine.status.model_dump()})

        thread = threading.Thread(target=self._run_engine, args=(tid, engine, models), daemon=True)
        task.thread = thread
        thread.start()
        logger.info("任务已创建: %s models=%d", tid, len(models))
        return tid

    def abort(self, task_id: str) -> bool:
        """中断任务（已结束的任务拒绝中断）。"""
        task = self._get_task(task_id)
        current = self.get(task_id)
        if task.finished or current.state in ("done", "error"):
            raise ApiError(ErrorCode.E_TASK_BUSY, "任务已结束，无法中断")
        engine = task.engine
        try:
            engine.abort()  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover
            logger.warning("中断失败: %s", exc)
            return False
        self._apply_event(task_id, {"type": "state", "status": self._snapshot_with_state(engine, "aborting")})
        return True

    # ---- SSE ----
    async def subscribe(self, task_id: str) -> AsyncIterator[str]:
        """SSE 订阅：产出 ``data: {json}\\n\\n`` 文本流。"""
        task = self._get_task(task_id)
        queue: asyncio.Queue = asyncio.Queue()
        task.subscribers.append(queue)

        # 先推送当前快照
        current = task.last_status or self.get(task_id).model_dump()
        yield self._sse(current)

        if task.finished:
            yield self._sse({"type": "done", "status": current})
            self._remove_subscriber(task, queue)
            return

        try:
            while True:
                payload = await queue.get()
                yield self._sse(payload)
                if payload.get("type") in ("done", "error"):
                    break
        finally:
            self._remove_subscriber(task, queue)

    # ---- 内部 ----
    def _get_task(self, task_id: str) -> _Task:
        """按 id 获取任务，不存在抛 E_TASK_NOT_FOUND。"""
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise ApiError(ErrorCode.E_TASK_NOT_FOUND, f"任务不存在: {task_id}")
        return task

    def _run_engine(self, task_id: str, engine: object, models: list[ModelMeta]) -> None:
        """后台线程执行引擎。"""
        try:
            engine.run(models)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - 顶层兜底
            logger.exception("任务 %s 执行失败: %s", task_id, exc)
            self._apply_event(task_id, {"type": "error", "status": {"task_id": task_id, "state": "error",
                                                                   "message": str(exc)}})
        finally:
            with self._lock:
                task = self._tasks.get(task_id)
                if task is not None:
                    task.finished = True

    def _on_event(self, task_id: str, payload: dict) -> None:
        """工作线程回调：更新快照并广播。"""
        self._apply_event(task_id, payload)
        with self._lock:
            task = self._tasks.get(task_id)
            subscribers = list(task.subscribers) if task else []
        loop = self._loop
        if loop is None:
            return
        for queue in subscribers:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except RuntimeError:  # pragma: no cover - 事件循环已关闭
                pass

    def _apply_event(self, task_id: str, payload: dict) -> None:
        """把事件中的 status 快照写入任务。"""
        status = payload.get("status")
        if status:
            with self._lock:
                task = self._tasks.get(task_id)
                if task is not None:
                    task.last_status = status

    @staticmethod
    def _snapshot_with_state(engine: object, state: str) -> dict:
        """基于引擎状态构造指定 state 的快照。"""
        try:
            snapshot = engine.status.model_dump()  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            snapshot = {}
        snapshot["state"] = state
        return snapshot

    @staticmethod
    def _remove_subscriber(task: _Task, queue: asyncio.Queue) -> None:
        """移除订阅者。"""
        try:
            task.subscribers.remove(queue)
        except ValueError:
            pass

    @staticmethod
    def _sse(payload: dict) -> str:
        """序列化一条 SSE 消息（转义 ``<`` 防止 ``</script>`` 问题）。"""
        text = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
        return f"data: {text}\n\n"


__all__ = ["TaskManager"]
