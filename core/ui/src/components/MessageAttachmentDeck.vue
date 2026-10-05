<template>
  <section
    v-if="deckItems.length"
    ref="rootEl"
    class="message-attachment-deck"
    :class="`message-attachment-deck--${side}`"
    :aria-label="ariaLabel"
  >
    <div v-if="heading" class="message-attachment-deck__heading">{{ heading }}</div>
    <div
      class="message-attachment-deck__shell"
      :class="{ 'message-attachment-deck__shell--paged': pageCount > 1 }"
    >
      <button
        v-if="pageCount > 1"
        type="button"
        class="message-attachment-deck__nav message-attachment-deck__nav--previous"
        :disabled="pageIndex === 0"
        aria-label="上一页附件"
        @click="changePage(pageIndex - 1)"
      >
        <ChevronLeft :size="16" :stroke-width="2" aria-hidden="true" />
      </button>

      <div
        ref="trackEl"
        class="message-attachment-deck__track"
        :class="{ 'message-attachment-deck__track--filled': fullPagedPage }"
        :style="trackStyle"
      >
        <article
          v-for="(item, index) in visibleItems"
          :key="item.key"
          class="message-attachment-deck__card"
          :class="{
            'message-attachment-deck__card--active': activeKey === item.key,
            'message-attachment-deck__card--neighbor': isActiveNeighbor(index),
            'message-attachment-deck__card--following': followsActiveCard(index),
            'message-attachment-deck__card--image': item.displayKind === 'image',
          }"
          :style="{
            '--stack-order': String(stackOrder(index)),
            '--deck-item-step': `${deckItemSteps[index] ?? STACK_STEP}px`,
          }"
          :data-deck-item="item.key"
          @pointerenter="setHovered(item.key)"
          @pointerleave="clearHovered(item.key)"
        >
          <button
            type="button"
            class="message-attachment-deck__preview"
            :aria-expanded="activeKey === item.key"
            :aria-label="`${item.displayKind === 'text' ? '双击文本预览' : '双击打开'} ${item.name}`"
            @click="releasePointerFocus"
            @dblclick.stop="openDeckItem(item)"
            @keydown.enter.prevent="openDeckItem(item)"
            @keydown.space.prevent="openDeckItem(item)"
          >
            <span class="message-attachment-deck__visual" :class="`message-attachment-deck__visual--${item.tone}`">
              <img
                v-if="previewUrls[item.key] && item.displayKind === 'image'"
                class="message-attachment-deck__thumbnail"
                :src="previewUrls[item.key]"
                :alt="item.name"
                loading="lazy"
              >
              <component
                :is="item.icon"
                v-else
                :size="26"
                :stroke-width="1.65"
                aria-hidden="true"
              />
              <span v-if="item.extension && item.displayKind !== 'image'" class="message-attachment-deck__extension">
                {{ item.extension }}
              </span>
            </span>

            <span class="message-attachment-deck__details">
              <span class="message-attachment-deck__name" :title="item.name">{{ item.name }}</span>
              <span class="message-attachment-deck__meta">{{ item.meta }}</span>
              <span v-if="item.preview" class="message-attachment-deck__excerpt">{{ item.preview }}</span>
            </span>
          </button>
        </article>
      </div>

      <button
        v-if="pageCount > 1"
        type="button"
        class="message-attachment-deck__nav message-attachment-deck__nav--next"
        :disabled="pageIndex >= pageCount - 1"
        aria-label="下一页附件"
        @click="changePage(pageIndex + 1)"
      >
        <ChevronRight :size="16" :stroke-width="2" aria-hidden="true" />
      </button>
    </div>

    <CoreConfirmDialog
      v-if="pendingOpenItem"
      :open="true"
      title="使用默认应用打开？"
      description="此文件将交给系统默认应用处理。"
      :detail="pendingOpenItem?.name"
      :loading="Boolean(openingKey)"
      :error="openError"
      @cancel="cancelOpen"
      @confirm="confirmOpen"
    />

    <Teleport to="body">
      <div
        v-if="textPreviewItem"
        class="message-attachment-deck__text-overlay"
        role="presentation"
        @click.self="closeTextPreview"
      >
        <section
          ref="textDialogEl"
          class="message-attachment-deck__text-dialog"
          role="dialog"
          aria-modal="true"
          :aria-label="`${textPreviewItem.name} 文本预览`"
          tabindex="-1"
          @keydown.esc.prevent="closeTextPreview"
        >
          <header class="message-attachment-deck__text-header">
            <span class="message-attachment-deck__text-title">
              <FileText :size="16" :stroke-width="1.8" aria-hidden="true" />
              <strong>{{ textPreviewItem.name }}</strong>
              <span>纯文本</span>
            </span>
            <button type="button" aria-label="关闭文本预览" title="关闭" @click="closeTextPreview">
              <X :size="16" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </header>
          <div v-if="textPreviewLoading" class="message-attachment-deck__text-state">正在读取文本…</div>
          <div v-else-if="textPreviewError" class="message-attachment-deck__text-state message-attachment-deck__text-state--error" role="alert">{{ textPreviewError }}</div>
          <pre v-else class="message-attachment-deck__text-content">{{ textPreviewContent }}</pre>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { Flip } from 'gsap/Flip'
