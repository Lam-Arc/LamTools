/**
 * Helpers barrel — re-exports all helper functions and types.
 */

export {
  createSessionMapper,
  createMessageMapper,
  type CoreSessionRawLike,
  type CoreMessageRawLike,
  type CreateSessionMapperOptions,
  type CreateMessageMapperOptions,
} from '@/helpers/coreApiMappers.ts';

export { createLoadingStepGroup } from '@/helpers/runtimeSteps.ts';

export {
  validateMemberSlotSet,
  getSlotFallback,
  hasSlot,
} from '@/helpers/slotValidation.ts';

export { createProductAdapter, createMemberSessionGroup } from '@/helpers/workbenchUtils.ts';

export { isExternalUrl, openExternalUrl } from '@/helpers/openUrl.ts';
