<template>
  <!-- user:“重做一下插件页面，精致高级、高可交互性，动画流畅自然”+
       插件页是一块可搜索、可筛选、可展开的工作台：每张卡片承载一个插件的
       身份、运行状态、能力和入口；安装、依赖、配置、卸载都在卡片内完成，
       诊断信息收在页尾折叠区，不再把所有控件平铺成一行。 -->
  <section ref="pageEl" class="settings-panel plugin-page">
    <!-- user:“上方那个标题只用保留两个字‘插件’，而且字号不用太大，以简洁为主”+
         页头只留标题与右侧操作，不再放图标和说明句。 -->
    <header class="plugin-hero">
      <h1 class="plugin-hero-title">{{ t("插件") }}</h1>

      <div class="plugin-hero-actions">
        <div class="plugin-stats">
          <span class="plugin-stat">{{ t("{0} 个插件", { 0: plugins.length }) }}</span>
          <span class="plugin-stat">
            <i class="plugin-stat-dot is-on" aria-hidden="true"></i>
            {{ t("{0} 个已启用", { 0: enabledCount }) }}
          </span>
          <span v-if="attentionCount" class="plugin-stat is-warning">
            <i class="plugin-stat-dot is-warn" aria-hidden="true"></i>
            {{ t("{0} 个需要处理", { 0: attentionCount }) }}
          </span>
        </div>
        <button
          class="small-btn primary plugin-install-toggle"
          type="button"
          data-install-toggle
          :aria-expanded="installOpen"
          @click="toggleInstall"
        >
          <component :is="installOpen ? X : Plus" :size="14" :stroke-width="2" aria-hidden="true" />
          <span>{{ installOpen ? t("收起安装") : t("安装插件") }}</span>
        </button>
        <button
          class="plugin-icon-button"
          type="button"
          data-plugin-refresh
          :aria-label="t('刷新')"
          :title="t('刷新')"
          @click="fetchPlugins()"
        >
          <RefreshCw :size="15" :class="{ spin: refreshing }" aria-hidden="true" />
        </button>
      </div>
    </header>
    <!-- user:“插件页再加上插件市场的界面”+(市场与已安装并列，原有管理功能保持可达)。 -->
    <SundaySegmented v-model="pluginSection" :options="[{ value: 'installed', label: t('已安装') }, { value: 'market', label: t('插件市场') }]" :label="t('插件页面')" />
    <PluginMarket v-if="pluginSection === 'market'" :request-rpc="props.requestRpc" @changed="fetchPlugins" />
    <div v-show="pluginSection === 'installed'">

    <!-- 安装托盘：默认不渲染，点「安装插件」平滑展开；三种来源共用同一条流程。
         收起时不占网格行，标题和搜索栏之间不会留下空档。 -->
    <Transition name="install-tray">
      <div v-if="installOpen" class="install-tray">
        <div class="install-tray-clip">
        <form class="install-tray-inner preview-install" @submit.prevent="submitInstall(false)">
          <div class="install-tray-head">
            <div>
              <strong>{{ t("安装或更新插件") }}</strong>
              <p>{{ t("本地目录、压缩包或链接，三种来源共用一条流程。") }}</p>
            </div>
            <span v-if="installBusy" class="install-busy" role="status">
              <LoaderCircle :size="13" class="spin" aria-hidden="true" />
              {{ t("处理中…") }}
            </span>
          </div>

          <div class="install-source" role="radiogroup" :aria-label="t('安装来源')">
            <label
              v-for="option in installSources"
              :key="option.value"
              class="install-source-option"
              :class="{ 'is-active': installSource === option.value }"
            >
              <input v-model="installSource" class="sr-only" type="radio" :value="option.value" />
              <component :is="option.icon" :size="13" :stroke-width="1.9" aria-hidden="true" />
              <span>{{ t(option.label) }}</span>
            </label>
          </div>

          <div class="install-fields">
            <label class="install-field">
              <component :is="sourceIcon" :size="14" :stroke-width="1.8" class="install-field-icon" aria-hidden="true" />
              <input
                ref="installInputEl"
                v-model="installTarget"
                class="install-input"
                type="text"
                :placeholder="installPlaceholder"
                :aria-label="t('安装来源地址')"
                spellcheck="false"
                autocomplete="off"
              />
            </label>
            <label v-if="installSource === 'url'" class="install-field install-sha-field">
              <ShieldCheck :size="14" :stroke-width="1.8" class="install-field-icon" aria-hidden="true" />
              <input
                v-model="installSha256"
                class="install-sha"
                type="text"
                :placeholder="t('sha256（可选）')"
                :aria-label="t('sha256（可选）')"
                spellcheck="false"
                autocomplete="off"
              />
            </label>
            <button class="small-btn primary install-submit" type="submit" :disabled="installBusy || !installTarget.trim()">
              {{ t("安装") }}
            </button>
            <button
              class="small-btn quiet install-update"
              type="button"
              data-install-update
              :disabled="installBusy || !installTarget.trim()"
              @click="submitInstall(true)"
            >
              {{ t("更新") }}
            </button>
          </div>
          <p class="install-hint">{{ t("更新会覆盖同名插件，data 目录会保留。") }}</p>
        </form>
        </div>
      </div>
    </Transition>

    <div v-if="error || notice || restartRequired" class="plugin-feedback-stack" aria-live="polite">
      <p v-if="error" class="plugin-feedback is-error" role="alert">
        <CircleAlert :size="14" :stroke-width="1.9" aria-hidden="true" />
        <span>{{ error }}</span>
        <button class="feedback-dismiss" type="button" :aria-label="t('关闭')" @click="error = ''">
          <X :size="13" aria-hidden="true" />
        </button>
      </p>
      <p v-if="notice" class="plugin-feedback" :class="noticeTone === 'warning' ? 'is-warning' : 'is-success'" role="status">
        <Info v-if="noticeTone === 'warning'" :size="14" :stroke-width="1.9" aria-hidden="true" />
        <CircleCheck v-else :size="14" :stroke-width="1.9" aria-hidden="true" />
        <span>{{ notice }}</span>
        <button class="feedback-dismiss" type="button" :aria-label="t('关闭')" @click="notice = ''">
          <X :size="13" aria-hidden="true" />
        </button>
      </p>
      <p v-if="restartRequired" class="plugin-feedback is-warning" role="status">
        <Info :size="14" :stroke-width="1.9" aria-hidden="true" />
        <span>{{ t('插件代码已更新，重启应用后模块覆盖和全局脚本将生效。') }}</span>
        <button class="feedback-dismiss" type="button" :aria-label="t('关闭')" @click="restartRequired = false">
          <X :size="13" aria-hidden="true" />
        </button>
      </p>
    </div>

    <div class="plugin-toolbar">
      <div class="plugin-search">
        <Search :size="15" :stroke-width="1.9" class="plugin-search-icon" aria-hidden="true" />
        <input
          ref="searchInputEl"
          v-model="query"
          data-plugin-search
          type="text"
          :placeholder="t('搜索插件、能力或路径')"
          :aria-label="t('搜索插件、能力或路径')"
          spellcheck="false"
          autocomplete="off"
          @keydown.esc="clearSearch"
        />
        <button v-if="query" class="plugin-search-clear" type="button" :aria-label="t('清除搜索')" @click="clearSearch">
          <X :size="13" aria-hidden="true" />
        </button>
        <kbd v-else class="plugin-search-key" aria-hidden="true">/</kbd>
      </div>

      <div class="plugin-filters" role="group" :aria-label="t('筛选插件')">
        <button
          v-for="item in filterChips"
          :key="item.id"
          class="plugin-filter"
          :class="{ 'is-active': filter === item.id }"
          type="button"
          :data-filter="item.id"
          :aria-pressed="filter === item.id"
          :disabled="item.id !== 'all' && item.count === 0"
          @click="filter = item.id"
        >
          {{ item.label }}<span class="plugin-filter-count">{{ item.count }}</span>
        </button>
      </div>

      <span class="plugin-result-count">{{ t('{0} / {1}', { 0: filteredPlugins.length, 1: plugins.length }) }}</span>
    </div>

    <div v-if="loading" class="plugin-grid plugin-grid--skeleton" aria-hidden="true">
      <article v-for="index in 3" :key="index" class="plugin-card plugin-skeleton">
        <div class="skeleton-head">
          <span class="skeleton-block"></span>
          <span class="skeleton-lines">
            <span class="skeleton-line is-wide"></span>
            <span class="skeleton-line is-narrow"></span>
          </span>
        </div>
        <span class="skeleton-line is-wide"></span>
        <span class="skeleton-line is-medium"></span>
        <span class="skeleton-chips"><i></i><i></i><i></i></span>
        <span class="skeleton-line is-short"></span>
      </article>
    </div>

    <div v-else-if="!plugins.length && error" class="plugin-empty">
      <span class="plugin-empty-mark is-error" aria-hidden="true"><CircleAlert :size="20" :stroke-width="1.6" /></span>
      <h2>{{ t("无法加载插件") }}</h2>
      <p>{{ t("检查后台连接后再试一次。") }}</p>
      <button class="small-btn primary" type="button" data-retry-load @click="fetchPlugins()">
        <RotateCw :size="14" aria-hidden="true" />
        {{ t("再试一次") }}
      </button>
    </div>

    <div v-else-if="!plugins.length" class="plugin-empty">
      <span class="plugin-empty-mark" aria-hidden="true"><Puzzle :size="20" :stroke-width="1.6" /></span>
      <h2>{{ t("还没有插件") }}</h2>
      <p>{{ t("在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。") }}</p>
      <button class="small-btn primary" type="button" @click="toggleInstall">
        <Plus :size="14" aria-hidden="true" />
        {{ t("安装插件") }}
      </button>
    </div>

    <div v-else-if="!filteredPlugins.length" class="plugin-empty">
      <span class="plugin-empty-mark" aria-hidden="true"><SearchX :size="20" :stroke-width="1.6" /></span>
      <h2>{{ t("没有匹配的插件") }}</h2>
      <p>{{ t("换个关键词，或清除筛选条件。") }}</p>
      <button class="small-btn" type="button" data-clear-filters @click="clearFilters">
        {{ t("清除筛选") }}
      </button>
    </div>

    <div v-else class="plugin-grid">
      <TransitionGroup
        v-for="(column, columnIndex) in pluginColumns"
        :key="`column-${columnIndex}`"
        tag="div"
        name="plugin-card"
        class="plugin-column"
        appear
      >
      <article
        v-for="plugin in column"
        :key="plugin.name"
        class="plugin-card"
        :class="{
          'is-disabled': !plugin.enabled,
          'is-attention': needsAttention(plugin),
          'is-busy': busy === plugin.name,
        }"
        :data-plugin="plugin.name"
        :style="{ '--plugin-accent': accentFor(plugin.name), '--card-index': cardIndexes.get(plugin.name) ?? 0 }"
      >
        <header class="plugin-card-head">
          <span class="plugin-glyph" aria-hidden="true">{{ glyphFor(plugin.name) }}</span>
          <div class="plugin-identity">
            <div class="plugin-name-line">
              <strong :title="plugin.name">{{ plugin.name }}</strong>
              <span class="plugin-version">v{{ plugin.version }}</span>
            </div>
            <div class="plugin-meta-line">
              <span class="plugin-scope" :title="plugin.scope">{{ scopeLabel(plugin.scope) }}</span>
              <span class="plugin-meta-sep" aria-hidden="true">·</span>
              <span class="plugin-root" :title="plugin.root">{{ plugin.root }}</span>
            </div>
          </div>
          <button
            class="plugin-switch"
            type="button"
            role="switch"
            :aria-checked="plugin.enabled"
            :aria-label="plugin.enabled ? t('禁用 {0}', { 0: plugin.name }) : t('启用 {0}', { 0: plugin.name })"
            :data-toggle-for="plugin.name"
            :disabled="busy === plugin.name"
            @click="toggle(plugin)"
          >
            <span class="plugin-switch-thumb">
              <LoaderCircle v-if="busy === plugin.name" :size="11" :stroke-width="2.4" class="spin" aria-hidden="true" />
            </span>
          </button>
        </header>

        <p class="plugin-description" :class="{ 'is-empty': !plugin.description }">
          {{ plugin.description || t("没有描述") }}
        </p>

        <div class="plugin-status-row" :class="`is-${statusOf(plugin).tone}`">
          <span class="plugin-status-dot" aria-hidden="true"></span>
          <span class="plugin-status-label">{{ statusOf(plugin).label }}</span>
          <span v-if="statusDetail(plugin)" class="plugin-status-detail" :title="statusDetail(plugin)">
            {{ statusDetail(plugin) }}
          </span>
          <button
            v-if="plugin.enabled && plugin.available === false && plugin.backend?.state === 'failed'"
            class="plugin-retry"
            type="button"
            :data-retry-for="plugin.name"
            :disabled="busy === plugin.name"
            @click="retry(plugin)"
          >
            <RotateCw :size="12" :stroke-width="2" aria-hidden="true" />
            {{ t("重试启动") }}
          </button>
        </div>

        <p v-if="plugin.capability_error" class="plugin-alert" role="alert">
          <ShieldAlert :size="13" :stroke-width="1.9" aria-hidden="true" />
          <span>{{ t("声明错误") }}：{{ plugin.capability_error }}</span>
        </p>

        <div class="plugin-capabilities">
          <span
            v-for="capability in capabilityChips(plugin)"
            :key="capability.key"
            class="plugin-capability"
            :title="capability.detail"
            :aria-label="capability.detail"
          >
            <component :is="capability.icon" :size="12" :stroke-width="1.9" aria-hidden="true" />
            <span>{{ capability.label }} {{ capability.count }}</span>
          </span>
          <span
            v-if="!capabilityChips(plugin).length && !plugin.capability_error"
            class="plugin-capability is-empty"
          >
            {{ t("未声明能力") }}
          </span>
        </div>

        <div v-if="windowsFor(plugin.name).length || pagesFor(plugin.name).length" class="plugin-entries">
          <span class="plugin-entries-label">{{ t("入口") }}</span>
          <button
            v-for="window in windowsFor(plugin.name)"
            :key="`window:${window.id}`"
            class="plugin-entry"
            type="button"
            :data-window-for="plugin.name"
            :title="t('打开窗口 {0}', { 0: window.title })"
            @click="openWindow(window)"
          >
            <AppWindow :size="12" :stroke-width="1.9" aria-hidden="true" />
            <span>{{ window.title }}</span>
          </button>
          <button
            v-for="page in pagesFor(plugin.name)"
            :key="`page:${page.id}`"
            class="plugin-entry"
            type="button"
            :data-open-plugin-page="page.id"
            :disabled="!splitWorkspace || !plugin.enabled || busy === plugin.name"
            :title="t('分屏打开 {0}', { 0: page.title })"
            @click="splitWorkspace?.openPluginPage(page)"
          >
            <LayoutPanelLeft :size="12" :stroke-width="1.9" aria-hidden="true" />
            <span>{{ page.title }}</span>
          </button>
        </div>

        <footer class="plugin-card-actions">
          <button
            class="plugin-action"
            :class="{ 'is-active': configuring === plugin.name }"
            type="button"
            :data-config-for="plugin.name"
            :aria-expanded="configuring === plugin.name"
            @click="toggleConfig(plugin, $event)"
          >
            <SlidersHorizontal :size="13" :stroke-width="1.9" aria-hidden="true" />
            <span>{{ t("配置") }}</span>
            <ChevronDown :size="12" class="plugin-action-chevron" aria-hidden="true" />
          </button>
          <button
            class="plugin-action"
            type="button"
            :data-deps-for="plugin.name"
            :disabled="depsBusy === plugin.name"
            @click="checkDeps(plugin)"
          >
            <LoaderCircle v-if="depsBusy === plugin.name" :size="13" class="spin" aria-hidden="true" />
            <PackageCheck v-else :size="13" :stroke-width="1.9" aria-hidden="true" />
            <span>{{ t("依赖") }}</span>
          </button>
          <span class="plugin-action-spacer" aria-hidden="true"></span>
          <button
            class="plugin-icon-action"
            type="button"
            data-copy-root
            :data-copy-for="plugin.name"
            :aria-label="copiedPlugin === plugin.name ? t('已复制') : t('复制安装路径')"
            :title="copiedPlugin === plugin.name ? t('已复制') : t('复制安装路径')"
            @click="copyRoot(plugin)"
          >
            <Check v-if="copiedPlugin === plugin.name" :size="14" :stroke-width="2" aria-hidden="true" />
            <Copy v-else :size="14" :stroke-width="1.9" aria-hidden="true" />
          </button>
          <button
            class="plugin-icon-action is-danger"
            type="button"
            :data-uninstall-for="plugin.name"
            :aria-label="t('卸载 {0}', { 0: plugin.name })"
            :title="t('卸载')"
            @click="askUninstall(plugin)"
          >
            <Trash2 :size="14" :stroke-width="1.9" aria-hidden="true" />
          </button>
        </footer>

        <Transition name="plugin-drawer">
          <div v-if="configuring === plugin.name || depsFor(plugin.name)" class="plugin-drawer">
            <div class="plugin-drawer-inner">
              <div v-if="configuring === plugin.name" class="plugin-drawer-section">
                <span class="plugin-drawer-label">
                  <SlidersHorizontal :size="12" :stroke-width="1.9" aria-hidden="true" />
                  {{ t("插件配置") }}
                </span>
                <PluginConfigPanel
                  :plugin-name="plugin.name"
                  :version="plugin.version"
                  :description="plugin.description"
                  :request-rpc="props.requestRpc"
                  :show-identity="false"
                />
              </div>
              <p
                v-if="depsFor(plugin.name)"
                class="preview-deps plugin-deps"
                :class="{ 'is-missing': depsMissing(plugin.name) }"
              >
                <PackageCheck :size="13" :stroke-width="1.9" aria-hidden="true" />
                <span>{{ depsFor(plugin.name) }}</span>
              </p>
            </div>
          </div>
        </Transition>
      </article>
      </TransitionGroup>
    </div>

    <section class="plugin-diagnostics" :class="{ 'is-open': diagnosticsOpen }">
      <button
        class="plugin-diagnostics-head"
        type="button"
        data-diagnostics-toggle
        :aria-expanded="diagnosticsOpen"
        @click="diagnosticsOpen = !diagnosticsOpen"
      >
        <span class="plugin-diagnostics-mark" aria-hidden="true">
          <Wrench :size="15" :stroke-width="1.8" />
        </span>
        <span class="plugin-diagnostics-copy">
          <strong>{{ t("诊断与行为表") }}</strong>
          <small>{{ t("行为表查询与加载错误") }}</small>
        </span>
        <span v-if="loadErrors.length" class="plugin-diagnostics-badge">{{ loadErrors.length }}</span>
        <ChevronDown :size="15" class="plugin-diagnostics-chevron" aria-hidden="true" />
      </button>

      <div class="plugin-diagnostics-body" :inert="!diagnosticsOpen">
        <div class="plugin-diagnostics-clip">
          <div class="plugin-diagnostics-inner">
            <form class="behavior-form" @submit.prevent="searchBehavior">
              <label class="behavior-label" :for="behaviorInputId">{{ t("查询行为表") }}</label>
              <div class="behavior-row">
                <input
                  :id="behaviorInputId"
                  v-model="behaviorQuery"
                  class="behavior-input"
                  type="text"
                  :placeholder="t('模块名或片段（如 prompt、plugin_system.host）')"
                  spellcheck="false"
                  autocomplete="off"
                />
                <button class="small-btn" type="submit" :disabled="!behaviorQuery.trim()">
                  <Search :size="13" :stroke-width="1.9" aria-hidden="true" />
                  {{ t("查询") }}
                </button>
                <span v-if="behaviorTotal >= 0" class="behavior-total">
                  {{ t("{0} 条匹配", { 0: behaviorTotal }) }}
                </span>
              </div>
            </form>

            <ul v-if="behaviorEntries.length" class="behavior-results">
              <li v-for="entry in behaviorEntries" :key="entry.module" class="behavior-result">
                <code>{{ entry.module }}</code>
                <span class="behavior-owner" :class="{ 'is-kernel': entry.ownership === 'kernel' }">
                  {{ entry.ownership === 'kernel' ? t('内核（不可替换）') : t('可替换模块') }}
                </span>
                <span class="behavior-layer">{{ entry.layer }}</span>
              </li>
            </ul>

            <div class="load-errors">
              <div class="load-errors-head">
                <strong>{{ t("加载错误 {0}", { 0: loadErrors.length }) }}</strong>
              </div>
              <ul v-if="loadErrors.length">
                <li v-for="item in loadErrors" :key="item.path">
                  <span class="load-error-name">{{ item.name }}</span>
                  <code class="load-error-message">{{ item.error }}</code>
                  <small class="load-error-path">{{ item.path }}</small>
                </li>
              </ul>
              <p v-else class="muted">{{ t("没有加载错误。") }}</p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <PluginSystemContributions :request-rpc="props.requestRpc" region="settings" />

    <CoreConfirmDialog
      :open="Boolean(pendingUninstall)"
      :title="t('卸载插件？')"
      :detail="uninstallDetail"
      :error="uninstallError"
      :loading="uninstalling"
      :confirm-label="t('卸载')"
      @cancel="closeUninstall"
      @confirm="confirmUninstall"
    />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, type Component } from 'vue'
