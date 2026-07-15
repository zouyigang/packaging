# 实验记录：把堆垛簇所需固定力并入 GA fitness（safe_loading）

> 状态：**实验性、默认关闭**。结论倾向正面（机制有效），但因存在种子方差、且 GA 在
> 1140 件工业案例上绝对质量仍不及生产启发式，暂不作为正式特性开启。本文档记录机制、
> 实验数据与复现方式，供后续决定是否推进「GA 与工业约束联合优化」。

## 背景与问题

引擎里原本有两套彼此独立的评分：

1. **GA fitness**（`backend/app/core/ga.py:_make_fitness`）——GA 搜索的方向盘，只用几何 +
   重量近似（体积、成本、重心、堆叠罚项），**完全不含工业物理指标**。
2. **工业硬约束**（`packer.py:_observe_industrial_candidate`）——构造期逐候选拒绝，只会
   毙掉违规候选，不引导搜索方向。

矛盾：工业约束只「拒绝」不「引导」。GA 蒙眼按几何/成本搜索，从不主动往「所需固定力更低、
危险簇更少」的布局走。文档中「密度与安全互斥」的旧结论，是在 **GA 看不到安全指标** 的
前提下得出的。本实验验证：让 GA「看见」堆垛簇所需固定力后，能否在**容器数不变**的前提下
找到更安全（固定力更低、危险簇更少）的布局。

## 改动（最小侵入，方案 A）

`_make_fitness` 内新增纯罚项子函数 `restraint_penalty(sol)`：复刻 `finalize_solution` 的
簇载荷构建（含托盘实例），逐容器调用纯函数
`industrial_context.analyze_stack_clusters(container, loads)` **现算**每只容器的
`required_longitudinal_restraint_kn + required_transverse_restraint_kn`，求和为罚项。

- 仅接入 `safe_loading` 分支；`cost_efficiency` / `space_utilization` / `delivery_sequence`
  / `custom` 四分支**逐位不变**。
- 门控：仅 `validation_mode == "industrial"` 且权重 > 0 时生效；否则短路返回 0，零开销。
- 权重乘子 `_SAFE_LOADING_RESTRAINT_WEIGHT`，来自环境变量 `GA_SAFE_RESTRAINT_WEIGHT`，
  **默认 0（关）**。罚项量级落在细粒度层（远小于 `common_score` 的 1e6+），不会翻转必装/
  装载量排序。
- fitness 在主进程执行，手里已有 `sol.containers` + `container_map` + `item_map`，故无需改
  多进程 worker、无需改 `finalize_solution`、无需 `request`。

单元测试：`backend/tests/test_ga_industrial_restraint.py`（罚项 = 权重 × 所需固定力、
平铺无罚项、其余四策略不受 industrial 开关影响）。

## 实验设置

- 案例：`scripts/benchmark_solver.py:_frontend_industrial_request("safe_loading")`，
  1140 件、`validation_mode=industrial`、`pallet_policy=auto`。
- 求解器：`solve_ga`，`GAConfig(population=24, generations=12)`，4 进程并行。
- 对照：同预算、同种子，仅切换 `GA_SAFE_RESTRAINT_WEIGHT` 为 0（基线）与 20（处理组）。
- 复现脚本：`scratchpad/ga_restraint_experiment.py <pop> <gens> <weight> <out.json> <seed>`。

## 结果（3 个种子，pop=24 / gen=12）

容器数在所有种子、所有条件下均为 **3，余货 0**（安全指标改善不以多开容器为代价）。

| 指标 | seed | 基线（关） | 处理（开 w=20） | 变化 |
| --- | --- | --- | --- | --- |
| 纵向固定力 kN | 7 | 14.64 | **7.04** | **−52%** |
|  | 13 | 15.02 | **6.20** | **−59%** |
|  | 21 | 15.42 | 16.33 | +6% |
| 横向固定力 kN | 7 | 3.04 | 2.49 | −18% |
|  | 13 | 3.69 | 2.20 | −40% |
|  | 21 | 4.78 | 3.47 | −27% |
| 危险簇数 | 7 | 114 | **35** | **−69%** |
|  | 13 | 117 | **50** | **−57%** |
|  | 21 | 134 | 126 | −6% |

