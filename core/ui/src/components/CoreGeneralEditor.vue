<template>
  <section class="settings-panel">
    <header class="settings-title">
      <h1>{{ t("通用") }}</h1>
      <p>{{ t("设置界面语言、网络连接与运行偏好。") }}</p>
    </header>

    <p v-if="error" class="general-error" role="alert">{{ error }}</p>

    <article class="setting-card">
      <div class="subhead"><span class="muted subhead-title">{{ t("界面语言") }}</span></div>
      <p class="general-hint">{{ t("选择应用界面的显示语言。不会更改对话内容或模型的回答语言。") }}</p>
      <UiSelect
        :model-value="uiLanguage"
        :options="languageOptions"
        :aria-label="t('界面语言')"
        :disabled="languageSaving"
        @update:model-value="changeLanguage"
      />
    </article>

    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">{{ t("HTTP 代理") }}</span>
        <div class="subhead-actions">
          <button class="btn btn--ghost" type="button" :disabled="loading || busy" @click="refreshNetwork">{{ t("刷新") }}</button>
          <button class="btn btn--ghost" type="button" :disabled="loading || busy" @click="saveField('proxy')">{{ t("保存") }}</button>
        </div>
      </div>
      <p class="general-hint">{{ t("模型、MCP、命令工具、网页抓取与搜索、插件安装、软件更新下载的出口流量都将经此代理； 应用界面内的网页（渲染层）跟随系统代理设置。留空时这些流量直连，不读取系统环境变量。 本机地址（localhost、127.0.0.1、::1）始终直连。") }}</p>
      <label class="field">
        <input
          v-model="form.proxy"
          type="text"
          spellcheck="false"
          autocomplete="off"
          :placeholder="t('例如 http://127.0.0.1:7890')"
          :aria-label="t('HTTP 代理')"
          :disabled="loading || busy"
          @keyup.enter="saveField('proxy')"
        />
      </label>
      <p v-if="savedField === 'proxy'" class="general-saved" role="status">
        <Check :size="12" :stroke-width="2.2" aria-hidden="true" />{{ t("已保存") }}</p>
    </article>

    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">{{ t("不使用代理的地址") }}</span>
        <div class="subhead-actions">
          <button class="btn btn--ghost" type="button" :disabled="loading || busy" @click="saveField('no_proxy')">{{ t("保存") }}</button>
        </div>
      </div>
      <p class="general-hint">{{ t("匹配这些主机的请求将直连，不经过 HTTP 代理；命令工具按同一份规则写入 NO_PROXY。 多个规则用英文逗号分隔。") }}</p>
      <label class="field">
        <input
          v-model="form.no_proxy"
          type="text"
          spellcheck="false"
          autocomplete="off"
          :placeholder="t('例如 localhost,127.0.0.1,::1,.example.com,*.corp.com')"
          :aria-label="t('不使用代理的地址')"
          :disabled="loading || busy"
          @keyup.enter="saveField('no_proxy')"
        />
      </label>
      <p v-if="savedField === 'no_proxy'" class="general-saved" role="status">
        <Check :size="12" :stroke-width="2.2" aria-hidden="true" />{{ t("已保存") }}</p>
    </article>

    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">{{ t("自定义证书") }}</span>
        <div class="subhead-actions">
          <button class="btn btn--ghost" type="button" :disabled="loading || busy" @click="saveField('ca_cert')">{{ t("保存") }}</button>
        </div>
      </div>
      <p class="general-hint">{{ t("可选。填写 PEM 根证书路径后，模型请求以它为信任根，并以 SSL_CERT_FILE、NODE_EXTRA_CA_CERTS 等变量注入 MCP 与命令工具；留空则使用系统信任链。") }}</p>
      <label class="field">
        <input
          v-model="form.ca_cert"
          type="text"
          spellcheck="false"
          autocomplete="off"
          :placeholder="t('例如 C:\\certs\\root-ca.pem')"
          :aria-label="t('自定义证书')"
          :disabled="loading || busy"
          @keyup.enter="saveField('ca_cert')"
        />
      </label>
      <p v-if="savedField === 'ca_cert'" class="general-saved" role="status">
        <Check :size="12" :stroke-width="2.2" aria-hidden="true" />{{ t("已保存") }}</p>
    </article>

    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">{{ t("提问自动继续") }}</span>
        <div class="subhead-actions">
          <button class="btn btn--ghost" type="button" :disabled="loading || busy" @click="fetchAskAutoContinue">{{ t("刷新") }}</button>
        </div>
      </div>
      <div class="general-toggle-row">
        <p class="general-hint general-hint--inline">{{ t("打开后，模型的提问卡超过 5 分钟无人回答，会按「用户跳过」回传，本轮继续往下走。 需要你授权的审批卡不受影响，会一直等你处理。") }}</p>
        <SundaySwitch
          :model-value="askAutoContinue"
          :disabled="loading || busy"
          :label="t('提问自动继续')"
          @update:model-value="toggleAskAutoContinue"
        />
      </div>
    </article>

    <article v-if="keepAwakeSupported" class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">{{ t("保持电脑运行") }}</span>
        <div class="subhead-actions">
          <button class="btn btn--ghost" type="button" :disabled="loading || busy" @click="fetchKeepAwake">{{ t("刷新") }}</button>
        </div>
      </div>
      <div class="general-toggle-row">
        <p class="general-hint general-hint--inline">{{ t("打开后阻止系统进入空闲休眠（手动睡眠、合盖休眠不受影响），长任务不会被中断。") }}</p>
        <SundaySwitch
          :model-value="keepAwake"
          :disabled="loading || busy"
          :label="t('保持电脑运行')"
          @update:model-value="toggleKeepAwake"
        />
      </div>
    </article>

    <article v-if="memoryResumeSupported" class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">{{ t("内存中断自动续跑") }}</span>
        <div class="subhead-actions">
          <button class="btn btn--ghost" type="button" :disabled="loading || memoryResumeBusy" @click="thresholdSettingsDraft.requestReplace(() => void fetchMemoryResume())">{{ t("刷新") }}</button>
          <button class="btn btn--ghost" type="button" :disabled="loading || memoryResumeBusy" @click="saveMemoryThreshold">{{ t("保存") }}</button>
        </div>
      </div>
      <div class="general-toggle-row">
        <p class="general-hint general-hint--inline">{{ t("机器内存不足导致本轮中断时，Sunday 会说明原因，并写明「可用内存大于多少就自动继续」； 内存回来后在同一会话自动开新一轮接着做，最多连续 3 次。你自己先发了新消息时不再自动继续。") }}</p>
        <SundaySwitch
          :model-value="memoryResume"
          :disabled="loading || memoryResumeBusy"
          :label="t('内存中断自动续跑')"
          @update:model-value="toggleMemoryResume"
        />
      </div>
      <p class="general-hint">{{ t("自动继续的内存阈值（GB）：可用内存 = 物理内存 + 页面文件还能分配的量。调高更保守，但要等更久。") }}</p>
      <label class="field">
        <input
          v-model="memoryThresholdDraft"
          type="number"
          min="0.5"
          max="1024"
          step="0.5"
          inputmode="decimal"
          :aria-label="t('自动继续的内存阈值（GB）')"
          :disabled="loading || memoryResumeBusy"
          @keyup.enter="saveMemoryThreshold"
        />
      </label>
      <p v-if="memoryResumeSaved" class="general-saved" role="status">
        <Check :size="12" :stroke-width="2.2" aria-hidden="true" />{{ t("已保存") }}</p>
    </article>

    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">{{ t("Assistant 显示") }}</span>
        <div class="subhead-actions">
          <button class="btn btn--ghost" type="button" :disabled="loading || assistantDisplayBusy" @click="saveAssistantIdentity">{{ t("保存") }}</button>
        </div>
      </div>
      <p class="general-hint">{{ t("只影响界面显示：是否用气泡、是否自动拆分，以及显示的名称与头像；对话记录、上下文和消息协议都不变。") }}</p>
      <div class="general-toggle-row">
        <p class="general-hint general-hint--inline">{{ t("Assistant 可选择是否使用消息气泡，开启后回复以气泡呈现，关闭时保持无边框正文。") }}</p>
        <SundaySwitch
          :model-value="assistantAppearance.bubblesEnabled"
          :disabled="loading || assistantDisplayBusy"
          :label="t('使用消息气泡')"
          @update:model-value="toggleAssistantBubbles"
        />
      </div>
      <div class="general-toggle-row">
        <p class="general-hint general-hint--inline">{{ t("自动气泡拆分会把一条长回复按段落与标题拆成多个气泡；代码块、公式和表格保持完整，关闭后整条回复只显示为一个气泡。") }}</p>
        <SundaySwitch
          :model-value="assistantAppearance.splitEnabled"
          :disabled="loading || assistantDisplayBusy"
          :label="t('自动气泡拆分')"
          @update:model-value="toggleAssistantSplit"
        />
      </div>
      <p class="general-hint">{{ t("显示名称：留空时使用默认名称（Assistant）。") }}</p>
      <label class="field">
        <input
          v-model="assistantNameDraft"
          type="text"
          spellcheck="false"
          autocomplete="off"
          :placeholder="t('例如 Sunday')"
          :aria-label="t('显示名称')"
          :disabled="loading || assistantDisplayBusy"
          @keyup.enter="saveAssistantIdentity"
        />
      </label>
      <p class="general-hint">{{ t("头像：上传一张图片并调整裁切；留空时显示名称首字母。") }}</p>
      <!-- user:“助手头像那块别填链接 上传，裁切”+(不再让用户填图片地址，
           改为选择本地图片后当场拖动、缩放裁切，导出正方形头像并立即保存) -->
      <AssistantAvatarField
        :avatar="assistantAvatarDraft"
        :fallback="assistantAvatarInitial"
        :size="assistantAvatarSizeDraft"
        :roundness="assistantAvatarRoundnessDraft"
        :disabled="loading || assistantDisplayBusy"
        @change="applyAssistantAvatar"
      />
      <!-- user:“头上头像显示大小太小了 设成可调节，裁切也是圆角率可调节”+
           (尺寸与圆角率做成可调项；裁切圈与消息区同步按这两个值显示) -->
      <div class="assistant-avatar-tuners">
        <SundayRange
          :model-value="assistantAvatarSizeDraft"
          :min="AVATAR_SIZE_MIN"
          :max="AVATAR_SIZE_MAX"
          :step="1"
          suffix=" px"
          :label="t('头像大小')"
          :disabled="loading"
          @update:model-value="updateAssistantAvatarSize"
        />
        <SundayRange
          :model-value="assistantAvatarRoundnessDraft"
          :min="AVATAR_ROUNDNESS_MIN"
          :max="AVATAR_ROUNDNESS_MAX"
          :step="1"
          suffix="%"
          :label="t('圆角率')"
          :disabled="loading"
          @update:model-value="updateAssistantAvatarRoundness"
        />
      </div>
      <p v-if="assistantDisplaySaved" class="general-saved" role="status">
        <Check :size="12" :stroke-width="2.2" aria-hidden="true" />{{ t("已保存") }}</p>
    </article>

    <article class="setting-card" data-experimental-preview>
      <div class="subhead">
        <span class="muted subhead-title">{{ t("实验性功能") }}</span>
        <span class="general-experimental-badge">{{ t("实验性") }}</span>
      </div>
      <div class="general-toggle-row">
        <p class="general-hint general-hint--inline">{{ t("图片、音视频、PDF、Office 与 Markdown 文件会在内置分屏里直接打开。功能仍在完善，遇到显示异常可以关闭，改回默认应用打开。") }}</p>
        <SundaySwitch
          :model-value="splitPreview.enabled.value"
          :label="t('分屏文件预览（实验性）')"
          data-experimental-preview-switch
          @update:model-value="splitPreview.setEnabled"
        />
      </div>
    </article>

    <p class="general-hint general-hint--foot">{{ t("保存后新发起的模型、MCP 与命令调用立即按新设置走；已连接的 MCP 服务与已运行的后台命令需重启应用。") }}</p>
  </section>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Check } from 'lucide-vue-next'
