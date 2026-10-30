<template>
  <!-- user:“插件页再加上插件市场的界面…你自己设计”+(沿用现有工作台主题，以插件用途、版本和安装状态组织市场)。 -->
  <section class="market" :aria-label="t('插件市场')" :aria-busy="loading || Boolean(busy)">
    <div class="market-heading">
      <div><h2>{{ t('从 GitHub 安装插件') }}</h2><p>{{ t('独立发布，按需安装。网络拓展可用时自动优化下载，安装前校验文件。') }}</p></div>
      <button class="btn btn--secondary" type="button" :disabled="loading || Boolean(busy)" @click="load"><RefreshCw :size="14" :class="{ spin: loading }" />{{ t('检查更新') }}</button>
    </div>
    <p v-if="error" class="market-error" role="alert"><CircleAlert :size="15" />{{ error }}</p>
    <p v-if="cached" class="market-note" role="status">{{ t('当前显示缓存目录；安装时会重新核对 GitHub 最新发布。') }}</p>
    <p v-if="notice" class="market-note" role="status">{{ notice }}</p>
    <div v-if="loading && !plugins.length" class="market-loading" role="status"><LoaderCircle class="spin" :size="18" />{{ t('正在连接插件市场…') }}</div>
    <ul v-else class="market-list">
      <li v-for="plugin in plugins" :key="plugin.id" class="market-row" :data-market-plugin="plugin.id">
        <div class="market-mark" aria-hidden="true"><component :is="plugin.id === 'qq-bot' ? MessagesSquare : Clapperboard" :size="26" :stroke-width="1.5" /></div>
        <div class="market-content">
          <div class="market-title"><h3>{{ t(plugin.title) }}</h3><span>{{ t(plugin.category) }}</span></div>
          <p>{{ t(plugin.description) }}</p>
          <ul class="market-capabilities" :aria-label="t('插件能力')"><li v-for="item in plugin.capabilities" :key="item">{{ t(item) }}</li></ul>
          <div class="market-meta"><span>{{ plugin.version ? `v${plugin.version}` : t('版本暂不可用') }}</span><span v-if="plugin.installed_version">{{ t('已安装') }} v{{ plugin.installed_version }}</span><button class="btn btn--ghost" type="button" @click="openExternalUrl(plugin.repository_url)"><Github :size="13" />{{ t('源代码与许可证') }}<ArrowUpRight :size="12" /></button></div>
        </div>
        <div class="market-action">
          <button class="btn btn--secondary" :class="{ primary: !plugin.installed_version || plugin.update_available }" type="button"
            :data-market-action="plugin.id" :disabled="Boolean(busy) || !plugin.installable || Boolean(plugin.installed_version && !plugin.update_available)" @click="install(plugin)">
            <LoaderCircle v-if="busy === plugin.id" :size="14" class="spin" /><Check v-else-if="plugin.installed_version && !plugin.update_available" :size="14" /><Download v-else :size="14" />
            {{ busy === plugin.id ? t('下载并校验中…') : !plugin.installable ? t('暂不可用') : plugin.update_available ? t('更新') : plugin.installed_version ? t('已安装') : t('安装') }}
          </button>
          <span v-if="plugin.update_available">{{ t('有新版本') }}</span>
        </div>
      </li>
    </ul>
    <div v-if="!loading && !plugins.length" class="market-loading"><p>{{ t('暂时无法获取市场目录，请检查网络后重试。') }}</p><button class="btn btn--secondary" type="button" @click="load">{{ t('重新连接') }}</button></div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowUpRight, Check, CircleAlert, Clapperboard, Download, Github, LoaderCircle, MessagesSquare, RefreshCw } from 'lucide-vue-next'
import { t } from '@/i18n/index'
import { openExternalUrl } from '@/helpers/openUrl'

