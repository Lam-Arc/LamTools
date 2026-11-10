<template>
  <div
    ref="catalogEl"
    class="mc"
    :class="{ 'mc--inspector': inspectorOpen, 'mc--overlay': overlayInspector, 'mc--narrow': narrowCatalog }"
    data-model-catalog
  >
    <!-- ── 命令条：搜索 / 视图 / 筛选 / 探测 ─────────────────────────── -->
    <header class="mc-bar">
      <label class="mc-search">
        <Search :size="14" :stroke-width="1.9" aria-hidden="true" />
        <input v-model.trim="query" type="search" data-model-catalog-search :placeholder="t('搜索模型或供应商')" />
        <span v-if="query" class="mc-search-total">{{ visibleModelCount }}</span>
      </label>

      <div class="mc-bar-tools">
        <CoreModelCatalogViewToggle
          :model-value="catalogView"
          @update:model-value="(value) => emit('update:catalogView', value)"
        />
        <button
          class="mc-icon"
          :class="{ 'is-on': activeFilterCount > 0 }"
          type="button"
          data-model-filter-toggle
          :aria-label="t('筛选')"
          :aria-expanded="filtersOpen ? 'true' : 'false'"
          @click="filtersOpen = !filtersOpen"
        >
          <SlidersHorizontal :size="15" :stroke-width="1.9" aria-hidden="true" />
          <span v-if="activeFilterCount" class="mc-icon-count">{{ activeFilterCount }}</span>
        </button>
        <button
          class="mc-icon"
          type="button"
          :disabled="probing"
          :aria-label="t('检测连接')"
          data-model-probe
          @click="probeAll(true)"
        >
          <RefreshCw :size="15" :stroke-width="1.9" :class="{ 'mc-spin': probing }" aria-hidden="true" />
        </button>
        <button class="btn btn--primary mc-add-provider" type="button" data-provider-create @click="openProviderCreate()">
          <Plus :size="14" :stroke-width="2.2" aria-hidden="true" />
          <span>{{ t('供应商') }}</span>
        </button>
      </div>

      <div v-if="filtersOpen" class="mc-filter-pop" data-model-filter-pop>
        <label class="mc-field mc-field--inline">
          <span>{{ t('分组') }}</span>
          <UiSelect
            :model-value="groupFilter"
            :options="groupFilterOptions"
            :aria-label="t('按分组筛选')"
            @update:model-value="groupFilter = $event"
          />
        </label>
        <label class="mc-field mc-field--inline">
          <span>{{ t('能力') }}</span>
          <UiSelect
            :model-value="capabilityFilter"
            :options="capabilityFilterOptions"
            :aria-label="t('按能力筛选')"
            @update:model-value="capabilityFilter = $event"
          />
        </label>
        <label class="mc-field mc-field--inline">
          <span>{{ t('连接') }}</span>
          <UiSelect
            :model-value="statusFilter"
            :options="statusFilterOptions"
            :aria-label="t('按连接状态筛选')"
            @update:model-value="statusFilter = $event"
          />
        </label>
        <label class="mc-field mc-field--inline">
          <span>{{ t('排序') }}</span>
          <UiSelect
            :model-value="sortMode"
            :options="sortOptions"
            :aria-label="t('排序方式')"
            @update:model-value="sortMode = $event as ModelSort"
          />
        </label>
        <button class="mc-text-btn" type="button" @click="resetFilters">{{ t('重置') }}</button>
      </div>
    </header>

    <!-- ── 供应商筛选轨 ───────────────────────────────────────────── -->
    <nav class="mc-chips" :aria-label="t('按供应商筛选')">
      <button
        class="mc-chip mc-chip--all"
        :class="{ 'is-on': providerFilter === 'all' }"
        type="button"
        data-provider-filter="all"
        @click="providerFilter = 'all'"
      >
        {{ t('全部') }}<i>{{ models.length }}</i>
      </button>
      <button
        v-for="provider in providers"
        :key="provider.id"
        class="mc-chip mc-chip--provider"
        :class="{ 'is-on': providerFilter === provider.id }"
        type="button"
        :data-provider-filter="provider.id"
        @click="providerFilter = providerFilter === provider.id ? 'all' : provider.id"
      >
        <span class="mc-led" :data-state="statusOf(provider.id).state" aria-hidden="true" />
        <span class="mc-chip-name">{{ provider.name || provider.id }}</span>
        <i>{{ modelsOfProvider(provider.id).length }}</i>
      </button>
    </nav>

    <!-- ── 用量信号带 ─────────────────────────────────────────────── -->
    <section class="mc-signal" :aria-label="t('调用用量')">
      <div class="mc-signal-readout">
        <div class="mc-metric">
          <b>{{ formatTokens(totals.tokens) }}</b>
          <small>tokens</small>
        </div>
        <div class="mc-metric">
          <b>{{ formatCost(totals.cost) }}</b>
          <small>{{ t('费用') }}</small>
        </div>
        <div class="mc-metric">
          <b>{{ formatCalls(totals.calls) }}</b>
          <small>{{ t('调用') }}</small>
        </div>
        <div v-if="totals.unpriced_tokens > 0" class="mc-signal-flag" :title="t('部分模型未配置价格，费用只统计已定价模型')">
          {{ formatTokens(totals.unpriced_tokens) }} {{ t('未定价') }}
        </div>
        <div v-else-if="!totals.calls && !usageLoading" class="mc-signal-note">
          {{ t('本次更新起记录调用') }}
        </div>
      </div>

      <div class="mc-spark" data-model-usage-spark @mouseleave="hoverBar = -1">
        <div
          v-for="(bar, index) in usageBars"
          :key="bar.date"
          class="mc-spark-slot"
          @mouseenter="hoverBar = index"
        >
          <span class="mc-spark-bar" :style="{ '--bar': bar.height }" :class="{ 'is-empty': !bar.tokens, 'is-hover': hoverBar === index }" />
          <span v-if="hoverBar === index" class="mc-spark-tip">
            <b>{{ formatTokens(bar.tokens) }}</b>
            <i>{{ bar.date.slice(5) }}</i>
          </span>
        </div>
      </div>

      <SundaySegmented
        class="mc-range-seg"
        :model-value="range"
        :options="rangeOptions"
        :label="t('统计范围')"
        @update:model-value="setRange"
      />
    </section>

    <div v-if="noticeText" class="mc-notice" role="status">
      <span>{{ noticeText }}</span>
      <button class="mc-icon mc-icon--xs" type="button" @click="noticeText = ''"><X :size="12" aria-hidden="true" /></button>
    </div>

    <!-- ── 模型墙 ─────────────────────────────────────────────────── -->
    <div ref="wallEl" class="mc-wall">
      <template v-if="providers.length">
        <section
          v-for="shelf in shelves"
          :key="shelf.id"
          class="mc-shelf"
          :data-shelf="shelf.kind"
          :data-provider-id="shelf.provider?.id"
        >
          <header class="mc-shelf-head">
            <span
              v-if="shelf.provider"
              class="mc-led"
              :data-state="statusOf(shelf.provider.id).state"
              :title="statusDetail(shelf.provider.id) || statusLabel(shelf.provider.id)"
              aria-hidden="true"
            />
            <span v-else class="mc-led" data-state="group" aria-hidden="true" />

            <span class="mc-shelf-mark" aria-hidden="true">{{ shelfInitial(shelf) }}</span>

            <button
              class="mc-shelf-name"
              type="button"
              :data-model-group-edit="shelf.group?.id"
              @click="shelf.provider ? openProvider(shelf.provider.id) : openGroup(shelf.groupId)"
            >
              <span class="mc-shelf-title">
                <b>{{ shelf.title }}</b>
              </span>
              <span class="mc-shelf-sub">
                <em v-if="shelf.provider">{{ hostOf(shelf.provider.base_url) }}</em>
                <em v-else>{{ shelf.models.length }} {{ t('个模型') }}</em>
                <span v-if="shelf.provider" class="mc-shelf-state" :data-state="statusOf(shelf.provider.id).state" :title="statusDetail(shelf.provider.id) || statusLabel(shelf.provider.id)">
                  {{ statusLabel(shelf.provider.id) }}
                </span>
              </span>
            </button>

            <span class="mc-shelf-metrics">
              <b>{{ shelfUsage(shelf).tokens ? formatTokens(shelfUsage(shelf).tokens) : '—' }}</b>
              <i>{{ formatCost(shelfUsage(shelf).cost) }}</i>
            </span>

            <div class="mc-shelf-actions">
              <button
                v-if="shelf.provider"
                class="mc-icon mc-icon--xs"
                type="button"
                :disabled="probing"
                :aria-label="t('检测这个供应商')"
                :data-provider-probe="shelf.provider.id"
                @click="probeProvider(shelf.provider.id)"
              >
                <RefreshCw :size="13" :stroke-width="1.9" :class="{ 'mc-spin': probingIds.has(shelf.provider.id) }" aria-hidden="true" />
              </button>
              <button
                v-if="shelf.provider"
                class="mc-icon mc-icon--xs"
                type="button"
                :aria-label="t('在这个供应商下新增模型')"
                :data-provider-add-model="shelf.provider.id"
                data-model-create
                @click="openModelCreate(shelf.provider.id)"
              >
                <Plus :size="14" :stroke-width="2.1" aria-hidden="true" />
              </button>
              <button
                v-if="shelf.provider"
                class="mc-icon mc-icon--xs"
                type="button"
                :aria-label="t('编辑供应商')"
                :data-provider-edit="shelf.provider.id"
                @click="openProviderEdit(shelf.provider)"
              >
                <Pencil :size="13" :stroke-width="1.9" aria-hidden="true" />
              </button>
              <template v-if="shelf.kind === 'group' && shelf.group">
                <button class="mc-icon mc-icon--xs" type="button" :aria-label="t('添加已有模型')" :data-model-group-members="shelf.group.id" @click="openGroupMembers(shelf.group)">
                  <Layers :size="13" :stroke-width="1.9" aria-hidden="true" />
                </button>
                <button class="mc-icon mc-icon--xs" type="button" :aria-label="t('删除分组')" :data-model-group-delete="shelf.group.id" @click="requestDeleteGroup(shelf.group)">
                  <Trash2 :size="13" :stroke-width="1.9" aria-hidden="true" />
                </button>
              </template>
            </div>
          </header>

          <div v-if="shelf.provider && budgetOf(shelf.provider.id)" class="mc-budget" :data-provider-budget="shelf.provider.id">
            <span class="mc-budget-track">
              <span class="mc-budget-fill" :style="{ width: budgetPercent(shelf.provider.id) }" />
            </span>
            <span class="mc-budget-text">
              {{ formatCost(monthCostOf(shelf.provider.id)) }} / {{ formatCost(budgetOf(shelf.provider.id)) }}
            </span>
          </div>

          <div v-if="shelf.models.length" class="mc-tiles">
            <!-- user:“停用和启用在卡片上搞个开关”+(开关放在卡片右上角，独立于卡片按钮，
                 点开关只切启停，不会顺带打开右侧检查器。) -->
            <div
              v-for="model in shelf.models"
              :key="model.id"
              class="mc-tile-wrap"
              :data-model-tile="model.id"
            >
              <button
                class="mc-tile"
                :class="{ 'is-selected': selection?.kind === 'model' && selection.id === model.id, 'is-off': model.enabled === false }"
                type="button"
                :data-model-card="model.id"
                @click="openModel(model)"
              >
                <span class="mc-tile-top">
                  <span v-if="model.is_default" class="mc-fallback-dot" :title="t('兜底模型：没有任何会话偏好时使用')" />
                  <span class="mc-tile-name">{{ modelName(model) }}</span>
                </span>
                <span class="mc-tile-id">{{ catalogView === 'group' ? `${providerName(model.provider_id)} · ${model.model_id || model.id}` : (model.model_id || model.id) }}</span>
                <span class="mc-tile-foot">
                  <span class="mc-caps" :title="capabilityTitle(model)" aria-hidden="true">
                    <span class="mc-cap-glyph">文</span>
                    <span v-if="isVision(model)" class="mc-cap-glyph">视</span>
                    <!-- user:“实现...”+(输出类型要在模型列表里看得见，不然只有点进编辑才知道。) -->
                    <span v-if="outputTypeOf(model) !== 'text'" class="mc-cap-glyph">{{ outputGlyph(model) }}</span>
                    <span v-if="model.thinking_supported" class="mc-cap-glyph">推</span>
                  </span>
                  <svg v-if="usageOfModel(model.id).tokens" class="mc-tile-spark" viewBox="0 0 44 14" preserveAspectRatio="none" aria-hidden="true">
                    <path :d="sparkPath(model.id)" />
                  </svg>
                  <span class="mc-tile-usage">
                    <b v-if="usageOfModel(model.id).tokens">{{ formatTokens(usageOfModel(model.id).tokens) }}</b>
                    <i v-if="usageOfModel(model.id).cost !== null">{{ formatCost(usageOfModel(model.id).cost) }}</i>
                  </span>
                </span>
              </button>
              <SundaySwitch
                class="mc-tile-switch"
                :model-value="model.enabled !== false"
                :label="model.enabled === false ? t('启用这个模型') : t('停用这个模型')"
                size="sm"
                :data-model-tile-toggle="model.id"
                @update:model-value="(value: boolean) => toggleModelEnabled(model, value)"
              />
            </div>
            <button
              v-if="shelf.provider && shelf.models.length < 4"
              class="mc-tile mc-tile--slot"
              type="button"
              :aria-label="t('新增模型')"
              :data-shelf-add-model="shelf.provider.id"
              @click="openModelCreate(shelf.provider.id)"
            >
              <Plus :size="14" :stroke-width="1.9" aria-hidden="true" />
              <span>{{ t('添加模型') }}</span>
            </button>
            <div v-if="showShelfWatermark(shelf)" class="mc-shelf-watermark" aria-hidden="true">
              <b>{{ shelfShare(shelf) }}</b>
              <span>{{ t('用量占比') }}</span>
            </div>
          </div>

          <div v-else class="mc-shelf-empty">
            <span>{{ query || activeFilterCount ? t('没有匹配的模型') : t('还没有模型') }}</span>
            <button v-if="shelf.provider && !query" class="mc-text-btn" type="button" @click="openModelCreate(shelf.provider.id)">
              {{ t('添加模型') }}
            </button>
          </div>
        </section>

        <button
          v-if="catalogView === 'group'"
          class="mc-group-new"
          type="button"
          data-model-group-create
          @click="openGroupCreate"
        >
          <Plus :size="14" :stroke-width="2" aria-hidden="true" />
          <span>{{ t('新建分组') }}</span>
        </button>

        <div v-if="!shelves.length" class="mc-no-result">
          <span>{{ t('没有匹配的结果') }}</span>
          <button class="mc-text-btn" type="button" @click="resetFilters">{{ t('清除筛选') }}</button>
        </div>
      </template>

      <div v-else class="mc-first-run">
        <div class="mc-first-copy">
          <strong>{{ t('接入一个模型供应商') }}</strong>
          <span>{{ t('密钥只保存在本机配置里') }}</span>
        </div>
        <div class="mc-preset-grid">
          <button
            v-for="preset in quickPresets"
            :key="preset.id"
            class="mc-preset"
            type="button"
            :data-provider-preset-card="preset.id"
            @click="openProviderCreate(preset.id)"
          >
            <span class="mc-preset-label">{{ preset.label }}</span>
            <span class="mc-preset-host">{{ hostOf(preset.baseUrl) }}</span>
          </button>
          <button class="mc-preset mc-preset--custom" type="button" @click="openProviderCreate()">
            <span class="mc-preset-label">{{ t('自定义接口') }}</span>
            <span class="mc-preset-host">{{ t('OpenAI 兼容') }}</span>
          </button>
        </div>
        <button
          v-if="allowEnvironmentImport"
          class="btn btn--ghost"
          type="button"
          data-import-environment
          @click="emit('import-environment')"
        >
          {{ t('从当前环境导入') }}
        </button>
      </div>
    </div>

    <div
      v-if="draft"
      class="mc-draft-catcher editor-overlay"
      aria-hidden="true"
      @pointerdown="requestDraftDismiss"
    />

    <!-- ── 右侧检查器 / 编辑器 ───────────────────────────────────── -->
    <aside
      v-if="inspectorOpen"
      ref="inspectorEl"
      class="mc-inspector"
      :style="overlayInspector ? overlayInspectorStyle : undefined"
      :aria-label="t('详情')"
    >
      <template v-if="draft">
        <header class="mc-insp-head">
          <div class="mc-insp-title">
            <span class="mc-insp-kicker">{{ draftKicker }}</span>
            <h2>{{ draftTitle }}</h2>
          </div>
          <button class="mc-icon mc-icon--xs editor-popover-close" type="button" :aria-label="t('关闭')" @click="requestCloseDraft">
            <X :size="14" aria-hidden="true" />
          </button>
        </header>

        <fieldset class="settings-editor-fields" :disabled="saving">
        <p v-if="draftError" class="mc-error editor-error" role="alert" data-model-editor-error>{{ draftError }}</p>

        <!-- 供应商编辑 -->
        <form v-if="draft.kind === 'provider'" class="mc-form" :data-provider-form="draft.mode" @submit.prevent="saveDraft">
          <template v-if="draft.mode === 'create'">
            <label class="mc-field">
              <span>{{ t('官方模板') }}</span>
              <UiSelect
                :model-value="draft.presetId"
                :options="presetOptions"
                data-provider-preset
                :placeholder="t('自定义')"
                :aria-label="t('官方模板')"
                @update:model-value="applyPreset"
              />
            </label>
            <button
              v-if="draftPreset?.apiKeyUrl"
              class="mc-text-btn mc-text-btn--start"
              type="button"
              data-provider-api-key-link
              @click="openPresetKeyPage"
            >
              {{ t('去申请 API Key') }} <ArrowUpRight :size="12" aria-hidden="true" />
            </button>
          </template>

          <label class="mc-field">
            <span>{{ t('名称') }}</span>
            <input v-model.trim="draft.name" data-provider-name required :placeholder="t('例如：OpenCode Go')" />
          </label>
          <label class="mc-field">
            <span>{{ t('接口地址') }}</span>
            <input v-model.trim="draft.baseUrl" data-provider-base-url type="url" required placeholder="https://api.example.com/v1" />
          </label>
          <label class="mc-field">
            <span>API Key</span>
            <span class="mc-input-row">
              <input
                v-model.trim="draft.apiKey"
                data-provider-api-key
                :type="showKey ? 'text' : 'password'"
                autocomplete="new-password"
                :required="draft.mode === 'create' && !draft.hasStoredKey"
                :placeholder="draft.hasStoredKey ? t('留空可保留现有密钥') : 'sk-…'"
              />
              <button
                class="mc-icon mc-icon--xs"
                type="button"
                :aria-label="showKey ? t('隐藏密钥') : t('显示密钥')"
                @click="showKey = !showKey"
              >
                <Eye v-if="showKey" :size="13" aria-hidden="true" />
                <EyeOff v-else :size="13" aria-hidden="true" />
              </button>
            </span>
          </label>
          <label class="mc-field">
            <span>{{ t('每月额度') }} <small>USD</small></span>
            <input v-model="draft.budget" data-provider-budget type="number" min="0" step="1" :placeholder="t('不设额度')" />
          </label>

          <details class="mc-advanced">
            <summary>{{ t('高级') }}</summary>
            <label class="mc-field">
              <span>{{ t('接口类型') }}</span>
              <UiSelect
                :model-value="draft.apiType"
                :options="apiTypeOptions"
                data-provider-api-type
                direction="up"
                :aria-label="t('接口类型')"
                @update:model-value="draft.apiType = $event"
              />
            </label>
            <label class="mc-field">
              <span>{{ t('适配参数 JSON') }}</span>
              <textarea v-model="draft.extraJson" rows="4" spellcheck="false" placeholder="{}" />
            </label>
          </details>

          <footer class="mc-form-actions">
            <button class="mc-text-btn" type="button" @click="closeDraftNow">{{ t('取消') }}</button>
            <button class="btn btn--primary" type="submit" :disabled="saving" data-provider-submit>
              {{ draft.mode === 'create' ? t('添加并检测') : t('保存并检测') }}
            </button>
          </footer>
        </form>

        <!-- 模型编辑 -->
        <form v-else-if="draft.kind === 'model'" class="mc-form" :data-model-form="draft.mode" @submit.prevent="saveDraft">
          <label class="mc-field">
            <span>{{ t('显示名称') }}</span>
            <input v-model.trim="draft.displayName" data-model-display-name :placeholder="t('留空时使用模型 ID')" />
          </label>
          <label class="mc-field">
            <span>{{ t('模型 ID') }}</span>
            <input v-model.trim="draft.modelId" data-model-id required placeholder="deepseek-v4.1-flash" />
          </label>
          <label class="mc-field">
            <span>{{ t('供应商') }}</span>
            <UiSelect
              :model-value="draft.providerId"
              :options="providerOptions"
              data-model-provider-id
              :disabled="draft.mode === 'update'"
              :aria-label="t('供应商')"
              @update:model-value="draft.providerId = $event"
            />
          </label>

          <div class="mc-field">
            <span>{{ t('能力') }}</span>
            <SundaySegmented
              class="mc-cap-seg"
              :model-value="draft.capability"
              :options="capabilityOptions"
              :label="t('能力')"
              @update:model-value="setDraftCapability"
            />
          </div>

          <div class="mc-field">
            <span>{{ t('输出') }}</span>
            <SundaySegmented
              class="mc-cap-seg"
              :model-value="draft.outputType"
              :options="outputOptions"
              :label="t('输出')"
              data-model-output-type
              @update:model-value="setDraftOutputType"
            />
          </div>

          <label class="mc-field mc-field--switch">
            <span>{{ t('启用') }}</span>
            <SundaySwitch v-model="draft.enabled" :label="t('启用')" size="sm" />
          </label>

          <div class="mc-field-grid">
            <label class="mc-field">
              <span>{{ t('上下文') }}</span>
              <input v-model.number="draft.contextWindow" data-model-context type="number" min="0" step="1000" />
            </label>
            <label class="mc-field">
              <span>{{ t('最大输出') }}</span>
              <input v-model.number="draft.maxOutputTokens" data-model-max-output type="number" min="0" step="512" />
            </label>
            <label class="mc-field">
              <span>{{ t('温度') }}</span>
              <input v-model.number="draft.temperature" type="number" min="0" max="2" step="0.1" />
            </label>
            <label class="mc-field mc-field--switch">
              <span>{{ t('推理') }}</span>
              <SundaySwitch v-model="draft.thinkingSupported" :label="t('推理')" size="sm" />
            </label>
          </div>

          <label v-if="draft.thinkingSupported" class="mc-field">
            <span>{{ t('推理预算') }}</span>
            <input v-model.number="draft.thinkingBudget" type="number" min="0" step="1024" />
          </label>

          <div class="mc-field-grid mc-field-grid--price">
            <label class="mc-field">
              <span>{{ t('输入价') }} <small>/1M</small></span>
              <input v-model="draft.priceInput" data-model-price-input type="number" min="0" step="0.01" placeholder="—" />
            </label>
            <label class="mc-field">
              <span>{{ t('输出价') }} <small>/1M</small></span>
              <input v-model="draft.priceOutput" data-model-price-output type="number" min="0" step="0.01" placeholder="—" />
            </label>
            <label class="mc-field">
              <span>{{ t('缓存价') }} <small>/1M</small></span>
              <input v-model="draft.priceCacheRead" type="number" min="0" step="0.01" placeholder="—" />
            </label>
          </div>

          <label class="mc-field">
            <span>{{ t('备注') }}</span>
            <textarea v-model.trim="draft.notes" rows="2" spellcheck="false" :placeholder="t('选填')" />
          </label>

          <details class="mc-advanced">
            <summary>{{ t('高级') }}</summary>
            <label class="mc-field">
              <span>{{ t('适配参数 JSON') }}</span>
              <textarea v-model="draft.extraJson" rows="4" spellcheck="false" placeholder="{}" />
            </label>
          </details>

          <footer class="mc-form-actions">
            <button class="mc-text-btn" type="button" @click="closeDraftNow">{{ t('取消') }}</button>
            <button class="btn btn--primary" type="submit" :disabled="saving" data-model-submit>
              {{ draft.mode === 'create' ? t('添加模型') : t('保存') }}
            </button>
          </footer>
        </form>

        <!-- 分组成员 -->
        <div v-else-if="draft.kind === 'group-members'" class="mc-form" data-model-group-members-form>
          <label class="mc-field">
            <span>{{ t('分组名称') }}</span>
            <input v-model.trim="draft.name" data-model-group-name required maxlength="80" />
          </label>
          <div class="mc-member-list">
            <label v-for="model in models" :key="model.id" class="mc-member">
              <input v-model="draft.modelIds" type="checkbox" :value="model.id" />
              <span>
                <b>{{ modelName(model) }}</b>
                <small>{{ providerName(model.provider_id) }}</small>
              </span>
            </label>
            <span v-if="!models.length" class="mc-muted">{{ t('暂无可添加的模型') }}</span>
          </div>
          <footer class="mc-form-actions">
            <button class="mc-text-btn" type="button" @click="closeDraftNow">{{ t('取消') }}</button>
            <button class="btn btn--primary" type="button" data-model-group-members-save :disabled="saving" @click="saveGroupMembers">
              {{ t('保存分组') }}
            </button>
          </footer>
        </div>

        <!-- 新建分组 -->
        <form v-else-if="draft.kind === 'group-create'" class="mc-form" data-model-group-form @submit.prevent="saveDraft">
          <label class="mc-field">
            <span>{{ t('名称') }}</span>
            <input v-model.trim="draft.name" data-model-group-name required maxlength="80" :placeholder="t('例如：Free')" />
          </label>
          <footer class="mc-form-actions">
            <button class="mc-text-btn" type="button" @click="closeDraftNow">{{ t('取消') }}</button>
            <button class="btn btn--primary" type="submit" :disabled="saving">{{ t('创建') }}</button>
          </footer>
        </form>
        </fieldset>
      </template>

      <!-- 模型详情 -->
      <template v-else-if="selection?.kind === 'model' && selectedModel">
        <header class="mc-insp-head">
          <div class="mc-insp-title">
            <span class="mc-insp-kicker">{{ t('模型') }}</span>
            <h2>{{ modelName(selectedModel) }}</h2>
            <code>{{ selectedModel.model_id || selectedModel.id }}</code>
          </div>
          <button class="mc-icon mc-icon--xs" type="button" :aria-label="t('关闭')" @click="closeInspector">
            <X :size="14" aria-hidden="true" />
          </button>
        </header>

        <div class="mc-insp-provider">
          <button class="mc-insp-provider-btn" type="button" @click="openProvider(selectedModel.provider_id)">
            <span class="mc-led" :data-state="statusOf(selectedModel.provider_id).state" aria-hidden="true" />
            {{ providerName(selectedModel.provider_id) }}
            <span class="mc-insp-provider-state">{{ statusLabel(selectedModel.provider_id) }}</span>
          </button>
        </div>

        <div class="mc-insp-metrics">
          <div><b>{{ formatTokens(usageOfModel(selectedModel.id).tokens) }}</b><small>tokens</small></div>
          <div><b>{{ usageOfModel(selectedModel.id).calls }}</b><small>{{ t('调用') }}</small></div>
          <div><b>{{ formatCost(usageOfModel(selectedModel.id).cost) }}</b><small>{{ t('费用') }}</small></div>
        </div>

        <div class="mc-cap-grid">
          <div class="mc-cap" :class="{ 'is-on': true }">
            <MessageCircle :size="15" :stroke-width="1.8" aria-hidden="true" /><span>{{ t('对话') }}</span>
          </div>
          <div class="mc-cap" :class="{ 'is-on': isVision(selectedModel) }">
            <Eye :size="14" :stroke-width="1.8" aria-hidden="true" /><span>{{ t('视觉') }}</span>
          </div>
          <div class="mc-cap" :class="{ 'is-on': selectedModel.thinking_supported }">
            <Brain :size="14" :stroke-width="1.8" aria-hidden="true" /><span>{{ t('推理') }}</span>
          </div>
        </div>

        <div class="mc-insp-switch">
          <span class="mc-insp-label">{{ t('启用') }}</span>
          <SundaySwitch
            v-model="selectedModelEnabled"
            data-model-enabled-toggle
            :label="t('启用')"
            size="sm"
          />
        </div>

        <dl class="mc-spec">
          <div><dt>{{ t('上下文') }}</dt><dd>{{ formatTokens(selectedModel.context_window) }}</dd></div>
          <div><dt>{{ t('最大输出') }}</dt><dd>{{ formatTokens(selectedModel.max_output_tokens) }}</dd></div>
          <div><dt>{{ t('温度') }}</dt><dd>{{ selectedModel.temperature ?? '—' }}</dd></div>
          <div><dt>{{ t('价格') }} /1M</dt><dd>{{ priceText(selectedModel) }}</dd></div>
          <div><dt>{{ t('兜底') }}</dt><dd>{{ selectedModel.is_default ? t('是') : t('否') }}</dd></div>
          <div v-if="selectedModel.notes"><dt>{{ t('备注') }}</dt><dd>{{ selectedModel.notes }}</dd></div>
          <div v-if="usageOfModel(selectedModel.id).last_used_at"><dt>{{ t('最近使用') }}</dt><dd>{{ shortTime(usageOfModel(selectedModel.id).last_used_at) }}</dd></div>
        </dl>

        <div v-if="modelGroups.length" class="mc-insp-groups">
          <span class="mc-insp-label">{{ t('分组') }}</span>
          <div class="mc-chip-row">
            <button
              v-for="group in modelGroups"
              :key="group.id"
              class="mc-chip"
              :class="{ 'is-on': group.model_ids.includes(selectedModel.id) }"
              type="button"
              :data-model-group-toggle="group.id"
              @click="toggleModelGroup(group)"
            >
              {{ group.name }}
            </button>
          </div>
        </div>

        <footer class="mc-insp-actions">
          <button class="btn btn--primary" type="button" data-model-edit="1" @click="openModelEdit(selectedModel)">
            {{ t('编辑') }}
          </button>
          <button
            v-if="!selectedModel.is_default && selectedModel.enabled !== false"
            class="btn btn--ghost"
            type="button"
            data-model-default="1"
            @click="setFallback(selectedModel)"
          >
            {{ t('设为兜底') }}
          </button>
          <button class="mc-icon mc-icon--xs mc-danger" type="button" :aria-label="t('删除模型')" data-model-delete="1" @click="requestDeleteModel(selectedModel)">
            <Trash2 :size="14" aria-hidden="true" />
          </button>
        </footer>
      </template>

      <!-- 供应商详情 -->
      <template v-else-if="selection?.kind === 'provider' && selectedProvider">
        <header class="mc-insp-head">
          <div class="mc-insp-title">
            <span class="mc-insp-kicker">{{ t('供应商') }}</span>
            <h2>{{ selectedProvider.name || selectedProvider.id }}</h2>
            <code>{{ apiTypeLabel(selectedProvider.api_type) }}</code>
          </div>
          <button class="mc-icon mc-icon--xs" type="button" :aria-label="t('关闭')" @click="closeInspector">
            <X :size="14" aria-hidden="true" />
          </button>
        </header>

        <div class="mc-conn" :data-state="statusOf(selectedProvider.id).state">
          <span class="mc-led" :data-state="statusOf(selectedProvider.id).state" aria-hidden="true" />
          <div>
            <b>{{ statusLabel(selectedProvider.id) }}</b>
            <span>{{ statusDetail(selectedProvider.id) || statusHint(selectedProvider.id) }}</span>
          </div>
          <button class="mc-text-btn" type="button" :disabled="probing" @click="probeProvider(selectedProvider.id)">
            {{ t('检测') }}
          </button>
        </div>

        <div class="mc-insp-metrics">
          <div><b>{{ formatTokens(usageOfProvider(selectedProvider.id).tokens) }}</b><small>tokens</small></div>
          <div><b>{{ formatCost(usageOfProvider(selectedProvider.id).cost) }}</b><small>{{ t('费用') }}</small></div>
          <div><b>{{ modelsOfProvider(selectedProvider.id).length }}</b><small>{{ t('模型') }}</small></div>
        </div>

        <div v-if="budgetOf(selectedProvider.id)" class="mc-budget mc-budget--insp">
          <span class="mc-budget-track"><span class="mc-budget-fill" :style="{ width: budgetPercent(selectedProvider.id) }" /></span>
          <span class="mc-budget-text">
            {{ formatCost(monthCostOf(selectedProvider.id)) }} / {{ formatCost(budgetOf(selectedProvider.id)) }}
          </span>
        </div>

        <dl class="mc-spec">
          <div><dt>{{ t('接口地址') }}</dt><dd class="mc-mono">{{ selectedProvider.base_url || '—' }}</dd></div>
          <div><dt>{{ t('密钥') }}</dt><dd>{{ selectedProvider.has_api_key ? t('已配置') : t('未配置') }}</dd></div>
          <div v-if="statusOf(selectedProvider.id).checked_at"><dt>{{ t('检测时间') }}</dt><dd>{{ shortTime(statusOf(selectedProvider.id).checked_at) }}</dd></div>
          <div v-if="statusOf(selectedProvider.id).model_count"><dt>{{ t('接口模型数') }}</dt><dd>{{ statusOf(selectedProvider.id).model_count }}</dd></div>
        </dl>

        <footer class="mc-insp-actions">
          <button class="btn btn--primary" type="button" data-provider-edit="1" @click="openProviderEdit(selectedProvider)">
            {{ t('编辑') }}
          </button>
          <button class="btn btn--ghost" type="button" data-provider-add-model="1" @click="openModelCreate(selectedProvider.id)">
            {{ t('新增模型') }}
          </button>
          <button class="mc-icon mc-icon--xs mc-danger" type="button" :aria-label="t('删除供应商')" data-provider-delete="1" @click="requestDeleteProvider(selectedProvider)">
            <Trash2 :size="14" aria-hidden="true" />
          </button>
        </footer>
      </template>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

