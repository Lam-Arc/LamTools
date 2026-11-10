/**
 * 资料库 · 卡片预览（视觉稿）。
 *
 * 用真实的 MaterialsView 渲染假数据，专看三件事：
 * 样式表的缩略图是不是真渲染、标签能不能点、评分能不能点。
 * 没有后端也能跑：样式原文用 Vite 的 ?raw 读进来当 artifact.text 的返回。
 */
import { createApp, h, ref } from 'vue'
import MaterialsView from '@/components/MaterialsView.vue'
import '@/styles/variables.css'
import '@/styles/base.css'
import '@/styles/layout.css'
import '@/styles/library-surface.css'
import '@/styles/library-styles.css'
import '@/styles/sunday-controls.css'

const params = new URLSearchParams(location.search)
if (params.get('motion') === 'off') document.documentElement.classList.add('lab-no-motion')
const theme = ref<'dark' | 'light'>(params.get('theme') === 'light' ? 'light' : 'dark')

const RAW = import.meta.glob('../styles/*.css', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

function textOf(name: string): string {
  const key = Object.keys(RAW).find(path => path.endsWith(`/${name}`))
  return key ? RAW[key] : ''
}

interface Row {
  artifact_id: string
  name: string
  path: string
  uri: string
  kind: string
  role: string
  mime_type: string
  favorite: boolean
  deleted: boolean
  folder: string
  updated_at: string
  tags: string[]
  rating: number
  usage?: { entry?: string; requires?: string; example?: string }
  usage_count?: number
}

import snapshot from './styles-snapshot.json'

// 真实数据：这份快照是登记脚本从资料库里导出来的，标签是按类名算的。
const files: Array<[string, string[], number]> = (snapshot as Array<{ name: string; tags: string[]; rating: number }>)
  .map(row => [row.name, row.tags, row.rating] as [string, string[], number])

const LEGACY_FILES: Array<[string, string[], number]> = [
  ['library-surface.css', ['css', 'card', 'button'], 5],
  ['sunday-controls.css', ['css', 'button', 'switch'], 4],
  ['chat-thread-cards.css', ['css', 'card'], 3],
  ['plugin-editor-cards.css', ['css', 'card'], 0],
  ['variables.css', ['css', 'token'], 5],
  ['layout.css', ['css', 'layout'], 2],
  ['core-model-catalog.css', ['css', 'card', 'chart'], 0],
  ['study.css', ['css'], 0],
]

const source = files.length ? files : LEGACY_FILES
// 用法与取用次数是这次新加的展示面：没有它们，人看不出素材该怎么用、有没有人用。
const LAB_USAGE: Record<string, { entry: string; requires: string }> = {
  'optical-glass.css': { entry: '.optical-glass--low-trans', requires: '父级要有可见底色' },
  'sunday-controls.css': { entry: '.btn.btn--primary', requires: 'min-height 32px' },
  'library-surface.css': { entry: '.library-button', requires: '--text 由面板提供' },
}

const items = ref<Row[]>(source.map(([name, tags, rating], index) => ({
  usage: LAB_USAGE[name] ?? {},
  usage_count: LAB_USAGE[name] ? index + 1 : 0,
  artifact_id: `lab-${index}`,
  name,
  path: `workspace://core/ui/src/styles/${name}`,
  uri: `workspace://core/ui/src/styles/${name}`,
  kind: 'file',
  role: 'deliverable',
  mime_type: 'text/css',
  favorite: index < 2,
  deleted: false,
  folder: index < 4 ? '界面样式' : '',
  updated_at: new Date(Date.now() - index * 86400000).toISOString(),
  tags,
  rating,
})))

const requestRpc = async (method: string, payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> => {
  if (method === 'artifact.list') return { artifacts: items.value }
  if (method === 'artifact.stats') return { count: items.value.length, bytes: 240_000 }
  if (method === 'artifact.text') {
    const row = items.value.find(item => item.artifact_id === payload.artifact_id)
    return { text: row ? textOf(row.name) : '', path: row?.path ?? '' }
  }
  if (method === 'artifact.rating') {
    const row = items.value.find(item => item.artifact_id === payload.artifact_id)
    if (row) row.rating = Number(payload.rating ?? 0)
    return { artifact: row }
  }
  if (method === 'artifact.tags') {
    const row = items.value.find(item => item.artifact_id === payload.artifact_id)
    if (row) row.tags = (payload.tags as string[]) ?? []
    return { artifact: row }
  }
  if (method === 'artifact.favorite') {
    const row = items.value.find(item => item.artifact_id === payload.artifact_id)
    if (row) row.favorite = Boolean(payload.favorite)
    return { artifact: row }
  }
  if (method === 'artifact.folder') return {}
  return {}
}

createApp({
  setup() {
    return () => h('div', { class: 'lab-host', 'data-theme': theme.value }, [
      h('div', { class: 'library-surface lab-surface', 'data-ui-id': 'library.root' }, [
        h(MaterialsView, {
          projectId: 'lab-project',
          workRoot: '/lab',
          requestRpc,
          transport: {} as never,
          uploading: false,
          uploadFiles: async () => {},
          artifactSignal: 0,
        }),
      ]),
      h('div', { class: 'lab-chrome' }, [
        h('button', {
          type: 'button',
          onClick: () => { theme.value = theme.value === 'dark' ? 'light' : 'dark' },
        }, theme.value === 'dark' ? '浅色' : '深色'),
      ]),
    ])
  },
}).mount('#app')

// 截图用：?compare=1 自动选中前两件并打开对比面板。
if (params.get('compare') === '1') {
  let picked = false
  const tick = window.setInterval(() => {
    const checks = document.querySelectorAll<HTMLElement>('[data-material-check]')
    if (!picked && checks.length >= 2) {
      checks[0].click()
      checks[1].click()
      picked = true
      return
    }
    const button = document.querySelector<HTMLButtonElement>('[data-materials-compare-open]')
    if (button && !button.disabled) {
      button.click()
      window.clearInterval(tick)
    }
  }, 120)
  window.setTimeout(() => window.clearInterval(tick), 8000)
}
