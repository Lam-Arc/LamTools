<template>
  <div class="plan-string-list" :data-plan-string-list="ariaLabel || 'list'">
    <div v-for="(item, index) in modelValue" :key="index" class="plan-string-row">
      <input
        class="plan-string-input"
        type="text"
        :value="item"
        :placeholder="placeholder"
        :aria-label="`${ariaLabel || '列表项'} ${index + 1}`"
        @input="onInput(index, $event)"
      />
      <button
        class="plan-string-remove"
        type="button"
        :aria-label="`删除${ariaLabel || '这一项'} ${index + 1}`"
        title="删除"
        @click="remove(index)"
      >×</button>
    </div>
    <button class="plan-string-add" type="button" @click="add">{{ addLabel || '添加一项' }}</button>
  </div>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{
  modelValue: string[]
  placeholder?: string
  addLabel?: string
  ariaLabel?: string
}>(), {
  placeholder: '',
  addLabel: '',
  ariaLabel: '',
})

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

function onInput(index: number, event: Event): void {
  const next = [...props.modelValue]
  next[index] = (event.target as HTMLInputElement).value
  emit('update:modelValue', next)
}

function remove(index: number): void {
  const next = [...props.modelValue]
  next.splice(index, 1)
  emit('update:modelValue', next)
}

function add(): void {
  emit('update:modelValue', [...props.modelValue, ''])
}
</script>

<style scoped>
.plan-string-list { --text: var(--theme-backdrop-text); display: grid; gap: var(--space-1); min-width: 0; }
.plan-string-row { display: flex; align-items: center; gap: var(--space-1); min-width: 0; }
.plan-string-input {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 30px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  padding: 0 var(--space-2);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  font: inherit;
  font-size: 11px;
}
.plan-string-input::placeholder { color: color-mix(in srgb, var(--theme-composer-text) 45%, transparent); }
.plan-string-input:focus-visible { outline: 0; }
.plan-string-remove {
  flex: 0 0 auto;
  min-width: 28px;
  min-height: 28px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 52%, transparent);
  font-size: 15px;
  line-height: 1;
}
.plan-string-remove:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.plan-string-remove:active { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); }
.plan-string-remove:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent); outline-offset: 1px; }
.plan-string-add {
  justify-self: start;
  min-height: 26px;
  border: 0;
  border-radius: var(--radius-sm);
  padding: 0 var(--space-1);
  background: transparent;
  color: color-mix(in srgb, var(--text) 55%, transparent);
  font-size: 10px;
}
.plan-string-add:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.plan-string-add:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent); outline-offset: 1px; }
@media (max-width: 640px) {
  .plan-string-input { min-height: 34px; }
  .plan-string-remove { min-width: 34px; min-height: 34px; }
  .plan-string-add { min-height: 34px; }
}
</style>
