<template>
  <Teleport to="body">
    <div ref="settingsOverlayEl" class="settings-overlay">
      <div ref="settingsCardEl" class="settings-card" :style="settingsThemeStyle">
        <SettingsShell
          :sections="sections"
          title="插件"
          :initial-section="props.initialSection"
          :settings-theme-style="settingsThemeStyle"
          @close="$emit('close')"
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
    </div>
  </Teleport>
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
import SettingsShell, { type SettingsSection } from './SettingsShell.vue'
import CorePluginsEditor from './CorePluginsEditor.vue'
import CoreSkillsEditor from './CoreSkillsEditor.vue'
import CoreHooksEditor from './CoreHooksEditor.vue'
import { gradientFromStops, relativeLuminance, type ThemeData } from '../helpers/theme'
import type { LamToolsTransport } from '../transport'
import { useOutsidePointerDismiss } from '../composables/useOutsidePointerDismiss'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  transport: LamToolsTransport
  theme?: ThemeData | null
  /** Section to open on: a search hit for a skill lands on 技能, not 插件. */
  initialSection?: string
}>()

const emit = defineEmits<{
  close: []
  'capabilities-changed': [refreshDesktop: boolean]
}>()

const settingsOverlayEl = ref<HTMLElement | null>(null)
const settingsCardEl = ref<HTMLElement | null>(null)

const sections: SettingsSection[] = [
  { id: 'plugins', label: '插件', icon: 'puzzle' },
  { id: 'skills', label: '技能', icon: 'sparkles' },
  { id: 'hooks', label: '钩子', icon: 'plug' },
]

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

useOutsidePointerDismiss({
  overlay: settingsOverlayEl,
  card: settingsCardEl,
  onDismiss: () => emit('close'),
})
</script>
