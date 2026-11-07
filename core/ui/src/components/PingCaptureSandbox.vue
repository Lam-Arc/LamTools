<script setup lang="ts">
/**
 * Ping 截图标注安全沙盒。
 *
 * user:“默认使用用户选择的示例图片（或工作台内模拟画布），复用正式
 * CaptureEditor 的选区/标注/导出逻辑；不创建全屏置顶层，不拦截系统鼠标，
 * 不发送消息。”+
 * (这里只把示例帧交给正式编辑器；发送按钮只生成本地导出结果摘要。)
 */
import { onMounted, ref } from 'vue'
import CaptureEditor, { type CaptureSelectionMeta } from '@/pet/ui/CaptureEditor.vue'
import type { CapturedFrame } from '@/pet/bridge.ts'

const frame = ref<CapturedFrame | null>(null)
const result = ref('')
const error = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

/** 画一张看起来像桌面的示例图，让框选/箭头/文字工具都有真实内容可标。 */
function sampleFrame(width = 1200, height = 720): CapturedFrame {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('无法创建示例画布')
  const gradient = context.createLinearGradient(0, 0, width, height)
  gradient.addColorStop(0, '#1d2736')
  gradient.addColorStop(1, '#0d1219')
  context.fillStyle = gradient
  context.fillRect(0, 0, width, height)
  context.fillStyle = 'rgba(255,255,255,0.06)'
  for (let x = 0; x < width; x += 48) context.fillRect(x, 0, 1, height)
  for (let y = 0; y < height; y += 48) context.fillRect(0, y, width, 1)
  // 模拟一个应用窗口，方便标注“这里”“这个按钮”。
  context.fillStyle = '#f5f7fb'
  context.fillRect(150, 120, 700, 430)
  context.fillStyle = '#dfe6f2'
  context.fillRect(150, 120, 700, 42)
  context.fillStyle = '#202a38'
  context.font = '600 20px system-ui, sans-serif'
  context.fillText('示例窗口 · 需要标注的区域', 180, 149)
  context.fillStyle = '#8b97a8'
  context.font = '16px system-ui, sans-serif'
  for (let index = 0; index < 7; index += 1) {
    context.fillRect(190, 200 + index * 44, 420 - (index % 3) * 30, 12)
  }
  context.fillStyle = '#6aa8ff'
  context.beginPath()
  context.roundRect(560, 470, 190, 48, 8)
  context.fill()
  context.fillStyle = '#fff'
  context.font = '600 18px system-ui, sans-serif'
  context.fillText('示例按钮', 610, 501)
  context.fillStyle = '#1b2430'
  context.fillRect(900, 170, 230, 300)
  context.fillStyle = '#8fd6ff'
  context.font = '14px system-ui, sans-serif'
  context.fillText('侧栏 / 可标注', 925, 205)
  const image = context.getImageData(0, 0, width, height)
  return {
    width,
    height,
    x: 0,
    y: 0,
    scale: 1,
    data: image.data,
    capturedAt: Date.now(),
  }
}

function reset(): void {
  error.value = ''
  result.value = ''
  try {
    frame.value = sampleFrame()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

/** 用户本地测试图 → 截图像素；不读取真实屏幕，也不上传文件。 */
async function importTestImage(file: File): Promise<void> {
  error.value = ''
  result.value = ''
  try {
    if (!/^image\//.test(file.type)) throw new Error('请选择图片文件')
    const url = URL.createObjectURL(file)
    try {
      const image = await new Promise<HTMLImageElement>((resolve, reject) => {
        const element = new Image()
        element.onload = () => resolve(element)
        element.onerror = () => reject(new Error('图片无法解码'))
        element.src = url
      })
      const maxEdge = 2400
      const scale = Math.min(1, maxEdge / Math.max(image.naturalWidth, image.naturalHeight))
      const width = Math.max(1, Math.round(image.naturalWidth * scale))
      const height = Math.max(1, Math.round(image.naturalHeight * scale))
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const context = canvas.getContext('2d')
      if (!context) throw new Error('无法创建测试图画布')
      context.drawImage(image, 0, 0, width, height)
      const imageData = context.getImageData(0, 0, width, height)
      frame.value = {
        width,
        height,
        x: 0,
        y: 0,
        scale: 1,
        data: imageData.data,
        capturedAt: Date.now(),
      }
    } finally {
      URL.revokeObjectURL(url)
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

function onPick(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) void importTestImage(file)
}

function onSend(payload: { blob: Blob; text: string; meta: CaptureSelectionMeta }): void {
  // 绝不调用真实上传/发送；只报告导出的本地结果。
  result.value = `沙盒导出成功：${payload.meta.width}×${payload.meta.height}，${Math.round(payload.blob.size / 1024)}KB，说明「${payload.text || '无'}」。没有发送到任何会话。`
}

function onCancel(): void {
  frame.value = null
  result.value = '已退出沙盒，没有保存或发送任何内容。'
}

onMounted(reset)
</script>

<template>
  <section class="ping-capture-sandbox">
    <header>
      <div>
        <h3>截图标注沙盒</h3>
        <p>复用正式框选/标注/导出逻辑；不会创建全屏窗口，也不会发送到 Agent。</p>
      </div>
      <div class="ping-capture-sandbox__actions">
        <input ref="fileInput" type="file" accept="image/*" hidden @change="onPick">
        <button type="button" class="btn btn--ghost" @click="fileInput?.click()">导入测试图</button>
        <button type="button" class="btn btn--ghost" @click="reset">重置示例图</button>
      </div>
    </header>
    <CaptureEditor
      v-if="frame"
      :frame="frame"
      :busy="false"
      :error="error"
      sandbox
      @cancel="onCancel"
      @send="onSend"
    />
    <div v-else class="ping-capture-sandbox__empty">
      <button type="button" class="btn" @click="reset">打开示例截图</button>
      <button type="button" class="btn btn--ghost" @click="fileInput?.click()">导入本地测试图</button>
    </div>
    <p v-if="result" class="ping-capture-sandbox__result">{{ result }}</p>
  </section>
</template>

<style scoped>
.ping-capture-sandbox {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel, var(--surface, transparent));
}
.ping-capture-sandbox header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.ping-capture-sandbox h3 {
  margin: 0 0 3px;
  font-size: 14px;
}
.ping-capture-sandbox p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}
.ping-capture-sandbox__empty {
  display: grid;
  place-items: center;
  min-height: 180px;
  border: 1px dashed var(--border);
  border-radius: 8px;
}
.ping-capture-sandbox__result {
  padding: 7px 9px;
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--success, #4f9d69) !important;
}
</style>
