export interface WriterQueuedInput {
  id: string
  session_id: string
  text: string
  mode: 'next_turn' | 'guidance' | string
  status: 'queued' | 'dispatching' | 'failed' | 'guidance_pending' | 'guidance_consumed' | 'guidance_expired' | 'cancelled' | 'sent' | string
  position: number
  target_turn_id: string | null
  created_at: string | null
  updated_at: string | null
  dispatching_at: string | null
  dispatched_at: string | null
  consumed_at: string | null
  error: string | null
  metadata: Record<string, unknown>
}
