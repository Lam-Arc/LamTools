<template>
  <div class="guide-story-art" :class="'guide-story-art--' + scene" aria-hidden="true">
    <!--
      user:“可用three js/blender/SVG等方式，不做限制”+
      (全部用内联 SVG 画：不引外部图片、不增加体积，也能跟着主题换明暗。
       图形刻意简单：一个发光的点代表我，圆环和连线代表流程，读者不需要
       看懂装饰，只要有个“它在陪着我讲”的感觉就够。)
    -->
    <svg viewBox="0 0 320 176" fill="none" role="presentation">
      <defs>
        <radialGradient :id="`${uid}-glow`" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="currentColor" stop-opacity=".45" />
          <stop offset="70%" stop-color="currentColor" stop-opacity=".08" />
          <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
        </radialGradient>
        <linearGradient :id="`${uid}-fade`" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="currentColor" stop-opacity=".05" />
          <stop offset="50%" stop-color="currentColor" stop-opacity=".3" />
          <stop offset="100%" stop-color="currentColor" stop-opacity=".05" />
        </linearGradient>
      </defs>

      <!-- 1. 你好：一扇窗里亮起一个点 -->
      <g v-if="scene === 'welcome'">
        <rect x="46" y="30" width="228" height="116" rx="18" class="art-surface" />
        <rect x="46" y="30" width="228" height="26" rx="18" class="art-surface art-surface--bar" />
        <circle cx="62" cy="43" r="3" class="art-dot-mute" />
        <circle cx="72" cy="43" r="3" class="art-dot-mute" />
        <circle cx="82" cy="43" r="3" class="art-dot-mute" />
        <circle cx="160" cy="100" r="40" :fill="`url(#${uid}-glow)`" class="art-glow" />
        <circle cx="160" cy="100" r="12" class="art-core" />
        <circle cx="160" cy="100" r="22" class="art-ring art-ring--dash" />
        <g class="art-orbit">
          <circle cx="160" cy="70" r="2.6" class="art-spark" />
          <circle cx="193" cy="112" r="2" class="art-spark" />
          <circle cx="128" cy="116" r="1.6" class="art-spark" />
        </g>
        <path d="M112 132h40M168 132h40" :stroke="`url(#${uid}-fade)`" stroke-width="3" stroke-linecap="round" />
      </g>

      <!-- 2. 放心：盾牌 + 三道勾 -->
      <g v-else-if="scene === 'trust'">
        <circle cx="160" cy="84" r="62" :fill="`url(#${uid}-glow)`" class="art-glow" />
        <path d="M160 38l44 16v32c0 26-18 42-44 52-26-10-44-26-44-52V54l44-16z" class="art-surface" />
        <path d="M160 38l44 16v32c0 26-18 42-44 52-26-10-44-26-44-52V54l44-16z" class="art-outline" />
        <g class="art-checks">
          <path d="M142 92l10 10 20-22" class="art-check" />
        </g>
        <circle cx="112" cy="140" r="9" class="art-chip" />
        <circle cx="160" cy="148" r="9" class="art-chip" />
        <circle cx="208" cy="140" r="9" class="art-chip" />
        <path d="M119 140l4 4 7-8M167 148l4 4 7-8M215 140l4 4 7-8" class="art-check art-check--small" />
      </g>

      <!-- 3. 三步循环：说 → 做 → 问 -->
      <g v-else-if="scene === 'loop'">
        <circle cx="160" cy="88" r="66" class="art-ring art-ring--hair" />
        <path d="M120 60a58 58 0 0 1 80 0" class="art-arc" />
        <path d="M200 116a58 58 0 0 1-80 0" class="art-arc art-arc--delay" />
        <g class="art-node">
          <circle cx="160" cy="42" r="16" class="art-surface" />
          <path d="M154 42h12M160 36v12" class="art-stroke" />
        </g>
        <g class="art-node art-node--delay">
          <circle cx="208" cy="118" r="16" class="art-surface" />
          <path d="M202 118h12M202 114h12M202 122h12" class="art-stroke" />
        </g>
        <g class="art-node art-node--delay2">
          <circle cx="112" cy="118" r="16" class="art-surface" />
          <path d="M112 111v8M112 124v.5" class="art-stroke" />
        </g>
        <circle cx="160" cy="88" r="20" :fill="`url(#${uid}-glow)`" class="art-glow" />
        <circle cx="160" cy="88" r="7" class="art-core" />
      </g>

      <!-- 4. 模型：一块芯片 + 一把钥匙 -->
      <g v-else-if="scene === 'provider'">
        <circle cx="150" cy="88" r="62" :fill="`url(#${uid}-glow)`" class="art-glow" />
        <rect x="86" y="44" width="92" height="92" rx="20" class="art-surface" />
        <rect x="86" y="44" width="92" height="92" rx="20" class="art-outline" />
        <rect x="112" y="70" width="40" height="40" rx="10" class="art-chip-inner" />
        <circle cx="132" cy="90" r="6" class="art-core" />
        <path
          d="M104 44v-9M122 44v-9M140 44v-9M158 44v-9M104 136v9M122 136v9M140 136v9M158 136v9M86 62h-9M86 80h-9M86 98h-9M86 116h-9M178 62h9M178 80h9M178 98h9M178 116h9"
          class="art-pin"
        />
        <g class="art-key">
          <circle cx="222" cy="88" r="11" class="art-surface" />
          <circle cx="222" cy="88" r="3" class="art-dot" />
          <path d="M233 88h26M251 88v10M260 88v7" class="art-stroke" />
        </g>
      </g>

      <!-- 5. Ping：同心环 + 指过去的光标 -->
      <g v-else-if="scene === 'ping'">
        <circle cx="146" cy="92" r="18" :fill="`url(#${uid}-glow)`" class="art-glow" />
        <circle cx="146" cy="92" r="18" class="art-ring" />
        <g class="art-ring art-ring--spin">
          <path d="M146 92 L146 44 A48 48 0 0 1 187 68 Z" class="art-sector" />
          <path d="M146 92 L189 113 A48 48 0 0 1 146 140 Z" class="art-sector art-sector--mute" />
          <path d="M146 92 L104 71 A48 48 0 0 1 118 55 Z" class="art-sector art-sector--mute" />
        </g>
        <circle cx="146" cy="92" r="4" class="art-core" />
        <path d="M186 96l30 26-13 2-6 12-11-40z" class="art-cursor" />
      </g>

      <!-- 6. 桌宠：一只会看你的小团子 -->
      <g v-else-if="scene === 'pet'">
        <ellipse cx="160" cy="146" rx="46" ry="7" class="art-shadow" />
        <g class="art-pet">
          <path d="M124 108c0-22 16-38 36-38s36 16 36 38c0 18-12 30-36 30s-36-12-36-30z" class="art-surface" />
          <path d="M124 108c0-22 16-38 36-38s36 16 36 38c0 18-12 30-36 30s-36-12-36-30z" class="art-outline" />
          <circle cx="148" cy="104" r="3.4" class="art-core" />
          <circle cx="174" cy="104" r="3.4" class="art-core" />
          <path d="M154 118c4 4 10 4 14 0" class="art-stroke" />
          <path d="M132 84c-6-8-2-16 6-18M190 84c6-8 2-16-6-18" class="art-ear" />
        </g>
        <g class="art-bubble">
          <rect x="206" y="46" width="58" height="30" rx="12" class="art-surface" />
          <path d="M212 76l-4 10 12-10" class="art-surface" />
          <circle cx="222" cy="61" r="2.4" class="art-dot" />
          <circle cx="235" cy="61" r="2.4" class="art-dot" />
          <circle cx="248" cy="61" r="2.4" class="art-dot" />
        </g>
      </g>

      <!-- 7. 毕业：勾 + 一点点庆祝 -->
      <g v-else>
        <circle cx="160" cy="88" r="58" :fill="`url(#${uid}-glow)`" class="art-glow" />
        <circle cx="160" cy="88" r="42" class="art-surface" />
        <circle cx="160" cy="88" r="42" class="art-outline" />
        <path d="M138 90l16 16 30-34" class="art-check art-check--big" />
        <g class="art-confetti">
          <rect x="92" y="44" width="6" height="6" rx="2" class="art-chip" />
          <rect x="222" y="52" width="5" height="5" rx="2" class="art-chip" />
          <rect x="104" y="128" width="5" height="5" rx="2" class="art-chip" />
          <rect x="216" y="124" width="6" height="6" rx="2" class="art-chip" />
        </g>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import type { GuideScene } from '@/guide/types.ts'

