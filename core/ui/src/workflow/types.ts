/** Workflow mode — shared types mirroring the backend runtime/workflow.py model. */

export type WorkflowNodeKind = 'llm' | 'agent' | 'action' | 'input' | 'output'
export type ActionKind = 'shell' | 'script' | 'http' | 'file-data'
export type PortDirection = 'in' | 'out'
export type NodeStateStatus = 'idle' | 'running' | 'done' | 'error' | 'skipped' | 'cancelled'

export interface WorkflowPort {
  name: string
  type: string
  direction: PortDirection
  description?: string
}

export interface WorkflowNode {
  id: string
  kind: WorkflowNodeKind
  title: string
  config: Record<string, unknown>
  ports: WorkflowPort[]
  position: { x: number; y: number }
}

/** Alias used where the `WorkflowNode` name clashes with the component export. */
export type WorkflowNodeData = WorkflowNode

export interface WorkflowEdge {
  id: string
  source: string
  source_port: string
  target: string
  target_port: string
}

export interface WorkflowInputParam {
  name: string
  type: string
  description?: string
  required: boolean
  default?: unknown
}

export interface WorkflowDef {
  name: string
  description: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  input_params: WorkflowInputParam[]
  output_port: string
  exposed: boolean
  tool_name: string
  work_root: string
  created_at: string
  updated_at: string
}

export interface WorkflowNodeState {
  node_id: string
  status: NodeStateStatus
  output?: unknown
  error?: string
  attempts: number
  started_at?: string | null
  finished_at?: string | null
}

export type WorkflowRunStatus = 'completed' | 'failed' | 'cancelled' | 'paused'

export interface WorkflowRunResult {
  status: WorkflowRunStatus
  output: unknown
  node_states: Record<string, WorkflowNodeState>
  values: Record<string, unknown>
  error: string
  run_id: string
  steps_remaining: number
}