import { gsap } from 'gsap'
import {
  ChevronLeft,
  ChevronRight,
  File,
  FileArchive,
  FileCode2,
  FileJson2,
  FileText,
  Image as ImageIcon,
  Presentation,
  Sheet,
  X,
  type LucideIcon,
} from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { CoreAttachment, ToolArtifact } from '../types'
import type { LamToolsTransport, TransportHttpResponse } from '../transport'
import CoreConfirmDialog from './CoreConfirmDialog.vue'

gsap.registerPlugin(Flip)

type ArtifactLike = ToolArtifact & {
  artifact_id?: string
  mime_type?: string
  name?: string
  size_bytes?: number
}

interface DeckItem {
  key: string
  source: 'artifact' | 'attachment'
  name: string
  extension: string
  mimeType: string
  size: number
  displayKind: 'image' | 'text' | 'file'
  tone: 'image' | 'code' | 'json' | 'text' | 'pdf' | 'sheet' | 'presentation' | 'archive' | 'file'
  icon: LucideIcon
  meta: string
  preview: string
  artifact?: ArtifactLike
  attachment?: CoreAttachment
}

const props = withDefaults(defineProps<{
  artifacts?: ArtifactLike[]
  attachments?: CoreAttachment[]
  transport: LamToolsTransport
  projectId?: string | null
  workRoot?: string | null
  side?: 'left' | 'right'
  heading?: string
  ariaLabel?: string
}>(), {
  artifacts: () => [],
  attachments: () => [],
  projectId: null,
  workRoot: null,
  side: 'left',
  heading: '',
  ariaLabel: '附件',
})

const COLLAPSED_WIDTH = 72
const EXPANDED_WIDTH = 220
const STACK_STEP = 36
const NAV_RESERVE = 64
const HOVER_HANDOFF_MS = 120

const rootEl = ref<HTMLElement | null>(null)
const trackEl = ref<HTMLElement | null>(null)
const measuredWidth = ref(760)
const pageIndex = ref(0)
const hoveredKey = ref('')
const openingKey = ref('')
const pendingOpenItem = ref<DeckItem | null>(null)
const openError = ref('')
const textPreviewItem = ref<DeckItem | null>(null)
const textPreviewContent = ref('')
const textPreviewError = ref('')
const textPreviewLoading = ref(false)
const textDialogEl = ref<HTMLElement | null>(null)
const reducedMotion = ref(false)
const previewUrls = reactive<Record<string, string>>({})
const textPreviews = reactive<Record<string, string>>({})
const ownedObjectUrls = new Set<string>()
let resizeObserver: ResizeObserver | null = null
let gsapContext: gsap.Context | null = null
let gsapMatchMedia: gsap.MatchMedia | null = null
let flipAnimation: gsap.core.Animation | null = null
let pageTimeline: gsap.core.Timeline | null = null
let animationRevision = 0
let hoverLeaveTimer: ReturnType<typeof setTimeout> | null = null
let textPreviewRestoreFocus: HTMLElement | null = null

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'avif', 'svg'])
const CODE_EXTENSIONS = new Set(['ts', 'tsx', 'js', 'jsx', 'vue', 'py', 'rs', 'go', 'java', 'c', 'cc', 'cpp', 'h', 'hpp', 'cs', 'php', 'rb', 'sh', 'ps1', 'sql', 'html', 'css', 'scss', 'less'])
const JSON_EXTENSIONS = new Set(['json', 'jsonc', 'yaml', 'yml', 'toml', 'xml'])
const TEXT_EXTENSIONS = new Set(['md', 'mdx', 'txt', 'log', 'ini', 'cfg', 'conf', 'env', 'csv'])
const SHEET_EXTENSIONS = new Set(['xls', 'xlsx', 'ods', 'csv'])
const PRESENTATION_EXTENSIONS = new Set(['ppt', 'pptx', 'odp'])
const ARCHIVE_EXTENSIONS = new Set(['zip', 'rar', '7z', 'tar', 'gz', 'bz2'])

