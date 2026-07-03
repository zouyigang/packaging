import { Button, Checkbox, Empty, Input, InputNumber, Modal, Select, Space, Switch, Tooltip } from 'antd'
import { DeleteOutlined, EditOutlined, LockOutlined, PlusOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { useStore } from '../store/useStore'

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

export default function EditableTable({ kind, title, fields }) {
  const rows = useStore((s) => s[kind])
  const updateRow = useStore((s) => s.updateRow)
  const removeRow = useStore((s) => s.removeRow)
  const addRow = useStore((s) => s.addRow)
  const [editingId, setEditingId] = useState(null)

  const editingRow = rows.find((row) => row.id === editingId) || null

  return (
    <section className="resource-section">
      <div className="resource-section-head">
        <strong>{title}</strong>
        <span className="resource-count">{rows.length}</span>
        <div style={{ flex: 1 }} />
        <Button size="small" icon={<PlusOutlined />} onClick={() => addRow(kind)}>新增</Button>
      </div>

      {rows.length === 0 ? (
        <div className="resource-empty">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />
        </div>
      ) : (
        rows.map((row) => (
          <ResourceRow
            key={row.id}
            row={row}
            fields={fields}
            onEdit={() => setEditingId(row.id)}
            onRemove={() => removeRow(kind, row.id)}
          />
        ))
      )}

      <Modal
        title={editingRow ? `${title} · ${editingRow.id}` : title}
        open={!!editingRow}
        onCancel={() => setEditingId(null)}
        footer={null}
        width={900}
        destroyOnClose
      >
        {editingRow && (
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
        )}
      </Modal>
    </section>
  )
}

function ResourceRow({ row, fields, onEdit, onRemove }) {
  const title = row.name || row.id
  const summary = getSummary(row, fields)
  const chips = getChips(row, fields)

  return (
    <div className="resource-row">
      <button type="button" onClick={onEdit} className="resource-row-main">
        <div className="resource-row-title">
          <strong>{title}</strong>
          <span className="resource-id">{row.id}</span>
        </div>
        <div className="resource-summary">{summary || '-'}</div>
        {chips.length > 0 && (
          <Space size={6} wrap style={{ marginTop: 6 }}>
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
      <Tooltip title="编辑">
        <Button size="small" type="text" icon={<EditOutlined />} onClick={onEdit} />
      </Tooltip>
      <Tooltip title="删除">
        <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={onRemove} />
      </Tooltip>
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
    return <Input value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
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
      <StackingTypeEditor
        value={value ?? field.defaultValue}
        options={field.options || []}
        onChange={onChange}
      />
    )
  }
  if (field.type === 'orientation_groups') {
    return <OrientationEditor row={row} value={value} onChange={onChange} />
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
      onChange={onChange}
    />
  )
}

function isTopLoadLocked(stackingType) {
  return TOP_LOAD_LOCKED_STACKING_TYPES.has(stackingType)
}

function StackingTypeEditor({ value, options, onChange }) {
  return (
    <div className="stacking-grid">
      {options.map((option) => {
        const active = value === option.value
        return (
          <button
            key={option.value}
            type="button"
            className={`stacking-card ${active ? 'is-active' : ''}`}
            aria-pressed={active}
            onClick={() => onChange(option.value)}
          >
            <div className="stacking-card-head">
              <span className="stacking-radio" />
              <strong>{option.label}</strong>
            </div>
            <StackingFigure type={option.value} active={active} />
            <p>{option.description}</p>
          </button>
        )
      })}
    </div>
  )
}

function StackingFigure({ type, active }) {
  const primary = active ? '#176bff' : '#8da2c0'
  const primaryFill = active ? '#bfdbfe' : '#e4e9f1'
  const lowerFill = active ? '#d9e7ff' : '#eef2f7'
  const upperFill = active ? '#bbf7d0' : '#e5e7eb'
  const mutedStroke = active ? '#5b7fb7' : '#98a2b3'

  return (
    <svg className="stacking-figure" viewBox="0 0 160 120" role="img" aria-hidden="true">
      <line x1="20" y1="104" x2="140" y2="104" stroke="#cbd5e1" strokeWidth="2" />
      {type === 'not_stackable' && (
        <>
          <Block x={58} y={70} fill={primaryFill} stroke={primary} label="本品" />
          <StopMark x={80} y={38} />
          <StopMark x={80} y={98} />
        </>
      )}
      {type === 'same_item_only' && (
        <>
          <Block x={58} y={76} fill={primaryFill} stroke={primary} label="同" />
          <Block x={58} y={52} fill={primaryFill} stroke={primary} label="同" />
          <Block x={58} y={28} fill={primaryFill} stroke={primary} label="同" />
        </>
      )}
      {type === 'stackable' && (
        <>
          <Block x={58} y={76} fill={lowerFill} stroke={mutedStroke} label="下" />
          <Block x={58} y={52} fill={primaryFill} stroke={primary} label="本" />
          <Block x={58} y={28} fill={upperFill} stroke="#22c55e" label="上" />
        </>
      )}
      {type === 'support_only' && (
        <>
          <Block x={58} y={76} fill={primaryFill} stroke={primary} label="本" />
          <Block x={58} y={52} fill={upperFill} stroke="#22c55e" label="上" />
          <Arrow x={120} y1={84} y2={46} active={active} />
        </>
      )}
      {type === 'top_only' && (
        <>
          <Block x={58} y={76} fill={lowerFill} stroke={mutedStroke} label="下" />
          <Block x={58} y={52} fill={primaryFill} stroke={primary} label="本" />
          <StopMark x={80} y={30} />
        </>
      )}
    </svg>
  )
}

function Block({ x, y, fill, stroke, label }) {
  return (
    <g>
      <rect x={x} y={y} width="44" height="22" rx="3" fill={fill} stroke={stroke} />
      <text x={x + 22} y={y + 15} textAnchor="middle">{label}</text>
    </g>
  )
}

function StopMark({ x, y }) {
  return (
    <g stroke="#ef4444" strokeWidth="3" strokeLinecap="round">
      <line x1={x - 8} y1={y - 8} x2={x + 8} y2={y + 8} />
      <line x1={x + 8} y1={y - 8} x2={x - 8} y2={y + 8} />
    </g>
  )
}

function Arrow({ x, y1, y2, active }) {
  const color = active ? '#176bff' : '#98a2b3'
  return (
    <g stroke={color} fill={color} strokeWidth="3" strokeLinecap="round">
      <line x1={x} y1={y1} x2={x} y2={y2} />
      <path d={`M${x} ${y2 - 8} L${x - 7} ${y2 + 4} L${x + 7} ${y2 + 4} Z`} stroke="none" />
    </g>
  )
}

function OrientationEditor({ row, value, onChange }) {
  const rotations = normalizeRotations(value)
  const active = new Set(rotations)

  const setAll = () => onChange(ORIENTATION_ORDER)
  const setDefaultOnly = () => onChange(ORIENTATION_GROUPS[0].rotations)

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
    <div className="orientation-editor">
      <div className="orientation-actions">
        <Button size="small" onClick={setAll}>全部允许</Button>
        <Button size="small" onClick={setDefaultOnly}>仅默认姿态</Button>
      </div>
      <div className="orientation-grid">
        {ORIENTATION_GROUPS.map((group) => {
          const checked = group.rotations.every((rotation) => active.has(rotation))
          return (
            <div
              key={group.key}
              role="button"
              tabIndex={0}
              className={`orientation-option ${checked ? 'is-active' : ''}`}
              onClick={() => toggleGroup(group, !checked)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') toggleGroup(group, !checked)
              }}
            >
              <div className="orientation-option-head" onClick={(event) => event.stopPropagation()}>
                <Checkbox
                  checked={checked}
                  disabled={group.fixed}
                  onChange={(event) => toggleGroup(group, event.target.checked)}
                >
                  {group.label}
                </Checkbox>
              </div>
              <div className="orientation-figure-button">
                <OrientationFigure group={group} row={row} active={checked} />
              </div>
              <div className="orientation-meta">
                <span>底面：{group.base}</span>
                <span>竖直：{group.vertical}</span>
              </div>
              <p>{group.description}</p>
            </div>
          )
        })}
      </div>
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

function LoadingAccessEditor({ field, row, value, onChange }) {
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
    <div className="access-editor">
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
              <div className="access-card-head" onClick={(event) => event.stopPropagation()}>
                <Checkbox checked={active} onChange={(event) => toggleAccess(option.value, event.target.checked)}>
                  {option.label}
                </Checkbox>
              </div>
              <div className="access-figure-button">
                <AccessFigure side={option.value} active={active} />
              </div>
              <p>{option.description}</p>
              {active && <AccessLockedFields row={row} side={option.value} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function AccessLockedFields({ row, side }) {
  const defaults = accessDefaultValues(row, side)
  return (
    <div className="access-locked" onClick={(event) => event.stopPropagation()}>
      <div className="access-premium-note">
        <LockOutlined />
        <span>高级会员可自定义门宽、门高和开口范围；当前默认整侧开口</span>
      </div>
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
  if (length && width && height) return `${length} x ${width} x ${height} cm`
  if (length && width) return `${length} x ${width} cm`
  const nameField = fields.find((field) => field.key === 'name')
  return nameField ? row[nameField.key] : ''
}

function getChips(row, fields) {
  const keys = ['quantity', 'weight', 'tare_weight', 'stacking_type', 'allowed_rotations', 'max_payload', 'loading_accesses', 'max_load', 'max_stack_height', 'deck_height']
  return keys
    .map((key) => {
      const field = fields.find((f) => f.key === key)
      const value = row[key]
      if (!field || value === undefined || value === null || value === '') return null
      if (field.type === 'loading_accesses') return accessChip(value, field, row)
      if (field.type === 'orientation_groups') return orientationChip(value)
      if (field.type === 'stacking_type_cards') return stackingChip(value, field)
      const option = field.options?.find((item) => item.value === value)
      return {
        text: `${field.label}: ${option?.label ?? value}`,
        tooltip: option?.description,
      }
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
    text: `${field.label}: ${labels.join('+')}`,
    tooltip: accesses.map((access) => {
      const label = options.find((option) => option.value === access.side)?.label || access.side
      const defaults = accessDefaultValues(row, access.side)
      return `${label}: 默认整侧开口 ${defaults.door_width} x ${defaults.door_height}`
    }).join('\n'),
  }
}
function stackingChip(value, field) {
  const option = field.options?.find((item) => item.value === value)
  return { text: `${field.label}: ${option?.label ?? value}` }
}

function orientationChip(value) {
  const rotations = normalizeRotations(value)
  const activeGroups = ORIENTATION_GROUPS.filter((group) =>
    group.rotations.every((rotation) => rotations.includes(rotation)),
  )
  const text = activeGroups.length === ORIENTATION_GROUPS.length
    ? '姿态: 全部允许'
    : activeGroups.length === 1
      ? '姿态: 仅默认'
      : `姿态: ${activeGroups.length} 类`
  return {
    text,
    tooltip: activeGroups.map((group) => `${group.label}: ${group.description}`).join('\n'),
  }
}
