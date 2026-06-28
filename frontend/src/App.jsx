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
    <div style={{ display: 'flex', height: '100vh' }}>
      <div style={{ width: 560, borderRight: '1px solid #f0f0f0', height: '100%' }}>
        <EditPanel />
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 16px', borderBottom: '1px solid #f0f0f0' }}>
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
        <div style={{ flex: 1, minHeight: 0, background: '#fafafa' }}>
          {view === '3D' ? <Scene /> : <TopView />}
        </div>
        <ResultPanel />
      </div>
    </div>
  )
}
