# CLAUDE.md — 3D 装箱（容器装载）项目

> 本文件供 Claude Code 在每个会话开始时读取，作为项目上下文。
> 第 1~8 节是已定的设计约定；第 9 节是阶段路线图与当前状态；第 10 节是工作约定与运行命令。

---

## 1. 项目目标

一个 3D 装箱 / 容器装载（Container Loading）系统：用户编辑「货品 / 托盘 / 容器」的信息与数量，由算法给出合理的装箱方案，并在前端 3D 可视化展示，**包含装箱顺序的逐步回放**。

问题性质：3D 装箱属于 NP-hard，采用「启发式 + 可选元启发式优化」求高质量近似解，不追求精确最优。

---

## 2. 已确认的关键决策（务必遵守）

1. **托盘是算法的可选手段，不是固定流程。**
   用户只录入货品数量和「可用托盘数量」，算法自行决定每件/每批货品是「直接装进容器」还是「先码到托盘再装」，按目标函数择优。不要写死「先码垛再装箱」的两阶段流程。

2. **优化目标可插拔（策略模式），运行时通过参数选择。**
   生产目标为 `cost_efficiency`（成本效率）/ `space_utilization`（空间利用）/ `safe_loading`（安全装载）/ `delivery_sequence`（顺序配送）/ `custom`（高级自定义）。旧目标名由后端兼容映射；放置评分、GA 与最终评估必须共用同一目标定义。

3. **多容器自动分配。**
   最外层是多容器求解循环：按用户录入的容器类型与数量自动开箱、装载，直到货品装完或容器用尽；装不下的进入余货清单（unpacked）。

---

## 3. 架构总览

```
前端 (React + react-three-fiber)
  信息编辑 · 3D 可视化 · 顺序回放
        │ REST (JSON)
        ▼
API 层 (FastAPI + Pydantic)
        │
        ▼
装箱引擎 (纯 Python · 可独立测试)
  预处理 → 装载决策(直接装/码托盘) → 极点启发式放置 → 顺序生成
        ▲
  约束模块 · 算法库(极点/空间管理/评分/可选GA)
```

求解主流程：预处理（展开数量、载入目标函数）→ 开启新容器 → 装载决策（直接装 vs 码托盘，按目标择优）→ 极点启发式放置（校验约束、记录坐标与顺序）→ 容器装满则循环开新容器 → 输出方案 + 余货清单。

---

## 4. 技术栈

- **后端**：FastAPI（异步、自带 OpenAPI）+ Pydantic（校验）+ NumPy（几何计算）。引擎自研，纯 Python，不依赖框架。
- **前端**：React + Vite + react-three-fiber（Three.js 封装）+ @react-three/drei（相机控制）+ Ant Design（表格录入）+ zustand（状态管理）。

---

## 5. 数据模型

约定：尺寸单位 **mm**，重量单位 **kg**。坐标系原点在容器内部一个底角，`x=长(length)`、`y=宽(width)`、`z=高(height, 向上)`。

### 货品 Item
- `id: str`，`name: str`
- `length, width, height: float`（mm）
- `weight: float`（kg，单件）
- `quantity: int`
- `allowed_rotations: list[str]`（朝向约束，如限制「此面朝上」）
- `stackable: bool`
- `max_load_top: float`（顶部可承重 kg，易碎品=0）
- `category: str`（用于可视化上色）

### 托盘 Pallet（资源上限，算法可选用）
- `id: str`，`name: str`
- `length, width: float`（mm）
- `deck_height: float`（台面高 mm）
- `max_stack_height: float`（最大可码高度 mm）
- `max_load: float`（kg）
- `quantity: int`（可用数量）

### 容器 Container
- `id: str`，`name: str`
- `inner_length, inner_width, inner_height: float`（mm）
- `max_payload: float`（kg）
- `door_width, door_height: float | None`（可选门洞约束）
- `quantity: int`（可用数量）

