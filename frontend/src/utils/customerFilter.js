export const ALL_CUSTOMERS = '__all_customers__'
export const EMPTY_CUSTOMER = '__empty_customer__'
export const ALL_ITEMS = '__all_items__'

export function customerKey(value) {
  const normalized = String(value ?? '').trim()
  return normalized || EMPTY_CUSTOMER
}

export function customerLabel(key) {
  return key === EMPTY_CUSTOMER ? '未指定客户' : key
}

export function placementCustomer(placement, itemMap) {
  const item = itemMap[placement.item_id]
  const key = customerKey(placement.customer_id ?? item?.customer_id)
  const rawStopSeq = placement.stop_seq ?? item?.stop_seq ?? 1
  const stopSeq = Number.isFinite(Number(rawStopSeq)) ? Math.max(1, Number(rawStopSeq)) : 1
  return { key, label: customerLabel(key), stopSeq }
}

export function filterPlacementsByCustomer(placements, itemMap, customerFilter) {
  if (!customerFilter || customerFilter === ALL_CUSTOMERS) return placements
  return placements.filter((placement) => placementCustomer(placement, itemMap).key === customerFilter)
}

export function filterPlacementsByItem(placements, itemFilter) {
  if (!itemFilter || itemFilter === ALL_ITEMS) return placements
  return placements.filter((placement) => placement.item_id === itemFilter)
}

export function filterPlacements(placements, itemMap, customerFilter, itemFilter) {
  return filterPlacementsByItem(
    filterPlacementsByCustomer(placements, itemMap, customerFilter),
    itemFilter,
  )
}

export function customerFilterOptions(placements, itemMap) {
  const customers = new Map()

  for (const placement of placements || []) {
    const customer = placementCustomer(placement, itemMap)
    const current = customers.get(customer.key)
    if (current) {
      current.count += 1
      current.stopSeq = Math.min(current.stopSeq, customer.stopSeq)
    } else {
      customers.set(customer.key, {
        value: customer.key,
        label: customer.label,
        stopSeq: customer.stopSeq,
        count: 1,
      })
    }
  }

  return [
    { value: ALL_CUSTOMERS, label: '全部客户' },
    ...Array.from(customers.values()).sort((a, b) => {
      if (a.stopSeq !== b.stopSeq) return a.stopSeq - b.stopSeq
      return a.label.localeCompare(b.label, 'zh-Hans-CN')
    }),
  ]
}

export function itemFilterOptions(placements, itemMap, customerFilter) {
  const filtered = filterPlacementsByCustomer(placements || [], itemMap, customerFilter)
  const items = new Map()

  for (const placement of filtered) {
    const item = itemMap[placement.item_id]
    const value = placement.item_id
    const current = items.get(value)
    if (current) {
      current.count += 1
      current.stopSeq = Math.min(current.stopSeq, placementCustomer(placement, itemMap).stopSeq)
    } else {
      items.set(value, {
        value,
        label: item?.name || value,
        stopSeq: placementCustomer(placement, itemMap).stopSeq,
        count: 1,
      })
    }
  }

  return [
    { value: ALL_ITEMS, label: '全部货品' },
    ...Array.from(items.values()).sort((a, b) => {
      if (a.stopSeq !== b.stopSeq) return a.stopSeq - b.stopSeq
      return a.label.localeCompare(b.label, 'zh-Hans-CN')
    }),
  ]
}