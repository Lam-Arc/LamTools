<template>
  <!-- user:“在「设置 → 界面」新增「消息流（Message Stream）」配置模块”+
       (上方所见即所得预览，下方控件区；窄容器自动上下堆叠。) -->
  <section class="message-stream-settings" data-ui-id="settings.message-stream">
    <header class="ms-head">
      <div>
        <h2>{{ t("消息流") }}</h2>
        <p>{{ t("正文与过程行的字体、间距、容器和色彩；改动立即生效并保存。") }}</p>
      </div>
    </header>

    <!-- ── 所见即所得预览：直接消费同一套 --ms-* 变量与 data-ms-* 属性 ── -->
    <div class="ms-preview-shell">
      <span class="ms-preview-caption">{{ t("预览") }}</span>
      <div
        class="ms-preview"
        v-bind="previewAttrs"
        :style="previewVars"
        :class="{ 'is-nested': nestedCard }"
        data-ms-preview
      >
        <div
          class="ms-preview-body"
          :class="[`is-${settings.bodyContainer}`, { 'ms-shimmer-edge': settings.bodyContainer !== 'none' }]"
          data-ms-preview-body
        >
          <p>{{ t("这是消息正文的预览，字号、行距和段落间距都会实时反映在这里。") }}</p>
          <p>{{ t("第二段用来观察段落间距，以及容器形态（无 / 边框 / 卡片）的差别。") }}</p>
        </div>

        <div class="ms-preview-proc">
          <!-- 折叠态：只有标题 -->
          <div
            class="ms-proc-title"
            :class="`is-${settings.procTitleContainer}`"
            data-ms-preview-title
          >
            <span v-if="settings.procTitleIcon" class="ms-proc-title-icon" aria-hidden="true">▸</span>
            <span class="ms-proc-title-text">{{ t("已读取 3 个文件（折叠态）") }}</span>
          </div>

          <!-- 展开态：标题 + 内容 -->
          <div class="ms-proc-group" data-ms-preview-expanded>
            <div class="ms-proc-title is-expanded" :class="`is-${settings.procTitleContainer}`">
              <span v-if="settings.procTitleIcon" class="ms-proc-title-icon" aria-hidden="true">▾</span>
              <span class="ms-proc-title-text">{{ t("已读取 3 个文件（展开态）") }}</span>
            </div>
            <div
              class="ms-proc-body"
              :class="[`is-${settings.procBodyContainer}`, { 'ms-shimmer-edge': settings.procBodyContainer !== 'none' }]"
              data-ms-preview-proc-body
              data-ms-running="1"
            >
              <div class="ms-proc-body-inner">
                <p v-for="line in previewLines" :key="line" class="ms-proc-line">
                  {{ t("第 {n} 行：过程行展开内容的行高与字号。", { n: line }) }}
                </p>
              </div>
              <span class="ms-proc-body-more">{{ t("一级最多 {n} 行", { n: settings.procLines1 }) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── 消息正文 ── -->
    <article class="setting-card ms-group">
      <div class="ms-group-head">
        <strong>{{ t("消息正文") }}</strong>
        <span>{{ t("会话里助手与用户消息的正文排版。") }}</span>
      </div>

      <label class="ms-field">
        <span class="ms-field-label">{{ t("字体") }}</span>
        <UiSelect
          :model-value="settings.bodyFont"
          :options="fontOptions"
          :aria-label="t('正文字体')"
          data-ms-body-font
          @update:model-value="(value) => patch({ bodyFont: value as MessageStreamFontKey })"
        />
      </label>
      <label v-if="settings.bodyFont === 'custom'" class="ms-field">
        <span class="ms-field-label">{{ t("自定义字体名") }}</span>
        <input
          class="ms-input"
          type="text"
          :value="settings.bodyFontCustom"
          :placeholder="t('例如 Source Han Serif SC')"
          data-ms-body-font-custom
          @input="patch({ bodyFontCustom: ($event.target as HTMLInputElement).value })"
        />
      </label>
      <SundayRange
        :model-value="settings.bodyFontSize"
        :min="12"
        :max="20"
        :step="1"
        :label="t('字号')"
        suffix="px"
        data-ms-body-font-size
        @update:model-value="(value) => patch({ bodyFontSize: value })"
      />
      <SundayRange
        :model-value="settings.bodyLineHeight"
        :min="1.2"
        :max="2"
        :step="0.1"
        :decimals="1"
        :label="t('行距')"
        data-ms-body-line-height
        @update:model-value="(value) => patch({ bodyLineHeight: value })"
      />
      <SundayRange
        :model-value="settings.bodyParaGap"
        :min="0"
        :max="24"
        :step="2"
        :label="t('段落间距')"
        suffix="px"
        data-ms-body-para-gap
        @update:model-value="(value) => patch({ bodyParaGap: value })"
      />
      <label class="ms-field">
        <span class="ms-field-label">{{ t("容器") }}</span>
        <UiSelect
          :model-value="settings.bodyContainer"
          :options="bodyContainerOptions"
          :aria-label="t('正文容器')"
          data-ms-body-container
          @update:model-value="(value) => patch({ bodyContainer: value as MessageStreamBodyContainer })"
        />
      </label>
    </article>

    <!-- ── 过程行标题 ── -->
    <article class="setting-card ms-group">
      <div class="ms-group-head">
        <strong>{{ t("过程行标题") }}</strong>
        <span>{{ t("会话里工具调用那一行的标题，固定单行垂直居中。") }}</span>
      </div>

      <label class="ms-field">
        <span class="ms-field-label">{{ t("字体") }}</span>
        <UiSelect
          :model-value="settings.procTitleFont"
          :options="inheritFontOptions"
          :aria-label="t('过程行标题字体')"
          data-ms-proc-title-font
          @update:model-value="(value) => patch({ procTitleFont: value as MessageStreamInheritFontKey })"
        />
      </label>
      <label v-if="settings.procTitleFont === 'custom'" class="ms-field">
        <span class="ms-field-label">{{ t("自定义字体名") }}</span>
        <input
          class="ms-input"
          type="text"
          :value="settings.procTitleFontCustom"
          :placeholder="t('例如 Source Han Serif SC')"
          data-ms-proc-title-font-custom
          @input="patch({ procTitleFontCustom: ($event.target as HTMLInputElement).value })"
        />
      </label>
      <SundayRange
        :model-value="settings.procTitleFontSize"
        :min="11"
        :max="16"
        :step="1"
        :label="t('字号')"
        suffix="px"
        data-ms-proc-title-font-size
        @update:model-value="(value) => patch({ procTitleFontSize: value })"
      />
      <div class="ms-field ms-field--row">
        <span class="ms-field-label">{{ t("图标") }}</span>
        <SundaySwitch
          :model-value="settings.procTitleIcon"
          :label="t('显示过程行图标')"
          data-ms-proc-title-icon
          @update:model-value="(value: boolean) => patch({ procTitleIcon: value })"
        >
          {{ settings.procTitleIcon ? t("显示") : t("隐藏") }}
        </SundaySwitch>
      </div>
      <label class="ms-field">
        <span class="ms-field-label">{{ t("容器") }}</span>
        <UiSelect
          :model-value="settings.procTitleContainer"
          :options="titleContainerOptions"
          :aria-label="t('过程行标题容器')"
          data-ms-proc-title-container
          @update:model-value="(value) => patch({ procTitleContainer: value as MessageStreamTitleContainer })"
        />
      </label>
    </article>

    <!-- ── 过程行展开内容 ── -->
    <article class="setting-card ms-group">
      <div class="ms-group-head">
        <strong>{{ t("过程行展开内容") }}</strong>
        <span>{{ t("展开后显示的细节；等宽字体更利于读日志和路径。") }}</span>
      </div>

      <label class="ms-field">
        <span class="ms-field-label">{{ t("字体") }}</span>
        <UiSelect
          :model-value="settings.procBodyFont"
          :options="inheritFontOptions"
          :aria-label="t('过程行内容字体')"
          data-ms-proc-body-font
          @update:model-value="(value) => patch({ procBodyFont: value as MessageStreamInheritFontKey })"
        />
      </label>
      <label v-if="settings.procBodyFont === 'custom'" class="ms-field">
        <span class="ms-field-label">{{ t("自定义字体名") }}</span>
        <input
          class="ms-input"
          type="text"
          :value="settings.procBodyFontCustom"
          :placeholder="t('例如 Source Han Serif SC')"
          data-ms-proc-body-font-custom
          @input="patch({ procBodyFontCustom: ($event.target as HTMLInputElement).value })"
        />
      </label>
      <SundayRange
        :model-value="settings.procBodyFontSize"
        :min="11"
        :max="16"
        :step="1"
        :label="t('字号')"
        suffix="px"
        data-ms-proc-body-font-size
        @update:model-value="(value) => patch({ procBodyFontSize: value })"
      />
      <!-- 0.05 步长：默认 1.65 必须能用滑条拖回，0.1 步长永远落不到 1.65。 -->
      <SundayRange
        :model-value="settings.procBodyLineHeight"
        :min="1.2"
        :max="1.8"
        :step="0.05"
        :decimals="2"
        :label="t('行距')"
        data-ms-proc-body-line-height
        @update:model-value="(value) => patch({ procBodyLineHeight: value })"
      />
      <SundayRange
        :model-value="settings.procLines1"
        :min="3"
        :max="8"
        :step="1"
        :label="t('一级高度')"
        :suffix="t(' 行')"
        data-ms-proc-lines-1
        @update:model-value="(value) => patch({ procLines1: value })"
      />
      <SundayRange
        :model-value="settings.procLines2"
        :min="8"
        :max="20"
        :step="1"
        :label="t('二级高度')"
        :suffix="t(' 行')"
        data-ms-proc-lines-2
        @update:model-value="(value) => patch({ procLines2: value })"
      />
      <label class="ms-field">
        <span class="ms-field-label">{{ t("容器") }}</span>
        <UiSelect
          :model-value="settings.procBodyContainer"
          :options="bodyContainerOptions"
          :aria-label="t('过程行内容容器')"
          data-ms-proc-body-container
          @update:model-value="(value) => patch({ procBodyContainer: value as MessageStreamBodyContainer })"
        />
      </label>
      <p v-if="nestedCard" class="ms-hint ms-hint--warn" data-ms-nested-hint>
        {{ t("正文与过程行内容都是卡片：内层自动降一级背景明度对比，避免嵌套脏乱。") }}
      </p>
    </article>

    <!-- ── 容器与描边：全部选「无」时整块收起 ── -->
    <article v-if="stylePanelVisible" class="setting-card ms-group" data-ms-style-panel>
      <div class="ms-group-head">
        <strong>{{ t("容器与描边") }}</strong>
        <span>{{ t("描边、填充、透明度与毛玻璃；只对「边框 / 胶囊 / 卡片」生效。") }}</span>
      </div>

      <label class="ms-field">
        <span class="ms-field-label">{{ t("线型") }}</span>
        <UiSelect
          :model-value="settings.borderStyle"
          :options="borderStyleOptions"
          :aria-label="t('描边线型')"
          data-ms-border-style
          @update:model-value="(value) => patch({ borderStyle: value as MessageStreamBorderStyle })"
        />
      </label>
      <label class="ms-field">
        <span class="ms-field-label">{{ t("粗细") }}</span>
        <UiSelect
          :model-value="String(settings.borderWidth)"
          :options="borderWidthOptions"
          :aria-label="t('描边粗细')"
          :disabled="borderWidthLocked"
          data-ms-border-width
          @update:model-value="(value) => patch({ borderWidth: Number(value) })"
        />
      </label>
      <p v-if="borderWidthLocked" class="ms-hint" data-ms-border-width-locked>
        {{ borderWidthLockedHint }}
      </p>

      <label class="ms-field">
        <span class="ms-field-label">{{ t("描边颜色") }}</span>
        <div class="ms-color-row">
          <button
            v-for="swatch in borderSwatches"
            :key="swatch.value"
            type="button"
            class="ms-swatch"
            :class="{ 'is-active': settings.borderColor === swatch.value }"
            :style="{ background: swatch.preview }"
            :title="swatch.label"
            :aria-label="swatch.label"
            @click="patch({ borderColor: swatch.value })"
          />
          <input
            class="ms-input ms-input--color"
            type="text"
            :value="settings.borderColor"
            :placeholder="t('跟随主题')"
            data-ms-border-color
            @input="patch({ borderColor: ($event.target as HTMLInputElement).value })"
          />
        </div>
      </label>

      <label class="ms-field">
        <span class="ms-field-label">{{ t("填充") }}</span>
        <UiSelect
          :model-value="settings.fillPreset"
          :options="fillOptions"
          :aria-label="t('填充预设')"
          data-ms-fill-preset
          @update:model-value="(value) => patch({ fillPreset: value as MessageStreamFillPreset })"
        />
      </label>
      <label v-if="settings.fillPreset === 'custom'" class="ms-field">
        <span class="ms-field-label">{{ t("自定义填充色") }}</span>
        <input
          class="ms-input"
          type="text"
          :value="settings.fillColor"
          placeholder="#8b5cf6 / rgb(139, 92, 246)"
          data-ms-fill-color
          @input="patch({ fillColor: ($event.target as HTMLInputElement).value })"
        />
      </label>
      <SundayRange
        :model-value="settings.fillAlpha"
        :min="0"
        :max="100"
        :step="5"
        :label="t('透明度')"
        suffix="%"
        data-ms-fill-alpha
        @update:model-value="(value) => patch({ fillAlpha: value })"
      />
      <div class="ms-field ms-field--row">
        <span class="ms-field-label">{{ t("毛玻璃") }}</span>
        <SundaySwitch
          :model-value="settings.blur"
          :label="t('毛玻璃背景')"
          data-ms-blur
          @update:model-value="(value: boolean) => patch({ blur: value })"
        >
          {{ settings.blur ? t("开启") : t("关闭") }}
        </SundaySwitch>
      </div>
    </article>

    <!-- ── 色彩主题与流光 ── -->
    <article class="setting-card ms-group">
      <div class="ms-group-head">
        <strong>{{ t("色彩主题与流光") }}</strong>
        <span>{{ t("单色跟随主色或自定义；幻彩主题按浅色 / 深色自动切换色阶。") }}</span>
      </div>

      <label class="ms-field">
        <span class="ms-field-label">{{ t("色彩主题") }}</span>
        <UiSelect
          :model-value="colorThemeValue"
          :options="colorThemeOptions"
          :aria-label="t('色彩主题')"
          data-ms-color-theme
          @update:model-value="onColorThemeChange"
        />
      </label>
      <label v-if="colorThemeValue === 'mono-custom'" class="ms-field">
        <span class="ms-field-label">{{ t("自定义单色") }}</span>
        <input
          class="ms-input"
          type="text"
          :value="settings.monoColor"
          placeholder="#8b5cf6"
          data-ms-mono-color
          @input="patch({ monoColor: ($event.target as HTMLInputElement).value })"
        />
      </label>
      <p v-if="settings.colorTheme === 'chromatic'" class="ms-hint" data-ms-chromatic-hint>
        {{ themeMode === 'dark'
          ? t("深色模式：自动使用低明度的 Muted / Neon-Dark 色阶。")
          : t("浅色模式：自动使用高饱和通透的 Vibrant 色阶。") }}
      </p>

      <div class="ms-field ms-field--row">
        <span class="ms-field-label">{{ t("流光动效") }}</span>
        <SundaySwitch
          :model-value="settings.shimmer"
          :label="t('边缘流光动效')"
          data-ms-shimmer
          @update:model-value="(value: boolean) => patch({ shimmer: value })"
        >
          {{ settings.shimmer ? t("开启") : t("关闭") }}
        </SundaySwitch>
      </div>
      <label v-if="settings.shimmer" class="ms-field">
        <span class="ms-field-label">{{ t("流光范围") }}</span>
        <UiSelect
          :model-value="settings.shimmerScope"
          :options="shimmerScopeOptions"
          :aria-label="t('流光范围')"
          data-ms-shimmer-scope
          @update:model-value="(value) => patch({ shimmerScope: value as MessageStreamShimmerScope })"
        />
      </label>
    </article>

    <!-- user:“底部要有「导出样式 JSON」和「恢复默认」按钮”+(再加「导入」入口；
         反馈一律行内文本，不弹 alert。) -->
    <footer class="ms-footer">
      <div class="ms-footer-actions">
        <button class="btn btn--quiet" type="button" data-ms-export @click="exportJson">
          {{ exportLabel }}
        </button>
        <button class="btn btn--quiet" type="button" data-ms-import @click="openImport">
          {{ t("导入样式 JSON") }}
        </button>
        <button
          v-if="!resetArmed"
          class="btn btn--quiet"
          type="button"
          data-ms-reset
          @click="resetArmed = true"
        >{{ t("恢复默认") }}</button>
        <template v-else>
          <button class="btn btn--danger" type="button" data-ms-reset-confirm @click="resetAll">
            {{ t("确认恢复默认") }}
          </button>
          <button class="btn btn--quiet" type="button" data-ms-reset-cancel @click="resetArmed = false">
            {{ t("取消") }}
          </button>
        </template>
      </div>

      <p v-if="importOk" class="ms-hint ms-hint--ok" data-ms-import-ok>{{ importOk }}</p>

      <div v-if="importOpen" class="ms-import" data-ms-import-panel>
        <label class="ms-field">
          <span class="ms-field-label">{{ t("粘贴样式 JSON") }}</span>
          <textarea
            ref="importTextareaEl"
            class="ms-input ms-import-text"
            rows="4"
            :value="importText"
            :placeholder="t('粘贴导出的消息流样式 JSON')"
            data-ms-import-text
            @input="importText = ($event.target as HTMLTextAreaElement).value"
          ></textarea>
        </label>
        <p v-if="importError" class="ms-hint ms-hint--error" data-ms-import-error>{{ importError }}</p>
        <div class="ms-footer-actions">
          <button class="btn btn--quiet" type="button" data-ms-import-file @click="pickImportFile">
            {{ t("选择 .json 文件") }}
          </button>
          <button class="btn btn--primary" type="button" data-ms-import-apply @click="applyImport">
            {{ t("应用") }}
          </button>
          <button class="btn btn--quiet" type="button" data-ms-import-cancel @click="closeImport">
            {{ t("取消") }}
          </button>
        </div>
        <input
          ref="importFileEl"
          class="ms-import-file"
          type="file"
          accept=".json,application/json"
          data-ms-import-file-input
          @change="onImportFile"
        />
      </div>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref } from 'vue'
import { t } from '@/i18n/index.ts'
import SundayRange from '@/components/SundayRange.vue'
import SundaySwitch from '@/components/SundaySwitch.vue'
import UiSelect from '@/components/UiSelect.vue'
import { copyText } from '@/helpers/clipboard.ts'
import {
  DEFAULT_MESSAGE_STREAM,
  exportMessageStreamJson,
  importMessageStreamJson,
  isNestedCardConflict,
  messageStreamCssVars,
  messageStreamRootAttrs,
  normalizeMessageStream,
  type MessageStreamBodyContainer,
  type MessageStreamBorderStyle,
  type MessageStreamColorTheme,
  type MessageStreamFillPreset,
  type MessageStreamFontKey,
  type MessageStreamInheritFontKey,
  type MessageStreamSettings,
  type MessageStreamShimmerScope,
  type MessageStreamTitleContainer,
} from '@/helpers/messageStreamStyle.ts'

defineOptions({ name: 'MessageStreamSettings' })

const props = withDefaults(defineProps<{
  settings?: MessageStreamSettings
  /** 与 effectiveThemeMode 同步，幻彩主题靠它切色阶。 */
  themeMode?: 'light' | 'dark'
}>(), {
  settings: () => ({ ...DEFAULT_MESSAGE_STREAM }),
  themeMode: 'light',
})

const emit = defineEmits<{
  'update:settings': [value: MessageStreamSettings]
}>()

/** 任何一次改动都先夹紧再上交，脏值不会流进全局变量。 */
const settings = computed(() => normalizeMessageStream(props.settings))
const themeMode = computed<'light' | 'dark'>(() => (props.themeMode === 'dark' ? 'dark' : 'light'))

function patch(partial: Partial<MessageStreamSettings>): void {
  emit('update:settings', normalizeMessageStream({ ...settings.value, ...partial }))
}

// ── 预览：与真实界面消费同一套变量与属性 ──────────────────────────
const previewVars = computed(() => messageStreamCssVars(settings.value, { themeMode: themeMode.value }))
const previewAttrs = computed(() => messageStreamRootAttrs(settings.value, themeMode.value))
const nestedCard = computed(() => isNestedCardConflict(settings.value))
const previewLines = computed(() => Array.from({ length: Math.min(settings.value.procLines1, 5) }, (_, i) => i + 1))

// ── 互斥联动 ────────────────────────────────────────────────────
const fontOptions = computed(() => [
  { value: 'system', label: t('系统默认') },
  { value: 'sans', label: t('无衬线') },
  { value: 'serif', label: t('衬线') },
  { value: 'mono', label: t('等宽') },
  { value: 'custom', label: t('自定义字体名') },
])
const inheritFontOptions = computed(() => [
  { value: 'inherit', label: t('继承正文') },
  ...fontOptions.value,
])
const bodyContainerOptions = computed(() => [
  { value: 'none', label: t('无') },
  { value: 'bordered', label: t('边框') },
  { value: 'card', label: t('卡片') },
])
const titleContainerOptions = computed(() => [
  { value: 'none', label: t('无') },
  { value: 'bordered', label: t('边框') },
  { value: 'pill', label: t('胶囊') },
])
const borderStyleOptions = computed(() => [
  { value: 'solid', label: t('实线 solid') },
  { value: 'dashed', label: t('虚线 dashed') },
  { value: 'dotted', label: t('点线 dotted') },
])
const borderWidthOptions = computed(() => [
  { value: '1', label: '1px' },
  { value: '1.5', label: '1.5px' },
  { value: '2', label: '2px' },
  { value: '3', label: '3px' },
])
const fillOptions = computed(() => [
  { value: 'surface', label: t('默认表面色') },
  { value: 'accent', label: t('主色微 tint') },
  { value: 'neutral', label: t('中性灰') },
  { value: 'custom', label: t('自定义 HEX / RGB') },
])
const borderSwatches = computed(() => [
  { value: '', label: t('跟随主题'), preview: 'color-mix(in srgb, currentColor 22%, transparent)' },
  { value: '#8b5cf6', label: t('紫'), preview: '#8b5cf6' },
  { value: '#79bcff', label: t('蓝'), preview: '#79bcff' },
  { value: '#32d17d', label: t('绿'), preview: '#32d17d' },
  { value: '#ff9142', label: t('橙'), preview: '#ff9142' },
  { value: '#f5555d', label: t('红'), preview: '#f5555d' },
])
const shimmerScopeOptions = computed(() => [
  { value: 'running', label: t('仅生成中 / 执行中') },
  { value: 'always', label: t('常驻') },
])

/** 三个容器全选「无」时，描边/填充这一整块没有意义，收起。 */
const stylePanelVisible = computed(() => (
  settings.value.bodyContainer !== 'none'
  || settings.value.procTitleContainer !== 'none'
  || settings.value.procBodyContainer !== 'none'
))

/** user:“胶囊：边框粗细强制 2px，控件置灰并提示「胶囊形态固定 2px 描边」”+(卡片同样强制 2px)。 */
const borderWidthLocked = computed(() => (
  settings.value.procTitleContainer === 'pill'
  || settings.value.bodyContainer === 'card'
  || settings.value.procBodyContainer === 'card'
))
const borderWidthLockedHint = computed(() => (
  settings.value.procTitleContainer === 'pill'
    ? t('胶囊形态固定 2px 描边')
    : t('卡片形态固定 2px 描边')
))

// ── 色彩主题：单色（跟随主色 / 自定义）与幻彩 ─────────────────────
const colorThemeValue = computed(() => {
  if (settings.value.colorTheme === 'chromatic') return 'chromatic'
  return settings.value.monoFollowAccent ? 'mono-accent' : 'mono-custom'
})
const colorThemeOptions = computed(() => [
  { value: 'mono-accent', label: t('单色 · 跟随主色') },
  { value: 'mono-custom', label: t('单色 · 自定义') },
  { value: 'chromatic', label: t('幻彩主题（自动切浅/深色阶）') },
])
function onColorThemeChange(value: string): void {
  if (value === 'chromatic') {
    patch({ colorTheme: 'chromatic' as MessageStreamColorTheme })
    return
  }
  patch({ colorTheme: 'mono' as MessageStreamColorTheme, monoFollowAccent: value === 'mono-accent' })
}

// ── 导出 / 恢复默认 ──────────────────────────────────────────────
const exportLabel = ref(t('导出样式 JSON'))
let exportTimer: ReturnType<typeof setTimeout> | null = null
/** 导出走 helpers 的同一份格式（带 kind + version），不在这里另写一套。 */
async function exportJson(): Promise<void> {
  try {
    await copyText(exportMessageStreamJson(settings.value))
    exportLabel.value = t('已复制到剪贴板')
  } catch {
    exportLabel.value = t('复制失败，请重试')
  }
  if (exportTimer !== null) clearTimeout(exportTimer)
  exportTimer = setTimeout(() => { exportLabel.value = t('导出样式 JSON') }, 1800)
}
onUnmounted(() => {
  if (exportTimer !== null) clearTimeout(exportTimer)
})

/** user:“恢复默认二次确认”+(先变成「确认恢复默认」，再点才真的重置)。 */
const resetArmed = ref(false)
function resetAll(): void {
  resetArmed.value = false
  emit('update:settings', normalizeMessageStream(DEFAULT_MESSAGE_STREAM))
}

// ── 导入样式 JSON：粘贴或选文件，失败只给行内错误文本 ──────────────
const importOpen = ref(false)
const importText = ref('')
const importError = ref('')
const importOk = ref('')
const importTextareaEl = ref<HTMLTextAreaElement | null>(null)
const importFileEl = ref<HTMLInputElement | null>(null)
let importOkTimer: ReturnType<typeof setTimeout> | null = null

/** 打开导入面板并聚焦粘贴框，不弹窗。 */
async function openImport(): Promise<void> {
  importOpen.value = true
  importError.value = ''
  importOk.value = ''
  await nextTick()
  importTextareaEl.value?.focus()
}

function closeImport(): void {
  importOpen.value = false
  importError.value = ''
  importText.value = ''
}

function pickImportFile(): void {
  importFileEl.value?.click()
}

async function onImportFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    importText.value = await file.text()
    importError.value = ''
  } catch {
    importError.value = t('读取文件失败，请重试')
  } finally {
    // 清掉选中值，同一个文件可以再选一次。
    input.value = ''
  }
}

