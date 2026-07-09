import { Select, Button, Alert, Divider, Space, Switch, Tooltip, Slider } from 'antd'
import EditableTable from './EditableTable'
import { useStore } from '../store/useStore'

const STACKING_TYPE_OPTIONS = [
  { value: 'not_stackable', label: '独立放置', description: '上方不能压货，下方也不能垫其它货，只能直接落地' },
  { value: 'same_item_only', label: '仅同品上下堆放', description: '上方/下方都允许，但直接接触的上下货品必须是同一种' },
  { value: 'stackable', label: '可上下堆放', description: '上方可压货，下方也可垫货，无同品限制' },
  { value: 'support_only', label: '仅作下层支撑', description: '只能在下层，上方可以压货，但自己下方不能有其它货' },
  { value: 'top_only', label: '仅作上层货品', description: '只能放在其它货品上，上方不能再压货' },
]

const LOADING_ACCESS_OPTIONS = [
  { value: 'x_max', label: '后门', description: '从容器长度末端装货，适合常规集装箱和厢式车尾门' },
  { value: 'x_min', label: '前门', description: '从容器长度起点装货，装箱顺序会从另一端开始' },
  { value: 'y_min', label: '左侧门', description: '从宽度一侧装货，适合侧开门车厢或侧向月台' },
  { value: 'y_max', label: '右侧门', description: '从另一侧宽度方向装货，可与左侧门组合使用' },
  { value: 'z_max', label: '顶部吊装', description: '从顶部入口装货，适合开顶箱或吊装作业' },
]

const DEFAULT_LOADING_ACCESS = [
  { side: 'x_max', door_width: null, door_height: null, opening_start: null, opening_end: null },
]
const itemFields = [
  { key: 'name', label: '名称', type: 'text' },
  { key: 'length', label: '长(cm)', type: 'number' },
  { key: 'width', label: '宽(cm)', type: 'number' },
  { key: 'height', label: '高(cm)', type: 'number' },
  { key: 'weight', label: '重(kg)', type: 'number' },
  { key: 'quantity', label: '数量', type: 'number', min: 1 },
  { key: 'stacking_type', label: '堆叠类型', type: 'stacking_type_cards', options: STACKING_TYPE_OPTIONS, defaultValue: 'stackable' },
  { key: 'allowed_rotations', label: '允许摆放姿态', type: 'orientation_groups' },
  { key: 'max_load_top', label: '顶承重(kg)', type: 'number' },
  { key: 'category', label: '类别', type: 'text' },
  { key: 'customer_id', label: '客户', type: 'text' },
  { key: 'order_id', label: '订单', type: 'text' },
  { key: 'destination_id', label: '目的地', type: 'text' },
  { key: 'stop_seq', label: '卸货顺序', type: 'number', min: 1 },
]

const palletFields = [
  { key: 'name', label: '名称', type: 'text' },
  { key: 'length', label: '长(cm)', type: 'number' },
  { key: 'width', label: '宽(cm)', type: 'number' },
  { key: 'tare_weight', label: '自重(kg)', type: 'number' },
  { key: 'deck_height', label: '台面高(cm)', type: 'number' },
  { key: 'max_stack_height', label: '限高(cm)', type: 'number' },
  { key: 'max_load', label: '限重(kg)', type: 'number' },
  { key: 'quantity', label: '数量', type: 'number' },
]

const containerFields = [
  { key: 'name', label: '名称', type: 'text' },
  { key: 'inner_length', label: '内长(cm)', type: 'number' },
  { key: 'inner_width', label: '内宽(cm)', type: 'number' },
  { key: 'inner_height', label: '内高(cm)', type: 'number' },
  { key: 'max_payload', label: '载重(kg)', type: 'number' },
  { key: 'loading_accesses', label: '装货入口', type: 'loading_accesses', options: LOADING_ACCESS_OPTIONS, defaultValue: DEFAULT_LOADING_ACCESS },
  { key: 'quantity', label: '数量', type: 'number', min: 1 },
]

const PRODUCTION_OBJECTIVES = [
  {
    value: 'transport_cost',
    label: '运输成本优先',
    description: '尽量少用容器/车辆，优先提高装载率，适合以运费和箱量为主要考核的发运场景。',
  },
  {
    value: 'load_stability',
    label: '装载稳定优先',
    description: '更偏好低重心、大底面、少堆高，适合易损货、重货或对运输稳定性要求更高的场景。',
  },
  {
    value: 'weight_balance',
    label: '重心均衡优先',
    description: '更关注前后/左右重量均衡，减少偏载风险，适合集装箱、车辆和长距离运输。',
  },
  {
    value: 'loading_efficiency',
    label: '装卸/多客户配送优先',
    description: '按装货入口和卸货顺序安排位置，同一站点内尽量聚集相同客户或订单的货品。',
  },
]

const ADVANCED_OBJECTIVES = [
  {
    value: 'advanced_score',
    label: '综合评分',
    description: '高级模式：在装载率、稳定性、托盘化和位置评分之间做折中，适合需要调试算法效果的场景。',
  },
]

