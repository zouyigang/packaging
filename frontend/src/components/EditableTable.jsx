import { Button, Checkbox, Empty, Input, InputNumber, Modal, Select, Space, Switch, Tooltip } from 'antd'
import { CheckOutlined, DeleteOutlined, DownOutlined, EditOutlined, LockOutlined, PlusOutlined, RightOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { useStore } from '../store/useStore'
import { colorForCustomer } from '../three/geometry'

const ORIENTATION_ORDER = ['LWH', 'WLH', 'LHW', 'HLW', 'WHL', 'HWL']
const TOP_LOAD_LOCKED_STACKING_TYPES = new Set(['not_stackable', 'top_only'])
const ORIENTATION_GROUPS = [
  {
    key: 'default_base',
    label: '默认底面朝下',
    description: '高作为竖直方向，底面为长 × 宽',
    base: '长 × 宽',
    vertical: '高',
    rotations: ['LWH', 'WLH'],
    dimKeys: ['length', 'width', 'height'],
    fixed: true,
  },
  {
    key: 'length_height_base',
    label: '长高面朝下',
    description: '宽作为竖直方向，底面为长 × 高',
    base: '长 × 高',
    vertical: '宽',
    rotations: ['LHW', 'HLW'],
    dimKeys: ['length', 'height', 'width'],
  },
  {
    key: 'width_height_base',
    label: '宽高面朝下',
    description: '长作为竖直方向，底面为宽 × 高',
    base: '宽 × 高',
    vertical: '长',
    rotations: ['WHL', 'HWL'],
    dimKeys: ['width', 'height', 'length'],
  },
]

// 货品弹窗的分区布局：基本信息两行网格 + 堆叠/姿态紧凑卡片 + 可折叠「更多参数」。
const STACKING_SHORT_LABELS = {
  not_stackable: '独立放置',
  same_item_only: '仅同品堆叠',
  stackable: '可上下堆放',
  support_only: '仅作下层支撑',
  top_only: '仅作上层货品',
}
const ITEM_MORE_FIELD_KEYS = [
  'max_load_top',
  'category',
  'customer_id',
  'order_id',
  'destination_id',
  'stop_seq',
  'pallet_group',
  'friction_coefficient',
  'priority',
]
const ITEM_FIELD_PLACEHOLDERS = {
  max_load_top: '不限',
  category: '如 五金 / 塑件',
  customer_id: '客户名称',
  order_id: '关联订单号',
  destination_id: '目的港 / 城市',
  stop_seq: '数字越小越先卸',
  pallet_group: '同组不与他组混托',
  friction_coefficient: '默认 0.5',
}

// 容器弹窗：基本信息 + 装货入口卡片 + 可折叠「更多参数」（按成本/固定/重心/加速度/开口分组）。
const CONTAINER_FIELD_PLACEHOLDERS = {
  use_cost: '0',
  max_floor_load_kg_m2: '不限',
  default_friction_coefficient: '0.5',
  longitudinal_restraint_capacity_kn: '不限',
  transverse_restraint_capacity_kn: '不限',
  cog_x_min_ratio: '0',
  cog_y_min_ratio: '0',
  cog_z_max_ratio: '1',
  cog_x_max_ratio: '1',
  cog_y_max_ratio: '1',
  longitudinal_g: '0',
  transverse_g: '0',
  vertical_g: '0',
  load_distribution_curve_json: '[{"h":0,"load":1}, …]',
}
// 「更多参数」里用更短的标签（分组标题已给出上下文），不改动 EditPanel 里的字段定义。
const CONTAINER_FIELD_LABELS = {
  cog_x_min_ratio: 'X 下限',
  cog_y_min_ratio: 'Y 下限',
  cog_z_max_ratio: 'Z 上限',
  cog_x_max_ratio: 'X 上限',
  cog_y_max_ratio: 'Y 上限',
  longitudinal_g: '纵向加速度',
  transverse_g: '横向加速度',
  vertical_g: '垂向加速度',
  load_distribution_curve_json: '载荷曲线 JSON',
}

export default function EditableTable({ kind, title, fields }) {
  const rows = useStore((s) => s[kind])
  const updateRow = useStore((s) => s.updateRow)
  const removeRow = useStore((s) => s.removeRow)
  const addRow = useStore((s) => s.addRow)
  const createBlankRow = useStore((s) => s.createBlankRow)
  const [editingId, setEditingId] = useState(null)
  const [addingRow, setAddingRow] = useState(null)
  const [collapsed, setCollapsed] = useState(false)
  const isItems = kind === 'items'
  const isContainers = kind === 'containers'
  const useSheet = isItems || isContainers
  const SheetForm = isItems ? ItemModalForm : ContainerModalForm
  const SheetTitle = isItems ? ItemModalTitle : ContainerModalTitle
  const sheetSubtitleAdd = isItems
    ? '填写尺寸与堆叠规则，其余参数可展开补充'
    : '填写内尺寸与装货入口，力学与重心参数可展开补充'
  const sheetWidth = isItems ? 860 : 920
  const sheetClassName = isContainers ? 'item-modal container-modal' : 'item-modal'
  const [mainTitle, hintTitle] = splitSectionTitle(title)

  const editingRow = rows.find((row) => row.id === editingId) || null

  const handleAddClick = () => {
    setAddingRow(createBlankRow(kind))
  }

  const handleAddChange = (field, value) => {
    setAddingRow((row) => (row ? { ...row, ...makePatch(field, value) } : row))
  }

  const handleAddConfirm = () => {
    if (!addingRow) return
    addRow(kind, addingRow)
    setAddingRow(null)
  }

  return (
    <section className="resource-section">
      <div className="resource-section-head">
        <strong>{mainTitle}</strong>
        {hintTitle && <span className="resource-hint">{hintTitle}</span>}
        <span className="resource-count">{rows.length}</span>
        <div style={{ flex: 1 }} />
        <Button size="small" color="primary" variant="filled" icon={<PlusOutlined />} onClick={handleAddClick}>新增</Button>
        <Button
          size="small"
          type="text"
          className="resource-collapse"
          aria-label={collapsed ? `展开${mainTitle}` : `折叠${mainTitle}`}
          icon={<DownOutlined className={`resource-collapse-icon ${collapsed ? 'is-collapsed' : ''}`} />}
          onClick={() => setCollapsed((value) => !value)}
        />
      </div>

      {!collapsed && (rows.length === 0 ? (
        <div className="resource-empty">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />
        </div>
      ) : (
        rows.map((row) => (
          <ResourceRow
            key={row.id}
            row={row}
            fields={fields}
            kind={kind}
            onEdit={() => setEditingId(row.id)}
            onRemove={() => removeRow(kind, row.id)}
          />
        ))
      ))}

      <Modal
        title={useSheet ? (
          <SheetTitle title={`新增${title}`} subtitle={sheetSubtitleAdd} />
        ) : `新增${title}`}
        open={!!addingRow}
        onCancel={() => setAddingRow(null)}
        onOk={handleAddConfirm}
        okText="确定"
        cancelText="取消"
        width={useSheet ? sheetWidth : 900}
        centered={useSheet}
        className={useSheet ? sheetClassName : undefined}
        footer={useSheet ? (
          <div className="item-modal-footer">
            <span className="item-dim-summary">{sheetSummary(kind, addingRow)}</span>
            <Button onClick={() => setAddingRow(null)}>取消</Button>
            <Button type="primary" icon={<CheckOutlined />} onClick={handleAddConfirm}>确定</Button>
          </div>
        ) : undefined}
        destroyOnHidden
      >
        {addingRow && (useSheet ? (
          <SheetForm
            fields={fields}
            row={addingRow}
            onChange={handleAddChange}
          />
        ) : (
          <div className="modal-field-grid">
            {fields.map((field) => (
              <FieldEditor
                key={field.key}
                field={field}
                row={addingRow}
                value={addingRow[field.key]}
                onChange={(value) => handleAddChange(field, value)}
              />
            ))}
          </div>
        ))}
      </Modal>
      <Modal
        title={editingRow ? (useSheet ? (
          <SheetTitle title={`${title} · ${editingRow.name || title}`} subtitle="修改即时保存，可随时关闭" />
        ) : `${title} · ${editingRow.name || title}`) : title}
        open={!!editingRow}
        onCancel={() => setEditingId(null)}
        footer={useSheet && editingRow ? (
          <div className="item-modal-footer">
            <span className="item-dim-summary">{sheetSummary(kind, editingRow)}</span>
            <Button type="primary" onClick={() => setEditingId(null)}>完成</Button>
          </div>
        ) : null}
        width={useSheet ? sheetWidth : 900}
        centered={useSheet}
        className={useSheet ? sheetClassName : undefined}
        destroyOnHidden
      >
        {editingRow && (useSheet ? (
          <SheetForm
            fields={fields}
            row={editingRow}
            onChange={(field, value) => updateRow(kind, editingRow.id, makePatch(field, value))}
          />
        ) : (
          <div className="modal-field-grid">
            {fields.map((field) => (
              <FieldEditor
                key={field.key}
                field={field}
                row={editingRow}
                value={editingRow[field.key]}
                onChange={(value) => updateRow(kind, editingRow.id, makePatch(field, value))}
              />
            ))}
          </div>
        ))}
      </Modal>
    </section>
  )
}

function splitSectionTitle(title) {
  const match = /^(.+?)（(.+)）$/.exec(title)
  return match ? [match[1], match[2]] : [title, '']
}

function customerAccent(customerName) {
  const color = colorForCustomer(customerName)
  const match = /^hsl\((\d+),\s*[^,]+,\s*[^)]+\)$/.exec(color)
  if (!match) {
    return { line: color, text: color, border: color, background: '#f8fafc' }
  }
  const hue = match[1]
  return {
    line: `hsl(${hue}, 58%, 76%)`,
    text: `hsl(${hue}, 58%, 34%)`,
    border: `hsl(${hue}, 52%, 78%)`,
    background: `hsl(${hue}, 72%, 96%)`,
  }
}
function normalizeCustomer(value) {
  return String(value ?? '').trim()
}