import {
  AppWindow,
  Check,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  Copy,
  FileArchive,
  FileCode2,
  FolderOpen,
  Info,
  LayoutPanelLeft,
  Link2,
  LoaderCircle,
  PackageCheck,
  Plug,
  Plus,
  Puzzle,
  RefreshCw,
  RotateCw,
  Search,
  SearchX,
  Server,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Terminal,
  Trash2,
  Wrench,
  X,
} from 'lucide-vue-next'

import CoreConfirmDialog from '@/components/CoreConfirmDialog.vue'
import SundaySegmented from '@/components/SundaySegmented.vue'
import PluginMarket from '@/components/PluginMarket.vue'
import PluginConfigPanel from '@/components/PluginConfigPanel.vue'
import PluginSystemContributions from '@/components/PluginSystemContributions.vue'
import { copyText } from '@/helpers/clipboard.ts'
import { t } from '@/i18n/index.ts'
import { contributionState, setPluginPageEntries, ensureContributions } from '@/plugins/contributions'
import { openPluginWindow, type PluginWindowTarget } from '@/helpers/pluginWindow.ts'
import { useOptionalSplitWorkspace } from '@/split/useSplitWorkspace'

interface PluginSystemCapabilities {
  tools: string[]
  skills: string[]
  hooks: string[]
  mcp: string[]
  commands: string[]
  context: string[]
}

