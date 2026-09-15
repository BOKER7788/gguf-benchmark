"""``ModelScanner``：递归扫描 ``*.gguf``、忽略 mmproj、推断尺寸与精度。"""

from __future__ import annotations

import re
from pathlib import Path

from .errors import ApiError, ErrorCode
from .logging_utils import get_logger
from .models import ModelMeta, Precision

logger = get_logger("scanner")

# 尺寸解析：0.8B / 2B / 35B / 26B / 7b 等
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z0-9])")
# 分片 GGUF 命名：<base>-00001-of-00002.gguf
_SHARD_RE = re.compile(
    r"^(?P<base>.+?)-(?P<idx>\d{2,6})-of-(?P<total>\d{2,6})\.gguf$",
    re.IGNORECASE,
)
# 精度标记
_W8_TOKENS = ("q8", "w8a8", "int8", "fp8", "q8_0", "8bit")
_W4_TOKENS = ("q4", "w4a8", "int4", "q4_k", "q4_0", "4bit", "mxfp4", "iq4")


class ModelScanner:
    """扫描目录中的 GGUF 模型并生成 ``ModelMeta`` 列表。"""

    def scan(self, directory: str | Path, recursive: bool = True) -> list[ModelMeta]:
        """扫描目录。

        Args:
            directory: 目标目录。
            recursive: 是否递归子目录。

        Returns:
            候选模型列表（已过滤 mmproj）。

        Raises:
            ApiError: 目录不存在（E_DIR_NOT_FOUND）。
        """
        root = Path(directory).expanduser()
        if not root.exists() or not root.is_dir():
            raise ApiError(ErrorCode.E_DIR_NOT_FOUND, f"扫描目录不存在: {directory}")

        pattern = "**/*.gguf" if recursive else "*.gguf"
        metas: list[ModelMeta] = []
        shard_groups: dict[str, list[Path]] = {}
        shard_order: list[str] = []
        for path in sorted(root.glob(pattern)):
            if self.is_mmproj(path.name):
                logger.info("忽略 mmproj 文件: %s", path.name)
                continue
            match = _SHARD_RE.match(path.name)
            if match:
                # 分片文件按 <base>-NNNNN-of-MMMMM 归并为一个模型。
                # 归并键必须包含父目录：否则不同子目录下的同名分片模型
                # （如 A/model-00001-of-00002 与 B/model-00001-of-00002）
                # 会被误合并成一个，导致其中一个模型被静默漏测。
                key = f"{path.parent.resolve()}::{match.group('base')}::{match.group('total')}"
                if key not in shard_groups:
                    shard_groups[key] = []
                    shard_order.append(key)
                shard_groups[key].append(path)
            else:
                metas.append(self._build_meta(path))
        for key in shard_order:
            metas.append(self._build_shard_meta(shard_groups[key]))
        metas.sort(key=lambda m: m.model_name.lower())
        logger.info("扫描完成: 目录=%s 候选=%d（其中分片模型 %d）", root, len(metas), len(shard_order))
        return metas

    def list_ignored(self, directory: str | Path, recursive: bool = True) -> list[str]:
        """列出被忽略的 mmproj 文件名（供 UI 灰色展示"已忽略"）。"""
        root = Path(directory).expanduser()
        if not root.exists() or not root.is_dir():
            return []
        pattern = "**/*.gguf" if recursive else "*.gguf"
        return [p.name for p in sorted(root.glob(pattern)) if self.is_mmproj(p.name)]

    # ---- 判定与推断 ----
    @staticmethod
    def is_mmproj(filename: str) -> bool:
        """判断是否为 mmproj（视觉投影）文件，应被忽略。"""
        lowered = filename.lower()
        return "mmproj" in lowered or "mm_projector" in lowered

    @staticmethod
    def parse_size(filename: str) -> str:
        """从文件名推断模型尺寸，如 ``0.8B`` / ``35B``；失败返回 ``Unknown``。"""
        stem = Path(filename).stem
        match = _SIZE_RE.search(stem)
        if match:
            value = match.group(1)
            # 归一化：去掉多余小数 0（如 2.0B -> 2B）
            if "." in value:
                value = value.rstrip("0").rstrip(".")
            return f"{value}B"
        return "Unknown"

    @staticmethod
    def infer_precision(filename: str) -> Precision:
        """从文件名推断精度 w8a8 / w4a8；无法判断时默认 w8a8。"""
        lowered = filename.lower()
        # 先判 4bit（q4/mxfp4 等），再判 8bit，避免 "q4_k_m" 被 q8 误判
        for token in _W4_TOKENS:
            if token in lowered:
                return "w4a8"
        for token in _W8_TOKENS:
            if token in lowered:
                return "w8a8"
        return "w8a8"

    def _build_meta(self, path: Path) -> ModelMeta:
        """构造单个 ``ModelMeta``。"""
        try:
            size_mb = round(path.stat().st_size / (1024 * 1024), 2)
        except OSError:  # pragma: no cover - 环境相关
            size_mb = 0.0
        name = self._model_name(path)
        return ModelMeta(
            model_name=name,
            model_size=self.parse_size(path.name),
            gguf_path=str(path.resolve()),
            precision=self.infer_precision(path.name),
            precision_source="filename",
            file_size_mb=size_mb,
            selected=False,
            status="pending",
        )

    @staticmethod
    def _model_name(path: Path) -> str:
        """由文件名生成模型显示名（去扩展名，去掉常见量化后缀）。"""
        stem = path.stem
        return stem if stem else path.name

    def _build_shard_meta(self, paths: list[Path]) -> ModelMeta:
        """把同一模型的分片 GGUF 合并为单个 ``ModelMeta``（尺寸求和）。"""
        ordered = sorted(paths, key=lambda p: p.name)
        first = ordered[0]
        match = _SHARD_RE.match(first.name)
        base = match.group("base") if match else first.stem
        total_mb = 0.0
        for path in ordered:
            try:
                total_mb += path.stat().st_size / (1024 * 1024)
            except OSError:  # pragma: no cover - 环境相关
                continue
        return ModelMeta(
            model_name=base,
            model_size=self.parse_size(first.name),
            gguf_path=str(first.resolve()),
            precision=self.infer_precision(first.name),
            precision_source="filename",
            file_size_mb=round(total_mb, 2),
            selected=False,
            status="pending",
        )


__all__ = ["ModelScanner"]
