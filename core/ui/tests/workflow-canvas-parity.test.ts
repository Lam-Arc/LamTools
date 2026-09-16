import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  alignWorkflowNodes,
  createWorkflowClipboardPayload,
  deleteWorkflowCanvasElementContents,
  distributeWorkflowNodes,
  workflowCanvasElementContents,
  normalizeCanvasElements,
  normalizeImportedWorkflow,
  parseWorkflowClipboardPayload,
  remapWorkflowClipboard,
  WORKFLOW_CANONICAL_NODE_KINDS,
  WORKFLOW_NODE_KINDS,
  workflowCanvasElementZIndex,
  writeWorkflowClipboardPayload,
} from '@lamtools/bundled-workflow-ui'

const node = (id: string, x: number, y: number, parent_id?: string) => ({
  id, kind: 'command', title: id, config: { command: '' },
  ports: [{ name: 'out', type: 'string', direction: 'out' }, { name: 'in', type: 'string', direction: 'in' }],
  position: { x, y },
  ...(parent_id ? { parent_id } : {}),
})

type TestNode = { id: string; position: { x: number; y: number } }
type TestEdge = { id: string }

describe('workflow canvas parity models', () => {
  it('keeps title and tabs clear while placing icon-only canvas tools on the left', () => {
    const viewSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowView.vue',
    ), 'utf8')
    const canvasSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue',
    ), 'utf8')
    const layoutSource = readFileSync(resolve(__dirname, '../src/styles/layout.css'), 'utf8')
    const controlBarSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowControlBar.vue',
    ), 'utf8')

    expect(viewSource).toContain('v-if="workflowTabs.length > 1"')
    expect(viewSource).toContain('<div class="wf-header-title">')
    expect(viewSource).toContain('to="[data-titlebar-workflow-tabs]"')
    expect(viewSource).toContain('-webkit-app-region: no-drag')
    expect(viewSource).toContain('border-radius: var(--radius) var(--radius) 0 0')
    expect(viewSource).toContain('background: var(--theme-main-soft-background)')
    expect(viewSource).toContain('.wf-workflow-tabs { display: none; }')
    expect(viewSource).toContain('<Teleport v-if="workflowDefinition" defer to=".workspace-plugin-modal">')
    expect(viewSource).toContain('data-workflow-conversation')
    expect(viewSource).toContain('class="wf-convo-float-body thread"')
    expect(viewSource).toContain('border-radius: var(--radius-xl) var(--radius-xl) 0 0')
    expect(viewSource).toContain('var(--composer-height, 120px)')
    expect(viewSource).not.toContain(':global(.workspace-shell--workflow-interaction-active)')
    expect(viewSource).not.toContain('bottom var(--dur-morph)')
    expect(viewSource).not.toContain(':global(.workspace-shell--workflow-composer-has-value)')
    expect(layoutSource).toContain('.workspace-shell--workflow-interaction-active .floating-composer')
    expect(layoutSource).toContain('.workspace-shell--workflow:has(.floating-composer:focus-within) [data-workflow-conversation]')
    expect(layoutSource).toContain('.workspace-shell--workflow-composer-has-value [data-workflow-conversation]')
    expect(layoutSource).toContain('.workspace-shell--workflow-composer-stop [data-workflow-conversation]')
    expect(layoutSource).toContain('.workspace-shell--workflow:has([data-workflow-conversation]:hover) [data-workflow-conversation]')
    expect(layoutSource).toContain('.workspace-shell--workflow:has(.wf-convo-float:hover) .floating-composer')
    expect(layoutSource).not.toContain('.workspace-shell--workflow-interaction-active [data-workflow-conversation]')
    expect(layoutSource).not.toContain([
      '.workspace-shell--workflow-interaction-active .floating-composer,',
      '.workspace-shell--workflow:has(.floating-composer:focus-within) .floating-composer,',
      '.workspace-shell--workflow-composer-has-value .floating-composer,',
    ].join('\n'))
    expect(viewSource).toContain('var(--workflow-composer-expanded-height, var(--composer-height, 120px))')
    expect(viewSource).not.toContain('bottom var(--dur-morph)')
    expect(viewSource).toMatch(/\.wf-convo-float\s*\{[\s\S]*?left: var\(--main-left\);[\s\S]*?right: var\(--main-right\);[\s\S]*?margin-inline: auto;/)
    expect(viewSource).not.toMatch(/\.wf-convo-float\s*\{[\s\S]*?transform:/)
    expect(viewSource).not.toMatch(/\.workspace-shell--workflow-interaction-active\) \.wf-convo-float,[\s\S]*?transform:/)
    expect(canvasSource).not.toContain('<Controls')
    expect(canvasSource).not.toContain('@vue-flow/controls')
    expect(canvasSource).toContain('<Grid2x2')
    expect(canvasSource).toContain('<Maximize2')
    expect(canvasSource).toContain('aria-label="左对齐"')
    expect(canvasSource).toContain('left: var(--space-3)')
    expect(canvasSource).toContain('flex-direction: column')
    expect(canvasSource).toContain('overflow-y: auto')
    expect(canvasSource).not.toContain('.vue-flow__controls')
    expect(viewSource).toContain('<template #controls>')
    expect(canvasSource).toContain('<slot name="controls" />')
    expect(controlBarSource).toContain('display: contents')
    expect(controlBarSource).not.toContain('position: absolute')
    expect(controlBarSource).toContain('aria-label="运行整个工作流"')
    expect(controlBarSource).toContain('<Square')
    expect(layoutSource).toContain('top: var(--titlebar-offset, 0px)')
    expect(layoutSource).toContain('height: calc(100dvh - var(--titlebar-offset, 0px))')
  })

  it('passes the active workflow repository scope into turn options', () => {
    const viewSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowView.vue',
    ), 'utf8')

    expect(viewSource).toContain("work_root: workflowRoot(activeWorkflow.value) || ''")
    expect(viewSource).toContain(':locked="chat.activeTurnRunning.value"')
    expect(viewSource).not.toContain('canvasLocked')
    expect(viewSource).toContain('if (chat.activeTurnRunning.value && !force) return')
    expect(viewSource).toContain('if (previous && !running) scheduleGraphReload(true)')
  })

  it('keeps the catalog localized, semantic, and bounded above the composer', () => {
    const catalogSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNodeCatalog.vue',
    ), 'utf8')
    const nodeSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNode.vue',
    ), 'utf8')

    expect(catalogSource).toContain('<Plus')
    expect(catalogSource).toContain('<Star')
    expect(catalogSource).toContain('<X')
    expect(catalogSource).toContain('workflowSchemaSearchValues')
    expect(catalogSource).toContain('overflow: auto')
    expect(catalogSource).toContain('--composer-height')
    expect(catalogSource).not.toContain('categoryGlyph')
    expect(catalogSource).not.toContain('>×</')
    expect(catalogSource).not.toContain('>★</')
    expect(nodeSource).toContain('<component :is="nodeTypeIcon"')
    expect(nodeSource).toContain('BrainCircuit')
    expect(nodeSource).toContain('workflowNodeDisplayName')
  })

  it('keeps visible built-in ids and workflow affordances aligned', () => {
    const visibleBuiltIns = [
      'model', 'agent', 'command', 'python', 'constant', 'input', 'output',
      'template', 'condition', 'merge', 'join', 'wait_event', 'approval', 'subgraph',
    ]
    expect([...WORKFLOW_CANONICAL_NODE_KINDS]).toEqual(visibleBuiltIns)
    expect([...WORKFLOW_NODE_KINDS]).toEqual(expect.arrayContaining(visibleBuiltIns))

    const inspectorSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowInspector.vue',
    ), 'utf8')
    const queueSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowQueuePanel.vue',
    ), 'utf8')
    const triggersSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowTriggersPanel.vue',
    ), 'utf8')
    const viewSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowView.vue',
    ), 'utf8')

    expect(inspectorSource).toContain('approval: UserCheck')
    expect(inspectorSource).toContain('wait_event: Clock3')
    expect(inspectorSource).toContain('|| Blocks')
    expect(inspectorSource).not.toContain('|| Command')
    expect(inspectorSource).toContain('<Maximize2')
    expect(queueSource).toContain('<RefreshCw')
    expect(queueSource).toContain('<ChevronRight')
    expect(queueSource).toContain('<X')
    expect(queueSource).not.toMatch(/>\s*[↻›×]\s*<\/./)
    expect(triggersSource).toContain('<RefreshCw')
    expect(triggersSource).toContain('<Plus')
    expect(triggersSource).not.toMatch(/>\s*[↻＋]\s*<\/./)
    expect(viewSource).not.toContain('LockKeyhole')
    expect(viewSource).not.toContain('锁定画布')
    expect(viewSource).not.toContain('<svg')
  })

  it('uses the middle mouse button for panning and stable port ids for handles', () => {
    const canvasSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue',
    ), 'utf8')
    const nodeSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNode.vue',
    ), 'utf8')

    expect(canvasSource).toContain(':pan-on-drag="[1]"')
    expect(canvasSource).toContain('edge.source_port_id')
    expect(canvasSource).toContain('edge.target_port_id')
    expect(canvasSource).toContain('port.id === params.sourceHandle || port.name === params.sourceHandle')
    expect(nodeSource).toContain(':id="portHandleId(p)"')
    expect(nodeSource).toContain(':key="`in-${portHandleId(p)}`"')
    expect(nodeSource).toContain('return String(port.id || port.name)')
  })

  it('uses left-drag for box selection and only drags already-selected items', () => {
    const canvasSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue',
    ), 'utf8')

    expect(canvasSource).toContain(':selection-key-code="true"')
    expect(canvasSource).not.toContain(':selection-on-drag=')
    expect(canvasSource).toContain(':select-nodes-on-drag="false"')
    expect(canvasSource).toContain('draggable: selectedCanvasElementIds.value.has(element.id)')
    expect(canvasSource).toContain('draggable: selectedNodeIds.value.has(n.id)')
    expect(canvasSource).toContain('draggable: isSelected')
  })

  it('keeps a double-clicked container selected with all of its contents', () => {
    const canvasSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue',
    ), 'utf8')

    expect(canvasSource).toContain("provide('wf-select-canvas-element-contents', (elementId: string) => selectCanvasElementContents(elementId, true))")
    expect(canvasSource).toContain('function selectCanvasElementContents(elementId: string, includeContainer = false)')
    expect(canvasSource).toContain('...(includeContainer ? [elementId] : [])')
  })

  it('suppresses the native browser context menu across the Tauri shell', () => {
    const desktopSource = readFileSync(resolve(__dirname, '../../desktop/src/main.ts'), 'utf8')
    expect(desktopSource).toContain("document.addEventListener('contextmenu', (event) => event.preventDefault(), { capture: true })")
  })

  it('disables the native browser context menu across the Tauri desktop shell', () => {
    const desktopSource = readFileSync(resolve(__dirname, '../../desktop/src/main.ts'), 'utf8')
    expect(desktopSource).toContain("document.addEventListener('contextmenu', (event) => event.preventDefault(), { capture: true })")
  })

  it('keeps node cards opaque while runtime details use a glass side dock', () => {
    const canvasSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue',
    ), 'utf8')
    const nodeSource = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowNode.vue',
    ), 'utf8')

    expect(nodeSource).toContain('box-shadow: var(--shadow-sm)')
    expect(nodeSource).toContain('background: var(--theme-main-background)')
    expect(nodeSource).toContain('WorkflowNodeRuntimeDock')
    expect(nodeSource).toContain('conic-gradient')
    expect(nodeSource).not.toContain('opacity: 0.8;')
    expect(nodeSource).not.toContain('backdrop-filter: blur(var(--space-2)) saturate(1.8) contrast(1.08)')
    expect(nodeSource).not.toContain('var(--shadow);')
    expect(canvasSource).toContain('var(--shadow-sm)')
    expect(canvasSource).toContain(':elevate-nodes-on-select="false"')
    expect(canvasSource).toContain("readLayoutPixels('--z-composer', 40) - 1")
  })

  it('clears local selection after an empty box-selection gesture', () => {
    const source = readFileSync(resolve(
      __dirname,
      '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue',
    ), 'utf8')
    const handler = source.match(/function onSelectionEnd\(\): void \{([\s\S]*?)\n\}/)?.[1] || ''
    expect(handler).toContain('setSelection(next)')
    expect(handler).not.toContain('if (!next.size) return')
  })

  it('normalizes legacy graphical buckets and aliases', () => {
    const elements = normalizeCanvasElements({
      frames: [{ id: 'f1', x: 10, y: 20, w: 300, h: 180, name: 'Legacy frame' }],
      notes: { n1: { content: 'remember', position: { x: 40, y: 50 } } },
      reroutes: [{ id: 'r1', type: 'waypoint', position: { x: 70, y: 80 } }],
    })
    expect(elements).toMatchObject([
      { id: 'f1', kind: 'frame', width: 300, height: 180, title: 'Legacy frame' },
      { id: 'n1', kind: 'note', text: 'remember', position: { x: 40, y: 50 } },
      { id: 'r1', kind: 'reroute', position: { x: 70, y: 80 } },
    ])
    expect(normalizeImportedWorkflow({ name: 'legacy', groups: [{ id: 'g1', type: 'box' }], nodes: [] }).canvas_elements).toHaveLength(1)
  })

  it('normalizes ComfyUI group bounds and reroute positions for geometry fallback', () => {
    expect(normalizeCanvasElements([
      { id: 'group-1', kind: 'group', bounding: [12, 18, 320, 180] },
      { id: 'reroute-1', kind: 'reroute', pos: [44, 52] },
    ])).toMatchObject([
      { id: 'group-1', position: { x: 12, y: 18 }, width: 320, height: 180 },
      { id: 'reroute-1', position: { x: 44, y: 52 } },
    ])
  })

  it('keeps explicit node parent ids when parsing and remapping clipboard data', () => {
    const payload = parseWorkflowClipboardPayload(JSON.stringify({
      nodes: [{ ...node('child', 20, 20, 'group') }],
      edges: [],
      canvas_elements: [{ id: 'group', kind: 'group', position: { x: 0, y: 0 }, width: 300, height: 200, title: 'group', text: '' }],
    }))
    expect(payload?.nodes[0].parent_id).toBe('group')
    const pasted = remapWorkflowClipboard(payload!, ['child', 'group'])
    expect(pasted.nodes[0].parent_id).toBe(pasted.canvas_elements[0].id)
    const partial = remapWorkflowClipboard({ ...payload!, canvas_elements: [] }, ['child'])
    expect(partial.nodes[0]).not.toHaveProperty('parent_id')
  })

  it('keeps visual aids behind executable graph content and exposes resize handles', () => {
    expect(workflowCanvasElementZIndex('frame')).toBeLessThan(workflowCanvasElementZIndex('group'))
    expect(workflowCanvasElementZIndex('group')).toBeLessThan(workflowCanvasElementZIndex('note'))
    expect(workflowCanvasElementZIndex('comment')).toBeLessThan(workflowCanvasElementZIndex('reroute'))
    const canvasSource = readFileSync(resolve(__dirname, '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue'), 'utf8')
    const elementSource = readFileSync(resolve(__dirname, '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvasElement.vue'), 'utf8')
    expect(canvasSource).toContain('const workflowEdgeZIndex = 10')
    expect(canvasSource).toContain('const workflowNodeZIndex = 20')
    expect(elementSource).toContain("startResize($event, 'southeast')")
    expect(elementSource).toContain("updateElement(element.value.id, { width: localWidth.value, height: localHeight.value })")
  })

  it('resolves container contents from parent links first and legacy geometry second', () => {
    const definition = {
      nodes: [
        { ...node('inside', 40, 40), dimensions: { width: 120, height: 80 } },
        { ...node('outside', 360, 260), dimensions: { width: 120, height: 80 } },
        { ...node('linked-node', 900, 900, 'frame'), dimensions: { width: 120, height: 80 } },
        { ...node('nested-node', 900, 900, 'nested'), dimensions: { width: 120, height: 80 } },
      ],
      edges: [],
      canvas_elements: [
        { id: 'frame', kind: 'frame', position: { x: 0, y: 0 }, width: 420, height: 340, title: 'frame', text: '' },
        { id: 'nested', kind: 'group', parent_id: 'frame', position: { x: 20, y: 20 }, width: 180, height: 120, title: 'nested', text: '' },
        { id: 'linked-outside', kind: 'note', parent_id: 'frame', position: { x: 900, y: 900 }, width: 60, height: 40, title: 'linked', text: '' },
        { id: 'legacy-inside', kind: 'note', position: { x: 300, y: 220 }, width: 80, height: 60, title: 'legacy', text: '' },
        { id: 'legacy-overlap', kind: 'note', position: { x: 390, y: 300 }, width: 80, height: 60, title: 'overlap', text: '' },
        { id: 'nested-note', kind: 'comment', parent_id: 'nested', position: { x: 10, y: 10 }, width: 60, height: 40, title: 'nested note', text: '' },
      ],
    } as any

    expect(workflowCanvasElementContents(definition, 'frame')).toEqual({
      nodeIds: ['inside', 'linked-node', 'nested-node'],
      canvasElementIds: ['nested', 'linked-outside', 'legacy-inside', 'nested-note'],
    })
  })

  it('recursively includes explicit descendants of geometry-contained containers', () => {
    const definition = {
      nodes: [node('child-node', 900, 900, 'inner')],
      edges: [],
      canvas_elements: [
        { id: 'outer', kind: 'frame', position: { x: 0, y: 0 }, width: 420, height: 340, title: 'outer', text: '' },
        { id: 'inner', kind: 'group', position: { x: 40, y: 40 }, width: 180, height: 120, title: 'inner', text: '' },
      ],
    } as any

    expect(workflowCanvasElementContents(definition, 'outer')).toEqual({
      nodeIds: ['child-node'],
      canvasElementIds: ['inner'],
    })

    const result = deleteWorkflowCanvasElementContents(definition, 'outer')
    expect(result.nodes).toEqual([])
    expect(result.canvas_elements).toEqual([])
    expect(result.deletedNodeIds).toEqual(['child-node'])
    expect(result.deletedCanvasElementIds).toEqual(['outer', 'inner'])
  })

  it('deletes a container contents and connected node edges without mutating the definition', () => {
    const definition = {
      nodes: [node('inside', 20, 20), node('outside', 500, 20)],
      edges: [
        { id: 'inside-outside', source: 'inside', source_port: 'out', target: 'outside', target_port: 'in' },
        { id: 'outside-only', source: 'outside', source_port: 'out', target: 'outside', target_port: 'in' },
      ],
      canvas_elements: [
        { id: 'group', kind: 'group', position: { x: 0, y: 0 }, width: 300, height: 220, title: 'group', text: '' },
        { id: 'note', kind: 'note', parent_id: 'group', position: { x: 10, y: 10 }, width: 80, height: 40, title: 'note', text: '' },
      ],
    } as any

    const result = deleteWorkflowCanvasElementContents(definition, 'group')
    expect(result.deletedNodeIds).toEqual(['inside'])
    expect(result.deletedCanvasElementIds).toEqual(['group', 'note'])
    expect(result.nodes.map((item: any) => item.id)).toEqual(['outside'])
    expect(result.edges.map((item: any) => item.id)).toEqual(['outside-only'])
    expect(result.canvas_elements).toEqual([])
    expect(definition.nodes).toHaveLength(2)
    expect(definition.edges).toHaveLength(2)
  })

  it('copies selected nodes with only internal edges and remaps on paste', () => {
    const definition = {
      nodes: [node('a', 10, 20, 'n1'), node('b', 200, 20), node('c', 400, 20)],
      edges: [
        { id: 'ab', source: 'a', source_port: 'out', target: 'b', target_port: 'in' },
        { id: 'bc', source: 'b', source_port: 'out', target: 'c', target_port: 'in' },
      ],
      canvas_elements: [{ id: 'n1', kind: 'note', position: { x: 10, y: 180 }, width: 240, height: 130, title: 'n', text: '' }],
    } as any
    const payload = createWorkflowClipboardPayload(definition, ['a', 'b', 'n1'])
    expect(payload.edges.map((edge: TestEdge) => edge.id)).toEqual(['ab'])
    expect(parseWorkflowClipboardPayload(JSON.stringify(payload))).toMatchObject({ nodes: [{ id: 'a' }, { id: 'b' }], canvas_elements: [{ id: 'n1' }] })
    const pasted = remapWorkflowClipboard(payload, ['a', 'b', 'ab'], { x: 800, y: 100 })
    expect(pasted.nodes.map((item: TestNode) => item.id)).not.toEqual(['a', 'b'])
    expect(pasted.edges[0]).toMatchObject({ source: pasted.nodes[0].id, target: pasted.nodes[1].id })
    expect(pasted.nodes[0].position).toEqual({ x: 800, y: 100 })
    expect(pasted.canvas_elements[0].position).toEqual({ x: 800, y: 260 })
    expect(pasted.nodes[0].parent_id).toBe(pasted.canvas_elements[0].id)
  })

  it('supports system-clipboard fallback and deterministic layout operations', async () => {
    const payload = createWorkflowClipboardPayload({ nodes: [node('a', 0, 0)], edges: [] }, ['a'])
    await writeWorkflowClipboardPayload(payload)
    expect(parseWorkflowClipboardPayload(JSON.stringify(payload))).toMatchObject({ version: 1, type: 'lamtools.workflow.clipboard' })
    const aligned = alignWorkflowNodes([node('a', 0, 10), node('b', 50, 100)], 'top')
    expect(aligned.map((item: TestNode) => item.position.y)).toEqual([10, 10])
    const distributed = distributeWorkflowNodes([node('a', 0, 0), node('b', 100, 0), node('c', 400, 0)], 'horizontal')
    expect(distributed.map((item: TestNode) => item.position.x)).toEqual([0, 200, 400])
  })
})
