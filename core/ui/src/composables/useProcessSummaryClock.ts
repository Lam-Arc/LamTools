import { onBeforeUnmount, shallowRef, watch, type ComputedRef, type Ref } from 'vue'

const processSummaryNow = shallowRef(Date.now())
const clockSubscribers = new Set<symbol>()
let processSummaryTimer: ReturnType<typeof setInterval> | null = null

/**
 * Share one low-frequency clock across visible process summaries. Historical
 * message rows never subscribe; the timer exists only while at least one
 * current running turn needs a live elapsed value.
 */
export function useProcessSummaryClock(enabled: ComputedRef<boolean>): Readonly<Ref<number>> {
  const subscriber = Symbol('process-summary-clock')

  function unsubscribe(): void {
    clockSubscribers.delete(subscriber)
    if (clockSubscribers.size || processSummaryTimer === null) return
    clearInterval(processSummaryTimer)
    processSummaryTimer = null
  }

  const stopWatch = watch(enabled, active => {
    if (!active) {
      unsubscribe()
      return
    }
    if (clockSubscribers.has(subscriber)) return
    clockSubscribers.add(subscriber)
    processSummaryNow.value = Date.now()
    if (processSummaryTimer === null) {
      processSummaryTimer = setInterval(() => {
        processSummaryNow.value = Date.now()
      }, 1000)
    }
  }, { immediate: true })

  onBeforeUnmount(() => {
    stopWatch()
    unsubscribe()
  })

  return processSummaryNow
}
