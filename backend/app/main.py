"""FastAPI 入口（M5）。

启动：在 backend/ 下 `uvicorn app.main:app --reload`
文档：启动后访问 /docs（Swagger UI）或 /openapi.json。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="3D 装箱 / 容器装载 API",
        version="0.1.0",
        description="启发式 3D 装箱引擎：多容器分配、可插拔目标、码托盘决策、物理约束。",
    )

    # 允许前端（Vite 默认 5173）跨域调用；开发期放开，部署时再收紧。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


app = create_app()
