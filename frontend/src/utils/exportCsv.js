import { orientedDims } from '../three/geometry'

// 把装箱方案导出为 CSV（一行一个放置），含朝向后的实际尺寸，便于在 Excel 复核。
export function exportSolutionCsv(solution, items) {
  const itemMap = Object.fromEntries(items.map((i) => [i.id, i]))
  const header = [
    '容器序号', '容器id', '装箱顺序seq', '货品id', '托盘id',
    'customer_id', 'order_id', 'destination_id', 'stop_seq',
    'x(cm)', 'y(cm)', 'z(cm)', '朝向', '长dx(cm)', '宽dy(cm)', '高dz(cm)', '重量(kg)',
  ]
  const rows = [header]

  solution.containers.forEach((c, ci) => {
    const ordered = [...c.placements].sort((a, b) => a.seq - b.seq)
    ordered.forEach((p) => {
      const it = itemMap[p.item_id]
      const [dx, dy, dz] = it
        ? orientedDims(it.length, it.width, it.height, p.orientation)
        : ['', '', '']
      rows.push([
        ci + 1, c.id, p.seq, p.item_id, p.pallet_id ?? '',
        p.customer_id ?? it?.customer_id ?? '', p.order_id ?? it?.order_id ?? '',
        p.destination_id ?? it?.destination_id ?? '', p.stop_seq ?? it?.stop_seq ?? 1,
        p.x, p.y, p.z, p.orientation, dx, dy, dz, it?.weight ?? '',
      ])
    })
  })

  if (solution.unpacked?.length) {
    rows.push([])
    rows.push(['余货(未装入)', ...solution.unpacked])
  }

  const csv = rows.map((r) => r.map(csvCell).join(',')).join('\r\n')
  // 加 BOM 让 Excel 正确识别 UTF-8 中文
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
  triggerDownload(blob, `packing-report-${Date.now()}.csv`)
}

function csvCell(v) {
  const s = String(v ?? '')
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
