import { useEffect, useMemo, useRef, useState } from 'react'
import { Slider, Button, Segmented, Tag, Empty } from 'antd'
import { CaretRightOutlined, PauseOutlined, StepBackwardOutlined } from '@ant-design/icons'
import { useStore } from '../store/useStore'
import { calculateCenterOfGravity, formatPercent } from '../utils/cog'

const OBJECTIVE_LABELS = {
  cost_efficiency: '成本效率',
  space_utilization: '空间利用',
  safe_loading: '安全装载',
  delivery_sequence: '顺序配送',
  custom: '高级自定义',
  transport_cost: '运输成本优先',
  max_utilization: '运输成本优先',
  min_containers: '最少容器数',
  load_stability: '装载稳定优先',
  stability: '装载稳定优先',
  weight_balance: '重心均衡优先',
  center_of_gravity: '重心均衡优先',
  loading_efficiency: '装卸/多客户配送优先',
  multi_customer_delivery: '装卸/多客户配送优先',
  advanced_score: '综合评分',
  balanced: '综合评分',
}

const GLOBAL_EVALUATION_METRICS = [
  { key: 'loaded_completion', label: '装载完成' },
  { key: 'container_count_score', label: '容器数' },
  { key: 'cost_efficiency_score', label: '成本效率' },
  { key: 'used_volume_utilization', label: '空间利用' },
  { key: 'stability_score', label: '稳定性' },
  { key: 'balance_score', label: '重心均衡' },
  { key: 'loading_score', label: '装卸匹配' },
  { key: 'unpacked_penalty', label: '余货惩罚', invert: true },
]

const CONTAINER_EVALUATION_METRICS = [
  { key: 'used_volume_utilization', label: '空间利用' },
  { key: 'weight_utilization', label: '重量利用' },
  { key: 'stability_score', label: '稳定性' },
  { key: 'balance_score', label: '重心均衡' },
  { key: 'loading_score', label: '装卸匹配' },
  { key: 'pallet_score', label: '托盘化' },
]

const PERFORMANCE_STAGE_LABELS = {
  build_placeables: '构造货品',
  pack_containers: '容器装载',
  pack_single_container: '单箱装载',
  find_placement: '寻找位置',
  evaluator: '方案评分',
  ga_initial_population: 'GA 初始种群',
  ga_generation: 'GA 迭代',
  ga_decode: 'GA 解码',
}

const PERFORMANCE_COUNTER_LABELS = {
  find_placement_calls: '位置搜索次数',
  candidate_points_ready: '候选点数',
  candidate_boxes_scored: '候选评分',
  candidate_boxes_checked: '硬约束检查',
  candidate_boxes_skipped_by_bound: '下界跳过',
  overlap_scan_items: '碰撞扫描',
  overlap_candidate_items: '碰撞候选',
  support_scan_items: '支撑扫描',
  support_candidate_items: '支撑候选',
  fallback_balance_calls: '重心 fallback',
  ga_generations_completed: 'GA 完成代数',
  ga_decode_cache_hits: 'GA 缓存命中',
  ga_decode_cache_misses: 'GA 缓存未命中',
}

