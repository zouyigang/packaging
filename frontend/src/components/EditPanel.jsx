import { Select, Button, Alert, Divider, Space, Switch, Tooltip } from 'antd'
import EditableTable from './EditableTable'
import { useStore } from '../store/useStore'

const itemFields = [
  { key: 'name', label: '名称', type: 'text', width: 90 },
  { key: 'length', label: '长', type: 'number', width: 70 },
  { key: 'width', label: '宽', type: 'number', width: 70 },
  { key: 'height', label: '高', type: 'number', width: 70 },
  { key: 'weight', label: '重(kg)', type: 'number', width: 75 },
  { key: 'quantity', label: '数量', type: 'number', width: 65, min: 1 },
  { key: 'stackable', label: '可堆叠', type: 'bool', width: 70 },
  { key: 'max_load_top', label: '顶承重', type: 'number', width: 80 },
  { key: 'category', label: '类别', type: 'text', width: 70 },
]

const palletFields = [
  { key: 'name', label: '名称', type: 'text', width: 90 },
  { key: 'length', label: '长', type: 'number', width: 75 },
  { key: 'width', label: '宽', type: 'number', width: 75 },
  { key: 'deck_height', label: '台面高', type: 'number', width: 80 },
  { key: 'max_stack_height', label: '限高', type: 'number', width: 80 },
  { key: 'max_load', label: '限重(kg)', type: 'number', width: 85 },
  { key: 'quantity', label: '数量', type: 'number', width: 65 },
]

const containerFields = [
  { key: 'name', label: '名称', type: 'text', width: 90 },
  { key: 'inner_length', label: '内长', type: 'number', width: 80 },
  { key: 'inner_width', label: '内宽', type: 'number', width: 80 },
  { key: 'inner_height', label: '内高', type: 'number', width: 80 },
  { key: 'max_payload', label: '载重(kg)', type: 'number', width: 90 },
  { key: 'quantity', label: '数量', type: 'number', width: 65, min: 1 },
]

const OBJECTIVES = [
  { value: 'max_utilization', label: '最大空间利用率' },
  { value: 'min_containers', label: '最少容器数' },
  { value: 'stability', label: '稳定性优先' },
  { value: 'balanced', label: '综合平衡' },
  { value: 'center_of_gravity', label: '重心居中' },
]

export default function EditPanel() {
  const objective = useStore((s) => s.objective)
  const setObjective = useStore((s) => s.setObjective)
  const solve = useStore((s) => s.solve)
  const loading = useStore((s) => s.loading)
  const error = useStore((s) => s.error)
  const useGa = useStore((s) => s.useGa)
  const setUseGa = useStore((s) => s.setUseGa)

  return (
    <div style={{ padding: 16, overflow: 'auto', height: '100%' }}>
      <h2 style={{ marginTop: 0 }}>3D 装箱</h2>
      <EditableTable kind="items" title="货品" fields={itemFields} />
      <EditableTable kind="pallets" title="托盘（可选资源）" fields={palletFields} />
      <EditableTable kind="containers" title="容器" fields={containerFields} />
      <Divider />
      <Space>
        <span>优化目标</span>
        <Select
          value={objective}
          onChange={setObjective}
          options={OBJECTIVES}
          style={{ width: 180 }}
        />
        <Tooltip title="遗传算法对放置顺序做全局优化，更慢但通常更优">
          <Space size={4}>
            <Switch size="small" checked={useGa} onChange={setUseGa} />
            <span>GA 优化</span>
          </Space>
        </Tooltip>
        <Button type="primary" loading={loading} onClick={solve}>求解装箱</Button>
      </Space>
      {error && <Alert style={{ marginTop: 12 }} type="error" message={error} showIcon />}
    </div>
  )
}