function basename(path: string): string {
  const clean = path.replace(/^workspace:\/\//, '').replace(/^attachment:\/\//, '').split(/[?#]/, 1)[0]
  return clean.split(/[\\/]/).filter(Boolean).pop() || 'artifact'
}

function extension(name: string): string {
  const suffix = name.split('.').pop()?.toLowerCase() || ''
  return suffix === name.toLowerCase() ? '' : suffix
}

function humanSize(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return ''
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function compactPreview(value: unknown): string {
  if (typeof value !== 'string') return ''
  const lines = value
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map(line => line.replace(/^[-+ ]/, '').trim())
    .filter(line => line && !line.startsWith('@@') && !line.startsWith('---') && !line.startsWith('+++'))
  return lines.join(' · ').slice(0, 150)
}

function displayDescriptor(name: string, mimeType: string, previewType = ''): Pick<DeckItem, 'displayKind' | 'tone' | 'icon'> {
  const ext = extension(name)
  if (previewType === 'image' || mimeType.startsWith('image/') || IMAGE_EXTENSIONS.has(ext)) {
    return { displayKind: 'image', tone: 'image', icon: ImageIcon }
  }
  if (ext === 'pdf' || mimeType === 'application/pdf') return { displayKind: 'file', tone: 'pdf', icon: FileText }
  if (SHEET_EXTENSIONS.has(ext)) return { displayKind: 'file', tone: 'sheet', icon: Sheet }
  if (PRESENTATION_EXTENSIONS.has(ext)) return { displayKind: 'file', tone: 'presentation', icon: Presentation }
  if (ARCHIVE_EXTENSIONS.has(ext)) return { displayKind: 'file', tone: 'archive', icon: FileArchive }
  if (CODE_EXTENSIONS.has(ext)) return { displayKind: 'text', tone: 'code', icon: FileCode2 }
  if (JSON_EXTENSIONS.has(ext)) return { displayKind: 'text', tone: 'json', icon: FileJson2 }
  if (previewType === 'text' || mimeType.startsWith('text/') || TEXT_EXTENSIONS.has(ext)) {
    return { displayKind: 'text', tone: 'text', icon: FileText }
  }
  return { displayKind: 'file', tone: 'file', icon: File }
}

function artifactKey(artifact: ArtifactLike, index: number): string {
  return String(artifact.artifact_id || artifact.uri || artifact.metadata?.image_data_url || `artifact-${index}`)
}

const deckItems = computed<DeckItem[]>(() => {
  const artifactItems = props.artifacts.map((artifact, index) => {
    const path = String(artifact.metadata?.path || artifact.uri || '')
    const name = String(artifact.name || basename(path))
    const mimeType = String(artifact.mime_type || artifact.metadata?.mime_type || '')
    const descriptor = displayDescriptor(name, mimeType)
    const ext = extension(name)
    const size = Number(artifact.size_bytes || artifact.metadata?.new_size_bytes || artifact.metadata?.size_bytes || 0)
    const action = String(artifact.metadata?.action || '')
    return {
      key: artifactKey(artifact, index),
      source: 'artifact' as const,
      name,
      extension: ext.toUpperCase(),
      mimeType,
      size,
      ...descriptor,
      meta: [action === 'create' ? '新建' : action ? '已修改' : '产物', ext.toUpperCase(), humanSize(size)].filter(Boolean).join(' · '),
      preview: compactPreview(artifact.content),
      artifact,
    }
  })
  const attachmentItems = props.attachments.map(attachment => {
    const name = attachment.label || attachment.filename || 'attachment'
    const ext = extension(name)
    const descriptor = displayDescriptor(name, attachment.mime_type || '', attachment.preview_type || '')
    return {
      key: `attachment:${attachment.id}`,
      source: 'attachment' as const,
      name,
      extension: ext.toUpperCase(),
      mimeType: attachment.mime_type || '',
      size: attachment.size || 0,
      ...descriptor,
      meta: [ext.toUpperCase() || '文件', humanSize(attachment.size || 0)].filter(Boolean).join(' · '),
      preview: textPreviews[`attachment:${attachment.id}`] || '',
      attachment,
    }
  })
  return [...artifactItems, ...attachmentItems]
})

const pageSize = computed(() => {
  const unpagedWidth = Math.max(COLLAPSED_WIDTH, measuredWidth.value)
  const unpagedCapacity = Math.max(1, Math.floor((unpagedWidth - COLLAPSED_WIDTH) / STACK_STEP) + 1)
  if (deckItems.value.length <= unpagedCapacity) return unpagedCapacity
  const pagedWidth = Math.max(EXPANDED_WIDTH, measuredWidth.value - NAV_RESERVE)
  return Math.max(1, Math.floor((pagedWidth - COLLAPSED_WIDTH) / STACK_STEP) + 1)
})

const pageCount = computed(() => Math.max(1, Math.ceil(deckItems.value.length / pageSize.value)))
const visibleItems = computed(() => {
  const start = pageIndex.value * pageSize.value
  return deckItems.value.slice(start, start + pageSize.value)
})
const activeKey = computed(() => hoveredKey.value)
const activeVisibleIndex = computed(() => visibleItems.value.findIndex(item => item.key === activeKey.value))
const fullPagedPage = computed(() => (
  pageCount.value > 1 && visibleItems.value.length === pageSize.value
))
const baseDeckStep = computed(() => {
  if (!fullPagedPage.value || visibleItems.value.length <= 1) {
    return STACK_STEP
  }
  const count = visibleItems.value.length
  const width = Math.max(EXPANDED_WIDTH, measuredWidth.value - NAV_RESERVE)
  const activeVisible = visibleItems.value.some(item => item.key === activeKey.value)
  const cardsWidth = COLLAPSED_WIDTH * count + (activeVisible ? EXPANDED_WIDTH - COLLAPSED_WIDTH : 0)
  const step = COLLAPSED_WIDTH + (width - cardsWidth) / (count - 1)
  return Math.max(0, step)
})
const trackStyle = computed(() => ({ '--deck-step': `${baseDeckStep.value}px` }))
const deckItemSteps = computed(() => {
  const count = visibleItems.value.length
  const steps = Array<number>(count).fill(baseDeckStep.value)
  const activeIndex = activeVisibleIndex.value
  if (activeIndex < 0 || activeIndex >= count - 1) return steps

  // The first card on the expansion side must remain fully targetable instead
  // of hiding under the raised card. Preserve the row's total span by sharing
  // the recovered overlap across every other gap, which keeps the tail compact.
  const visibleGap = 4
  steps[activeIndex + 1] = COLLAPSED_WIDTH + visibleGap
  if (count <= 2) return steps
  const originalMarginTotal = (count - 1) * (baseDeckStep.value - COLLAPSED_WIDTH)
  const redistributedMargin = (originalMarginTotal - visibleGap) / (count - 2)
  for (let index = 1; index < count; index += 1) {
    if (index === activeIndex + 1) continue
    steps[index] = Math.max(0, COLLAPSED_WIDTH + redistributedMargin)
  }
  return steps
})

function stackOrder(index: number): number {
  return props.side === 'left' ? index + 1 : visibleItems.value.length - index
}

function isActiveNeighbor(index: number): boolean {
  return activeVisibleIndex.value >= 0 && Math.abs(index - activeVisibleIndex.value) === 1
}

function followsActiveCard(index: number): boolean {
  return activeVisibleIndex.value >= 0 && index > activeVisibleIndex.value
}

function cardElements(): HTMLElement[] {
  return trackEl.value ? Array.from(trackEl.value.querySelectorAll<HTMLElement>('.message-attachment-deck__card')) : []
}

function animateState(mutate: () => void): void {
  const cards = cardElements()
  const state = !reducedMotion.value && cards.length ? Flip.getState(cards) : null
  mutate()
  const revision = ++animationRevision
  void nextTick(() => {
    if (revision !== animationRevision) return
    flipAnimation?.kill()
    const nextCards = cardElements()
    if (state && nextCards.length) {
      gsapContext?.add(() => {
        flipAnimation = Flip.from(state, {
          targets: nextCards,
          duration: 0.3,
          ease: 'power2.out',
          simple: true,
          scale: true,
          nested: true,
          absolute: false,
        })
      })
    }
    const previews = nextCards.map(card => card.querySelector<HTMLElement>('.message-attachment-deck__preview')).filter(Boolean) as HTMLElement[]
    if (!previews.length) return
    gsapContext?.add(() => {
      gsap.to(previews, {
        scale: (_index, target) => {
          const card = target.closest('.message-attachment-deck__card')
          if (card?.classList.contains('message-attachment-deck__card--active')) return 1.025
          if (card?.classList.contains('message-attachment-deck__card--neighbor')) return 1.012
          return 1
        },
        duration: reducedMotion.value ? 0 : 0.22,
        ease: 'power2.out',
        overwrite: 'auto',
      })
    })
  })
}

function setHovered(key: string): void {
  if (hoverLeaveTimer) {
    clearTimeout(hoverLeaveTimer)
    hoverLeaveTimer = null
  }
  if (hoveredKey.value === key) return
  animateState(() => { hoveredKey.value = key })
}

function clearHovered(key: string): void {
  if (hoveredKey.value !== key) return
  if (hoverLeaveTimer) clearTimeout(hoverLeaveTimer)
  hoverLeaveTimer = setTimeout(() => {
    hoverLeaveTimer = null
    if (hoveredKey.value !== key) return
    animateState(() => { hoveredKey.value = '' })
  }, HOVER_HANDOFF_MS)
}

function releasePointerFocus(event: MouseEvent): void {
  if (event.currentTarget instanceof HTMLElement) {
    event.currentTarget.blur()
  }
}

async function openDeckItem(item: DeckItem): Promise<void> {
  if (openingKey.value) return
  if (item.displayKind === 'text') {
    await openTextPreview(item)
    return
  }
  openError.value = ''
  pendingOpenItem.value = item
}

async function openTextPreview(item: DeckItem): Promise<void> {
  textPreviewItem.value = item
  textPreviewContent.value = ''
  textPreviewError.value = ''
  textPreviewLoading.value = true
  try {
    let path = ''
    if (item.artifact) path = artifactRequestPath(item.artifact)
    else if (item.attachment) path = `/attachments/${encodeURIComponent(item.attachment.id)}/download`
    if (path) {
      const response = await props.transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path })
      if (response.status < 200 || response.status >= 300) throw new Error(`HTTP ${response.status}`)
      textPreviewContent.value = new TextDecoder().decode(Uint8Array.from(response.body))
    } else if (typeof item.artifact?.content === 'string') {
      textPreviewContent.value = item.artifact.content
    } else {
      throw new Error('缺少可读取的文本路径')
    }
  } catch (error) {
    textPreviewError.value = `无法读取文本：${error instanceof Error ? error.message : String(error)}`
  } finally {
    textPreviewLoading.value = false
  }
}

