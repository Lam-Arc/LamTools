<template>
  <div class="full-area-column full-area-surface" :style="settingsThemeStyle">
    <SettingsShell
          :sections="sections"
          title="插件"
          :initial-section="props.initialSection"
          :settings-theme-style="settingsThemeStyle"
          :hide-nav="props.hideNav"
          :active-section="props.activeSection"
          @close="$emit('close')"
          @section-change="$emit('section-change', $event)"
        >
          <template #default="{ activeSection }">
            <section v-if="activeSection === 'plugins'" class="settings-panel">
              <CorePluginsEditor
                :request-rpc="props.requestRpc"
                :transport="props.transport"
                @changed="(refreshDesktop) => $emit('capabilities-changed', refreshDesktop)"
              />
            </section>
            <section v-else-if="activeSection === 'skills'" class="settings-panel">
              <CoreSkillsEditor
                :request-rpc="props.requestRpc"
                @changed="$emit('capabilities-changed', false)"
              />
            </section>
            <section v-else-if="activeSection === 'hooks'" class="settings-panel">
              <KeepAlive>
                <CoreHooksEditor :request-rpc="props.requestRpc" />
              </KeepAlive>
            </section>
          </template>
    </SettingsShell>
  </div>
</template>

<script setup lang="ts">
/**
 * PluginsShell — 与设置（CoreSettings）同级的插件管理全屏页。
 *
 * 插件 / 技能 / 钩子是插件管理体系的导航内页（用户共识）：
 * - 插件：插件列表 / 安装 / 详情资产 / 配置表单（CorePluginsEditor）
 * - 技能：系统级技能管理（CoreSkillsEditor，含 create-plugin / plugin-manager）
 * - 钩子：系统级 Hook 管理（CoreHooksEditor，逐条信任）
 * 复用 SettingsShell 骨架（同一 overlay/侧边栏布局 + --settings-* token）。
 */
import { computed, ref } from 'vue'
import SettingsShell from './SettingsShell.vue'
import { PLUGIN_SHELL_SECTIONS, type SettingsSection } from './settingsSections'
import CorePluginsEditor from './CorePluginsEditor.vue'
import CoreSkillsEditor from './CoreSkillsEditor.vue'
import CoreHooksEditor from './CoreHooksEditor.vue'
import { gradientFromStops, relativeLuminance, type ThemeData } from '../helpers/theme'
import type { LamToolsTransport } from '../transport'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  transport: LamToolsTransport
  theme?: ThemeData | null
  /** Section to open on: a search hit for a skill lands on 技能, not 插件. */
  initialSection?: string
  /** Hide the built-in left nav: the host renders it in the workspace drawer. */
  hideNav?: boolean
  /** Controlled section from the host's drawer nav. */
  activeSection?: string
}>()

const emit = defineEmits<{
  close: []
  'section-change': [id: string]
  'capabilities-changed': [refreshDesktop: boolean]
}>()


const sections = PLUGIN_SHELL_SECTIONS

const settingsThemeStyle = computed(() => {
  if (!props.theme) return {}
  const theme = props.theme
  const lightMain = relativeLuminance(theme.mainText) < 0.45
  return {
    '--settings-backdrop-background': gradientFromStops(
      theme.backdropAngle,
      theme.backdropStops,
      1,
    ),
    '--settings-backdrop-text': theme.backdropText,
    '--settings-main-background': gradientFromStops(
      theme.mainAngle,
      theme.mainStops,
      theme.mainOpacity,
    ),
    '--settings-main-text': theme.mainText,
    '--settings-main-solid': theme.mainStops[0]?.color || '#111111',
    '--settings-card-background': 'color-mix(in srgb, var(--settings-main-solid) 96%, var(--settings-main-text) 4%)',
    '--settings-card-text': theme.mainText,
    '--settings-control-background': gradientFromStops(
      theme.controlAngle,
      theme.controlStops,
      theme.controlOpacity,
    ),
    '--settings-control-text': theme.controlText,
    '--settings-control-solid': theme.controlStops[0]?.color || '#3a3834',
    ...(lightMain ? {
      '--settings-panel-2': '#f0efeb',
      '--settings-line': '#d4d0cc',
      '--settings-muted': '#8a8580',
    } : {}),
  } as Record<string, string>
})

</script>
