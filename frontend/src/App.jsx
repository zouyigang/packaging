import { useEffect, useMemo, useState } from 'react'
import { Segmented, Button, Select } from 'antd'
import {
  CaretRightOutlined,
  CodeSandboxOutlined,
  DownloadOutlined,
  MinusOutlined,
  PlusOutlined,
  ReloadOutlined,
  TableOutlined,
} from '@ant-design/icons'
import EditPanel from './components/EditPanel'
import ResultPanel from './components/ResultPanel'
import TopView from './components/TopView'
import Scene, { sceneViewControls } from './three/Scene'
import { useStore } from './store/useStore'
import { colorForCustomer } from './three/geometry'
import { exportSolutionCsv } from './utils/exportCsv'
import {
  ALL_CUSTOMERS,
  ALL_ITEMS,
  EMPTY_CUSTOMER,
  customerFilterOptions,
  customerKey,
  customerLabel,
  itemFilterOptions,
} from './utils/customerFilter'

const VIEW_OPTIONS = [
  { value: '3D', label: <span className="view-seg"><CodeSandboxOutlined /> 3D 透视</span> },
  { value: '2D 俯视', label: <span className="view-seg"><TableOutlined /> 2D 俯视</span> },
]

const CURRENCY_SYMBOLS = { CNY: '¥', USD: '$', EUR: '€' }
const GRADE_LABELS = { A: '优', B: '良', C: '中', D: '差' }

function formatWeight(kg) {
  if (!Number.isFinite(kg) || kg <= 0) return '-'
  if (kg >= 1000) return `${(kg / 1000).toFixed(1)} t`
  return `${kg.toFixed(0)} kg`
}

function formatCost(costSummary) {
  if (!costSummary) return null
  const symbol = CURRENCY_SYMBOLS[costSummary.currency] || `${costSummary.currency} `
  return `${symbol}${Math.round(costSummary.total_cost).toLocaleString('zh-CN')}`
}

function UtilizationRing({ percent }) {
  const radius = 15.5
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(100, percent))
  return (
    <svg className="utilization-ring" viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r={radius} fill="none" stroke="#e5eaf2" strokeWidth="4.5" />
      <circle
        cx="20"
        cy="20"
        r={radius}
        fill="none"
        stroke="var(--primary)"
        strokeWidth="4.5"
        strokeLinecap="round"
        strokeDasharray={`${(circumference * clamped) / 100} ${circumference}`}
        transform="rotate(-90 20 20)"
      />
      <text x="20" y="21.5" textAnchor="middle" dominantBaseline="middle">{Math.round(clamped)}%</text>
    </svg>
  )
}