defineProps<{ scene: GuideScene }>()

// 同一页可能重复出现同一个场景（重播），渐变 id 必须唯一，否则会串色。
const uid = ref(`guide-art-${Math.random().toString(36).slice(2, 8)}`)
</script>

<style scoped>
.guide-story-art {
  position: relative;
  display: grid;
  place-items: center;
  width: 100%;
  height: 176px;
  color: var(--text);
  border-radius: var(--radius);
  background:
    radial-gradient(120% 90% at 50% 20%, color-mix(in srgb, var(--text) 7%, transparent), transparent 70%),
    var(--theme-main-soft-background, rgba(255, 255, 255, .04));
  overflow: hidden;
}

.guide-story-art svg {
  width: min(100%, 340px);
  height: auto;
}

.art-surface {
  fill: color-mix(in srgb, var(--text) 8%, transparent);
  stroke: color-mix(in srgb, var(--text) 14%, transparent);
  stroke-width: 1;
}

.art-surface--bar {
  fill: color-mix(in srgb, var(--text) 5%, transparent);
}

.art-outline {
  fill: none;
  stroke: color-mix(in srgb, var(--text) 26%, transparent);
  stroke-width: 1.4;
}

.art-core {
  fill: var(--text);
}

.art-chip-inner {
  fill: color-mix(in srgb, var(--text) 6%, transparent);
  stroke: color-mix(in srgb, var(--text) 18%, transparent);
  stroke-width: 1.2;
}

