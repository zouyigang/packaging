import { useMemo } from 'react'
import { Empty } from 'antd'
import { useStore } from '../store/useStore'
import { orientedDims, colorForItem } from '../three/geometry'
import { calculateCenterOfGravity } from '../utils/cog'
import { filterPlacements } from '../utils/customerFilter'
import { deriveVisiblePalletDecks } from '../utils/palletDecks'

// 空容器俯视占位：圆角外框 + 内部浅网格，只是示意，不承载数据。
function TopViewPlaceholder({ length, width }) {
  const PAD = length * 0.02
  const cols = 12
  const rowCount = 4
  const verticals = Array.from({ length: cols - 1 }, (_, i) => ((i + 1) * length) / cols)
  const horizontals = Array.from({ length: rowCount - 1 }, (_, i) => ((i + 1) * width) / rowCount)
  return (
    <div className="topview-placeholder-wrap">
      <svg
        viewBox={`${-PAD} ${-PAD} ${length + 2 * PAD} ${width + 2 * PAD}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <rect
          x={0}
          y={0}
          width={length}
          height={width}
          rx={length * 0.004}
          fill="#f2f5fd"
          stroke="#93a4e0"
          strokeWidth={length * 0.0028}
        />
        <g stroke="#dde4f5" strokeWidth={length * 0.0012}>
          {verticals.map((x) => <line key={`v-${x}`} x1={x} y1={0} x2={x} y2={width} />)}
          {horizontals.map((y) => <line key={`h-${y}`} x1={0} y1={y} x2={length} y2={y} />)}
        </g>
      </svg>
    </div>
  )
}

// 2D 俯视装载图：沿 z 轴向下看，画出当前容器各货品在 x-y 平面的投影。
// 低层先画、高层后画（叠在上面），高度越高描边越深以示层次。
export default function TopView() {
  const solution = useStore((s) => s.solution)
  const items = useStore((s) => s.items)
  const pallets = useStore((s) => s.pallets)
  const containersInput = useStore((s) => s.containers)
  const activeContainer = useStore((s) => s.activeContainer)
  const seqCursor = useStore((s) => s.seqCursor)
  const customerFilter = useStore((s) => s.customerFilter)
  const itemFilter = useStore((s) => s.itemFilter)

  const itemMap = useMemo(() => Object.fromEntries(items.map((i) => [i.id, i])), [items])
  const palletMap = useMemo(() => Object.fromEntries(pallets.map((p) => [p.id, p])), [pallets])
  const loaded = solution?.containers?.[activeContainer]
  const cdef = useMemo(
    () => containersInput.find((c) => c.id === loaded?.id) || containersInput[0],
    [containersInput, loaded?.id],
  )
  const sequenceVisible = useMemo(
    () => (loaded?.placements || []).filter((p) => p.seq <= seqCursor),
    [loaded?.placements, seqCursor],
  )
  const filteredPlacements = useMemo(
    () => filterPlacements(sequenceVisible, itemMap, customerFilter, itemFilter),
    [sequenceVisible, itemMap, customerFilter, itemFilter],
  )

  const boxes = useMemo(
    () => filteredPlacements
      .map((p) => {
        const it = itemMap[p.item_id]
        const [dx, dy, dz] = it ? orientedDims(it.length, it.width, it.height, p.orientation) : [0, 0, 0]
        return { p, dx, dy, ztop: p.z + dz, it }
      })
      .sort((a, b) => a.p.z - b.p.z),
    [filteredPlacements, itemMap],
  )

  const maxZ = Math.max(1, ...boxes.map((b) => b.ztop))
  const cog = useMemo(() => calculateCenterOfGravity(filteredPlacements, itemMap, cdef), [filteredPlacements, itemMap, cdef])

  const decks = useMemo(
    () => deriveVisiblePalletDecks(filteredPlacements, loaded?.pallet_instances, palletMap),
    [filteredPlacements, loaded?.pallet_instances, palletMap],
  )

  // 空状态：画一个待装载的空容器俯视框（取第一个容器类型的比例），与 3D 视图的空态呼应。
  if (!solution || !loaded || !cdef) {
    const def = cdef || containersInput[0]
    if (!def) return <Empty style={{ marginTop: 60 }} description="请先录入容器" />
    return <TopViewPlaceholder length={def.inner_length || 5900} width={def.inner_width || 2350} />
  }

  const L = cdef.inner_length
  const W = cdef.inner_width
  const PAD = L * 0.04

  return (
    <div style={{ height: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
      <svg
        data-testid="topview"
        viewBox={`${-PAD} ${-PAD} ${L + 2 * PAD} ${W + 2 * PAD}`}
        style={{ width: '100%', height: '100%', maxWidth: '100%', maxHeight: '100%' }}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* 容器外框 */}
        <rect x={0} y={0} width={L} height={W} fill="#fafafa" stroke="#1677ff" strokeWidth={L * 0.003} />
        <g opacity="0.55">
          <line x1={L / 2} y1={0} x2={L / 2} y2={W} stroke="#94a3b8" strokeWidth={L * 0.0012} strokeDasharray={`${L * 0.01} ${L * 0.01}`} />
          <line x1={0} y1={W / 2} x2={L} y2={W / 2} stroke="#94a3b8" strokeWidth={L * 0.0012} strokeDasharray={`${L * 0.01} ${L * 0.01}`} />
        </g>
        {/* 托盘底板（画在货品下层） */}
        {decks.map((d) => (
          <rect
            key={`deck-${d.id}`}
            x={d.x} y={d.y} width={d.L} height={d.W}
            fill="#9c6b3f" fillOpacity={0.35}
            stroke="#5c3d1e" strokeWidth={L * 0.0025} strokeDasharray={`${L * 0.012} ${L * 0.008}`}
          />
        ))}
        {boxes.map((b, i) => {
          const fill = colorForItem(b.it)
          const depth = 0.25 + 0.55 * (b.ztop / maxZ) // 越高越不透明
          return (
            <g key={`${b.p.seq}-${i}`} data-testid="topview-box">
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
        {cog && (
          <g>
            <circle cx={cog.x} cy={cog.y} r={L * 0.012} fill="none" stroke="#ef4444" strokeWidth={L * 0.003} />
            <circle cx={cog.x} cy={cog.y} r={L * 0.0045} fill="#ef4444" />
            <line x1={cog.x - L * 0.018} y1={cog.y} x2={cog.x + L * 0.018} y2={cog.y} stroke="#ef4444" strokeWidth={L * 0.002} />
            <line x1={cog.x} y1={cog.y - L * 0.018} x2={cog.x} y2={cog.y + L * 0.018} stroke="#ef4444" strokeWidth={L * 0.002} />
            <text x={cog.x + L * 0.018} y={cog.y - L * 0.018} fontSize={L * 0.018} fill="#ef4444">重心</text>
          </g>
        )}
        <text x={L / 2} y={-PAD * 0.3} fontSize={L * 0.02} textAnchor="middle" fill="#999">
          长 {L} × 宽 {W} cm（俯视）
        </text>
      </svg>
    </div>
  )
}
