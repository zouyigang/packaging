import { create } from 'zustand'
import { solve as solveApi } from '../api/solve'

let uid = 100
const nextId = (prefix) => `${prefix}${uid++}`

// 一组示例数据，打开即可直接「求解」看到效果。
const sampleItems = [
  { id: 'box-A', name: '大箱A', length: 600, width: 400, height: 400, weight: 20, quantity: 8, stackable: true, max_load_top: null, category: 'A' },
  { id: 'box-B', name: '小箱B', length: 400, width: 300, height: 300, weight: 8, quantity: 12, stackable: true, max_load_top: null, category: 'B' },
]
const samplePallets = [
  { id: 'plt', name: '标准托盘', length: 1200, width: 1000, deck_height: 150, max_stack_height: 1500, max_load: 1000, quantity: 4 },
]
const sampleContainers = [
  { id: 'cntr', name: '20GP', inner_length: 5900, inner_width: 2350, inner_height: 2390, max_payload: 28000, door_width: null, door_height: null, quantity: 2 },
]

export const useStore = create((set, get) => ({
  items: sampleItems,
  pallets: samplePallets,
  containers: sampleContainers,
  objective: 'max_utilization',
  useGa: false,

  solution: null,
  loading: false,
  error: null,

  // 回放：当前显示到第几个 seq（按容器）
  activeContainer: 0,
  seqCursor: 0,

  setObjective: (objective) => set({ objective }),
  setUseGa: (useGa) => set({ useGa }),
  // 切换容器时默认显示该容器全部货物（游标设为满件数），否则会因游标=0 显示为空。
  setActiveContainer: (i) =>
    set((s) => ({ activeContainer: i, seqCursor: s.solution?.containers?.[i]?.placements.length || 0 })),
  setSeqCursor: (n) => set({ seqCursor: n }),

  // 通用增删改（kind: 'items' | 'pallets' | 'containers'）
  updateRow: (kind, id, patch) =>
    set((s) => ({ [kind]: s[kind].map((r) => (r.id === id ? { ...r, ...patch } : r)) })),
  removeRow: (kind, id) => set((s) => ({ [kind]: s[kind].filter((r) => r.id !== id) })),
  addRow: (kind) =>
    set((s) => ({ [kind]: [...s[kind], blankRow(kind)] })),

  solve: async () => {
    const { items, pallets, containers, objective, useGa } = get()
    set({ loading: true, error: null })
    try {
      const solution = await solveApi({ items, pallets, containers, objective, use_ga: useGa })
      const maxSeq = solution.containers[0]?.placements.length || 0
      set({ solution, loading: false, activeContainer: 0, seqCursor: maxSeq })
    } catch (e) {
      set({ error: e.message, loading: false })
    }
  },
}))

function blankRow(kind) {
  if (kind === 'items')
    return { id: nextId('item-'), name: '新货品', length: 300, width: 200, height: 200, weight: 1, quantity: 1, stackable: true, max_load_top: null, category: '' }
  if (kind === 'pallets')
    return { id: nextId('plt-'), name: '新托盘', length: 1200, width: 1000, deck_height: 150, max_stack_height: 1500, max_load: 1000, quantity: 1 }
  return { id: nextId('cntr-'), name: '新容器', inner_length: 5900, inner_width: 2350, inner_height: 2390, max_payload: 28000, door_width: null, door_height: null, quantity: 1 }
}