import UiSelect from '@/components/UiSelect.vue'
import SundaySwitch from '@/components/SundaySwitch.vue'
import SundayRange from '@/components/SundayRange.vue'
import AssistantAvatarField from '@/components/AssistantAvatarField.vue'
import { UI_LANGUAGES, uiLanguage, saveUiLanguage } from '@/i18n/index.ts'
import { useSettingsDraft } from '@/composables/useSettingsDraftGuard.ts'
import { useSplitPreviewPreference } from '@/split/previewPreference.ts'
import {
  ASSISTANT_DISPLAY_NAMESPACE,
  AVATAR_ROUNDNESS_MAX,
  AVATAR_ROUNDNESS_MIN,
  AVATAR_SIZE_MAX,
  AVATAR_SIZE_MIN,
  assistantDisplayPreferences,
  assistantDisplaySnapshot,
  normalizeAssistantDisplayPreferences,
  setAssistantDisplayPreferences,
  type AssistantDisplayPreferences,
} from '@/composables/useAssistantDisplayPreferences.ts'

const languageOptions = [...UI_LANGUAGES]
// user:“设置中把它标记为实验性功能”+(开关直接生效并记住选择，不需要再点保存)。
const splitPreview = useSplitPreviewPreference()
const languageSaving = ref(false)
async function changeLanguage(locale: string) {
  if (languageSaving.value) return
  languageSaving.value = true
  error.value = ''
  try {
    await saveUiLanguage(props.requestRpc, locale)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    languageSaving.value = false
  }
}

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  /** Mirrors the settings shell: the keep-awake switch exists on Windows only. */
  platform?: 'windows' | 'linux' | 'mobile' | 'web' | 'other'
}>()

