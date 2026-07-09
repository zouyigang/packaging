"""REST 路由（M5）。

对外只暴露一个核心接口 POST /solve：收 SolveRequest，调用装箱引擎，返回 Solution。
处理函数为同步：solve() 是纯 CPU 计算，FastAPI 会自动放到线程池执行，不阻塞事件循环。
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter

from ..core.ga import GAConfig, solve_ga
from ..core.packer import solve
from ..models.schemas import Solution, SolveRequest

router = APIRouter()
logger = logging.getLogger("uvicorn.error")


@router.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/solve", response_model=Solution, tags=["solve"])
def solve_endpoint(request: SolveRequest) -> Solution:
    """对给定货品/托盘/容器与优化目标求装箱方案。

    use_ga=True 时用遗传算法对放置顺序做全局优化（更慢但通常更优）。
    前端拿到每个容器的 placements 后，按 seq 排序即可做装箱顺序回放。
    """
    if request.use_ga:
        solution = solve_ga(request, GAConfig.for_speed(request.ga_speed, seed=secrets.randbits(32)))
    else:
        solution = solve(request)
    _log_performance(request, solution)
    return solution


def _log_performance(request: SolveRequest, solution: Solution) -> None:
    perf = solution.performance
    if perf is None:
        return
    logger.info(
        "solve completed mode=%s objective=%s runtime_ms=%.3f stages_ms=%s counters=%s",
        "ga" if request.use_ga else "heuristic",
        request.objective,
        perf.runtime_ms,
        perf.stages_ms,
        perf.counters,
    )