const OBJECTIVES = [
  { label: '生产策略', options: PRODUCTION_OBJECTIVES },
  { label: '高级模式', options: ADVANCED_OBJECTIVES },
]
const FLAT_OBJECTIVES = [...PRODUCTION_OBJECTIVES, ...ADVANCED_OBJECTIVES]
const ADVANCED_WEIGHT_FIELDS = [
  { key: 'space_utilization', label: '空间利用' },
  { key: 'stability', label: '稳定性' },
  { key: 'palletization', label: '托盘化' },
  { key: 'balance', label: '重心均衡' },
  { key: 'loading_position', label: '装卸位置' },
]

const GA_SPEED_OPTIONS = [
  { value: 'fast', label: '快速' },
  { value: 'standard', label: '标准' },
  { value: 'fine', label: '精细' },
]

const GA_SPEED_LABELS = {
  fast: '快速',
  standard: '标准',
  fine: '精细',
}

function objectiveMeta(value) {
  return FLAT_OBJECTIVES.find((item) => item.value === value) || PRODUCTION_OBJECTIVES[0]
}

function isAdvancedObjective(value) {
  return value === 'advanced_score' || value === 'balanced'
}

export default function EditPanel() {
  const objective = useStore((s) => s.objective)
  const setObjective = useStore((s) => s.setObjective)
  const advancedWeights = useStore((s) => s.advancedWeights)
  const setAdvancedWeight = useStore((s) => s.setAdvancedWeight)
  const resetAdvancedWeights = useStore((s) => s.resetAdvancedWeights)
  const solve = useStore((s) => s.solve)
  const loading = useStore((s) => s.loading)
  const error = useStore((s) => s.error)
  const useGa = useStore((s) => s.useGa)
  const setUseGa = useStore((s) => s.setUseGa)
  const gaSpeed = useStore((s) => s.gaSpeed)
  const setGaSpeed = useStore((s) => s.setGaSpeed)
  const selectedObjective = objectiveMeta(objective)
  const solveButtonText = loading
    ? (useGa ? `GA ${GA_SPEED_LABELS[gaSpeed] || '标准'}模式求解中` : `${selectedObjective.label}求解中`)
    : '求解装箱'

  return (
    <div className="edit-panel">
      <div className="edit-header">
        <h1>3D 装箱</h1>
        <p>维护基础资源，生成可回放的装载方案</p>
      </div>

      <EditableTable kind="items" title="货品" fields={itemFields} />
      <EditableTable kind="pallets" title="托盘（可选资源）" fields={palletFields} />
      <EditableTable kind="containers" title="容器" fields={containerFields} />

      <Divider />
      <div className="solve-card">
        <div className="solve-grid">
          <label>
            <span className="field-label">装箱策略</span>
            <Select
              value={objective}
              onChange={setObjective}
              options={OBJECTIVES}
              style={{ width: '100%' }}
              optionRender={(option) => (
                <div className="objective-option">
                  <strong>{option.data.label}</strong>
                  {option.data.description && <span>{option.data.description}</span>}
                </div>
              )}
            />
          </label>
          <div className="objective-meaning">
            <strong>{selectedObjective.label}</strong>
            <span>{selectedObjective.description}</span>
          </div>
          {isAdvancedObjective(objective) && (
            <div className="advanced-weights">
              <div className="advanced-weights-head">
                <strong>权重</strong>
                <Button size="small" onClick={resetAdvancedWeights}>恢复默认</Button>
              </div>
              <div className="advanced-weight-list">
                {ADVANCED_WEIGHT_FIELDS.map((field) => {
                  const value = advancedWeights[field.key] ?? 0
                  return (
                    <label className="advanced-weight-row" key={field.key}>
                      <span className="advanced-weight-label">{field.label}</span>
                      <Slider
                        min={0}
                        max={100}
                        step={5}
                        value={Math.round(value * 100)}
                        onChange={(nextValue) => setAdvancedWeight(field.key, nextValue / 100)}
                      />
                      <span className="advanced-weight-value">{Math.round(value * 100)}%</span>
                    </label>
                  )
                })}
              </div>
            </div>
          )}
          <div className="solve-actions">
            <Tooltip title="遗传算法对放置顺序做全局优化，更慢但通常更优">
              <Space size={6}>
                <Switch size="small" checked={useGa} onChange={setUseGa} />
                <span>GA 优化</span>
              </Space>
            </Tooltip>
            <Select
              size="small"
              value={gaSpeed}
              onChange={setGaSpeed}
              options={GA_SPEED_OPTIONS}
              disabled={!useGa}
              style={{ width: 82 }}
            />
            <Button type="primary" loading={loading} onClick={solve}>{solveButtonText}</Button>
          </div>
        </div>
      </div>
      {error && <Alert style={{ marginTop: 12 }} type="error" message={error} showIcon />}
    </div>
  )
}
