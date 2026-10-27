import { createApp, h, reactive } from 'vue'
import MarkdownRenderer from '../../src/components/MarkdownRenderer.vue'

// user:“不要出错”+(用真实浏览器验证按钮、脚本隔离与主题传递)。
const html = `<button id="counter" onclick="this.textContent=String(Number(this.textContent)+1)">0</button>
<input id="amount" type="range" min="0" max="100" value="10" oninput="document.getElementById('value').textContent=this.value"><output id="value">10</output>
<script>
try { parent.document.body.dataset.escaped='yes'; } catch { document.body.dataset.isolated='yes'; }
try { localStorage.setItem('escape','yes'); } catch { document.body.dataset.storageBlocked='yes'; }
window.fetch('http://127.0.0.1:1/forbidden').catch(() => { document.body.dataset.networkBlocked='yes'; });
</script>`
const fence = (source: string) => '\n```interactive-html\n' + source + '\n```'
const content = ':::note 说明\n支持 **格式化内容**\n:::\n\n:::details 查看详情\n详情正文\n:::\n\n:::writing{variant="document" title="验收成稿"}\n原始正文\n:::\n' + fence(html)
const state = reactive({ content, streaming: false })
Object.assign(window, { blockAcceptance: { state, fence, content } })
createApp({ render: () => h('main', { style: {
  '--theme-main-soft-background': 'rgb(30, 30, 30)', '--theme-main-text': 'rgb(240, 240, 240)',
  '--theme-control-background': 'rgb(220, 220, 220)', '--theme-control-text': 'rgb(25, 25, 25)',
  '--theme-main-border': 'rgb(80, 80, 80)', '--space-1': '4px', '--space-2': '8px', '--space-3': '12px', '--radius': '12px', '--radius-sm': '6px',
} }, [h(MarkdownRenderer, { content: state.content, streaming: state.streaming, interactive: true })]) }).mount('#app')
