<template>
  <section class="theme-area-card">
    <h4>{{ label }}</h4>
    <!--
      user:“色彩渐变图像作为一个 mark 节点，然后玻璃应该单独作为一个 preference 节点”+
      (填充节点只描述区域里放什么：纯色/渐变/图片；玻璃另设一个材质偏好节点。)
    -->
    <div class="theme-fill-modes" role="radiogroup" :aria-label="t('填充')">
      <button
        v-for="mode in fillModes"
        :key="mode.value"
        class="theme-fill-mode"
        :class="{ 'is-active': fillMode === mode.value }"
        type="button"
        role="radio"
        :aria-checked="fillMode === mode.value ? 'true' : 'false'"
        :data-theme-fill-mode="mode.value"
        @click="$emit('update:fill-mode', mode.value)"
      >{{ mode.label }}</button>
    </div>

    <label v-if="fillMode === 'solid'" class="field color-field">
      <span>{{ t("颜色") }}</span>
      <span>
        <input
          type="color"
          :value="solidColor"
          data-theme-solid-color
          @input="updateSolidColor(($event.target as HTMLInputElement).value)"
        />
        <input
          :value="solidColor"
          data-theme-solid-color-hex
          @change="updateSolidColor(($event.target as HTMLInputElement).value)"
        />
      </span>
    </label>

    <template v-else-if="fillMode === 'gradient'">
      <div class="gradient-stop-list">
        <div
          v-for="(stop, index) in stops"
          :key="index"
          class="gradient-stop-row"
        >
          <span>{{ index + 1 }}</span>
          <input
            v-model="stop.color"
            type="color"
            @change="$emit('sort-stops')"
          />
          <input
            v-model="stop.color"
            @change="$emit('sort-stops')"
          />
          <input
            v-model.number="stop.position"
            type="number"
            min="0"
            max="100"
            step="1"
            @change="$emit('sort-stops')"
          />
          <button
            type="button"
            :disabled="stops.length <= 1"
            @click="$emit('remove-stop', index)"
          >{{ t("删") }}</button>
        </div>
        <button
          class="btn btn--secondary"
          type="button"
          :disabled="stops.length >= 8"
          @click="$emit('add-stop')"
        >{{ t("+ 添加节点") }}</button>
      </div>
      <label class="field width-field">
        <span>{{ t("渐变角度") }}<em>{{ angle }}deg</em></span>
        <div class="width-control">
          <SundayRange
            bare
            :model-value="angleModel"
            :min="0"
            :max="360"
            :step="5"
            :label="t('渐变角度')"
            @update:model-value="angleModel = Number($event)"
          />
          <input
            v-model.number="angleModel"
            type="number"
            min="0"
            max="360"
            step="5"
          />
        </div>
      </label>
    </template>

    <template v-else>
      <div class="theme-image-row">
        <!-- user:“添加图片应该是一个按钮。如果成功添加图片之后，该按钮应换成图片的小号预览” -->
        <button
          class="btn btn--secondary theme-image-chip"
          :class="{ 'has-thumb': Boolean(image) }"
          type="button"
          data-theme-pick-image
          :aria-label="image ? t('更换图片') : t('选择图片')"
          @click="pickImage"
        >
          <img v-if="image" :src="image" alt="" data-theme-image-preview />
          <span v-else>{{ t("选择图片") }}</span>
        </button>
        <button
          v-if="image"
          class="btn btn--secondary"
          type="button"
          data-theme-clear-image
          @click="$emit('update:image', '')"
        >{{ t("清除") }}</button>
      </div>
      <!--
        user:“还有低透玻璃和高透玻璃底色是不允许放置颜色是吗”+
        (图片也可以垫一层底色：透明图会透出它，开启玻璃时它就是玻璃的着色。)
      -->
      <label class="field color-field">
        <span>{{ t("底色") }}</span>
        <span>
          <input
            type="color"
            :value="solidColor"
            data-theme-image-base-color
            @input="updateSolidColor(($event.target as HTMLInputElement).value)"
          />
          <input
            :value="solidColor"
            data-theme-image-base-color-hex
            @change="updateSolidColor(($event.target as HTMLInputElement).value)"
          />
        </span>
      </label>
      <label class="field theme-image-fit-field">
        <span>{{ t("适应方式") }}</span>
        <select
          :value="imageFit"
          class="theme-image-fit"
          data-theme-image-fit
          @change="$emit('update:image-fit', ($event.target as HTMLSelectElement).value as ThemeImageFit)"
        >
          <option v-for="fit in imageFits" :key="fit.value" :value="fit.value">{{ fit.label }}</option>
        </select>
      </label>
      <p class="theme-area-hint">{{ t("支持 PNG、JPEG、GIF、WebP、AVIF、SVG；动图会照常播放。") }}</p>
      <p v-if="imageError" class="theme-area-error" role="alert">{{ imageError }}</p>
      <input ref="imageInputEl" type="file" accept="image/*" hidden @change="onPickImage" />
    </template>

    <!--
      user:“玻璃应该单独作为一个 preference 节点”+
      (玻璃是表面材质，不是填充类型；关闭/高透/低透，填充分量就是它的着色内容。)
    -->
    <div class="theme-glass-preference">
      <span class="theme-glass-label">{{ t("玻璃材质") }}</span>
      <div class="theme-glass-levels" role="radiogroup" :aria-label="t('玻璃材质')">
        <button
          v-for="level in glassLevels"
          :key="level.value"
          class="theme-glass-level"
          :class="{ 'is-active': glassLevel === level.value }"
          type="button"
          role="radio"
          :aria-checked="glassLevel === level.value ? 'true' : 'false'"
          :data-theme-glass-level="level.value"
          @click="$emit('update:glass-level', level.value)"
        >{{ level.label }}</button>
      </div>
    </div>
    <p v-if="glassLevel !== 'off'" class="theme-area-hint">
      {{ t("开启后整个区域变成玻璃表面，上面的颜色、渐变或图片就是它的着色。") }}
    </p>

    <label v-if="glassLevel === 'off' && fillMode !== 'image' && showOpacity" class="field width-field">
      <span>{{ t("透明度") }}<em>{{ opacityPct }}</em></span>
      <div class="width-control">
        <SundayRange
          bare
          :model-value="opacityModel"
          :min="0.1"
          :max="1"
          :step="0.05"
          :decimals="2"
          :label="t('透明度')"
          @update:model-value="opacityModel = Number($event)"
        />
        <input
          v-model.number="opacityModel"
          type="number"
          min="0.1"
          max="1"
          step="0.05"
        />
      </div>
    </label>
    <label class="field color-field">{{ t("文本颜色") }}<span>
        <input
          v-model="textColorModel"
          type="color"
          @change="$emit('update:text-color', textColorModel)"
        />
        <input
          v-model="textColorModel"
          @change="$emit('update:text-color', textColorModel)"
        />
      </span>
    </label>
  </section>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

