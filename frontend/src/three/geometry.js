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
export function colorForCategory(category) {
  const key = category || 'default'
  let hash = 0
  for (let i = 0; i < key.length; i++) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0
  }
  const hue = Math.round((hash * 137.508) % 360)
  return `hsl(${hue}, 65%, 52%)`
}
