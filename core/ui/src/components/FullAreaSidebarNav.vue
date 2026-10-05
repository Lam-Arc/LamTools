<template>
  <nav class="full-area-sidebar-nav" :aria-label="ariaLabel">
    <button
      v-for="section in sections"
      :key="section.id"
      type="button"
      class="full-area-sidebar-nav__item"
      :class="{ 'is-active': section.id === activeId }"
      :aria-current="section.id === activeId ? 'page' : undefined"
      :data-nav-section="section.id"
      @click="$emit('select', section.id)"
    >
      <span class="full-area-sidebar-nav__icon" aria-hidden="true">
        <component
          :is="settingsSectionIcon(section.icon)"
          v-if="settingsSectionIcon(section.icon)"
          :size="15"
          :stroke-width="1.8"
        />
        <span v-else class="full-area-sidebar-nav__dot"></span>
      </span>
      <span class="full-area-sidebar-nav__label">{{ section.label }}</span>
    </button>
  </nav>
</template>

<script setup lang="ts">
/**
 * FullAreaSidebarNav — 设置 / 插件占用整个界面时的左侧竖排导航。
 *
 * 会话栏那一列让给当前整版界面：页名顶替模式位（在 LamToolsApp 里），
 * 这里列出分区。只渲染名称与图标，不带小字描述。
 */
import { settingsSectionIcon, type SettingsSection } from './settingsSections'

defineProps<{
  sections: SettingsSection[]
  activeId?: string
  ariaLabel?: string
}>()

defineEmits<{ select: [id: string] }>()
</script>
