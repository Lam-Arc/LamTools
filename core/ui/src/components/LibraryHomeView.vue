<template>
  <div class="library-surface full-area-view library-home" data-ui-id="library.root">
    <!-- user:“同时收敛一下套系”+(资料分区用共享筛选样式，保留原有切换和草稿保护)。 -->
    <div class="library-sections sunday-page-tabs" role="tablist" :aria-label="t('资料库分区')" data-library-sections @keydown="onManualTabGroupKeydown">
      <button
        v-for="item in sections"
        :key="item.id"
        type="button"
        role="tab"
        :aria-selected="section === item.id"
        :tabindex="section === item.id ? 0 : -1"
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
    <!-- user:“全盘文件自动可搜索，不需要手动导入”+(本机文件与项目资料并列：搜索、浏览、预览、收藏共用一份文件身份)。 -->
    <LocalFilesView
      v-else-if="section === 'local'"
      :request-rpc="requestRpc"
      :transport="transport"
    />
    <MemoryView
      v-else-if="section === 'memory'"
      ref="sectionRef"
      :root-label="t('记忆')"
      :request-rpc="requestRpc"
      :client="client"
      :platform="platform"
      :band-actions="bandActions"
      @back="emit('back')"
      @heading="onChildHeading"
    />
    <PlanLibraryView
      v-else-if="section === 'plans'"
      ref="sectionRef"
      :root-label="t('方案')"
      :client="client"
      :project-id="projectId"
      :refresh-signal="refreshSignal"
      :band-actions="bandActions"
      @back="emit('back')"
      @start-plan="emit('start-plan', $event)"
      @heading="onChildHeading"
    />
    <WikiView
      v-else-if="section === 'wiki'"
      ref="sectionRef"
      :request-rpc="requestRpc"
      @heading="onChildHeading"
    />
    <!-- user:“把库和easy file统合到一起”+(资料库直接使用项目文件树，保留目录、搜索和文件操作)。 -->
    <CoreSplitFileTree
      v-if="filesVisited"
      v-show="section === 'files'"
      class="library-project-files"
      :root="workRoot ?? ''"
      :transport="transport"
      :list-files="listFiles"
      @open="openFile"
    />
  </div>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'
// user:“确保视觉、功能和交互不退化”+(先移动标签焦点，激活仍经过现有草稿保护)。
import { onManualTabGroupKeydown } from '@/composables/radioGroupKeyboard.ts'

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
import type { CoreProjectClient } from '@/projects/client.ts'
import type { LamToolsTransport } from '@/transport/index.ts'
// user:“该修修”+(Wiki 分区使用真实组件，避免未注册标签导致空白)。
import WikiView from '@/components/WikiView.vue'
import MaterialsView from '@/components/MaterialsView.vue'
import LocalFilesView from '@/components/LocalFilesView.vue'
import MemoryView from '@/components/MemoryView.vue'
import PlanLibraryView from '@/components/PlanLibraryView.vue'
import type { PlanLibraryEntry } from '@/components/PlanLibraryView.vue'
import CoreSplitFileTree from '@/components/CoreSplitFileTree.vue'
import type { SplitFileEntry } from '@/split/native'

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
  listFiles?: (root: string, path: string) => Promise<SplitFileEntry[]>
  openProjectFile?: (path: string, scope: { workRoot: string; projectId?: string }) => void | Promise<void>
}>()

const emit = defineEmits<{
  back: []
  'start-plan': [entry: PlanLibraryEntry]
  /** 顶部条标题跟随分区与分区内的子页。 */
  heading: [payload: { title: string; subtitle: string }]
}>()

type SectionId = 'materials' | 'local' | 'files' | 'memory' | 'plans' | 'wiki'
const SECTIONS: Array<{ id: SectionId; label: string }> = [
  { id: 'materials', get label() { return t("资料") } },
  { id: 'local', get label() { return t('本机文件') } },
  { id: 'files', get label() { return t('项目文件') } },
  { id: 'memory', get label() { return t("记忆") } },
  { id: 'plans', get label() { return t("方案") } },
  { id: 'wiki', get label() { return t("Wiki") } },
]

const section = ref<SectionId>('materials')
const sections = computed(() => SECTIONS.filter(item => (item.id !== 'files' || Boolean(props.openProjectFile && props.platform !== 'mobile')) && (item.id !== 'local' || props.platform !== 'mobile')))
const filesVisited = ref(false)
const childHeading = ref<{ title: string; subtitle: string } | null>(null)
const sectionRef = ref<{ handleBack?: () => boolean; isEditing?: () => boolean; hasUnsavedChanges?: () => boolean; savePendingChanges?: () => Promise<boolean>; discardPendingChanges?: () => void } | null>(null)

/** 正在写的草稿不该被一次分区切换吞掉：编辑中先不让切走。 */
function selectSection(next: SectionId): void {
  if (section.value === next) return
  if (sectionRef.value?.isEditing?.()) return
  if (next === 'files') filesVisited.value = true
  section.value = next
  childHeading.value = null
}

function openFile(path: string) {
  if (props.workRoot) void props.openProjectFile?.(path, { workRoot: props.workRoot, projectId: props.projectId ?? undefined })
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
    return { get title() { return t("资料库 › 资料") }, get subtitle() { return t("项目里进出的文件 — 用户上传、中间产物与最终产物。") } }
  }
  if (section.value === 'local') {
    return { get title() { return t("资料库 › 本机文件") }, get subtitle() { return t("搜索整台电脑、浏览目录、预览并管理本机文件与资产。") } }
  }
  const label = SECTIONS.find(item => item.id === section.value)?.label ?? ''
  const child = childHeading.value
  if (!child) return { title: t("资料库 › {0}", { 0: label }), subtitle: '' }
  return { title: t("资料库 › {0}", { 0: child.title }), subtitle: child.subtitle }
})
watch(heading, (value) => emit('heading', { ...value }), { immediate: true })

/* ---- 返回层级：分区内先回上一层，都不在了才退出整版 ---- */
function handleBack(): boolean {
  return sectionRef.value?.handleBack?.() ?? false
}
// user:“内置文本编辑器”+(分屏关闭资料库时也要保护正在编辑的记忆与方案)。
defineExpose({ handleBack, hasUnsavedChanges: () => sectionRef.value?.hasUnsavedChanges?.() || false, savePendingChanges: () => sectionRef.value?.savePendingChanges?.() ?? Promise.resolve(true), discardPendingChanges: () => sectionRef.value?.discardPendingChanges?.() })
</script>

<style scoped>
.library-project-files { flex: 1 1 auto; min-height: 0; }
</style>
