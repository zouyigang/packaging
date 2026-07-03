import { useEffect, useRef, useState } from 'react'
import { Slider, Button, Segmented, Tag, Empty } from 'antd'
import { CaretRightOutlined, PauseOutlined, StepBackwardOutlined } from '@ant-design/icons'
import { useStore } from '../store/useStore'
import { calculateCenterOfGravity, formatPercent } from '../utils/cog'

export default function ResultPanel() {
  const solution = useStore((s) => s.solution)
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

  return (
    <div className="result-panel">
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