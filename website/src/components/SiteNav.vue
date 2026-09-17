<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDownToLine, Moon, Sun } from 'lucide-vue-next'
import iconDark from '@ui/assets/sunday-app-icon-dark-display.png'
import iconLight from '@ui/assets/sunday-app-icon-light-display.png'
import type { SiteTheme } from '../composables/useSiteTheme'

const props = defineProps<{ theme: SiteTheme }>()
defineEmits<{ 'toggle-theme': [] }>()

const icon = computed(() => props.theme === 'ivory' ? iconLight : iconDark)
</script>

<template>
  <header class="site-nav">
    <a class="site-brand" href="#top" aria-label="Sunday 首页">
      <img :src="icon" alt="" width="34" height="34" />
      <span>Sunday</span>
      <small>by LamTools</small>
    </a>

    <nav class="site-nav-links" aria-label="主导航">
      <a href="#product">产品</a>
      <a href="#capabilities">能力</a>
      <a href="#download">下载</a>
    </nav>

    <div class="site-nav-actions">
      <button
        class="theme-toggle"
        type="button"
        :aria-label="theme === 'ivory' ? '切换到石墨黑主题' : '切换到象牙白主题'"
        :title="theme === 'ivory' ? '石墨黑' : '象牙白'"
        @click="$emit('toggle-theme')"
      >
        <Moon v-if="theme === 'ivory'" :size="17" :stroke-width="1.8" aria-hidden="true" />
        <Sun v-else :size="17" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <a class="site-nav-download" href="#download">
        <ArrowDownToLine :size="16" :stroke-width="1.8" aria-hidden="true" />
        <span>下载</span>
      </a>
    </div>
  </header>
</template>
