import { useEffect, useRef, useState } from 'react'
import { Slider, Button, Segmented, Statistic, Row, Col, Tag, Empty, Space } from 'antd'
import { CaretRightOutlined, PauseOutlined, StepBackwardOutlined } from '@ant-design/icons'
import { useStore } from '../store/useStore'

export default function ResultPanel() {
  const solution = useStore((s) => s.solution)
  const activeContainer = useStore((s) => s.activeContainer)
  const setActiveContainer = useStore((s) => s.setActiveContainer)
  const seqCursor = useStore((s) => s.seqCursor)
  const setSeqCursor = useStore((s) => s.setSeqCursor)
  const [playing, setPlaying] = useState(false)
  const timer = useRef(null)

  const loaded = solution?.containers?.[activeContainer]
  const total = loaded?.placements.length || 0

  // 自动回放：每 200ms 前进一步，到末尾停止。
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
      <div style={{ padding: 16 }}>
        <Empty description="点击「求解装箱」查看方案与回放" />
      </div>
    )
  }

  const containerOptions = solution.containers.map((c, i) => ({
    label: `${c.id} #${i + 1}`,
    value: i,
  }))

  return (
    <div style={{ padding: '12px 16px', borderTop: '1px solid #f0f0f0' }}>
      <Row gutter={16} align="middle">
        <Col>
          <Segmented
            options={containerOptions}
            value={activeContainer}
            onChange={(v) => { setActiveContainer(v); setPlaying(false) }}
          />
        </Col>
        <Col>
          <Statistic title="体积利用率" valueStyle={{ fontSize: 16 }}
            value={((loaded?.volume_utilization || 0) * 100).toFixed(1)} suffix="%" />
        </Col>
        <Col>
          <Statistic title="重量利用率" valueStyle={{ fontSize: 16 }}
            value={((loaded?.weight_utilization || 0) * 100).toFixed(1)} suffix="%" />
        </Col>
        <Col>
          <Statistic title="件数" valueStyle={{ fontSize: 16 }} value={total} />
        </Col>
        <Col flex="auto" />
        <Col>
          {solution.unpacked.length > 0 && (
            <Tag color="warning">余货 {solution.unpacked.length} 件</Tag>
          )}
        </Col>
      </Row>

      <Space style={{ marginTop: 8, width: '100%' }} align="center">
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
          style={{ flex: 1, width: 360 }}
          min={0}
          max={total}
          value={seqCursor}
          onChange={(v) => { setSeqCursor(v); setPlaying(false) }}
        />
        <span style={{ width: 70, textAlign: 'right' }}>{seqCursor} / {total}</span>
      </Space>
    </div>
  )
}