export default function App() {
  const [view, setView] = useState('3D')
  const solution = useStore((s) => s.solution)
  const items = useStore((s) => s.items)
  const containersInput = useStore((s) => s.containers)
  const activeContainer = useStore((s) => s.activeContainer)
  const customerFilter = useStore((s) => s.customerFilter)
  const itemFilter = useStore((s) => s.itemFilter)
  const setCustomerFilter = useStore((s) => s.setCustomerFilter)
  const setItemFilter = useStore((s) => s.setItemFilter)
  const loading = useStore((s) => s.loading)
  const solve = useStore((s) => s.solve)

  const itemMap = useMemo(() => Object.fromEntries(items.map((item) => [item.id, item])), [items])
  const loaded = solution?.containers?.[activeContainer]
  const placements = loaded?.placements || []
  const customerOptions = useMemo(
    () => customerFilterOptions(placements, itemMap),
    [placements, itemMap],
  )
  const itemOptions = useMemo(
    () => itemFilterOptions(placements, itemMap, customerFilter),
    [placements, itemMap, customerFilter],
  )

  // 顶部 KPI 与视口浮层都是对现有 solution 的展示，不改任何求解数据。
  const kpis = useMemo(() => {
    if (!solution) return null
    const used = solution.containers?.length || 0
    const available = containersInput.reduce((sum, c) => sum + (Number(c.quantity) || 0), 0)
    const utilizationRaw = solution.evaluation?.metrics?.used_volume_utilization
    const utilization = utilizationRaw !== undefined
      ? Number(utilizationRaw)
      : (solution.containers?.length
          ? solution.containers.reduce((sum, c) => sum + Number(c.volume_utilization || 0), 0) / solution.containers.length
          : 0)
    const totalKg = (solution.containers || []).reduce(
      (sum, c) => sum + c.placements.reduce((acc, p) => acc + (Number(itemMap[p.item_id]?.weight) || 0), 0),
      0,
    )
    return {
      used,
      available,
      utilization,
      totalKg,
      cost: formatCost(solution.cost_summary),
      grade: GRADE_LABELS[solution.evaluation?.grade] || '',
    }
  }, [solution, containersInput, itemMap])

  const legendCustomers = useMemo(() => {
    const seen = new Map()
    for (const placement of placements) {
      const item = itemMap[placement.item_id]
      const key = customerKey(placement.customer_id ?? item?.customer_id)
      if (!seen.has(key)) {
        seen.set(key, {
          key,
          label: key === EMPTY_CUSTOMER ? customerLabel(key) : `客户 ${customerLabel(key)}`,
          color: key === EMPTY_CUSTOMER ? '#94a3b8' : colorForCustomer(customerLabel(key)),
        })
      }
    }
    return Array.from(seen.values())
  }, [placements, itemMap])

  useEffect(() => {
    if (!customerOptions.some((option) => option.value === customerFilter)) {
      setCustomerFilter(ALL_CUSTOMERS)
    }
  }, [customerFilter, customerOptions, setCustomerFilter])

  useEffect(() => {
    if (!itemOptions.some((option) => option.value === itemFilter)) {
      setItemFilter(ALL_ITEMS)
    }
  }, [itemFilter, itemOptions, setItemFilter])

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <EditPanel />
      </aside>
      <main className="app-workspace">
        <div className="app-topbar">
          <div className="view-title">
            <strong>装箱视图</strong>
            <span>方案预览与装箱详情</span>
          </div>
          <Segmented options={VIEW_OPTIONS} value={view} onChange={setView} />
          <div style={{ flex: 1 }} />
          <div className="view-filter-group">
            <div className="view-filter-control">
              <span>客户筛选</span>
              <Select
                size="small"
                variant="borderless"
                value={customerFilter}
                options={customerOptions}
                disabled={!solution}
                onChange={setCustomerFilter}
                style={{ width: 118 }}
                popupMatchSelectWidth={220}
              />
            </div>
            <div className="view-filter-control">
              <span>货品筛选</span>
              <Select
                size="small"
                variant="borderless"
                value={itemFilter}
                options={itemOptions}
                disabled={!solution}
                onChange={setItemFilter}
                style={{ width: 118 }}
                popupMatchSelectWidth={220}
              />
            </div>
          </div>
          <Button
            icon={<DownloadOutlined />}
            disabled={!solution}
            aria-label="导出 CSV"
            onClick={() => exportSolutionCsv(solution, items)}
          >
            导出
          </Button>
        </div>

        {kpis && (
          <div className="kpi-strip">
            <div className="kpi kpi-primary">
              <span>空间利用率</span>
              <strong>{(kpis.utilization * 100).toFixed(1)}%</strong>
            </div>
            <div className="kpi">
              <span>使用箱数</span>
              <strong>{kpis.used}{kpis.available > 0 ? ` / ${kpis.available}` : ''}</strong>
            </div>
            {kpis.cost && (
              <div className="kpi">
                <span>预估成本</span>
                <strong>{kpis.cost}</strong>
              </div>
            )}
            <div className="kpi">
              <span>总重量</span>
              <strong>{formatWeight(kpis.totalKg)}</strong>
            </div>
          </div>
        )}

        <div className="app-viewport">
          {view === '3D' ? <Scene /> : <TopView />}

          {solution && legendCustomers.length > 0 && (
            <div className="viewport-legend">
              {legendCustomers.map((customer) => (
                <span key={customer.key} className="legend-chip">
                  <i style={{ background: customer.color }} />
                  {customer.label}
                </span>
              ))}
            </div>
          )}

          {solution && kpis && (
            <div className="viewport-score-card">
              <UtilizationRing percent={kpis.utilization * 100} />
              <div className="viewport-score-text">
                <span>空间利用率</span>
                <strong>{kpis.grade ? `${kpis.grade} · ` : ''}已装 {kpis.used} 箱</strong>
              </div>
            </div>
          )}

          <div className="viewport-caption">
            {view === '3D' ? '透视视图 · 自由旋转' : '俯视视图 · 装载序号'}
          </div>

          {view === '3D' && (
            <div className="viewport-zoom">
              <button type="button" aria-label="放大" onClick={() => sceneViewControls.zoomIn()}><PlusOutlined /></button>
              <button type="button" aria-label="缩小" onClick={() => sceneViewControls.zoomOut()}><MinusOutlined /></button>
              <button type="button" aria-label="重置视角" onClick={() => sceneViewControls.reset()}><ReloadOutlined /></button>
            </div>
          )}

          {!solution && (
            <div className="viewport-empty">
              <div className="viewport-empty-card">
                <span className="viewport-empty-icon"><CodeSandboxOutlined /></span>
                <strong>尚未生成装箱方案</strong>
                <p>配置货品、托盘与容器后，点击下方按钮生成装箱方案，可在 3D 透视与 2D 俯视间切换查看。</p>
                {/* aria-label 让 e2e 的 /求解装箱/ 只命中侧栏那颗按钮，避免 strict mode 撞两个 */}
                <Button
                  type="primary"
                  size="large"
                  icon={<CaretRightOutlined />}
                  loading={loading}
                  aria-label="生成装箱方案"
                  onClick={solve}
                >
                  求解装箱
                </Button>
              </div>
            </div>
          )}
        </div>
        <ResultPanel />
      </main>
    </div>
  )
}
