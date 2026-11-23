<script setup lang="ts">
import { onBeforeUnmount, provide, ref } from 'vue'
import PreviewLightbox, { type PreviewResolver } from '@/preview/PreviewLightbox.vue'
import { PREVIEW_COMPOSER_KEY, type PreviewComposerPath } from '@/preview/composerBridge'
import { resolvePreviewDocument } from '@/preview/resolve'
import { htmlPreviewTarget, urlPreviewTarget } from '@/preview/target'
import { openInLightbox, resetPreviewLightbox } from '@/preview/usePreviewLightbox'

/**
 * user:“『引用』，直接将已标注/未标注则为原图直接加入输入框”+
 * (展厅没有会话输入框，缺了通道「引用」按钮就不会渲染；这里接一个只做记录的
 *  替身，让按钮在展厅里可见可点，并把收到的文件如实报出来——标注图能不能解码，
 *  一眼就能验。真实应用里接的是 LamToolsApp 的上传管线。)
 */
const referenced = ref<{ name: string; type: string; size: number; decodable: boolean } | null>(null)
provide(PREVIEW_COMPOSER_KEY, {
  canAttach: () => true,
  async attach(items: (File | PreviewComposerPath)[]) {
    const item = items[0]
    if (!item) return
    if (!(item instanceof File)) { referenced.value = { name: item.name, type: 'path', size: 0, decodable: false }; return }
    const head = new Uint8Array(await item.slice(0, 8).arrayBuffer())
    const decodable = await new Promise<boolean>(resolve => {
      const url = URL.createObjectURL(item)
      const image = new Image()
      image.onload = () => { URL.revokeObjectURL(url); resolve(image.naturalWidth > 0) }
      image.onerror = () => { URL.revokeObjectURL(url); resolve(false) }
      image.src = url
    })
    referenced.value = {
      name: item.name,
      type: item.type,
      size: item.size,
      decodable: head[0] === 0x89 && head[1] === 0x50 && decodable,
    }
  },
})

// user:“交互测试”+(灯箱只打开内存中的示例，不读取真实文件)。
function openSample() {
  openInLightbox(htmlPreviewTarget('<h1>展厅示例内容</h1><p>这是一个隔离的预览示例。</p>', '示例文档'))
}

// user:“灯箱应该配套缩放UI…默认大小自适应，左键可拖动”+
// (图片示例在内存里画一张，经注入的解析函数交给真实灯箱，仍然不碰任何真实文件)。
function sampleImageUrl(): string {
  const canvas = document.createElement('canvas')
  canvas.width = 1600
  canvas.height = 1000
  const context = canvas.getContext('2d')
  if (context) {
    const gradient = context.createLinearGradient(0, 0, 1600, 1000)
    gradient.addColorStop(0, '#2b2f3a')
    gradient.addColorStop(1, '#4a5a7a')
    context.fillStyle = gradient
    context.fillRect(0, 0, 1600, 1000)
    context.strokeStyle = 'rgba(255,255,255,0.22)'
    context.lineWidth = 2
    for (let x = 0; x <= 1600; x += 100) {
      context.beginPath(); context.moveTo(x, 0); context.lineTo(x, 1000); context.stroke()
    }
    for (let y = 0; y <= 1000; y += 100) {
      context.beginPath(); context.moveTo(0, y); context.lineTo(1600, y); context.stroke()
    }
    context.fillStyle = '#eef3fb'
    context.font = '64px system-ui, sans-serif'
    context.textAlign = 'center'
    context.textBaseline = 'middle'
    context.fillText('灯箱图片示例 1600 × 1000', 800, 500)
  }
  return canvas.toDataURL('image/png')
}

const resolveSample: PreviewResolver = (target, transport) => {
  if (target.kind === 'url' && target.url.startsWith('data:image/')) {
    return Promise.resolve({ mode: 'native', url: target.url, mime: 'image/png', title: '图片示例.png' })
  }
  return resolvePreviewDocument(target, transport)
}

function openImageSample() {
  openInLightbox(urlPreviewTarget(sampleImageUrl(), '图片示例.png'))
}

onBeforeUnmount(() => resetPreviewLightbox())
</script>

<template>
  <button type="button" class="btn btn--secondary" @click="openSample">打开示例预览</button>
  <button type="button" class="btn btn--secondary" data-gallery-image-sample @click="openImageSample">打开图片示例</button>
  <!-- 引用的回执：收到的到底是什么（名称/类型/字节数/是不是能解码的 PNG）。 -->
  <output
    v-if="referenced"
    class="btn btn--ghost"
    data-gallery-reference
    :data-name="referenced.name"
    :data-type="referenced.type"
    :data-size="referenced.size"
    :data-decodable="referenced.decodable ? 'true' : 'false'"
  >已引用：{{ referenced.name }}</output>
  <PreviewLightbox :resolver="resolveSample" />
</template>
