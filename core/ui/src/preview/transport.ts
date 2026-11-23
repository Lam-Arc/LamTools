/**
 * 把预览解析层需要的外部能力接到真实的传输通道上。
 *
 * user:“预览器是内容终点，浏览器是内容入口”+(预览器只取本机内容：一条是能直接给 iframe
 * 加载的绝对地址，一条是需要转换时读取的字节；两条都走已有的传输通道，不新开网络路径)。
 */
import type { LamToolsTransport, TransportHttpResponse } from '@/transport'
import type { PreviewResolveTransport } from './resolve'

export interface PreviewTransportOptions {
  transport?: LamToolsTransport
  /**
   * 后台实际源（含动态端口），例如 http://127.0.0.1:52341。
   * 桌面端端口是随机分配的，不能假定开发端口；为空时退回相对地址（同源托管场景）。
   */
  origin?: string | null
}

/** 内核 HTTP 前缀；iframe 地址必须带上它，否则请求到的是静态站点而不是后台。 */
const CORE_PREFIX = '/api/core'

/**
 * user:“与灯箱共用同一条解析与呈现链路”+
 * (没有后台绝对源时也要给出可加载的地址：补上 `/api/core` 前缀由开发代理转给后台。
 * 早期版本在这里直接返回不带前缀的 path，结果分屏用相对地址取图会 404。)
 */
function joinOrigin(origin: string | null | undefined, path: string): string {
  if (!origin) return `${CORE_PREFIX}${path}`
  return new URL(`${CORE_PREFIX}${path}`, origin).href
}

export function createPreviewTransport(options: PreviewTransportOptions = {}): PreviewResolveTransport {
  const origin = options.origin || null
  return {
    url(path: string): string {
      return joinOrigin(origin, path)
    },
    async read(path: string): Promise<Uint8Array> {
      if (!options.transport) throw new Error('预览通道未就绪')
      const response = await options.transport.request<TransportHttpResponse>({
        kind: 'http',
        method: 'GET',
        path,
        timeoutMs: 120_000,
        // user:“标注后无法引用”+(同一地址可能已被 `<img>` 以 no-cors 缓存过；
        // CORS 读字节时绕开缓存，否则浏览器直接报“没有 ACAO / Failed to fetch”)。
        cache: 'no-store',
      })
      if (response.status < 200 || response.status >= 300) {
        let detail = response.status === 404 ? '原文件不存在' : '文件无法读取'
        try {
          const payload = JSON.parse(new TextDecoder().decode(response.body))
          if (typeof payload.detail === 'string') detail = payload.detail
        } catch { /* Non-JSON failures keep the readable fallback. */ }
        throw new Error(detail)
      }
      return response.body
    },
  }
}
