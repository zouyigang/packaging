import { Table, InputNumber, Input, Switch, Button, Space } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useStore } from '../store/useStore'

// 通用可编辑表格：fields 描述列；id 只读（新增时自动生成），其余单元格就地编辑。
export default function EditableTable({ kind, title, fields }) {
  const rows = useStore((s) => s[kind])
  const updateRow = useStore((s) => s.updateRow)
  const removeRow = useStore((s) => s.removeRow)
  const addRow = useStore((s) => s.addRow)

  const columns = fields.map((f) => ({
    title: f.label,
    dataIndex: f.key,
    width: f.width,
    render: (value, row) => {
      if (f.type === 'text')
        return <Input size="small" value={value ?? ''} onChange={(e) => updateRow(kind, row.id, { [f.key]: e.target.value })} />
      if (f.type === 'bool')
        return <Switch size="small" checked={!!value} onChange={(v) => updateRow(kind, row.id, { [f.key]: v })} />
      // number（可空：max_load_top / door_* 允许 null 表示未指定）
      return (
        <InputNumber
          size="small"
          style={{ width: '100%' }}
          value={value}
          min={f.min ?? 0}
          onChange={(v) => updateRow(kind, row.id, { [f.key]: v })}
        />
      )
    },
  }))

  columns.unshift({ title: 'id', dataIndex: 'id', width: 90, fixed: 'left' })
  columns.push({
    title: '',
    width: 40,
    fixed: 'right',
    render: (_, row) => (
      <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => removeRow(kind, row.id)} />
    ),
  })

  return (
    <div style={{ marginBottom: 16 }}>
      <Space style={{ marginBottom: 8 }}>
        <strong>{title}</strong>
        <Button size="small" icon={<PlusOutlined />} onClick={() => addRow(kind)}>新增</Button>
      </Space>
      <Table
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 'max-content' }}
      />
    </div>
  )
}
