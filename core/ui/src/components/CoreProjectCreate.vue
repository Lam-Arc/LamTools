<template>
  <Teleport defer to=".workspace-shell">
    <div class="core-project-dialog-backdrop" data-project-backdrop @mousedown.self="cancel">
      <section
        class="core-project-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="core-project-dialog-title"
        :aria-busy="loading || selectingRoot"
      >
        <header class="core-project-dialog-header">
          <h2 id="core-project-dialog-title">新建项目</h2>
          <p>选择一个工作目录，系统会为项目准备基础配置。</p>
        </header>

        <form class="core-project-create" @keydown.esc.prevent="cancel" @submit.prevent="submit">
          <label class="core-project-field core-project-root-label">
            <span>项目地址</span>
            <div class="core-project-root-field">
              <input
                ref="workRootInput"
                v-model="workRoot"
                data-project-root
                class="core-project-input"
                autocomplete="off"
                placeholder="选择或填写项目地址"
                required
                :disabled="loading || selectingRoot"
              />
              <button
                v-if="selectWorkRoot"
                type="button"
                class="core-project-browse"
                data-project-browse
                :disabled="loading || selectingRoot"
                :aria-label="selectingRoot ? '正在选择项目目录' : '选择项目目录'"
                :title="selectingRoot ? '选择中' : '选择项目目录'"
                @click="browse"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M3.5 6.5A2.5 2.5 0 0 1 6 4h4l2 2h6A2.5 2.5 0 0 1 20.5 8.5v8A2.5 2.5 0 0 1 18 19H6a2.5 2.5 0 0 1-2.5-2.5z" />
                </svg>
              </button>
            </div>
            <small>项目文件和自动生成的 AGENTS.md 将存放在此目录。</small>
          </label>

          <label class="core-project-field">
            <span>项目名称 <em>选填</em></span>
            <input
              v-model="name"
              data-project-name
              class="core-project-input"
              autocomplete="off"
              placeholder="留空时使用目录名称"
              :disabled="loading"
            />
          </label>

          <p v-if="error" class="core-project-error" role="alert">{{ error }}</p>

          <footer class="core-project-actions">
            <button type="button" class="core-project-cancel" data-project-cancel :disabled="loading" @click="cancel">取消</button>
            <button type="submit" class="core-project-submit" data-project-submit :disabled="loading || selectingRoot || !workRoot.trim()">
              {{ loading ? '创建中' : '创建项目' }}
            </button>
          </footer>
        </form>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'

const props = withDefaults(defineProps<{
  loading?: boolean
  error?: string
  selectWorkRoot?: () => Promise<string | null | undefined>
}>(), {
  loading: false,
  error: '',
  selectWorkRoot: undefined,
})

const emit = defineEmits<{
  submit: [payload: { name: string; work_root: string }]
  cancel: []
}>()

const name = ref('')
const workRoot = ref('')
const workRootInput = ref<HTMLInputElement | null>(null)
const selectingRoot = ref(false)

onMounted(() => nextTick(() => workRootInput.value?.focus()))

function submit() {
  const root = workRoot.value.trim()
  if (!root || props.loading || selectingRoot.value) return
  emit('submit', { name: name.value.trim(), work_root: root })
}

function cancel() {
  if (!props.loading) emit('cancel')
}

async function browse() {
  if (!props.selectWorkRoot || props.loading || selectingRoot.value) return
  selectingRoot.value = true
  try {
    const selected = await props.selectWorkRoot()
    if (selected) workRoot.value = selected.trim()
  } finally {
    selectingRoot.value = false
    await nextTick()
    workRootInput.value?.focus()
  }
}
</script>

<style scoped>
.core-project-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal-backdrop, 80);
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgb(0 0 0 / 34%);
}