interface PluginSystemEntry {
  name: string
  version: string
  description: string
  enabled: boolean
  available?: boolean
  backend?: { state: string; error?: { message?: string } }
  scope: string
  root: string
  capabilities?: PluginSystemCapabilities
  capability_error?: string
}

interface PluginSystemError {
  name: string
  path: string
  error: string
}

interface PluginSystemWindow {
  plugin: string
  id: string
  title: string
  url: string
  width: number
  height: number
}

type PluginSystemRpc = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

type PluginFilter = 'all' | 'enabled' | 'disabled' | 'attention'
type InstallSource = 'local' | 'zip' | 'url'
type StatusTone = 'success' | 'pending' | 'danger' | 'idle'

interface CapabilityChip {
  key: keyof PluginSystemCapabilities
  label: string
  detail: string
  count: number
  icon: Component
}

const props = defineProps<{ requestRpc: PluginSystemRpc }>()
const pluginSection = ref('installed')
const splitWorkspace = useOptionalSplitWorkspace()

const CAPABILITY_META: Array<{ key: keyof PluginSystemCapabilities; label: string; icon: Component }> = [
  { key: 'tools', label: '工具', icon: Wrench },
  { key: 'skills', label: '技能', icon: Sparkles },
  { key: 'hooks', label: '钩子', icon: Plug },
  { key: 'mcp', label: 'MCP', icon: Server },
  { key: 'commands', label: '命令', icon: Terminal },
  { key: 'context', label: '上下文', icon: FileCode2 },
]

// 六个稳定的卡片强调色：四个语义色 + 两个语义色之间的过渡色，
// 让相邻插件更容易区分，同时不引入新的主题色体系。
const ACCENTS = [
  'var(--blue)',
  'var(--purple)',
  'var(--orange)',
  'var(--green)',
  'color-mix(in srgb, var(--blue) 55%, var(--purple))',
  'color-mix(in srgb, var(--green) 58%, var(--blue))',
] as const

const installSources: Array<{ value: InstallSource; label: string; icon: Component }> = [
  { value: 'local', label: '本地目录', icon: FolderOpen },
  { value: 'zip', label: '压缩包', icon: FileArchive },
  { value: 'url', label: '链接', icon: Link2 },
]

const behaviorQuery = ref('')
const behaviorEntries = ref<Array<{ module: string; ownership: string; layer: string }>>([])
const behaviorTotal = ref(-1)
const installSource = ref<InstallSource>('local')
const installTarget = ref('')
const installSha256 = ref('')
const installBusy = ref(false)
const installOpen = ref(false)
const depsReport = ref<Record<string, string>>({})
const depsBusy = ref('')
const plugins = ref<PluginSystemEntry[]>([])
const windows = ref<PluginSystemWindow[]>([])
const configuring = ref('')
const loadErrors = ref<PluginSystemError[]>([])
const loading = ref(true)
const refreshing = ref(false)
const busy = ref('')
const error = ref('')
const notice = ref('')
const noticeTone = ref<'success' | 'warning'>('success')
const restartRequired = ref(false)
const query = ref('')
const filter = ref<PluginFilter>('all')
const diagnosticsOpen = ref(false)
const copiedPlugin = ref('')
const pendingUninstall = ref<PluginSystemEntry | null>(null)
const uninstallError = ref('')
const uninstalling = ref(false)
const searchInputEl = ref<HTMLInputElement | null>(null)
const installInputEl = ref<HTMLInputElement | null>(null)
const pageEl = ref<HTMLElement | null>(null)
const columnCount = ref(1)
const behaviorInputId = `plugin-behavior-${useId()}`
let gridObserver: ResizeObserver | undefined

