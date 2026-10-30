<template>
  <div class="assistant-avatar-field" data-assistant-avatar>
    <div class="assistant-avatar-field__row">
      <span class="assistant-avatar-field__preview" :style="previewStyle" aria-hidden="true">
        <img v-if="avatar" :src="avatar" alt="" />
        <span v-else class="assistant-avatar-field__initial">{{ fallback }}</span>
      </span>
      <div class="assistant-avatar-field__actions">
        <button
          class="btn btn--ghost"
          type="button"
          :disabled="disabled || cropOpen"
          data-avatar-pick
          @click="openFilePicker"
        >{{ avatar ? t("更换图片") : t("上传图片") }}</button>
        <button
          v-if="avatar"
          class="btn btn--ghost"
          type="button"
          :disabled="disabled || cropOpen"
          data-avatar-remove
          @click="removeAvatar"
        >{{ t("移除") }}</button>
      </div>
      <input
        ref="fileInputEl"
        type="file"
        accept="image/*"
        hidden
        data-avatar-file
        @change="onFileSelected"
      />
    </div>

    <!-- user:“助手头像那块别填链接 上传，裁切”+(选图后就在原位进入裁切：
         固定正方形预览框，拖动调位置、滑块调缩放，圆圈内即头像实际显示部分) -->
    <div v-if="cropOpen" class="assistant-avatar-field__crop" data-avatar-crop>
      <div
        class="assistant-avatar-field__frame"
        role="application"
        :aria-label="t('拖动图片调整裁切位置')"
        @pointerdown="onCropPointerDown"
        @wheel.prevent="onCropWheel"
      >
        <img
          v-if="cropDisplay"
          class="assistant-avatar-field__crop-image"
          :src="cropSrc"
          :style="cropImageStyle"
          alt=""
          draggable="false"
        />
        <span
          class="assistant-avatar-field__crop-ring"
          :style="cropRingStyle"
          aria-hidden="true"
        />
      </div>
      <div class="assistant-avatar-field__crop-side">
        <p class="assistant-avatar-field__hint">
          {{ t("拖动图片调整位置，用滑块缩放；圆圈内就是头像实际显示的部分。") }}
        </p>
        <SundayRange
          :model-value="cropZoom"
          :min="ASSISTANT_AVATAR_MIN_ZOOM"
          :max="ASSISTANT_AVATAR_MAX_ZOOM"
          :step="0.05"
          :decimals="2"
          suffix="×"
          :label="t('缩放')"
          :disabled="!cropSize"
          @update:model-value="setCropZoom"
        />
        <div class="assistant-avatar-field__crop-actions">
          <button class="btn btn--ghost" type="button" @click="closeCrop">{{ t("取消") }}</button>
          <button
            class="btn btn--primary"
            type="button"
            :disabled="!cropSize"
            data-avatar-apply
            @click="applyCrop"
          >{{ t("应用") }}</button>
        </div>
      </div>
    </div>

    <p v-if="localError" class="assistant-avatar-field__error" role="alert">{{ localError }}</p>
  </div>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, onBeforeUnmount, ref } from 'vue'
import SundayRange from '@/components/SundayRange.vue'
import {
  ASSISTANT_AVATAR_EXPORT_SIZE,
  ASSISTANT_AVATAR_MAX_ZOOM,
  ASSISTANT_AVATAR_MIN_ZOOM,
  avatarCropSourceRect,
  avatarDisplaySize,
  centeredAvatarOffset,
  clampAvatarOffset,
  rescaleAvatarOffset,
  type AvatarCropImageSize,
  type AvatarCropOffset,
} from '@/helpers/assistantAvatarCrop.ts'

const props = withDefaults(defineProps<{
  /** 当前头像（设置里的草稿值）：data URL 或旧版图片地址，空串表示首字母。 */
  avatar: string
  /** 没有头像时显示的首字母。 */
  fallback: string
  /** 头像显示边长（px），与消息区保持一致。 */
  size?: number
  /** 圆角率 0–100：100 为圆形，0 为方形。 */
  roundness?: number
  disabled?: boolean
}>(), {
  size: 28,
  roundness: 100,
  disabled: false,
})

const emit = defineEmits<{
  'change': [avatar: string]
}>()

/** 裁切框在界面上的边长（与样式保持一致）；用常量而不是量 DOM，jsdom 里也能算。 */
const CROP_FRAME_SIZE = 200
const MAX_FILE_BYTES = 12 * 1024 * 1024

