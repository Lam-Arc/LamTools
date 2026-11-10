/**
 * 复合样式组：由多个部件拼起来的真实界面块，一块一页。
 *
 * user:“再把类似于输入栏，ping 环，这种复合样式组给加进去”+
 * (单看一个按钮说明不了问题，要看它和输入、图标、浮层拼在一起的样子)。
 *
 * 地址带 ?only=composer|ping|session|confirm，画廊用独立框分别嵌。
 */
import { createApp, h, reactive, ref } from 'vue'
import PingRing from '@/pet/ui/PingRing.vue'
import CoreConfirmDialog from '@/components/CoreConfirmDialog.vue'
import '@/styles/variables.css'
import '@/styles/base.css'
import '@/styles/sunday-controls.css'
import '@/styles/layout.css'
import '@/styles/library-surface.css'
import '@/styles/optical-glass.css'

const params = new URLSearchParams(location.search)
const ONLY = params.get('only') || 'all'

const PLUS = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>'
const ARROW_UP = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 19V5M5 12l7-7 7 7"/></svg>'
const CHEVRON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>'

function composerBlock() {
  return h('div', { class: 'composer-demo' }, [
    h('div', { class: 'composer-root composer-root--floating' }, [
      h('div', { class: 'floating-composer composer-bar--floating' }, [
        h('div', { class: 'composer-main-card' }, [
          h('div', { class: 'composer-input-row' }, [
            h('textarea', {
              class: 'auto-textarea',
              rows: 2,
              placeholder: '给 Sunday 发消息…',
            }),
          ]),
          h('div', { class: 'composer-bottom' }, [
            h('div', { class: 'tool-row' }, [
              h('button', { class: 'composer-attachment-button', type: 'button', innerHTML: PLUS }),
              h('button', { class: 'btn btn--ghost', type: 'button' }, 'Agent'),
              h('button', { class: 'btn btn--ghost', type: 'button' }, '思考：中'),
            ]),
            h('button', { class: 'core-send-stop-button', type: 'button', innerHTML: ARROW_UP }),
          ]),
        ]),
      ]),
    ]),
  ])
}

function sessionRow() {
  return h('div', { class: 'session-demo' }, [
    h('div', { class: 'session-row-wrap is-active' }, [
      h('span', { class: 'session-row-title' }, '界面场景与复用结论'),
      h('span', { class: 'session-row-meta' }, '刚刚 · 12 条消息'),
      h('button', { class: 'session-menu-button', type: 'button', innerHTML: CHEVRON }),
    ]),
    h('div', { class: 'session-row-wrap' }, [
      h('span', { class: 'session-row-title' }, '样式库做成交互展台'),
      h('span', { class: 'session-row-meta' }, '昨天 · 8 条消息'),
      h('button', { class: 'session-menu-button', type: 'button', innerHTML: CHEVRON }),
    ]),
  ])
}

function pingStub() {
  const sectors = [
    { id: 'question', label: '询问', icon: '?', kind: 'question', enabled: true },
    { id: 'note', label: '记录', icon: '记', kind: 'note', enabled: true },
    { id: 'select', label: '框选', icon: '框', kind: 'select', enabled: true },
    { id: 'chat', label: '对话', icon: '聊', kind: 'chat', enabled: true },
    { id: 'switch', label: '切换', icon: '换', kind: 'switch', enabled: true },
  ]
  const size = { width: 620, height: 460 }
  return {
    ring: reactive({ visible: true, x: size.width / 2, y: size.height / 2, sectors, hovered: '', depth: 0, parentId: '' }),
    overlay: reactive({ x: 0, y: 0, ...size }),
    config: { enabled: true, ping: { radius: 132, ringWidth: 74, hubRadius: 54, background: '', sectors } },
    tiers: reactive({
      expanded: '',
      l2: { visible: false, radius: 0, width: 0, sectors: [], slots: [], hovered: '', projectId: '' },
      l3: { visible: false, radius: 0, width: 0, sectors: [], slots: [], hovered: '', projectId: '' },
    }),
  }
}

createApp({
  setup() {
    const ping = pingStub()
    const confirmOpen = ref(true)

    const blocks: Record<string, () => unknown> = {
      composer: () => h('section', { class: 'block' }, [
        h('header', { class: 'block-head' }, [
          h('h2', {}, '输入栏'),
          h('p', {}, '输入、附件、模式、发送拼在一起，外层是浮起材质'),
        ]),
        h('div', { class: 'stage composer-stage' }, [composerBlock()]),
        h('ul', { class: 'parts' }, [
          h('li', {}, 'floating-composer'),
          h('li', {}, 'auto-textarea'),
          h('li', {}, 'composer-attachment-button'),
          h('li', {}, 'core-send-stop-button'),
        ]),
      ]),
      ping: () => h('section', { class: 'block block--ping' }, [
        h('header', { class: 'block-head' }, [
          h('h2', {}, 'ping 环'),
          h('p', {}, '扇形按数量均分；悬停高亮；中心盘是触发点'),
        ]),
        h('div', { class: 'stage ping-stage' }, [h(PingRing, { ping })]),
      ]),
      session: () => h('section', { class: 'block' }, [
        h('header', { class: 'block-head' }, [
          h('h2', {}, '会话行'),
          h('p', {}, '标题、时间与操作键；选中态和悬停态'),
        ]),
        h('div', { class: 'stage row-stage' }, [sessionRow()]),
      ]),
      confirm: () => h('section', { class: 'block' }, [
        h('header', { class: 'block-head' }, [
          h('h2', {}, '确认弹窗'),
          h('p', {}, '遮罩 + 标题 + 说明 + 两个动作'),
        ]),
        h('div', { class: 'stage dialog-stage' }, [
          h('button', { class: 'btn btn--primary', type: 'button', onClick: () => { confirmOpen.value = true } }, '再打开一次'),
        ]),
        h(CoreConfirmDialog, {
          open: confirmOpen.value,
          title: '从资料库移除',
          detail: '将移除此处的 3 项；文件本身不会被删除。',
          confirmLabel: '移除',
          onCancel: () => { confirmOpen.value = false },
          onConfirm: () => { confirmOpen.value = false },
        }),
      ]),
    }

    if (ONLY !== 'all') {
      return () => h('div', { class: 'composite-lab composite-lab--single' }, [blocks[ONLY]?.() ?? h('p', {}, '未知块')])
    }
    return () => h('div', { class: 'composite-lab' }, Object.values(blocks).map(build => build()))
  },
}).mount('#app')