function ResourceRow({ row, fields, kind, onEdit, onRemove }) {
  const title = row.name || row.id
  const summary = getSummary(row, fields)
  const chips = getChips(row, fields)
  const isItem = kind === 'items'
  const customerName = isItem ? normalizeCustomer(row.customer_id) : ''
  const rawStopSeq = Number(row.stop_seq)
  const stopSeq = isItem && row.stop_seq !== '' && row.stop_seq !== null && row.stop_seq !== undefined && Number.isFinite(rawStopSeq)
    ? Math.max(1, rawStopSeq)
    : null
  const accent = customerName ? customerAccent(customerName) : null

  const quantity = Number(row.quantity)
  const showQuantity = Number.isFinite(quantity) && quantity > 0

  return (
    <div
      className="resource-row"
      style={accent ? {
        '--resource-accent': accent.line,
        '--resource-customer-text': accent.text,
        '--resource-customer-border': accent.border,
        '--resource-customer-bg': accent.background,
      } : undefined}
    >
      <button type="button" onClick={onEdit} className="resource-row-main">
        <div className="resource-row-title">
          <strong>{title}</strong>
          {isItem && customerName && <span className="resource-customer-badge">客户 {customerName}</span>}
          {isItem && stopSeq !== null && <span className="resource-stop-badge">卸货 {stopSeq}</span>}
        </div>
        <div className="resource-summary">{summary || '-'}</div>
        {chips.length > 0 && (
          <Space size={6} wrap style={{ marginTop: 7 }}>
            {chips.map((chip) => {
              const node = <span className="resource-chip">{chip.text}</span>
              return chip.tooltip ? (
                <Tooltip key={chip.text} title={chip.tooltip}>{node}</Tooltip>
              ) : (
                <span key={chip.text}>{node}</span>
              )
            })}
          </Space>
        )}
      </button>
      <div className="resource-row-side">
        {showQuantity && <span className="resource-qty">×{quantity}</span>}
        <div className="resource-row-buttons">
          <Tooltip title="编辑">
            <Button size="small" type="text" icon={<EditOutlined />} onClick={onEdit} />
          </Tooltip>
          <Tooltip title="删除">
            <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={onRemove} />
          </Tooltip>
        </div>
      </div>
    </div>
  )
}

