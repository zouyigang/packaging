# 装箱算法性能优化方案

本文档记录当前装箱算法的效率优化路线。后续修改 GA、极点放置、几何检测、评估器或前端求解体验时，应同步更新本文档。

## 优化目标

- 非 GA 模式保持当前结果基本一致，降低单次求解耗时。
- GA 模式缩短等待时间，同时保留多候选方案能力。
- 前端允许用户选择快速、标准、精细等求解档位，并明确显示当前求解状态。
- 所有优化都要有回归测试，避免装载数量、约束、评分或策略行为被破坏。

## 第一阶段：性能基线和低风险优化

先建立可观测性，再做确定收益的热点优化。

当前进度：

- 已在求解响应中返回 `performance.runtime_ms`、`stages_ms` 和 `counters`，并在后端日志输出求解耗时摘要。
- 已统计构造 placeables、单容器装载、`find_placement`、evaluator、GA 初始种群和每代耗时。
- 已增加 `scripts/benchmark_solver.py`，可用于固定样例的重复性能基线采集。
- 已缓存 `_Placeable` 体积和可用朝向尺寸，`find_placement` 可直接复用预计算朝向。
- 已对极点和重心 fallback 候选做去重、越界裁剪，并统计 fallback 调用次数和候选点数量。
- 已合并候选硬约束检查：每个候选只计算一次 supporters，并复用 ScoreContext 做重心硬约束，避免支撑/承重/堆叠/重心校验反复扫描已放置物。
- 已增加轻量 z 层空间过滤：重叠检测只检查 z 区间可能相交的已放置物，支撑检测只检查候选底面对应顶面 z 层的已放置物。
- 当前短基准（`scripts/benchmark_solver.py --iterations 1 --warmups 0 --include-frontend-all`）中，`heuristic_transport` 约 11ms，`heuristic_cog` 约 16ms，并行快速档 `ga_fast` 约 1200ms。
- 前端默认样例已加入 benchmark（`--include-frontend-all`），当前默认数量为 1140 件（40/300/300/500）；最新单次结果约为：重心优先 8.2s、空间利用类 9.1s、稳定性 6.4s。
- 暂未按原计划只在重心策略传入 `balance_points`：当前 `max_utilization` 等策略也有重心硬约束，直接移除 fallback 会破坏既有约束测试。后续需要先拆分“硬重心约束”和“重心目标额外候选”的职责。

- 增加后端耗时统计，至少记录构造 placeables、单容器装载、`find_placement`、evaluator、GA 每代等阶段耗时。
- 在求解结果中返回 `runtime_ms` 等性能指标，前端可展示本次求解耗时。
- 优化 `find_placement`：
  - 预计算每个货品的可用朝向尺寸，避免重复 `oriented_dims`。
  - 加强极点去重和无效点裁剪。
  - 对明显越界的朝向提前跳过。
  - 只在重心策略需要时传入 `balance_points`，其他策略减少 fallback 成本。
- 减少重复对象查找和计算：
  - 提前建立 `item_map`、`container_map`。
  - 缓存体积、重量、朝向尺寸。
  - evaluator 复用 placement 尺寸和质量推导结果。

## 第二阶段：GA 专项提速

GA 的主要耗时来自每代 population 的反复解码，每个个体相互独立，适合做档位控制、早停和多进程并行。

当前进度：

- 已增加 GA 档位，请求字段为 `ga_speed`：
  - 快速：population 16，generations 8-12。
  - 标准：population 32，generations 20-30。
  - 精细：population 64，generations 40-60。
- 已增加早停机制，并在 `performance.counters` 中记录 `ga_generations_completed` 和 `ga_early_stopped`：
  - 快速：连续 4 代无提升停止。
  - 标准：连续 8 代无提升停止。
  - 精细：连续 12 代无提升停止。
- 已在前端 GA 开关旁增加速度档位选择，开启 GA 时发送当前档位；前端默认使用“快速”档，避免误触发较慢的标准/精细搜索。
- 已增加 GA 内部排序签名缓存：相同放置顺序的个体不再重复 decode，并在 `performance.counters` 中记录 `ga_decode_cache_hits` 和 `ga_decode_cache_misses`；当前真实快速档样例中约减少 17 次 decode，`find_placement_calls` 从 3680 降到 2898。
- 已增加 GA population 多进程并行评估：默认 worker 数为 `min(cpu_count - 1, 4)`，小 population 自动回退单进程；当前快速档样例从单进程约 5115ms 降到约 2340ms。

后续计划：

- 继续按真实业务样例校准并行 worker 数和并行阈值，避免 Windows 进程调度与序列化开销反噬。
- 多候选方案继续从一次 GA 搜索中收集，不额外完整运行多次 GA。

## 第三阶段：算法层优化

当第一、二阶段仍不足以支撑更大数据集时，再进入结构性算法优化。

当前进度：