/** user:“走 importMessageStreamJson()，成功后应用配置并给一次性成功反馈，失败显示可读错误” */
function applyImport(): void {
  try {
    const next = importMessageStreamJson(importText.value)
    importError.value = ''
    importOk.value = t('已应用导入的样式')
    importOpen.value = false
    importText.value = ''
    emit('update:settings', next)
  } catch (cause) {
    importOk.value = ''
    importError.value = cause instanceof Error ? cause.message : t('导入失败：内容无法解析')
    return
  }
  if (importOkTimer !== null) clearTimeout(importOkTimer)
  importOkTimer = setTimeout(() => { importOk.value = '' }, 2400)
}

onUnmounted(() => {
  if (importOkTimer !== null) clearTimeout(importOkTimer)
})
</script>

<style scoped>
.message-stream-settings {
  display: grid;
  gap: var(--space-3);
  container-type: inline-size;
}

.ms-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-2);
}

.ms-head h2 {
  margin: 0;
  font-size: var(--type-lg);
}

.ms-head p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: var(--type-md);
}

.ms-head-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

/* ── 预览 ── */
.ms-preview-shell {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 3%, transparent);
}

.ms-preview-caption {
  color: var(--muted);
  font-size: var(--type-sm);
  letter-spacing: 0.04em;
}

