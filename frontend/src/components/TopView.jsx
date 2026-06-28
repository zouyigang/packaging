import { Empty } from 'antd'
import { useStore } from '../store/useStore'
import { orientedDims, colorForCategory } from '../three/geometry'

// 2D 俯视装载图：沿 z 轴向下看，画出当前容器各货品在 x-y 平面的投影。
// 低层先画、高层后画（叠在上面），高度越高描边越深以示层次。
export default function TopView() {
  const solution = useStore((s) => s.solution)
  const items = useStore((s) => s.items)
  const pallets = useStore((s) => s.pallets)
  const containersInput = useStore((s) => s.containers)
  const activeContainer = useStore((s) => s.activeContainer)
  const seqCursor = useStore((s) => s.seqCursor)

  if (!solution) return <Empty style={{ marginTop: 60 }} description="先求解" />

  const itemMap = Object.fromEntries(items.map((i) => [i.id, i]))
  const palletMap = Object.fromEntries(pallets.map((p) => [p.id, p]))
  const loaded = solution.containers[activeContainer]
  const cdef = containersInput.find((c) => c.id === loaded?.id) || containersInput[0]
  if (!loaded || !cdef) return <Empty style={{ marginTop: 60 }} description="无数据" />

  const L = cdef.inner_length
  const W = cdef.inner_width
  const PAD = L * 0.04

  const boxes = loaded.placements
    .filter((p) => p.seq <= seqCursor)
    .map((p) => {
      const it = itemMap[p.item_id]
      const [dx, dy, dz] = it ? orientedDims(it.length, it.width, it.height, p.orientation) : [0, 0, 0]
      return { p, dx, dy, ztop: p.z + dz, it }
    })
    .sort((a, b) => a.p.z - b.p.z) // 低层先画

  const maxZ = Math.max(1, ...boxes.map((b) => b.ztop))

  // 从可见的托盘货品反推各托盘底板（俯视下的 footprint），画在货品下层。
  const deckGroups = {}
  for (const b of boxes) {
    if (!b.p.pallet_id) continue
    ;(deckGroups[b.p.pallet_id] ||= []).push(b)
  }
  const decks = Object.entries(deckGroups)
    .map(([pid, bs]) => {
      const pdef = palletMap[pid.split('#')[0]]
      if (!pdef) return null
      return {
        x: Math.min(...bs.map((b) => b.p.x)),
        y: Math.min(...bs.map((b) => b.p.y)),
        L: pdef.length,
        W: pdef.width,
      }
    })
    .filter(Boolean)

  return (
    <div style={{ height: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
      <svg
        viewBox={`${-PAD} ${-PAD} ${L + 2 * PAD} ${W + 2 * PAD}`}
        style={{ width: '100%', height: '100%', maxWidth: '100%', maxHeight: '100%' }}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* 容器外框 */}
        <rect x={0} y={0} width={L} height={W} fill="#fafafa" stroke="#1677ff" strokeWidth={L * 0.003} />
        {/* 托盘底板（画在货品下层） */}
        {decks.map((d, i) => (
          <rect
            key={`deck-${i}`}
            x={d.x} y={d.y} width={d.L} height={d.W}
            fill="#9c6b3f" fillOpacity={0.35}
            stroke="#5c3d1e" strokeWidth={L * 0.0025} strokeDasharray={`${L * 0.012} ${L * 0.008}`}
          />
        ))}
        {boxes.map((b, i) => {
          const fill = colorForCategory(b.it?.category)
          const depth = 0.25 + 0.55 * (b.ztop / maxZ) // 越高越不透明
          return (
            <g key={`${b.p.seq}-${i}`}>
              <rect
                x={b.p.x} y={b.p.y} width={b.dx} height={b.dy}
                fill={fill} fillOpacity={depth}
                stroke="#333" strokeWidth={L * 0.0015}
              />
              <text
                x={b.p.x + b.dx / 2} y={b.p.y + b.dy / 2}
                fontSize={Math.min(b.dx, b.dy) * 0.35}
                textAnchor="middle" dominantBaseline="central" fill="#111"
              >
                {b.p.seq}
              </text>
            </g>
          )
        })}
        <text x={L / 2} y={-PAD * 0.3} fontSize={L * 0.02} textAnchor="middle" fill="#999">
          长 {L} × 宽 {W} mm（俯视）
        </text>
      </svg>
    </div>
  )
}