- 已增加尺寸感知候选点过滤：本次货品所有朝向都无法放入容器边界的极点不再进入完整校验。
- 已在每次成功放置后删除最小角已落入新箱体占用空间的极点，并统计 `candidate_points_pruned_covered`。
- 已将重叠检测的 x/y 区间预过滤前移到 z 层查询阶段，避免大量不相交箱子进入 `boxes_overlap`；当前快速档样例 `overlap_candidate_items` 从上一轮约 13282468 降到约 152716。
- 已增加评分下界提前停止：候选按目标评分稳定排序，找到可行最优后，后续评分不可能更优的候选不再做碰撞/支撑/重心校验；当前快速档样例跳过约 624092 个候选盒。
- 已将支撑候选的 x/y 区间预过滤前移到 z 顶面查询阶段；前端旧 438 件重心样例从约 3695ms 降到约 2293ms。
- 已增加候选最大值 counters（如 `candidate_boxes_scored_max`、`candidate_boxes_checked_max`、`candidate_points_ready_max`），用于评估是否能安全设置候选硬上限。
- 已将候选尝试从 dataclass 对象改为轻量 tuple，减少候选排序前的对象分配；前端旧 438 件重心样例进一步降到约 2116ms。
- 已将重叠检测从 z 层列表扫描升级为 z 层 + x/y 网格索引，候选查询只扫相交网格；前端旧 438 件重心样例 `overlap_scan_items` 从约 864 万降到约 69 万，耗时降到约 1423ms。
- 已内联 overlap 网格查询的 bin 计算，并仅在候选跨多个网格时分配去重集合；前端旧 438 件重心样例进一步降到约 1336ms。
- 已按新的 1140 件默认样例重新评估：`candidate_boxes_scored` 约 229 万、`candidate_boxes_checked` 约 156 万、`overlap_scan_items` 约 357 万、`support_candidate_items` 约 39 万，下一轮优化应优先压低 `find_placement` 候选数量和检查次数。
- 已补充 1140 件默认样例全策略评估：`transport_cost`/`max_utilization` 约 12.7s，`center_of_gravity` 约 10.6s，`stability` 约 7.9s；结论是瓶颈在所有策略共享的 `find_placement`，不应只做重心专项优化。
- 已给支撑检查增加 z 顶面 + x/y 网格索引，减少同层支撑扫描；1140 件默认重心样例约从 10.6s 降到 9.7s，空间利用类策略约从 12.7s 降到 12.2s。
- 已为默认空间利用类评分 `(z, y, x)` 增加点序扫描快路径，避免对所有“点 × 姿态”候选建堆排序；1140 件 `transport_cost`/`max_utilization` 约进一步降到 10.8s，装载率保持 1140/1140。
- 已试验 `stability` 按 z 层和底面积顺序扫描的快路径，实测硬检查次数上升、总耗时变慢，未保留。
- 已将高频性能 counters 从候选热循环逐次 `timer.count` 改为本地累加后批量写回，保留统计值但降低字典更新开销；1140 件默认重心样例约从 9.8s 降到 9.0s。
- 已将装载顺序重排 `_resequence_inside_to_outside` 从全量两两支撑依赖扫描改为 z 顶面 + x/y 网格查询，并用 `emitted_set` 加速依赖判定；1140 件默认重心样例约进一步降到 8.2s，空间利用类约 9.1s，稳定性约 6.4s。
- 已给 `ExtremePointSet` 增加内部 key set，极点去重从线性扫描改为 O(1) key 查询；单独收益较小，但避免后续大样例极点维护继续放大。
- 已试验“剩余货品尺寸安全裁剪极点”，实测维护 suffix 尺寸集合的开销超过收益，未保留在运行路径中。

后续计划：

- 控制极点数量：
  - 删除被其他极点支配的点。
  - 限制极点最大数量，并按策略保留最有价值的前 N 个；当前 1140 件样例最大 scored 约 2858、checked 约 1959，需要先验证硬截断不影响装载率和稳定性。
  - 不同策略使用不同极点排序。
- 扩展候选扫描快路径：
  - `center_of_gravity` 仍需要动态重心评分，需先做候选限流或近似分桶，不能直接套用 `(z, y, x)` 快路径。
  - `stability` 需要谨慎处理，简单顺序扫描会增加硬检查次数，下一步若继续优化应先做候选上限或支撑/碰撞更早过滤。
- 加速重叠检测：
  - 从 `candidate × placed_items` 全量遍历逐步改为按 z 层分桶或 x/y 网格分桶。
  - 只检查空间上可能相交的已放置物。
- 轻量化策略 scorer：
  - 将归一化常量提前计算。
  - 避免 scorer 内部频繁做 dict/list 操作。
  - 对 stop/customer 聚类评分做缓存或简化。

## 第四阶段：前端体验

- 已在 GA 开关旁边增加速度档位。
- 已让求解按钮在 GA 求解中显示当前模式，例如“GA 标准模式求解中”。
- 显示后端返回的 `runtime_ms`。
- 如果 GA 超过一定时间，提示用户可切换快速模式。

## GPU 评估结论

当前装箱逻辑主要由 Python 分支、对象操作、极点遍历、碰撞检测和约束判断组成，不是矩阵计算型任务。直接引入 GPU 不会自动提速，反而需要把核心几何检测和候选评分重写为批量数组或 CUDA 逻辑，投入较大且收益不确定。

优先级应为：

1. CPU 热点优化。
2. GA 档位和早停。
3. GA 多进程并行。
4. 几何检测空间索引。
5. 在核心逻辑可批量化后再重新评估 GPU。

## 验收标准

- 非 GA 默认数据集耗时下降至少 20%-40%。
- GA 标准模式在多核 CPU 上明显快于当前单进程版本。
- GA 快速模式可用于交互试算。
- 装载完成率不下降，硬约束不破坏。
- 各策略核心评分不异常下降。
- 后端测试通过：`conda run -n packaging python -m pytest backend -q`。
- 前端构建通过：`cd frontend && npm run build`。