const fileInputEl = ref<HTMLInputElement | null>(null)
const cropSrc = ref('')
const cropSize = ref<AvatarCropImageSize | null>(null)
const cropZoom = ref(ASSISTANT_AVATAR_MIN_ZOOM)
const cropOffset = ref<AvatarCropOffset>({ x: 0, y: 0 })
const localError = ref('')
let loadedImage: HTMLImageElement | null = null
let drag: { startX: number; startY: number; baseX: number; baseY: number } | null = null

const cropOpen = computed(() => cropSrc.value !== '')
const cropDisplay = computed(() => (
  cropSize.value ? avatarDisplaySize(CROP_FRAME_SIZE, cropSize.value, cropZoom.value) : null
))

// user:“头上头像显示大小太小了 设成可调节，裁切也是圆角率可调节”+
// (设置里的预览与裁切圈都按同一份尺寸/圆角率画，所见即消息区所得)
const previewStyle = computed<Record<string, string>>(() => {
  const size = Math.min(72, Math.max(16, props.size))
  return {
    width: `${size}px`,
    height: `${size}px`,
    borderRadius: `${props.roundness / 2}%`,
    fontSize: `${Math.max(10, Math.round(size * 0.42))}px`,
  }
})
const cropRingStyle = computed<Record<string, string>>(() => ({
  borderRadius: `${props.roundness / 2}%`,
}))

const cropImageStyle = computed<Record<string, string>>(() => {
  const display = cropDisplay.value
  if (!display) return { display: 'none' }
  const style: Record<string, string> = {
    width: `${display.width}px`,
    height: `${display.height}px`,
    transform: `translate(${cropOffset.value.x}px, ${cropOffset.value.y}px)`,
  }
  return style
})

function openFilePicker(): void {
  if (props.disabled || cropOpen.value) return
  localError.value = ''
  fileInputEl.value?.click()
}

function onFileSelected(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  // 允许再次选择同一张图片：清空 value，否则 change 不会触发。
  input.value = ''
  if (!file) return
  // 有些来源的图片 MIME 为空，按扩展名补一次判断，别把正常图片挡在门外。
  const looksLikeImage = file.type.startsWith('image/') || /\.(png|jpe?g|gif|webp|avif|bmp|svg)$/i.test(file.name)
  if (!looksLikeImage) {
    localError.value = t('请选择图片文件')
    return
  }
  if (file.size > MAX_FILE_BYTES) {
    localError.value = t('图片不能超过 12 MB')
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    const dataUrl = typeof reader.result === 'string' ? reader.result : ''
    if (!dataUrl) {
      localError.value = t('图片读取失败，请换一张再试')
      return
    }
    openCrop(dataUrl)
  }
  reader.onerror = () => {
    localError.value = t('图片读取失败，请换一张再试')
  }
  reader.readAsDataURL(file)
}

function openCrop(src: string): void {
  localError.value = ''
  closeCrop()
  cropSrc.value = src
  const image = new Image()
  image.onload = () => {
    if (cropSrc.value !== src) return
    const size = { width: image.naturalWidth || image.width, height: image.naturalHeight || image.height }
    if (size.width <= 0 || size.height <= 0) {
      localError.value = t('这张图片打不开，请换一张再试')
      closeCrop()
      return
    }
    loadedImage = image
    cropSize.value = size
    cropZoom.value = ASSISTANT_AVATAR_MIN_ZOOM
    cropOffset.value = centeredAvatarOffset(CROP_FRAME_SIZE, avatarDisplaySize(CROP_FRAME_SIZE, size, cropZoom.value))
  }
  image.onerror = () => {
    if (cropSrc.value !== src) return
    localError.value = t('这张图片打不开，请换一张再试')
    closeCrop()
  }
  image.src = src
}

function closeCrop(): void {
  stopDrag()
  cropSrc.value = ''
  cropSize.value = null
  cropZoom.value = ASSISTANT_AVATAR_MIN_ZOOM
  cropOffset.value = { x: 0, y: 0 }
  loadedImage = null
}

function setCropZoom(next: number): void {
  if (!cropSize.value) return
  const previous = avatarDisplaySize(CROP_FRAME_SIZE, cropSize.value, cropZoom.value)
  const zoom = Math.min(ASSISTANT_AVATAR_MAX_ZOOM, Math.max(ASSISTANT_AVATAR_MIN_ZOOM, next))
  cropZoom.value = zoom
  const current = avatarDisplaySize(CROP_FRAME_SIZE, cropSize.value, zoom)
  cropOffset.value = rescaleAvatarOffset(CROP_FRAME_SIZE, previous, current, cropOffset.value)
}