const pagesFor = (plugin: string) => contributionState().pages.filter(page => page.plugin === plugin)

const enabledCount = computed(() => plugins.value.filter(plugin => plugin.enabled).length)

const attentionCount = computed(() => plugins.value.filter(needsAttention).length)

const filterChips = computed<Array<{ id: PluginFilter; label: string; count: number }>>(() => [
  { id: 'all', label: t('全部'), count: plugins.value.length },
  { id: 'enabled', label: t('已启用'), count: enabledCount.value },
  { id: 'disabled', label: t('已停用'), count: plugins.value.length - enabledCount.value },
  { id: 'attention', label: t('需要处理'), count: attentionCount.value },
])

const filteredPlugins = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return plugins.value.filter((plugin) => {
    if (filter.value === 'enabled' && !plugin.enabled) return false
    if (filter.value === 'disabled' && plugin.enabled) return false
    if (filter.value === 'attention' && !needsAttention(plugin)) return false
    return !needle || haystack(plugin).includes(needle)
  })
})

// user:“插件你最好贴紧一点。比如说，你这里面那个 broken 应该是和上面那个贴着的”+
// 每列独立向下堆叠，卡片高度不同时不会在短卡片下面空出整行。
const pluginColumns = computed<PluginSystemEntry[][]>(() => {
  const count = Math.max(1, Math.min(columnCount.value, filteredPlugins.value.length || 1))
  const columns = Array.from({ length: count }, () => [] as PluginSystemEntry[])
  filteredPlugins.value.forEach((plugin, index) => {
    columns[index % count].push(plugin)
  })
  return columns
})

// 进场的错峰序号按整页顺序算，不按列内序号算，视觉节奏才连续。
const cardIndexes = computed(
  () => new Map(filteredPlugins.value.map((plugin, index) => [plugin.name, index])),
)

function updateColumnCount(): void {
  const width = pageEl.value?.clientWidth ?? 0
  if (!width) {
    columnCount.value = 1
    return
  }
  const gap = 12
  const minimumCardWidth = 340
  columnCount.value = Math.max(
    1,
    Math.min(3, Math.floor((width + gap) / (minimumCardWidth + gap))),
  )
}

function handleWindowResize(): void {
  updateColumnCount()
}

const installPlaceholder = computed(() =>
  installSource.value === 'url'
    ? 'https://example.com/plugin.zip'
    : String.raw`C:\path\to\plugin`,
)

const uninstallDetail = computed(() =>
  pendingUninstall.value
    ? `${pendingUninstall.value.name} · ${t('data 目录会保留')}`
    : '',
)

const sourceIcon = computed(
  () => installSources.find(option => option.value === installSource.value)?.icon ?? FolderOpen,
)

