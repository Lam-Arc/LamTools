import type { ProductAdapter, CoreSessionGroup } from '@lamtools/ui'

export const adapter: ProductAdapter = {
  id: 'sage',
  displayName: 'Sage',
  version: '0.1.0',
  supportedFeatures: ['chat'],
}

export function useSessionGroups() {
  return {
    sessionGroups: [
      { id: 'sage-sessions', label: 'Sage sessions', description: 'All Sage sessions' },
    ] as CoreSessionGroup[],
  }
}