.art-pin {
  fill: none;
  stroke: color-mix(in srgb, var(--text) 24%, transparent);
  stroke-width: 1.4;
  stroke-linecap: round;
}

.art-dot {
  fill: color-mix(in srgb, var(--text) 42%, transparent);
}

.art-dot-mute {
  fill: color-mix(in srgb, var(--text) 18%, transparent);
}

.art-shadow {
  fill: color-mix(in srgb, var(--text) 10%, transparent);
}

.art-ring {
  fill: none;
  stroke: color-mix(in srgb, var(--text) 30%, transparent);
  stroke-width: 1.4;
}

.art-ring--hair {
  stroke: color-mix(in srgb, var(--text) 12%, transparent);
}

.art-ring--dash {
  stroke-dasharray: 4 6;
  animation: art-rotate 18s linear infinite;
  transform-origin: 160px 100px;
}

.art-arc {
  stroke: color-mix(in srgb, var(--text) 26%, transparent);
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-dasharray: 120;
  stroke-dashoffset: 120;
  animation: art-draw 2.6s ease-out forwards;
}

.art-arc--delay {
  animation-delay: 1.1s;
}

.art-stroke,
.art-ear {
  fill: none;
  stroke: color-mix(in srgb, var(--text) 58%, transparent);
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.art-stroke--dash {
  stroke-dasharray: 3 5;
  stroke-width: 1.4;
}

.art-chip {
  fill: color-mix(in srgb, var(--text) 10%, transparent);
  stroke: color-mix(in srgb, var(--text) 16%, transparent);
  stroke-width: 1;
}

.art-check {
  fill: none;
  stroke: var(--green);
  stroke-width: 2.4;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-dasharray: 60;
  stroke-dashoffset: 60;
  animation: art-draw 1.4s .3s ease-out forwards;
}

.art-check--small {
  stroke-width: 1.8;
}

.art-check--big {
  stroke-width: 3;
}

.art-spark {
  fill: color-mix(in srgb, var(--text) 55%, transparent);
}

.art-sector {
  fill: color-mix(in srgb, var(--text) 16%, transparent);
  stroke: color-mix(in srgb, var(--text) 30%, transparent);
  stroke-width: 1;
}

.art-sector--mute {
  fill: color-mix(in srgb, var(--text) 6%, transparent);
}

.art-cursor {
  fill: color-mix(in srgb, var(--text) 82%, transparent);
  stroke: var(--theme-main-background, #1b1d22);
  stroke-width: 1.4;
  animation: art-nudge 2.4s ease-in-out infinite;
}

.art-orbit {
  transform-origin: 160px 100px;
  animation: art-rotate 22s linear infinite;
}

.art-glow {
  animation: art-breathe 4.4s ease-in-out infinite;
}

.art-node {
  opacity: 0;
  animation: art-in 0.6s ease-out .2s forwards;
}
.art-node--delay { animation-delay: .9s; }
.art-node--delay2 { animation-delay: 1.6s; }

.art-ring--spin {
  transform-origin: 146px 92px;
  animation: art-rotate 26s linear infinite;
}

.art-pet {
  transform-origin: 160px 130px;
  animation: art-float 4s ease-in-out infinite;
}

.art-bubble {
  animation: art-in 0.6s .6s ease-out both;
}

.art-confetti rect {
  animation: art-in 0.5s ease-out both;
}
.art-confetti rect:nth-child(2) { animation-delay: .12s; }
.art-confetti rect:nth-child(3) { animation-delay: .24s; }
.art-confetti rect:nth-child(4) { animation-delay: .36s; }

@keyframes art-rotate { to { transform: rotate(360deg); } }
@keyframes art-draw { to { stroke-dashoffset: 0; } }
@keyframes art-breathe {
  0%, 100% { opacity: .75; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.05); }
}
@keyframes art-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes art-nudge {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(-3px, -3px); }
}
@keyframes art-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}

@media (prefers-reduced-motion: reduce) {
  .guide-story-art * {
    animation: none !important;
  }
  .art-arc,
  .art-check {
    stroke-dashoffset: 0;
  }
  .art-node,
  .art-bubble,
  .art-confetti rect {
    opacity: 1;
  }
}
</style>
