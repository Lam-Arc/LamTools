import { computed, ref, watch, type Ref } from 'vue'
import { findActiveSlashCandidate, resolveComposerCommandKind } from '../composer/syntax'
import type { CoreCommandCatalogItem } from '../types'

export interface ComposerCommandPaletteOptions {
  text: Ref<string>
  cursor: Ref<number>
  commands: Ref<CoreCommandCatalogItem[]>
}

export function useComposerCommandPalette(options: ComposerCommandPaletteOptions) {
  const activeIndex = ref(0)

  const activeSlash = computed(() => findActiveSlashCandidate(options.text.value, options.cursor.value))
  const filteredCommands = computed(() => {
    const span = activeSlash.value
    if (!span) return []
    const query = span.value.toLowerCase()
    return options.commands.value
      .filter(command => command.name.toLowerCase().startsWith(query))
      .map((command, index) => ({ command, index }))
      .sort((left, right) => {
        const kindDelta = Number(resolveComposerCommandKind(left.command) === 'skill')
          - Number(resolveComposerCommandKind(right.command) === 'skill')
        return kindDelta || left.index - right.index
      })
      .map(item => item.command)
      .slice(0, 12)
  })
  const open = computed(() => filteredCommands.value.length > 0)

  watch(
    filteredCommands,
    commands => {
      if (!commands.length) {
        activeIndex.value = 0
        return
      }
      if (activeIndex.value >= commands.length) {
        activeIndex.value = commands.length - 1
      }
    },
    { flush: 'sync' },
  )

  function move(delta: number) {
    const total = filteredCommands.value.length
    if (!total) return
    activeIndex.value = (activeIndex.value + delta + total) % total
  }

  function selected(): CoreCommandCatalogItem | null {
    return filteredCommands.value[activeIndex.value] ?? null
  }

  function reset() {
    activeIndex.value = 0
  }

  return { activeSlash, filteredCommands, open, activeIndex, move, selected, reset }
}
