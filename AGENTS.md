# 仓库指南

## 项目结构与模块组织

本仓库是一个 3D 容器装载应用，包含 FastAPI 后端和 React/Vite 前端。后端源码位于 `backend/app/`：`api/` 放接口路由，`models/` 放 Pydantic 数据模型，`core/` 放装箱算法、约束、几何和目标函数。后端测试位于 `backend/tests/`，由 `backend/pytest.ini` 配置。前端源码位于 `frontend/src/`：`components/` 放 React 组件，`three/` 放 Three.js 场景代码，`store/` 放 Zustand 状态，`api/` 放请求封装，`utils/` 放共享工具函数。启动脚本位于根目录和 `scripts/`。

## 构建、测试与本地开发命令

- `.\start.ps1`：在 Windows PowerShell 中同时启动后端 8000 端口和前端 5173 端口。
- `.\scripts\start-backend.ps1`：通过 conda 启动 `uvicorn app.main:app --port 8000 --reload`。
- `.\scripts\start-frontend.ps1`：启动 Vite 开发服务器。
- `conda run -n packaging python -m pytest backend -q`：运行后端测试套件。
- `cd frontend && npm run dev`：仅启动前端开发服务器。
- `cd frontend && npm run build`：构建前端生产产物。

后端依赖使用 `pip install -r backend/requirements.txt` 安装；前端依赖在 `frontend/` 下使用 `npm install` 安装。

## 代码风格与命名约定

Python 使用 4 空格缩进，优先补充清晰的类型标注，并按职责拆分小模块。函数、变量和测试文件使用描述性的 snake_case 命名。React 代码使用 ES modules、函数组件、Hooks 和 2 空格缩进；组件文件使用 PascalCase，例如 `ResultPanel.jsx`。可复用前端逻辑应放入 `frontend/src/utils/`，避免散落在组件中。

## 测试指南

后端使用 `pytest`，测试根目录配置为 `backend`。新增测试文件命名为 `test_*.py`，例如 `test_constraints.py` 或 `test_multi_customer_delivery.py`。修改装箱约束、几何放置、API 请求/响应结构或目标函数评分时，应补充回归测试。当前未配置前端测试框架；UI 变更至少运行 `npm run build`，并在本地浏览器验证主要交互。

## 提交与 Pull Request 规范

近期提交使用简短的祈使句标题，例如 `Add multi-customer delivery packing support`。保持同样风格：以动词开头，主题聚焦，不把无关改动混在同一次提交中。Pull Request 应包含简要说明、已运行的测试命令、相关 issue 链接；涉及可见 UI 变化时附截图。

## 安全与配置提示

不要提交本地环境文件、生成缓存或依赖目录。前端通过 `frontend/vite.config.js` 将 `/api/*` 代理到 `http://127.0.0.1:8000`；如果修改开发端口或部署域名，需要同步检查后端 CORS 配置。

## 编码与终端约定

所有文本文件使用 UTF-8 编码；PowerShell 脚本保留 UTF-8 BOM，以兼容 Windows PowerShell 5.1 对中文脚本的读取。启动脚本会加载 `scripts/set-utf8.ps1`，统一设置控制台输出、`PYTHONUTF8=1` 和 `PYTHONIOENCODING=utf-8`。在 PowerShell 中查看中文文件时优先使用 `Get-Content -Encoding UTF8 <path>`，避免旧版 PowerShell 将无 BOM 的 UTF-8 文件按系统 ANSI 编码显示。新增脚本或文档时遵守 `.editorconfig`；不要绕过 `.gitattributes` 中的换行规则，`.sh` 保持 LF，`.ps1` 保持 CRLF。
