import { useMemo } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Edges } from '@react-three/drei'
import { useStore } from '../store/useStore'
import { orientedDims, colorForItem } from './geometry'
import { calculateCenterOfGravity } from '../utils/cog'
import { ALL_CUSTOMERS, ALL_ITEMS, customerKey } from '../utils/customerFilter'

const SCALE = 0.01 // mm → 场景单位（1000mm = 10）

// 后端坐标 z 向上；three 默认 y 向上。映射 (x,y,z) → (x, z, y)。
function toScene(x, y, z) {
  return [x * SCALE, z * SCALE, y * SCALE]
}

function Box({ box }) {
  return (
    <mesh position={box.position}>
      <boxGeometry args={box.size} />
      <meshStandardMaterial color={box.color} />
      <Edges color="#333" />
    </mesh>
  )
}

// 托盘台面：码托盘的货品底部距地有 deck_height 的台面高，画出来即托住货品、不再悬空。
function PalletDeck({ deck }) {
  const pos = toScene(deck.x + deck.L / 2, deck.y + deck.W / 2, deck.z + deck.H / 2)
  const size = [deck.L * SCALE, deck.H * SCALE, deck.W * SCALE]
  return (
    <mesh position={pos}>
      <boxGeometry args={size} />
      <meshStandardMaterial color="#9c6b3f" />
      <Edges color="#5c3d1e" />
    </mesh>
  )
}

// 从可见的托盘货品反推各托盘台面：按 pallet_id 分组，取最小角与托盘尺寸。
function deriveDecks(visibleBoxes, palletMap) {
  const groups = {}
  for (const box of visibleBoxes) {
    const p = box.placement
    if (!p.pallet_id) continue
    ;(groups[p.pallet_id] ||= []).push(p)
  }
  const decks = []
  for (const [pid, ps] of Object.entries(groups)) {
    const pdef = palletMap[pid.split('#')[0]]
    if (!pdef) continue
    const x = Math.min(...ps.map((p) => p.x))
    const y = Math.min(...ps.map((p) => p.y))
    const minItemZ = Math.min(...ps.map((p) => p.z)) // 货品底 = 台面顶
    decks.push({ x, y, z: minItemZ - pdef.deck_height, L: pdef.length, W: pdef.width, H: pdef.deck_height })
  }
  return decks
}

function ContainerBox({ container }) {
  const w = container.inner_length * SCALE
  const h = container.inner_height * SCALE
  const d = container.inner_width * SCALE
  return (
    <mesh position={[w / 2, h / 2, d / 2]}>
      <boxGeometry args={[w, h, d]} />
      <meshBasicMaterial transparent opacity={0.04} color="#1677ff" />
      <Edges color="#1677ff" />
    </mesh>
  )
}

function CogMarker({ cog }) {
  if (!cog) return null
  const pos = toScene(cog.x, cog.y, cog.z)
  const ground = toScene(cog.x, cog.y, 0)
  const height = Math.max(0.01, pos[1] - ground[1])
  return (
    <group renderOrder={999}>
      <mesh position={pos} renderOrder={999}>
        <sphereGeometry args={[0.28, 32, 32]} />
        <meshBasicMaterial color="#ef4444" depthTest={false} depthWrite={false} />
      </mesh>
      <mesh position={pos} rotation={[-Math.PI / 2, 0, 0]} renderOrder={999}>
        <ringGeometry args={[0.38, 0.48, 40]} />
        <meshBasicMaterial color="#ef4444" depthTest={false} depthWrite={false} />
      </mesh>
      <mesh position={ground} rotation={[-Math.PI / 2, 0, 0]} renderOrder={999}>
        <ringGeometry args={[0.3, 0.42, 40]} />
        <meshBasicMaterial color="#ef4444" depthTest={false} depthWrite={false} />
      </mesh>
      <mesh position={[pos[0], ground[1] + height / 2, pos[2]]} renderOrder={999}>
        <cylinderGeometry args={[0.035, 0.035, height, 12]} />
        <meshBasicMaterial color="#ef4444" depthTest={false} depthWrite={false} />
      </mesh>
    </group>
  )
}
export default function Scene() {
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
  // 用输入容器尺寸画外框（按装载容器 id 匹配，回退第一个）
  const cdef = useMemo(
    () => containersInput.find((c) => c.id === loaded?.id) || containersInput[0],
    [containersInput, loaded?.id],
  )

  const renderBoxes = useMemo(
    () => (loaded?.placements || []).map((placement, index) => buildRenderBox(placement, itemMap, index)).filter(Boolean),
    [loaded?.placements, itemMap],
  )
  const visibleBoxes = useMemo(
    () => renderBoxes.filter((box) => box.seq <= seqCursor && matchesFilters(box, customerFilter, itemFilter)),
    [renderBoxes, seqCursor, customerFilter, itemFilter],
  )
  const visiblePlacements = useMemo(() => visibleBoxes.map((box) => box.placement), [visibleBoxes])
  const decks = useMemo(() => deriveDecks(visibleBoxes, palletMap), [visibleBoxes, palletMap])
  const cog = useMemo(() => calculateCenterOfGravity(visiblePlacements, itemMap, cdef), [visiblePlacements, itemMap, cdef])

  // 让相机大致对准容器中心
  const cx = (cdef?.inner_length || 5900) * SCALE
  const camPos = useMemo(() => [cx * 1.2, cx * 1.0, cx * 1.4], [cx])
  const controlTarget = useMemo(
    () => (cdef ? [cx / 2, 0, (cdef.inner_width * SCALE) / 2] : [0, 0, 0]),
    [cdef, cx],
  )

  return (
    <Canvas frameloop="demand" camera={{ position: camPos, fov: 50, far: 5000 }}>
      <ambientLight intensity={0.7} />
      <directionalLight position={[50, 80, 40]} intensity={0.8} />
      <directionalLight position={[-40, 30, -40]} intensity={0.3} />
      {cdef && <ContainerBox container={cdef} />}
      {decks.map((d, i) => (
        <PalletDeck key={`deck-${i}`} deck={d} />
      ))}
      {visibleBoxes.map((box) => (
        <Box key={box.key} box={box} />
      ))}
      <CogMarker cog={cog} />
      <gridHelper args={[200, 40, '#ccc', '#eee']} />
      <OrbitControls makeDefault target={controlTarget} />
    </Canvas>
  )
}

function buildRenderBox(placement, itemMap, index) {
  const item = itemMap[placement.item_id]
  if (!item) return null
  const [dx, dy, dz] = orientedDims(item.length, item.width, item.height, placement.orientation)
  const cx = placement.x + dx / 2
  const cy = placement.y + dy / 2
  const cz = placement.z + dz / 2
  return {
    key: `${placement.item_id}-${placement.seq}-${index}`,
    seq: placement.seq,
    itemId: placement.item_id,
    customer: customerKey(placement.customer_id ?? item.customer_id),
    placement,
    position: toScene(cx, cy, cz),
    size: [dx * SCALE, dz * SCALE, dy * SCALE],
    color: colorForItem(item),
  }
}

function matchesFilters(box, customerFilter, itemFilter) {
  if (customerFilter && customerFilter !== ALL_CUSTOMERS && box.customer !== customerFilter) return false
  if (itemFilter && itemFilter !== ALL_ITEMS && box.itemId !== itemFilter) return false
  return true
}
