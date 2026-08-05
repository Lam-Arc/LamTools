import {
  appServerUrl as coreAppServerUrl,
} from '@lamtools/ui'

export {
  CoreAppServerClient as WriterAppServerClient,
  CoreAppServerClosedError as WriterAppServerClosedError,
  type CoreAppServerClientOptions as WriterAppServerClientOptions,
  type JsonRpcClientResponse,
  type JsonRpcRequest,
  type JsonRpcResponse,
} from '@lamtools/ui'

export function appServerUrl(apiBase: string): string {
  return coreAppServerUrl(apiBase || window.location.origin, {
    path: '/api/core/app-server',
  })
}