export default function ResultPanel() {
  const solution = useStore((s) => s.solution)
  const solutionCandidates = useStore((s) => s.solutionCandidates)
  const activeSolutionIndex = useStore((s) => s.activeSolutionIndex)
  const setActiveSolutionIndex = useStore((s) => s.setActiveSolutionIndex)
  const items = useStore((s) => s.items)
  const containersInput = useStore((s) => s.containers)
  const activeContainer = useStore((s) => s.activeContainer)
  const setActiveContainer = useStore((s) => s.setActiveContainer)
  const seqCursor = useStore((s) => s.seqCursor)
  const setSeqCursor = useStore((s) => s.setSeqCursor)
  const [playing, setPlaying] = useState(false)
  const timer = useRef(null)

  const loaded = solution?.containers?.[activeContainer]
  const total = loaded?.placements.length || 0
  const itemMap = useMemo(() => Object.fromEntries(items.map((item) => [item.id, item])), [items])
  const cdef = containersInput.find((container) => container.id === loaded?.id) || containersInput[0]
  const visible = useMemo(
    () => (loaded?.placements || []).filter((placement) => placement.seq <= seqCursor),
    [loaded?.placements, seqCursor],
  )
  const cog = useMemo(() => calculateCenterOfGravity(visible, itemMap, cdef), [visible, itemMap, cdef])
  const evaluation = solution?.evaluation
  const activeEvaluation = evaluation?.containers?.[activeContainer]
  const slowHint = getSlowSolveHint(solution?.performance)

  useEffect(() => {
    if (!playing) return
    timer.current = setInterval(() => {
      const { seqCursor: cur, solution: sol, activeContainer: ac } = useStore.getState()
      const max = sol?.containers?.[ac]?.placements.length || 0
      if (cur >= max) {
        setPlaying(false)
      } else {
        setSeqCursor(cur + 1)
      }
    }, 200)
    return () => clearInterval(timer.current)
  }, [playing, setSeqCursor])

  if (!solution) {
    return (
      <div className="result-panel">
        <Empty description="点击求解装箱后查看方案" />
      </div>
    )
  }

  const containerOptions = solution.containers.map((c, i) => ({
    label: `${c.id} #${i + 1}`,
    value: i,
  }))
  const candidateOptions = solutionCandidates.map((candidate, index) => ({
    label: `方案 ${index + 1}`,
    value: index,
  }))

  return (
    <div className="result-panel">
      {solutionCandidates.length > 1 && (
        <div className="solution-switcher">
          <div className="solution-switcher-head">
            <strong>候选方案</strong>
            <span>按全局评分排序</span>
          </div>
          <Segmented
            options={candidateOptions}
            value={activeSolutionIndex}
            onChange={(v) => { setActiveSolutionIndex(v); setPlaying(false) }}
          />
          <div className="solution-candidate-list">
            {solutionCandidates.map((candidate, index) => (
              <button
                key={`candidate-${index}`}
                type="button"
                className={index === activeSolutionIndex ? 'solution-candidate is-active' : 'solution-candidate'}
                onClick={() => { setActiveSolutionIndex(index); setPlaying(false) }}
              >
                <span>方案 {index + 1}</span>
                <strong>{Number(candidate.evaluation?.score || 0).toFixed(1)}</strong>
                <Tag color={gradeColor(candidate.evaluation?.grade)}>{candidate.evaluation?.grade || '-'}</Tag>
                <em>{candidate.containers?.length || 0} 箱</em>
                {(candidate.unpacked?.length || 0) > 0 && <em>余货 {candidate.unpacked.length}</em>}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="metric-strip">
        <Segmented
          options={containerOptions}
          value={activeContainer}
          onChange={(v) => { setActiveContainer(v); setPlaying(false) }}
        />
        <Metric label="体积利用率" value={`${((loaded?.volume_utilization || 0) * 100).toFixed(1)}%`} />
        <Metric label="重量利用率" value={`${((loaded?.weight_utilization || 0) * 100).toFixed(1)}%`} />
        <Metric label="件数" value={total} />
        {solution.performance && <Metric label="求解耗时" value={formatRuntime(solution.performance.runtime_ms)} />}
        {solution.cost_summary && (
          <Metric label="估算成本" value={`${solution.cost_summary.total_cost.toFixed(2)} ${solution.cost_summary.currency}`} />
        )}
        <Metric label="重心偏移率" value={cog ? formatPercent(cog.offsetRate) : '-'} />
        <Metric label="重心位置" value={cog ? `${cog.x.toFixed(0)}, ${cog.y.toFixed(0)}, ${cog.z.toFixed(0)} cm` : '-'} compact />
        {(loaded?.industrial_metrics?.stack_cluster_count || 0) > 0 && (
          <>
            <Metric label="风险堆垛簇" value={Number(loaded.industrial_metrics.risky_stack_cluster_count || 0).toFixed(0)} />
            <Metric label="簇倾覆裕量" value={Number(loaded.industrial_metrics.stack_cluster_tip_margin || 0).toFixed(2)} />
            <Metric label="需纵向固定" value={`${Number(loaded.industrial_metrics.required_stack_longitudinal_restraint_kn || 0).toFixed(2)} kN`} />
            <Metric label="需横向固定" value={`${Number(loaded.industrial_metrics.required_stack_transverse_restraint_kn || 0).toFixed(2)} kN`} />
          </>
        )}
        <div style={{ flex: 1 }} />
        {slowHint && <Tag color="warning">{slowHint}</Tag>}
        <StatusTag solution={solution} />
        {solution.unpacked.length > 0 && <Tag color="warning">余货 {solution.unpacked.length} 件</Tag>}
      </div>

      {evaluation && (
        <div className="evaluation-stack">
          <div className="evaluation-panel evaluation-panel-global">
            <div className="evaluation-summary">
              <div className="evaluation-score">
                <span>全局方案评分</span>
                <strong>{Number(evaluation.score || 0).toFixed(1)}</strong>
                <Tag color={gradeColor(evaluation.grade)}>{evaluation.grade}</Tag>
              </div>
              <div className="evaluation-objective">
                <strong>{OBJECTIVE_LABELS[evaluation.objective] || evaluation.objective}</strong>
                {evaluation.warnings?.length > 0 && <span>{evaluation.warnings[0]}</span>}
              </div>
            </div>
            <EvaluationMetricGrid metrics={GLOBAL_EVALUATION_METRICS} values={evaluation.metrics} />
            {evaluation.warnings?.length > 1 && (
              <div className="evaluation-warnings">
                {evaluation.warnings.slice(1).map((warning) => <span key={warning}>{warning}</span>)}
              </div>
            )}
          </div>

          {activeEvaluation && (
            <div className="evaluation-panel evaluation-panel-container">
              <div className="evaluation-summary">
                <div className="evaluation-score">
                  <span>当前箱评分</span>
                  <strong>{Number(activeEvaluation.score || 0).toFixed(1)}</strong>
                  <Tag color={gradeColor(activeEvaluation.grade)}>{activeEvaluation.grade}</Tag>
                </div>
                <div className="evaluation-objective">
                  <strong>{loaded?.id} #{activeContainer + 1}</strong>
                  {activeEvaluation.warnings?.length > 0 && <span>{activeEvaluation.warnings[0]}</span>}
                </div>
              </div>
              <EvaluationMetricGrid metrics={CONTAINER_EVALUATION_METRICS} values={activeEvaluation.metrics} />
              {activeEvaluation.warnings?.length > 1 && (
                <div className="evaluation-warnings">
                  {activeEvaluation.warnings.slice(1).map((warning) => <span key={warning}>{warning}</span>)}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <DiagnosticsPanel solution={solution} />

      {solution.performance && <PerformancePanel performance={solution.performance} />}

      <div className="playback-row">
        <Button icon={<StepBackwardOutlined />} onClick={() => { setSeqCursor(0); setPlaying(false) }} />
        <Button
          type="primary"
          icon={playing ? <PauseOutlined /> : <CaretRightOutlined />}
          onClick={() => {
            if (!playing && seqCursor >= total) setSeqCursor(0)
            setPlaying((p) => !p)
          }}
        >
          {playing ? '暂停' : '回放'}
        </Button>
        <Slider
          style={{ flex: 1, minWidth: 220 }}
          min={0}
          max={total}
          value={seqCursor}
          onChange={(v) => { setSeqCursor(v); setPlaying(false) }}
        />
        <span className="playback-count">{seqCursor} / {total}</span>
      </div>
    </div>
  )
}

function PerformancePanel({ performance }) {
  const stages = Object.entries(performance?.stages_ms || {})
    .filter(([, value]) => Number(value) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 6)
  const counters = Object.entries(PERFORMANCE_COUNTER_LABELS)
    .map(([key, label]) => ({ key, label, value: performance?.counters?.[key] }))
    .filter((item) => item.value !== undefined && Number(item.value) !== 0)
    .slice(0, 8)
  const runtimeMs = Number(performance?.runtime_ms || 0)
  const slowHint = getSlowSolveHint(performance)

  if (stages.length === 0 && counters.length === 0) return null

  return (
    <details className="performance-panel">
      <summary className="performance-head">
        <div>
          <strong>性能诊断</strong>
          <span>本次求解耗时拆分</span>
        </div>
        {slowHint && <Tag color="warning">{slowHint}</Tag>}
      </summary>
      <div className="performance-content">
        {stages.length > 0 && (
          <div className="performance-block">
            <div className="performance-block-title">阶段耗时</div>
            <div className="performance-stage-list">
              {stages.map(([key, value]) => (
                <PerformanceStage
                  key={key}
                  label={PERFORMANCE_STAGE_LABELS[key] || key}
                  value={Number(value)}
                  total={runtimeMs}
                />
              ))}
            </div>
          </div>
        )}
        {counters.length > 0 && (
          <div className="performance-block">
            <div className="performance-block-title">关键计数</div>
            <div className="performance-counter-grid">
              {counters.map((counter) => (
                <div className="performance-counter" key={counter.key}>
                  <span>{counter.label}</span>
                  <strong>{formatCount(counter.value)}</strong>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </details>
  )
}

function PerformanceStage({ label, value, total }) {
  const percent = total > 0 ? Math.max(2, Math.min(100, (value / total) * 100)) : 0
  return (
    <div className="performance-stage">
      <div className="performance-stage-head">
        <span>{label}</span>
        <strong>{formatRuntime(value)}</strong>
      </div>
      <div className="performance-bar">
        <div style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

function Metric({ label, value, compact = false }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={compact ? 'metric-value metric-value-compact' : 'metric-value'}>{value}</div>
    </div>
  )
}

function formatRuntime(runtimeMs) {
  const value = Number(runtimeMs || 0)
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`
  return `${value.toFixed(0)}ms`
}

function formatCount(value) {
  const number = Number(value || 0)
  return new Intl.NumberFormat('zh-CN').format(number)
}

function getSlowSolveHint(performance) {
  const runtimeMs = Number(performance?.runtime_ms || 0)
  if (runtimeMs < 8000) return ''
  const counters = performance?.counters || {}
  const isGa = Number(counters.ga_generations_completed || 0) > 0
  return isGa ? '耗时偏高，可切换快速档或降低 GA 精度' : '耗时偏高，可先用非 GA 快速试算'
}

function EvaluationMetricGrid({ metrics, values = {} }) {
  return (
    <div className="evaluation-metrics">
      {metrics.filter((metric) => values?.[metric.key] !== undefined).map((metric) => (
        <EvaluationMetric key={metric.key} metric={metric} value={values[metric.key]} />
      ))}
    </div>
  )
}

function EvaluationMetric({ metric, value }) {
  const normalized = metric.invert ? 1 - Number(value || 0) : Number(value || 0)
  const percent = Math.max(0, Math.min(100, normalized * 100))
  return (
    <div className="evaluation-metric">
      <div className="evaluation-metric-head">
        <span>{metric.label}</span>
        <strong>{percent.toFixed(0)}%</strong>
      </div>
      <div className="evaluation-bar">
        <div style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

function gradeColor(grade) {
  if (grade === 'A') return 'success'
  if (grade === 'B') return 'processing'
  if (grade === 'C') return 'warning'
  return 'error'
}

// 三层诊断：错误（不可执行，必须解决）/ 风险（可执行，但要绑扎支挡）/ 提示（配置口径说明）。
// 后端 severity 与 Solution.status 是同一套语义，见 schemas.ConstraintViolation。
const SEVERITY_LAYERS = [
  { severity: 'error', label: '错误', hint: '方案不可执行，必须先解决', color: 'error' },
  { severity: 'warning', label: '风险', hint: '可执行，但需要绑扎或支挡等措施', color: 'warning' },
  { severity: 'info', label: '提示', hint: '配置口径说明，无需改动布局', color: 'default' },
]

function violationLocation(violation) {
  const parts = []
  if (violation.container_index !== null && violation.container_index !== undefined) {
    // 多只容器共用同一个类型 id，只有实例下标能定位到具体是哪一只。
    parts.push(`容器 #${violation.container_index + 1}${violation.container_id ? ` ${violation.container_id}` : ''}`)
  }
  if (violation.item_id) parts.push(`货品 ${violation.item_id}`)
  if (violation.stop_seq) parts.push(`站点 ${violation.stop_seq}`)
  return parts.join(' · ')
}

function DiagnosticsPanel({ solution }) {
  const diagnostics = solution.diagnostics
  const violations = solution.violations || []
  if (!diagnostics && violations.length === 0) return null

  return (
    <div className="evaluation-panel diagnostics-panel">
      {diagnostics?.status_reason && (
        <div className="diagnostics-summary">
          <span>{diagnostics.status_reason}</span>
        </div>
      )}
      {SEVERITY_LAYERS.map((layer) => {
        const layerViolations = violations.filter((v) => v.severity === layer.severity)
        if (layerViolations.length === 0) return null
        return (
          <div className="diagnostics-layer" key={layer.severity}>
            <div className="diagnostics-layer-head">
              <Tag color={layer.color}>{layer.label} {layerViolations.length}</Tag>
              <span className="diagnostics-layer-hint">{layer.hint}</span>
            </div>
            {layerViolations.map((violation, index) => {
              const location = violationLocation(violation)
              return (
                <div className="diagnostics-item" key={`${violation.code}-${index}`}>
                  <code>{violation.code}</code>
                  {location && <span className="diagnostics-location">{location}</span>}
                  <span className="diagnostics-message">{violation.message}</span>
                </div>
              )
            })}
          </div>
        )
      })}
    </div>
  )
}

// 「可执行」和「可执行但有风险」是两回事：前者可以直接上路，后者必须先绑扎支挡。
// 后端 status 只分 feasible/partial/infeasible，风险数量来自 diagnostics。
function StatusTag({ solution }) {
  const warnings = solution.diagnostics?.warning_count || 0
  const reason = solution.diagnostics?.status_reason || ''

  if (solution.status === 'infeasible') {
    return <Tag color="error" title={reason}>不可执行</Tag>
  }
  if (solution.status === 'partial') {
    return <Tag color="warning" title={reason}>部分装载</Tag>
  }
  if (warnings > 0) {
    return <Tag color="gold" title={reason}>可执行 · {warnings} 项风险</Tag>
  }
  return <Tag color="success" title={reason}>可执行</Tag>
}
