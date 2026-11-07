/**
 * 手机悬浮环的动作落地。
 *
 * user:“动作落地（v1 范围）：question / note / exclamation：把 Sunday 拉到前台，并把动作和
 * 提示词前缀交给界面，界面把文字填进输入框（不自动发送）…chat：把 Sunday 拉到前台，打开当前
 * 会话…switch：把 Sunday 拉到前台，打开会话选择器”+(拉前台是原生侧做的；这里只负责
 * 「界面该变成什么样」，所以每次动作都落到一个具体的界面动作上，没有第二个业务实现)。
 *
 * 为什么是一个安装函数而不是组件逻辑：宿主只发事件，界面才知道输入框在哪。桌面端没有这些
 * 事件，调用点用 mobile 守卫，桌面上这个模块永远不会被安装。
 */
import { ref } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

/** 悬浮环状态：权限、服务是否活着、用户是否希望它开着。 */
export interface OverlayState {
  granted: boolean
  running: boolean
  wanted: boolean
}

/** 界面能为环动作做的事。 */
export interface OverlayActionHost {
  /** 把文字放进输入框，不发送。 */
  fillComposer(text: string): void
  /** 打开会话选择器。 */
  openSessions(): void
}

/** 未指定提示词时的默认前缀，与桌宠配置里的默认模板一致。 */
const DEFAULT_PROMPTS: Record<string, string> = {
  question: '？',
  exclamation: '！',
  note: '记录',
}

/**
 * 共享状态：设置页要显示开关，环事件也会改它。
 *
 * 用模块级 ref 而不是 props，是因为事件来自宿主，设置页可能还没挂载。
 */
export const overlayStateRef = ref<OverlayState>({ granted: false, running: false, wanted: false })

/** 当前是否在小窗里，界面据此收窄布局。 */
export const pipActiveRef = ref(false)

/** 重新读一次宿主的真实状态。 */
export async function refreshOverlayState(): Promise<OverlayState> {
  try {
    const state = await invoke<OverlayState>('overlay_state')
    overlayStateRef.value = {
      granted: state?.granted === true,
      running: state?.running === true,
      wanted: state?.wanted === true,
    }
  } catch (error) {
    // 宿主还没准备好：保持上一次的状态，界面不会因此假装已经开启。
    console.warn('[sunday] overlay: cannot read the state', error)
  }
  return overlayStateRef.value
}

export async function openOverlayPermission(): Promise<void> {
  try {
    await invoke('overlay_open_settings')
  } catch (error) {
    console.warn('[sunday] overlay: cannot open the permission page', error)
  }
}

export async function startOverlay(): Promise<void> {
  try {
    await invoke('overlay_start')
  } catch (error) {
    console.warn('[sunday] overlay: cannot start the service', error)
  }
}

export async function stopOverlay(): Promise<void> {
  try {
    await invoke('overlay_stop')
  } catch (error) {
    console.warn('[sunday] overlay: cannot stop the service', error)
  }
}

/**
 * 进入系统小窗。返回 false 表示设备拒绝，此时原生侧已经把应用拉回前台并给出了提示。
 */
export async function enterSmallWindow(): Promise<boolean> {
  try {
    return (await invoke<boolean>('pip_enter')) === true
  } catch (error) {
    console.warn('[sunday] pip: cannot enter the small window', error)
    return false
  }
}

/** 一个环动作该让界面做什么。 */
export function applyOverlayAction(payload: unknown, host: OverlayActionHost): void {
  const record = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {}
  const action = typeof record.action === 'string' ? record.action : ''
  const text = typeof record.text === 'string' ? record.text : ''
  switch (action) {
    case 'question':
    case 'exclamation':
    case 'note':
      // user:“不自动发送”+(只填进输入框，用户自己按发送)。
      host.fillComposer(text || DEFAULT_PROMPTS[action] || '')
      break
    case 'chat':
      // 应用已经在当前会话上：拉前台那一步就够了。
      break
    case 'switch':
      host.openSessions()
      break
    default:
      // 未知动作不静默吞掉，日志里有据可查。
      console.warn('[sunday] overlay: unknown action', action)
      break
  }
}

/**
 * 安装宿主事件。
 *
 * 返回卸载函数：热更新与卸载都要摘掉监听，否则一次动作会执行多次。
 */
export async function installOverlayAction(host: OverlayActionHost): Promise<() => void> {
  const offs: Array<() => void> = []

  try {
    offs.push(
      await listen<unknown>('overlay-action', ({ payload }) => {
        applyOverlayAction(payload, host)
      }),
    )
  } catch (error) {
    console.warn('[sunday] overlay: cannot listen for actions', error)
  }

  try {
    offs.push(
      await listen<OverlayState>('overlay-state', ({ payload }) => {
        overlayStateRef.value = {
          granted: payload?.granted === true,
          running: payload?.running === true,
          wanted: payload?.wanted === true,
        }
      }),
    )
  } catch (error) {
    console.warn('[sunday] overlay: cannot listen for the state', error)
  }

  try {
    offs.push(
      await listen<{ active?: boolean }>('pip-mode', ({ payload }) => {
        pipActiveRef.value = payload?.active === true
      }),
    )
  } catch (error) {
    console.warn('[sunday] pip: cannot listen for the mode', error)
  }

  // user:“冷启动也要能拿到…如果拿不到就记录待处理，setup 后 emit”+(宿主改了做法：启动早期
  // emit 的事件没人听得到，所以它留在 Rust 侧，这里主动取一次，取到就当作刚发生)。
  try {
    const pending = await invoke<unknown>('overlay_take_pending')
    if (pending && typeof pending === 'object') applyOverlayAction(pending, host)
  } catch (error) {
    console.warn('[sunday] overlay: cannot take the pending action', error)
  }

  await refreshOverlayState()

  return () => {
    for (const off of offs.splice(0)) {
      try {
        off()
      } catch {
        // 已经失效的监听忽略。
      }
    }
  }
}