const NAMESPACE = 'core.network'
const KEEP_AWAKE_NAMESPACE = 'core.keepAwake'
const ASK_AUTO_CONTINUE_NAMESPACE = 'core.askAutoContinue'
const MEMORY_RESUME_NAMESPACE = 'core.memoryResume'

// Mirrors the backend defaults in runtime/memory_guard.py: an unset namespace
// means「开着，阈值 4 GB」, so the card must not read an empty value as "off".
const MEMORY_RESUME_DEFAULT_THRESHOLD_GB = 4

type FieldKey = 'proxy' | 'no_proxy' | 'ca_cert'

const form = reactive({ proxy: '', no_proxy: '', ca_cert: '' })
const loading = ref(true)
const busyKeys = ref<FieldKey[]>([])
const savedField = ref<FieldKey | ''>('')
const error = ref('')
const keepAwake = ref(false)
const keepAwakeSaving = ref(false)
const askAutoContinue = ref(false)
const askAutoContinueSaving = ref(false)
const memoryResume = ref(true)
const memoryResumeSaving = ref(false)
const memoryResumeLoading = ref(false)
const memoryThresholdDraft = ref(String(MEMORY_RESUME_DEFAULT_THRESHOLD_GB))
const memoryResumeSaved = ref(false)

// user:“Assistant 可选择是否使用消息气泡”“支持自定义 Assistant 显示名称和头像”
// “支持开启或关闭自动气泡拆分”+(三项都只是显示偏好：读侧在消息渲染里同步生效，
// 这里负责编辑，并写进既有设置命名空间持久化，不新增存储体系)。
const assistantAppearance = assistantDisplayPreferences
const assistantNameDraft = ref(assistantAppearance.name)
const assistantAvatarDraft = ref(assistantAppearance.avatar)
// user:“头上头像显示大小太小了 设成可调节，裁切也是圆角率可调节”+
// (尺寸/圆角率用草稿值驱动预览，停手 400ms 后合并写一次设置，避免拖动时反复落盘)
const assistantAvatarSizeDraft = ref(assistantAppearance.avatarSize)
const assistantAvatarRoundnessDraft = ref(assistantAppearance.avatarRoundness)
const assistantDisplaySaving = ref(false)
const assistantDisplaySaved = ref(false)
const assistantDisplayBusy = computed(() => busy.value || assistantDisplaySaving.value)

