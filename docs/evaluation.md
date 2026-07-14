# 策略评估算法

> 新生产策略、工业模式和兼容映射见 [industrial-strategies.md](industrial-strategies.md)。
> 当前生产策略为 `cost_efficiency`、`space_utilization`、`safe_loading`、
> `delivery_sequence` 和 `custom`；下文旧名称权重仅用于兼容请求。

本文档记录装箱方案评估算法。以后修改求解目标、GA fitness、托盘化逻辑、硬约束或评估公式时，必须同步更新本文档。

## 基本原则

评估分数表示“方案与所选策略的匹配度”，不是全局最优证明。3D 装箱问题通常无法在业务时间内证明最优，当前求解器也主要使用极点启发式和可选 GA，因此满分定义采用可计算上界和业务理想状态。

总分范围为 0-100，并给出等级：

- A：90 分及以上
- B：75-89.9 分
- C：60-74.9 分
- D：60 分以下

所有策略先计算同一批基础指标，再根据策略权重汇总为总分。未装货物按未装体积额外扣分。`evaluation` 同时返回整套方案评分和每个物理容器实例的局部评分，前端切换容器时优先展示当前箱评分。

## 多候选方案

多候选方案只在 `use_ga=true` 时启用；未开启 GA 时仍返回单个确定性启发式方案，以保持响应速度和结果可复现。`candidate_count` 默认值为 3，表示主方案加最多 2 个备选方案。

GA 会在一次搜索过程中收集见过的非重复可行方案，而不是完整运行多次 GA。候选方案按全局 `evaluation.score` 降序排序，评分相同时用 GA fitness 作为次级排序依据。重复方案按容器、装载顺序、货品、坐标和朝向签名去重；如果搜索空间里可区分的高分方案不足 3 个，则只返回实际可用数量。

接口响应中主方案仍放在 `Solution.containers` / `Solution.evaluation`，备选方案放在 `Solution.alternatives`。前端把主方案视为“方案 1”，将 `alternatives` 依次展示为后续候选。

## 基础指标

- `loaded_completion`：已装体积 / 总货物体积。
- `available_fit_ratio`：已装体积 / min(总货物体积, 可用容器总体积)。
- `used_volume_utilization`：已装体积 / 已使用容器总体积。
- `weight_utilization`：已装重量 / 已使用容器总载重。
- `container_count_score`：理论容器数下界 / 实际使用容器数。理论下界取体积下界和重量下界的较大值。
- `stability_score`：基于货物中心高度、底面积占比、细高比的稳定性近似评分。
- `balance_score`：按物理容器实例逐箱计算，衡量每箱已装货物重心相对容器水平中心的偏移评分；同一容器类型开多箱时不能按容器 id 混算。
- `loading_score`：卸货顺序与装货入口深度的匹配评分。无多站点卸货时，默认更偏好深处装载。
- `pallet_score`：已装货物中带托盘 id 的比例。
- `unpacked_penalty`：未装体积 / 总货物体积。

## 策略评分

### 运输成本优先

适用目标：`transport_cost`、`max_utilization`

满分含义：货物全部装完，使用容器数接近体积/重量理论下界，已使用容器利用率高。

权重：

- `loaded_completion`：40%
- `container_count_score`：30%
- `used_volume_utilization`：20%
- `weight_utilization`：10%

### 最少容器数

适用目标：`min_containers`

满分含义：货物全部装完，并尽量达到理论最少容器数。

权重：

- `loaded_completion`：35%
- `container_count_score`：40%
- `used_volume_utilization`：15%
- `weight_utilization`：10%

### 装载稳定优先

适用目标：`load_stability`、`stability`

满分含义：无未装货物，整体低位、大底面、少细高堆放，托盘化符合稳定性收益。

权重：

- `stability_score`：45%
- `loaded_completion`：20%
- `balance_score`：15%
- `pallet_score`：10%
- `used_volume_utilization`：10%

### 重心均衡优先

适用目标：`weight_balance`、`center_of_gravity`

满分含义：货物全部装完，每个物理容器实例的水平重心接近几何中心，偏载风险低。该策略的放置评分以重心偏移为主，并将低位高度惩罚和紧凑填充惩罚合入主项，避免为了追求水平重心而形成垂直高塔或碎片化布局。每个物理容器装完后还会在不改变相对布局的前提下做水平整体平移校正，使最终重心尽量靠近容器中心。

权重：

- `balance_score`：55%
- `loaded_completion`：25%
- `stability_score`：10%
- `used_volume_utilization`：10%

### 装卸/多客户配送优先

适用目标：`loading_efficiency`、`multi_customer_delivery`

满分含义：货物全部装完，后卸货更靠内，先卸货更靠近入口，同一卸货序列的空间关系更清晰。装卸策略有多卸货顺序时，会把卸货顺序与入口深度区间的匹配作为候选位置的首要评分项，再考虑聚集、低位和空间利用。

权重：

- `loading_score`：45%
- `loaded_completion`：25%
- `used_volume_utilization`：15%
- `balance_score`：10%
- `pallet_score`：5%

### 综合评分

适用目标：`advanced_score`、`balanced`

满分含义：按用户配置的高级权重，在空间利用、稳定性、托盘化、重心均衡、装卸位置之间取得较好折中。

权重：

- `loaded_completion`：固定 20%
- `used_volume_utilization`：使用 `advanced_weights.space_utilization`
- `stability_score`：使用 `advanced_weights.stability`
- `pallet_score`：使用 `advanced_weights.palletization`
- `balance_score`：使用 `advanced_weights.balance`
- `loading_score`：使用 `advanced_weights.loading_position`

## Warning 规则

评估结果会根据分项指标生成可解释提示：

- 有未装货物时提示余货扣分。
- `balance_score < 0.75` 时提示重心偏移。
- `stability_score < 0.70` 时提示稳定性偏低。
- 装卸策略下 `loading_score < 0.75` 时提示卸货顺序与入口匹配度偏低。
- 成本/容器策略下 `container_count_score < 0.90` 时提示容器数高于理论下界。
