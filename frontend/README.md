# 前端（3D 装箱可视化）

React + Vite + react-three-fiber + Ant Design + zustand。

## 运行

```bash
npm install
npm run dev        # http://localhost:5173
```

开发服务器把 `/api/*` 代理到后端 `http://127.0.0.1:8000`（见 `vite.config.js`），
所以请先在 `backend/` 启动 FastAPI：

```bash
conda run -n packaging uvicorn app.main:app --reload
```

## 结构

- `src/components/` — Ant Design 编辑表格（货品/托盘/容器）、优化目标选择、结果与回放面板。
- `src/three/` — react-three-fiber 3D 场景；`geometry.js` 的朝向映射与后端 `core/geometry.py` 一致。
- `src/store/` — zustand 全局状态（含示例数据，打开即可求解）。
- `src/api/` — 调用后端 `POST /solve`。

## 用法

打开页面已带一组示例数据，直接点「求解装箱」即可看到 3D 装载结果；
用底部滑块或「回放」按钮按装箱顺序（seq）逐步播放；多容器用分段器切换。
