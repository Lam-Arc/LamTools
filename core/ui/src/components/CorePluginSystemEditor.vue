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
          class="btn btn--primary plugin-install-toggle"
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
            <button class="btn btn--primary install-submit" type="submit" :disabled="installBusy || !installTarget.trim()">
              {{ t("安装") }}
            </button>
            <button
              class="btn btn--quiet install-update"
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
      <button class="btn btn--primary" type="button" data-retry-load @click="fetchPlugins()">
        <RotateCw :size="14" aria-hidden="true" />
        {{ t("再试一次") }}
      </button>
    </div>

    <div v-else-if="!plugins.length" class="plugin-empty">
      <span class="plugin-empty-mark" aria-hidden="true"><Puzzle :size="20" :stroke-width="1.6" /></span>
      <h2>{{ t("还没有插件") }}</h2>
      <p>{{ t("在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。") }}</p>
      <button class="btn btn--primary" type="button" @click="toggleInstall">
        <Plus :size="14" aria-hidden="true" />
        {{ t("安装插件") }}
      </button>
    </div>

    <div v-else-if="!filteredPlugins.length" class="plugin-empty">
      <span class="plugin-empty-mark" aria-hidden="true"><SearchX :size="20" :stroke-width="1.6" /></span>
      <h2>{{ t("没有匹配的插件") }}</h2>
      <p>{{ t("换个关键词，或清除筛选条件。") }}</p>
      <button class="btn btn--secondary" type="button" data-clear-filters @click="clearFilters">
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
                <button class="btn btn--secondary" type="submit" :disabled="!behaviorQuery.trim()">
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

<style scoped src="../styles/plugin-editor-shell.css"></style>
<style scoped src="../styles/plugin-editor-cards.css"></style>
<style scoped src="../styles/plugin-editor-details.css"></style>
<style scoped src="../styles/plugin-editor-states.css"></style>
