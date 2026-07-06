import { useEffect, useRef, useState } from 'react'
import { Slider, Button, Segmented, Tag, Empty } from 'antd'
import { CaretRightOutlined, PauseOutlined, StepBackwardOutlined } from '@ant-design/icons'
import { useStore } from '../store/useStore'
import { calculateCenterOfGravity, formatPercent } from '../utils/cog'

const OBJECTIVE_LABELS = {
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
  const itemMap = Object.fromEntries(items.map((item) => [item.id, item]))
  const cdef = containersInput.find((container) => container.id === loaded?.id) || containersInput[0]
  const visible = (loaded?.placements || []).filter((placement) => placement.seq <= seqCursor)
  const cog = calculateCenterOfGravity(visible, itemMap, cdef)
  const evaluation = solution?.evaluation
  const activeEvaluation = evaluation?.containers?.[activeContainer]

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
        <Metric label="重心偏移率" value={cog ? formatPercent(cog.offsetRate) : '-'} />
        <Metric label="重心位置" value={cog ? `${cog.x.toFixed(0)}, ${cog.y.toFixed(0)}, ${cog.z.toFixed(0)} cm` : '-'} compact />
        <div style={{ flex: 1 }} />
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

function Metric({ label, value, compact = false }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={compact ? 'metric-value metric-value-compact' : 'metric-value'}>{value}</div>
    </div>
  )
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
