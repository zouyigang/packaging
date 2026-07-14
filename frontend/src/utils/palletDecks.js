export function deriveVisiblePalletDecks(placements, palletInstances = [], palletMap = {}) {
  const groups = {}
  for (const placement of placements) {
    if (!placement.pallet_id) continue
    ;(groups[placement.pallet_id] ||= []).push(placement)
  }

  const instances = Object.fromEntries(palletInstances.map((instance) => [instance.id, instance]))
  return Object.entries(groups)
    .map(([id, palletPlacements]) => {
      const instance = instances[id]
      if (instance) {
        return {
          id,
          x: instance.x,
          y: instance.y,
          z: instance.z,
          L: instance.length,
          W: instance.width,
          H: instance.deck_height,
        }
      }

      // Compatibility fallback for solutions produced before pallet_instances existed.
      const definition = palletMap[id.split('#')[0]]
      if (!definition) return null
      const minItemZ = Math.min(...palletPlacements.map((placement) => placement.z))
      return {
        id,
        x: Math.min(...palletPlacements.map((placement) => placement.x)),
        y: Math.min(...palletPlacements.map((placement) => placement.y)),
        z: minItemZ - definition.deck_height,
        L: definition.length,
        W: definition.width,
        H: definition.deck_height,
      }
    })
    .filter(Boolean)
}