function FieldEditor({ field, row, value, onChange }) {
  const isWide = field.type === 'orientation_groups' || field.type === 'stacking_type_cards' || field.type === 'loading_accesses'
  return (
    <div className={isWide ? 'modal-field-wide' : ''} style={{ minWidth: 0 }}>
      <span className="field-label">{field.label}</span>
      {renderControl(field, row, value, onChange)}
    </div>
  )
}

function makePatch(field, value) {
  if (field.key === 'stacking_type' && isTopLoadLocked(value)) {
    return { [field.key]: value, max_load_top: 0 }
  }
  return { [field.key]: value }
}

function renderControl(field, row, value, onChange) {
  if (field.type === 'text') {
    return <Input value={value ?? ''} placeholder={field.placeholder} onChange={(e) => onChange(e.target.value)} />
  }
  if (field.type === 'bool') {
    return <Switch checked={!!value} onChange={onChange} />
  }
  if (field.type === 'select') {
    return (
      <Select
        value={value ?? field.defaultValue}
        options={field.options || []}
        onChange={onChange}
        style={{ width: '100%' }}
        optionRender={(option) => (
          <Tooltip title={option.data.description} placement="right">
            <span>{option.data.label}</span>
          </Tooltip>
        )}
      />
    )
  }
  if (field.type === 'stacking_type_cards') {
    return (
      <StackingTypeCards
        value={value ?? field.defaultValue}
        options={field.options || []}
        onChange={onChange}
      />
    )
  }
  if (field.type === 'orientation_groups') {
    return <OrientationCards row={row} value={value} onChange={onChange} />
  }
  if (field.type === 'loading_accesses') {
    return <LoadingAccessEditor field={field} row={row} value={value} onChange={onChange} />
  }
  const lockedTopLoad = field.key === 'max_load_top' && isTopLoadLocked(row?.stacking_type)
  return (
    <InputNumber
      style={{ width: '100%' }}
      value={lockedTopLoad ? 0 : value}
      min={field.min ?? 0}
      disabled={lockedTopLoad}
      placeholder={field.placeholder}
      onChange={onChange}
    />
  )
}

function isTopLoadLocked(stackingType) {
  return TOP_LOAD_LOCKED_STACKING_TYPES.has(stackingType)
}

function StackingTypeCards({ value, options, onChange }) {
  return (
    <div className="stacking-compact-grid">
      {options.map((option) => {
        const active = value === option.value
        return (
          <button
            key={option.value}
            type="button"
            className={`stacking-compact-card ${active ? 'is-active' : ''}`}
            aria-pressed={active}
            title={option.description}
            onClick={() => onChange(option.value)}
          >
            <StackingGlyph type={option.value} />
            <strong>{STACKING_SHORT_LABELS[option.value] ?? option.label}</strong>
          </button>
        )
      })}
    </div>
  )
}

function StackingGlyph({ type }) {
  const box = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinejoin: 'round' }
  const arrow = { stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', fill: 'currentColor' }
  return (
    <svg className="stacking-glyph" viewBox="0 0 26 26" aria-hidden="true">
      {type === 'not_stackable' && (
        <>
          <rect x="6.5" y="13.5" width="13" height="8" rx="1.5" {...box} />
          <g stroke="#ef4444" strokeWidth="2.1" strokeLinecap="round">
            <line x1="10.6" y1="4.6" x2="15.4" y2="9.4" />
            <line x1="15.4" y1="4.6" x2="10.6" y2="9.4" />
          </g>
        </>
      )}
      {type === 'same_item_only' && (
        <>
          <rect x="6.5" y="4.5" width="13" height="6.5" rx="1.3" {...box} />
          <rect x="6.5" y="15" width="13" height="6.5" rx="1.3" {...box} />
          <line x1="10" y1="7.75" x2="16" y2="7.75" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          <line x1="10" y1="18.25" x2="16" y2="18.25" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </>
      )}
      {type === 'stackable' && (
        <>
          <rect x="6.5" y="9.5" width="13" height="7" rx="1.3" {...box} />
          <g {...arrow}>
            <line x1="13" y1="6.5" x2="13" y2="3.5" fill="none" />
            <path d="M13 1.6 L10.8 4.8 L15.2 4.8 Z" stroke="none" />
            <line x1="13" y1="19.5" x2="13" y2="22.5" fill="none" />
            <path d="M13 24.4 L10.8 21.2 L15.2 21.2 Z" stroke="none" />
          </g>
        </>
      )}
      {type === 'support_only' && (
        <>
          <rect x="6.5" y="14" width="13" height="7.5" rx="1.4" {...box} />
          <g {...arrow}>
            <line x1="13" y1="11" x2="13" y2="5" fill="none" />
            <path d="M13 2.9 L10.6 6.4 L15.4 6.4 Z" stroke="none" />
          </g>
        </>
      )}
      {type === 'top_only' && (
        <>
          <rect x="6.5" y="4.5" width="13" height="7.5" rx="1.4" {...box} />
          <g {...arrow}>
            <line x1="13" y1="15" x2="13" y2="21" fill="none" />
            <path d="M13 23.1 L10.6 19.6 L15.4 19.6 Z" stroke="none" />
          </g>
        </>
      )}
    </svg>
  )
}

