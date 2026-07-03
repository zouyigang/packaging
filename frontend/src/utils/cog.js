import { orientedDims } from '../three/geometry'

export function calculateCenterOfGravity(placements, itemMap, container) {
  if (!container || !placements?.length) return null

  let totalMass = 0
  let sumX = 0
  let sumY = 0
  let sumZ = 0

  for (const placement of placements) {
    const item = itemMap[placement.item_id]
    if (!item) continue
    const [dx, dy, dz] = orientedDims(item.length, item.width, item.height, placement.orientation)
    const mass = item.weight > 0 ? item.weight : dx * dy * dz
    totalMass += mass
    sumX += mass * (placement.x + dx / 2)
    sumY += mass * (placement.y + dy / 2)
    sumZ += mass * (placement.z + dz / 2)
  }

  if (totalMass <= 0) return null

  const x = sumX / totalMass
  const y = sumY / totalMass
  const z = sumZ / totalMass
  const centerX = container.inner_length / 2
  const centerY = container.inner_width / 2
  const offsetXRate = centerX ? Math.abs(x - centerX) / centerX : 0
  const offsetYRate = centerY ? Math.abs(y - centerY) / centerY : 0

  return {
    x,
    y,
    z,
    offsetXRate,
    offsetYRate,
    offsetRate: Math.max(offsetXRate, offsetYRate),
  }
}

export function formatPercent(value) {
  return `${((value || 0) * 100).toFixed(1)}%`
}
