import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it } from 'vitest'
import CommandPalette from '../src/components/CommandPalette.vue'
import { useComposerCommandPalette } from '../src/composables/useComposerCommandPalette'
import type { CoreCommandCatalogItem } from '../src/types'

const commands = [
  { name: 'compact', title: '压缩上下文', description: '压缩当前会话上下文', icon: 'archive', source: 'core', action: 'run_action' },
  { name: 'fork', title: '分叉', description: '从当前会话分叉', icon: 'git-branch', source: 'core', action: 'run_action' },
  { name: 'brainstorming', title: 'brainstorming', description: '梳理需求', icon: 'sparkles', source: 'core', action: 'insert_token' },
] satisfies CoreCommandCatalogItem[]

describe('CommandPalette', () => {
  it('renders commands and emits select', async () => {
    const wrapper = mount(CommandPalette, {
      props: { commands, activeIndex: 0 },
    })
    expect(wrapper.text()).toContain('/compact')
    expect(wrapper.text()).toContain('Enter')
    expect(wrapper.text()).toContain('Esc')
    await wrapper.find('[data-command-name="compact"]').trigger('click')
    expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({ name: 'compact' })
  })

  it('keeps the selected command in range when the query shrinks the result set', () => {
    const text = ref('/')
    const cursor = ref(text.value.length)
    const palette = useComposerCommandPalette({
      text,
      cursor,
      commands: ref(commands),
    })

    palette.move(2)
    expect(palette.selected()?.name).toBe('brainstorming')

    text.value = '/co'
    cursor.value = text.value.length

    expect(palette.filteredCommands.value.map(command => command.name)).toEqual(['compact'])
    expect(palette.activeIndex.value).toBe(0)
    expect(palette.selected()?.name).toBe('compact')
  })
})
