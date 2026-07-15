# 3D 装箱 / 容器装载系统

一个 3D 装箱（Container Loading）系统：录入「货品 / 托盘 / 容器」的信息与数量，由启发式算法给出装箱方案，并在前端做 3D/2D 可视化、装箱顺序回放、客户与货品筛选、CSV 报表导出。

3D 装箱属 NP-hard，本项目采用「极点启发式 + 可选遗传算法（BRKGA）」求高质量近似解。算法支持多容器、多目标、托盘化、堆叠约束、重心评估、多客户配送和卸货顺序。

## 功能特性

- **多容器自动分配**：按录入的容器类型与数量自动开箱装载，装不下的进入余货清单。
- **工业化策略目录**：支持成本效率、空间利用、安全装载、顺序配送和高级自定义；旧策略名继续作为兼容别名。
- **多客户配送与卸货顺序**：货品可配置客户、订单、目的地、卸货顺序；装卸策略会按入口和卸货顺序安排位置，并尽量聚集同客户/订单货品。
- **直接装 vs 码托盘决策**：托盘是算法的可选资源，按当前目标对货品择优决定直接装箱或先码托盘再装箱。
- **工业校验**：除几何、载重、朝向、支撑和递归承重外，可校验门洞、设备重心范围、载荷分布曲线、地板载荷及固定能力需求。
- **装货入口配置**：容器可配置后门、前门、左右侧门、顶部吊装等入口，影响装载位置评分和回放顺序。
- **GA 全局优化**：可选 BRKGA，以放置顺序为基因、极点启发式为解码器，进一步提升装载质量。
- **3D/2D 可视化**：3D 场景、2D 俯视图、托盘底板、重心标记、按 `seq` 的顺序回放。
- **客户/货品联动筛选**：装载视图支持客户筛选和二级货品筛选；客户按卸货顺序排列，货品选项随客户联动。
- **货品卡片信息增强**：左侧货品卡片显示客户、卸货顺序、同客户色系标识；不同货品在同客户色系下有轻微色差，便于识别。
- **弹窗式新增/编辑**：货品、托盘、容器新增时先弹窗编辑，确认后回填；编辑复用同一套字段控件。
- **CSV 导出**：导出每个放置项的容器、顺序、货品、托盘、客户、订单、目的地、卸货顺序、位置、朝向和尺寸。
- **内置测试数据**：页面默认加载一组多客户、多货品、托盘和 20GP 容器数据，刷新或重启前端后可直接测试。

## 技术栈

- 后端：FastAPI + Pydantic + NumPy，装箱引擎纯 Python，可独立测试。
- 前端：React + Vite + react-three-fiber + Ant Design + zustand。

## 快速开始

### Docker 一键启动（推荐）

只需要本机已安装 Docker，无需安装 conda、Python、Node.js 或 npm。

```bash
docker compose up --build
```

如果构建时依赖下载较慢或失败，可临时指定镜像源后再启动：

```powershell
$env:PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
$env:NPM_REGISTRY="https://registry.npmmirror.com"
docker compose up --build
```

启动后打开：

```text
http://localhost:8000
```

如需后台运行：

```bash
docker compose up -d --build
```

停止服务：

```bash
docker compose down
```

也可以不用 Compose，直接构建并运行镜像：

```bash
docker build -t packaging-app .
docker run --rm -p 8000:8000 packaging-app
```

### 本地开发前置条件

- Anaconda / Miniconda：提供 `conda` 命令，用于后端 Python 环境。
- Node.js >= 18：提供 `node` 和 `npm`，用于前端。

可先执行以下命令确认：

```bash
conda --version
node -v
npm -v
```

### 首次安装

假设已经 `git clone` 并进入项目根目录。

#### 1. 后端环境

```bash
conda create -n packaging python=3.12 -y
conda activate packaging

cd backend
pip install -r requirements.txt
cd ..
```

如果使用其他 conda 环境名，需要同步修改 `scripts/*.ps1` 和 `start.sh` 中的环境名，或使用手动启动命令。

验证后端依赖：

```bash
PYTHONIOENCODING=utf-8 D:/miniconda3/envs/packaging/python.exe -m pytest backend -q
```

> `conda run -n packaging ...` 在输出中文时会因 GBK 编码崩溃，故直接调用环境里的 `python.exe`。

#### 2. 前端依赖