聚合：**横向固定力与危险簇在 3/3 种子上全部下降**（均值分别约 −29%、−42%）；纵向固定力
在 2/3 种子上大幅下降（中位 15.02→7.04，约 −53%），但 seed 21 未能转化（+6%）。

低预算对照（pop=8 / gen=2）：处理组反而略差（种子 7：14.6→17.4）——说明罚项需要足够 GA
搜索深度才能转化为收益，2 代种群下是噪声。

## 结论

- **机制成立，反驳了「盲搜互斥」的强结论**：一旦 GA 能看见堆垛簇所需固定力，它能在**同
  容器数**下找到显著更安全的布局。旧的「密度/安全互斥」很大程度是 GA 对安全指标失明的
  产物，而非物理必然。（追加实验的精化：这一结论在「同箱数」层面成立，但**严格同容器
  组合**时改善微弱且不稳定——见下文「2 箱实验」，互斥中有一部分是真物理。）
- **但不是无条件的胜利**：效果依赖随机种子（GA 随机性），纵向固定力偶有种子无法改善；
  作为安全相关特性，这种非单调性要求更谨慎（多种子/更大预算）才能作为默认行为。

## 已知边界（诚实记录）

1. ~~GA 绝对质量仍不及生产启发式（3 箱 vs 2 箱）~~ **此说法有误，已被追加实验推翻**，
   见下节：启发式 2 箱解就是 GA 第 0 代的恒等个体，一直在候选池里；GA 输出 3 箱是最终
   排序（按 0-100 评分）弃选了它，不是搜索失败。
2. **计算昂贵**：pop=24/gen=12 下每次 GA 约 11–13 分钟（1140 件）。
3. **仅 GA 路径生效**：默认求解 `solve()` 与 `--industrial-strategies` 基准不走 GA，故本
   改动对既有基准与默认行为**零影响**（全量后端测试 213 项通过）。

## 追加实验：恒等个体探针 + 2 箱空间搜索

### 探针：为什么 GA 报 3 箱？

`solve_ga` 的初始种群用 linspace 播了一个恒等序个体（`pop[0]`：placeables 原序 + 朝向 0 +
容器原序），而 `solve()` 本体就是 `run_container_loop(_build_placeables(...),
_expand_containers(...))`——两者理论上应同构。探针（`scratchpad/ga_identity_probe.py`）
实测确认：**恒等个体解码结果与 `solve()` 逐位同布局**（2 箱、利用率 51.97%、评分 55.4，
layout_signature 相同）。即启发式解从第 0 代起就在 GA 候选池中。

GA 最终输出 3 箱的真因是 `_rank_ga_candidates` 的排序键 `(status, evaluation.score,
fitness)`：safe_loading 的 0-100 评分权重为 `safety_worst 0.50 + stability 0.20 +
balance 0.20 + loaded_completion 0.08 + used_volume 0.02`——**容器数与固定力都不进评分**，
摊开的 3 箱解堆高更低、stability 分更高，评分反超 2 箱解，于是被排到第一。

### 2 箱实验：同箱数下 GA 能否击败启发式的固定力？

在 fitness 上叠加容器数罚项（−700/箱，scratchpad monkeypatch，不改生产代码）+ 固定力
罚项（w=20），dump 整个候选池（`scratchpad/ga_2box_experiment.py`），pop=24/gen=12，
2 个种子。启发式参照：2×20GP、固定力 纵+横 = 11.67 kN、危险簇 27、评分 55.4。

| seed | 2 箱候选数 | 2 箱最低固定力 kN | 所用容器组合 | 危险簇 | 评分 |
| --- | --- | --- | --- | --- | --- |
| 7 | 98 | **5.86**（−50%） | 40GP+20GP | 35 | 60.9 |
| 13 | 127 | **9.29**（−20%） | 40GP+20GP | 29 | 58.3 |

关键分解——按容器组合看：

