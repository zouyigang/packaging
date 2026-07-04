import { useEffect, useMemo, useState } from 'react'
import { Segmented, Button, Select } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import EditPanel from './components/EditPanel'
import ResultPanel from './components/ResultPanel'
import TopView from './components/TopView'
import Scene from './three/Scene'
import { useStore } from './store/useStore'
import { exportSolutionCsv } from './utils/exportCsv'
import { ALL_CUSTOMERS, ALL_ITEMS, customerFilterOptions, itemFilterOptions } from './utils/customerFilter'

export default function App() {
  const [view, setView] = useState('3D')
  const solution = useStore((s) => s.solution)
  const items = useStore((s) => s.items)
  const activeContainer = useStore((s) => s.activeContainer)
  const customerFilter = useStore((s) => s.customerFilter)
  const itemFilter = useStore((s) => s.itemFilter)
  const setCustomerFilter = useStore((s) => s.setCustomerFilter)
  const setItemFilter = useStore((s) => s.setItemFilter)

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
            <strong>装载视图</strong>
            <span>方案预览与顺序回放</span>
          </div>
          <Segmented options={['3D', '2D 俯视']} value={view} onChange={setView} />
          <div style={{ flex: 1 }} />
          <div className="view-filter-group">
            <div className="view-filter-control">
              <span>客户筛选</span>
              <Select
                size="small"
                value={customerFilter}
                options={customerOptions}
                disabled={!solution}
                onChange={setCustomerFilter}
                style={{ width: 150 }}
                popupMatchSelectWidth={220}
              />
            </div>
            <div className="view-filter-control">
              <span>货品筛选</span>
              <Select
                size="small"
                value={itemFilter}
                options={itemOptions}
                disabled={!solution}
                onChange={setItemFilter}
                style={{ width: 150 }}
                popupMatchSelectWidth={220}
              />
            </div>
          </div>
          <Button
            icon={<DownloadOutlined />}
            disabled={!solution}
            onClick={() => exportSolutionCsv(solution, items)}
          >
            导出 CSV
          </Button>
        </div>
        <div className="app-viewport">
          {view === '3D' ? <Scene /> : <TopView />}
        </div>
        <ResultPanel />
      </main>
    </div>
  )
}