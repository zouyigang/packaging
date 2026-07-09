import { orientedDims } from '../three/geometry'

const STAGE_LABELS = {
  build_placeables: '构造货品',
  pack_containers: '容器装载',
  pack_single_container: '单箱装载',
  find_placement: '寻找位置',
  evaluator: '方案评分',
  ga_initial_population: 'GA 初始种群',
  ga_generation: 'GA 迭代',
  ga_decode: 'GA 解码',
}

const COUNTER_LABELS = {
  find_placement_calls: '位置搜索次数',
  candidate_points_ready: '候选点数',
  candidate_boxes_scored: '候选评分',
  candidate_boxes_checked: '硬约束检查',
  candidate_boxes_skipped_by_bound: '下界跳过',
  overlap_scan_items: '碰撞扫描',
  overlap_candidate_items: '碰撞候选',
  support_scan_items: '支撑扫描',
  support_candidate_items: '支撑候选',
  fallback_balance_calls: '重心 fallback',
  ga_generations_completed: 'GA 完成代数',
  ga_decode_cache_hits: 'GA 缓存命中',
  ga_decode_cache_misses: 'GA 缓存未命中',
}

// 把装箱方案导出为 CSV（一行一个放置），含朝向后的实际尺寸，便于在 Excel 复核。
export function exportSolutionCsv(solution, items) {
  const itemMap = Object.fromEntries(items.map((i) => [i.id, i]))
  const rows = buildSummaryRows(solution)
  rows.push([])
  rows.push(['装载明细'])
  const header = [
    '容器序号', '容器id', '装箱顺序seq', '货品id', '托盘id',
    'customer_id', 'order_id', 'destination_id', 'stop_seq',
    'x(cm)', 'y(cm)', 'z(cm)', '朝向', '长dx(cm)', '宽dy(cm)', '高dz(cm)', '重量(kg)',
  ]
  rows.push(header)

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

function buildSummaryRows(solution) {
  const evaluation = solution?.evaluation || {}
  const performance = solution?.performance || {}
  const containers = solution?.containers || []
  const loadedCount = containers.reduce((sum, container) => sum + (container.placements?.length || 0), 0)
  const rows = [
    ['方案摘要'],
    ['导出时间', new Date().toLocaleString('zh-CN')],
    ['策略', evaluation.objective || ''],
    ['评分', formatNumber(evaluation.score, 1)],
    ['等级', evaluation.grade || ''],
    ['容器数', containers.length],
    ['已装件数', loadedCount],
    ['余货件数', solution?.unpacked?.length || 0],
    ['求解耗时(ms)', formatNumber(performance.runtime_ms, 3)],
  ]

  const metrics = evaluation.metrics || {}
  if (Object.keys(metrics).length > 0) {
    rows.push([])
    rows.push(['评分指标'])
    Object.entries(metrics).forEach(([key, value]) => {
      rows.push([key, formatNumber(Number(value) * 100, 1) + '%'])
    })
  }

  const stages = Object.entries(performance.stages_ms || {})
    .filter(([, value]) => Number(value) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
  if (stages.length > 0) {
    rows.push([])
    rows.push(['阶段耗时'])
    stages.forEach(([key, value]) => {
      rows.push([STAGE_LABELS[key] || key, formatNumber(value, 3), 'ms'])
    })
  }

  const counters = Object.entries(COUNTER_LABELS)
    .map(([key, label]) => [label, performance.counters?.[key]])
    .filter(([, value]) => value !== undefined && Number(value) !== 0)
  if (counters.length > 0) {
    rows.push([])
    rows.push(['关键计数'])
    counters.forEach(([label, value]) => {
      rows.push([label, value])
    })
  }

  return rows
}

function formatNumber(value, digits) {
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  return number.toFixed(digits)
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