/**
 * 模型与供应商目录。
 *
 * user:“重新设计 Sunday 的「模型与供应商」界面”+(把供应商、密钥、接口地址、模型配置
 * 收进同一张目录；顶部是调用用量信号带，中间按供应商/分组铺模型瓦片，右侧检查器
 * 兼顾查看与编辑；兜底模型只留一个小标记，不再占据页首。)
 */
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { gsap } from 'gsap'
import {
  ArrowUpRight,
  Brain,
  Eye,
  EyeOff,
  MessageCircle,
  Layers,
  MessageSquare,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  X,
} from 'lucide-vue-next'
import CoreModelCatalogViewToggle from '@/components/CoreModelCatalogViewToggle.vue'
import UiSelect from '@/components/UiSelect.vue'
import SundaySegmented from '@/components/SundaySegmented.vue'
import SundaySwitch from '@/components/SundaySwitch.vue'
import { createSettingsDraftGuard, useSettingsDraft } from '@/composables/useSettingsDraftGuard.ts'
import { openExternalUrl } from '@/helpers/openUrl.ts'
import { PROVIDER_PRESETS, providerPresetModelExtra, type ProviderPreset } from '@/data/provider-presets.ts'
import type { CoreModelCatalogView } from '@/composer/execution.ts'
import type {
  CoreModelPricing,
  CoreSettingsModel,
  CoreSettingsModelGroup,
  CoreSettingsModelPayload,
  CoreSettingsProvider,
  CoreSettingsProviderPayload,
  ModelCatalogRange,
  ModelUsageEntry,
  ModelUsageSummary,
  ProviderConnectionState,
  ProviderConnectionStatus,
  ProviderUsageEntry,
  SettingsCatalogMutation,
} from '@/components/model-catalog/types.ts'

