<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDownToLine, Monitor } from 'lucide-vue-next'
import iconDark from '@ui/assets/sunday-app-icon-dark-display.png'
import iconLight from '@ui/assets/sunday-app-icon-light-display.png'
import type { SiteTheme } from '../composables/useSiteTheme'

const props = defineProps<{ theme: SiteTheme }>()
const icon = computed(() => props.theme === 'ivory' ? iconLight : iconDark)
const version = import.meta.env.VITE_SUNDAY_VERSION || '0.3.3'
const downloadUrl = import.meta.env.VITE_WINDOWS_DOWNLOAD_URL || '/downloads/Sunday-latest-x64-setup.exe'
</script>

<template>
  <section id="download" class="download-section">
    <div class="site-container download-layout">
      <div class="download-mark">
        <img :src="icon" alt="Sunday 应用图标" width="144" height="144" />
      </div>
      <div class="download-copy">
        <p class="section-label">准备开始</p>
        <h2>把 Sunday 带回你的电脑。</h2>
        <p>当前提供 Windows 预览版。安装包与后续更新均由 LamTools 自有服务分发。</p>
      </div>
      <div class="download-action">
        <a class="site-btn site-btn-primary site-btn-download" :href="downloadUrl" download>
          <Monitor :size="20" :stroke-width="1.8" aria-hidden="true" />
          <span>
            <strong>下载 Windows 版</strong>
            <small>Sunday {{ version }}</small>
          </span>
          <ArrowDownToLine :size="18" :stroke-width="1.8" aria-hidden="true" />
        </a>
        <p>macOS 与 Linux 版本正在准备</p>
      </div>
    </div>
  </section>
</template>