function haystack(plugin: PluginSystemEntry): string {
  const capabilityNames = CAPABILITY_META.flatMap(meta => plugin.capabilities?.[meta.key] ?? [])
  return [
    plugin.name,
    plugin.version,
    plugin.description,
    plugin.scope,
    plugin.root,
    plugin.capability_error,
    plugin.backend?.error?.message,
    ...capabilityNames,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

function needsAttention(plugin: PluginSystemEntry): boolean {
  if (!plugin.enabled) return false
  return Boolean(plugin.capability_error) || plugin.backend?.state === 'failed' || plugin.available === false
}

function accentFor(name: string): string {
  // FNV-1a：同一插件每次进入页面都得到同一个颜色，且相邻名字不易撞色。
  let hash = 2166136261
  for (let index = 0; index < name.length; index += 1) {
    hash ^= name.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return ACCENTS[(hash >>> 0) % ACCENTS.length]
}

function glyphFor(name: string): string {
  const parts = name.split(/[-_.\s]+/).filter(Boolean)
  if (parts.length >= 2) return `${parts[0][0] ?? ''}${parts[1][0] ?? ''}`.toUpperCase()
  return name.slice(0, 2).toUpperCase()
}

function scopeLabel(scope: string): string {
  if (scope === 'global') return t('全局')
  if (scope === 'mode') return t('模式')
  if (scope === 'session') return t('会话')
  return scope
}

function capabilityChips(plugin: PluginSystemEntry): CapabilityChip[] {
  const capabilities = plugin.capabilities
  if (!capabilities) return []
  return CAPABILITY_META.flatMap((meta) => {
    const names = capabilities[meta.key] ?? []
    if (!names.length) return []
    const label = t(meta.label)
    return [{
      key: meta.key,
      label,
      detail: `${label}：${names.join('、')}`,
      count: names.length,
      icon: meta.icon,
    }]
  })
}

function statusOf(plugin: PluginSystemEntry): { label: string; tone: StatusTone } {
  if (!plugin.enabled) return { label: t('已停用'), tone: 'idle' }
  switch (plugin.backend?.state) {
    case 'failed':
      return { label: t('启动失败'), tone: 'danger' }
    case 'starting':
      return { label: t('正在启动'), tone: 'pending' }
    case 'transitioning':
      return { label: t('正在切换'), tone: 'pending' }
    case 'ready':
      return { label: t('运行就绪'), tone: 'success' }
    case 'safe_mode':
      return { label: t('安全模式已跳过'), tone: 'idle' }
    case 'stopped':
      return { label: t('已停止'), tone: 'idle' }
    default:
      return { label: t('等待启动'), tone: 'idle' }
  }
}

function statusDetail(plugin: PluginSystemEntry): string {
  return plugin.backend?.state === 'failed' ? plugin.backend.error?.message || '' : ''
}

function windowsFor(pluginName: string): PluginSystemWindow[] {
  return windows.value.filter((window) => window.plugin === pluginName)
}

function toggleInstall(): void {
  installOpen.value = !installOpen.value
  if (installOpen.value) {
    void nextTick(() => installInputEl.value?.focus())
  }
}

function clearSearch(): void {
  query.value = ''
  searchInputEl.value?.focus()
}

function clearFilters(): void {
  query.value = ''
  filter.value = 'all'
}

function toggleConfig(plugin: PluginSystemEntry, event?: Event): void {
  const opening = configuring.value !== plugin.name
  configuring.value = opening ? plugin.name : ''
  if (!opening) return
  const card = (event?.currentTarget as HTMLElement | null)?.closest('.plugin-card')
  void nextTick(() => {
    card?.scrollIntoView?.({ block: 'nearest', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
  })
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

async function openWindow(target: PluginSystemWindow): Promise<void> {
  notice.value = ''
  error.value = ''
  try {
    const opened = await openPluginWindow(target as PluginWindowTarget)
    if (!opened) {
      noticeTone.value = 'warning'
      notice.value = t('当前环境没有桌面窗口，插件窗口只能在桌面端打开。')
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function fetchWindows(): Promise<void> {
  try {
    const payload = await props.requestRpc('plugin.system.ui', {})
    setPluginPageEntries(payload.pages)
    windows.value = Array.isArray(payload.windows)
      ? (payload.windows as PluginSystemWindow[])
      : []
  } catch {
    windows.value = []
    setPluginPageEntries([])
  }
}

async function fetchPlugins(): Promise<void> {
  const firstLoad = plugins.value.length === 0
  if (firstLoad) loading.value = true
  refreshing.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('plugin.system.list', {})
    // 先量宽度再放数据，卡片第一次出现就是正确的列数，不会先挤成一列再跳开。
    updateColumnCount()
    plugins.value = Array.isArray(result.plugins)
      ? (result.plugins as PluginSystemEntry[]).map(plugin => ({ ...plugin }))
      : []
    loadErrors.value = Array.isArray(result.errors)
      ? (result.errors as PluginSystemError[])
      : []
    await fetchWindows()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

async function retry(plugin: PluginSystemEntry): Promise<void> {
  busy.value = plugin.name
  try {
    // user:“该重建就重建”+(重试或开关均保留宿主返回的重启提示)。
    const result = await props.requestRpc('plugin.system.enable', { name: plugin.name }) as { restart_required?: boolean }
    restartRequired.value ||= result.restart_required === true
    await fetchPlugins()
    await ensureContributions(props.requestRpc)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = ''
  }
}

async function toggle(plugin: PluginSystemEntry): Promise<void> {
  const wasEnabled = plugin.enabled
  const previousBackend = plugin.backend
  // 开关先动起来，再把结果交给后台；失败时回退，避免点了没反应。
  plugin.enabled = !wasEnabled
  plugin.backend = { ...(previousBackend ?? {}), state: wasEnabled ? 'stopped' : 'starting' }
  busy.value = plugin.name
  error.value = ''
  try {
    const result = await props.requestRpc(
      wasEnabled ? 'plugin.system.disable' : 'plugin.system.enable',
      { name: plugin.name },
    ) as { restart_required?: boolean }
    restartRequired.value ||= result.restart_required === true
    await fetchPlugins()
    await ensureContributions(props.requestRpc)
  } catch (cause) {
    plugin.enabled = wasEnabled
    plugin.backend = previousBackend
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = ''
  }
}

function askUninstall(plugin: PluginSystemEntry): void {
  pendingUninstall.value = plugin
  uninstallError.value = ''
}

function closeUninstall(): void {
  if (uninstalling.value) return
  pendingUninstall.value = null
  uninstallError.value = ''
}

async function confirmUninstall(): Promise<void> {
  const plugin = pendingUninstall.value
  if (!plugin) return
  uninstalling.value = true
  uninstallError.value = ''
  try {
    await props.requestRpc('plugin.system.uninstall', {
      name: plugin.name,
      keep_data: true,
    })
    pendingUninstall.value = null
    noticeTone.value = 'success'
    notice.value = t('已卸载 {0}，data 目录保留。', { 0: plugin.name })
    await fetchPlugins()
    await ensureContributions(props.requestRpc)
  } catch (cause) {
    uninstallError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    uninstalling.value = false
  }
}

let copiedTimer: ReturnType<typeof setTimeout> | undefined

async function copyRoot(plugin: PluginSystemEntry): Promise<void> {
  try {
    await copyText(plugin.root)
    copiedPlugin.value = plugin.name
    if (copiedTimer) clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => {
      if (copiedPlugin.value === plugin.name) copiedPlugin.value = ''
    }, 1600)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

interface InstallResult {
  installed?: boolean
  updated?: boolean
  name?: string
  dependencies?: Array<{ name: string; status: string }>
  missing_dependencies?: number
  restart_required?: boolean
}

function describeDependencies(result: InstallResult): string {
  const items = result.dependencies || []
  if (!items.length) return ''
  const missing = items.filter((item) => item.status === 'missing').map((item) => item.name)
  const summary = items.map((item) => `${item.name}:${item.status === 'ok' ? '✓' : t('缺失')}`).join(' · ')
  return missing.length
    ? `${summary}${t('（缺 {0}，可用 pip 安装；不阻止安装）', { 0: missing.join('、') })}`
    : summary
}

async function submitInstall(isUpdate: boolean): Promise<void> {
  if (!installTarget.value.trim()) return
  const source = installSource.value
  const payload: Record<string, unknown> = { source }
  if (source === 'url') {
    payload.url = installTarget.value.trim()
    if (installSha256.value.trim()) payload.sha256 = installSha256.value.trim()
  } else {
    payload.path = installTarget.value.trim()
  }
  installBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = (await props.requestRpc(
      isUpdate ? 'plugin.system.update' : 'plugin.system.install',
      payload,
    )) as unknown as InstallResult
    restartRequired.value = result.restart_required === true
    const label = isUpdate
      ? t('已更新 {0}', { 0: result.name || '' })
      : t('已安装 {0}', { 0: result.name || '' })
    const deps = describeDependencies(result)
    noticeTone.value = 'success'
    notice.value = deps ? `${label}；${t('依赖：{0}', { 0: deps })}` : label
    installTarget.value = ''
    installSha256.value = ''
    installOpen.value = false
    await fetchPlugins()
    await ensureContributions(props.requestRpc)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    installBusy.value = false
  }
}

function depsFor(name: string): string {
  return depsReport.value[name] || ''
}

function depsMissing(name: string): boolean {
  return (depsReport.value[name] || '').includes(t('缺失'))
}

async function checkDeps(plugin: PluginSystemEntry): Promise<void> {
  depsBusy.value = plugin.name
  try {
    const result = await props.requestRpc('plugin.deps-status', { name: plugin.name })
    const items = Array.isArray(result.dependencies)
      ? (result.dependencies as Array<{ name: string; status: string }>)
      : []
    depsReport.value[plugin.name] = items.length
      ? items.map((item) => `${item.name}:${item.status === 'ok' ? '✓' : t('缺失')}`).join(' · ')
      : t('没有声明依赖')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    depsBusy.value = ''
  }
}

async function searchBehavior(): Promise<void> {
  const queryText = behaviorQuery.value.trim()
  if (!queryText) return
  try {
    const result = await props.requestRpc('plugin.system.behavior', { query: queryText })
    behaviorEntries.value = Array.isArray(result.entries)
      ? (result.entries as Array<{ module: string; ownership: string; layer: string }>)
      : []
    behaviorTotal.value = Number(result.total_matches || 0)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

function handleGlobalKey(event: KeyboardEvent): void {
  if (event.defaultPrevented || event.key !== '/') return
  if (event.metaKey || event.ctrlKey || event.altKey) return
  const target = event.target as Element | null
  if (target?.closest?.('input, textarea, select, [contenteditable="true"], [contenteditable=""]')) return
  event.preventDefault()
  searchInputEl.value?.focus()
}

let statusTimer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  void fetchPlugins()
  updateColumnCount()
  if (typeof ResizeObserver !== 'undefined' && pageEl.value) {
    gridObserver = new ResizeObserver(updateColumnCount)
    gridObserver.observe(pageEl.value)
  } else {
    window.addEventListener('resize', handleWindowResize)
  }
  document.addEventListener('keydown', handleGlobalKey)
  statusTimer = setInterval(async () => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    if (loading.value || busy.value || installBusy.value || uninstalling.value) return
    try {
      const result = await props.requestRpc('plugin.system.list', {})
      if (Array.isArray(result.plugins)) {
        plugins.value = (result.plugins as PluginSystemEntry[]).map(plugin => ({ ...plugin }))
      }
    } catch {
      // Retain the last status; explicit refresh reports connection errors.
    }
  }, 2000)
})

onBeforeUnmount(() => {
  if (statusTimer) clearInterval(statusTimer)
  if (copiedTimer) clearTimeout(copiedTimer)
  gridObserver?.disconnect()
  window.removeEventListener('resize', handleWindowResize)
  document.removeEventListener('keydown', handleGlobalKey)
})
</script>

<style scoped>
.plugin-page {
  /* user:“那同步底下的那个输入 也要上移呀 不要留太大的空白”+
     页头—搜索—卡片之间收紧；安装托盘收起时不再占网格行。 */
  gap: var(--space-3);
  container: plugin-page / inline-size;
  --plugin-text: var(--settings-main-text, var(--theme-main-text, var(--text)));
  --plugin-muted: color-mix(in srgb, var(--plugin-text) 58%, transparent);
  --plugin-faint: color-mix(in srgb, var(--plugin-text) 40%, transparent);
  --plugin-border: color-mix(in srgb, var(--plugin-text) 12%, transparent);
  --plugin-border-strong: color-mix(in srgb, var(--plugin-text) 20%, transparent);
  --plugin-card: var(--settings-card-background, var(--theme-main-soft-background, #1b1c1c));
  --plugin-soft: color-mix(in srgb, var(--plugin-text) 5%, transparent);
  color: var(--plugin-text);
}

.plugin-page :is(h1, h2, h3, p) {
  margin: 0;
}

/* ── 页头 ─────────────────────────────────────────────────────────────── */
/* 标题只留“插件”两个字：紧凑一行，剩下的信息交给右侧状态和卡片本身。 */
.plugin-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.plugin-hero-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.3;
  letter-spacing: -.01em;
}

.plugin-hero-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.plugin-stats {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
  color: var(--plugin-muted);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.plugin-stat {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  white-space: nowrap;
}

.plugin-stat-dot {
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: currentColor;
  opacity: .5;
}

.plugin-stat-dot.is-on {
  background: var(--green);
  opacity: .9;
}

.plugin-stat-dot.is-warn {
  background: var(--orange);
  opacity: .95;
}

.plugin-stat.is-warning {
  color: color-mix(in srgb, var(--orange) 78%, var(--plugin-text));
}

.plugin-install-toggle {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  white-space: nowrap;
}

.plugin-icon-button {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--plugin-muted);
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.plugin-icon-button:hover {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-hover), transparent);
  color: var(--plugin-text);
}

.plugin-icon-button:active {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-active), transparent);
}

/* ── 安装托盘 ─────────────────────────────────────────────────────────── */
.install-tray {
  display: grid;
  grid-template-rows: 1fr;
}

.install-tray-enter-active,
.install-tray-leave-active {
  overflow: hidden;
  transition:
    grid-template-rows var(--dur-slow) var(--ease-emphasized),
    opacity var(--dur-base) var(--ease-out);
}

.install-tray-enter-from,
.install-tray-leave-to {
  grid-template-rows: 0fr;
  opacity: 0;
}

.install-tray-clip {
  overflow: hidden;
  min-height: 0;
}

.install-tray-inner {
  display: grid;
  gap: var(--space-3);
  padding: var(--space-3);
  margin-top: var(--space-1);
  border: 1px solid var(--plugin-border);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--plugin-text) 3.5%, transparent);
}

.install-tray-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.install-tray-head strong {
  display: block;
  font-size: 13.5px;
  line-height: 1.35;
}

.install-tray-head p {
  margin-top: 2px;
  color: var(--plugin-muted);
  font-size: 11.5px;
}

.install-busy {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--plugin-muted);
  font-size: 11.5px;
  white-space: nowrap;
}

.install-source {
  width: max-content;
  max-width: 100%;
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--plugin-border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--plugin-text) 4%, transparent);
}

.install-source-option {
  min-height: 28px;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-3);
  border-radius: 999px;
  color: var(--plugin-muted);
  font-size: 12px;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.install-source-option:hover {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-hover), transparent);
  color: var(--plugin-text);
}