```bash
cd frontend
npm install
cd ..
```

国内网络较慢时可临时使用镜像：

```bash
npm install --registry=https://registry.npmmirror.com
```

## 启动

### 一键启动

```powershell
# Windows PowerShell，项目根目录
.\start.ps1
```

```bash
# Git Bash / WSL
bash start.sh
```

启动后打开：

```text
http://localhost:5173
```

页面会加载默认测试数据，可直接点击「求解装箱」。

### 分别启动

```powershell
.\scripts\start-backend.ps1
.\scripts\start-frontend.ps1
```

```bash
# 后端
cd backend
D:/miniconda3/envs/packaging/python.exe -m uvicorn app.main:app --port 8000 --reload

# 前端，另开终端
cd frontend
npm install
npm run dev
```

前端开发服务器会把 `/api/*` 代理到 `http://127.0.0.1:8000`，配置见 `frontend/vite.config.js`。

## 使用流程

1. 在左侧维护货品、托盘、容器。点击「新增」会打开弹窗，确认后写入列表。
2. 货品可配置尺寸、重量、数量、堆叠类型、可摆放姿态、客户、订单、目的地、卸货顺序。
3. 容器可配置尺寸、载重、数量和装货入口。
4. 选择装箱策略。多客户配送场景使用「顺序配送」；需要设备级约束时切换到「工业校验」。
5. 可按需要打开「GA 优化」，质量可能更高但耗时更长。
6. 点击「求解装箱」。
7. 在右侧 3D 或 2D 视图查看结果，使用底部回放和容器切换控件检查顺序。
8. 使用顶部「客户筛选」和「货品筛选」查看特定客户或货品的装载位置。
9. 点击「导出 CSV」下载装载明细。

## 默认测试数据

前端默认数据共 1140 件，用于验证多客户配送、筛选与多容器类型混装：

- 货品（合计 1140 件）：
  - 大箱A：600 x 400 x 400，数量 40，客户「甲」，卸货 1，**不可堆叠且顶部不可承重**。
  - 小箱B：400 x 300 x 300，数量 300，客户「甲」，卸货 1，可堆叠。
  - 箱C：500 x 400 x 230，数量 300，客户「乙」，卸货 2，可堆叠。
  - 箱D：300 x 200 x 200，数量 500，客户「乙」，卸货 2，可堆叠。
- 托盘：标准托盘 1200 x 1000，数量 4，自重 10，限重 1000，限高 1500。
- 容器（两种类型，成本策略会自行择优）：
  - 20GP：5900 x 2350 x 2390，数量 10，载重 28000，启用成本 2000，后门装货。
  - 40GP：12030 x 2350 x 2390，数量 5，载重 26700，启用成本 3400，后门装货。

新增货品的卸货顺序默认为空；卡片上不会显示卸货标签。求解前会把空卸货顺序按后端默认值 `1` 处理。

## 接口

### `GET /health`

健康检查，返回：

```json
{ "status": "ok" }
```

### `POST /solve`

请求体示例：

```json
{
  "items": [
    {
      "id": "box-A",
      "name": "大箱A",
      "length": 600,
      "width": 400,
      "height": 400,
      "weight": 20,
      "quantity": 8,
      "allowed_rotations": ["LWH", "WLH"],
      "stackable": false,
      "stacking_type": "not_stackable",
      "max_load_top": 0,
      "category": "A",
      "customer_id": "甲",
      "order_id": "",
      "destination_id": "",
      "stop_seq": 1
    }
  ],
  "pallets": [
    {
      "id": "plt",
      "name": "标准托盘",
      "length": 1200,
      "width": 1000,
      "tare_weight": 10,
      "deck_height": 150,
      "max_stack_height": 1500,
      "max_load": 1000,
      "quantity": 4
    }
  ],
  "containers": [
    {
      "id": "cntr",
      "name": "20GP",
      "inner_length": 5900,
      "inner_width": 2350,
      "inner_height": 2390,
      "max_payload": 28000,
      "quantity": 2,
      "loading_accesses": [
        { "side": "x_max" }
      ]
    }
  ],
  "objective": "loading_efficiency",
  "use_ga": false
}
```

`objective` 可用值包括：

- `transport_cost`
- `load_stability`
- `weight_balance`
- `loading_efficiency`
- `multi_customer_delivery`（等价于 `loading_efficiency`）
- `advanced_score`
- 兼容别名：`max_utilization`、`min_containers`、`stability`、`balanced`、`center_of_gravity`

