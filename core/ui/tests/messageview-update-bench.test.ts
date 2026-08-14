import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MessageView from '../src/components/MessageView.vue'
import type { MessagePart } from '../src/types'

function bigLiveMessage(text: string) {
	const parts: MessagePart[] = [
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
		const wrapper = mount(MessageView, { props: { msg: base, processExpandedIds: new Set<string>(), typingMessageIds: new Set<string>() } })
		await wrapper.vm.$nextTick()

		const runs = 30
		const textPart = base.parts[0]
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
		// The bench must assert something real — the rendered text must track
		// the prop updates (audit 21 S3: `expect(true).toBe(true)` made this a
		// no-op). The threshold is generous (CI machines are slow) — it only
		// catches a pathological O(n²) regression, not perf tuning.
		expect(perTick).toBeLessThan(250)
		const rendered = wrapper.text()
		expect(rendered).toContain('x'.repeat(145))
		expect(rendered).not.toContain('x'.repeat(150))
		wrapper.unmount()
	}, 60_000)
})