function syncAssistantDrafts(): void {
  assistantNameDraft.value = assistantAppearance.name
  assistantAvatarDraft.value = assistantAppearance.avatar
  assistantAvatarSizeDraft.value = assistantAppearance.avatarSize
  assistantAvatarRoundnessDraft.value = assistantAppearance.avatarRoundness
}

function applyAssistantAppearance(value: unknown): void {
  setAssistantDisplayPreferences(normalizeAssistantDisplayPreferences(value))
  syncAssistantDrafts()
}

async function persistAssistantAppearance(patch: Partial<AssistantDisplayPreferences>): Promise<boolean> {
  const previous = assistantDisplaySnapshot()
  const next = setAssistantDisplayPreferences(patch)
  assistantDisplaySaving.value = true
  assistantDisplaySaved.value = false
  error.value = ''
  try {
    await props.requestRpc('settings.update', { namespace: ASSISTANT_DISPLAY_NAMESPACE, value: next })
    assistantDisplaySaved.value = true
    return true
  } catch (e) {
    // 保存失败就退回上一次成功的取值，界面不能显示一个后端没存下的状态
    setAssistantDisplayPreferences(previous)
    error.value = e instanceof Error ? e.message : String(e)
    return false
  } finally {
    assistantDisplaySaving.value = false
  }
}