.ms-preview {
  display: grid;
  gap: var(--space-3);
  min-width: 0;
}

.ms-preview-body {
  min-width: 0;
  padding: 2px 4px;
}

.ms-preview-body p {
  margin: 0;
  font-family: var(--ms-body-font-family);
  font-size: var(--ms-body-font-size);
  line-height: var(--ms-body-line-height);
}

.ms-preview-body p + p {
  margin-top: var(--ms-body-para-gap);
}

/* 容器：无 = 只有文本和基础内边距 */
.ms-preview-body.is-bordered,
.ms-proc-body.is-bordered,
.ms-proc-title.is-bordered {
  border: var(--ms-proc-border-width-bordered) var(--ms-proc-border-style) var(--ms-proc-border-color);
  border-radius: var(--ms-proc-radius-sm);
  background: transparent;
  padding: var(--space-2) var(--space-3);
}

/* 卡片：独立背景填充 + 投影/描边，圆角 10~12px，描边固定 2px */
.ms-preview-body.is-card,
.ms-proc-body.is-card {
  border: var(--ms-proc-border-width) var(--ms-proc-border-style) var(--ms-proc-border-color);
  border-radius: var(--ms-proc-radius-lg);
  background-color: color-mix(in srgb, var(--ms-proc-fill-color) var(--ms-proc-fill-alpha), transparent);
  background-image: var(--ms-proc-fill-gradient);
  box-shadow: var(--shadow-md, 0 8px 24px rgba(0, 0, 0, 0.18));
  padding: var(--space-2) var(--space-3);
  backdrop-filter: var(--ms-proc-blur);
}

