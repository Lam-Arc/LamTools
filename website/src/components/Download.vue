<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDownToLine, Monitor, Smartphone } from 'lucide-vue-next'
import iconDark from '@ui/assets/sunday-app-icon-dark-display.png'
import iconLight from '@ui/assets/sunday-app-icon-light-display.png'
import type { SiteTheme } from '../composables/useSiteTheme'

const props = defineProps<{ theme: SiteTheme }>()
const icon = computed(() => props.theme === 'ivory' ? iconLight : iconDark)
const version = import.meta.env.VITE_SUNDAY_VERSION || '0.3.31'
const linuxVersion = import.meta.env.VITE_LINUX_VERSION || '0.3.17'
const downloadUrl = import.meta.env.VITE_WINDOWS_DOWNLOAD_URL || '/downloads/Sunday-latest-x64-setup.exe'
const mobileVersion = import.meta.env.VITE_SUNDAY_MOBILE_VERSION || '0.1.48'
// user:“接 GitHub release”+(安卓包走 GitHub Release 的固定地址：同一个 tag 下同名资产
// 每次构建覆盖，官网链接不用跟着版本号改，扫码之后永远是最新那一个)。
const androidDownloadUrl = import.meta.env.VITE_ANDROID_DOWNLOAD_URL
  || 'https://github.com/Lam-Arc/LamTools/releases/download/android-latest/Sunday-mobile-arm64.apk'
const androidQrUrl = import.meta.env.VITE_ANDROID_QR_URL || '/downloads/android-qr.svg'
const linuxReleaseDownloadBase = 'https://github.com/Lam-Arc/LamTools/releases/latest/download'
const linuxAppImageUrl = import.meta.env.VITE_LINUX_APPIMAGE_URL || `${linuxReleaseDownloadBase}/Sunday_${linuxVersion}_amd64.AppImage`
const linuxDebUrl = import.meta.env.VITE_LINUX_DEB_URL || `${linuxReleaseDownloadBase}/Sunday_${linuxVersion}_amd64.deb`
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
        <p>当前提供 Windows、Android 与 Linux x64 预览版。安装包与后续更新均由 LamTools 自有服务分发。</p>
      </div>
      <div class="download-action">
        <div class="download-buttons">
          <a class="site-btn site-btn-primary site-btn-download" :href="downloadUrl" download>
            <Monitor :size="20" :stroke-width="1.8" aria-hidden="true" />
            <span>
              <strong>下载 Windows 版</strong>
              <small>Sunday {{ version }} · x64</small>
            </span>
            <ArrowDownToLine :size="18" :stroke-width="1.8" aria-hidden="true" />
          </a>
          <a class="site-btn site-btn-quiet site-btn-download" :href="androidDownloadUrl" download>
            <Smartphone :size="20" :stroke-width="1.8" aria-hidden="true" />
            <span>
              <strong>下载 Android 版</strong>
              <small>Sunday Mobile {{ mobileVersion }} · APK</small>
            </span>
            <ArrowDownToLine :size="18" :stroke-width="1.8" aria-hidden="true" />
          </a>
          <a class="site-btn site-btn-quiet site-btn-download" :href="linuxAppImageUrl" download>
            <span>
              <strong>下载 Linux 版</strong>
              <small>AppImage · x64</small>
            </span>
            <ArrowDownToLine :size="18" :stroke-width="1.8" aria-hidden="true" />
          </a>
        </div>
        <div class="download-qr">
          <img :src="androidQrUrl" alt="手机扫码下载 Sunday 安卓版" width="104" height="104" loading="lazy" />
          <div>
            <strong>手机扫码安装</strong>
            <span>用手机相机扫一下就能下载 APK。装好之后在手机「远程连接」里扫码配对电脑。</span>
          </div>
        </div>
        <div class="download-linux-alt">
          <span>Debian / Ubuntu：</span>
          <a :href="linuxDebUrl" download>下载 .deb</a>
        </div>
        <p>支持 Windows、Android 与 Linux x64。macOS 暂不提供。</p>
      </div>
    </div>
  </section>
</template>
