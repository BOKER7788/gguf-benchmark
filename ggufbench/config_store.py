"""``ConfigStore``：读写 ``config.json``，default_config 合并，PUT 增量 patch。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import CONFIG_FILE, DEFAULT_CONFIG_FILE
from .logging_utils import get_logger
from .models import BenchConfig

logger = get_logger("config")


def _load_json(path: Path) -> dict[str, Any]:
    """安全读取 JSON；失败返回空字典。"""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:  # pragma: no cover - 环境相关
        logger.warning("读取 %s 失败: %s", path, exc)
        return {}


class ConfigStore:
    """配置持久化：以 ``config/default_config.json`` 为初值，用户配置存于项目根 ``config.json``。"""

    def __init__(self, config_file: Path | None = None, default_file: Path | None = None) -> None:
        self.config_file: Path = Path(config_file) if config_file else CONFIG_FILE
        self.default_file: Path = Path(default_file) if default_file else DEFAULT_CONFIG_FILE
        self._config: BenchConfig | None = None

    # ---- 内部 ----
    def _merged_dict(self) -> dict[str, Any]:
        """default_config 与用户 config.json 合并（用户优先）。"""
        merged = _load_json(self.default_file)
        merged.update(_load_json(self.config_file))
        return merged

    # ---- 公开 API ----
    def load(self) -> BenchConfig:
        """加载配置（首次运行写出 ``config.json``；损坏时回退默认值）。"""
        if self._config is None:
            data = self._merged_dict()
            try:
                self._config = BenchConfig(
                    **{k: v for k, v in data.items() if k in BenchConfig.model_fields}
                )
            except Exception as exc:  # 配置文件被手工改坏 → 回退默认，保证可启动
                logger.warning("config.json 校验失败，回退默认配置: %s", exc)
                self._config = BenchConfig()
            # 首次运行：落盘完整配置
            if not self.config_file.exists():
                self.save(self._config.model_dump())
        return self._config

    def save(self, patch: dict[str, Any] | BenchConfig) -> BenchConfig:
        """增量更新配置并持久化，返回合并后的完整配置。"""
        current = self.load().model_dump()

        if isinstance(patch, BenchConfig):
            incoming = patch.model_dump()
        else:
            # 仅接受已知键，忽略 UI 未提交的运行期字段
            incoming = {k: v for k, v in patch.items() if k in BenchConfig.model_fields}

        # scan_result / llama_version 等运行期字段在 UI PUT 时可缺省，保留现有
        current.update(incoming)
        try:
            self._config = BenchConfig(**current)
        except Exception as exc:  # pydantic 校验失败
            logger.warning("配置校验失败，回退旧值: %s", exc)
            raise

        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with self.config_file.open("w", encoding="utf-8") as fh:
            json.dump(self._config.model_dump(), fh, ensure_ascii=False, indent=2)
        return self._config

    def set_runtime(self, **kwargs: Any) -> BenchConfig:
        """写入运行期字段（如 scan_result、llama_version）但不强制回写文件失败。"""
        assert self._config is not None
        data = self._config.model_dump()
        data.update(kwargs)
        self._config = BenchConfig(**data)
        return self._config


__all__ = ["ConfigStore"]
