declare module '@lamtools/bundled-workflow-ui' {
  export function buildWorkflowRunPayload(name: string, options?: Record<string, unknown>, includeContinuation?: boolean): Record<string, unknown>
  export function createWorkflowApi(requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>): any
  export function normalizeWorkflowActivations(value: unknown): any[]
  export function isWorkflowRevisionConflict(error: unknown): boolean
  export function normalizeWorkflowRunResponse(value: unknown): any
  export function buildWorkflowQueuePayload(name: string, options?: Record<string, unknown>): Record<string, unknown>
  export function buildWorkflowQueueClearPayload(options?: Record<string, unknown>): Record<string, unknown>
  export function buildWorkflowQueueQuery(options?: Record<string, unknown>, includeHistory?: boolean): Record<string, unknown>
  export function normalizeWorkflowObjectInfo(value: unknown, requestedType?: string): Record<string, any>
  export function normalizeWorkflowQueueItem(value: unknown): any
  export function normalizeWorkflowQueueItems(value: unknown): any[]
  export function normalizeImportedWorkflow(value: unknown, fallbackName?: string): any
  export function serializeWorkflowJson(definition: any, filename?: string): string
  export function schemaFields(value: unknown, direction?: string): any[]
  export function schemaPorts(value: unknown, existing?: any[]): any[]
  export const WorkflowNodeCatalog: any
  export const SchemaNodeEditor: any
  export const WorkflowNodeRuntimeDock: any
  export const WorkflowRunInputForm: any
  export const WorkflowQueuePanel: any
  export const WorkflowResourcesPanel: any
  export const WorkflowPoliciesPanel: any
  export function createWorkflowNodeFromSchema(schema: any, id: string, position: { x: number; y: number }): any
  export function createWorkflowDocument(definition: any): any
  export function workflowDefinitionToDocument(definition: any): any
  export function workflowDocumentToDefinition(document: any, fallback?: any): any
  export function isWorkflowDocumentV2(value: unknown): boolean
  export function reconcileWorkflowNodePorts(definition: any, previous: any, next: any): any
  export function normalizeNodeStateStatus(value: unknown): any
  export function normalizeWorkflowNodeState(value: unknown, nodeId?: string): any
  export function normalizeWorkflowRunStatus(value: unknown): any
  export function normalizeCanvasElement(value: unknown, key?: string): any
  export function normalizeCanvasElements(value: unknown, legacyBuckets?: Record<string, unknown>): any[]
  export function createWorkflowClipboardPayload(definition: any, selectedIds: Iterable<string>): any
  export function deleteWorkflowCanvasElementContents(definition: any, containerId: string): any
  export function parseWorkflowClipboardPayload(value: unknown): any
  export function remapWorkflowClipboard(payload: any, existingIds?: Iterable<string>, anchor?: { x: number; y: number }): any
  export function alignWorkflowNodes(nodes: any[], alignment: string): any[]
  export function distributeWorkflowNodes(nodes: any[], direction: string): any[]
  export function workflowCanvasElementZIndex(kind: string): number
  export function workflowCanvasElementContents(definition: any, containerId: string): any
  export function deleteWorkflowCanvasElementContents(definition: any, containerId: string): any
  export function workflowCanvasElementContents(definition: any, containerId: string): any
  export function hasWorkflowClipboardPayload(): boolean
  export function writeWorkflowClipboardPayload(payload: any): Promise<boolean>
  export const WORKFLOW_CANVAS_STORAGE_KEY: string
  export const WORKFLOW_CLIPBOARD_TYPE: string
  export const WORKFLOW_CLIPBOARD_VERSION: number
  export const WORKFLOW_CANONICAL_NODE_KINDS: readonly string[]
  export const WORKFLOW_NODE_KINDS: readonly string[]
  export type WorkflowDef = any
  export type WorkflowNode = any
  export type WorkflowActivation = any
  export type WorkflowTrigger = any
}