.core-project-dialog {
  width: min(520px, 100%);
  max-height: calc(100dvh - 48px);
  overflow-y: auto;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #171717) 14%, transparent);
  border-radius: 12px;
  background: color-mix(in srgb, var(--theme-main-background, #fff) 97%, var(--theme-main-text, #171717) 3%);
  color: var(--theme-main-text, #171717);
  box-shadow: 0 8px 24px rgb(0 0 0 / 16%);
}

.core-project-dialog-header {
  padding: 30px 32px 0;
}

.core-project-dialog-header h2 {
  margin: 0;
  font-size: 25px;
  font-weight: 760;
  letter-spacing: 0;
  line-height: 1.2;
}

.core-project-dialog-header p {
  margin: 8px 0 0;
  color: color-mix(in srgb, var(--theme-main-text, #171717) 62%, transparent);
  font-size: 13px;
  line-height: 1.5;
}

.core-project-create {
  display: grid;
  gap: 20px;
  padding: 26px 32px 28px;
}

.core-project-field {
  display: grid;
  gap: 8px;
  min-width: 0;
  color: color-mix(in srgb, var(--theme-main-text, #171717) 82%, transparent);
  font-size: 13px;
  font-weight: 680;
}

.core-project-field em {
  color: color-mix(in srgb, var(--theme-main-text, #171717) 48%, transparent);
  font-size: 12px;
  font-style: normal;
  font-weight: 520;
}

.core-project-field small {
  color: color-mix(in srgb, var(--theme-main-text, #171717) 54%, transparent);
  font-size: 12px;
  font-weight: 480;
  line-height: 1.45;
}

.core-project-root-field {
  position: relative;
  min-width: 0;
}

.core-project-input {
  width: 100%;
  min-width: 0;
  height: 46px;
  box-sizing: border-box;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #171717) 18%, transparent);
  border-radius: 8px;
  outline: 0;
  background: transparent;
  color: var(--theme-main-text, #171717);
  padding: 0 13px;
  font: inherit;
  font-weight: 520;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.core-project-root-field .core-project-input {
  padding-right: 50px;
}

.core-project-input::placeholder {
  color: color-mix(in srgb, var(--theme-main-text, #171717) 44%, transparent);
}

.core-project-input:focus {
  border-color: color-mix(in srgb, var(--theme-main-text, #171717) 58%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--theme-main-text, #171717) 8%, transparent);
}

.core-project-browse {
  position: absolute;
  top: 5px;
  right: 5px;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--theme-main-text, #171717);
}

.core-project-browse:hover {
  background: color-mix(in srgb, var(--theme-main-text, #171717) 8%, transparent);
}

.core-project-browse:focus-visible,
.core-project-cancel:focus-visible,
.core-project-submit:focus-visible {
  outline: 2px solid var(--theme-main-text, #171717);
  outline-offset: 2px;
}

.core-project-browse svg {
  width: 21px;
  height: 21px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.7;
}

.core-project-error {
  margin: -6px 0 0;
  color: var(--red, #b42318);
  font-size: 12px;
  line-height: 1.4;
}

.core-project-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 2px;
}

.core-project-cancel,
.core-project-submit {
  min-width: 84px;
  height: 38px;
  border-radius: 7px;
  padding: 0 16px;
  font: inherit;
  font-size: 13px;
  font-weight: 680;
}

.core-project-cancel {
  border: 0;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #171717) 72%, transparent);
}

.core-project-cancel:hover {
  background: color-mix(in srgb, var(--theme-main-text, #171717) 7%, transparent);
  color: var(--theme-main-text, #171717);
}

.core-project-submit {
  border: 1px solid var(--theme-main-text, #171717);
  background: var(--theme-main-text, #171717);
  color: var(--theme-main-background, #fff);
}

.core-project-submit:hover:not(:disabled) {
  opacity: .86;
}

.core-project-dialog button:disabled,
.core-project-dialog input:disabled {
  cursor: default;
  opacity: .48;
}

@media (max-width: 600px) {
  .core-project-dialog-backdrop {
    padding: 12px;
  }

  .core-project-dialog {
    max-height: calc(100dvh - 24px);
    border-radius: 10px;
  }

  .core-project-dialog-header {
    padding: 24px 22px 0;
  }

  .core-project-create {
    gap: 18px;
    padding: 22px;
  }

  .core-project-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .core-project-cancel,
  .core-project-submit {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .core-project-input {
    transition: none;
  }
}
</style>
