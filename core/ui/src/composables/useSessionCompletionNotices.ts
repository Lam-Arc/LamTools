import { onScopeDispose, watch, type Ref } from 'vue'

import { t } from '@/i18n/index.ts'
import { showToast } from '@/composables/useCoreToast.ts'
import { isBusySessionStatus, selectFinishedSessionNotices } from '@/sessions/completion.ts'
import type { CoreSessionListItem } from '@/types.ts'

export interface UseSessionCompletionNoticesOptions {
  sessions: Ref<CoreSessionListItem[]>
  activeSessionId: Ref<string | null | undefined>
  /** Open a session from the notice (usually the app's normal session switch). */
  openSession: (id: string) => void | Promise<void>
  /** Re-read the server's session list. */
  refreshSessions: () => void | Promise<void>
  /** Cadence for the busy-session safety net. */
  busyPollIntervalMs?: number
}

/**
 * user:“做完了还是在这转啊”“也没有弹窗提示”“只有点进去才知道已经完成任务了”
 * +(会话列表的状态可能由工作台自己的刷新（session/updated）替换，所以统一在这里
 *   对比前后两份列表：后台会话从“进行中”变成“已完成/失败”时弹一条可点击的提示，
 *   点一下直接打开那个会话。只显示进行中时还会低频核对服务端，推送丢失时转圈也
 *   不会永远停不下来。)
 */
export function useSessionCompletionNotices(options: UseSessionCompletionNoticesOptions): void {
  const { sessions, activeSessionId, openSession, refreshSessions } = options
  const pollIntervalMs = options.busyPollIntervalMs ?? 4000

  let previous: readonly CoreSessionListItem[] = sessions.value
  watch(sessions, (next) => {
    const notices = selectFinishedSessionNotices(previous, next, {
      activeSessionId: activeSessionId.value,
    })
    previous = next
    for (const notice of notices) {
      const failed = notice.status === 'failed'
      showToast(
        failed ? 'error' : 'success',
        failed
          ? t('会话「{0}」执行失败，点击打开', { 0: notice.title })
          : t('会话「{0}」已完成，点击打开', { 0: notice.title }),
        8000,
        {
          label: t('打开会话'),
          run: () => { void Promise.resolve(openSession(notice.id)).catch(() => {}) },
        },
      )
    }
  }, { immediate: true })

  let timer: ReturnType<typeof setInterval> | null = null
  function syncPolling(): void {
    const busy = sessions.value.some((session) => isBusySessionStatus(session.status))
    if (busy && timer === null) {
      timer = setInterval(() => {
        void Promise.resolve(refreshSessions()).catch(() => {})
      }, pollIntervalMs)
    } else if (!busy && timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }
  watch(sessions, syncPolling, { immediate: true })
  onScopeDispose(() => {
    if (timer !== null) clearInterval(timer)
    timer = null
  })
}