interface MarketPlugin { id: string; title: string; description: string; category: string; capabilities: string[]; version: string; installed_version: string; update_available: boolean; installable: boolean; repository_url: string }
const props = defineProps<{ requestRpc: (method: string, params?: Record<string, unknown>, timeoutMs?: number) => Promise<Record<string, unknown>> }>()
const emit = defineEmits<{ changed: [] }>()
const plugins = ref<MarketPlugin[]>([])
const loading = ref(false)
const busy = ref('')
const error = ref('')
const notice = ref('')
const cached = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('plugin.market.list', {})
    plugins.value = Array.isArray(result.plugins) ? result.plugins as MarketPlugin[] : []
    cached.value = result.source === 'cache'
    // user:“注意一下插件市场，如果没有或者没做好的话给它做好”+(目录占位行不能隐藏实际连接错误)。
    if (result.error) error.value = String(result.error)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally { loading.value = false }
}

async function install(plugin: MarketPlugin) {
  if (busy.value || loading.value) return
  busy.value = plugin.id
  error.value = ''; notice.value = ''
  try {
    // user:“从 GitHub 等平台下载并安装”+(安装允许下载和后端验证完成，避免沿用普通查询的 30 秒等待上限)。
    const result = await props.requestRpc('plugin.market.install', { name: plugin.id }, 180_000)
    if (result.error) throw new Error(String(result.error))
    // user:“注意一下插件市场，如果没有或者没做好的话给它做好”+(只有已就绪的安装结果才能显示成功)。
    const backend = result.backend as Record<string, unknown> | undefined
    const state = String(backend?.state || '')
    // user:“注意一下插件市场，如果没有或者没做好的话给它做好”+(更新保留禁用状态，安全模式不运行插件，均不属于启动失败)。
    if (result.available === false && state !== 'disabled' && state !== 'safe_mode') {
      throw new Error(String(backend?.error || t('插件启动失败，请在“已安装”中查看详情。')))
    }
    emit('changed')
    await load()
    notice.value = state === 'disabled' ? t('插件已更新，仍保持禁用。')
      : state === 'safe_mode' ? t('插件已安装，安全模式下暂不运行。')
      : t('插件已安装，可在“已安装”中配置和管理。')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally { busy.value = '' }
}
onMounted(load)
</script>

<style scoped>
.market { --text: var(--theme-main-text); container-type: inline-size; color: var(--text); padding-block: var(--space-4); }
.market-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); margin-bottom: var(--space-5); }
.market-heading h2 { margin: 0 0 var(--space-2); font-size: 18px; font-weight: 650; }
.market-heading p, .market-content p { margin: 0; color: color-mix(in srgb, var(--text) 65%, transparent); line-height: 1.65; max-width: 65ch; }
.market-list, .market-capabilities { padding: 0; margin: 0; list-style: none; }
.market-row { display: grid; grid-template-columns: 48px minmax(0, 1fr) auto; gap: var(--space-4); align-items: start; padding-block: var(--space-5); border-top: 1px solid var(--theme-main-border); }
.market-mark { width: 48px; height: 48px; display: grid; place-items: center; border-radius: var(--radius); background: var(--theme-main-soft-background); }
.market-title { display: flex; gap: var(--space-3); align-items: baseline; margin-bottom: var(--space-2); }
.market-title h3 { margin: 0; font-size: 16px; font-weight: 650; }
.market-title span, .market-meta, .market-action > span { font-size: 12px; color: color-mix(in srgb, var(--text) 65%, transparent); }
.market-capabilities { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-top: var(--space-3); font-size: 12px; }
.market-meta { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); margin-top: var(--space-3); font-variant-numeric: tabular-nums; }
.market-meta button { display: inline-flex; align-items: center; gap: var(--space-1); }
.market-action { display: flex; flex-direction: column; align-items: flex-end; gap: var(--space-2); padding-top: var(--space-1); }
.market-error, .market-note { display: flex; align-items: center; gap: var(--space-2); padding-block: var(--space-3); line-height: 1.6; }
.market-error { color: var(--red); }
.market-note { color: color-mix(in srgb, var(--text) 65%, transparent); font-size: 13px; }
.market-loading { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-5) 0; }
.spin { animation: market-spin 1s linear infinite; }
@keyframes market-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
@container (max-width: 620px) { .market-row { grid-template-columns: 40px minmax(0, 1fr); } .market-action { grid-column: 2; align-items: flex-start; } .market-heading { align-items: flex-start; flex-wrap: wrap; } }
</style>