function onCropWheel(event: WheelEvent): void {
  if (!cropSize.value) return
  setCropZoom(cropZoom.value + (event.deltaY < 0 ? 0.1 : -0.1))
}

function onCropPointerDown(event: PointerEvent): void {
  if (!cropDisplay.value) return
  event.preventDefault()
  drag = {
    startX: event.clientX,
    startY: event.clientY,
    baseX: cropOffset.value.x,
    baseY: cropOffset.value.y,
  }
  window.addEventListener('pointermove', onCropPointerMove)
  window.addEventListener('pointerup', onCropPointerEnd, { once: true })
  window.addEventListener('pointercancel', onCropPointerEnd, { once: true })
}

function onCropPointerMove(event: PointerEvent): void {
  const display = cropDisplay.value
  if (!drag || !display) return
  cropOffset.value = clampAvatarOffset({
    x: drag.baseX + (event.clientX - drag.startX),
    y: drag.baseY + (event.clientY - drag.startY),
  }, CROP_FRAME_SIZE, display)
}

function onCropPointerEnd(): void {
  stopDrag()
}

function stopDrag(): void {
  drag = null
  window.removeEventListener('pointermove', onCropPointerMove)
  window.removeEventListener('pointerup', onCropPointerEnd)
  window.removeEventListener('pointercancel', onCropPointerEnd)
}

function removeAvatar(): void {
  localError.value = ''
  closeCrop()
  emit('change', '')
}

function applyCrop(): void {
  const image = loadedImage
  const size = cropSize.value
  if (!image || !size) {
    localError.value = t('这张图片打不开，请换一张再试')
    return
  }
  const rect = avatarCropSourceRect(CROP_FRAME_SIZE, size, cropZoom.value, cropOffset.value)
  const canvas = document.createElement('canvas')
  canvas.width = ASSISTANT_AVATAR_EXPORT_SIZE
  canvas.height = ASSISTANT_AVATAR_EXPORT_SIZE
  const context = canvas.getContext('2d')
  if (!context) {
    localError.value = t('无法处理这张图片，请换一张再试')
    return
  }
  context.drawImage(
    image,
    rect.sx,
    rect.sy,
    rect.width,
    rect.height,
    0,
    0,
    ASSISTANT_AVATAR_EXPORT_SIZE,
    ASSISTANT_AVATAR_EXPORT_SIZE,
  )
  // WebP 体积远小于 PNG；WebView 不支持编码时会按规范退回 PNG。
  let dataUrl = canvas.toDataURL('image/webp', 0.9)
  if (!dataUrl.startsWith('data:image/webp')) dataUrl = canvas.toDataURL('image/png')
  if (!dataUrl.startsWith('data:image/')) {
    localError.value = t('无法处理这张图片，请换一张再试')
    return
  }
  closeCrop()
  emit('change', dataUrl)
}

onBeforeUnmount(stopDrag)
</script>

<style scoped>
.assistant-avatar-field {
  display: grid;
  gap: var(--space-2);
}

.assistant-avatar-field__row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.assistant-avatar-field__preview {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) 12%, transparent);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) 72%, transparent);
  font-weight: 720;
  line-height: 1;
}

.assistant-avatar-field__preview img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.assistant-avatar-field__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.assistant-avatar-field__crop {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.assistant-avatar-field__frame {
  position: relative;
  flex: 0 0 auto;
  width: 200px;
  height: 200px;
  overflow: hidden;
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) 6%, transparent);
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.assistant-avatar-field__frame:active {
  cursor: grabbing;
}

.assistant-avatar-field__crop-image {
  position: absolute;
  top: 0;
  left: 0;
  max-width: none;
  transform-origin: 0 0;
  pointer-events: none;
}

/* 圆角率跟随显示偏好：100 为圆形，0 为方形；圆外压暗，避免裁到看不见的角落。 */
.assistant-avatar-field__crop-ring {
  position: absolute;
  inset: 0;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) 35%, transparent);
  box-shadow: 0 0 0 1000px color-mix(in srgb, var(--settings-main-background, var(--theme-main-background)) 62%, transparent);
  pointer-events: none;
}

.assistant-avatar-field__crop-side {
  display: grid;
  gap: var(--space-2);
  flex: 1 1 180px;
  min-width: 0;
}

.assistant-avatar-field__hint {
  margin: 0;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) 62%, transparent);
  font-size: 12px;
  line-height: 1.6;
}

.assistant-avatar-field__crop-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.assistant-avatar-field__error {
  margin: 0;
  color: var(--red);
  font-size: 12px;
  line-height: 1.6;
}
</style>
