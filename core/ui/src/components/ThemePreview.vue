<template>
  <div class="theme-preview-stage" :class="{ 'is-interactive': interactive }" :style="backdropStyle">
    <aside
      class="theme-preview-area theme-preview-area--backdrop"
      data-theme-preview-area="backdrop"
      :role="interactive ? 'button' : undefined"
      :tabindex="interactive ? 0 : undefined"
      :aria-label="interactive ? '调整背景板和侧边栏' : undefined"
      @click="selectArea('backdrop')"
      @keydown.enter.prevent="selectArea('backdrop')"
      @keydown.space.prevent="selectArea('backdrop')"
    >
      <span class="theme-preview-dot" />
      <strong>{{ productName }}</strong>
      <small>工作台</small>
      <span v-if="interactive" class="theme-preview-area-nodes" aria-hidden="true">
          <i v-for="(stop, index) in areaStops?.backdrop" :key="`${stop.color}-${index}`" :style="{ background: stop.color }" />
      </span>
    </aside>
    <main
      class="theme-preview-area theme-preview-area--main"
      data-theme-preview-area="main"
      :style="mainStyle"
      :role="interactive ? 'button' : undefined"
      :tabindex="interactive ? 0 : undefined"
      :aria-label="interactive ? '调整主界面' : undefined"
      @click="selectArea('main')"
      @keydown.enter.prevent="selectArea('main')"
      @keydown.space.prevent="selectArea('main')"
    >
      <div class="theme-preview-heading">
        <strong>主界面</strong>
        <span>···</span>
      </div>
      <span>{{ contentDescription }}</span>
      <div
        class="theme-preview-composer theme-preview-area theme-preview-area--composer"
        data-theme-preview-area="composer"
        :style="composerStyle"
        :role="interactive ? 'button' : undefined"
        :tabindex="interactive ? 0 : undefined"
        :aria-label="interactive ? '调整输入栏' : undefined"
        @click.stop="selectArea('composer')"
        @keydown.enter.stop.prevent="selectArea('composer')"
        @keydown.space.stop.prevent="selectArea('composer')"
      >
        输入栏
        <span v-if="interactive" class="theme-preview-area-nodes" aria-hidden="true">
          <i v-for="(stop, index) in areaStops?.composer" :key="`${stop.color}-${index}`" :style="{ background: stop.color }" />
        </span>
      </div>
      <button type="button" data-theme-preview-area="control" :style="controlStyle" :aria-label="interactive ? '调整控件' : undefined" @click.stop="selectArea('control')">
        控件
        <span v-if="interactive" class="theme-preview-area-nodes" aria-hidden="true">
          <i v-for="(stop, index) in areaStops?.control" :key="`${stop.color}-${index}`" :style="{ background: stop.color }" />
        </span>
      </button>
      <span v-if="interactive" class="theme-preview-area-nodes theme-preview-area-nodes--main" aria-hidden="true">
        <i v-for="(stop, index) in areaStops?.main" :key="`${stop.color}-${index}`" :style="{ background: stop.color }" />
      </span>
    </main>
  </div>
</template>

<script setup lang="ts">
import type { ThemeArea, ThemeStop } from '../helpers/theme'

const props = withDefaults(defineProps<{
  interactive?: boolean
  areaStops?: Partial<Record<ThemeArea, ThemeStop[]>>
  backdropStyle: Record<string, string>
  mainStyle: Record<string, string>
  composerStyle: Record<string, string>
  controlStyle: Record<string, string>
  productName: string
  contentDescription: string
}>(), {
  interactive: false,
  areaStops: () => ({}),
})

const emit = defineEmits<{
  'select-area': [area: ThemeArea]
}>()

function selectArea(area: ThemeArea) {
  if (props.interactive) emit('select-area', area)
}

</script>