/* 单选圆点视觉隐藏后，键盘聚焦要在整块来源选项上可见。 */
.install-source-option:has(input:focus-visible) {
  outline: 2px solid var(--blue);
  outline-offset: 2px;
}

.install-source-option.is-active {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-active), transparent);
  color: var(--plugin-text);
}

.install-fields {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.install-field {
  flex: 1 1 240px;
  min-width: 0;
  min-height: 36px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  border: 1px solid var(--plugin-border);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--plugin-text) 3%, transparent);
}

.install-sha-field {
  flex: 0 1 190px;
}

.install-field-icon {
  flex: 0 0 auto;
  color: var(--plugin-faint);
}

.install-field input {
  flex: 1 1 auto;
  min-width: 0;
  height: 34px;
  border: 0;
  background: transparent;
  color: var(--plugin-text);
  font: inherit;
  font-size: 12.5px;
}

.install-field input::placeholder {
  color: color-mix(in srgb, var(--plugin-text) 42%, transparent);
}

.install-submit,
.install-update {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  white-space: nowrap;
}

/* 更新是安装的次要动作：描边式，不与主按钮抢同一块实心背景。 */
.install-update {
  border: 1px solid color-mix(in srgb, var(--plugin-text) 16%, transparent);
  background: transparent;
  color: var(--plugin-text);
}

.install-update:hover:not(:disabled) {
  border-color: var(--plugin-border-strong);
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-hover), transparent);
  filter: none;
}

.plugin-page .small-btn:disabled {
  opacity: .45;
  cursor: default;
}

.install-hint {
  color: var(--plugin-faint);
  font-size: 11px;
}

/* ── 提示条 ───────────────────────────────────────────────────────────── */
.plugin-feedback-stack {
  display: grid;
  gap: var(--space-2);
}

.plugin-feedback {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--plugin-border);
  border-radius: var(--radius);
  font-size: 12px;
  line-height: 1.5;
}

.plugin-feedback.is-error {
  border-color: color-mix(in srgb, var(--red) 28%, transparent);
  background: color-mix(in srgb, var(--red) 8%, transparent);
  color: color-mix(in srgb, var(--red) 56%, var(--plugin-text));
}

.plugin-feedback.is-success {
  border-color: color-mix(in srgb, var(--green) 26%, transparent);
  background: color-mix(in srgb, var(--green) 8%, transparent);
  color: color-mix(in srgb, var(--green) 52%, var(--plugin-text));
}

.plugin-feedback.is-warning {
  border-color: color-mix(in srgb, var(--orange) 28%, transparent);
  background: color-mix(in srgb, var(--orange) 8%, transparent);
  color: color-mix(in srgb, var(--orange) 58%, var(--plugin-text));
}

.plugin-feedback > span {
  min-width: 0;
  flex: 1 1 auto;
  overflow-wrap: anywhere;
}

.feedback-dismiss {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  opacity: .6;
  transition: background var(--dur-fast) var(--ease-out), opacity var(--dur-fast) var(--ease-out);
}

.feedback-dismiss:hover {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-hover), transparent);
  opacity: 1;
}

/* ── 搜索与筛选 ───────────────────────────────────────────────────────── */
.plugin-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.plugin-search {
  flex: 1 1 260px;
  min-width: 0;
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  border: 1px solid var(--plugin-border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--plugin-text) 3.5%, transparent);
  transition: border-color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}

.plugin-search:hover {
  border-color: var(--plugin-border-strong);
}

.plugin-search-icon {
  flex: 0 0 auto;
  color: var(--plugin-faint);
}

.plugin-search input {
  flex: 1 1 auto;
  min-width: 0;
  height: 32px;
  border: 0;
  background: transparent;
  color: var(--plugin-text);
  font: inherit;
  font-size: 12.5px;
}

.plugin-search input::placeholder {
  color: color-mix(in srgb, var(--plugin-text) 42%, transparent);
}

.plugin-search-clear {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-hover), transparent);
  color: var(--plugin-muted);
}

.plugin-search-clear:hover {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-active), transparent);
  color: var(--plugin-text);
}

.plugin-search-key {
  flex: 0 0 auto;
  min-width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  border: 1px solid var(--plugin-border);
  border-radius: var(--radius-sm);
  color: var(--plugin-faint);
  font-family: var(--font-mono);
  font-size: 10px;
}

.plugin-filters {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.plugin-filter {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  padding: 0 var(--space-2);
  border-radius: 999px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--plugin-muted);
  font-size: 12px;
  white-space: nowrap;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.plugin-filter:hover:not(:disabled) {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-hover), transparent);
  color: var(--plugin-text);
}

.plugin-filter:disabled {
  opacity: .42;
  cursor: default;
}

.plugin-filter.is-active {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-active), transparent);
  color: var(--plugin-text);
}

.plugin-filter-count {
  margin-left: var(--space-1);
  color: var(--plugin-faint);
  font-variant-numeric: tabular-nums;
}

.plugin-filter.is-active .plugin-filter-count {
  color: color-mix(in srgb, var(--plugin-text) 64%, transparent);
}

.plugin-result-count {
  margin-left: auto;
  color: var(--plugin-faint);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* ── 卡片网格（按列瀑布流）─────────────────────────────────────────────── */
.plugin-grid {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}

.plugin-column {
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.plugin-grid--skeleton {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
}

.plugin-card {
  position: relative;
  min-width: 0;
  display: grid;
  gap: var(--space-2);
  padding: var(--space-4);
  border: 1px solid var(--plugin-border);
  border-radius: var(--radius-lg);
  background: var(--plugin-card);
  color: var(--settings-card-text, var(--plugin-text));
  transition:
    border-color var(--dur-base) var(--ease-out),
    box-shadow var(--dur-base) var(--ease-out),
    transform var(--dur-base) var(--ease-out),
    background var(--dur-base) var(--ease-out);
}

.plugin-card::before {
  content: '';
  position: absolute;
  inset: -1px -1px auto;
  height: 2px;
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  background: linear-gradient(90deg, transparent, var(--plugin-accent) 30%, var(--plugin-accent) 70%, transparent);
  opacity: 0;
  transition: opacity var(--dur-base) var(--ease-out);
  pointer-events: none;
}

.plugin-card:hover {
  border-color: var(--plugin-border-strong);
  box-shadow: var(--shadow-sm);
  transform: translateY(-2px);
}

.plugin-card:hover::before,
.plugin-card:focus-within::before {
  opacity: .55;
}

.plugin-card.is-attention {
  border-color: color-mix(in srgb, var(--red) 26%, var(--plugin-border));
}

.plugin-card.is-disabled {
  background: color-mix(in srgb, var(--plugin-card) 94%, var(--plugin-text) 3%);
}

.plugin-card.is-disabled .plugin-glyph,
.plugin-card.is-disabled .plugin-capability {
  filter: grayscale(.7);
  opacity: .62;
}

.plugin-card.is-busy {
  cursor: progress;
}

/* 卡片进出与排序动画 */
.plugin-card-enter-active {
  transition:
    opacity var(--dur-base) var(--ease-out),
    transform var(--dur-slow) var(--ease-emphasized);
  transition-delay: calc(min(var(--card-index, 0), 8) * 35ms);
}

.plugin-card-enter-from {
  opacity: 0;
  transform: translateY(10px) scale(.985);
}

.plugin-card-leave-active {
  position: absolute;
  width: 0;
  height: 0;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
}

.plugin-card-move {
  transition: transform var(--dur-slow) var(--ease-emphasized);
}

/* ── 卡片头部 ─────────────────────────────────────────────────────────── */
.plugin-card-head {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: var(--space-3);
  align-items: start;
}

.plugin-glyph {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--plugin-accent) 26%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--plugin-accent) 13%, transparent);
  color: color-mix(in srgb, var(--plugin-accent) 62%, var(--plugin-text));
  font-size: 13px;
  font-weight: 760;
  letter-spacing: .02em;
  transition: transform var(--dur-base) var(--ease-out);
}

