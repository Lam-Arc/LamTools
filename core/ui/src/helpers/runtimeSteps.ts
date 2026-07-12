/**
 * Runtime step helpers — shared step-group factories used by all products.
 *
 * Products display this loading step-group while fetching session data.
 * This factory avoids duplicating that structure.
 */

import type { CoreRuntimeStepGroup } from '../types';

/**
 * Create the standard loading step-group shown while session data is being
 * fetched.  Returns a single-element array so it can be spread directly into
 * a `stepGroups` computed:
 *
 * ```ts
 * const stepGroups = computed(() => [
 *   ...createLoadingStepGroup(),
 *   // product-specific groups …
 * ])
 * ```
 */
export function createLoadingStepGroup(): CoreRuntimeStepGroup[] {
  return [
    {
      id: 'loading',
      label: 'Loading',
      status: 'running',
      steps: [
        {
          id: 'fetch-session-data',
          title: 'Fetching session data',
          status: 'running',
        },
      ],
    },
  ];
}
