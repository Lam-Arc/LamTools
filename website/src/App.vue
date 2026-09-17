<script setup lang="ts">
import SiteNav from './components/SiteNav.vue'
import Hero from './components/Hero.vue'
import Showcase from './components/Showcase.vue'
import Features from './components/Features.vue'
import Download from './components/Download.vue'
import SiteFooter from './components/SiteFooter.vue'
import { useSiteTheme } from './composables/useSiteTheme'

const { theme, toggle } = useSiteTheme()
</script>

<template>
  <SiteNav :theme="theme" @toggle-theme="toggle" />
  <main>
    <Hero :theme="theme" />
    <Showcase :theme="theme" />
    <Features />
    <Download :theme="theme" />
  </main>
  <SiteFooter :theme="theme" />
</template>

<style>
/* 官网专用：双主题品牌层；Core UI 样式仅在 iframe 预览文档中加载。 */
@import './styles/sections.css';
</style>