function closeTextPreview(): void {
  textPreviewItem.value = null
  textPreviewContent.value = ''
  textPreviewError.value = ''
  textPreviewLoading.value = false
  textPreviewRestoreFocus?.focus()
  textPreviewRestoreFocus = null
}

function cancelOpen(): void {
  if (openingKey.value) return
  pendingOpenItem.value = null
  openError.value = ''
}

async function confirmOpen(): Promise<void> {
  const item = pendingOpenItem.value
  if (!item || openingKey.value) return
  openingKey.value = item.key
  openError.value = ''
  try {
    const attachmentId = item.attachment?.id || attachmentIdFromArtifact(item.artifact)
    if (attachmentId) {
      const response = await props.transport.request<TransportHttpResponse>({
        kind: 'http',
        method: 'POST',
        path: `/attachments/${encodeURIComponent(attachmentId)}/open`,
      })
      if (response.status < 200 || response.status >= 300) throw new Error(`HTTP ${response.status}`)
    } else if (item.artifact && props.projectId) {
      await props.transport.request({
        method: 'artifact.open',
        params: {
          project_id: props.projectId,
          artifact_id: item.artifact.artifact_id || '',
          path: artifactLocalPath(item.artifact),
        },
      })
    } else {
      throw new Error('缺少可打开的附件标识')
    }
    pendingOpenItem.value = null
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    openError.value = `无法打开：${detail}`
  } finally {
    openingKey.value = ''
  }
}