### 输出 Solution
- `containers: list[LoadedContainer]`
  - `LoadedContainer`：`id`、`placements: list[Placement]`、`volume_utilization: float`、`weight_utilization: float`
  - `Placement`：`item_id`、`pallet_id: str | None`、`x, y, z`、`orientation`、`seq`（装箱顺序号）
- `unpacked: list[str]`（装不下的货品）

---

## 6. 核心算法

- **极点启发式（Extreme Point heuristic）+ 放置评分**：维护候选放置点集合，从原点开始；每放一个箱子在其角上投影生成新极点；放置时遍历极点，选「能放下 + 满足约束 + 评分最优」的位置（默认优先靠底/靠里/靠左以利堆叠稳定）。
- **装箱顺序天然来自构造顺序**；卸货可选 LIFO（后装先卸）。
- **码托盘判定**：对每件/每批货品比较「直接装容器」与「先码托盘再装」在当前目标下的收益，择优；相同货品组成「层/块」批量摆放提效。
- **可插拔目标函数**：见决策 2，作为策略注入评分与方案比较。
- **多容器循环**：见决策 3。
- **进阶（后置）**：遗传算法 / BRKGA 对「货品排序 + 朝向选择」做全局搜索，以极点启发式为解码器。

### 约束（引擎逐条校验）
不越界、不与已放置物体重叠；累计重量 ≤ 托盘/容器上限；朝向符合限制；堆叠时上方重量 ≤ 下方 `max_load_top`（易碎品不被压）；整体重心尽量低且居中。

---

## 7. 对外接口

`POST /solve`

请求体：
```json
{ "items": [], "pallets": [], "containers": [], "objective": "max_utilization" }
```

响应体：
```json
{
  "containers": [
    { "id": "...", "placements": [
        { "item_id": "...", "pallet_id": null, "x": 0, "y": 0, "z": 0, "orientation": "...", "seq": 1 }
      ], "volume_utilization": 0.0, "weight_utilization": 0.0 }
  ],
  "unpacked": []
}
```
前端拿到 `placements` 按 `seq` 排序即可做顺序回放。

---

## 8. 建议目录结构

```
backend/
  app/
    main.py              # FastAPI 入口
    api/                 # 路由 (POST /solve)
    models/              # Pydantic schemas (Item/Pallet/Container/Solution)
    core/
      packer.py          # 编排器：多容器求解主循环
      extreme_point.py   # 极点启发式与放置评分
      space.py           # 空间/极点管理
      palletizer.py      # 码托盘逻辑与「直接装 vs 码托盘」决策
      objectives.py      # 可插拔目标函数策略
      constraints.py     # 约束校验
      geometry.py        # 包围盒/旋转/重叠判定
  tests/                 # 引擎单元测试
  requirements.txt
frontend/
  src/
    components/          # 货品/托盘/容器编辑表格 (Ant Design)
    three/               # 3D 场景、顺序回放
    store/               # zustand 状态
    api/                 # 调用后端 /solve
  package.json
```

---

## 9. 路线图 / 当前状态

项目共 **四个大阶段**，四个阶段均已完成。

- [x] **阶段一：基础系统（M1~M7）** — 数据模型、单/多容器极点装箱、「直接装 vs 码托盘」决策、完整约束（重量/朝向/堆叠承重/支撑）、`POST /solve`、React + Three.js 可视化与顺序回放、2D 俯视图、CSV 导出、GA 优化。
- [x] **阶段二：评估体系与业务扩展** — 0-100 评分与 A~D 等级（整体 + 逐容器局部评分）、GA 多候选方案（`alternatives`）、多客户/顺序配送、装货入口（门洞/侧门/顶开）约束、重心居中目标。详见 `docs/evaluation.md`。
- [x] **阶段三：性能优化** — 性能计数与 `scripts/benchmark_solver.py` 基准、`find_placement` 热点优化（z 层 + x/y 网格索引、评分下界早停等）、GA 档位/早停/多进程并行、前端分包与性能诊断。1140 件默认样例耗时约 5.4~8.8s。详见 `docs/performance-optimization.md`。
- [x] **阶段四：工业策略重构** — 生产策略收敛为 `cost_efficiency` / `space_utilization` / `safe_loading` / `delivery_sequence` + `custom`（旧目标名兼容映射）；`validation_mode=standard|industrial`；增量工业载荷上下文（preview/commit）；设备重心范围、地板载荷、纵向载荷曲线硬约束前置；堆垛簇稳定性与固定能力闭环（`restraint_mode`）；48 件快速门禁 + 1140 件工业验收基准。四策略均以 2 个容器装完 1140 件、无工业错误码，耗时 4.5~8.7s。详见 `docs/industrial-strategies.md`。