响应体示例：

```json
{
  "containers": [
    {
      "id": "cntr",
      "placements": [
        {
          "item_id": "box-A",
          "pallet_id": null,
          "customer_id": "甲",
          "order_id": "",
          "destination_id": "",
          "stop_seq": 1,
          "x": 0,
          "y": 0,
          "z": 0,
          "length": 600,
          "width": 400,
          "height": 400,
          "orientation": "LWH",
          "seq": 1
        }
      ],
      "volume_utilization": 0.0,
      "weight_utilization": 0.0
    }
  ],
  "unpacked": []
}
```

单位：尺寸使用同一长度单位，重量 kg。坐标原点在容器内部一个底角，x=长，y=宽，z=高（向上）。

## 测试

后端单元测试：

```bash
PYTHONIOENCODING=utf-8 D:/miniconda3/envs/packaging/python.exe -m pytest backend -q
```

基准 + 质量退化门禁（关键指标越界即失败）：

```bash
PYTHONIOENCODING=utf-8 D:/miniconda3/envs/packaging/python.exe scripts/benchmark_solver.py \
    --iterations 2 --warmups 0 --industrial-strategies --industrial-large
```

前端构建与浏览器端到端回归（真实 Chromium + 真实后端）：

```bash
cd frontend
npm run build
PACKAGING_PYTHON=D:/miniconda3/envs/packaging/python.exe npm run e2e
```

解释器说明见 `CLAUDE.md` 第 10 节：PATH 上的 `python` 不是本项目的 conda 环境，后端命令必须显式指定。

## 目录结构

```text
backend/
  app/
    main.py            FastAPI 入口
    api/routes.py      POST /solve、GET /health
    models/schemas.py  Pydantic 数据模型
    core/
      geometry.py           朝向、尺寸、AABB 几何
      space.py              极点集合
      extreme_point.py      极点放置与评分
      constraints.py        支撑、堆叠、承重约束
      objectives.py         可插拔优化目标与配送评分
      palletizer.py         码托盘逻辑与直接装/码托盘决策
      packer.py             多容器编排主循环、开箱类型选择
      industrial.py         工业校验、成本、诊断分层
      industrial_context.py 增量载荷上下文、堆垛簇分析
      evaluator.py          0-100 评分与 A~D 等级
      ga.py                 BRKGA 全局优化
      performance.py        耗时/计数采集
  tests/               后端单元测试
frontend/
  src/
    App.jsx            顶部视图切换、客户/货品筛选、导出入口
    components/        编辑面板、资源卡片、结果/回放面板、2D 俯视图
    three/             3D 场景、货品颜色、朝向几何
    store/             zustand 状态与默认测试数据
    api/               /solve 调用
    utils/             CSV 导出、客户/货品筛选工具
start.ps1 / start.sh   一键启动脚本
scripts/               分项启动脚本 + benchmark_solver.py（基准与质量门禁）
CLAUDE.md              设计约定、路线图与运行命令
docs/                  评估公式、工业策略、性能优化
```

## 常见问题

- `conda activate` 提示未初始化：先执行 `conda init`，PowerShell 用 `conda init powershell`，关闭并重开终端。
- `conda` 或 `npm` 找不到：确认已经安装并加入 PATH。
- 端口占用：后端默认 8000，前端默认 5173。关闭占用进程，或修改启动端口和 Vite 代理配置。
- 点击「求解装箱」无响应：确认后端正在运行，并访问 `http://127.0.0.1:8000/health` 返回 `{"status":"ok"}`。
- Windows 不允许运行 `.ps1`：使用 `powershell -ExecutionPolicy Bypass -File .\start.ps1`，或执行 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

## 状态

四个阶段（基础系统 / 评估体系 / 性能优化 / 工业策略重构）均已完成，详见 `CLAUDE.md` 第 9 节。

在此之上还有：工业校验模式（重心范围、地板载荷、载荷分布曲线、堆垛簇稳定性与固定能力）、
质量退化门禁、诊断三层语义、多容器类型混装、前端浏览器端到端回归。

后续候选方向：GA 与工业约束的联合优化（把工业指标并入 fitness）。**尚未确认业务价值**——
实测多次表明装载密度与堆垛安全在本样例上互斥，收益不确定。
