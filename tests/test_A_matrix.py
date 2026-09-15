"""A. 数据与矩阵（P0）。

验证 ``BenchEngine.build_matrix`` 与 A7 ``/api/tasks/preview``：
- 每模型恰好 49 组；逐 ctx 分组 4/5/6/7/8/9/10；
- 每个组合都满足 input < ctx（逐组合断言，而非仅总数）；
- 边界：input == ctx 必须被排除。
"""

from __future__ import annotations

from _harness import Suite

from ggufbench.engine import BenchEngine
from ggufbench.models import BenchConfig

CTX = [4000, 8000, 16000, 32000, 64000, 128000, 256000]
INP = [250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000, 128000]
EXPECTED_PER_CTX = {4000: 4, 8000: 5, 16000: 6, 32000: 7, 64000: 8, 128000: 9, 256000: 10}


def run() -> Suite:
    s = Suite("A. 数据与矩阵")

    m = BenchEngine.build_matrix(CTX, INP)

    s.eq("A1", "每模型恰好 49 组", m["total"], 49)
    s.eq(
        "A2",
        "逐 ctx 分组 4/5/6/7/8/9/10",
        {k: len(v) for k, v in m["per_ctx"].items()},
        EXPECTED_PER_CTX,
    )

    # 逐组合断言 input < ctx（不只看总数）
    violations = [(c, i) for (c, i) in m["pairs"] if not (i < c)]
    s.check(
        "A3",
        "每个组合均满足 input < ctx",
        not violations,
        f"存在 {len(violations)} 个违规组合（前 5 个）: {violations[:5]}",
    )

    # pairs 数量与 per_ctx 求和一致
    s.eq("A3b", "pairs 数 == per_ctx 求和", len(m["pairs"]), sum(EXPECTED_PER_CTX.values()))

    # 边界：input == ctx 必须被排除
    m_eq = BenchEngine.build_matrix([4000], [4000])
    s.check(
        "A4",
        "边界 input == ctx 被排除",
        m_eq["total"] == 0 and 4000 not in m_eq["per_ctx"],
        f"total={m_eq['total']} per_ctx={m_eq['per_ctx']}",
    )

    # 边界：input > ctx 必须被排除
    m_gt = BenchEngine.build_matrix([1000], [2000])
    s.check("A4b", "边界 input > ctx 被排除", m_gt["total"] == 0, f"total={m_gt['total']}")

    # 无有效输入时该 ctx 不出现
    m_empty = BenchEngine.build_matrix([250], [250, 1000])
    s.check(
        "A4c",
        "某 ctx 无有效输入时被整体剔除",
        m_empty["total"] == 0 and 250 not in m_empty["per_ctx"],
        f"total={m_empty['total']} per_ctx={m_empty['per_ctx']}",
    )

    # 去重 + 升序
    m_dup = BenchEngine.build_matrix([8000, 4000, 4000], [500, 250, 250])
    s.eq(
        "A5",
        "去重并升序排列",
        m_dup["pairs"],
        [(4000, 250), (4000, 500), (8000, 250), (8000, 500)],
    )

    # 默认配置（BenchConfig 默认档位）也必须得到 49
    cfg = BenchConfig()
    m_def = BenchEngine.build_matrix(cfg.ctx_levels, cfg.input_levels)
    s.eq("A6", "BenchConfig 默认档位 == 49", m_def["total"], 49)

    # A7：真实 HTTP 契约（TestClient）
    try:
        from fastapi.testclient import TestClient

        from ggufbench.app import create_app

        client = TestClient(create_app())
        payload = {
            "models": [
                {"model_name": "M1", "model_size": "2B", "gguf_path": "/x/1.gguf"},
                {"model_name": "M2", "model_size": "4B", "gguf_path": "/x/2.gguf"},
            ],
            "config": {"ctx_levels": CTX, "input_levels": INP},
        }
        r = client.post("/api/tasks/preview", json=payload)
        body = r.json()
        s.eq("A7", "A7 状态码 200", r.status_code, 200)
        s.eq("A7b", "A7 每模型点数 49", [pm["points"] for pm in body["per_model"]], [49, 49])
        s.eq("A7c", "A7 total_points == 49×模型数", body["total_points"], 98)
        s.eq("A7d", "A7 matrix.total == 49", body["matrix"]["total"], 49)
    except Exception as exc:  # noqa: BLE001
        s.check("A7", "A7 /api/tasks/preview 可调用", False, repr(exc))

    return s
