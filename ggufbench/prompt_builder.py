"""``PromptBuilder``：内置中性长文本、按目标 token 填充/截断、``/tokenize`` 校准。"""

from __future__ import annotations

from typing import Protocol

from .logging_utils import get_logger

logger = get_logger("prompt")

# 内置中性中文长文本（技术文档片段风格，无敏感内容）
DEFAULT_BASE_TEXT = (
    "本地大语言模型的推理性能取决于多个相互作用的因素。首先，权重与激活的量化精度直接影响显存占用与计算吞吐；"
    "在同样的硬件条件下，较低的位宽通常带来更高的解码速度，但可能牺牲一定的输出质量。"
    "其次，上下文长度决定了键值缓存（KV cache）的规模，随着上下文窗口的增长，显存压力呈线性上升，"
    "在统一内存架构（UMA）的设备上尤其需要关注可用的显存划分。"
    "再次，批处理大小、线程数与后端驱动（如 Vulkan、ROCm、CUDA）共同决定了并行计算的效率。"
    "预热阶段可以缓解冷启动抖动，多次重复测量并取中位数能够降低系统噪声带来的偏差。"
    "在评估一个模型时，我们通常分别记录预填充（prefill）与解码（decode）两个阶段的吞吐率："
    "预填充反映模型处理长输入的速度，解码反映逐 token 生成的速度。"
    "为了获得可复现的结论，应当固定提示词内容、采样参数与运行环境，并在报告中记录完整的启动命令。"
    "本工具通过扫描本地模型目录、按上下文与输入长度两个维度构造测试矩阵，"
    "对每个组合执行预热与重复测量，最终生成完全离线、可分享的可视化报告。"
)


class _Tokenizer(Protocol):
    """最小 tokenize 协议（避免与 runners 包循环依赖）。"""

    def tokenize(self, text: str) -> int:  # pragma: no cover - 协议
        ...


class PromptBuilder:
    """按目标 token 数构造提示词，并可用 ``/tokenize`` 校准到真实 token 数。"""

    def __init__(self, base_text: str = "", *, char_per_token: float = 4.0) -> None:
        self.base_text: str = base_text.strip() or DEFAULT_BASE_TEXT
        self.char_per_token: float = char_per_token

    # ---- 公开 API ----
    def build(self, target_tokens: int, runner: _Tokenizer | None = None) -> str:
        """构造目标 token 数的提示词。

        Args:
            target_tokens: 目标 token 数（<=0 时返回 base_text）。
            runner: 若提供且已 ready，则用 ``/tokenize`` 校准到误差 < 2%（架构 Q14）。

        Returns:
            构造好的提示词文本。
        """
        if target_tokens <= 0:
            return self.base_text

        # 1) 粗略按字符估算长度并拼接
        char_target = max(1, int(target_tokens * self.char_per_token))
        text = self._grow_to(char_target)

        # 2) 用真实 tokenizer 校准
        if runner is not None:
            text = self._calibrate(text, target_tokens, runner)
        return text

    # ---- 内部 ----
    def _grow_to(self, char_target: int) -> str:
        """把 base_text 循环拼接/截断到指定字符长度。"""
        base = self.base_text
        if len(base) >= char_target:
            return base[:char_target]
        repeats = char_target // len(base) + 1
        return (base * repeats)[:char_target]

    def _calibrate(self, text: str, target_tokens: int, runner: _Tokenizer) -> str:
        """用 tokenizer 迭代微调，使真实 token 数逼近目标（误差 < 2%）。"""
        best_text = text
        best_diff = float("inf")
        for _ in range(6):
            try:
                real = runner.tokenize(text)
            except Exception as exc:  # pragma: no cover - 运行器相关
                logger.warning("tokenize 校准失败，使用估算结果: %s", exc)
                return text
            if real <= 0:
                return text
            diff = abs(real - target_tokens) / max(1, target_tokens)
            if diff < best_diff:
                best_diff = diff
                best_text = text
            if diff < 0.02:
                return text
            ratio = target_tokens / real
            new_len = max(1, int(len(text) * ratio))
            text = self._grow_to(new_len)
        return best_text


__all__ = ["PromptBuilder", "DEFAULT_BASE_TEXT"]
