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
const EQUIPMENT_PROFILE_OPTIONS = [
  { value: 'generic', label: '通用容器' },
  { value: 'iso_container', label: 'ISO 集装箱' },
  { value: 'road_vehicle', label: '道路车辆' },
]
const RESTRAINT_MODE_OPTIONS = [
  { value: 'unverified', label: '未核验（仅告警）' },
  { value: 'none', label: '无固定装置' },
  { value: 'rated', label: '额定固定能力' },
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
  { key: 'must_load', label: '必须装载', type: 'bool' },
  { key: 'priority', label: '业务优先级', type: 'number', min: 0 },
  { key: 'pallet_group', label: '混托兼容组', type: 'text' },
  { key: 'friction_coefficient', label: '摩擦系数', type: 'number', min: 0 },
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
  { key: 'handling_cost', label: '处理成本', type: 'number' },
  { key: 'friction_coefficient', label: '摩擦系数', type: 'number', min: 0 },
]

const containerFields = [
  { key: 'name', label: '名称', type: 'text' },
  { key: 'inner_length', label: '内长(cm)', type: 'number' },
  { key: 'inner_width', label: '内宽(cm)', type: 'number' },
  { key: 'inner_height', label: '内高(cm)', type: 'number' },
  { key: 'max_payload', label: '载重(kg)', type: 'number' },
  { key: 'equipment_profile', label: '设备模板', type: 'select', options: EQUIPMENT_PROFILE_OPTIONS, defaultValue: 'generic' },
  { key: 'use_cost', label: '启用成本', type: 'number' },
  { key: 'max_floor_load_kg_m2', label: '地板载荷(kg/m²)', type: 'number' },
  { key: 'default_friction_coefficient', label: '默认摩擦系数', type: 'number' },
  { key: 'restraint_mode', label: '堆垛固定模式', type: 'select', options: RESTRAINT_MODE_OPTIONS, defaultValue: 'unverified' },
  { key: 'longitudinal_restraint_capacity_kn', label: '纵向固定能力(kN)', type: 'number', min: 0 },
  { key: 'transverse_restraint_capacity_kn', label: '横向固定能力(kN)', type: 'number', min: 0 },
  { key: 'cog_x_min_ratio', label: '重心X下限(0-1)', type: 'number' },
  { key: 'cog_x_max_ratio', label: '重心X上限(0-1)', type: 'number' },
  { key: 'cog_y_min_ratio', label: '重心Y下限(0-1)', type: 'number' },
  { key: 'cog_y_max_ratio', label: '重心Y上限(0-1)', type: 'number' },
  { key: 'cog_z_max_ratio', label: '重心Z上限(0-1)', type: 'number' },
  { key: 'longitudinal_g', label: '纵向加速度(g)', type: 'number' },
  { key: 'transverse_g', label: '横向加速度(g)', type: 'number' },
  { key: 'vertical_g', label: '垂向加速度(g)', type: 'number' },
  { key: 'load_distribution_curve_json', label: '载荷曲线JSON', type: 'text' },
  { key: 'loading_accesses', label: '装货入口', type: 'loading_accesses', options: LOADING_ACCESS_OPTIONS, defaultValue: DEFAULT_LOADING_ACCESS },
  { key: 'quantity', label: '数量', type: 'number', min: 1 },
]

const PRODUCTION_OBJECTIVES = [
  {
    value: 'cost_efficiency',
    label: '成本效率',
    description: '完成必装与优先货物后，最小化容器启用成本和托盘处理成本。',
  },
  {
    value: 'space_utilization',
    label: '空间利用',
    description: '优先选择最佳适配容器，提高已使用容器的体积利用率。',
  },
  {
    value: 'safe_loading',
    label: '安全装载',
    description: '同时优化堆垛稳定、承重裕量和整体载荷分布。',
  },
  {
    value: 'delivery_sequence',
    label: '顺序配送',
    description: '保证按站点直接卸货、禁止倒货，并检查卸货后的剩余载荷。',
  },
]

const ADVANCED_OBJECTIVES = [
  {
    value: 'custom',
    label: '高级自定义',
    description: '在安全硬约束下自定义成本、空间、稳定、均衡与装卸权重。',
  },
]

const OBJECTIVES = [
  { label: '生产策略', options: PRODUCTION_OBJECTIVES },
  { label: '高级模式', options: ADVANCED_OBJECTIVES },
]
const FLAT_OBJECTIVES = [...PRODUCTION_OBJECTIVES, ...ADVANCED_OBJECTIVES]
const ADVANCED_WEIGHT_FIELDS = [
  { key: 'cost_efficiency', label: '成本效率' },
  { key: 'space_utilization', label: '空间利用' },
  { key: 'stability', label: '稳定性' },
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
  return value === 'custom' || value === 'advanced_score' || value === 'balanced'
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
  const validationMode = useStore((s) => s.validationMode)
  const setValidationMode = useStore((s) => s.setValidationMode)
  const palletPolicy = useStore((s) => s.palletPolicy)
  const setPalletPolicy = useStore((s) => s.setPalletPolicy)
  const costCurrency = useStore((s) => s.costCurrency)
  const setCostCurrency = useStore((s) => s.setCostCurrency)
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
            <Select
              size="small"
              value={validationMode}
              onChange={setValidationMode}
              options={[{ value: 'standard', label: '标准校验' }, { value: 'industrial', label: '工业校验' }]}
              style={{ width: 100 }}
            />
            <Select
              size="small"
              value={palletPolicy}
              onChange={setPalletPolicy}
              options={[
                { value: 'auto', label: '托盘自动' },
                { value: 'prefer', label: '偏好托盘' },
                { value: 'avoid', label: '避免托盘' },
                { value: 'required', label: '必须托盘' },
              ]}
              style={{ width: 100 }}
            />
            <Select
              size="small"
              value={costCurrency}
              onChange={setCostCurrency}
              options={['CNY', 'USD', 'EUR'].map((value) => ({ value, label: value }))}
              style={{ width: 72 }}
            />
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
