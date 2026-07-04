import { create } from 'zustand'
import { solve as solveApi } from '../api/solve'

let uid = 100
const nextId = (prefix) => `${prefix}${uid++}`
const allRotations = ['LWH', 'WLH', 'LHW', 'HLW', 'WHL', 'HWL']

const sampleItems = [
  { id: 'box-A', name: '大箱A', length: 600, width: 400, height: 400, weight: 20, quantity: 8, allowed_rotations: allRotations, stackable: true, stacking_type: 'stackable', max_load_top: null, category: 'A', customer_id: '', order_id: '', destination_id: '', stop_seq: 1 },
  { id: 'box-B', name: '小箱B', length: 400, width: 300, height: 300, weight: 8, quantity: 12, allowed_rotations: allRotations, stackable: true, stacking_type: 'stackable', max_load_top: null, category: 'B', customer_id: '', order_id: '', destination_id: '', stop_seq: 1 },
]
const samplePallets = [
  { id: 'plt', name: '标准托盘', length: 1200, width: 1000, tare_weight: 0, deck_height: 150, max_stack_height: 1500, max_load: 1000, quantity: 4 },
]
const sampleContainers = [
  { id: 'cntr', name: '20GP', inner_length: 5900, inner_width: 2350, inner_height: 2390, max_payload: 28000, loading_accesses: [{ side: 'x_max', door_width: null, door_height: null, opening_start: null, opening_end: null }], door_width: null, door_height: null, quantity: 2 },
]

export const useStore = create((set, get) => ({
  items: sampleItems,
  pallets: samplePallets,
  containers: sampleContainers,
  objective: 'transport_cost',
  useGa: false,

  solution: null,
  loading: false,
  error: null,

  activeContainer: 0,
  seqCursor: 0,
  customerFilter: '__all_customers__',
  itemFilter: '__all_items__',

  setObjective: (objective) => set({ objective }),
  setUseGa: (useGa) => set({ useGa }),
  setActiveContainer: (i) =>
    set((s) => ({
      activeContainer: i,
      seqCursor: s.solution?.containers?.[i]?.placements.length || 0,
      customerFilter: '__all_customers__',
  itemFilter: '__all_items__',
    })),
  setSeqCursor: (n) => set({ seqCursor: n }),
  setCustomerFilter: (customerFilter) => set({ customerFilter, itemFilter: '__all_items__' }),
  setItemFilter: (itemFilter) => set({ itemFilter }),

  updateRow: (kind, id, patch) =>
    set((s) => ({ [kind]: s[kind].map((r) => (r.id === id ? { ...r, ...patch } : r)) })),
  removeRow: (kind, id) => set((s) => ({ [kind]: s[kind].filter((r) => r.id !== id) })),
  createBlankRow: (kind) => blankRow(kind, false),
  addRow: (kind, row) =>
    set((s) => ({ [kind]: [...s[kind], row ? withRowId(kind, row) : blankRow(kind)] })),

  solve: async () => {
    const { items, pallets, containers, objective, useGa } = get()
    set({ loading: true, error: null })
    try {
      const solution = await solveApi({ items, pallets, containers, objective, use_ga: useGa })
      const maxSeq = solution.containers[0]?.placements.length || 0
      set({
        solution,
        loading: false,
        activeContainer: 0,
        seqCursor: maxSeq,
        customerFilter: '__all_customers__',
        itemFilter: '__all_items__',
      })
    } catch (e) {
      set({ error: e.message, loading: false })
    }
  },
}))

function withRowId(kind, row) {
  if (row.id) return row
  return { ...row, id: nextId(rowPrefix(kind)) }
}

function rowPrefix(kind) {
  if (kind === 'items') return 'item-'
  if (kind === 'pallets') return 'plt-'
  return 'cntr-'
}

function blankRow(kind, includeId = true) {
  if (kind === 'items')
    return { ...(includeId ? { id: nextId('item-') } : {}), name: '新货品', length: 300, width: 200, height: 200, weight: 1, quantity: 1, allowed_rotations: allRotations, stackable: true, stacking_type: 'stackable', max_load_top: null, category: '', customer_id: '', order_id: '', destination_id: '', stop_seq: 1 }
  if (kind === 'pallets')
    return { ...(includeId ? { id: nextId('plt-') } : {}), name: '新托盘', length: 1200, width: 1000, tare_weight: 0, deck_height: 150, max_stack_height: 1500, max_load: 1000, quantity: 1 }
  return { ...(includeId ? { id: nextId('cntr-') } : {}), name: '新容器', inner_length: 5900, inner_width: 2350, inner_height: 2390, max_payload: 28000, loading_accesses: [{ side: 'x_max', door_width: null, door_height: null, opening_start: null, opening_end: null }], door_width: null, door_height: null, quantity: 1 }
}
