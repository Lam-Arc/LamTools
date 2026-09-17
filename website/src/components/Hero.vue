<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { animate } from 'animejs'
import { ArrowDown, ArrowDownToLine } from 'lucide-vue-next'
import iconDark from '@ui/assets/sunday-app-icon-dark-display.png'
import iconLight from '@ui/assets/sunday-app-icon-light-display.png'
import type { SiteTheme } from '../composables/useSiteTheme'

const props = defineProps<{ theme: SiteTheme }>()
const icon = computed(() => props.theme === 'ivory' ? iconLight : iconDark)
const hero = ref<HTMLElement | null>(null)

onMounted(() => {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || !hero.value) return
  animate(hero.value.querySelectorAll('[data-hero-enter]'), {
    opacity: [0, 1],
    translateY: [24, 0],
    duration: 760,
    delay: (_el, index) => 80 + index * 90,
    easing: 'outQuint',
  })
  animate(hero.value.querySelector('.hero-icon'), {
    opacity: [0, 1],
    scale: [0.88, 1],
    rotate: [-3, 0],
    duration: 980,
    delay: 160,
    easing: 'outExpo',
  })
})
</script>

<template>
  <section id="top" ref="hero" class="hero-section">
    <div class="hero-grid">
      <div class="hero-copy">
        <p class="hero-signature" data-hero-enter>Sunday <span>by LamTools</span></p>
        <h1 data-hero-enter>让复杂任务，<br />自己向前走。</h1>
        <p class="hero-summary" data-hero-enter>
          一站式 AI 工作台。会话、推理、工具调用与长期任务，
          都在一个可观察、可中断的本地空间里完成。
        </p>
        <div class="hero-actions" data-hero-enter>
          <a class="site-btn site-btn-primary site-btn-lg" href="#download">
            <ArrowDownToLine :size="18" :stroke-width="1.8" aria-hidden="true" />
            下载 Windows 版
          </a>
          <a class="site-btn site-btn-quiet site-btn-lg" href="#product">直接看产品</a>
        </div>
        <ul class="hero-facts" data-hero-enter aria-label="产品特点">
          <li>本地运行</li>
          <li>过程可见</li>
          <li>中断可恢复</li>
        </ul>
      </div>

      <div class="hero-mark" aria-hidden="true">
        <span class="hero-spectrum"></span>
        <img class="hero-icon" :src="icon" alt="" />
        <span class="hero-orbit hero-orbit-one"></span>
        <span class="hero-orbit hero-orbit-two"></span>
      </div>
    </div>

    <a class="hero-down" href="#product" aria-label="查看真实产品界面">
      <span>真实界面就在下面</span>
      <ArrowDown :size="16" :stroke-width="1.8" aria-hidden="true" />
    </a>
  </section>
</template>
