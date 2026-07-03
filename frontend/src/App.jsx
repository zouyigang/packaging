import { useState } from 'react'
import { Segmented, Button } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import EditPanel from './components/EditPanel'
import ResultPanel from './components/ResultPanel'
import TopView from './components/TopView'
import Scene from './three/Scene'
import { useStore } from './store/useStore'
import { exportSolutionCsv } from './utils/exportCsv'

export default function App() {
  const [view, setView] = useState('3D')
  const solution = useStore((s) => s.solution)
  const items = useStore((s) => s.items)

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