function attachmentIdFromArtifact(artifact?: ArtifactLike): string {
  const path = artifactLocalPath(artifact)
  return path.startsWith('attachment://') ? path.slice('attachment://'.length) : ''
}

function artifactLocalPath(artifact?: ArtifactLike): string {
  return String(artifact?.uri || artifact?.metadata?.path || '')
}

function changePage(nextPage: number): void {
  if (nextPage < 0 || nextPage >= pageCount.value || nextPage === pageIndex.value) return
  const direction = nextPage > pageIndex.value ? 1 : -1
  const track = trackEl.value
  pageTimeline?.kill()
  if (!track || reducedMotion.value) {
    pageIndex.value = nextPage
    hoveredKey.value = ''
    return
  }
  gsapContext?.add(() => {
    pageTimeline = gsap.timeline({
      onComplete: () => { pageTimeline = null },
    })
    pageTimeline.to(track, {
      x: direction * -18,
      autoAlpha: 0,
      duration: 0.13,
      ease: 'power2.in',
      onComplete: () => {
        pageIndex.value = nextPage
        hoveredKey.value = ''
      },
    }).fromTo(track, {
      x: direction * 18,
      autoAlpha: 0,
    }, {
      x: 0,
      autoAlpha: 1,
      duration: 0.24,
      ease: 'power2.out',
      immediateRender: false,
    })
  })
}