/**
 * ThemeAreaEditor — single theme area (backdrop/main/composer/control) editor
 *
 * 两个独立节点：填充（纯色/渐变/图片）与玻璃材质偏好（关闭/高透/低透）。
 */
import { computed, ref } from 'vue'
import type { ThemeFillMode, ThemeGlassPreference, ThemeImageFit, ThemeStop } from '@/helpers/theme.ts'
import { readThemeImageFile } from '@/helpers/themeImage.ts'
import SundayRange from '@/components/SundayRange.vue'

const props = defineProps<{
  label: string
  stops: ThemeStop[]
  angle: number
  opacity: number
  textColor: string
  showOpacity?: boolean
  fillMode: ThemeFillMode
  glassLevel: ThemeGlassPreference
  image: string
  imageFit: ThemeImageFit
}>()

const emit = defineEmits<{
  'update:stops': [stops: ThemeStop[]]
  'update:angle': [angle: number]
  'update:opacity': [opacity: number]
  'update:text-color': [color: string]
  'update:fill-mode': [mode: ThemeFillMode]
  'update:glass-level': [level: ThemeGlassPreference]
  'update:image': [dataUrl: string]
  'update:image-fit': [fit: ThemeImageFit]
  'add-stop': []
  'remove-stop': [index: number]
  'sort-stops': []
}>()

const fillModes: Array<{ value: ThemeFillMode; label: string }> = [
  { value: 'solid', get label() { return t("纯色") } },
  { value: 'gradient', get label() { return t("渐变") } },
  { value: 'image', get label() { return t("图片") } },
]
const glassLevels: Array<{ value: ThemeGlassPreference; label: string }> = [
  { value: 'off', get label() { return t("关闭") } },
  { value: 'high', get label() { return t("高透玻璃") } },
  { value: 'low', get label() { return t("低透玻璃") } },
]
const imageFits: Array<{ value: ThemeImageFit; label: string }> = [
  { value: 'cover', get label() { return t("铺满") } },
  { value: 'contain', get label() { return t("完整显示") } },
  { value: 'tile', get label() { return t("平铺") } },
  { value: 'stretch', get label() { return t("拉伸") } },
]

const angleModel = computed({
  get: () => props.angle,
  set: (val) => emit('update:angle', val),
})

const opacityModel = computed({
  get: () => props.opacity,
  set: (val) => emit('update:opacity', val),
})

const textColorModel = computed({
  get: () => props.textColor,
  set: (val) => emit('update:text-color', val),
})

const opacityPct = computed(() => `${Math.round(props.opacity * 100)}%`)
const solidColor = computed(() => props.stops[0]?.color || '#000000')

/** 纯色只编辑第一个节点；其余节点保留，切回渐变时原样恢复。 */
function updateSolidColor(value: string) {
  if (!/^#[0-9a-fA-F]{6}$/.test(value)) return
  if (!props.stops.length) {
    emit('update:stops', [{ color: value, position: 0 }])
    return
  }
  emit('update:stops', [{ ...props.stops[0], color: value }, ...props.stops.slice(1)])
}

const imageInputEl = ref<HTMLInputElement | null>(null)
const imageError = ref('')

function pickImage() {
  imageInputEl.value?.click()
}

async function onPickImage(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  imageError.value = ''
  try {
    const image = await readThemeImageFile(file)
    emit('update:image', image.dataUrl)
  } catch (error) {
    imageError.value = t(error instanceof Error ? error.message : '图片读取失败')
  }
}
</script>
