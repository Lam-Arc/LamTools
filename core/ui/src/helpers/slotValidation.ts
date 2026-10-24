import type { MemberSlotSet, WorkspaceSlotName, SlotValidationResult } from '@/types.ts';
import { WORKSPACE_SLOT_NAMES } from '@/types.ts';

/** Validate a MemberSlotSet declaration.
 *  - Checks that all declared slots are valid WorkspaceSlotNames
 *  - Checks that fallbacks reference valid slot names
 *  - Warns about recommended slots that are missing */
export function validateMemberSlotSet(slotSet: MemberSlotSet): SlotValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const validNames = new Set<string>(WORKSPACE_SLOT_NAMES);

  // Check declared slots
  for (const slotName of slotSet.declaredSlots) {
    if (!validNames.has(slotName)) {
      errors.push(`Invalid slot name '${slotName}' in member '${slotSet.memberId}'. Valid names: ${WORKSPACE_SLOT_NAMES.join(', ')}`);
    }
  }

  // Check fallbacks
  if (slotSet.fallbacks) {
    for (const key of Object.keys(slotSet.fallbacks)) {
      if (!validNames.has(key)) {
        errors.push(`Invalid fallback slot name '${key}' in member '${slotSet.memberId}'`);
      }
    }
  }

  // Warn about missing recommended slots
  const recommended: WorkspaceSlotName[] = ['sidebar-body', 'main-content', 'composer-textarea'];
  const declared = new Set(slotSet.declaredSlots);
  for (const rec of recommended) {
    if (!declared.has(rec)) {
      warnings.push(`Recommended slot '${rec}' not declared in member '${slotSet.memberId}'`);
    }
  }

  return { valid: errors.length === 0, errors, warnings };
}

/** Get the fallback component name for a slot, or null if none. */
export function getSlotFallback(slotSet: MemberSlotSet, slotName: WorkspaceSlotName): string | null {
  return slotSet.fallbacks?.[slotName] ?? null;
}

/** Check if a member declares a specific slot. */
export function hasSlot(slotSet: MemberSlotSet, slotName: WorkspaceSlotName): boolean {
  return slotSet.declaredSlots.includes(slotName);
}