阶段四内部按第 0~6 步推进（定义与完成标准见 `docs/industrial-strategies.md`）：

| 步骤 | 状态 |
| --- | --- |
| 第 0 步 回归基线 | ✅ 完成 |
| 第 1 步 增量约束上下文 | ✅ 完成 |
| 第 2 步 硬约束前置 | ✅ 完成：重心/地板载荷/载荷曲线已前置并有固定能力闭环；`restraint_mode=unverified` 下倾覆裕量仅告警是**正确设计**（假定绑扎，报出所需固定力），不是缺口 |
| 第 3 步 安全装载升级 | ✅ 完成：「倾覆裕量转正」已证伪（物理不可达）；实测密度与安全互斥，故落为产品开关 `safety_priority`（默认关=容器优先）。开启后固定力 11.67→5.53 kN、危险簇 27→17、细长比 11→8，代价容器 2→3 |
| 第 4 步 顺序配送升级 | ✅ 完成：逐站点载荷上下文 + 重心可达区间、直线卸货通道过滤已前置到构造（1140 件重心拒绝 1428→0、重心均衡 63%→79%）；多用的 1 个容器已消除（3→2 箱、成本 6080→4000、体积利用 34.6%→52.0%），与成本策略持平 |
| 第 5 步 策略对比门禁 | ✅ 完成：9 个基准用例各自钉上关键指标基线与允许退化幅度（容器数 0 容差、成本 +2%、体积利用 −2%、固定力 +10% 等），越界即失败并指名越界项；已用两次真实历史回归验证 |
| 第 6 步 评估与界面 | ✅ 完成：`error/warning/info` 三层语义与 `feasible/partial/infeasible` 对应；新增 `Solution.diagnostics` 与告警的容器实例下标（顺带修掉同名告警被去重吞掉的缺陷）；前端分层展示 + `destroyOnHidden` 迁移 |

**阶段四已收尾（第 0~6 步全部完成）**。后续候选方向（尚未排定优先级，需先确认业务价值）：① GA 与工业约束的联合优化——目前 GA 只搜「放置顺序 + 朝向」，工业硬约束仍靠解码器逐候选拒绝，把工业指标并入 fitness 有望在同样容器数下拿到更低固定力；② 前端 3D/2D 的浏览器回归验证（当前只有构建验证，无端到端点击回归）；③ 多容器类型混装的成本最优（现有多容器循环按目标排定开箱顺序，未做类型组合搜索）。

---

## 10. 工作约定

- **引擎优先、测试先行**：`core/` 是纯 Python，不依赖 FastAPI/前端，每个模块先写单元测试（用一组示例货品/容器验证利用率与无重叠）。
- 单位统一 mm / kg；坐标系如第 5 节约定，全项目一致。
- 目标函数、码托盘决策务必保持「可选/可插拔」，不要为了图省事写死流程（见第 2 节决策）。
- 先用一组示例数据端到端跑通最小闭环，再逐步加约束与优化。
- 脚手架搭好后，把实际的运行/测试/构建命令补到本节下方，方便后续会话直接使用。

### 运行 / 测试命令

后端（在 `backend/` 目录下）：

```bash
pip install -r requirements.txt   # 首次：安装依赖
python -m pytest                  # 跑全部单元测试（pytest.ini 已配置 testpaths/pythonpath）
```