- **同箱数、换更大组合（40GP+20GP，容量 +52%、成本约 4080→5440 即 +33%）**：两个种子
  都稳定找到显著更低固定力的解。这是「用容量买安全」，不纯是布局智慧。
- **严格同组合（2×20GP，与启发式完全同口径）**：seed 7 找到 11.67→10.85 kN（−7%）、
  危险簇 27→24；seed 13 一无所获（候选池里该组合只剩恒等个体本身）。**改善微弱且不
  稳定**——启发式在 2×20GP 的密装下固定力已接近该密度的下限，「高密度下互斥」这部分
  是真物理，不是 GA 失明。

### 顺带暴露的真缺口：评分器对固定力失明 —— 已修复

两个种子里，生产排序选出的 GA primary 都是**高评分但纵向固定力爆表**的解（seed 7：
16.99 kN / 评分 62.6；seed 13：14.93 kN / 评分 110 个危险簇）——因为 0-100 评分器
（`evaluator.py`）的指标集里**没有任何固定力/危险簇指标**，工业安全量只活在
`evaluation.metrics` 附录里，不参与排序。

**已按下节「后续方向 1」修复**：`evaluator.py` 在工业模式的 safe_loading 下新增
`restraint_score` 维度（归一化的堆垛簇所需固定力，权重从 `safety_worst` 分 0.15），
从此固定力爆表的解不再能靠堆矮拿高分。这是比「调 GA」更前置、且同时惠及启发式多候选
`alternatives` 排序的改动——因为 `_rank_ga_candidates` 与 `alternatives` 排序都以
`evaluation.score` 为首键。改动只碰评分（`solve()` 的确定性装载不受影响），故 9 项质量
门禁全绿、无需重钉基线；全量后端测试 216 项通过。评分公式细节见
[evaluation.md](evaluation.md) 的「安全装载优先」与 `restraint_score` 定义。

**规模验证（干净 A/B，seed 7、pop24/gen12、同一候选池、罚项关）**：240 个装完候选里
`restraint_score` 跨度 [0.5525, 0.8642] = 0.31——在 0.15 权重下约 4.7 分摆幅，足以改排序
（曾担心 1140 件下聚合口径会把固定力稀释到不可分辨，实测证伪）。新评分选出的 top-1 与
旧评分不同：新首选在旧评分下排更低、被 `restraint_score` 项抬上来；因新分只多加
`0.15 × restraint_score`，换人方向必然指向更低固定力。故聚合口径（合计固定力 / 合计理论
上限）够用，无需改「最差容器」口径。

## 如何开启 / 复现

```bash
# 开启罚项（仅影响 GA + industrial + safe_loading）
GA_SAFE_RESTRAINT_WEIGHT=20 PYTHONIOENCODING=utf-8 D:/miniconda3/envs/packaging/python.exe \
    scratchpad/ga_restraint_experiment.py 24 12 20 out.json 7
```

## 后续方向（若决定推进）

「追平启发式」已不是问题（恒等个体即启发式解）。按实验数据，落地优先级应为：

1. ~~评分器补固定力维度~~ **✅ 已完成**：工业模式 safe_loading 评分新增 `restraint_score`
   维度（`evaluator.py`，权重从 `safety_worst` 分 0.15），GA 与多候选排序都不再把固定力
   爆表的解排到第一。只碰评分不碰装载，9 项质量门禁全绿、后端测试 216 项通过。
   （下一步候选 2/3 仍待排。）
2. **safe_loading 的 GA fitness 补容器数/成本意识**：实验里的 −700/箱罚项证明有效
   （2 箱候选从 0~个位数涨到 98/127 个）；转正式需与固定力罚项一样走 opt-in 或纳入
   策略定义。
3. **把「容量换安全”做成显式选项**而不是让 GA 偷偷换大箱：同箱数下换 40GP+20GP 可把
   固定力砍 20~50%，但多花 ~33% 成本——这本质是 `safety_priority` 开关的另一档
   （现有开关是多开一箱 2→3，这里是同箱数换大箱），应交给产品决策。
