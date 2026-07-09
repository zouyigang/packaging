import { create } from 'zustand'
import { solve as solveApi } from '../api/solve'

let uid = 100
const nextId = (prefix) => `${prefix}${uid++}`
const allRotations = ['LWH', 'WLH', 'LHW', 'HLW', 'WHL', 'HWL']
const defaultBaseRotations = ['LWH', 'WLH']
const twoBaseRotations = ['LWH', 'WLH', 'LHW', 'HLW']
export const defaultAdvancedWeights = {
  space_utilization: 0.35,
  stability: 0.25,
  palletization: 0.15,
  balance: 0.15,
  loading_position: 0.10,
}

const sampleItems = [
  {
    id: 'box-A',
    name: '大箱A',
    length: 600,
    width: 400,
    height: 400,
    weight: 20,
    quantity: 40,
    allowed_rotations: defaultBaseRotations,
    stackable: false,
    stacking_type: 'not_stackable',
    max_load_top: 0,
    category: 'A',
    customer_id: '甲',
    order_id: '',
    destination_id: '',
    stop_seq: 1,
  },
  {
    id: 'box-B',
    name: '小箱B',
    length: 400,
    width: 300,
    height: 300,
    weight: 8,
    quantity: 300,
    allowed_rotations: allRotations,
    stackable: true,
    stacking_type: 'stackable',
    max_load_top: null,
    category: 'B',
    customer_id: '甲',
    order_id: '',
    destination_id: '',
    stop_seq: 1,
  },
  {
    id: 'box-C',
    name: '新货品',
    length: 500,
    width: 400,
    height: 230,
    weight: 10,
    quantity: 300,
    allowed_rotations: twoBaseRotations,
    stackable: true,
    stacking_type: 'stackable',
    max_load_top: null,
    category: 'C',
    customer_id: '乙',
    order_id: '',
    destination_id: '',
    stop_seq: 2,
  },
  {
    id: 'box-D',
    name: '新货品',
    length: 300,
    width: 200,
    height: 200,
    weight: 1,
    quantity: 500,
    allowed_rotations: allRotations,
    stackable: true,
    stacking_type: 'stackable',
    max_load_top: null,
    category: '',
    customer_id: '乙',
    order_id: '',
    destination_id: '',
    stop_seq: 2,
  },
]
const samplePallets = [
  { id: 'plt', name: '标准托盘', length: 1200, width: 1000, tare_weight: 10, deck_height: 150, max_stack_height: 1500, max_load: 1000, quantity: 4 },
]
const sampleContainers = [
  { id: 'cntr', name: '20GP', inner_length: 5900, inner_width: 2350, inner_height: 2390, max_payload: 28000, loading_accesses: [{ side: 'x_max', door_width: null, door_height: null, opening_start: null, opening_end: null }], door_width: null, door_height: null, quantity: 10 },
]

export const useStore = create((set, get) => ({
  items: sampleItems,
  pallets: samplePallets,
  containers: sampleContainers,
  objective: 'transport_cost',
  advancedWeights: defaultAdvancedWeights,
  useGa: false,
  gaSpeed: 'fast',

  solution: null,
  solutionCandidates: [],
  activeSolutionIndex: 0,
  loading: false,
  error: null,

  activeContainer: 0,
  seqCursor: 0,
  customerFilter: '__all_customers__',
  itemFilter: '__all_items__',

  setObjective: (objective) => set({ objective }),
  setAdvancedWeight: (key, value) =>
    set((s) => ({ advancedWeights: { ...s.advancedWeights, [key]: value } })),
  resetAdvancedWeights: () => set({ advancedWeights: defaultAdvancedWeights }),
  setUseGa: (useGa) => set({ useGa }),
  setGaSpeed: (gaSpeed) => set({ gaSpeed }),
  setActiveSolutionIndex: (index) =>
    set((s) => {
      const solution = s.solutionCandidates[index]
      return {
        solution,
        activeSolutionIndex: index,
        activeContainer: 0,
        seqCursor: solution?.containers?.[0]?.placements.length || 0,
        customerFilter: '__all_customers__',
        itemFilter: '__all_items__',
      }
    }),
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
    const { items, pallets, containers, objective, advancedWeights, useGa, gaSpeed } = get()
    const payload = {
      items: normalizeItemsForSolve(items),
      pallets,
      containers,
      objective,
      use_ga: useGa,
      ...(useGa ? { candidate_count: 3, ga_speed: gaSpeed } : {}),
      ...(isAdvancedObjective(objective) ? { advanced_weights: advancedWeights } : {}),
    }
    set({ loading: true, error: null })
    try {
      const response = await solveApi(payload)
      const solutionCandidates = buildSolutionCandidates(response)
      const solution = solutionCandidates[0] || response
      const maxSeq = solution.containers[0]?.placements.length || 0
      set({
        solution,
        solutionCandidates,
        activeSolutionIndex: 0,
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

function isAdvancedObjective(objective) {
  return objective === 'advanced_score' || objective === 'balanced'
}

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
    return { ...(includeId ? { id: nextId('item-') } : {}), name: '新货品', length: 300, width: 200, height: 200, weight: 1, quantity: 1, allowed_rotations: allRotations, stackable: true, stacking_type: 'stackable', max_load_top: null, category: '', customer_id: '', order_id: '', destination_id: '', stop_seq: '' }
  if (kind === 'pallets')
    return { ...(includeId ? { id: nextId('plt-') } : {}), name: '新托盘', length: 1200, width: 1000, tare_weight: 0, deck_height: 150, max_stack_height: 1500, max_load: 1000, quantity: 1 }
  return { ...(includeId ? { id: nextId('cntr-') } : {}), name: '新容器', inner_length: 5900, inner_width: 2350, inner_height: 2390, max_payload: 28000, loading_accesses: [{ side: 'x_max', door_width: null, door_height: null, opening_start: null, opening_end: null }], door_width: null, door_height: null, quantity: 1 }
}

function normalizeItemsForSolve(items) {
  return items.map((item) => {
    const stopSeq = Number(item.stop_seq)
    return {
      ...item,
      stop_seq: Number.isFinite(stopSeq) && stopSeq >= 1 ? stopSeq : 1,
    }
  })
}

function buildSolutionCandidates(solution) {
  if (!solution) return []
  const alternatives = solution.alternatives || []
  const primary = {
    ...solution,
    candidate_rank: 1,
    candidate_seed: alternatives[0]?.seed ?? null,
    alternatives: [],
  }
  return [
    primary,
    ...alternatives.map((alternative) => ({
      containers: alternative.containers || [],
      unpacked: alternative.unpacked || [],
      evaluation: alternative.evaluation || null,
      candidate_rank: alternative.rank,
      candidate_seed: alternative.seed,
      alternatives: [],
    })),
  ]
}
