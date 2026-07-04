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

// 按 category 稳定生成一个颜色（HSL），同类同色。
// 用黄金角(137.5°)散布色相，避免相邻类别（如 'A'/'B'）色相只差 1° 而看不出区别。
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

export function colorForCategory(category) {
  return `hsl(${hueForKey(category)}, 65%, 52%)`
}

export function colorForItem(item) {
  if (!item?.customer_id) return colorForCategory(item?.category)

  const baseHue = hueForKey(item.customer_id)
  const variant = hashKey(item.id || item.name || item.category) % 7
  const hueOffset = [-5, -3, -1, 0, 2, 4, 6][variant]
  const saturation = [62, 66, 70, 64, 68, 72, 65][variant]
  const lightness = [47, 51, 55, 49, 53, 57, 45][variant]
  const hue = (baseHue + hueOffset + 360) % 360
  return `hsl(${hue}, ${saturation}%, ${lightness}%)`
}