type Rpc = (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
type SettingsDraftGuard = ReturnType<typeof createSettingsDraftGuard>
type Persist = (operation: SettingsCatalogMutation, payload: Record<string, unknown>) => Promise<void>

const props = withDefaults(defineProps<{
  models: CoreSettingsModel[]
  providers: CoreSettingsProvider[]
  modelGroups?: CoreSettingsModelGroup[]
  catalogView?: CoreModelCatalogView
  requestRpc?: Rpc
  persistCatalog?: Persist
  draftGuard?: SettingsDraftGuard
  allowEnvironmentImport?: boolean
}>(), {
  modelGroups: () => [],
  catalogView: 'provider',
  allowEnvironmentImport: false,
})

const emit = defineEmits<{
  'update:catalogView': [value: CoreModelCatalogView]
  'create-provider': [payload: CoreSettingsProviderPayload]
  'update-provider': [payload: CoreSettingsProviderPayload]
  'delete-provider': [providerId: string]
  'create-model': [payload: CoreSettingsModelPayload]
  'update-model': [payload: CoreSettingsModelPayload]
  'delete-model': [modelRecordId: string]
  'set-default-model': [modelId: string]
  'create-model-group': [payload: { name: string }]
  'update-model-group': [payload: { group_id: string; name: string }]
  'delete-model-group': [groupId: string]
  'set-model-group-members': [payload: { group_id: string; model_ids: string[] }]
  'create-model-with-provider': [payload: Record<string, unknown>]
  'import-environment': []
}>()

type ModelSort = 'usage' | 'name' | 'default'
type Selection = { kind: 'provider' | 'model'; id: string }

interface ShelfModel {
  provider: CoreSettingsProvider | null
  groupId?: string
  group?: CoreSettingsModelGroup
  kind: 'provider' | 'group'
  id: string
  title: string
  models: CoreSettingsModel[]
}

type Draft =
  | {
      kind: 'provider'
      mode: 'create' | 'update'
      id?: string
      presetId: string
      name: string
      apiType: string
      baseUrl: string
      apiKey: string
      hasStoredKey: boolean
      budget: string
      extraJson: string
    }
  | {
      kind: 'model'
      mode: 'create' | 'update'
      recordId?: string
      providerId: string
      modelId: string
      displayName: string
      capability: 'text' | 'multimodal'; outputType: 'text' | 'image' | 'video' | 'audio'
      enabled: boolean
      isDefault: boolean
      contextWindow: number
      maxOutputTokens: number
      temperature: number
      thinkingSupported: boolean
      thinkingBudget: number
      priceInput: string
      priceOutput: string
      priceCacheRead: string
      notes: string
      extraJson: string
    }
  | { kind: 'group-members'; groupId: string; name: string; modelIds: string[] }
  | { kind: 'group-create'; name: string }

const range = ref<ModelCatalogRange>('30d')
const usage = ref<ModelUsageSummary | null>(null)
const usageLoading = ref(false)
const statuses = ref<Record<string, ProviderConnectionStatus>>({})
const statusUpdatedAt = ref('')
const probing = ref(false)
const probingIds = reactive(new Set<string>())

const query = ref('')
const filtersOpen = ref(false)
const providerFilter = ref('all')
const groupFilter = ref('all')
const capabilityFilter = ref('all')
const statusFilter = ref('all')
const sortMode = ref<ModelSort>('usage')
const hoverBar = ref(-1)

const selection = ref<Selection | null>(null)
const draft = ref<Draft | null>(null)
const draftError = ref('')
const saving = ref(false)
const showKey = ref(false)
const noticeText = ref('')
const catalogEl = ref<HTMLElement | null>(null)
const wallEl = ref<HTMLElement | null>(null)
const wallWidth = ref(0)
const catalogWidth = ref(0)
/** Below this width the inspector overlays the wall instead of eating a column. */
const INSPECTOR_COLUMN_MIN_WIDTH = 1180
const overlayInspector = computed(() => catalogWidth.value > 0 && catalogWidth.value < INSPECTOR_COLUMN_MIN_WIDTH)
const narrowCatalog = computed(() => catalogWidth.value > 0 && catalogWidth.value < 800)
const overlayTop = ref(180)
const overlayRight = ref(18)
const overlayInspectorStyle = computed(() => ({
  top: `${overlayTop.value}px`,
  right: `${overlayRight.value}px`,
  maxHeight: `calc(100dvh - ${overlayTop.value}px - 16px)`,
}))

/** Keep the overlay drawer pinned to the top-right of the wall, under the controls. */
function updateOverlayGeometry(): void {
  const wall = wallEl.value
  if (!wall) return
  const rect = wall.getBoundingClientRect()
  overlayTop.value = Math.max(8, Math.round(rect.top + 8))
  overlayRight.value = Math.max(8, Math.round(window.innerWidth - rect.right))
}
const inspectorEl = ref<HTMLElement | null>(null)
const serverTracked = ref(false)

const rangeOptions: Array<{ value: ModelCatalogRange; label: string }> = [
  { value: '24h', get label() { return t('24 时') } },
  { value: '7d', get label() { return t('7 天') } },
  { value: '30d', get label() { return t('30 天') } },
]

const capabilityOptions: Array<{ value: 'text' | 'multimodal'; label: string }> = [
  { value: 'text', get label() { return t('文本') } },
  { value: 'multimodal', get label() { return t('视觉') } },
]

// user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
// +(模型能产出什么要在配置里写清楚，调用台才能给它配对的输入表单与结果区。)
const outputOptions: Array<{ value: 'text' | 'image' | 'video' | 'audio'; label: string }> = [
  { value: 'text', get label() { return t('文本') } },
  { value: 'image', get label() { return t('图片') } },
  { value: 'video', get label() { return t('视频') } },
  { value: 'audio', get label() { return t('音频') } },
]

function normalizeOutputType(value: unknown): 'text' | 'image' | 'video' | 'audio' {
  const normalized = String(value || '').trim().toLowerCase()
  return normalized === 'image' || normalized === 'video' || normalized === 'audio' ? normalized : 'text'
}

function outputTypeOf(model: CoreSettingsModel): 'text' | 'image' | 'video' | 'audio' {
  return normalizeOutputType(model.output_type)
}

function outputGlyph(model: CoreSettingsModel): string {
  const type = outputTypeOf(model)
  return type === 'image' ? '图' : type === 'video' ? '影' : type === 'audio' ? '音' : ''
}

const apiTypeOptions = [
  { value: 'openai', label: 'OpenAI compatible' },
  { value: 'anthropic', label: 'Anthropic' },
]

const capabilityFilterOptions = computed(() => [
  { value: 'all', get label() { return t('全部能力') } },
  { value: 'text', get label() { return t('文本') } },
  { value: 'multimodal', get label() { return t('视觉') } },
])

const statusFilterOptions = computed(() => [
  { value: 'all', get label() { return t('全部连接') } },
  { value: 'ready', get label() { return t('可用') } },
  { value: 'attention', get label() { return t('待处理') } },
])

const sortOptions = computed(() => [
  { value: 'usage', get label() { return t('按用量') } },
  { value: 'default', get label() { return t('按默认顺序') } },
  { value: 'name', get label() { return t('按名称') } },
])

const groupFilterOptions = computed(() => [
  { value: 'all', get label() { return t('全部分组') } },
  { value: 'none', get label() { return t('未分组') } },
  ...props.modelGroups.map(group => ({ value: group.id, label: group.name })),
])

const providerOptions = computed(() => props.providers.map(provider => ({
  value: provider.id,
  label: provider.name || provider.id,
})))

const presetOptions = computed(() => [
  { value: '', get label() { return t('自定义') } },
  ...PROVIDER_PRESETS.map(preset => ({ value: preset.id, label: preset.label })),
])

const quickPresets = computed(() => PROVIDER_PRESETS.filter(preset =>
  ['openai', 'anthropic', 'deepseek', 'zhipu', 'opencode-zen', 'opencode-go'].includes(preset.id),
).slice(0, 5))

const draftPreset = computed<ProviderPreset | null>(() => {
  const current = draft.value
  if (current?.kind !== 'provider' || !current.presetId) return null
  return PROVIDER_PRESETS.find(item => item.id === current.presetId) || null
})

const totals = computed(() => usage.value?.totals || {
  calls: 0, input_tokens: 0, output_tokens: 0, cached_tokens: 0, tokens: 0,
  cost: 0, unpriced_tokens: 0, currency: 'USD',
})

const usageByModel = computed(() => {
  const map = new Map<string, ModelUsageEntry>()
  for (const entry of usage.value?.by_model || []) map.set(entry.model_record_id, entry)
  return map
})

const usageByProvider = computed(() => {
  const map = new Map<string, ProviderUsageEntry>()
  for (const entry of usage.value?.by_provider || []) map.set(entry.provider_id, entry)
  return map
})

const inspectorOpen = computed(() => Boolean(selection.value || draft.value))

function setRange(value: string): void {
  range.value = value === '24h' || value === '7d' ? value : '30d'
}

function setDraftCapability(value: string): void {
  if (draft.value?.kind !== 'model') return
  draft.value.capability = value === 'multimodal' ? 'multimodal' : 'text'
}
function setDraftOutputType(value: string): void {
  if (draft.value?.kind !== 'model') return
  draft.value.outputType = normalizeOutputType(value)
}
const selectedModel = computed(() => selection.value?.kind === 'model'
  ? props.models.find(model => model.id === selection.value!.id) || null
  : null)
const selectedProvider = computed(() => selection.value?.kind === 'provider'
  ? props.providers.find(provider => provider.id === selection.value!.id) || null
  : null)
const selectedModelEnabled = computed({
  get: () => selectedModel.value?.enabled !== false,
  set: (value: boolean) => {
    const model = selectedModel.value
    if (model) void toggleModelEnabled(model, value)
  },
})

const activeFilterCount = computed(() =>
  Number(groupFilter.value !== 'all')
  + Number(capabilityFilter.value !== 'all')
  + Number(statusFilter.value !== 'all')
  + Number(providerFilter.value !== 'all'),
)

const visibleModelCount = computed(() => shelves.value.reduce((total, shelf) => total + shelf.models.length, 0))

const shelves = computed<ShelfModel[]>(() => {
  const normalizedQuery = query.value.toLocaleLowerCase()
  const matches = (model: CoreSettingsModel) => {
    if (!normalizedQuery) return true
    return [model.display_name, model.model_id, model.id, model.provider_name, model.notes]
      .some(value => String(value || '').toLocaleLowerCase().includes(normalizedQuery))
  }
  const capabilityOk = (model: CoreSettingsModel) => capabilityFilter.value === 'all'
    || (model.capability || 'text') === capabilityFilter.value
  const statusOk = (providerId: string | undefined) => {
    if (statusFilter.value === 'all') return true
    const state = statusOf(providerId).state
    const ready = state === 'ok' || state === 'no_model_list'
    return statusFilter.value === 'ready' ? ready : !ready
  }
  const sortModels = (models: CoreSettingsModel[]) => [...models].sort((a, b) => {
    if (sortMode.value === 'name') return modelName(a).localeCompare(modelName(b))
    if (sortMode.value === 'usage') {
      const delta = usageOfModel(b.id).tokens - usageOfModel(a.id).tokens
      if (delta !== 0) return delta
    }
    if (a.is_default !== b.is_default) return a.is_default ? 1 : -1
    return modelName(a).localeCompare(modelName(b))
  })
  const groupedIds = new Set(props.modelGroups.flatMap(group => group.model_ids))
  const selectedGroup = props.modelGroups.find(group => group.id === groupFilter.value)
  const groupOk = (model: CoreSettingsModel) => {
    if (groupFilter.value === 'all') return true
    if (groupFilter.value === 'none') return !groupedIds.has(model.id)
    return Boolean(selectedGroup?.model_ids.includes(model.id))
  }
  const accepted = (model: CoreSettingsModel) =>
    matches(model) && capabilityOk(model) && statusOk(model.provider_id) && groupOk(model)

  if (props.catalogView === 'group') {
    const providerOk = (model: CoreSettingsModel) => providerFilter.value === 'all' || model.provider_id === providerFilter.value
    const groupShelves: ShelfModel[] = props.modelGroups
      .filter(group => groupFilter.value === 'all' || groupFilter.value === group.id || groupFilter.value === 'none')
      .map(group => ({
        kind: 'group' as const,
        id: `group:${group.id}`,
        groupId: group.id,
        group,
        provider: null,
        title: group.name,
        models: sortModels(props.models.filter(model =>
          group.model_ids.includes(model.id) && providerOk(model) && accepted(model))),
      }))
      .filter(shelf => shelf.models.length > 0 || (!query.value && activeFilterCount.value === 0))
    const grouped = new Set(props.modelGroups.flatMap(group => group.model_ids))
    const ungrouped = props.models.filter(model => !grouped.has(model.id) && providerOk(model) && accepted(model))
    if (groupFilter.value === 'all' || groupFilter.value === 'none') {
      if (ungrouped.length || !query.value) {
        groupShelves.push({
          kind: 'group',
          id: 'group:__ungrouped__',
          provider: null,
          title: t('未分组'),
          models: sortModels(ungrouped),
        })
      }
    }
    return groupShelves
  }

  const providers = props.providers.filter(provider => providerFilter.value === 'all' || provider.id === providerFilter.value)
  return providers
    .map(provider => ({
      kind: 'provider' as const,
      id: `provider:${provider.id}`,
      provider,
      title: provider.name || provider.id,
      models: sortModels(props.models.filter(model => model.provider_id === provider.id && accepted(model))),
    }))
    .filter(shelf => shelf.models.length > 0 || (!query.value && activeFilterCount.value === 0))
})

const usageBars = computed(() => {
  const days = usage.value?.daily || []
  const peak = Math.max(1, ...days.map(day => day.tokens))
  return days.map(day => ({
    date: day.date,
    tokens: day.tokens,
    height: `${Math.max(day.tokens ? 6 : 2, Math.round((day.tokens / peak) * 100))}%`,
  }))
})

function usageOfModel(id: string): { tokens: number; calls: number; cost: number | null; last_used_at?: string } {
  const entry = usageByModel.value.get(id)
  return entry || { tokens: 0, calls: 0, cost: null }
}

function usageOfProvider(id: string | undefined): { tokens: number; cost: number | null; calls: number } {
  if (!id) return { tokens: 0, cost: null, calls: 0 }
  const entry = usageByProvider.value.get(id)
  if (!entry) return { tokens: 0, cost: null, calls: 0 }
  return {
    tokens: entry.tokens,
    cost: entry.priced_tokens > 0 ? entry.cost : null,
    calls: entry.calls,
  }
}

function shelfUsage(shelf: ShelfModel): { tokens: number; cost: number | null } {
  if (shelf.provider) return usageOfProvider(shelf.provider.id)
  let tokens = 0
  let cost = 0
  let priced = false
  for (const model of shelf.models) {
    const entry = usageOfModel(model.id)
    tokens += entry.tokens
    if (entry.cost !== null) {
      priced = true
      cost += entry.cost
    }
  }
  return { tokens, cost: priced ? cost : null }
}

function shelfShare(shelf: ShelfModel): string {
  const total = totals.value.tokens
  if (!total) return '0%'
  const share = (shelfUsage(shelf).tokens / total) * 100
  if (share > 0 && share < 1) return '<1%'
  return `${Math.round(share)}%`
}

const tileColumns = computed(() => Math.max(1, Math.floor((wallWidth.value + 6) / 230)))

function showShelfWatermark(shelf: ShelfModel): boolean {
  if (shelfUsage(shelf).tokens <= 0) return false
  // The add slot also occupies a column; only the leftover columns may host
  // the share watermark, so it never wraps onto a line of its own.
  const occupied = shelf.models.length + (shelf.provider && shelf.models.length < 4 ? 1 : 0)
  return occupied < tileColumns.value
}

function monthCostOf(id: string): number {
  return usageByProvider.value.get(id)?.month_cost || 0
}

function budgetOf(id: string): number | null {
  return usageByProvider.value.get(id)?.budget_usd ?? null
}

function budgetPercent(id: string): string {
  const budget = budgetOf(id)
  if (!budget) return '0%'
  return `${Math.min(100, Math.round((monthCostOf(id) / budget) * 100))}%`
}

function statusOf(providerId: string | undefined): ProviderConnectionStatus {
  return statuses.value[providerId || ''] || {
    state: 'unknown', detail: '', latency_ms: 0, http_status: 0, model_count: 0, checked_at: '',
  }
}

const STATUS_LABELS: Record<ProviderConnectionState, string> = {
  ok: '在线',
  no_model_list: '可达',
  rate_limited: '限流',
  unauthorized: '密钥无效',
  missing_key: '未配置密钥',
  unreachable: '无法连接',
  error: '连接异常',
  invalid: '地址无效',
  unknown: '未检测',
}

function statusLabel(providerId: string | undefined): string {
  const record = statusOf(providerId)
  const label = t(STATUS_LABELS[record.state])
  if (record.state === 'ok' && record.latency_ms) return `${label} ${record.latency_ms}ms`
  return label
}

function statusDetail(providerId: string | undefined): string {
  const record = statusOf(providerId)
  if (record.detail) return record.detail
  if (record.state === 'ok' && record.checked_at) return `${t('最近检测')} ${shortTime(record.checked_at)}`
  return ''
}

function statusHint(providerId: string | undefined): string {
  const record = statusOf(providerId)
  if (record.state === 'unknown') return t('点右侧检测连接')
  return ''
}

function modelName(model: CoreSettingsModel): string {
  return model.display_name || model.model_id || model.id
}

function providerName(id: string | undefined): string {
  const provider = props.providers.find(item => item.id === id)
  return provider?.name || provider?.id || '—'
}

function modelsOfProvider(id: string): CoreSettingsModel[] {
  return props.models.filter(model => model.provider_id === id)
}

function isVision(model: CoreSettingsModel): boolean {
  return model.capability === 'multimodal'
}

function capabilityTitle(model: CoreSettingsModel): string {
  return [
    t('文本'),
    isVision(model) ? t('视觉') : '',
    model.thinking_supported ? t('推理') : '',
  ].filter(Boolean).join(' · ')
}

function apiTypeLabel(apiType?: string): string {
  if (apiType === 'anthropic') return 'Anthropic'
  if (apiType === 'openai') return 'OpenAI compatible'
  return apiType || t('自定义接口')
}

function hostOf(url?: string): string {
  const raw = String(url || '').trim()
  if (!raw) return '—'
  try {
    return new URL(raw).host
  } catch {
    return raw.replace(/^https?:\/\//, '').split('/')[0]
  }
}

function shelfInitial(shelf: ShelfModel): string {
  if (shelf.kind === 'group') return (shelf.title || 'G').slice(0, 1).toUpperCase()
  return (shelf.title || 'P').slice(0, 1).toUpperCase()
}

function formatTokens(value: number | undefined): string {
  const number = Number(value || 0)
  if (!number) return '0'
  if (number >= 1_000_000_000) return `${(number / 1_000_000_000).toFixed(1)}B`
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(number >= 10_000_000 ? 0 : 1)}M`
  if (number >= 1_000) return `${(number / 1_000).toFixed(number >= 10_000 ? 0 : 1)}K`
  return String(Math.round(number))
}

function formatCalls(value: number | undefined): string {
  const number = Number(value || 0)
  if (number >= 10_000) return `${(number / 1000).toFixed(0)}K`
  return String(number)
}

function formatCost(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  if (number === 0) return '$0'
  if (number < 0.01) return `$${number.toFixed(4)}`
  if (number < 10) return `$${number.toFixed(2)}`
  return `$${number.toFixed(1)}`
}

function priceText(model: CoreSettingsModel): string {
  const pricing = model.pricing || {}
  const input = Number(pricing.input_per_1m || 0)
  const output = Number(pricing.output_per_1m || 0)
  if (!input && !output) return t('未设置')
  return `${formatCost(input)} / ${formatCost(output)}`
}

function shortTime(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function sparkPath(modelId: string): string {
  const series = usage.value?.series?.[modelId] || []
  if (!series.length) return 'M0 11 L44 11'
  const max = Math.max(1, ...series)
  const step = 44 / Math.max(1, series.length - 1)
  return series.map((value, index) => {
    const x = (index * step).toFixed(2)
    const y = (12 - (value / max) * 10).toFixed(2)
    return `${index === 0 ? 'M' : 'L'}${x} ${y}`
  }).join(' ')
}

// ── 数据加载 ──────────────────────────────────────────────────────

const rpc = computed<Rpc | null>(() => props.requestRpc || null)

async function loadUsage(): Promise<void> {
  if (!rpc.value) return
  usageLoading.value = true
  try {
    const result = await rpc.value('config.models.usage', { range: range.value })
    usage.value = result as unknown as ModelUsageSummary
    serverTracked.value = true
  } catch {
    // A missing usage backend must not break the catalog itself.
  } finally {
    usageLoading.value = false
  }
}

async function loadStatus(): Promise<void> {
  if (!rpc.value) return
  try {
    const result = await rpc.value('config.providers.status')
    statuses.value = (result.providers as Record<string, ProviderConnectionStatus>) || {}
    statusUpdatedAt.value = String(result.updated_at || '')
  } catch {
    statuses.value = {}
  }
}

async function probeAll(force: boolean): Promise<void> {
  if (!rpc.value || probing.value) return
  probing.value = true
  try {
    const result = await rpc.value('config.providers.probe', { force })
    statuses.value = { ...statuses.value, ...((result.providers as Record<string, ProviderConnectionStatus>) || {}) }
    statusUpdatedAt.value = String(result.updated_at || '')
  } catch {
    // Status is informative; a failed probe leaves the last known state.
  } finally {
    probing.value = false
  }
}

async function probeProvider(providerId: string): Promise<void> {
  if (!rpc.value || probingIds.has(providerId)) return
  probingIds.add(providerId)
  try {
    const result = await rpc.value('config.providers.probe', { provider_ids: [providerId], force: true })
    statuses.value = { ...statuses.value, ...((result.providers as Record<string, ProviderConnectionStatus>) || {}) }
  } catch {
    // Keep the previous state.
  } finally {
    probingIds.delete(providerId)
  }
}

// ── 选择与检查器 ──────────────────────────────────────────────────

function select(next: Selection | null): void {
  if (draft.value) {
    settingsDraft.requestReplace(() => {
      draft.value = null
      draftError.value = ''
      settingsDraft.accept(null)
      selection.value = next
    })
    return
  }
  selection.value = next
  void nextTick(() => {
    if (inspectorEl.value && !prefersReducedMotion()) {
      gsap.fromTo(inspectorEl.value, { x: 24, autoAlpha: 0 }, { x: 0, autoAlpha: 1, duration: 0.22, ease: 'power2.out', clearProps: 'transform' })
    }
  })
}

function openModel(model: CoreSettingsModel): void {
  select({ kind: 'model', id: model.id })
}

function openProvider(providerId: string | undefined): void {
  if (!providerId) return
  select({ kind: 'provider', id: providerId })
}

function openGroup(groupId: string | undefined): void {
  if (!groupId) return
  const group = props.modelGroups.find(item => item.id === groupId)
  if (group) openGroupMembers(group)
}

function closeInspector(): void {
  selection.value = null
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

// ── 编辑器（草稿受设置页离开守卫保护） ───────────────────────────

const draftLabel = computed(() => {
  if (!draft.value) return t('模型与供应商')
  if (draft.value.kind === 'provider') return t('供应商配置')
  if (draft.value.kind === 'model') return t('模型配置')
  return t('分组')
})

const settingsDraft = useSettingsDraft<Draft | null>({
  guard: props.draftGuard,
  section: 'models',
  label: () => draftLabel.value,
  read: () => draft.value,
  restore: (saved) => {
    draft.value = saved
    draftError.value = ''
  },
  save: () => saveDraft(),
  busy: saving,
  error: draftError,
})

const draftKicker = computed(() => {
  if (!draft.value) return ''
  if (draft.value.kind === 'provider') return draft.value.mode === 'create' ? t('新供应商') : t('供应商')
  if (draft.value.kind === 'model') return draft.value.mode === 'create' ? t('新模型') : t('模型')
  return t('分组')
})

const draftTitle = computed(() => {
  if (!draft.value) return ''
  if (draft.value.kind === 'provider') return t(draft.value.mode === 'create' ? '接入供应商' : '编辑连接')
  if (draft.value.kind === 'model') return t(draft.value.mode === 'create' ? '添加模型' : '编辑模型')
  if (draft.value.kind === 'group-create') return t('新建分组')
  return t('管理成员')
})

function openDraft(next: Draft): void {
  settingsDraft.requestReplace(() => {
    draftError.value = ''
    draft.value = next
    settingsDraft.accept(next)
  })
}

function closeDraftNow(): void {
  if (saving.value) return
  draft.value = null
  draftError.value = ''
  settingsDraft.accept(null)
}

function requestCloseDraft(): void {
  if (!draft.value || saving.value) return
  if (!settingsDraft.dirty.value) {
    closeDraftNow()
    return
  }
  settingsDraft.requestReplace(() => closeDraftNow())
}

function requestDraftDismiss(): void {
  if (!draft.value || saving.value) return
  settingsDraft.requestReplace(() => closeDraftNow())
}

function openProviderCreate(presetId?: string): void {
  const preset = presetId ? PROVIDER_PRESETS.find(item => item.id === presetId) : null
  openDraft({
    kind: 'provider',
    mode: 'create',
    presetId: preset?.id || '',
    name: preset?.name || '',
    apiType: preset?.apiType || 'openai',
    baseUrl: preset?.baseUrl || '',
    apiKey: preset?.defaultApiKey || '',
    hasStoredKey: false,
    budget: '',
    extraJson: JSON.stringify({ ...(preset?.extra || {}), ...(preset?.adapterProfile ? { adapter_profile_id: preset.adapterProfile } : {}) }, null, 2),
  })
  showKey.value = Boolean(preset?.defaultApiKey)
}

function openProviderEdit(provider: CoreSettingsProvider): void {
  const extra = { ...(provider.extra || {}) }
  const budget = extra.monthly_budget_usd
  delete extra.monthly_budget_usd
  delete extra.adapter_profile_id
  openDraft({
    kind: 'provider',
    mode: 'update',
    id: provider.id,
    presetId: '',
    name: provider.name || provider.id,
    apiType: provider.api_type || 'openai',
    baseUrl: provider.base_url || '',
    apiKey: '',
    hasStoredKey: Boolean(provider.has_api_key),
    budget: budget === undefined || budget === null ? '' : String(budget),
    extraJson: JSON.stringify(extra, null, 2),
  })
  showKey.value = false
}

function openModelCreate(providerId: string): void {
  openDraft({
    kind: 'model',
    mode: 'create',
    providerId,
    modelId: '',
    displayName: '',
    capability: 'text',
    outputType: 'text',
    enabled: true,
    isDefault: false,
    contextWindow: 128000,
    maxOutputTokens: 16384,
    temperature: 0.7,
    thinkingSupported: false,
    thinkingBudget: 10000,
    priceInput: '',
    priceOutput: '',
    priceCacheRead: '',
    notes: '',
    extraJson: '{}',
  })
}

function openModelEdit(model: CoreSettingsModel): void {
  const pricing = model.pricing || {}
  const extra = { ...(model.extra || {}) }
  delete extra.capability
  openDraft({
    kind: 'model',
    mode: 'update',
    recordId: model.id,
    providerId: model.provider_id || '',
    modelId: model.model_id || '',
    displayName: model.display_name || '',
    capability: model.capability === 'multimodal' ? 'multimodal' : 'text',
    outputType: normalizeOutputType(model.output_type),
    enabled: model.enabled !== false,
    isDefault: model.is_default === true,
    contextWindow: model.context_window ?? 128000,
    maxOutputTokens: model.max_output_tokens ?? 16384,
    temperature: model.temperature ?? 0.7,
    thinkingSupported: model.thinking_supported === true,
    thinkingBudget: model.thinking_budget ?? 10000,
    priceInput: pricing.input_per_1m === undefined ? '' : String(pricing.input_per_1m),
    priceOutput: pricing.output_per_1m === undefined ? '' : String(pricing.output_per_1m),
    priceCacheRead: pricing.cache_read_per_1m === undefined ? '' : String(pricing.cache_read_per_1m),
    notes: model.notes || '',
    extraJson: JSON.stringify(extra, null, 2),
  })
}

function openGroupCreate(): void {
  openDraft({ kind: 'group-create', name: '' })
}

function openGroupMembers(group: CoreSettingsModelGroup): void {
  openDraft({ kind: 'group-members', groupId: group.id, name: group.name, modelIds: [...group.model_ids] })
}

function applyPreset(presetId: string): void {
  if (draft.value?.kind !== 'provider') return
  draft.value.presetId = presetId
  const preset = PROVIDER_PRESETS.find(item => item.id === presetId)
  if (!preset) return
  draft.value.name = preset.name
  draft.value.apiType = preset.apiType
  draft.value.baseUrl = preset.baseUrl
  draft.value.apiKey = preset.defaultApiKey || ''
  draft.value.extraJson = JSON.stringify({ ...(preset.extra || {}), ...(preset.adapterProfile ? { adapter_profile_id: preset.adapterProfile } : {}) }, null, 2)
}

async function openPresetKeyPage(): Promise<void> {
  const url = draftPreset.value?.apiKeyUrl
  if (url) await openExternalUrl(url)
}

function parseJsonObject(value: string): Record<string, unknown> | null {
  const raw = value.trim()
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    return parsed as Record<string, unknown>
  } catch {
    return null
  }
}

function pricingFromDraft(value: string): number | undefined {
  const raw = String(value ?? '').trim()
  if (!raw) return undefined
  const number = Number(raw)
  return Number.isFinite(number) && number >= 0 ? number : undefined
}

async function saveDraft(): Promise<boolean> {
  const current = draft.value
  if (!current || saving.value) return false
  draftError.value = ''
  if (current.kind === 'provider') return saveProviderDraft(current)
  if (current.kind === 'model') return saveModelDraft(current)
  if (current.kind === 'group-create') {
    if (!current.name.trim()) {
      draftError.value = t('请填写分组名称')
      return false
    }
    return persist('create-model-group', { name: current.name.trim() })
  }
  return saveGroupMembers()
}

async function saveProviderDraft(current: Extract<Draft, { kind: 'provider' }>): Promise<boolean> {
  if (!current.name.trim() || !current.baseUrl.trim()) {
    draftError.value = t('名称和接口地址不能为空')
    return false
  }
  const extra = parseJsonObject(current.extraJson)
  if (extra === null) {
    draftError.value = t('适配参数必须是 JSON 对象')
    return false
  }
  const budget = Number(current.budget)
  if (current.budget.trim() && (!Number.isFinite(budget) || budget < 0)) {
    draftError.value = t('每月额度必须是不小于 0 的数字')
    return false
  }
  if (current.budget.trim()) extra.monthly_budget_usd = budget
  else delete extra.monthly_budget_usd

  const payload: CoreSettingsProviderPayload = {
    ...(current.id ? { provider_id: current.id } : {}),
    ...(current.presetId ? { preset_id: current.presetId } : {}),
    name: current.name.trim(),
    api_type: current.apiType,
    base_url: current.baseUrl.trim(),
    extra,
    ...(current.apiKey.trim() ? { api_key: current.apiKey.trim() } : {}),
  }
  const preset = PROVIDER_PRESETS.find(item => item.id === current.presetId)
  if (current.mode === 'create' && preset) {
    if (preset.group === 'free') payload.model_group_name = 'Free'
    payload.models = preset.models.map(model => ({
      provider_id: '',
      model_id: model.modelId,
      display_name: model.displayName,
      context_window: model.contextWindow,
      max_output_tokens: model.maxOutputTokens,
      thinking_supported: model.thinkingSupported,
      thinking_budget: model.thinkingBudget,
      temperature: model.temperature,
      is_default: model.modelId === preset.defaultModelId,
      extra: providerPresetModelExtra(model),
    }))
  }
  const ok = await persist(current.mode === 'create' ? 'create-provider' : 'update-provider', payload as unknown as Record<string, unknown>)
  if (ok) {
    void loadStatus()
    if (current.mode === 'update' && current.id) void probeProvider(current.id)
    else void probeAll(false)
  }
  return ok
}

async function saveModelDraft(current: Extract<Draft, { kind: 'model' }>): Promise<boolean> {
  if (!current.providerId) {
    draftError.value = t('请选择供应商')
    return false
  }
  if (!current.modelId.trim()) {
    draftError.value = t('请填写模型 ID')
    return false
  }
  const extra = parseJsonObject(current.extraJson)
  if (extra === null) {
    draftError.value = t('适配参数必须是 JSON 对象')
    return false
  }
  const pricing: CoreModelPricing = {}
  const input = pricingFromDraft(current.priceInput)
  const output = pricingFromDraft(current.priceOutput)
  const cache = pricingFromDraft(current.priceCacheRead)
  if (input !== undefined) pricing.input_per_1m = input
  if (output !== undefined) pricing.output_per_1m = output
  if (cache !== undefined) pricing.cache_read_per_1m = cache
  const hasPricing = Object.keys(pricing).length > 0
  if (hasPricing) pricing.currency = 'USD'

  const payload: CoreSettingsModelPayload = {
    ...(current.recordId ? { model_record_id: current.recordId } : {}),
    provider_id: current.providerId,
    model_id: current.modelId.trim(),
    display_name: current.displayName.trim(),
    context_window: Number(current.contextWindow) || 0,
    max_output_tokens: Number(current.maxOutputTokens) || 4096,
    temperature: Number(current.temperature) || 0,
    thinking_supported: current.thinkingSupported,
    thinking_budget: Number(current.thinkingBudget) || 0,
    capability: current.capability,
    output_type: current.outputType,
    notes: current.notes,
    enabled: current.enabled,
    is_default: current.enabled ? current.isDefault : false,
    extra,
    ...(hasPricing ? { pricing } : {}),
  }
  const ok = await persist(current.mode === 'create' ? 'create-model' : 'update-model', payload as unknown as Record<string, unknown>)
  if (ok) void loadUsage()
  return ok
}

async function saveGroupMembers(): Promise<boolean> {
  const current = draft.value
  if (!current || current.kind !== 'group-members') return false
  if (!current.name.trim()) {
    draftError.value = t('请填写分组名称')
    return false
  }
  const renamed = current.name.trim() !== (props.modelGroups.find(group => group.id === current.groupId)?.name || '')
  if (renamed) {
    const renamedOk = await persist('update-model-group', { group_id: current.groupId, name: current.name.trim() }, { close: false })
    if (!renamedOk) return false
  }
  return persist('set-model-group-members', { group_id: current.groupId, model_ids: [...new Set(current.modelIds)] })
}

async function persist(
  operation: SettingsCatalogMutation,
  payload: Record<string, unknown>,
  options: { close?: boolean } = {},
): Promise<boolean> {
  if (saving.value) return false
  saving.value = true
  draftError.value = ''
  try {
    if (props.persistCatalog) await props.persistCatalog(operation, payload)
    else (emit as unknown as (event: string, value: Record<string, unknown>) => void)(operation, payload)
    if (options.close !== false) {
      draft.value = null
      settingsDraft.accept(null)
    }
    noticeText.value = ''
    return true
  } catch (cause) {
    draftError.value = cause instanceof Error ? cause.message : String(cause)
    return false
  } finally {
    saving.value = false
  }
}

async function toggleModelGroup(group: CoreSettingsModelGroup): Promise<void> {
  const model = selectedModel.value
  if (!model) return
  const member = group.model_ids.includes(model.id)
  const next = member ? group.model_ids.filter(id => id !== model.id) : [...group.model_ids, model.id]
  const ok = await persist('set-model-group-members', { group_id: group.id, model_ids: next })
  if (!ok && draftError.value) noticeText.value = draftError.value
}

function modelUpdatePayload(model: CoreSettingsModel, enabled: boolean): CoreSettingsModelPayload {
  const pricing = model.pricing && Object.keys(model.pricing).length ? { ...model.pricing } : undefined
  return {
    model_record_id: model.id,
    provider_id: model.provider_id || '',
    provider_name: model.provider_name || '',
    model_id: model.model_id || '',
    display_name: model.display_name || '',
    context_window: model.context_window ?? 0,
    max_output_tokens: model.max_output_tokens ?? 4096,
    temperature: model.temperature ?? 0.2,
    thinking_supported: model.thinking_supported === true,
    thinking_budget: model.thinking_budget ?? 0,
    capability: model.capability || '',
    notes: model.notes || '',
    enabled,
    is_default: enabled ? model.is_default === true : false,
    extra: model.extra || {},
    ...(pricing ? { pricing } : {}),
  }
}

async function toggleModelEnabled(model: CoreSettingsModel, enabled: boolean): Promise<void> {
  if (model.enabled === enabled) return
  const ok = await persist('update-model', modelUpdatePayload(model, enabled) as unknown as Record<string, unknown>)
  if (ok) {
    noticeText.value = enabled ? t('已启用模型') : t('已停用模型')
    void loadUsage()
  } else if (draftError.value) {
    noticeText.value = draftError.value
  }
}

function setFallback(model: CoreSettingsModel): void {
  emit('set-default-model', model.id)
  noticeText.value = t('已设为兜底模型')
}

function requestDeleteModel(model: CoreSettingsModel): void {
  emit('delete-model', model.id)
  closeInspector()
}

function requestDeleteProvider(provider: CoreSettingsProvider): void {
  emit('delete-provider', provider.id)
  closeInspector()
}

function requestDeleteGroup(group: CoreSettingsModelGroup): void {
  emit('delete-model-group', group.id)
  closeInspector()
}

let settingsScrollHost: HTMLElement | null = null

function onDocumentPointerDown(event: PointerEvent): void {
  if (!filtersOpen.value) return
  const target = event.target as Element | null
  if (!target) return
  if (target.closest('.mc-filter-pop') || target.closest('[data-model-filter-toggle]') || target.closest('.ui-select-menu')) {
    return
  }
  filtersOpen.value = false
}

function resetFilters(): void {
  providerFilter.value = 'all'
  groupFilter.value = 'all'
  capabilityFilter.value = 'all'
  statusFilter.value = 'all'
  query.value = ''
  filtersOpen.value = false
}

watch(range, () => { void loadUsage() })

watch(() => props.catalogView, (view) => {
  if (view === 'provider') groupFilter.value = 'all'
})

watch(() => props.providers, () => {
  if (selection.value?.kind === 'provider' && !props.providers.some(provider => provider.id === selection.value!.id)) {
    selection.value = null
  }
  if (selection.value?.kind === 'model' && !props.models.some(model => model.id === selection.value!.id)) {
    selection.value = null
  }
})

let rootObserver: ResizeObserver | null = null
let wallObserver: ResizeObserver | null = null

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown, true)
  if (typeof ResizeObserver !== 'undefined') {
    if (catalogEl.value) {
      rootObserver = new ResizeObserver((entries) => {
        catalogWidth.value = entries[0]?.contentRect.width || 0
        updateOverlayGeometry()
      })
      rootObserver.observe(catalogEl.value)
      catalogWidth.value = catalogEl.value.clientWidth
    }
    if (wallEl.value) {
      wallObserver = new ResizeObserver((entries) => {
        wallWidth.value = entries[0]?.contentRect.width || 0
        updateOverlayGeometry()
      })
      wallObserver.observe(wallEl.value)
      wallWidth.value = wallEl.value.clientWidth
    }
  }
  updateOverlayGeometry()
  settingsScrollHost = (catalogEl.value?.closest('.settings-main') as HTMLElement | null) || null
  settingsScrollHost?.addEventListener('scroll', updateOverlayGeometry, { passive: true })
  window.addEventListener('resize', updateOverlayGeometry, { passive: true })
  void loadUsage()
  void loadStatus().then(() => probeAll(false))
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown, true)
  wallObserver?.disconnect()
  wallObserver = null
  rootObserver?.disconnect()
  rootObserver = null
  settingsScrollHost?.removeEventListener('scroll', updateOverlayGeometry)
  settingsScrollHost = null
  window.removeEventListener('resize', updateOverlayGeometry)
})
</script>

<style scoped src="../styles/core-model-catalog.css"></style>