### 当前进度

整体进度见第 9 节路线图（四阶段，当前在第四阶段）。后端引擎 185 个单元测试全绿；前端 React 可视化端到端联调通过。修改求解目标、GA fitness、托盘化、硬约束或评估公式时，必须同步更新 `docs/evaluation.md` 与 `docs/industrial-strategies.md`。

> 后端测试：`conda run -n packaging python -m pytest backend -q`
> 启动 API：在 `backend/` 下 `conda run -n packaging uvicorn app.main:app --port 8000`，文档见 `/docs`。
> 启动前端：在 `frontend/` 下 `npm install` 后 `npm run dev`（http://localhost:5173，已配 `/api`→8000 代理）。

M1（核心引擎最小闭环）：
- `app/models/schemas.py` — Item/Pallet/Container/Placement/LoadedContainer/Solution/SolveRequest（Pydantic v2），含 6 种轴对齐朝向定义。
- `app/core/geometry.py` — 朝向→实际尺寸、AABB 越界/重叠/体积，纯函数。
- `app/core/space.py` — 极点集合 `ExtremePointSet`（简化版极点法，靠底/靠里/靠左排序）。
- `app/core/extreme_point.py` — 单容器极点放置 + 评分；评分函数 `score_fn` 可注入。
- `app/core/packer.py` — `pack_single_container` 单容器装载。

M2（多容器循环 + 可插拔目标）：
- `app/core/objectives.py` — 目标策略 `Objective` 基类 + MaxUtilization/MinContainers/Stability/Balanced，`get_objective(name)` 工厂；影响放置评分 `placement_score` 与开箱顺序 `order_containers`。
- `app/core/packer.py` — 新增 `pack_units_into_container(units, container, objective)` 与多容器主循环 `solve(request)`：按目标排定开箱顺序、自动开箱、余货进 `unpacked`、统计体积/重量利用率。

M3（直接装 vs 码托盘决策）：
- `app/core/objectives.py` — 目标新增 `should_palletize(load_efficiency, count_per_pallet)` 钩子；默认/利用率类目标恒不码托盘（体积最优），`stability` 凡能成块(≥2件)就码，`balanced` 还要求满托盘填充率≥0.6。
- `app/core/palletizer.py` — 托盘当迷你容器做极点码垛：`build_pallet_load`（限件数/限重）、`fits_on_pallet`、`pallet_load_efficiency`、`select_pallet`（挑可码件数最多的托盘类型）。每只物理托盘有独立实例 id（如 `p#2`）。
- `app/core/packer.py` — `solve` 重构为基于「待放置单元 `_Placeable`」：单件 或 托盘整块（块内多件共享 `pallet_id`，M3 块固定不旋转）。`_build_placeables` 逐货品种类决策直接装/码托盘并扣减托盘数量，剩余转直接装；`_pack_placeables_into_container` 统一放置；托盘块放不下时块内各件按数量计入 `unpacked`。

M4（完整约束）：
- `app/models/schemas.py` — `Item.max_load_top` 改为 `Optional[float]=None`（None=无限制，0=易碎，>0=承重上限）。
- `app/core/constraints.py` — `PlacedItem`（几何+承重状态）；`check_support`（防悬空，底面支撑比例≥0.6 可调）、`check_stack_load`/`commit_stack_load`（新箱重量按接触面积分摊给直接支撑箱，不超 `max_load_top`；易碎=0 不可压）。简化：仅向直接支撑层分摊，不向更下层传递。
- `app/core/extreme_point.py` — `find_placement` 改收 `PlacedItem` 列表，新增 `weight`、`enforce_constraints`、`min_support_ratio`；放置时校验支撑与堆叠承重。
- `app/core/packer.py` — 容器载重上限按累计重量校验（超 `max_payload` 的留待后续容器）；放置后 `commit_stack_load` 累加承重；`pack_units_into_container` 改为委托 placeable 循环（去重）。
- 重心「尽量低且居中」按 CLAUDE 第 6 节定位为软目标，由 objectives 放置评分体现（stability 已显式偏好低重心+大底面），未作硬约束。

