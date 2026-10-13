<template>
  <section class="project-visual-picker" :aria-label="t('项目图标与颜色')">
    <div class="project-visual-picker-group">
      <strong>{{ t("图标") }}</strong>
      <div class="project-icon-options" role="radiogroup" :aria-label="t('项目图标')">
        <button
          v-for="option in iconOptions"
          :key="option.key"
          class="project-icon-option"
          :class="{ 'is-active': iconKey === option.key }"
          type="button"
          role="radio"
          :aria-checked="iconKey === option.key ? 'true' : 'false'"
          :aria-label="option.label"
          :title="option.label"
          :disabled="disabled"
          :data-project-icon-option="option.key"
          @click="$emit('update:icon-key', option.key)"
        >
          <ProjectVisualIcon :icon-key="option.key" :color-key="colorKey" :size="30" :icon-size="17" />
        </button>
      </div>
    </div>

    <div class="project-visual-picker-group">
      <strong>{{ t("颜色") }}</strong>
      <div class="project-color-options" role="radiogroup" :aria-label="t('项目颜色')">
        <button
          v-for="option in colorOptions"
          :key="option.key"
          class="project-color-option"
          :class="{ 'is-active': colorKey === option.key }"
          type="button"
          role="radio"
          :aria-checked="colorKey === option.key ? 'true' : 'false'"
          :aria-label="option.label"
          :title="option.label"
          :disabled="disabled"
          :data-project-color-option="option.key"
          @click="$emit('update:color-key', option.key)"
        >
          <ProjectVisualIcon icon-key="folder" :color-key="option.key" :size="22" swatch />
        </button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { t } from '../i18n/index'

import type { CoreProjectColorKey, CoreProjectIconKey } from '../projects/types'
import ProjectVisualIcon from './ProjectVisualIcon.vue'

withDefaults(defineProps<{
  iconKey?: CoreProjectIconKey
  colorKey?: CoreProjectColorKey
  disabled?: boolean
}>(), {
  iconKey: 'folder',
  colorKey: 'gray',
  disabled: false,
})

defineEmits<{
  'update:icon-key': [key: CoreProjectIconKey]
  'update:color-key': [key: CoreProjectColorKey]
}>()

const iconOptions: Array<{ key: CoreProjectIconKey; label: string }> = [
  { key: 'folder', get label() { return t("通用文件夹") } },
  { key: 'code', get label() { return t("代码开发") } },
  { key: 'idea', get label() { return t("灵感构思") } },
  { key: 'design', get label() { return t("设计创作") } },
  { key: 'docs', get label() { return t("文档知识") } },
  { key: 'work', get label() { return t("工作业务") } },
  { key: 'rocket', get label() { return t("产品发布") } },
  { key: 'sparkles', get label() { return t("AI 创意") } },
]

const colorOptions: Array<{ key: CoreProjectColorKey; label: string }> = [
  { key: 'gray', get label() { return t("淡灰") } },
  { key: 'blue', get label() { return t("蓝色") } },
  { key: 'violet', get label() { return t("紫色") } },
  { key: 'pink', get label() { return t("粉色") } },
  { key: 'red', get label() { return t("红色") } },
  { key: 'orange', get label() { return t("橙色") } },
  { key: 'green', get label() { return t("绿色") } },
  { key: 'cyan', get label() { return t("青色") } },
  { key: 'sunrise', get label() { return t("日出渐变") } },
  { key: 'aurora', get label() { return t("极光渐变") } },
  { key: 'ocean', get label() { return t("海洋渐变") } },
  { key: 'violet-sky', get label() { return t("紫蓝渐变") } },
  { key: 'berry', get label() { return t("莓果渐变") } },
  { key: 'ember', get label() { return t("余烬渐变") } },
  { key: 'forest', get label() { return t("森林渐变") } },
  { key: 'prism', get label() { return t("棱镜渐变") } },
]
</script>

<style scoped>
.project-visual-picker {
  display: grid;
  gap: var(--space-4);
  min-width: 0;
}

.project-visual-picker-group {
  display: grid;
  gap: var(--space-2);
}

.project-visual-picker-group > strong {
  color: color-mix(in srgb, var(--theme-main-text) 76%, transparent);
  font-size: 12px;
  font-weight: 650;
}

.project-icon-options,
.project-color-options {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.project-icon-option,
.project-color-option {
  display: grid;
  place-items: center;
  box-sizing: border-box;
  width: 38px;
  height: 38px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--theme-control-text);
  cursor: pointer;
}

.project-color-option {
  width: 32px;
  height: 32px;
}

.project-icon-option:hover,
.project-color-option:hover {
  background: color-mix(in srgb, var(--theme-control-text) var(--alpha-hover), transparent);
}

.project-icon-option:active,
.project-color-option:active {
  background: color-mix(in srgb, var(--theme-control-text) var(--alpha-active), transparent);
}

.project-icon-option.is-active,
.project-color-option.is-active {
  border-color: color-mix(in srgb, var(--theme-control-text) 48%, transparent);
  background: color-mix(in srgb, var(--theme-control-text) var(--alpha-hover), transparent);
}

.project-icon-option:focus-visible,
.project-color-option:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent);
  outline-offset: 1px;
}

.project-icon-option:disabled,
.project-color-option:disabled {
  cursor: default;
  opacity: .45;
}
</style>