.plugin-card:hover .plugin-glyph {
  transform: scale(1.04);
}

.plugin-identity {
  min-width: 0;
  display: grid;
  gap: 2px;
  padding-top: 1px;
}

.plugin-name-line {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.plugin-name-line strong {
  min-width: 0;
  overflow: hidden;
  color: var(--settings-card-text, var(--plugin-text));
  font-size: 14px;
  font-weight: 700;
  letter-spacing: -.01em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plugin-version {
  flex: 0 0 auto;
  color: var(--plugin-faint);
  font-family: var(--font-mono);
  font-size: 10.5px;
}

.plugin-meta-line {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--plugin-muted);
  font-size: 10.5px;
}

.plugin-scope {
  flex: 0 0 auto;
  padding: 1px 6px;
  border: 1px solid color-mix(in srgb, var(--plugin-text) 16%, transparent);
  border-radius: 999px;
  font-size: 9.5px;
  line-height: 1.4;
}

.plugin-meta-sep {
  opacity: .4;
}

.plugin-root {
  min-width: 0;
  overflow: hidden;
  font-family: var(--font-mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 开关 */
.plugin-switch {
  position: relative;
  flex: 0 0 auto;
  width: 42px;
  height: 24px;
  margin-top: 1px;
  padding: 2px;
  border: 1px solid color-mix(in srgb, var(--plugin-text) 16%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--plugin-text) 12%, transparent);
  transition:
    background var(--dur-base) var(--ease-out),
    border-color var(--dur-base) var(--ease-out),
    opacity var(--dur-fast) var(--ease-out);
}

.plugin-switch:hover {
  border-color: color-mix(in srgb, var(--plugin-text) 26%, transparent);
}

.plugin-switch[aria-checked='true'] {
  border-color: transparent;
  background: color-mix(in srgb, var(--green) 72%, var(--plugin-card));
}

.plugin-switch:disabled {
  opacity: .6;
  cursor: progress;
}

.plugin-switch-thumb {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  background: var(--plugin-text);
  color: var(--plugin-card);
  box-shadow: 0 1px 2px rgba(0, 0, 0, .22);
  transform: translateX(0);
  transition: transform var(--dur-base) var(--ease-emphasized), background var(--dur-base) var(--ease-out);
}

.plugin-switch[aria-checked='true'] .plugin-switch-thumb {
  transform: translateX(18px);
  background: var(--plugin-text);
}

/* ── 卡片正文 ─────────────────────────────────────────────────────────── */
.plugin-description {
  display: -webkit-box;
  overflow: hidden;
  color: color-mix(in srgb, var(--plugin-text) 74%, transparent);
  font-size: 12.5px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.plugin-description.is-empty {
  color: var(--plugin-faint);
}

.plugin-status-row {
  min-width: 0;
  min-height: 18px;
  display: flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--plugin-muted);
  font-size: 11.5px;
}

.plugin-status-row.is-success {
  color: color-mix(in srgb, var(--green) 66%, var(--plugin-text));
}

.plugin-status-row.is-pending {
  color: color-mix(in srgb, var(--orange) 76%, var(--plugin-text));
}

.plugin-status-row.is-danger {
  color: color-mix(in srgb, var(--red) 78%, var(--plugin-text));
}

.plugin-status-dot {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: currentColor;
}

.plugin-status-row.is-pending .plugin-status-dot {
  animation: plugin-status-pulse 1.6s var(--ease-out) infinite;
}

.plugin-status-label {
  flex: 0 0 auto;
  font-weight: 600;
}

.plugin-status-detail {
  min-width: 0;
  overflow: hidden;
  font-family: var(--font-mono);
  font-size: 10.5px;
  opacity: .82;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plugin-retry {
  flex: 0 0 auto;
  min-height: 22px;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-2);
  border-radius: 999px;
  background: color-mix(in srgb, var(--red) 10%, transparent);
  color: color-mix(in srgb, var(--red) 72%, var(--plugin-text));
  font-size: 11px;
  transition: background var(--dur-fast) var(--ease-out);
}

.plugin-retry:hover {
  background: color-mix(in srgb, var(--red) 16%, transparent);
}

.plugin-retry:disabled {
  opacity: .5;
  cursor: progress;
}

.plugin-alert {
  display: flex;
  align-items: flex-start;
  gap: var(--space-1);
  padding: 6px 8px;
  border: 1px solid color-mix(in srgb, var(--red) 20%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--red) 7%, transparent);
  color: color-mix(in srgb, var(--red) 70%, var(--plugin-text));
  font-size: 11px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.plugin-capabilities {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
}

.plugin-capability {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 3px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--plugin-accent) 20%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--plugin-accent) 9%, transparent);
  color: color-mix(in srgb, var(--plugin-accent) 52%, var(--plugin-text));
  font-size: 10.5px;
  line-height: 1.4;
  white-space: nowrap;
}

.plugin-capability.is-empty {
  border-color: var(--plugin-border);
  background: transparent;
  color: var(--plugin-faint);
}

.plugin-entries {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
  padding-top: var(--space-1);
}

.plugin-entries-label {
  color: var(--plugin-faint);
  font-size: 10px;
  letter-spacing: .04em;
  text-transform: uppercase;
}

.plugin-entry {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-2);
  border: 1px solid var(--plugin-border);
  border-radius: 999px;
  background: transparent;
  color: var(--plugin-muted);
  font-size: 11px;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.plugin-entry:hover:not(:disabled) {
  border-color: var(--plugin-border-strong);
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-hover), transparent);
  color: var(--plugin-text);
}

.plugin-entry:active:not(:disabled) {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-active), transparent);
}

.plugin-entry:disabled {
  opacity: .4;
  cursor: not-allowed;
}

/* ── 卡片操作 ─────────────────────────────────────────────────────────── */
.plugin-card-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding-top: var(--space-2);
  border-top: 1px solid color-mix(in srgb, var(--plugin-text) 8%, transparent);
}

.plugin-action {
  min-height: 28px;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--plugin-muted);
  font-size: 11.5px;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.plugin-action:hover:not(:disabled) {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-hover), transparent);
  color: var(--plugin-text);
}

.plugin-action:active:not(:disabled),
.plugin-action.is-active {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-active), transparent);
  color: var(--plugin-text);
}

.plugin-action:disabled {
  opacity: .5;
  cursor: progress;
}

.plugin-action-chevron {
  transition: transform var(--dur-base) var(--ease-out);
}

.plugin-action.is-active .plugin-action-chevron {
  transform: rotate(180deg);
}

.plugin-action-spacer {
  flex: 1 1 auto;
}

.plugin-icon-action {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--plugin-faint);
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.plugin-icon-action:hover {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-hover), transparent);
  color: var(--plugin-text);
}

.plugin-icon-action:active {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-active), transparent);
}

.plugin-icon-action.is-danger:hover {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-hover), transparent);
  color: var(--red);
}

/* ── 卡片内抽屉 ───────────────────────────────────────────────────────── */
.plugin-drawer {
  overflow: hidden;
}

.plugin-drawer-inner {
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-1);
  padding-top: var(--space-3);
  border-top: 1px solid color-mix(in srgb, var(--plugin-text) 9%, transparent);
}

.plugin-drawer-section {
  display: grid;
  gap: var(--space-2);
}

.plugin-drawer-label {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--plugin-faint);
  font-size: 10px;
  letter-spacing: .05em;
  text-transform: uppercase;
}

.plugin-deps {
  display: flex;
  align-items: flex-start;
  gap: var(--space-1);
  margin: 0;
  color: var(--plugin-muted);
  font-size: 11px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.plugin-deps.is-missing {
  color: color-mix(in srgb, var(--red) 72%, var(--plugin-text));
}

.plugin-drawer-enter-active,
.plugin-drawer-leave-active {
  transition:
    max-height var(--dur-slow) var(--ease-emphasized),
    opacity var(--dur-base) var(--ease-out),
    transform var(--dur-slow) var(--ease-emphasized);
}

.plugin-drawer-enter-from,
.plugin-drawer-leave-to {
  max-height: 0;
  opacity: 0;
  transform: translateY(-4px);
}

.plugin-drawer-enter-to,
.plugin-drawer-leave-from {
  max-height: 1200px;
  opacity: 1;
  transform: translateY(0);
}

/* ── 空态与骨架 ───────────────────────────────────────────────────────── */
.plugin-empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-6) var(--space-5);
  border: 1px dashed var(--plugin-border-strong);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--plugin-text) 2%, transparent);
}

.plugin-empty-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--plugin-text) 7%, transparent);
  color: color-mix(in srgb, var(--plugin-text) 62%, transparent);
}