async function fetchAssistantAppearance(): Promise<void> {
  try {
    const value = readValue(await props.requestRpc('settings.get', { namespace: ASSISTANT_DISPLAY_NAMESPACE }))
    if (Object.keys(value).length > 0) applyAssistantAppearance(value)
    else syncAssistantDrafts()
  } catch (e) {
    // 设置读不到时沿用本地偏好，不拦住其它卡片的操作
    syncAssistantDrafts()
    error.value = e instanceof Error ? e.message : String(e)
  }
}

function toggleAssistantBubbles(next: boolean): void {
  if (assistantDisplayBusy.value) return
  void persistAssistantAppearance({ bubblesEnabled: next })
}

function toggleAssistantSplit(next: boolean): void {
  if (assistantDisplayBusy.value) return
  void persistAssistantAppearance({ splitEnabled: next })
}

async function saveAssistantIdentity(): Promise<boolean> {
  if (loading.value || assistantDisplayBusy.value) return false
  const saved = await persistAssistantAppearance({
    name: assistantNameDraft.value.trim(),
    avatar: assistantAvatarDraft.value.trim(),
  })
  if (saved) syncAssistantDrafts()
  return saved
}

const assistantAvatarInitial = computed(
  () => (assistantNameDraft.value.trim().charAt(0) || 'A').toUpperCase(),
)

// user:“助手头像那块别填链接 上传，裁切”+(裁切按下的“应用”就是头像的确认动作，
// 因此上传/移除都直接保存头像；名称输入仍走卡片右上角的保存，不顺手提交草稿)
async function applyAssistantAvatar(avatar: string): Promise<void> {
  if (assistantDisplayBusy.value) return
  const previous = assistantAvatarDraft.value
  assistantAvatarDraft.value = avatar
  const saved = await persistAssistantAppearance({ avatar })
  if (!saved) assistantAvatarDraft.value = previous
}

let avatarTunerSaveTimer: ReturnType<typeof setTimeout> | null = null

function updateAssistantAvatarSize(value: number): void {
  assistantAvatarSizeDraft.value = value
  scheduleAvatarTunerSave()
}

function updateAssistantAvatarRoundness(value: number): void {
  assistantAvatarRoundnessDraft.value = value
  scheduleAvatarTunerSave()
}

function scheduleAvatarTunerSave(): void {
  if (avatarTunerSaveTimer) clearTimeout(avatarTunerSaveTimer)
  avatarTunerSaveTimer = setTimeout(() => {
    avatarTunerSaveTimer = null
    void persistAvatarTuners()
  }, 400)
}

async function persistAvatarTuners(): Promise<void> {
  const saved = await persistAssistantAppearance({
    avatarSize: assistantAvatarSizeDraft.value,
    avatarRoundness: assistantAvatarRoundnessDraft.value,
  })
  // 保存失败就退回后端仍然生效的外观，滑块不留在没存下的位置。
  if (!saved) {
    assistantAvatarSizeDraft.value = assistantAppearance.avatarSize
    assistantAvatarRoundnessDraft.value = assistantAppearance.avatarRoundness
  }
}

onBeforeUnmount(() => {
  // 关掉设置页前最后一次拖动也要落盘，不能等定时器
  if (avatarTunerSaveTimer) {
    clearTimeout(avatarTunerSaveTimer)
    avatarTunerSaveTimer = null
    void persistAvatarTuners()
  }
})

