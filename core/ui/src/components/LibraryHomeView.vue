<template>
  <div class="library-surface full-area-view library-home">
    <!-- ── 三大项：资料 / 记忆 / 方案 ── -->
    <div class="library-sections" role="tablist" aria-label="资料库分区" data-library-sections>
      <button
        v-for="item in SECTIONS"
        :key="item.id"
        type="button"
        role="tab"
        :aria-selected="section === item.id"
        :class="{ active: section === item.id }"
        :data-library-section="item.id"
        @click="selectSection(item.id)"
      >{{ item.label }}</button>
    </div>

    <MaterialsView
      v-if="section === 'materials'"
      data-library-materials
      :project-id="projectId ?? null"
      :transport="transport"
      :request-rpc="requestRpc"
      :work-root="workRoot"
      :artifact-signal="artifactSignal"
      :upload-files="uploadFiles"
    />
    <MemoryView
      v-else-if="section === 'memory'"
      ref="sectionRef"
      root-label="记忆"
      :request-rpc="requestRpc"
      :client="client"
      :platform="platform"
      :band-actions="bandActions"
      @back="emit('back')"
      @heading="onChildHeading"
    />
    <PlanLibraryView
      v-else
      ref="sectionRef"
      root-label="方案"
      :client="client"
      :project-id="projectId"
      :refresh-signal="refreshSignal"
      :band-actions="bandActions"
      @back="emit('back')"
      @start-plan="emit('start-plan', $event)"
      @heading="onChildHeading"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * LibraryHomeView — 资料库的壳：一个入口，三个分区。
 *
 * ChatGPT 式资料库那件事在这里被拆成三块，都是同一种版面（见
 * styles/library-surface.css），所以合起来是一个入口而不是三个：
 *
 * - 资料：项目里进出的文件（用户 / 中间产物 / 产物），版式对标 ChatGPT 资料库
 *   （大标题 + 工具栏 + 药丸筛选 + 卡片墙 + 缩略图 + 上传新建）。
 * - 记忆：项目档与全局档的记忆文件；项目档先列项目这一层，即原有的记忆浏览。
 * - 方案：「方案/」文件夹里的方案，即原有的方案库。
 *
 * 分区切换只在最外层；每一项内部的层级（记忆的项目层与档位、方案的状态筛选）各自管自己。
 */
import { computed, ref, watch } from 'vue'
import type { CoreProjectClient } from '../projects/client'
import type { LamToolsTransport } from '../transport'
import MaterialsView from './MaterialsView.vue'
import MemoryView from './MemoryView.vue'
import PlanLibraryView from './PlanLibraryView.vue'
import type { PlanLibraryEntry } from './PlanLibraryView.vue'

const props = defineProps<{
  /** The switchable project client (desktop HTTP or the phone's standalone bridge). */
  client: CoreProjectClient
  /** The project every section reads. */
  projectId?: string | null
  /** The project work root — the materials tier needs it. */
  workRoot?: string | null
  /** Transport + RPC for the artifact catalog. */
  transport?: LamToolsTransport
  /** Durable RPC bridge — the artifact catalog and memory both read through it. */
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  /** Last workbench event; artifact-bearing events trigger a quiet refresh. */
  artifactSignal?: unknown
  /** 上传文件到资料库的当前层（选文件与传字节都由宿主负责）。 */
  uploadFiles?: (folder: string) => Promise<void>
  /** Bumped by the host when a turn finishes — the cue to rescan. */
  refreshSignal?: number
  /** Desktop sends actions into the header band; phones render them in place. */
  bandActions?: boolean
  /** Phones have no memory RPC, so that section explains instead of pretending. */
  platform?: string
}>()

const emit = defineEmits<{
  back: []
  'start-plan': [entry: PlanLibraryEntry]
  /** 顶部条标题跟随分区与分区内的子页。 */
  heading: [payload: { title: string; subtitle: string }]
}>()

type SectionId = 'materials' | 'memory' | 'plans'
const SECTIONS: Array<{ id: SectionId; label: string }> = [
  { id: 'materials', label: '资料' },
  { id: 'memory', label: '记忆' },
  { id: 'plans', label: '方案' },
]

const section = ref<SectionId>('materials')
const childHeading = ref<{ title: string; subtitle: string } | null>(null)
const sectionRef = ref<{ handleBack?: () => boolean; isEditing?: () => boolean } | null>(null)

/** 正在写的草稿不该被一次分区切换吞掉：编辑中先不让切走。 */
function selectSection(next: SectionId): void {
  if (section.value === next) return
  if (sectionRef.value?.isEditing?.()) return
  section.value = next
  childHeading.value = null
}

watch(() => props.projectId, () => {
  section.value = 'materials'
  childHeading.value = null
})

function onChildHeading(payload: { title: string; subtitle: string }): void {
  childHeading.value = payload
}

/** 顶栏动作条与标题都归当前分区；标题再统一挂到「资料库」下面。 */
const heading = computed<{ title: string; subtitle: string }>(() => {
  if (section.value === 'materials') {
    return { title: '资料库 › 资料', subtitle: '项目里进出的文件 — 用户上传、中间产物与最终产物。' }
  }
  const label = SECTIONS.find(item => item.id === section.value)?.label ?? ''
  const child = childHeading.value
  if (!child) return { title: `资料库 › ${label}`, subtitle: '' }
  return { title: `资料库 › ${child.title}`, subtitle: child.subtitle }
})
watch(heading, (value) => emit('heading', { ...value }), { immediate: true })

/* ---- 返回层级：分区内先回上一层，都不在了才退出整版 ---- */
function handleBack(): boolean {
  return sectionRef.value?.handleBack?.() ?? false
}
defineExpose({ handleBack })
</script>