.plugin-empty-mark.is-error {
  background: color-mix(in srgb, var(--red) 10%, transparent);
  color: color-mix(in srgb, var(--red) 70%, var(--plugin-text));
}

.plugin-empty h2 {
  font-size: 15px;
  line-height: 1.35;
}

.plugin-empty p {
  max-width: 56ch;
  color: var(--plugin-muted);
  font-size: 12.5px;
  line-height: 1.55;
}

.plugin-empty .small-btn {
  margin-top: var(--space-1);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.plugin-grid--skeleton .plugin-skeleton {
  gap: var(--space-3);
  pointer-events: none;
}

.skeleton-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.skeleton-block {
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--plugin-text) 8%, transparent);
  animation: plugin-skeleton-pulse 1.4s var(--ease-out) infinite;
}

.skeleton-lines {
  flex: 1 1 auto;
  display: grid;
  gap: var(--space-2);
}

.skeleton-line {
  height: 9px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--plugin-text) 8%, transparent);
  animation: plugin-skeleton-pulse 1.4s var(--ease-out) infinite;
}

.skeleton-line.is-wide { width: 82%; }
.skeleton-line.is-medium { width: 64%; }
.skeleton-line.is-narrow { width: 38%; }
.skeleton-line.is-short { width: 24%; }

.skeleton-chips {
  display: flex;
  gap: var(--space-1);
}

.skeleton-chips i {
  width: 54px;
  height: 20px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--plugin-text) 6%, transparent);
  animation: plugin-skeleton-pulse 1.4s var(--ease-out) infinite;
}

/* ── 诊断区 ───────────────────────────────────────────────────────────── */
.plugin-diagnostics {
  border: 1px solid var(--plugin-border);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--plugin-text) 2.5%, transparent);
  overflow: hidden;
}

.plugin-diagnostics-head {
  width: 100%;
  min-height: 54px;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: transparent;
  color: var(--plugin-text);
  text-align: left;
}

.plugin-diagnostics-head:hover {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-hover), transparent);
}

.plugin-diagnostics-head:active {
  background: color-mix(in srgb, var(--plugin-text) var(--alpha-active), transparent);
}

.plugin-diagnostics-mark {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--plugin-text) 7%, transparent);
  color: var(--plugin-muted);
}

.plugin-diagnostics-copy {
  min-width: 0;
  flex: 1 1 auto;
  display: grid;
  gap: 1px;
}

.plugin-diagnostics-copy strong {
  font-size: 12.5px;
  font-weight: 660;
}

.plugin-diagnostics-copy small {
  color: var(--plugin-muted);
  font-size: 11px;
}

.plugin-diagnostics-badge {
  flex: 0 0 auto;
  min-width: 19px;
  height: 19px;
  display: grid;
  place-items: center;
  padding: 0 5px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--red) 14%, transparent);
  color: color-mix(in srgb, var(--red) 72%, var(--plugin-text));
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.plugin-diagnostics-chevron {
  flex: 0 0 auto;
  color: var(--plugin-faint);
  transition: transform var(--dur-base) var(--ease-out);
}

.plugin-diagnostics.is-open .plugin-diagnostics-chevron {
  transform: rotate(180deg);
}

.plugin-diagnostics-body {
  display: grid;
  grid-template-rows: 0fr;
  opacity: 0;
  transition:
    grid-template-rows var(--dur-slow) var(--ease-emphasized),
    opacity var(--dur-base) var(--ease-out);
}

.plugin-diagnostics.is-open .plugin-diagnostics-body {
  grid-template-rows: 1fr;
  opacity: 1;
}

.plugin-diagnostics-clip {
  overflow: hidden;
  min-height: 0;
}

.plugin-diagnostics-inner {
  display: grid;
  gap: var(--space-4);
  padding: 0 var(--space-3) var(--space-4);
}

.behavior-form {
  display: grid;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid color-mix(in srgb, var(--plugin-text) 8%, transparent);
}

.behavior-label {
  color: var(--plugin-muted);
  font-size: 11px;
}

.behavior-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.behavior-input {
  flex: 1 1 280px;
  min-width: 0;
  height: 34px;
  padding: 0 var(--space-3);
  border: 1px solid var(--plugin-border);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--plugin-text) 3%, transparent);
  color: var(--plugin-text);
  font: inherit;
  font-size: 12px;
}

.behavior-input::placeholder {
  color: color-mix(in srgb, var(--plugin-text) 42%, transparent);
}

.behavior-total {
  color: var(--plugin-faint);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.behavior-results {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.behavior-result {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--plugin-text) 3%, transparent);
  font-size: 11.5px;
}

.behavior-result code {
  min-width: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  overflow-wrap: anywhere;
}

.behavior-owner {
  padding: 1px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--green) 12%, transparent);
  color: color-mix(in srgb, var(--green) 62%, var(--plugin-text));
  font-size: 10px;
}

.behavior-owner.is-kernel {
  background: color-mix(in srgb, var(--purple) 12%, transparent);
  color: color-mix(in srgb, var(--purple) 62%, var(--plugin-text));
}

.behavior-layer {
  margin-left: auto;
  color: var(--plugin-faint);
  font-size: 10px;
}

.load-errors {
  display: grid;
  gap: var(--space-2);
}

.load-errors-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--plugin-muted);
  font-size: 11.5px;
}

.load-errors ul {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.load-errors li {
  display: grid;
  gap: 2px;
  padding: var(--space-2);
  border: 1px solid color-mix(in srgb, var(--red) 16%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--red) 5%, transparent);
}

.load-error-name {
  color: color-mix(in srgb, var(--red) 68%, var(--plugin-text));
  font-size: 11.5px;
  font-weight: 640;
}

.load-error-message {
  color: var(--plugin-muted);
  font-family: var(--font-mono);
  font-size: 10.5px;
  overflow-wrap: anywhere;
}

.load-error-path {
  color: var(--plugin-faint);
  font-family: var(--font-mono);
  font-size: 10px;
  overflow-wrap: anywhere;
}

.plugin-diagnostics-inner .muted {
  color: var(--plugin-faint);
  font-size: 11.5px;
}

/* ── 动画 ─────────────────────────────────────────────────────────────── */
.spin {
  animation: plugin-spin 1s linear infinite;
}

@keyframes plugin-spin {
  to { transform: rotate(360deg); }
}

@keyframes plugin-status-pulse {
  0%, 100% {
    box-shadow: 0 0 0 0 color-mix(in srgb, currentColor 38%, transparent);
    opacity: .75;
  }
  50% {
    box-shadow: 0 0 0 4px transparent;
    opacity: 1;
  }
}

@keyframes plugin-skeleton-pulse {
  0%, 100% { opacity: .5; }
  50% { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .plugin-card,
  .plugin-card::before,
  .plugin-glyph,
  .plugin-switch,
  .plugin-switch-thumb,
  .plugin-description,
  .plugin-entry,
  .plugin-action,
  .plugin-action-chevron,
  .plugin-icon-action,
  .plugin-search,
  .plugin-filter,
  .install-tray-enter-active,
  .install-tray-leave-active,
  .plugin-diagnostics-body,
  .plugin-diagnostics-chevron,
  .plugin-drawer-enter-active,
  .plugin-drawer-leave-active,
  .plugin-card-enter-active,
  .plugin-card-move {
    transition: none;
  }

  .plugin-status-row.is-pending .plugin-status-dot,
  .skeleton-block,
  .skeleton-line,
  .skeleton-chips i,
  .spin {
    animation: none;
  }
}

/* ── 窄容器适配 ───────────────────────────────────────────────────────── */
@container plugin-page (max-width: 760px) {
  .plugin-hero {
    align-items: center;
  }

  .plugin-hero-actions {
    width: 100%;
  }

  .plugin-stats {
    gap: var(--space-2);
  }

  .plugin-result-count {
    display: none;
  }

  .install-source {
    width: 100%;
  }

  .install-source-option {
    flex: 1 1 0;
    justify-content: center;
  }

  .install-fields {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }

  .install-sha-field {
    max-width: none;
  }

  .install-submit,
  .install-update {
    width: 100%;
  }

  .plugin-filters {
    width: 100%;
    overflow-x: auto;
    padding-bottom: 2px;
    scrollbar-width: none;
  }

  .plugin-filters::-webkit-scrollbar {
    display: none;
  }
}

@container plugin-page (max-width: 480px) {
  .plugin-card {
    padding: var(--space-3);
  }

  .plugin-card-actions {
    flex-wrap: wrap;
  }

  .plugin-root {
    max-width: 150px;
  }

  .plugin-status-row {
    flex-wrap: wrap;
  }

  .plugin-status-detail {
    flex: 1 1 100%;
    white-space: normal;
  }
}
</style>