function artifactRequestPath(artifact: ArtifactLike): string {
  let path = String(artifact.uri || artifact.metadata?.path || '')
  if (props.projectId && artifact.artifact_id) {
    const fallback = path ? `?path=${encodeURIComponent(path)}` : ''
    return `/projects/${encodeURIComponent(props.projectId)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/file${fallback}`
  }
  if (path.startsWith('attachment://')) return `/attachments/${encodeURIComponent(path.slice('attachment://'.length))}/download`
  if (path.startsWith('workspace://')) path = path.slice('workspace://'.length)
  return props.projectId && path
    ? `/projects/${encodeURIComponent(props.projectId)}/files/raw?path=${encodeURIComponent(path)}`
    : ''
}

function directArtifactImage(artifact: ArtifactLike): string {
  const dataUrl = artifact.metadata?.image_data_url
  if (typeof dataUrl === 'string' && dataUrl.startsWith('data:image')) return dataUrl
  let path = String(artifact.uri || artifact.metadata?.path || '')
  if (path.startsWith('data:image') || /^https?:\/\//i.test(path)) return path
  if (path.startsWith('workspace://')) path = path.slice('workspace://'.length)
  const localFileSrc = (window as { __LAMTOOLS_FILE_SRC__?: (value: string) => string }).__LAMTOOLS_FILE_SRC__
  if (typeof localFileSrc === 'function' && props.workRoot && path && !path.startsWith('attachment://')) {
    const absolute = `${props.workRoot.replace(/[\\/]+$/, '')}/${path.replace(/^[\\/]+/, '')}`
    return localFileSrc(absolute)
  }
  return ''
}

async function responseObjectUrl(path: string, mimeType: string): Promise<string> {
  const response = await props.transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path })
  if (response.status < 200 || response.status >= 300) return ''
  const url = URL.createObjectURL(new Blob([Uint8Array.from(response.body)], {
    type: response.headers['content-type'] || mimeType || 'application/octet-stream',
  }))
  ownedObjectUrls.add(url)
  return url
}

async function loadItemPreview(item: DeckItem): Promise<void> {
  if (item.displayKind === 'image' && !previewUrls[item.key]) {
    if (item.artifact) {
      const direct = directArtifactImage(item.artifact)
      if (direct) previewUrls[item.key] = direct
      else {
        const path = artifactRequestPath(item.artifact)
        if (path) previewUrls[item.key] = await responseObjectUrl(path, item.mimeType)
      }
    } else if (item.attachment) {
      previewUrls[item.key] = await responseObjectUrl(
        `/attachments/${encodeURIComponent(item.attachment.id)}/download`,
        item.mimeType,
      )
    }
  }
  if (item.source === 'attachment' && item.displayKind === 'text' && item.attachment && !textPreviews[item.key]) {
    try {
      const response = await props.transport.request<TransportHttpResponse>({
        kind: 'http',
        method: 'GET',
        path: `/attachments/${encodeURIComponent(item.attachment.id)}/preview`,
      })
      if (response.status < 200 || response.status >= 300) return
      const payload = JSON.parse(new TextDecoder().decode(Uint8Array.from(response.body))) as { text?: unknown }
      textPreviews[item.key] = compactPreview(payload.text)
    } catch {
      // Keep the file identity visible when preview bytes are unavailable.
    }
  }
}

watch(
  () => visibleItems.value.map(item => item.key).join('|'),
  () => { for (const item of visibleItems.value) void loadItemPreview(item) },
  { immediate: true },
)

watch([pageCount, pageSize], () => {
  if (pageIndex.value >= pageCount.value) pageIndex.value = pageCount.value - 1
})

watch(() => deckItems.value.map(item => item.key).join('|'), () => {
  const keys = new Set(deckItems.value.map(item => item.key))
  for (const key of Object.keys(previewUrls)) {
    if (keys.has(key)) continue
    const url = previewUrls[key]
    if (ownedObjectUrls.delete(url)) URL.revokeObjectURL(url)
    delete previewUrls[key]
  }
})

