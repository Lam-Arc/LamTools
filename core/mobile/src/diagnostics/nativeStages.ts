import { listen } from '@tauri-apps/api/event'
import { hasEmbeddedRustCore } from '../native/rustAgent'
import type { MobileDiagnostics } from './MobileDiagnostics'

interface NativeStageEvent {
  turnId?: unknown
  stage?: unknown
}

export async function listenForNativeAgentStages(diagnostics: MobileDiagnostics): Promise<() => void> {
  if (!hasEmbeddedRustCore()) return () => {}
  return await listen<NativeStageEvent>('sunday-agent-stage', ({ payload }) => {
    diagnostics.recordNativeStage(payload)
  })
}
