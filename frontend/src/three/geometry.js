// 朝向 → 实际占用尺寸，与后端 app/core/geometry.py 的 _ORIENTATION_MAP 保持一致。
// 三字母表示原始 (length,width,height) 中哪一维落在 x / y / z 轴。
const ORIENTATION_MAP = {
  LWH: [0, 1, 2],
  WLH: [1, 0, 2],
  LHW: [0, 2, 1],
  HWL: [2, 1, 0],
  WHL: [1, 2, 0],
  HLW: [2, 0, 1],
}

export function orientedDims(length, width, height, orientation) {
  const idx = ORIENTATION_MAP[orientation] || ORIENTATION_MAP.LWH
  const dims = [length, width, height]
  return [dims[idx[0]], dims[idx[1]], dims[idx[2]]]
}

// 按 key 稳定生成颜色。同客户同一基础色，同客户不同货品只做轻微变化。
function hashKey(value) {
  const key = String(value || 'default')
  let hash = 0
  for (let i = 0; i < key.length; i++) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0
  }
  return hash
}

function hueForKey(value) {
  return Math.round((hashKey(value) * 137.508) % 360)
}

const CUSTOMER_PALETTE = [
  { hue: 204, saturation: 58, lightness: 68 }, // soft blue
  { hue: 138, saturation: 48, lightness: 66 }, // soft green
  { hue: 344, saturation: 58, lightness: 72 }, // soft rose
  { hue: 48, saturation: 62, lightness: 70 }, // soft yellow
  { hue: 178, saturation: 50, lightness: 66 }, // soft teal
  { hue: 260, saturation: 34, lightness: 74 }, // pale lavender
  { hue: 112, saturation: 46, lightness: 68 }, // soft leaf
]

function customerBaseColor(customerId) {
  return CUSTOMER_PALETTE[hashKey(customerId) % CUSTOMER_PALETTE.length]
}

export function colorForCustomer(customerId) {
  const base = customerBaseColor(customerId)
  return `hsl(${base.hue}, ${base.saturation}%, ${base.lightness}%)`
}

export function colorForCategory(category) {
  return `hsl(${hueForKey(category)}, 58%, 60%)`
}

export function colorForItem(item) {
  if (!item?.customer_id) return colorForCategory(item?.category)

  const base = customerBaseColor(item.customer_id)
  const itemKey = item.id || item.name || item.category || item.customer_id
  const itemHash = hashKey(`${item.customer_id}:${itemKey}`)
  const hueOffset = (Math.round((itemHash * 137.508) % 360) % 81) - 40
  const saturationOffset = ((Math.floor(itemHash / 81) % 5) - 2) * 4
  const lightnessOffset = ((Math.floor(itemHash / 405) % 5) - 2) * 4
  const hue = (base.hue + hueOffset + 360) % 360
  const saturation = Math.max(38, Math.min(64, base.saturation + saturationOffset))
  const lightness = Math.max(56, Math.min(78, base.lightness + lightnessOffset))
  return `hsl(${hue}, ${saturation}%, ${lightness}%)`
}
