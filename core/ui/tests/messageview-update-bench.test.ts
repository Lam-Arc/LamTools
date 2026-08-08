import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MessageView from '../src/components/MessageView.vue'

function bigLiveMessage(text: string) {
	const parts: unknown[] = [
		{ id: 'text-1', partType: 'model_text', status: 'running', content: text, label: '正文', metadata: { source: 'core_app_server' } },
	]
	for (let i = 0; i < 300; i += 1) {
		parts.push({
			id: `tool-${i}`,
			partType: 'tool_call',
			status: 'completed',
			content: '',
			label: '工具',
			toolName: 'read_file',
			toolArgs: { path: `/a/b/c${i}.py` },
			toolResult: '内容'.repeat(20),
			metadata: { source: 'core_app_server' },
		})
	}
	return {
		id: 'assistant:1',
		role: 'assistant' as const,
		content: text,
		timestamp: '',
		parts,
		metadata: { source: 'core_app_server', live: true },
	}
}

describe('big live message update bench', () => {
	it('measures per-tick update cost for a 300-part live message', async () => {
		const base = bigLiveMessage('')
		const wrapper = mount(MessageView, { props: { msg: base, processExpandedIds: new Set(), typingMessageIds: new Set() } })
		await wrapper.vm.$nextTick()

		const runs = 30
		const textPart = base.parts[0] as { id: string; partType: string; content: string }
		const toolParts = base.parts.slice(1)
		let t0 = performance.now()
		for (let i = 0; i < runs; i += 1) {
			const next = {
				...base,
				content: 'x'.repeat(i * 5),
				parts: [{ ...textPart, content: 'x'.repeat(i * 5) }, ...toolParts],
			}
			await wrapper.setProps({ msg: next })
			await wrapper.vm.$nextTick()
		}
		const perTick = (performance.now() - t0) / runs
		console.log(`[bench] MessageView update, 300-part live message → ${perTick.toFixed(1)}ms/tick`)
		expect(true).toBe(true)
		wrapper.unmount()
	}, 60_000)
})