const busy = computed(() => busyKeys.value.length > 0 || keepAwakeSaving.value || askAutoContinueSaving.value)
const keepAwakeSupported = computed(() => (props.platform ?? 'other') === 'windows')
/** The host-memory reading exists on Windows and Linux; elsewhere the feature is inert. */
const memoryResumeSupported = computed(
  () => (props.platform ?? 'other') === 'windows' || (props.platform ?? 'other') === 'linux',
)
const memoryResumeBusy = computed(() => memoryResumeLoading.value || memoryResumeSaving.value || busy.value)
const navigationBusy = computed(() => busy.value || memoryResumeSaving.value || languageSaving.value)
const networkDrafts = Object.fromEntries((['proxy', 'no_proxy', 'ca_cert'] as const).map(key => [key, useSettingsDraft({
  section: 'general', label: () => ({ proxy: t('代理地址'), no_proxy: t('直连地址'), ca_cert: t('CA 证书') })[key],
  read: () => form[key], restore: value => { form[key] = value; error.value = '' },
  save: () => saveField(key), busy: navigationBusy, error,
})])) as Record<FieldKey, ReturnType<typeof useSettingsDraft<string>>>
const thresholdSettingsDraft = useSettingsDraft({
  section: 'general', label: () => t('自动恢复阈值'), read: () => String(memoryThresholdDraft.value),
  restore: value => { memoryThresholdDraft.value = value; error.value = '' },
  save: saveMemoryThreshold, busy: navigationBusy, error,
})
function refreshNetwork() {
  networkDrafts.proxy.requestReplace(() => void fetchConfig(), Object.values(networkDrafts).map(item => item.draft))
}