/* 嵌套卡片降级：内层用降了一级的填充 */
.ms-preview.is-nested .ms-proc-body.is-card {
  background-color: color-mix(in srgb, var(--ms-proc-fill-color-inner) var(--ms-proc-fill-alpha-inner), transparent);
}

/* 胶囊：仅限单行过程行标题，圆角 9999px */
.ms-proc-title.is-pill {
  border: var(--ms-proc-border-width) solid var(--ms-proc-border-color);
  border-radius: 9999px;
  background-color: color-mix(in srgb, var(--ms-proc-fill-color) var(--ms-proc-fill-alpha), transparent);
  background-image: var(--ms-proc-fill-gradient);
  padding: 2px var(--space-3);
}

.ms-preview-proc {
  display: grid;
  gap: var(--space-2);
  min-width: 0;
}

.ms-proc-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: calc(var(--ms-proc-title-font-size) * 1.8);
  min-width: 0;
  padding: 2px 4px;
  /* 固定单行垂直居中 */
  white-space: nowrap;
}

.ms-proc-title-icon {
  flex: none;
  font-size: var(--ms-proc-title-font-size);
  color: var(--muted);
}

.ms-proc-title-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--ms-proc-title-font-family);
  font-size: var(--ms-proc-title-font-size);
  line-height: 1;
}

