"""REST 路由（M5）。

对外只暴露一个核心接口 POST /solve：收 SolveRequest，调用装箱引擎，返回 Solution。
处理函数为同步：solve() 是纯 CPU 计算，FastAPI 会自动放到线程池执行，不阻塞事件循环。
"""
from __future__ import annotations

from fastapi import APIRouter

from ..core.ga import solve_ga
from ..core.packer import solve
from ..models.schemas import Solution, SolveRequest

router = APIRouter()


@router.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/solve", response_model=Solution, tags=["solve"])
def solve_endpoint(request: SolveRequest) -> Solution:
    """对给定货品/托盘/容器与优化目标求装箱方案。

    use_ga=True 时用遗传算法对放置顺序做全局优化（更慢但通常更优）。
    前端拿到每个容器的 placements 后，按 seq 排序即可做装箱顺序回放。
    """
    return solve_ga(request) if request.use_ga else solve(request)
