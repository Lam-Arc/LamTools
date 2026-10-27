<script setup lang="ts">
import { computed } from 'vue'
import iconDark from '@ui/assets/sunday-app-icon-dark-display.png'
import iconLight from '@ui/assets/sunday-app-icon-light-display.png'
import type { SiteTheme } from '../composables/useSiteTheme'

const props = defineProps<{ theme: SiteTheme }>()
const icon = computed(() => props.theme === 'ivory' ? iconLight : iconDark)
const year = new Date().getFullYear()
</script>

<template>
  <footer class="site-footer">
    <div class="site-container site-footer-inner">
      <a class="site-brand" href="#top" aria-label="返回顶部">
        <img :src="icon" alt="" width="30" height="30" />
        <span>Sunday</span>
        <small>by LamTools</small>
      </a>
      <nav aria-label="页脚导航">
        <a href="#product">产品</a>
        <a href="#capabilities">能力</a>
        <a href="#download">下载</a>
        <!-- user:“实现这个插件，也正好实验我们的新插件架构”+(官网提供当前版本的网络插件使用说明)。 -->
        <a href="/docs/network-exploration.md">网络拓展文档</a>
      </nav>
      <p>© {{ year }} LamTools</p>
    </div>
  </footer>
</template>