M5（FastAPI 接口）：
- `app/api/routes.py` — `POST /solve`（收 SolveRequest，调 `solve()`，返回 Solution）+ `GET /health`。同步处理函数（FastAPI 自动放线程池）。
- `app/main.py` — `create_app()`：标题/版本、CORS（放开 Vite 5173 便于前端开发）、挂载路由；模块级 `app`。
- 测试 `tests/test_api.py` — 暂无 httpx（本机 pip 无法联网安装），故直接调用路由处理函数 + 校验 `app.openapi()` 合同（含 SolveRequest/Solution schema）；已用 `curl` 对真实 uvicorn 做过端到端验证。

M6（前端可视化 + 顺序回放）：`frontend/`，React + Vite + react-three-fiber + Ant Design + zustand。
- `src/store/useStore.js` — zustand 全局状态（货品/托盘/容器/目标/方案/回放游标），内置一组示例数据；`solve()` 调后端。
- `src/components/` — `EditableTable`（通用可编辑表格）+ `EditPanel`（货品/托盘/容器编辑、目标选择、求解）+ `ResultPanel`（容器分段切换、利用率统计、余货标签、seq 滑块/播放回放）。
- `src/three/` — `Scene.jsx`（r3f：容器线框 + 货品盒，按 seq 游标增量显示；托盘件橙色，其余按 category 着色）；`geometry.js` 朝向映射与后端 `core/geometry.py` 一致。坐标 z 向上→three y 向上映射。
- `src/api/solve.js` — `POST /api/solve`（经 Vite 代理到 8000）。
- 已验证：`npm run build` 通过；uvicorn + vite dev 起好后，经代理 `POST /api/solve` 正常返回 placements。

M7（GA 优化 + 报表导出 + 2D 俯视图）：
- 后端 `app/core/ga.py` — BRKGA 精简版 `solve_ga(request, GAConfig)`：以「放置顺序」为随机键基因，`run_container_loop` 为解码器，按目标算适应度（装入体积；min_containers 额外惩罚容器数）进化；种群植入默认顺序个体保证不劣于启发式；同 seed 结果确定。`packer.solve` 拆出 `run_container_loop`/`_expand_containers` 供复用。
- `SolveRequest.use_ga: bool` + 路由按 flag 分派 `solve_ga`/`solve`。
- 前端 `EditPanel` 加「GA 优化」开关；`utils/exportCsv.js` + 顶栏「导出 CSV」（一行一放置，含朝向后尺寸，UTF-8 BOM 适配 Excel）；`components/TopView.jsx` 2D 俯视 SVG（按 z 分层、随 seq 回放）；`App.jsx` 顶栏 3D / 2D 俯视切换。
- 已验证：64 测试全绿；`npm run build` 通过；HTTP `use_ga:true` 正常返回。

后续增补（重心居中目标）：
- `objectives.py` — `Objective` 新增 `make_scorer(ctx)` 带上下文评分入口（默认等同 `placement_score`，不改既有目标）；`ScoreContext` 持有容器尺寸 + 容器内累计质量/加权坐标；新增 `CenterOfGravity`（name `center_of_gravity`）：评分主项=放置后整体重心到容器水平中心偏移、次项=低 z；质量用重量、无重量用体积兜底。
- `packer._pack_placeables_into_container` — 每只容器建 `ScoreContext`、每放一件更新累计重心。
- `schemas.Objective` 增加 `center_of_gravity`；前端目标下拉新增「重心居中」。
- 效果（24 件部分装载示例）：重心总偏移从 ~916mm 降到 ~133mm，利用率不变。测试 `test_center_of_gravity.py`（68 测试全绿）。
- 已知局限：极点候选点从角落生长，无法完美居中，但显著减小偏心。
