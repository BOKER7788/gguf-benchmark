"""模型体量与内存的可行性判断（v1.1.2）。

**为什么需要这个模块**：v1.1.1 及更早版本既不在报告里显示模型体积、也不做任何
可行性校验，于是「224 GB 的 397B 在 64 GB 机器上显示测试成功」这种结论可以毫无
阻拦地产生。这里把「模型权重体积 vs 本机可用内存」这条一秒就能算清的算术，
变成一个显式、可展示、可拦截的结论。

单位约定：统一用 **GiB**（1 GiB = 1024³ 字节），与 Windows「内存」显示口径一致。
``ModelMeta.file_size_mb`` 来自扫描器对分片求和，已是真实字节数。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import HardwareInfo, ModelMeta

# 权重之外还要留给系统 / KV cache / 计算缓冲的余量：权重最多占物理内存的 90%
_HEADROOM_RATIO = 0.90
# 超过容量的 80% 即视为「紧张」，即便能加载也会很慢
_TIGHT_RATIO = 0.80

LEVEL_UNKNOWN = "unknown"
LEVEL_OK = "ok"
LEVEL_TIGHT = "tight"
LEVEL_IMPOSSIBLE = "impossible"

_LEVEL_ORDER = {
    LEVEL_UNKNOWN: 0,
    LEVEL_OK: 1,
    LEVEL_TIGHT: 2,
    LEVEL_IMPOSSIBLE: 3,
}


def weights_gib(file_size_mb: float) -> float:
    """模型文件体积 → GiB。"""
    return max(0.0, float(file_size_mb or 0.0)) * 1_048_576.0 / (1024 ** 3)


def memory_capacity_gb(hw: HardwareInfo) -> float:
    """可用于容纳模型权重的内存上限（GB）。

    - UMA 核显（本工具的主要目标机形态）：显存与系统**共享**同一块物理内存，
      因此上限就是物理内存，不能把「显存」再加一遍。
    - 独立显卡且显存大于物理内存时，按两者之和估算。
    - 内存未知（未采集到）时退化为显存值；都未知则返回 0，由调用方判为「无法判断」。
    """
    ram = float(hw.ram_gb or 0.0)
    vram = float(hw.uma_vram_gb or 0.0)
    if ram <= 0:
        return vram
    if vram > ram:
        return ram + vram
    return ram


@dataclass
class Verdict:
    """单个模型的可行性结论。"""

    model_name: str
    level: str = LEVEL_UNKNOWN
    weights_gib: float = 0.0
    capacity_gb: float = 0.0
    detail: str = ""
    reasons: list[str] = field(default_factory=list)

    @property
    def is_impossible(self) -> bool:
        return self.level == LEVEL_IMPOSSIBLE

    @property
    def needs_attention(self) -> bool:
        return self.level in (LEVEL_TIGHT, LEVEL_IMPOSSIBLE)

    def short(self) -> str:
        """一行摘要，供进度提示 / 任务日志使用。"""
        if self.level == LEVEL_UNKNOWN:
            return f"{self.model_name}: 体量或内存未知，无法预判"
        return (
            f"{self.model_name}: 权重 {self.weights_gib:.1f} GiB / "
            f"可用 {self.capacity_gb:.1f} GB → {_LEVEL_LABEL[self.level]}"
        )


_LEVEL_LABEL = {
    LEVEL_UNKNOWN: "无法判断",
    LEVEL_OK: "可以加载",
    LEVEL_TIGHT: "内存紧张",
    LEVEL_IMPOSSIBLE: "物理上装不下",
}


def judge(meta: ModelMeta, hw: HardwareInfo) -> Verdict:
    """判断单个模型在本机是否可能加载成功（只看权重 vs 内存）。"""
    weights = weights_gib(meta.file_size_mb)
    capacity = memory_capacity_gb(hw)

    if weights <= 0 or capacity <= 0:
        missing = []
        if weights <= 0:
            missing.append("模型体积")
        if capacity <= 0:
            missing.append("本机内存")
        return Verdict(
            model_name=meta.model_name,
            level=LEVEL_UNKNOWN,
            weights_gib=weights,
            capacity_gb=capacity,
            detail=f"未能采集到{'与'.join(missing)}，无法判断可行性。",
        )

    headroom = capacity * _HEADROOM_RATIO
    ratio = weights / capacity

    if weights > headroom:
        return Verdict(
            model_name=meta.model_name,
            level=LEVEL_IMPOSSIBLE,
            weights_gib=weights,
            capacity_gb=capacity,
            detail=(
                f"模型权重 {weights:.1f} GiB，本机可用内存约 {capacity:.1f} GB"
                f"（{ratio:.2f} 倍）。仅权重就已超出内存上限，"
                "无论量化方式如何都无法加载 —— 真实模式下只会失败或长时间卡死，"
                "若报告里出现成功数据，那一定不是本机真实推理的结果。"
            ),
            reasons=[
                "换更小的量化版本（如 Q4_K_M 降到 Q2_K / IQ2）",
                "换参数量更小的模型",
                "增加物理内存，或改用显存更大的独立显卡",
            ],
        )

    if ratio > _TIGHT_RATIO:
        return Verdict(
            model_name=meta.model_name,
            level=LEVEL_TIGHT,
            weights_gib=weights,
            capacity_gb=capacity,
            detail=(
                f"模型权重 {weights:.1f} GiB，本机可用内存约 {capacity:.1f} GB"
                f"（占 {ratio * 100:.0f}%）。能加载，但留给 KV cache 与系统的余量很少，"
                "大上下文档位很可能显存/内存不足（OOM），建议先试跑 1 个档位确认。"
            ),
            reasons=[
                "先把上下文档位调小（如 4K/8K）试跑",
                "关闭其他占内存的应用后重试",
            ],
        )

    return Verdict(
        model_name=meta.model_name,
        level=LEVEL_OK,
        weights_gib=weights,
        capacity_gb=capacity,
        detail=(
            f"模型权重 {weights:.1f} GiB，本机可用内存约 {capacity:.1f} GB"
            f"（占 {ratio * 100:.0f}%），可以加载。"
        ),
    )


def judge_all(
    models: list[ModelMeta], hw: HardwareInfo
) -> list[Verdict]:
    """批量判断，保持传入顺序。"""
    return [judge(m, hw) for m in models]


def worst_level(verdicts: list[Verdict]) -> str:
    """取最严重的一档，供总览汇总使用。"""
    if not verdicts:
        return LEVEL_UNKNOWN
    return max((v.level for v in verdicts), key=lambda lv: _LEVEL_ORDER.get(lv, 0))


def has_impossible(verdicts: list[Verdict]) -> bool:
    """是否存在物理上装不下的模型。"""
    return any(v.is_impossible for v in verdicts)


__all__ = [
    "LEVEL_IMPOSSIBLE",
    "LEVEL_OK",
    "LEVEL_TIGHT",
    "LEVEL_UNKNOWN",
    "Verdict",
    "has_impossible",
    "judge",
    "judge_all",
    "memory_capacity_gb",
    "weights_gib",
    "worst_level",
]
