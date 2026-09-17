<script setup lang="ts">
import { ref, watch } from 'vue'
import type { SiteTheme } from '../composables/useSiteTheme'

const props = defineProps<{ theme: SiteTheme }>()
const previewFrame = ref<HTMLIFrameElement | null>(null)

function syncPreviewTheme() {
  previewFrame.value?.contentWindow?.postMessage(
    { type: 'lamtools:preview-theme', theme: props.theme },
    window.location.origin,
  )
}

// Keep one iframe document alive. Replacing its URL on every theme change
// makes browsers scroll the host page until the newly navigated frame is in
// view; a same-origin message updates the preview without moving the page.
watch(() => props.theme, syncPreviewTheme, { flush: 'post' })
</script>

<template>
  <section id="product" class="product-section">
    <div class="site-container product-heading">
      <div>
        <p class="section-label">不是效果图</p>
        <h2>你看到的，就是 Sunday。</h2>
      </div>
      <p>
        官网直接运行与桌面端同一份完整前端。这里只把数据传输层替换为本地模拟，
        不会连接真实 API，也不会向外发送内容。
      </p>
    </div>

    <div class="product-stage-wrap">
      <div class="product-stage-rail" aria-hidden="true"></div>
      <div class="product-stage" aria-label="Sunday 真实产品界面预览">
        <iframe
          ref="previewFrame"
          class="product-preview-frame"
          src="/preview.html"
          title="Sunday 真实产品界面预览"
          loading="eager"
          @load="syncPreviewTheme"
        ></iframe>
      </div>
      <div class="product-stage-meta" aria-hidden="true">
        <span>REAL PRODUCT UI</span>
        <span>LOCAL MOCK TRANSPORT</span>
      </div>
    </div>
  </section>
</template>
