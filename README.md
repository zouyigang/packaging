# 3D 装箱 / 容器装载系统

一个 3D 装箱（Container Loading）系统：录入「货品 / 托盘 / 容器」的信息与数量，
由启发式算法给出装箱方案，并在前端做 **3D 可视化 + 装箱顺序逐步回放**。

3D 装箱属 NP-hard，本项目采用「极点启发式 + 可选遗传算法(BRKGA)」求高质量近似解。

## 功能特性

- **多容器自动分配**：按录入的容器类型与数量自动开箱装载，装不下的进入余货清单。
- **可插拔优化目标**（运行时切换）：最大空间利用率 / 最少容器数 / 稳定性优先 / 综合平衡。
- **直接装 vs 码托盘决策**：托盘是算法的可选手段，按当前目标对每件/每批货品择优，不写死流程。
- **完整物理约束**：不越界/不重叠、容器载重上限、堆叠承重（易碎品不被压）、防悬空支撑、朝向限制。
- **GA 全局优化**（可选）：以放置顺序为基因、极点启发式为解码器，进一步提升装载质量。
- **可视化**：3D 场景 + 按 `seq` 的顺序回放、2D 俯视装载图、CSV 报表导出。

## 技术栈

- 后端：FastAPI + Pydantic + NumPy，装箱引擎纯 Python、可独立测试。
- 前端：React + Vite + react-three-fiber + Ant Design + zustand。

## 快速开始

### 前置条件（需自行安装）
- **Anaconda / Miniconda**（提供 `conda` 命令，用于后端 Python 环境）。
- **Node.js ≥ 18**（自带 `npm`，用于前端）。
  在终端执行 `conda --version`、`node -v`、`npm -v` 能打印版本即说明已就绪。

### 首次安装（从 git 拉取代码后）

> 下面假设已 `git clone` 并进入项目根目录（含 `backend/`、`frontend/` 两个子目录）。

#### 1) 后端：创建 conda 环境并安装依赖

```bash
# 在项目根目录执行。创建名为 packaging 的环境（Python 3.12）
conda create -n packaging python=3.12 -y

# 激活环境
conda activate packaging        # 若提示未初始化，先执行 conda init 后重开终端

# 安装后端三方包（fastapi / uvicorn / pydantic / numpy / pytest / httpx）
cd backend
pip install -r requirements.txt
cd ..
```

> 环境名可自取，但**必须叫 `packaging`**才能直接用本仓库的启动脚本（脚本里写死了 `-n packaging`）；
> 若用别的名字，请相应改 `scripts/*.ps1`、`start.sh` 里的环境名，或改用「手动启动」里激活环境后的命令。

验证后端依赖装好：

```bash
conda run -n packaging python -m pytest backend -q      # 应显示全部测试通过
```

#### 2) 前端：安装 node 依赖

```bash
cd frontend
npm install            # 读取 package.json，生成 node_modules（首次较慢，需联网）
cd ..
```

> 国内网络慢可临时换源：`npm install --registry=https://registry.npmmirror.com`。

装好后即可用下面任意方式启动。

### 一键启动

```powershell
# Windows PowerShell（项目根目录）
.\start.ps1        # 在两个新窗口分别拉起后端(8000) 与 前端(5173)
```

```bash
# Git Bash / WSL
bash start.sh
```

启动后浏览器打开 **http://localhost:5173**，页面自带一组示例数据，直接点「求解装箱」即可。

### 分别启动 / 手动启动

```powershell
.\scripts\start-backend.ps1     # 仅后端
.\scripts\start-frontend.ps1    # 仅前端（首次自动 npm install）
```

```bash
# 后端
cd backend
conda run --no-capture-output -n packaging uvicorn app.main:app --port 8000 --reload
# 前端（另开终端）
cd frontend
npm install        # 首次
npm run dev
```

> 前端开发服务器把 `/api/*` 代理到后端 `http://127.0.0.1:8000`（见 `frontend/vite.config.js`），无需额外处理跨域。

### 常见问题

- **`conda activate` 报 "not initialized"**：先执行 `conda init`（PowerShell 用 `conda init powershell`），关闭并重开终端再试。
- **`conda` / `npm` 找不到命令**：未装或未加入 PATH，确认前置条件已安装。
- **端口被占用**：后端默认 8000、前端默认 5173。先关掉占用进程，或改端口（后端 `--port`，前端 `npm run dev -- --port 5174` 并相应改 `vite.config.js` 代理目标）。
- **页面点「求解装箱」无反应/报错**：多半是后端没起或端口不对。确认后端窗口在跑、能访问 http://127.0.0.1:8000/health 返回 `{"status":"ok"}`。
- **Windows 下 `.ps1` 脚本不让运行**：用 `powershell -ExecutionPolicy Bypass -File .\start.ps1`，或对当前用户放开：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

## 使用

1. 在左侧表格编辑货品 / 托盘 / 容器及数量。
2. 选择优化目标；如需更优解可打开「GA 优化」开关（更慢）。
3. 点「求解装箱」。
4. 右侧查看 **3D** 装载结果，用底部滑块或「回放」按 `seq` 逐步播放；多容器用分段器切换。
5. 切到 **2D 俯视** 看俯视装载图；点「导出 CSV」下载报表。

## 接口

`POST /solve`（另有 `GET /health`，文档见 `/docs`）

请求体：
```json
{ "items": [], "pallets": [], "containers": [], "objective": "max_utilization", "use_ga": false }
```
响应体：
```json
{ "containers": [ { "id": "...", "placements": [ { "item_id": "...", "pallet_id": null,
  "x": 0, "y": 0, "z": 0, "orientation": "LWH", "seq": 1 } ],
  "volume_utilization": 0.0, "weight_utilization": 0.0 } ], "unpacked": [] }
```

单位：尺寸 mm、重量 kg。坐标系原点在容器内一个底角，x=长、y=宽、z=高(向上)。

## 测试

```bash
conda run -n packaging python -m pytest backend -q     # 64 个单元测试
```

## 目录结构

```
backend/
  app/
    main.py            FastAPI 入口（create_app + CORS）
    api/routes.py      POST /solve · GET /health
    models/schemas.py  Pydantic 数据模型
    core/
      geometry.py      朝向→尺寸、AABB 越界/重叠
      space.py         极点集合
      extreme_point.py 极点放置 + 评分
      constraints.py   支撑/堆叠承重校验
      objectives.py    可插拔优化目标（策略）
      palletizer.py    码托盘逻辑与「直接装 vs 码托盘」决策
      packer.py        多容器编排主循环
      ga.py            BRKGA 全局优化
  tests/               引擎单元测试
frontend/
  src/
    components/        编辑表格、结果/回放面板、2D 俯视
    three/             3D 场景 + 朝向几何
    store/             zustand 状态
    api/ utils/        调用 /solve、CSV 导出
start.ps1 / start.sh   一键启动
scripts/               分项启动脚本
CLAUDE.md              设计说明与里程碑进度
```

## 状态

里程碑 M1~M7 全部完成（引擎 + 约束 + 码托盘 + REST + 3D/2D 可视化 + GA），端到端可用。
后续可增强：GA 朝向基因、传递式承重、门洞约束、大算例性能优化。
