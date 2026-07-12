import {
  appServerUrl as coreAppServerUrl,
  fetchAppServerToken as fetchCoreAppServerToken,
} from '@lamtools/ui'

export {
  CoreAppServerClient as WriterAppServerClient,
  CoreAppServerClosedError as WriterAppServerClosedError,
  type CoreAppServerClientOptions as WriterAppServerClientOptions,
  type JsonRpcClientResponse,
  type JsonRpcRequest,
  type JsonRpcResponse,
} from '@lamtools/ui'

export async function fetchAppServerToken(apiBase: string): Promise<string> {
  return await fetchCoreAppServerToken(apiBase, '/api/app-server-token')
}

export function appServerUrl(apiBase: string, token?: string): string {
  return coreAppServerUrl(apiBase || window.location.origin, {
    path: '/api/app-server',
    token,
  })
}