watch(textPreviewItem, async item => {
  if (!item) return
  textPreviewRestoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  await nextTick()
  textDialogEl.value?.focus()
})

onMounted(() => {
  if (rootEl.value) gsapContext = gsap.context(() => {}, rootEl.value)
  gsapMatchMedia = gsap.matchMedia()
  gsapMatchMedia.add('(prefers-reduced-motion: reduce)', () => {
    reducedMotion.value = true
    return () => { reducedMotion.value = false }
  })
  if (rootEl.value) measuredWidth.value = rootEl.value.clientWidth || measuredWidth.value
  if (typeof ResizeObserver !== 'undefined' && rootEl.value) {
    resizeObserver = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width || rootEl.value?.clientWidth || 0
      if (width > 0) measuredWidth.value = width
    })
    resizeObserver.observe(rootEl.value)
  }
})

onBeforeUnmount(() => {
  if (hoverLeaveTimer) clearTimeout(hoverLeaveTimer)
  hoverLeaveTimer = null
  resizeObserver?.disconnect()
  resizeObserver = null
  flipAnimation?.kill()
  pageTimeline?.kill()
  gsapMatchMedia?.revert()
  gsapMatchMedia = null
  gsapContext?.revert()
  gsapContext = null
  for (const url of ownedObjectUrls) URL.revokeObjectURL(url)
  ownedObjectUrls.clear()
  textPreviewRestoreFocus?.focus()
  textPreviewRestoreFocus = null
})
</script>

<style scoped>
.message-attachment-deck {
  --text: var(--theme-main-text);
  width: min(100%, 760px);
  min-width: 0;
  margin-top: var(--space-2);
}

.message-attachment-deck--right {
  margin-left: auto;
}

.message-attachment-deck__heading {
  margin-bottom: var(--space-1);
  color: color-mix(in srgb, var(--text) 56%, transparent);
  font-size: 11px;
  line-height: 1.35;
}

.message-attachment-deck__shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
  min-width: 0;
}

.message-attachment-deck__shell--paged {
  grid-template-columns: 28px minmax(0, 1fr) 28px;
  gap: var(--space-1);
}

.message-attachment-deck__track {
  --deck-step: 36px;
  display: flex;
  min-width: 0;
  min-height: 72px;
  align-items: center;
  overflow: visible;
}

.message-attachment-deck--left .message-attachment-deck__track {
  justify-content: flex-start;
}

.message-attachment-deck--right .message-attachment-deck__track {
  flex-direction: row-reverse;
  justify-content: flex-start;
}

.message-attachment-deck__card {
  position: relative;
  z-index: var(--stack-order);
  flex: 0 0 72px;
  width: 72px;
  height: 72px;
  margin: 0;
  overflow: visible;
  will-change: transform;
}

.message-attachment-deck--left .message-attachment-deck__card + .message-attachment-deck__card {
  margin-left: calc(var(--deck-item-step, var(--deck-step)) - 72px);
}

.message-attachment-deck--right .message-attachment-deck__card + .message-attachment-deck__card {
  margin-right: calc(var(--deck-item-step, var(--deck-step)) - 72px);
}

.message-attachment-deck__card--active {
  z-index: var(--z-stage);
  flex-basis: 220px;
  width: 220px;
}

.message-attachment-deck__preview {
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 0;
  align-items: stretch;
  overflow: hidden;
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  padding: 0;
  /* Stacked cards still need an opaque surface, but it should inherit the
     current content area instead of collapsing to a hard black fallback. */
  background: var(--theme-main-background);
  box-shadow: none;
  color: var(--text);
  text-align: left;
  transform-origin: center;
  will-change: transform;
}

.message-attachment-deck__preview:hover {
  border-color: color-mix(in srgb, var(--text) var(--alpha-hover), var(--theme-main-border));
  box-shadow: var(--shadow-sm);
}

.message-attachment-deck__preview:active {
  border-color: color-mix(in srgb, var(--text) var(--alpha-active), var(--theme-main-border));
}

.message-attachment-deck__card--active .message-attachment-deck__preview {
  border-color: color-mix(in srgb, var(--theme-main-text) 20%, var(--theme-main-border));
  background: var(--theme-main-background);
}

.message-attachment-deck__visual {
  position: relative;
  display: grid;
  flex: 0 0 72px;
  width: 72px;
  height: 72px;
  place-items: center;
  align-self: center;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: var(--theme-main-subtle-background);
  color: color-mix(in srgb, var(--text) 68%, transparent);
}

