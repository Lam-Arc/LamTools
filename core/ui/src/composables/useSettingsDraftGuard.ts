import { computed, inject, onScopeDispose, provide, ref, shallowReactive, shallowRef, watch, type InjectionKey, type Ref } from 'vue'
import { t } from '../i18n'

// Compare data, not input events: editing back to the saved value is clean.
export function draftSnapshot(value: unknown): string {
  return JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b)))
    : item)
}

export interface SettingsDraft {
  section: string
  label: () => string
  dirty: Ref<boolean>
  busy?: Ref<boolean>
  error?: Ref<string>
  save: () => Promise<boolean | void>
  discard: () => void
}

export interface SettingsDraftSelection { section?: string; drafts?: SettingsDraft[] }
const draftGuardKey: InjectionKey<ReturnType<typeof createSettingsDraftGuard>> = Symbol('settings-draft-guard')

export function createSettingsDraftGuard() {
  const drafts = shallowReactive<SettingsDraft[]>([])
  const pendingAction = shallowRef<(() => void) | null>(null)
  const selected = shallowRef<SettingsDraft[]>([])
  const saving = ref(false)
  const error = ref('')
  const open = computed(() => pendingAction.value !== null)
  const busy = computed(() => saving.value || selected.value.some(draft => draft.busy?.value))
  const detail = computed(() => selected.value.filter(draft => draft.dirty.value).map(draft => draft.label()).join('、') || t('正在保存…'))

  function cancel() {
    if (saving.value) return
    pendingAction.value = null
    selected.value = []
    error.value = ''
  }

  function finish() {
    const action = pendingAction.value
    pendingAction.value = null
    selected.value = []
    error.value = ''
    action?.()
  }

  function requestNavigation(action: () => void, selection: SettingsDraftSelection = {}) {
    if (saving.value || open.value) return
    const candidates = selection.drafts ?? drafts.filter(draft => !selection.section || draft.section === selection.section)
    if (!candidates.some(draft => draft.dirty.value || draft.busy?.value)) {
      action()
      return
    }
    selected.value = [...candidates]
    error.value = ''
    pendingAction.value = action
  }

  async function saveAndContinue() {
    if (busy.value) return
    saving.value = true
    error.value = ''
    try {
      for (const draft of selected.value) {
        if (!draft.dirty.value) continue
        if (await draft.save() === false || draft.dirty.value) {
          error.value = draft.error?.value || t('未能保存，请检查修改后重试。')
          return
        }
      }
      saving.value = false
      finish()
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      saving.value = false
    }
  }

  function discardAndContinue() {
    if (busy.value) return
    for (const draft of selected.value) if (draft.dirty.value) draft.discard()
    finish()
  }

  // Navigation requested during an existing save needs no confirmation if
  // that save succeeds. A failed save still leaves the decision open.
  watch(() => selected.value.some(draft => draft.busy?.value), (isBusy, wasBusy) => {
    if (wasBusy && !isBusy && open.value && !saving.value && !selected.value.some(draft => draft.dirty.value)) finish()
  })

  const guard = { drafts, open, busy, detail, error, requestNavigation, saveAndContinue, discardAndContinue, cancel }
  provide(draftGuardKey, guard)
  return guard
}

export function useSettingsDraft<T>(options: {
  guard?: ReturnType<typeof createSettingsDraftGuard>
  section: string
  label: () => string
  read: () => T
  restore: (saved: T) => void
  save: () => Promise<boolean | void>
  busy?: Ref<boolean>
  error?: Ref<string>
}) {
  // Vue injection resolves ancestors, not a provider on the same component.
  const guard = options.guard ?? inject(draftGuardKey, null)
  const baseline = ref(draftSnapshot(options.read()))
  const dirty = computed(() => draftSnapshot(options.read()) !== baseline.value)
  const accept = (value: unknown = options.read()) => { baseline.value = draftSnapshot(value) }
  const discard = () => options.restore(JSON.parse(baseline.value))
  const draft: SettingsDraft = { ...options, dirty, discard }
  guard?.drafts.push(draft)
  onScopeDispose(() => {
    if (!guard) return
    const index = guard.drafts.indexOf(draft)
    if (index >= 0) guard.drafts.splice(index, 1)
  })
  function requestReplace(action: () => void, affected: SettingsDraft[] = [draft]) {
    if (guard) guard.requestNavigation(action, { drafts: affected })
    else if (!affected.some(item => item.dirty.value || item.busy?.value)) action()
  }
  return { dirty, accept, discard, requestReplace, draft }
}