function OrientationCards({ row, value, onChange }) {
  const rotations = normalizeRotations(value)
  const active = new Set(rotations)

  const toggleGroup = (group, checked) => {
    if (group.fixed) return
    const next = new Set(rotations)
    for (const rotation of group.rotations) {
      if (checked) next.add(rotation)
      else next.delete(rotation)
    }
    for (const rotation of ORIENTATION_GROUPS[0].rotations) next.add(rotation)
    onChange(ORIENTATION_ORDER.filter((rotation) => next.has(rotation)))
  }

  return (
    <div className="orientation-compact-grid">
      {ORIENTATION_GROUPS.map((group) => {
        const checked = group.rotations.every((rotation) => active.has(rotation))
        return (
          <div
            key={group.key}
            role="button"
            tabIndex={0}
            className={`orientation-compact-card ${checked ? 'is-active' : ''}`}
            title={group.description}
            onClick={() => toggleGroup(group, !checked)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') toggleGroup(group, !checked)
            }}
          >
            <div className="orientation-compact-head">
              <Checkbox
                checked={checked}
                disabled={group.fixed}
                onClick={(event) => event.stopPropagation()}
                onChange={(event) => toggleGroup(group, event.target.checked)}
              >
                {group.label}
              </Checkbox>
            </div>
            <div className="orientation-compact-figure">
              <OrientationFigure group={group} row={row} active={checked} />
            </div>
            <div className="orientation-compact-caption">底面 {group.base.replace(/\s/g, '')} · 竖直 {group.vertical}</div>
          </div>
        )
      })}
    </div>
  )
}

function ItemModalTitle({ title, subtitle }) {
  return (
    <div className="item-modal-title">
      <span className="item-modal-title-icon">
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
          <path d="M12 3 L20 7.2 L20 16.8 L12 21 L4 16.8 L4 7.2 Z" />
          <path d="M4 7.2 L12 11.4 L20 7.2" />
          <path d="M12 11.4 L12 21" />
        </svg>
      </span>
      <span className="item-modal-title-text">
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </span>
    </div>
  )
}

function dimensionSummary(row) {
  const dims = ['length', 'width', 'height'].map((key) => Number(row?.[key]))
  if (dims.some((dim) => !Number.isFinite(dim) || dim <= 0)) return '尺寸待完善'
  return `尺寸 ${dims[0]} × ${dims[1]} × ${dims[2]} cm`
}

function ContainerModalTitle({ title, subtitle }) {
  return (
    <div className="item-modal-title">
      <span className="item-modal-title-icon">
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
          <rect x="3.5" y="5" width="17" height="14" rx="1.6" />
          <path d="M3.5 9.7 L20.5 9.7" />
          <path d="M9.2 9.7 L9.2 19" />
          <path d="M14.8 9.7 L14.8 19" />
        </svg>
      </span>
      <span className="item-modal-title-text">
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </span>
    </div>
  )
}

function sheetSummary(kind, row) {
  if (kind === 'containers') return containerSummary(row)
  return dimensionSummary(row)
}

function containerSummary(row) {
  const dims = ['inner_length', 'inner_width', 'inner_height'].map((key) => Number(row?.[key]))
  const dimText = dims.some((dim) => !Number.isFinite(dim) || dim <= 0)
    ? '内尺寸待完善'
    : `内尺寸 ${dims[0]} × ${dims[1]} × ${dims[2]} cm`
  const payload = Number(row?.max_payload)
  if (!Number.isFinite(payload) || payload <= 0) return dimText
  const tons = payload / 1000
  const tonText = Number.isInteger(tons) ? tons : Number(tons.toFixed(1))
  return `${dimText} · 载重 ${tonText} t`
}

function ContainerField({ field, row, onChange, span }) {
  if (!field) return null
  const placeholder = CONTAINER_FIELD_PLACEHOLDERS[field.key]
  const merged = placeholder ? { ...field, placeholder } : field
  const label = CONTAINER_FIELD_LABELS[field.key] ?? field.label
  return (
    <div className={`item-field${span ? ' container-field-span' : ''}`} style={{ minWidth: 0 }}>
      <span className="field-label">{label}</span>
      {renderControl(merged, row, row[field.key], (value) => onChange(field, value))}
    </div>
  )
}