.ms-proc-group {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
}

.ms-proc-body {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
  padding: var(--ms-proc-body-pad-y) 4px;
}

.ms-proc-body-inner {
  overflow: hidden;
  max-height: var(--ms-proc-height-1);
}

.ms-proc-line {
  margin: 0;
  font-family: var(--ms-proc-body-font-family);
  font-size: var(--ms-proc-body-font-size);
  line-height: var(--ms-proc-body-line-height);
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ms-proc-body-more {
  color: var(--faint, var(--muted));
  font-size: var(--type-2xs);
}

/* 流光预览：与 message-stream.css 里 .ms-shimmer-edge 同一套效果。
   真实界面靠 :root[data-ms-shimmer]，预览的属性挂在 .ms-preview 上，所以这里再声明一遍。 */
.ms-preview[data-ms-shimmer="1"] .ms-shimmer-edge {
  position: relative;
}

.ms-preview[data-ms-shimmer="1"] .ms-shimmer-edge::after {
  content: "";
  position: absolute;
  inset: 0;
  z-index: 1;
  border-radius: inherit;
  padding: var(--ms-proc-border-width, 2px);
  background-image: linear-gradient(
    100deg,
    transparent 34%,
    var(--ms-proc-shimmer-color) 50%,
    transparent 66%
  );
  background-repeat: no-repeat;
  background-size: 240% 100%;
  -webkit-mask-image: linear-gradient(#000 0 0), linear-gradient(#000 0 0);
  -webkit-mask-clip: content-box, border-box;
  -webkit-mask-composite: xor;
  mask-image: linear-gradient(#000 0 0), linear-gradient(#000 0 0);
  mask-clip: content-box, border-box;
  mask-composite: exclude;
  opacity: 0;
  pointer-events: none;
  animation: ms-shimmer-flow 3.2s linear infinite;
  animation-play-state: paused;
}

/* 边框模式的描边只有 1/1.5/2/3，流光环厚度跟着它走。 */
.ms-preview[data-ms-shimmer="1"] .ms-shimmer-edge.is-bordered::after {
  padding: var(--ms-proc-border-width-bordered, 1px);
}

.ms-preview[data-ms-shimmer="1"][data-ms-shimmer-scope="always"] .ms-shimmer-edge::after,
.ms-preview[data-ms-shimmer="1"][data-ms-shimmer-scope="running"] .ms-shimmer-edge[data-ms-running="1"]::after {
  opacity: 1;
  animation-play-state: running;
}

@media (prefers-reduced-motion: reduce) {
  .ms-preview[data-ms-shimmer="1"] .ms-shimmer-edge::after {
    animation: none;
    opacity: 0;
  }
}

/* ── 控件区 ── */
.ms-group {
  gap: var(--space-2);
}

.ms-group-head {
  display: grid;
  gap: 3px;
}

.ms-group-head strong {
  font-size: var(--type-base);
}

.ms-group-head span {
  color: var(--muted);
  font-size: var(--type-sm);
}

.ms-field {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
}

.ms-field--row {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
}

.ms-field-label {
  color: var(--muted);
  font-size: var(--type-sm);
}

.ms-input {
  width: 100%;
  min-height: 32px;
  padding: 0 var(--space-2);
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--theme-control-text, #f4f1ec)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, var(--theme-control-solid, #242424)) 70%, transparent);
  color: var(--settings-control-text, var(--theme-control-text, #f4f1ec));
  font-size: var(--type-md);
}

.ms-color-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.ms-swatch {
  width: 22px;
  height: 22px;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 22%, transparent);
  border-radius: 50%;
  cursor: pointer;
}

.ms-swatch.is-active {
  outline: var(--focus-ring-width) solid var(--focus-ring-color);
  outline-offset: var(--focus-ring-offset);
}

.ms-input--color {
  flex: 1 1 120px;
  min-width: 96px;
}

.ms-hint {
  margin: 0;
  color: var(--muted);
  font-size: var(--type-sm);
}

.ms-hint--warn {
  color: color-mix(in srgb, var(--orange, #ff9142) 76%, var(--settings-main-text, #fff));
}

.ms-hint--ok {
  color: var(--green, #32d17d);
}

.ms-hint--error {
  color: var(--red, #f5555d);
}

.ms-footer {
  display: grid;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
}

.ms-footer-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.ms-import {
  display: grid;
  gap: var(--space-2);
}

.ms-import-text {
  min-height: 88px;
  padding: var(--space-2);
  font-family: var(--font-mono, Consolas, monospace);
  resize: vertical;
}

.ms-import-file {
  display: none;
}

/* 窄容器自动改上下堆叠 */
@container (max-width: 520px) {
  .ms-field--row {
    grid-template-columns: minmax(0, 1fr);
    justify-items: start;
  }
}
</style>