.message-attachment-deck__card--active .message-attachment-deck__visual {
  border-right: 1px solid var(--theme-main-border);
  border-radius: 0;
}

.message-attachment-deck__visual--image { color: color-mix(in srgb, var(--purple) 62%, var(--text)); }
.message-attachment-deck__visual--code,
.message-attachment-deck__visual--text { color: color-mix(in srgb, var(--text) 76%, transparent); }
.message-attachment-deck__visual--json,
.message-attachment-deck__visual--archive { color: color-mix(in srgb, var(--orange) 58%, var(--text)); }
.message-attachment-deck__visual--pdf { color: color-mix(in srgb, var(--red) 62%, var(--text)); }
.message-attachment-deck__visual--sheet { color: color-mix(in srgb, var(--green) 62%, var(--text)); }
.message-attachment-deck__visual--presentation { color: color-mix(in srgb, var(--purple) 58%, var(--text)); }

.message-attachment-deck__thumbnail {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.message-attachment-deck__extension {
  position: absolute;
  right: var(--space-1);
  bottom: var(--space-1);
  max-width: calc(100% - var(--space-2));
  overflow: hidden;
  border: 1px solid color-mix(in srgb, currentColor 28%, transparent);
  border-radius: 3px;
  padding: 2px 3px;
  background: var(--theme-main-background);
  color: currentColor;
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 760;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-attachment-deck__details {
  display: grid;
  min-width: 0;
  flex: 1 1 auto;
  align-content: center;
  gap: var(--space-1);
  padding: var(--space-2);
  opacity: 0;
  visibility: hidden;
}

.message-attachment-deck__card--active .message-attachment-deck__details {
  opacity: 1;
  visibility: visible;
}

.message-attachment-deck__name,
.message-attachment-deck__meta,
.message-attachment-deck__excerpt {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.message-attachment-deck__name {
  font-size: 12px;
  font-weight: 720;
  line-height: 1.35;
  white-space: nowrap;
}

.message-attachment-deck__meta {
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 10px;
  line-height: 1.3;
  white-space: nowrap;
}

.message-attachment-deck__excerpt {
  display: -webkit-box;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
  white-space: normal;
}

.message-attachment-deck__nav {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 0;
  border-radius: var(--radius-sm);
  padding: 0;
  background: transparent;
  color: color-mix(in srgb, var(--text) 65%, transparent);
}

.message-attachment-deck__nav:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.message-attachment-deck__nav:active:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.message-attachment-deck__nav:disabled {
  opacity: .45;
}

.message-attachment-deck__text-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: grid;
  place-items: center;
  padding: var(--space-4);
  background: color-mix(in srgb, var(--theme-backdrop-text) 20%, transparent);
}

.message-attachment-deck__text-dialog {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  width: min(860px, 92vw);
  height: min(680px, 82vh);
  overflow: hidden;
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: var(--theme-main-background);
  color: var(--theme-main-text);
  box-shadow: var(--shadow-lg);
}

.message-attachment-deck__text-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-height: 42px;
  border-bottom: 1px solid var(--theme-main-border);
  padding: 0 var(--space-2) 0 var(--space-3);
  background: var(--theme-main-subtle-background);
}

.message-attachment-deck__text-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-2);
}

.message-attachment-deck__text-title strong {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-attachment-deck__text-title span {
  color: color-mix(in srgb, var(--theme-main-text) 48%, transparent);
  font-size: 10px;
}

.message-attachment-deck__text-header button {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  place-items: center;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 64%, transparent);
}

.message-attachment-deck__text-header button:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--theme-main-text);
}

.message-attachment-deck__text-content,
.message-attachment-deck__text-state {
  min-width: 0;
  min-height: 0;
  margin: 0;
  overflow: auto;
  padding: var(--space-3);
}

.message-attachment-deck__text-content {
  color: var(--theme-main-text);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  tab-size: 2;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.message-attachment-deck__text-state {
  display: grid;
  place-items: center;
  color: color-mix(in srgb, var(--theme-main-text) 58%, transparent);
  font-size: 12px;
}

.message-attachment-deck__text-state--error { color: color-mix(in srgb, var(--red) 76%, var(--theme-main-text)); }

@media (max-width: 520px) {
  .message-attachment-deck__card--active {
    flex-basis: 184px;
    width: 184px;
  }

}

@media (prefers-reduced-motion: reduce) {
  .message-attachment-deck__card,
  .message-attachment-deck__preview {
    will-change: auto;
  }
}
</style>