function ContainerModalForm({ fields, row, onChange }) {
  const [moreOpen, setMoreOpen] = useState(false)
  const byKey = Object.fromEntries(fields.map((field) => [field.key, field]))
  const accessField = byKey.loading_accesses
  const accesses = normalizeAccesses(row.loading_accesses, row, accessField?.defaultValue)
  const enabledCount = accesses.length
  const totalCount = (accessField?.options || []).length

  return (
    <div className="item-form">
      <section className="item-form-section">
        <div className="item-section-head">
          <span className="item-section-title">基本信息</span>
        </div>
        <div className="item-form-row container-row-name">
          <ContainerField field={byKey.name} row={row} onChange={onChange} />
          <ContainerField field={byKey.quantity} row={row} onChange={onChange} />
        </div>
        <div className="item-form-row container-row-dims">
          <ContainerField field={byKey.inner_length} row={row} onChange={onChange} />
          <ContainerField field={byKey.inner_width} row={row} onChange={onChange} />
          <ContainerField field={byKey.inner_height} row={row} onChange={onChange} />
        </div>
        <div className="item-form-row container-row-payload">
          <ContainerField field={byKey.max_payload} row={row} onChange={onChange} />
          <ContainerField field={byKey.equipment_profile} row={row} onChange={onChange} />
        </div>
      </section>

      {accessField && (
        <section className="item-form-section">
          <div className="item-section-head">
            <span className="item-section-title">装货入口</span>
            <span className="item-section-hint">已启用 {enabledCount} / {totalCount} 个入口</span>
          </div>
          <LoadingAccessEditor
            field={accessField}
            row={row}
            value={row.loading_accesses}
            onChange={(value) => onChange(accessField, value)}
            compact
          />
        </section>
      )}

      <section className="item-form-section item-more-section">
        <button
          type="button"
          className="item-more-toggle"
          aria-expanded={moreOpen}
          onClick={() => setMoreOpen((open) => !open)}
        >
          <span className="item-section-title">更多参数</span>
          <span className="item-section-hint">成本 · 固定能力 · 重心限制 · 加速度 · 开口范围（选填）</span>
          <RightOutlined className={`item-more-chevron ${moreOpen ? 'is-open' : ''}`} />
        </button>
        {moreOpen && (
          <div className="container-more">
            <div className="container-subsection">
              <span className="container-sub-title">成本与地板</span>
              <div className="container-sub-grid">
                <ContainerField field={byKey.use_cost} row={row} onChange={onChange} />
                <ContainerField field={byKey.max_floor_load_kg_m2} row={row} onChange={onChange} />
                <ContainerField field={byKey.default_friction_coefficient} row={row} onChange={onChange} />
              </div>
            </div>
            <div className="container-subsection">
              <span className="container-sub-title">固定与稳定</span>
              <div className="container-sub-grid">
                <ContainerField field={byKey.restraint_mode} row={row} onChange={onChange} />
                <ContainerField field={byKey.longitudinal_restraint_capacity_kn} row={row} onChange={onChange} />
                <ContainerField field={byKey.transverse_restraint_capacity_kn} row={row} onChange={onChange} />
              </div>
            </div>
            <div className="container-subsection">
              <span className="container-sub-title">重心允许范围 (0–1)</span>
              <div className="container-sub-grid">
                <ContainerField field={byKey.cog_x_min_ratio} row={row} onChange={onChange} />
                <ContainerField field={byKey.cog_y_min_ratio} row={row} onChange={onChange} />
                <ContainerField field={byKey.cog_z_max_ratio} row={row} onChange={onChange} />
                <ContainerField field={byKey.cog_x_max_ratio} row={row} onChange={onChange} />
                <ContainerField field={byKey.cog_y_max_ratio} row={row} onChange={onChange} />
              </div>
            </div>
            <div className="container-subsection">
              <span className="container-sub-title">加速度 (G) 与载荷曲线</span>
              <div className="container-sub-grid">
                <ContainerField field={byKey.longitudinal_g} row={row} onChange={onChange} />
                <ContainerField field={byKey.transverse_g} row={row} onChange={onChange} />
                <ContainerField field={byKey.vertical_g} row={row} onChange={onChange} />
                <ContainerField field={byKey.load_distribution_curve_json} row={row} onChange={onChange} span />
              </div>
            </div>
            {accessField && (
              <div className="container-subsection">
                <span className="container-sub-title">各门开口范围 (CM)</span>
                <OpeningRangeTable field={accessField} row={row} />
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

// 开口范围只读展示：与旧版卡片内锁定字段同源（accessDefaultValues），仅换成分组表格布局。
function OpeningRangeTable({ field, row }) {
  const options = field.options || []
  const accesses = normalizeAccesses(row.loading_accesses, row, field.defaultValue)
  return (
    <div className="opening-range-table">
      {accesses.map((access) => {
        const label = options.find((option) => option.value === access.side)?.label || access.side
        const defaults = accessDefaultValues(row, access.side)
        return (
          <div className="opening-range-row" key={access.side}>
            <span className="opening-range-label"><i />{label}</span>
            <InputNumber size="small" disabled value={defaults.door_width} />
            <InputNumber size="small" disabled value={defaults.door_height} />
            <InputNumber size="small" disabled value={defaults.opening_start} />
            <InputNumber size="small" disabled value={defaults.opening_end} />
          </div>
        )
      })}
    </div>
  )
}

function ItemField({ field, row, onChange }) {
  if (!field) return null
  const placeholder = ITEM_FIELD_PLACEHOLDERS[field.key]
  const merged = placeholder ? { ...field, placeholder } : field
  return (
    <div className="item-field" style={{ minWidth: 0 }}>
      <span className="field-label">{field.label}</span>
      {renderControl(merged, row, row[field.key], (value) => onChange(field, value))}
    </div>
  )
}

function ItemModalForm({ fields, row, onChange }) {
  const [moreOpen, setMoreOpen] = useState(false)
  const byKey = Object.fromEntries(fields.map((field) => [field.key, field]))
  const stackingField = byKey.stacking_type
  const orientationField = byKey.allowed_rotations
  const mustLoadField = byKey.must_load
  const stackingValue = row.stacking_type ?? stackingField?.defaultValue
  const selectedStacking = (stackingField?.options || []).find((option) => option.value === stackingValue)
  const rotations = normalizeRotations(row.allowed_rotations)
  const allAllowed = rotations.length === ORIENTATION_ORDER.length
  const defaultOnly = !allAllowed && rotations.length === ORIENTATION_GROUPS[0].rotations.length

  return (
    <div className="item-form">
      <section className="item-form-section">
        <div className="item-section-head">
          <span className="item-section-title">基本信息</span>
        </div>
        <div className="item-form-row item-form-row-name">
          <ItemField field={byKey.name} row={row} onChange={onChange} />
          <ItemField field={byKey.quantity} row={row} onChange={onChange} />
          <ItemField field={byKey.weight} row={row} onChange={onChange} />
        </div>
        <div className="item-form-row item-form-row-dims">
          <ItemField field={byKey.length} row={row} onChange={onChange} />
          <ItemField field={byKey.width} row={row} onChange={onChange} />
          <ItemField field={byKey.height} row={row} onChange={onChange} />
        </div>
      </section>

      {stackingField && (
        <section className="item-form-section">
          <div className="item-section-head">
            <span className="item-section-title">堆叠类型</span>
            {selectedStacking?.description && (
              <span className="item-section-hint">{selectedStacking.description}</span>
            )}
          </div>
          <StackingTypeCards
            value={stackingValue}
            options={stackingField.options || []}
            onChange={(value) => onChange(stackingField, value)}
          />
        </section>
      )}

      {orientationField && (
        <section className="item-form-section">
          <div className="item-section-head">
            <span className="item-section-title">允许摆放姿态</span>
            <div className="item-segment">
              <button
                type="button"
                className={allAllowed ? 'is-active' : ''}
                onClick={() => onChange(orientationField, ORIENTATION_ORDER)}
              >
                全部允许
              </button>
              <button
                type="button"
                className={defaultOnly ? 'is-active' : ''}
                onClick={() => onChange(orientationField, ORIENTATION_GROUPS[0].rotations)}
              >
                仅默认姿态
              </button>
            </div>
          </div>
          <OrientationCards
            row={row}
            value={row.allowed_rotations}
            onChange={(value) => onChange(orientationField, value)}
          />
        </section>
      )}

      <section className="item-form-section item-more-section">
        <button
          type="button"
          className="item-more-toggle"
          aria-expanded={moreOpen}
          onClick={() => setMoreOpen((open) => !open)}
        >
          <span className="item-section-title">更多参数</span>
          <span className="item-section-hint">承重 · 客户 · 订单 · 优先级等（选填）</span>
          <RightOutlined className={`item-more-chevron ${moreOpen ? 'is-open' : ''}`} />
        </button>
        {moreOpen && (
          <div className="item-more-grid">
            {ITEM_MORE_FIELD_KEYS.map((key) => (
              <ItemField key={key} field={byKey[key]} row={row} onChange={onChange} />
            ))}
            {mustLoadField && (
              <div className="item-field" style={{ minWidth: 0 }}>
                <span className="field-label">{mustLoadField.label}</span>
                <div className="item-must-load">
                  <Switch
                    size="small"
                    checked={!!row.must_load}
                    onChange={(value) => onChange(mustLoadField, value)}
                  />
                  <span>{row.must_load ? '必装' : '非必装'}</span>
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

function OrientationFigure({ group, row, active }) {
  const [baseXValue, baseYValue, verticalValue] = group.dimKeys.map((key) => getPositiveDimension(row, key))
  const maxDimension = Math.max(
    getPositiveDimension(row, 'length'),
    getPositiveDimension(row, 'width'),
    getPositiveDimension(row, 'height'),
    1,
  )
  const scale = 62 / maxDimension
  const baseX = Math.max(18, baseXValue * scale)
  const depth = Math.max(14, baseYValue * scale * 0.62)
  const vertical = Math.max(18, verticalValue * scale)
  const ox = 42
  const oy = 94
  const sx = depth * 0.82
  const sy = -depth * 0.45

  const a = [ox, oy]
  const b = [ox + baseX, oy]
  const c = [ox + baseX + sx, oy + sy]
  const d = [ox + sx, oy + sy]
  const at = [a[0], a[1] - vertical]
  const bt = [b[0], b[1] - vertical]
  const ct = [c[0], c[1] - vertical]
  const dt = [d[0], d[1] - vertical]

  const points = (...items) => items.map((point) => point.join(',')).join(' ')
  const front = points(a, b, bt, at)
  const side = points(b, c, ct, bt)
  const top = points(at, bt, ct, dt)
  const guideX = Math.min(172, c[0] + 16)
  const guideTop = Math.min(at[1], bt[1], ct[1], dt[1])

  return (
    <svg viewBox="0 0 190 126" role="img" aria-label={group.description}>
      <polygon points={front} fill={active ? '#bfdbfe' : '#e4e9f1'} stroke="#8da2c0" />
      <polygon points={side} fill={active ? '#93c5fd' : '#d5dce7'} stroke="#8da2c0" />
      <polygon points={top} fill={active ? '#dbeafe' : '#eef2f7'} stroke="#8da2c0" />
      <line x1={guideX} y1={oy} x2={guideX} y2={guideTop} stroke={active ? '#176bff' : '#98a2b3'} strokeWidth="3" />
      <path d={`M${guideX} ${guideTop - 8} L${guideX - 7} ${guideTop + 5} L${guideX + 7} ${guideTop + 5} Z`} fill={active ? '#176bff' : '#98a2b3'} />
      <text x={ox + baseX / 2 + sx * 0.5} y="118" textAnchor="middle">{group.base}</text>
      <text x={Math.max(126, guideX - 18)} y={Math.max(16, guideTop + 10)} textAnchor="middle">{group.vertical}</text>
    </svg>
  )
}

function LoadingAccessEditor({ field, row, value, onChange, compact = false }) {
  const options = field.options || []
  const accesses = normalizeAccesses(value, row, field.defaultValue)
  const bySide = new Map(accesses.map((access) => [access.side, access]))

  const commit = (next) => {
    const clean = next.length > 0 ? next : [blankAccess('x_max')]
    onChange(clean)
  }

  const toggleAccess = (side, checked) => {
    if (checked) {
      if (bySide.has(side)) return
      commit([...accesses, blankAccess(side)])
      return
    }
    commit(accesses.filter((access) => access.side !== side))
  }

  return (
    <div className={`access-editor ${compact ? 'is-compact' : ''}`}>
      <div className="access-editor-note">
        <LockOutlined />
        <span>当前按整侧开口计算；门宽、门高和开口范围为高级设置</span>
      </div>
      <div className="access-grid">
        {options.map((option) => {
          const access = bySide.get(option.value)
          const active = !!access
          return (
            <div
              key={option.value}
              role="button"
              tabIndex={0}
              className={`access-card ${active ? 'is-active' : ''}`}
              onClick={() => toggleAccess(option.value, !active)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') toggleAccess(option.value, !active)
              }}
            >
              <div className="access-card-head">
                <Checkbox
                  checked={active}
                  onClick={(event) => event.stopPropagation()}
                  onChange={(event) => toggleAccess(option.value, event.target.checked)}
                >
                  {option.label}
                </Checkbox>
              </div>
              <div className="access-figure-button">
                <AccessFigure side={option.value} active={active} />
              </div>
              <p>{option.description}</p>
              {!compact && <AccessLockedFields row={row} side={option.value} hidden={!active} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function AccessLockedFields({ row, side, hidden = false }) {
  const defaults = accessDefaultValues(row, side)
  return (
    <div
      className={`access-locked ${hidden ? 'is-hidden' : ''}`}
      aria-hidden={hidden}
      onClick={(event) => event.stopPropagation()}
    >
      <div className="access-fields">
        <label>
          <span>门宽</span>
          <InputNumber size="small" disabled value={defaults.door_width} />
        </label>
        <label>
          <span>门高</span>
          <InputNumber size="small" disabled value={defaults.door_height} />
        </label>
        <label>
          <span>开口起点</span>
          <InputNumber size="small" disabled value={defaults.opening_start} />
        </label>
        <label>
          <span>开口终点</span>
          <InputNumber size="small" disabled value={defaults.opening_end} />
        </label>
      </div>
    </div>
  )
}

function AccessFigure({ side, active }) {
  const stroke = active ? '#176bff' : '#8da2c0'
  const base = active ? '#dbeafe' : '#eef2f7'
  const sideFill = active ? '#bfdbfe' : '#e4e9f1'
  const topFill = active ? '#eff6ff' : '#f8fafc'
  const door = active ? '#22c55e' : '#98a2b3'
  const arrow = active ? '#176bff' : '#98a2b3'
  const doorMarks = {
    x_min: <line x1="42" y1="55" x2="42" y2="94" stroke={door} strokeWidth="6" strokeLinecap="round" />,
    x_max: <polygon points="128,56 151,43 151,77 128,91" fill="rgba(34,197,94,0.20)" stroke={door} strokeWidth="3" />,
    y_min: <rect x="55" y="62" width="58" height="28" rx="3" fill="rgba(34,197,94,0.18)" stroke={door} strokeWidth="3" />,
    y_max: <line x1="74" y1="36" x2="150" y2="36" stroke={door} strokeWidth="6" strokeLinecap="round" />,
    z_max: <polygon points="42,54 70,36 154,36 126,54" fill="rgba(34,197,94,0.20)" stroke={door} strokeWidth="3" />,
  }
  const arrows = {
    x_min: <AccessArrow points="23,76 43,76" tip="43,76 35,70 35,82" color={arrow} />,
    x_max: <AccessArrow points="169,64 149,64" tip="149,64 157,58 157,70" color={arrow} />,
    y_min: <AccessArrow points="84,112 84,91" tip="84,91 78,99 90,99" color={arrow} />,
    y_max: <AccessArrow points="112,16 112,37" tip="112,37 106,29 118,29" color={arrow} />,
    z_max: <AccessArrow points="98,11 98,38" tip="98,38 91,28 105,28" color={arrow} />,
  }
  return (
    <svg viewBox="0 0 190 126" role="img" aria-hidden="true">
      <polygon points="42,54 126,54 126,96 42,96" fill={base} stroke={stroke} />
      <polygon points="126,54 154,36 154,78 126,96" fill={sideFill} stroke={stroke} />
      <polygon points="42,54 70,36 154,36 126,54" fill={topFill} stroke={stroke} />
      <line x1="70" y1="36" x2="70" y2="78" stroke="#cbd5e1" />
      <line x1="70" y1="78" x2="42" y2="96" stroke="#cbd5e1" />
      {doorMarks[side]}
      {arrows[side]}
    </svg>
  )
}

function AccessArrow({ points, tip, color }) {
  const [x1, y1, x2, y2] = points.split(/[ ,]+/).map(Number)
  return (
    <g stroke={color} fill={color} strokeWidth="3" strokeLinecap="round">
      <line x1={x1} y1={y1} x2={x2} y2={y2} />
      <path d={`M${tip.split(' ').join(' L')} Z`} stroke="none" />
    </g>
  )
}

function blankAccess(side = 'x_max') {
  return { side, door_width: null, door_height: null, opening_start: null, opening_end: null }
}

function accessDefaultValues(row, side) {
  const length = getPositiveDimension(row, 'inner_length')
  const width = getPositiveDimension(row, 'inner_width')
  const height = getPositiveDimension(row, 'inner_height')
  if (side === 'y_min' || side === 'y_max') {
    return { door_width: length, door_height: height, opening_start: 0, opening_end: length }
  }
  if (side === 'z_max') {
    return { door_width: length, door_height: width, opening_start: 0, opening_end: length }
  }
  return { door_width: width, door_height: height, opening_start: 0, opening_end: width }
}

function normalizeAccesses(value, row, defaultValue) {
  if (Array.isArray(value) && value.length > 0) {
    return value.map((access) => ({ ...blankAccess(access.side || 'x_max'), ...access }))
  }
  if (row?.door_width != null || row?.door_height != null) {
    return [{ ...blankAccess('x_max'), door_width: row.door_width ?? null, door_height: row.door_height ?? null }]
  }
  if (Array.isArray(defaultValue) && defaultValue.length > 0) {
    return defaultValue.map((access) => ({ ...blankAccess(access.side || 'x_max'), ...access }))
  }
  return [blankAccess('x_max')]
}
function getPositiveDimension(row, key) {
  const value = Number(row?.[key])
  return Number.isFinite(value) && value > 0 ? value : 1
}

function normalizeRotations(value) {
  if (!Array.isArray(value) || value.length === 0) return ORIENTATION_ORDER
  const next = new Set(value)
  for (const rotation of ORIENTATION_GROUPS[0].rotations) next.add(rotation)
  return ORIENTATION_ORDER.filter((rotation) => next.has(rotation))
}

function getSummary(row, fields) {
  const length = row.length ?? row.inner_length
  const width = row.width ?? row.inner_width
  const height = row.height ?? row.inner_height
  if (length && width && height) return `${length} × ${width} × ${height} cm`
  if (length && width) return `${length} × ${width} cm`
  const nameField = fields.find((field) => field.key === 'name')
  return nameField ? row[nameField.key] : ''
}

function formatKgChip(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return `${value} kg`
  if (number >= 1000) return `${(number / 1000).toFixed(number % 1000 === 0 ? 0 : 1)} t`
  return `${number} kg`
}

// chip 只是把已有字段值换成更短的展示文案，数量单独放在卡片右上（×N）不再进 chips。
function chipText(key, field, value) {
  if (key === 'must_load') return { text: `必装 ${value ? '是' : '否'}` }
  if (key === 'priority') return { text: `优先级 ${value}` }
  if (key === 'weight') return { text: formatKgChip(value) }
  if (key === 'tare_weight') return Number(value) > 0 ? { text: `自重 ${formatKgChip(value)}` } : null
  if (key === 'max_payload') return { text: `载重 ${formatKgChip(value)}` }
  if (key === 'max_load') return { text: `限重 ${formatKgChip(value)}` }
  if (key === 'max_stack_height') return { text: `限高 ${value}` }
  if (key === 'deck_height') return { text: `台面 ${value}` }
  const option = field.options?.find((item) => item.value === value)
  return {
    text: `${option?.label ?? value}`,
    tooltip: option?.description,
  }
}

function getChips(row, fields) {
  const keys = ['must_load', 'priority', 'weight', 'tare_weight', 'stacking_type', 'allowed_rotations', 'equipment_profile', 'max_payload', 'loading_accesses', 'max_load', 'max_stack_height', 'deck_height']
  return keys
    .map((key) => {
      const field = fields.find((f) => f.key === key)
      const value = row[key]
      if (!field || value === undefined || value === null || value === '') return null
      if (field.type === 'loading_accesses') return accessChip(value, field, row)
      if (field.type === 'orientation_groups') return orientationChip(value)
      if (field.type === 'stacking_type_cards') return stackingChip(value, field)
      return chipText(key, field, value)
    })
    .filter(Boolean)
    .slice(0, 4)
}

function accessChip(value, field, row) {
  const accesses = normalizeAccesses(value, row, field.defaultValue)
  const options = field.options || []
  const labels = accesses.map((access) => (
    options.find((option) => option.value === access.side)?.label || access.side
  ))
  return {
    text: `入口 ${labels.join('+')}`,
    tooltip: accesses.map((access) => {
      const label = options.find((option) => option.value === access.side)?.label || access.side
      const defaults = accessDefaultValues(row, access.side)
      return `${label}: 默认整侧开口 ${defaults.door_width} x ${defaults.door_height}`
    }).join('\n'),
  }
}
function stackingChip(value, field) {
  const option = field.options?.find((item) => item.value === value)
  return { text: STACKING_SHORT_LABELS[value] ?? option?.label ?? value, tooltip: option?.description }
}

function orientationChip(value) {
  const rotations = normalizeRotations(value)
  const activeGroups = ORIENTATION_GROUPS.filter((group) =>
    group.rotations.every((rotation) => rotations.includes(rotation)),
  )
  const text = activeGroups.length === ORIENTATION_GROUPS.length
    ? '全部朝向'
    : activeGroups.length === 1
      ? '仅默认朝向'
      : `朝向 ${activeGroups.length} 类`
  return {
    text,
    tooltip: activeGroups.map((group) => `${group.label}: ${group.description}`).join('\n'),
  }
}
