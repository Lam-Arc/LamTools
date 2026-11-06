import type {
  LamToolsTransport,
  TransportHttpRequest,
  TransportHttpResponse,
} from '@/transport/index.ts'
import { createWorkbench } from '@/workbench/createWorkbench.ts'
import type { WorkbenchRuntime, WorkbenchRuntimeOptions } from '@/workbench/types.ts'
import type { CoreProjectClient } from '@/projects/client.ts'
import type { Ref } from 'vue'

export type LamToolsPlatform = 'desktop' | 'mobile' | 'web'

export type RuntimeFileSource = 'file' | 'photos' | 'camera'

export interface RuntimeFileCapabilities {
  // user:“若此附件真实存在于计算机则添加绝对路径”+(桌面选择器直接返回原件路径)。
  // user:“使用 Android SAF 桥接现有 Python Core 附件接口”+(安卓走同一条：宿主把 SAF
  // 选中的文件落到核心可读的目录并返回路径，由同一个 reference 接口登记，不新建一套附件业务)。
  pickPaths?(options?: {
    multiple?: boolean
    accept?: string
    source?: RuntimeFileSource
  }): Promise<string[] | null>
  // user:“没有原文件路径的环境才发字节”+(浏览器与网页版保留 DOM 选择器；安卓只提供路径，不虚报)。
  pick?(options?: {
    multiple?: boolean
    accept?: string
    source?: RuntimeFileSource
  }): Promise<File[] | null>
}

export interface RuntimeSessionExportCapabilities {
  saveFullArchive(sessionId: string, suggestedFilename: string): Promise<string | null>
}

/**
 * Which device is actually running the work.
 *
 * user:“清晰展示当前设备、连接状态和运行位置”+(手机连着电脑时，界面顶上要能看出来
 * 这一步是在电脑上执行的；本机模式就没有这个标记)。
 */
export interface RuntimeRemoteInfo {
  peer: string
}

export interface RuntimeCapabilities {
  filePicker: boolean
  notifications: boolean
  desktopWindow: boolean
  files?: RuntimeFileCapabilities
  sessionExports?: RuntimeSessionExportCapabilities
  localProjects?: Readonly<Ref<boolean>>
  remote?: RuntimeRemoteInfo
}

export interface RuntimeWorkspaceOption {
  id: string
  label: string
  online?: boolean
  platform?: string
  deviceName?: string
}

export interface RuntimeWorkspaceControl {
  activeId: Ref<string>
  options: Readonly<Ref<RuntimeWorkspaceOption[]>>
  select(id: string): Promise<void>
}

/**
 * Host-owned runtime passed to the one shared LamTools application.
 *
 * The application can use platform and capabilities for native affordances,
 * but all Core data and commands go through the injected Workbench/transport.
 */
export interface LamToolsRuntime {
  transport: LamToolsTransport
  workbench: WorkbenchRuntime
  platform: LamToolsPlatform
  capabilities: RuntimeCapabilities
  projectClient?: CoreProjectClient
  workspaceControl?: RuntimeWorkspaceControl
  request(request: TransportHttpRequest): Promise<TransportHttpResponse>
  requestJson<TResponse = unknown>(path: string, init?: RequestInit): Promise<TResponse>
  requestRpc(method: string, params?: Record<string, unknown>, timeoutMs?: number): Promise<Record<string, unknown>>
  close(): void
}

export interface CreateLamToolsRuntimeOptions extends Omit<WorkbenchRuntimeOptions, 'transport'> {
  transport: LamToolsTransport
  platform: LamToolsPlatform
  capabilities: RuntimeCapabilities
  projectClient?: CoreProjectClient
  workspaceControl?: RuntimeWorkspaceControl
}

export function createLamToolsRuntime(options: CreateLamToolsRuntimeOptions): LamToolsRuntime {
  const workbench = createWorkbench({
    ...options,
    transport: options.transport,
  })
  const capabilities: RuntimeCapabilities = {
    ...options.capabilities,
    files: options.capabilities.files
      || (options.capabilities.filePicker ? createDomFilePicker() : undefined),
  }
  return {
    transport: options.transport,
    workbench,
    platform: options.platform,
    capabilities,
    projectClient: options.projectClient,
    workspaceControl: options.workspaceControl,
    request: workbench.request,
    requestJson: workbench.requestJson,
    requestRpc: workbench.requestRpc,
    close: workbench.close,
  }
}

/**
 * Browser/Tauri fallback capability. The shared app only calls the capability;
 * it never owns an input element or a platform-specific picker lifecycle.
 */
export function createDomFilePicker(): RuntimeFileCapabilities {
  return {
    pick(options = {}) {
      if (typeof document === 'undefined') return Promise.resolve(null)
      return new Promise<File[] | null>((resolve) => {
        const input = document.createElement('input')
        input.type = 'file'
        input.multiple = options.source === 'camera' ? false : (options.multiple ?? true)
        input.accept = options.accept || (options.source === 'photos' || options.source === 'camera' ? 'image/*' : '')
        if (options.source === 'camera') input.setAttribute('capture', 'environment')
        input.style.display = 'none'
        let settled = false
        const cleanup = () => {
          input.removeEventListener('change', onChange)
          input.removeEventListener('cancel', onCancel)
          input.remove()
        }
        const finish = (files: File[] | null) => {
          if (settled) return
          settled = true
          cleanup()
          resolve(files)
        }
        const onChange = () => finish(input.files?.length ? Array.from(input.files) : null)
        const onCancel = () => finish(null)
        input.addEventListener('change', onChange, { once: true })
        input.addEventListener('cancel', onCancel, { once: true })
        document.body.appendChild(input)
        input.click()
      })
    },
  }
}