function readValue(result: Record<string, unknown>): Record<string, unknown> {
  const value = result.value
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

async function fetchConfig() {
  loading.value = true
  error.value = ''
  savedField.value = ''
  try {
    const value = readValue(await props.requestRpc('settings.get', { namespace: NAMESPACE }))
    form.proxy = String(value.proxy ?? '')
    form.no_proxy = String(value.no_proxy ?? '')
    form.ca_cert = String(value.ca_cert ?? '')
    for (const draft of Object.values(networkDrafts)) draft.accept()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function saveField(key: FieldKey) {
  if (loading.value || busy.value) return false
  const next = form[key].trim()
  const previous = form[key]
  form[key] = next
  savedField.value = ''
  error.value = ''
  busyKeys.value = [...busyKeys.value, key]
  try {
    await props.requestRpc('settings.update', { namespace: NAMESPACE, value: { [key]: next } })
    networkDrafts[key].accept(next)
    savedField.value = key
    return true
  } catch (e) {
    // The backend validates the field; restore the last known-good value and
    // never claim the draft was stored.
    error.value = e instanceof Error ? e.message : String(e)
    form[key] = previous
    return false
  } finally {
    busyKeys.value = busyKeys.value.filter((item) => item !== key)
  }
}

onMounted(fetchConfig)

async function fetchKeepAwake() {
  if (!keepAwakeSupported.value) return
  error.value = ''
  try {
    const value = readValue(await props.requestRpc('settings.get', { namespace: KEEP_AWAKE_NAMESPACE }))
    keepAwake.value = !!value.enabled
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function toggleKeepAwake() {
  if (!keepAwakeSupported.value || keepAwakeSaving.value) return
  const next = !keepAwake.value
  const previous = keepAwake.value
  keepAwake.value = next
  keepAwakeSaving.value = true
  error.value = ''
  try {
    await props.requestRpc('settings.update', {
      namespace: KEEP_AWAKE_NAMESPACE,
      value: { enabled: next },
    })
  } catch (e) {
    keepAwake.value = previous
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    keepAwakeSaving.value = false
  }
}

onMounted(fetchKeepAwake)


async function fetchAskAutoContinue() {
  error.value = ''
  try {
    const value = readValue(await props.requestRpc('settings.get', { namespace: ASK_AUTO_CONTINUE_NAMESPACE }))
    askAutoContinue.value = !!value.enabled
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function toggleAskAutoContinue() {
  if (askAutoContinueSaving.value) return
  const next = !askAutoContinue.value
  const previous = askAutoContinue.value
  askAutoContinue.value = next
  askAutoContinueSaving.value = true
  error.value = ''
  try {
    await props.requestRpc('settings.update', {
      namespace: ASK_AUTO_CONTINUE_NAMESPACE,
      value: { enabled: next },
    })
  } catch (e) {
    askAutoContinue.value = previous
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    askAutoContinueSaving.value = false
  }
}

onMounted(fetchAskAutoContinue)


function readMemoryThreshold(value: Record<string, unknown>): number {
  const raw = value.threshold_gb
  if (typeof raw !== 'number' || !Number.isFinite(raw) || raw <= 0) {
    return MEMORY_RESUME_DEFAULT_THRESHOLD_GB
  }
  return raw
}

async function fetchMemoryResume() {
  if (!memoryResumeSupported.value) return
  memoryResumeLoading.value = true
  error.value = ''
  memoryResumeSaved.value = false
  try {
    const value = readValue(await props.requestRpc('settings.get', { namespace: MEMORY_RESUME_NAMESPACE }))
    // Absent namespace = the backend default (on, 4 GB), not "off".
    memoryResume.value = value.enabled === undefined ? true : !!value.enabled
    memoryThresholdDraft.value = String(readMemoryThreshold(value))
    thresholdSettingsDraft.accept()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    memoryResumeLoading.value = false
  }
}

async function toggleMemoryResume() {
  if (!memoryResumeSupported.value || memoryResumeBusy.value) return
  const next = !memoryResume.value
  const previous = memoryResume.value
  memoryResume.value = next
  memoryResumeSaving.value = true
  memoryResumeSaved.value = false
  error.value = ''
  try {
    await props.requestRpc('settings.update', {
      namespace: MEMORY_RESUME_NAMESPACE,
      value: { enabled: next },
    })
  } catch (e) {
    memoryResume.value = previous
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    memoryResumeSaving.value = false
  }
}

async function saveMemoryThreshold() {
  if (!memoryResumeSupported.value || memoryResumeBusy.value) return false
  const parsed = Number(memoryThresholdDraft.value)
  if (!Number.isFinite(parsed) || parsed < 0.5 || parsed > 1024) {
    error.value = t("阈值需要是 0.5 到 1024 之间的数字（GB）")
    return false
  }
  const previous = memoryThresholdDraft.value
  memoryResumeSaving.value = true
  memoryResumeSaved.value = false
  error.value = ''
  try {
    await props.requestRpc('settings.update', {
      namespace: MEMORY_RESUME_NAMESPACE,
      value: { threshold_gb: parsed },
    })
    memoryThresholdDraft.value = String(parsed)
    thresholdSettingsDraft.accept()
    memoryResumeSaved.value = true
    return true
  } catch (e) {
    // The backend validates; keep the last known-good value rather than
    // pretending the draft was stored.
    memoryThresholdDraft.value = previous
    error.value = e instanceof Error ? e.message : String(e)
    return false
  } finally {
    memoryResumeSaving.value = false
  }
}

onMounted(fetchMemoryResume)
onMounted(fetchAssistantAppearance)
</script>

<style scoped>
.general-hint {
  margin: 0 0 var(--space-2);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) 62%, transparent);
  font-size: 12px;
  line-height: 1.6;
}

.general-hint--foot {
  margin: 0;
  padding: 0 var(--space-1);
}

.general-toggle-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-3);
  align-items: center;
}

.general-hint--inline {
  margin: 0;
}

.btn--ghost.is-on {
  color: var(--green);
}

.general-saved {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 0;
  color: var(--green);
  font-size: 12px;
}

.assistant-avatar-tuners {
  display: grid;
  gap: var(--space-2);
  max-width: 340px;
}

.general-experimental-badge {
  flex: 0 0 auto;
  padding: 1px var(--space-2);
  border-radius: 999px;
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) 65%, transparent);
  font-size: 10px;
  line-height: 1.6;
}

.general-error {
  margin: 0;
  padding: 9px 12px;
  border: 1px solid color-mix(in srgb, var(--red) 22%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--red) 10%, transparent);
  color: color-mix(in srgb, var(--red) 64%, var(--settings-main-text, #fff));
  font-size: 13px;
}
</style>
