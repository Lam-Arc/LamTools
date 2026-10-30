<template>
  <div
    ref="settingsRootEl"
    class="full-area-column full-area-surface" data-ui-id="settings.root"
    :class="{ 'settings-surface--narrow': narrowSurface }"
    :style="settingsThemeStyle"
  >
    <SettingsShell
          :sections="sections"
          :title="t('Sunday 设置')"
          :initial-section="props.section"
          :settings-theme-style="settingsThemeStyle"
          :hide-nav="props.hideNav"
          :active-section="resolvedSection"
          :before-section-change="beforeSectionChange"
          @close="requestCloseSettings"
          @section-change="onSectionChange"
        >
          <template #default="{ activeSection }">
      <section v-if="activeSection === 'general'" class="settings-panel">
        <CoreGeneralEditor :request-rpc="requestRpc || defaultRequestRpc" :platform="commandShellPlatform" />
      </section>

      <section v-if="activeSection === 'models'" class="settings-panel models-panel">
        <header class="settings-title models-title">
          <div class="models-title-copy">
            <h1>{{ t("模型与供应商") }}</h1>
            <p>{{ t("管理模型接入、供应商配置与默认模型选择。") }}</p>
          </div>
          <CoreModelCatalogViewToggle
            :model-value="catalogView"
            @update:model-value="$emit('update:catalogView', $event)"
          />
        </header>

        <div v-if="noticeText" class="settings-notice">{{ noticeText }}</div>

        <div v-if="catalogView === 'group' || providers.length" class="models-workspace settings-surface">
          <div class="models-workspace-body">
          <aside v-if="catalogView === 'provider'" class="provider-rail" :aria-label="t('供应商列表')">
            <div class="provider-rail-head">
              <div class="provider-rail-title">
                <strong>{{ t("供应商") }}</strong>
                <span>{{ providerCount }}</span>
              </div>
            </div>

            <label class="resource-search provider-search">
              <span class="sr-only">{{ t("搜索供应商") }}</span>
              <input v-model.trim="providerQuery" type="search" :placeholder="t('搜索供应商')" />
            </label>

            <div class="provider-picker" role="listbox" :aria-label="t('选择供应商')">
              <button
                v-for="provider in filteredProviders"
                :key="provider.id"
                class="provider-picker-item"
                :class="{ 'is-selected': selectedProvider?.id === provider.id }"
                type="button"
                role="option"
                :aria-selected="selectedProvider?.id === provider.id ? 'true' : 'false'"
                @click="selectProvider(provider.id)"
              >
                <span class="provider-picker-mark" aria-hidden="true">{{ (provider.name || provider.id).slice(0, 1).toUpperCase() }}</span>
                <span class="provider-picker-copy">
                  <strong>{{ provider.name || provider.id }}</strong>
                  <span>{{ modelsForProvider(provider.id).length }}{{ t("个模型") }}</span>
                </span>
                <span class="provider-picker-state" :class="{ 'is-configured': provider.has_api_key }">
                  <span class="provider-picker-state-dot" aria-hidden="true" />
                  <span>{{ provider.has_api_key ? t("已就绪") : t("待配置") }}</span>
                </span>
              </button>
              <div v-if="!filteredProviders.length" class="provider-rail-empty">
                <strong>{{ t("没有匹配的供应商") }}</strong>
                <small>{{ t("换个关键词试试") }}</small>
              </div>
            </div>

            <div class="provider-rail-footer">
              <button class="provider-create-btn" type="button" data-provider-create @click="startProviderCreate">
                <span aria-hidden="true">＋</span>
                <span>{{ t("新增供应商") }}</span>
              </button>
              <div class="provider-rail-links">
                <button v-if="allowEnvironmentImport" class="btn btn--ghost" type="button" @click="$emit('import-environment')">{{ t("从当前环境导入") }}</button>
                <button class="btn btn--ghost" type="button" data-reopen-onboarding @click="$emit('reopen-onboarding')">{{ t("重新显示首次引导") }}</button>
              </div>
            </div>
          </aside>

          <aside v-else class="provider-rail" :aria-label="t('模型组列表')">
            <div class="provider-rail-head">
              <div class="provider-rail-title">
                <strong>{{ t("模型组") }}</strong>
                <span>{{ modelGroups.length }}</span>
              </div>
            </div>
            <label class="resource-search provider-search">
              <span class="sr-only">{{ t("搜索模型组") }}</span>
              <input v-model.trim="groupQuery" type="search" :placeholder="t('搜索模型组')" />
            </label>
            <div class="provider-picker" role="listbox" :aria-label="t('选择模型组')">
              <button
                v-for="group in filteredModelGroups"
                :key="group.id"
                class="provider-picker-item"
                :class="{ 'is-selected': selectedModelGroup?.id === group.id }"
                type="button"
                role="option"
                :aria-selected="selectedModelGroup?.id === group.id ? 'true' : 'false'"
                :data-model-group="group.id"
                @click="selectModelGroup(group.id)"
              >
                <span class="provider-picker-mark" aria-hidden="true">{{ (group.name || group.id).slice(0, 1).toUpperCase() }}</span>
                <span class="provider-picker-copy">
                  <strong>{{ group.name || group.id }}</strong>
                  <span>{{ group.model_ids.length }}{{ t("个模型") }}</span>
                </span>
              </button>
              <div v-if="!filteredModelGroups.length" class="provider-rail-empty">
                <strong>{{ groupQuery ? t("没有匹配的模型组") : t("还没有模型组") }}</strong>
                <small>{{ groupQuery ? t("换个关键词试试") : t("创建分组来整理常用模型") }}</small>
              </div>
            </div>
            <div class="provider-rail-footer">
              <button class="provider-create-btn" type="button" data-model-group-create @click="startModelGroupCreate">
                <span aria-hidden="true">＋</span>
                <span>{{ t("新建模型组") }}</span>
              </button>
            </div>
          </aside>

          <section v-if="catalogView === 'provider' && selectedProvider" class="provider-detail" :aria-label="t('供应商详情')">
            <header class="provider-detail-head">
              <div class="provider-detail-identity">
                <span class="provider-detail-context">{{ t("当前供应商") }}</span>
                <div class="provider-name-line">
                  <h2>{{ selectedProvider.name || selectedProvider.id }}</h2>
                  <span class="provider-type">{{ providerTypeLabel(selectedProvider.api_type) }}</span>
                </div>
                <div class="provider-meta">
                  <span class="provider-url" :title="selectedProvider.base_url || selectedProvider.id">{{ selectedProvider.base_url || selectedProvider.id }}</span>
                  <span class="provider-state" :class="{ 'is-configured': selectedProvider.has_api_key }">
                    <span class="provider-state-dot" aria-hidden="true" />
                    {{ selectedProvider.has_api_key ? t("已就绪 · 已配置密钥") : t("待配置 · 缺少 API Key") }}
                  </span>
                </div>
              </div>
              <div class="provider-head-actions">
                <button class="btn btn--ghost" type="button" :data-provider-edit="selectedProvider.id" @click="startProviderUpdate(selectedProvider)">{{ t("编辑") }}</button>
                <button class="btn btn--ghost btn--danger" type="button" :data-provider-delete="selectedProvider.id" @click="$emit('delete-provider', selectedProvider.id)">{{ t("删除") }}</button>
              </div>
            </header>

            <section class="model-section">
              <header class="model-section-head">
                <div class="model-section-title">
                  <h2>{{ t("模型") }}</h2>
                  <span>{{ selectedProviderModels.length }}{{ t("个模型") }}</span>
                </div>
                <div class="model-section-tools">
                  <label class="resource-search model-search">
                    <span class="sr-only">{{ t("搜索模型") }}</span>
                    <input v-model.trim="modelQuery" type="search" :placeholder="t('搜索模型')" />
                  </label>
                  <button class="btn btn--primary" type="button" data-model-create @click="startSelectedModelCreate">{{ t("＋ 新增模型") }}</button>
                </div>
              </header>
              <div class="model-list">
                <div v-for="model in filteredSelectedProviderModels" :key="model.id" class="model-row" :class="{ 'is-default': model.is_default }">
                  <div class="model-leading">
                    <div class="model-identity">
                      <div class="model-name-line">
                        <strong>{{ model.display_name || model.model_id || model.id }}</strong>
                        <span v-if="model.is_default" class="model-default-badge">{{ t("预设首选") }}</span>
                      </div>
                      <span class="model-meta">
                        <span class="model-id">{{ model.model_id || model.id }}</span>
                      </span>
                    </div>
                  </div>
                  <div class="model-capabilities" :aria-label="t('模型能力')">
                    <span class="model-capability">{{ t("聊天") }}</span>
                    <span v-if="model.thinking_supported" class="model-capability">{{ t("推理") }}</span>
                    <span v-if="model.capability === 'multimodal'" class="model-capability">{{ t("视觉") }}</span>
                    <span v-else-if="model.capability === 'text'" class="model-capability">{{ t("文本") }}</span>
                  </div>
                  <div class="row-actions">
                    <button v-if="!model.is_default" class="btn btn--ghost model-default-btn" type="button" :data-model-default="model.id" @click="$emit('set-default-model', model.id)">{{ t("设为预设首选") }}</button>
                    <button class="btn btn--ghost" type="button" :data-model-edit="model.id" @click="startModelUpdate(model)">{{ t("编辑") }}</button>
                    <button class="btn btn--ghost btn--danger" type="button" :data-model-delete="model.id" @click="$emit('delete-model', model.id)">{{ t("删除") }}</button>
                  </div>
                </div>
                <div v-if="!filteredSelectedProviderModels.length" class="model-empty">
                  <div>
                    <strong>{{ modelQuery ? t("没有匹配的模型") : t("该供应商下还没有模型") }}</strong>
                    <span>{{ modelQuery ? t("换个关键词试试") : t('为 {0} 添加第一个模型', { 0: selectedProvider.name || selectedProvider.id }) }}</span>
                  </div>
                  <button v-if="!modelQuery" class="btn btn--quiet" type="button" @click="startSelectedModelCreate">{{ t("新增模型") }}</button>
                </div>
              </div>
            </section>
          </section>

          <section v-else-if="catalogView === 'group' && selectedModelGroup" class="provider-detail" :aria-label="t('模型组详情')">
            <header class="provider-detail-head">
              <div class="provider-detail-identity">
                <span class="provider-detail-context">{{ t("当前模型组") }}</span>
                <div class="provider-name-line"><h2>{{ selectedModelGroup.name }}</h2></div>
                <div class="provider-meta"><span>{{ selectedGroupModels.length }}{{ t("个模型，可来自多个供应商") }}</span></div>
              </div>
              <div class="provider-head-actions">
                <button class="btn btn--ghost" type="button" :data-model-group-edit="selectedModelGroup.id" @click="startModelGroupUpdate(selectedModelGroup)">{{ t("重命名") }}</button>
                <button class="btn btn--ghost btn--danger" type="button" :data-model-group-delete="selectedModelGroup.id" @click="$emit('delete-model-group', selectedModelGroup.id)">{{ t("删除组") }}</button>
              </div>
            </header>
            <section class="model-section">
              <header class="model-section-head">
                <div class="model-section-title">
                  <h2>{{ t("模型") }}</h2><span>{{ selectedGroupModels.length }}{{ t("个模型") }}</span>
                </div>
                <div class="model-section-tools">
                  <label class="resource-search model-search">
                    <span class="sr-only">{{ t("搜索模型") }}</span>
                    <input v-model.trim="modelQuery" type="search" :placeholder="t('搜索模型')" />
                  </label>
                  <button class="btn btn--quiet" type="button" data-model-group-members @click="startGroupMembersEdit">{{ t("添加已有模型") }}</button>
                  <button class="btn btn--primary" type="button" data-group-model-create @click="startGroupModelCreate">{{ t("＋ 新增模型") }}</button>
                </div>
              </header>
              <div class="model-list">
                <div v-for="model in filteredSelectedGroupModels" :key="model.id" class="model-row" :class="{ 'is-default': model.is_default }">
                  <div class="model-leading">
                    <div class="model-identity">
                      <div class="model-name-line">
                        <strong>{{ model.display_name || model.model_id || model.id }}</strong>
                        <span v-if="model.is_default" class="model-default-badge">{{ t("预设首选") }}</span>
                      </div>
                      <span class="model-meta">{{ modelProviderName(model) }} · {{ model.model_id || model.id }}</span>
                    </div>
                  </div>
                  <div class="row-actions">
                    <button v-if="!model.is_default" class="btn btn--ghost model-default-btn" type="button" @click="$emit('set-default-model', model.id)">{{ t("设为预设首选") }}</button>
                    <button class="btn btn--ghost" type="button" :data-model-edit="model.id" @click="startModelUpdate(model)">{{ t("编辑") }}</button>
                    <button class="btn btn--ghost btn--danger" type="button" :data-model-group-remove="model.id" @click="removeModelFromSelectedGroup(model.id)">{{ t("移出组") }}</button>
                  </div>
                </div>
                <div v-if="!filteredSelectedGroupModels.length" class="model-empty">
                  <div>
                    <strong>{{ modelQuery ? t("没有匹配的模型") : t("该组还没有模型") }}</strong>
                    <span>{{ modelQuery ? t("换个关键词试试") : t("添加现有模型，或创建一个新模型") }}</span>
                  </div>
                </div>
              </div>
            </section>
          </section>

          <section v-else-if="catalogView === 'provider'" class="models-empty-state models-empty-state--main" :aria-label="t('供应商空状态')">
            <div class="models-empty-mark" aria-hidden="true"><span>+</span></div>
            <div class="models-empty-copy">
              <h2>{{ t("还没有供应商") }}</h2>
              <p>{{ t("从左侧添加一个模型供应商，开始使用 Sunday。") }}</p>
            </div>
          </section>
          <section v-else class="models-empty-state models-empty-state--main" :aria-label="t('模型组空状态')">
            <div class="models-empty-mark" aria-hidden="true"><span>+</span></div>
            <div class="models-empty-copy"><h2>{{ t("还没有模型组") }}</h2><p>{{ t("创建一个模型组来整理所有供应商下的模型。") }}</p></div>
            <button class="btn btn--primary" type="button" data-model-group-create @click="startModelGroupCreate">{{ t("新建模型组") }}</button>
          </section>
          </div>
        </div>

        <section v-else class="models-empty-state models-empty-state--full settings-surface" :aria-label="t('供应商空状态')">
          <div class="models-empty-mark" aria-hidden="true"><span>＋</span></div>
          <div class="models-empty-copy">
            <h2>{{ t("还没有供应商") }}</h2>
            <p>{{ t("添加一个 OpenAI Compatible 或其他模型供应商") }}</p>
          </div>
          <button class="btn btn--primary" type="button" data-provider-create @click="startProviderCreate">{{ t("新增供应商") }}</button>
        </section>
      </section>

      <section v-if="activeSection === 'appearance'" class="settings-panel settings-panel--appearance">
        <header class="settings-title">
          <h1>{{ t("界面") }}</h1>
          <p>{{ t("主题和密度只影响当前 Sunday 界面。") }}</p>
        </header>

        <ThemeEditor
          product-name="Sunday"
          :content-description="t('Sunday 工作区')"
          :density="density"
          :density-options="densityOptions"
          :content-width="contentWidth"
          :theme-mode="themeMode"
          :theme-schedule="themeSchedule"
          :effective-theme-mode="effectiveThemeMode"
          :get-stops="getStops"
          :get-angle="getAngle"
          :get-opacity="getOpacity"
          :get-text-color="getTextColor"
          :get-fill-mode="getFillMode"
          :get-glass-level="getGlassLevel"
          :get-image="getImage"
          :get-image-fit="getImageFit"
          :process-icon-color="theme.processIconColor"
          :presets="presets"
          :theme-preview-style="themePreviewStyle"
          :theme-preview-main-style="themePreviewMainStyle"
          :theme-preview-composer-style="themePreviewComposerStyle"
          :theme-preview-control-style="themePreviewControlStyle"
          @reset-theme="$emit('reset-theme')"
          @apply-preset="(preset) => $emit('apply-preset', preset)"
          @update:theme-mode="(mode) => $emit('update:theme-mode', mode)"
          @update:theme-schedule="(schedule) => $emit('update:theme-schedule', schedule)"
          @update:density="(value) => $emit('update:density', value as CoreSettingsDensity)"
          @update:content-width="(value) => $emit('update:content-width', value)"
          @update:stops="(area: ThemeArea, stops: ThemeStop[]) => $emit('update-stops', area, stops)"
          @update:angle="(area: ThemeArea, angle: number) => $emit('update-angle', area, angle)"
          @update:opacity="(area: ThemeArea, opacity: number) => $emit('update-opacity', area, opacity)"
          @update:text-color="(area: ThemeArea, color: string) => $emit('update-text-color', area, color)"
          @update:fill-mode="(area: ThemeArea, mode: ThemeFillMode) => $emit('update-fill-mode', area, mode)"
          @update:glass-level="(area: ThemeArea, level: ThemeGlassPreference) => $emit('update-glass-level', area, level)"
          @update:image="(area: ThemeArea, dataUrl: string) => $emit('update-image', area, dataUrl)"
          @update:image-fit="(area: ThemeArea, fit: ThemeImageFit) => $emit('update-image-fit', area, fit)"
          @update:process-icon-color="(color: string) => $emit('update-process-icon-color', color)"
          @add-stop="(area) => $emit('add-stop', area)"
          @remove-stop="(area, index) => $emit('remove-stop', area, index)"
          @sort-stops="(area) => $emit('sort-stops', area)"
        />

        <!-- user:“可视化主题与布局编辑器”+(界面分区提供进入编辑器的入口，进入后是真实界面的编辑态) -->
        <article class="setting-card studio-entry">
          <div class="studio-entry-copy">
            <!-- user:“编辑布局是实验性功能”+(布局编辑器入口明确标注实验性，避免被当成稳定功能) -->
            <div class="studio-entry-title">
              <strong>{{ t("编辑布局") }}</strong>
              <span class="studio-entry-badge">{{ t("实验性") }}</span>
            </div>
            <p>{{ t("进入可视化编辑器，调整组件的颜色、背景、圆角、字号与层级；修改会立即预览，发布后保存。") }}</p>
          </div>
          <button class="btn btn--primary" type="button" data-open-theme-studio @click="openThemeStudio">{{ t("打开编辑器") }}</button>
        </article>
      </section>

      <section v-if="activeSection === 'loadtools'" class="settings-panel">
        <article v-if="commandShellPlatform === 'windows' || commandShellPlatform === 'linux'" class="setting-card command-shell-card" data-command-shell-card>
          <div class="subhead">
            <span class="muted subhead-title">{{ t("命令行") }}<span class="subhead-sub">{{ t("本机命令工具使用的 shell") }}</span>
            </span>
            <div v-if="commandShellPlatform === 'windows'" class="subhead-actions">
              <button class="btn btn--ghost" type="button" :disabled="commandShellLoading || commandShellSaving" data-command-shell-refresh @click="fetchCommandShellSettings">{{ t("刷新") }}</button>
            </div>
          </div>
          <div v-if="commandShellPlatform === 'windows'" class="dream-row">
            <span class="dream-min-turns">Windows shell</span>
            <UiSelect
              class="command-shell-select"
              :model-value="commandShellPreference"
              :options="commandShellOptions"
              aria-label="Windows shell"
              :disabled="commandShellLoading || commandShellSaving"
              @update:model-value="updateCommandShellPreference"
            />
            <span v-if="commandShellSaving" class="muted" role="status">{{ t("正在保存…") }}</span>
          </div>
          <p v-if="commandShellPlatform === 'windows'" class="hook-meta">{{ t("自动模式按 WSL → Git Bash → PowerShell 的顺序选择可用 shell；手动选择的 shell 不可用时也会按此顺序回退。") }}</p>
          <p v-else class="hook-meta">{{ t("Linux 直接运行本机命令，不提供 Windows shell 选择。") }}</p>
          <p v-if="commandShellError" class="skill-error" role="alert" data-command-shell-error>{{ commandShellError }}</p>
        </article>
        <!-- KeepAlive: switching sections must not destroy editor draft
             state (audit 17 S3 — the SettingsShell :key remount used to
             wipe every unsaved draft). -->
        <CoreLoadToolsEditor :request-rpc="requestRpc || defaultRequestRpc" />
      </section>

      <section v-if="activeSection === 'permissions'" class="settings-panel permissions-panel">
        <header class="settings-title">
          <p>{{ t("控制新会话的默认权限；当前任务可以在输入框中临时调整。") }}</p>
        </header>

        <div class="settings-surface permissions-surface">
          <section class="permission-summary" :aria-label="t('当前默认状态')">
            <div class="permission-summary-copy">
              <span class="permission-section-label">{{ t("当前默认状态") }}</span>
              <h2>{{ t("新会话将从这里开始") }}</h2>
              <p>{{ t("这些设置只作为新会话的起点，不会静默改变已经运行的任务。") }}</p>
            </div>
            <dl class="permission-summary-metrics">
              <div>
                <dt>{{ t("权限审批") }}</dt>
                <dd>{{ permissionPresetLabel }}</dd>
              </div>
              <div>
                <dt>{{ t("文件边界") }}</dt>
                <dd>{{ effectiveAllowAccessOutsideWorkdir ? t("允许工作目录外") : t("工作目录外需确认") }}</dd>
              </div>
            </dl>
          </section>

          <section class="permission-section">
            <div class="permission-section-heading">
              <div>
                <h2>{{ t("新会话默认") }}</h2>
                <p>{{ t("权限审批与输入框保持一致；工具清单由“工具模式”管理。") }}</p>
              </div>
              <span class="permission-section-hint">{{ t("当前会话可临时切换") }}</span>
            </div>

            <div class="permission-setting-group">
              <div class="permission-setting-copy">
                <strong>{{ t("权限审批") }}</strong>
                <span>{{ t("决定工具执行前是否需要你确认。") }}</span>
              </div>
              <div class="permission-choice-grid permission-choice-grid--approval" role="group" :aria-label="t('权限审批')">
                <button
                  v-for="option in permissionPresetOptions"
                  :key="option.id"
                  type="button"
                  class="permission-choice"
                  :class="{ 'is-selected': permissionPreset === option.id }"
                  :aria-label="t('选择') + option.label"
                  :aria-pressed="permissionPreset === option.id ? 'true' : 'false'"
                  :data-default-permission-preset="option.id"
                  @click="selectPermissionPreset(option.id)"
                >
                  <span class="permission-choice-state" aria-hidden="true">
                    <span v-if="permissionPreset === option.id">✓</span>
                  </span>
                  <span class="permission-choice-copy">
                    <strong>{{ option.label }}</strong>
                    <small>{{ option.description }}</small>
                  </span>
                </button>
              </div>
            </div>

          </section>

          <section class="permission-section permission-boundary-section">
            <div class="permission-section-heading">
              <div>
                <h2>{{ t("安全边界") }}</h2>
                <p>{{ t("控制文件操作的默认范围；更高风险的规则仍由 Sunday 强制执行。") }}</p>
              </div>
            </div>

            <div class="permission-boundary-row">
              <div class="permission-setting-copy">
                <strong>{{ t("工作目录外访问") }}</strong>
                <span>{{ permissionPreset === 'full_access' ? t("完全访问模式会临时允许访问工作目录之外的路径。") : allowAccessOutsideWorkdir ? t("允许读写工作目录之外的路径。") : t("工作目录外的读写与命令行访问会先征求你的确认，批准后本次执行。") }}</span>
              </div>
              <!-- user:“把功能相近或者实际相似的样式和组件，统一成一套”+(权限开关改用统一开关，
                   不再自带一套轨道标记；文案作为行内标签，整行可点) -->
              <SundaySwitch
                class="permission-switch"
                data-allow-outside-workdir
                :class="{ 'is-on': effectiveAllowAccessOutsideWorkdir }"
                :model-value="effectiveAllowAccessOutsideWorkdir"
                :disabled="permissionPreset === 'full_access'"
                :label="t('允许访问工作目录以外')"
                size="sm"
                @update:model-value="toggleAllowOutsideWorkdir"
              >
                {{ permissionPreset === 'full_access' ? t("完全访问已包含") : allowAccessOutsideWorkdir ? t("已允许") : t("需确认") }}
              </SundaySwitch>
            </div>

            <ul class="permission-safety-list">
              <li><span class="permission-safety-dot" aria-hidden="true" />{{ t("敏感路径（如 .env、SSH 凭据）写入和编辑仍会阻断。") }}</li>
              <li><span class="permission-safety-dot" aria-hidden="true" />{{ t("3 级操作在询问和自动模式下均需确认；完全访问自动放行到 3 级。") }}</li>
              <li><span class="permission-safety-dot" aria-hidden="true" />{{ t("插件与 MCP 的 hard block 不能从此页解除。") }}</li>
            </ul>
          </section>

          <OperationTrustSettings :request-rpc="requestRpc || defaultRequestRpc" />
          <section class="permission-session-note" :aria-label="t('当前会话说明')">
            <span class="permission-session-note-mark" aria-hidden="true">i</span>
            <div>
              <strong>{{ t("当前会话") }}</strong>
              <p>{{ t("输入框里的“询问 / 自动 / 完全访问”是当前会话的实时状态；切换后仅放行处于对应免问线以内的待审批操作。") }}</p>
            </div>
          </section>

          <details class="permission-related-settings">
            <summary>
              <span>
                <strong>{{ t("相关设置") }}</strong>
                <small>{{ t("按具体操作等级判断，工具模式与扩展声明分别管理") }}</small>
              </span>
            </summary>
            <div class="permission-related-list">
              <div>
                <strong>{{ t("工具模式") }}</strong>
                <span>{{ t("控制模型能看到哪些工具，以及工具在思索 / 执行模式下的暴露方式。") }}</span>
              </div>
              <div>
                <strong>{{ t("插件与 MCP") }}</strong>
                <span>{{ t("扩展自身的审批等级与 hard block 由各自的管理入口负责。") }}</span>
              </div>
              <div>
                <!-- user:“不一棒子按工具类型打死了”+(说明当前按具体操作等级限制能力)。 -->
                <strong>{{ t("操作能力上限") }}</strong>
                <span>{{ t("按本次操作的等级判断：只读允许 1 级，有限编辑允许到 2 级，完全编辑允许到 3 级。") }}</span>
              </div>
            </div>
          </details>
        </div>
      </section>

      <MobileControlPanel
        v-if="activeSection === 'mobile-control'"
        :account-status="remoteAccountStatus"
        :account-identity="remoteAccountIdentity"
        :account-loading="remoteAccountLoading"
        :account-devices="remoteAccountDevices"
        :status="remoteGatewayStatus"
        :pairing="remotePairing"
        :loading="remoteGatewayLoading"
        :error="remoteGatewayError"
        :available="remoteGatewayAvailable"
        @gateway-start="$emit('remote-gateway-start')"
        @gateway-stop="$emit('remote-gateway-stop')"
        @pairing-create="$emit('remote-pairing-create')"
        @revoke="(deviceId) => $emit('remote-device-revoke', deviceId)"
        @account-submit="(payload) => $emit('remote-account-submit', payload)"
        @account-logout="$emit('remote-account-logout')"
      />

      <section v-if="activeSection === 'agents'" class="settings-panel">
        <header class="settings-title">
          <h1>{{ t("上下文") }}</h1>
          <p>{{ t("全局上下文。注入顺序：全局 AGENTS.md（优先级 5）→ 项目 AGENTS.md（10）；load_context 的 addition/except 全局叠加到每个工作区。") }}</p>
        </header>
        <div class="settings-surface settings-surface--stack">
        <article class="setting-card">
          <div class="subhead">
            <span class="muted subhead-title">{{ t("全局约束") }}<span v-if="commandShellPlatform === 'mobile'" class="subhead-sub">{{ t("AGENTS.md · 移动端全局规则") }}</span>
              <span v-else class="subhead-sub">AGENTS.md · .lam/core/config/</span>
            </span>
            <div class="subhead-actions">
              <button class="btn btn--ghost" type="button" :disabled="agentsLoading || agentsSaving" @click="agentsSettingsDraft.requestReplace(() => void fetchGlobalAgentsMd())">{{ t("刷新") }}</button>
              <button class="btn btn--ghost" type="button" :disabled="agentsLoading || agentsSaving" @click="saveGlobalAgentsMd">{{ t("保存") }}</button>
            </div>
          </div>
          <textarea
            v-model="agentsDraft"
            class="guide-editor"
            rows="10"
            spellcheck="false"
            :placeholder="agentsLoading ? t('加载中…') : t('# 全局约束\n对所有项目生效的指令。项目级 AGENTS.md 会在此基础上叠加…')"
            :disabled="agentsLoading || agentsSaving"
          />
          <p v-if="agentsError" class="skill-error" role="alert">{{ agentsError }}</p>
          <p v-if="commandShellPlatform === 'mobile'" class="hook-meta">{{ t("保存在此设备的应用私有 SQLite 配置中。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。") }}</p>
          <p v-else class="hook-meta">{{ t("保存到") }}<code>.lam/core/config/AGENTS.md</code>{{ t("（统一配置目录）。项目级规则请在「项目设置 → 项目」内编辑，两者会相加注入系统提示词。") }}</p>
        </article>

        <article class="setting-card">
          <div class="subhead">
            <span class="muted subhead-title">{{ t("全局上下文加载") }}<span v-if="commandShellPlatform === 'mobile'" class="subhead-sub">{{ t("load_context.jsonc · 移动端全局加载规则") }}</span>
              <span v-else class="subhead-sub">load_context.jsonc · .lam/core/config/</span>
            </span>
            <div class="subhead-actions">
              <button class="btn btn--ghost" type="button" :disabled="contextLoading || contextSaving" @click="contextSettingsDraft.requestReplace(() => void fetchLoadContext())">{{ t("刷新") }}</button>
              <button class="btn btn--ghost" type="button" :disabled="contextLoading || contextSaving" @click="saveLoadContext">{{ t("保存") }}</button>
            </div>
          </div>

          <div class="lc-block">
            <div class="lc-label">{{ t("追加加载的文件（addition）") }}</div>
            <div v-for="(item, index) in contextAdditions" :key="index" class="lc-row">
              <input v-model="item.name" class="lc-input lc-name" spellcheck="false" :placeholder="t('文件名（如 TEAM_RULES.md）')" :disabled="contextLoading || contextSaving" />
              <input v-model.number="item.priority" type="number" class="lc-input lc-priority" :title="t('注入优先级（越小越靠前）')" :disabled="contextLoading || contextSaving" />
              <UiSelect
                :model-value="item.kind"
                :options="lcKindOptions"
                class="lc-kind"
                :disabled="contextLoading || contextSaving"
                :aria-label="t('加载类型')"
                @update:model-value="item.kind = $event"
              />
              <button class="btn btn--ghost btn--danger" type="button" :disabled="contextSaving" @click="contextAdditions.splice(index, 1)">{{ t("移除") }}</button>
            </div>
            <button class="btn btn--quiet" type="button" :disabled="contextLoading || contextSaving" @click="contextAdditions.push({ name: '', priority: 50, kind: 'system' })">{{ t("＋ 追加文件") }}</button>
          </div>

          <div class="lc-block">
            <div class="lc-label">{{ t("排除的默认上下文文件（except）") }}</div>
            <div class="lc-chips">
              <span v-for="(name, index) in contextExcept" :key="name" class="lc-chip">
                {{ name }}
                <button type="button" class="lc-chip-x" :disabled="contextSaving" @click="contextExcept.splice(index, 1)">
                  <X :size="10" :stroke-width="2.2" aria-hidden="true" />
                </button>
              </span>
            </div>
            <div class="lc-row">
              <input
                v-model="contextExceptDraft"
                class="lc-input lc-name"
                spellcheck="false"
                :placeholder="t('如 AGENTS.md / CONTEXT.md')"
                :disabled="contextLoading || contextSaving"
                @keydown.enter.prevent="addContextExcept"
              />
              <button class="btn btn--quiet" type="button" :disabled="contextLoading || contextSaving || !contextExceptDraft.trim()" @click="addContextExcept">{{ t("添加") }}</button>
            </div>
          </div>

          <p v-if="contextError" class="skill-error" role="alert">{{ contextError }}</p>
          <p v-if="commandShellPlatform === 'mobile'" class="hook-meta">{{ t("保存在此设备的应用私有 SQLite 配置中，全局规则叠加到本机工作区。") }}</p>
          <p v-else class="hook-meta">{{ t("保存到") }}<code>.lam/core/config/load_context.jsonc</code>{{ t("，全局叠加到每个工作区（工作区自己的 load_context.jsonc 在其上叠加）。CLI：") }}<code>core load-context get/set</code>。</p>
        </article>

        <article class="setting-card" data-context-compaction-card>
          <div class="subhead">
            <span class="muted subhead-title">{{ t("上下文压缩") }}<span class="subhead-sub">{{ t("保留最近的 Step") }}</span>
            </span>
            <div class="subhead-actions">
              <button
                class="btn btn--ghost"
                type="button"
                data-context-compaction-refresh
                :disabled="contextCompactionLoading || contextCompactionSaving"
                @click="compactionSettingsDraft.requestReplace(() => void fetchContextCompactionSettings())"
              >{{ t("刷新") }}</button>
            </div>
          </div>
          <div class="dream-row">
            <label class="dream-min-turns" for="context-compaction-retained-steps-input">{{ t("压缩保留最近 Step 数") }}</label>
            <input
              id="context-compaction-retained-steps-input"
              v-model.number="contextCompactionRetainedSteps"
              data-context-compaction-retained-steps
              type="number"
              class="lc-input lc-priority"
              min="0"
              max="100"
              step="1"
              :disabled="contextCompactionLoading || contextCompactionSaving"
            />
            <button
              class="btn btn--quiet"
              type="button"
              data-context-compaction-save
              :disabled="contextCompactionLoading || contextCompactionSaving"
              @click="saveContextCompactionSettings"
            >{{ t("保存") }}</button>
          </div>
          <p v-if="contextCompactionError" class="skill-error" role="alert">{{ contextCompactionError }}</p>
          <p class="hook-meta">{{ t("一个 Step 是一次模型响应及其后续工具结果；默认保留 0 个 Step，历史会全部汇总；随后程序会将最新 20 条用户指令原文追加为编号的“Recent user messages”段落。令牌预算不足时较早条目会静默丢弃。") }}</p>
        </article>
        </div>
      </section>

      <section v-if="activeSection === 'subagent'" class="settings-panel">
        <CoreSubAgentEditor :request-rpc="requestRpc || defaultRequestRpc" :models="models" />
      </section>

      <section v-if="activeSection === 'about'" class="settings-panel">
        <header class="settings-title">
          <h1>{{ t("关于与更新") }}</h1>
          <p>{{ t("当前版本与软件更新（优先读取官网更新清单，官网不可达时回退 GitHub Releases）。") }}</p>
        </header>
        <div class="settings-surface settings-surface--stack">
        <article class="setting-card">
          <h3>{{ t("版本信息") }}</h3>
          <div class="about-version-row">
            <span>{{ t("当前版本") }}<strong data-current-version>{{ updateCurrentVersion }}</strong></span>
            <button class="btn btn--quiet" type="button" data-check-updates :disabled="updateStatus === 'checking'" @click="checkForUpdates()">
              {{ updateStatus === 'checking' ? t("正在检查…") : t("检查更新") }}
            </button>
          </div>
          <p v-if="updateStatus === 'up_to_date' && updateNoInstallerForPlatform" class="about-status" data-update-no-installer>{{ t("已发布 v") }}{{ updateLatestVersion }}{{ t("，但没有适用于本平台的安装包（可到发布页查看）") }}</p>
          <p v-else-if="updateStatus === 'up_to_date'" class="about-status" data-update-up-to-date>{{ t("已是最新版本（v") }}{{ updateLatestVersion }}<template v-if="updateSourceLabel">{{ t("· 来源：") }}{{ updateSourceLabel }}</template>）
          </p>
          <p v-else-if="updateStatus === 'check_failed'" class="about-status error" data-update-error>{{ t("检查失败：") }}{{ updateError }}{{ t("（检查网络后重试）") }}</p>
        </article>
        <article v-if="updateStatus === 'update_available'" class="setting-card" data-update-available>
          <h3>{{ t("发现新版本 v") }}{{ updateLatestVersion }}<span v-if="updateSourceLabel" class="muted">{{ t("· 来源：") }}{{ updateSourceLabel }}</span></h3>
          <p v-if="updateReleaseNotes" class="about-notes">{{ updateReleaseNotes }}</p>
          <div class="about-actions">
            <!-- 清单带 sha256 时由宿主下载并校验，再交给平台安装器；没有摘要就退回浏览器下载页。 -->
            <button
              v-if="updateInstallSupported"
              class="btn btn--primary"
              type="button"
              data-download-installer
              :disabled="updateInstallState === 'downloading' || updateInstallState === 'installing'"
              @click="downloadInstaller()"
            >{{ updateInstallState === 'downloading' ? (updateInstallProgressLabel || t("正在下载…")) : updateInstallState === 'downloaded' ? t("重新下载") : t("下载安装包") }}</button>
            <button
              v-if="updateInstallSupported && updateInstallState === 'downloaded'"
              class="btn btn--primary"
              type="button"
              data-run-installer
              @click="runInstaller()"
            >{{ t("立即安装") }}</button>
            <button
              v-else-if="!updateInstallSupported"
              class="btn btn--primary"
              type="button"
              data-download-update
              @click="downloadUpdate()"
            >{{ t("下载安装包") }}</button>
            <button class="btn btn--quiet" type="button" data-open-release-page @click="openUpdateReleasePage">{{ t("查看发布说明") }}</button>
          </div>
          <p v-if="updateInstallError" class="about-status error" data-install-error>{{ updateInstallError }}</p>
          <p v-else-if="updateInstallMessage" class="about-status" data-install-status>{{ updateInstallMessage }}</p>
          <p v-if="updateInstallState === 'downloading'" class="about-status" data-install-progress>
            {{ updateInstallProgressLabel || t("正在下载…") }}
          </p>
          <p v-if="updateInstallSupported" class="muted">
            {{ updateInstallHint || t("下载完成后点击「立即安装」。") }}<template v-if="updatePackageSizeLabel">{{ t("安装包约") }}{{ updatePackageSizeLabel }}。</template>
          </p>
          <p v-else class="muted">{{ t("下载完成后请先退出 Sunday，再运行安装包完成升级。") }}</p>
        </article>
        <article class="setting-card">
          <h3>{{ t("自动检查") }}</h3>
          <div class="dream-row">
            <div class="dream-toggle">
          <button
            type="button"
            class="toggle-btn"
            data-update-auto-check
            :class="{ 'is-on': updateAutoCheck }"
            :aria-label="t('启动时自动检查更新')"
            :aria-pressed="updateAutoCheck ? 'true' : 'false'"
            @click="toggleUpdateAutoCheck"
          >
            <ToggleRight v-if="updateAutoCheck" :size="16" :stroke-width="1.8" aria-hidden="true" />
            <ToggleLeft v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
          </button>
              <span class="dream-toggle-label">{{ t("启动时自动检查更新") }}</span>
            </div>
            <span class="muted">{{ t("发现新版本时会在顶部显示提示条") }}</span>
          </div>
        </article>
        </div>
      </section>
    </template>
  </SettingsShell>

      <!-- 提供方 / 模型编辑表单的浮层：就在设置的版面内联呈现（整版界面里
           没有更大的遮罩层，浮层只盖住这一栏内容）。 -->
      <div v-if="providerEditor || modelEditor || modelGroupEditor || groupMembersEditor" ref="editorOverlayEl" class="editor-overlay">
          <div ref="editorPopoverEl" class="editor-popover" :class="{ 'editor-popover--model': Boolean(modelEditor) }">
            <fieldset class="settings-editor-fields" :disabled="catalogSaving">
            <!-- Validation errors must render INSIDE the popover — the outer
                 noticeText sits behind the overlay's dim/blur and was
                 invisible to the user (audit 17 S3). -->
            <p v-if="editorError" class="skill-error editor-error" role="alert">{{ editorError }}</p>
            <form v-if="modelGroupEditor" data-model-group-form class="config-form" @submit.prevent="submitModelGroup">
              <div class="editor-popover-head field-wide">
                <div>
                  <span class="editor-overline">{{ t("模型组") }}</span>
                  <h3>{{ modelGroupEditor.mode === 'create' ? t("新建模型组") : t("重命名模型组") }}</h3>
                  <p>{{ t("模型可同时存在于多个组；删除组不会删除模型。") }}</p>
                </div>
                <button type="button" class="editor-popover-close" @click="requestCloseEditors">
                  <X :size="14" :stroke-width="1.8" aria-hidden="true" />
                </button>
              </div>
              <label class="field field-wide">{{ t("名称") }}<input v-model.trim="modelGroupEditor.name" data-model-group-name required maxlength="80" :placeholder="t('例如：Free')" />
              </label>
              <div class="editor-actions field-wide">
                <button type="button" class="btn btn--quiet" @click="requestCloseEditors">{{ t("取消") }}</button>
                <button class="btn btn--primary" type="submit">{{ t("保存") }}</button>
              </div>
            </form>

            <form v-else-if="groupMembersEditor" data-model-group-members-form class="config-form" @submit.prevent="submitGroupMembers">
              <div class="editor-popover-head field-wide">
                <div>
                  <span class="editor-overline">{{ t("模型组成员") }}</span>
                  <h3>{{ t("添加已有模型") }}</h3>
                  <p>{{ t("选择要放入") }}{{ selectedModelGroup?.name || t("当前组") }}{{ t("的模型。") }}</p>
                </div>
                <button type="button" class="editor-popover-close" @click="requestCloseEditors">
                  <X :size="14" :stroke-width="1.8" aria-hidden="true" />
                </button>
              </div>
              <div class="group-member-list field-wide">
                <label v-for="model in models" :key="model.id" class="group-member-option">
                  <input v-model="groupMembersEditor.model_ids" type="checkbox" :value="model.id" />
                  <span><strong>{{ model.display_name || model.model_id || model.id }}</strong><small>{{ modelProviderName(model) }}</small></span>
                </label>
                <span v-if="!models.length" class="muted">{{ t("暂无可添加的模型") }}</span>
              </div>
              <div class="editor-actions field-wide">
                <button type="button" class="btn btn--quiet" @click="requestCloseEditors">{{ t("取消") }}</button>
                <button class="btn btn--primary" type="submit">{{ t("保存成员") }}</button>
              </div>
            </form>

            <!-- Provider editor -->
            <form v-else-if="providerEditor" :data-provider-form="providerEditor.mode" class="config-form" @submit.prevent="submitProvider">
              <div class="editor-popover-head field-wide">
                <div>
                  <span class="editor-overline">{{ t("供应商配置") }}</span>
                  <h3>{{ providerEditor.mode === 'create' ? t("新增供应商") : t("编辑供应商") }}</h3>
                  <p>{{ providerEditor.mode === 'create' ? t("连接一个可用的模型服务。") : t("更新连接信息，已有密钥不会被覆盖。") }}</p>
                </div>
                <button type="button" class="editor-popover-close" @click="requestCloseEditors">
                  <X :size="14" :stroke-width="1.8" aria-hidden="true" />
                </button>
              </div>
              <section v-if="providerEditor.mode === 'create'" class="editor-section field-wide">
                <div class="editor-section-heading">
                  <strong>{{ t("快速开始") }}</strong>
                  <span>{{ t("使用官方模板自动填充连接信息和模型。") }}</span>
                </div>
                <label class="field">{{ t("官方模板") }}<UiSelect
                    :model-value="providerEditor.preset_id"
                    :options="providerPresetOptions"
                    data-provider-preset
                    :placeholder="t('自定义')"
                    :aria-label="t('官方模板')"
                    @update:model-value="onProviderPresetChange"
                  />
                </label>
                <div v-if="providerEditor.preset_id" class="preset-summary">
                  <strong>{{ providerEditor.name }}</strong>
                  <span>{{ providerEditor.base_url }}{{ t("· 将自动添加模板内模型") }}</span>
                  <button
                    v-if="selectedProviderPreset?.apiKeyUrl"
                    class="btn btn--ghost"
                    type="button"
                    data-provider-api-key-link
                    @click="openProviderApiKeyPage"
                  >{{ t("点此申请 API key") }}</button>
                </div>
              </section>

              <section class="editor-section editor-section--grid field-wide">
                <div class="editor-section-heading field-wide">
                  <strong>{{ t("连接信息") }}</strong>
                  <span>{{ t("这些信息用于连接模型服务。") }}</span>
                </div>
                <label v-if="providerEditor.mode === 'update' || !providerEditor.preset_id" class="field">{{ t("名称") }}<input v-model.trim="providerEditor.name" data-provider-name required />
                </label>
                <label v-if="providerEditor.mode === 'update' || !providerEditor.preset_id || selectedProviderPreset?.baseUrlEditable" class="field">{{ t("服务地址") }}<input v-model.trim="providerEditor.base_url" data-provider-base-url type="url" required />
                </label>
                <label class="field field-wide">API Key
                  <input
                    v-model="providerEditor.api_key"
                    data-provider-api-key
                    type="password"
                    autocomplete="new-password"
                    :required="providerEditor.mode === 'create'"
                    :placeholder="providerEditor.mode === 'update' ? t('留空以保留现有密钥') : ''"
                  />
                </label>
              </section>

              <details class="settings-advanced editor-section field-wide">
                <summary>
                  <span>
                    <strong>{{ t("高级设置") }}</strong>
                    <small>{{ t("接口类型与适配参数") }}</small>
                  </span>
                </summary>
                <div class="advanced-fields">
                  <label class="field">{{ t("接口类型") }}<UiSelect
                      :model-value="providerEditor.api_type"
                      :options="apiTypeOptions"
                      data-provider-api-type
                      direction="up"
                      :aria-label="t('接口类型')"
                      @update:model-value="providerEditor!.api_type = $event"
                    />
                  </label>
                  <label class="field field-wide">{{ t("高级适配 JSON") }}<textarea v-model="providerEditor.extra_json" rows="5" spellcheck="false" placeholder="{}"></textarea>
                  </label>
                </div>
              </details>
              <div class="editor-actions field-wide">
                <button type="button" class="btn btn--quiet" @click="requestCloseEditors">{{ t("取消") }}</button>
                <button class="btn btn--primary" type="submit">{{ providerEditor.mode === 'create' ? t("添加供应商") : t("保存供应商") }}</button>
              </div>
            </form>

            <!-- Model editor -->
            <form v-else-if="modelEditor" :data-model-form="modelEditor.mode" class="config-form model-editor-form" @submit.prevent="submitModel">
              <div class="editor-popover-head field-wide">
                <div>
                  <span class="editor-overline">{{ t("模型配置") }}</span>
                  <h3>{{ modelEditor.mode === 'create' ? t("新增模型") : t("编辑模型") }}</h3>
                  <p>{{ modelEditor.mode === 'create' ? t("为供应商添加一个可调用的模型。") : t("更新模型标识、能力和运行参数。") }}</p>
                </div>
                <button type="button" class="editor-popover-close" @click="requestCloseEditors">
                  <X :size="14" :stroke-width="1.8" aria-hidden="true" />
                </button>
              </div>
              <section class="editor-section model-editor-basics field-wide">
                <div class="model-editor-provider">
                  <span>{{ modelEditor.origin_group_id ? t("供应商") : t("添加到") }}</span>
                  <UiSelect
                    :model-value="modelEditor.provider_id"
                    :options="modelEditor.origin_group_id ? groupModelProviderOptions : providerOptions"
                    data-model-provider-id
                    :aria-label="t('供应商')"
                    @update:model-value="onModelProviderChange"
                  />
                </div>
                <template v-if="modelEditor.origin_group_id">
                  <label class="field field-wide">{{ t("API 基础 URL") }}<input v-model.trim="modelEditor.base_url" data-model-base-url type="url" required placeholder="https://api.example.com/v1" />
                    <small v-if="modelEditor.provider_mode === 'existing'">{{ t("必须与所选供应商的 API 基础 URL 一致。") }}</small>
                  </label>
                  <div v-if="modelEditor.provider_mode === 'new'" class="model-editor-secondary field-wide">
                    <label class="field">{{ t("供应商名称") }}<input v-model.trim="modelEditor.new_provider_name" data-model-new-provider-name required :placeholder="t('例如：我的供应商')" />
                    </label>
                    <label class="field">{{ t("接口类型") }}<UiSelect
                        :model-value="modelEditor.new_provider_api_type ?? 'openai'"
                        :options="apiTypeOptions"
                        data-model-new-provider-api-type
                        @update:model-value="modelEditor!.new_provider_api_type = $event"
                      />
                    </label>
                    <label class="field field-wide">API Key
                      <input v-model="modelEditor.new_provider_api_key" data-model-new-provider-api-key type="password" autocomplete="new-password" required />
                    </label>
                  </div>
                </template>
                <label class="field model-editor-id">{{ t("模型 ID") }}<input v-model.trim="modelEditor.model_id" data-model-id required :placeholder="t('例如 deepseek-v4-flash')" />
                  <small>{{ t("向供应商 API 发送的模型标识。") }}</small>
                </label>
                <div class="model-editor-secondary">
                  <label class="field">{{ t("显示名称") }}<input v-model.trim="modelEditor.display_name" data-model-display-name :placeholder="t('选填，留空时使用模型 ID')" />
                  </label>
                  <label class="field">{{ t("备注") }}<textarea v-model.trim="modelEditor.notes" rows="2" spellcheck="false" :placeholder="t('选填，如限速、用途、注意事项等')"></textarea>
                  </label>
                </div>
              </section>
              <section class="editor-section model-editor-capabilities field-wide">
                <div class="editor-section-heading">
                  <strong>{{ t("能力") }}</strong>
                  <span>{{ t("决定模型是否接收图片，以及是否启用推理参数。") }}</span>
                </div>
                <div class="model-editor-capability-controls">
                  <label class="field">{{ t("能力分类") }}<UiSelect
                      :model-value="modelEditor.capability ?? ''"
                      :options="capabilityOptions"
                      direction="up"
                      :aria-label="t('能力分类')"
                      @update:model-value="modelEditor!.capability = $event ?? ''"
                    />
                  </label>
                  <div class="model-reasoning-control">
                    <div>
                      <strong>{{ t("支持推理") }}</strong>
                      <span>{{ t("启用推理预算") }}</span>
                    </div>
                    <button
                      type="button"
                      class="toggle-btn"
                      :class="{ 'is-on': modelEditor.thinking_supported }"
                      :aria-label="t('支持推理')"
                      :aria-pressed="modelEditor.thinking_supported ? 'true' : 'false'"
                      @click="modelEditor.thinking_supported = !modelEditor.thinking_supported"
                    >
                      <ToggleRight v-if="modelEditor.thinking_supported" :size="18" :stroke-width="1.8" aria-hidden="true" />
                      <ToggleLeft v-else :size="18" :stroke-width="1.8" aria-hidden="true" />
                    </button>
                  </div>
                </div>
              </section>
              <details class="settings-advanced model-editor-runtime field-wide">
                <summary>
                  <span>
                    <strong>{{ t("运行与适配") }}</strong>
                    <small>{{ t("上下文、输出、Temperature 与高级适配") }}</small>
                  </span>
                </summary>
                <div class="advanced-fields model-advanced-fields">
                  <label class="field">{{ t("上下文窗口") }}<input v-model.number="modelEditor.context_window" type="number" min="1" />
                  </label>
                  <label class="field">{{ t("最大输出") }}<input v-model.number="modelEditor.max_output_tokens" type="number" min="1" />
                  </label>
                  <label class="field">Temperature
                    <input v-model.number="modelEditor.temperature" type="number" min="0" max="2" step="0.1" />
                  </label>
                  <label class="field">{{ t("推理预算") }}<input v-model.number="modelEditor.thinking_budget" type="number" min="0" />
                  </label>
                  <label class="field field-wide">{{ t("高级适配 JSON") }}<textarea v-model="modelEditor.extra_json" rows="5" spellcheck="false" placeholder="{}"></textarea>
                  </label>
                </div>
              </details>
              <div class="editor-actions field-wide">
                <button type="button" class="btn btn--quiet" @click="requestCloseEditors">{{ t("取消") }}</button>
                <button class="btn btn--primary" type="submit">{{ modelEditor.mode === 'create' ? t("添加模型") : t("保存模型") }}</button>
              </div>
            </form>
            </fieldset>
          </div>
        </div>
      <!-- 必须留在根节点内部：整版界面把 full-area-view / full-area-wide 挂在
           这个组件的根元素上，多出一个并列根节点 Vue 会静默丢弃这些属性，
           设置页就再也铺不满主卡、也滚不动（0.3.11 起的回归）。 -->
      <SettingsDraftDialog :guard="draftGuard" />
  </div>
  </template>

<script setup lang="ts">
import OperationTrustSettings from './OperationTrustSettings.vue'
import SundaySwitch from '@/components/SundaySwitch.vue'
import { useSplitKeyboardScope } from '@/split/keyboardScope'
const splitKeyboardActive = useSplitKeyboardScope()

import { t } from '@/i18n/index.ts'

import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useOutsidePointerDismiss } from '@/composables/useOutsidePointerDismiss.ts'
import { useThemeStudio } from '@/composables/useThemeStudio.ts'
import { createSettingsDraftGuard, useSettingsDraft } from '@/composables/useSettingsDraftGuard.ts'
import { ToggleLeft, ToggleRight, X } from 'lucide-vue-next'
import { PROVIDER_PRESETS, PROVIDER_PRESET_GROUP_LABELS, providerPresetModelExtra } from '@/data/provider-presets.ts'
import { THEME_PRESETS } from '@/data/theme-presets.ts'
import {
  CORE_PERMISSION_PRESET_DESCRIPTIONS,
  CORE_PERMISSION_PRESET_LABELS,
  type CoreModelCatalogView,
  type CorePermissionPreset,
} from '@/composer/execution.ts'
import {
  relativeLuminance,
  themeAreaBackground,
  themeAreaFill,
  themeAreaGlass,
  themeAreaGlassFilter,
  themeAreaImage,
  themeAreaImageFit,
  themeAreaImageLayer,
  themeAreaImageRepeat,
  themeAreaImageSize,
  type ThemeArea,
  type ThemeData,
  type ThemeFillMode,
  type ThemeGlassPreference,
  type ThemeImageFit,
  type ThemeMode,
  type ThemePreset,
  type ThemeSchedule,
  type ThemeStop,
} from '@/helpers/theme.ts'
import { openUpdatePage } from '@/helpers/update.ts'
import { openExternalUrl } from '@/helpers/openUrl.ts'
import SettingsShell from '@/components/SettingsShell.vue'
import { CORE_SETTINGS_SECTIONS, type SettingsSection } from '@/components/settingsSections.ts'
import ThemeEditor from '@/components/ThemeEditor.vue'
import CoreSubAgentEditor from '@/components/CoreSubAgentEditor.vue'
import CoreGeneralEditor from '@/components/CoreGeneralEditor.vue'
import CoreLoadToolsEditor from '@/components/CoreLoadToolsEditor.vue'
import MobileControlPanel, {
  type MobileControlAccountDevice,
  type MobileControlAccountPayload,
  type MobileControlAccountStatus,
  type MobileControlGatewayStatus,
  type MobileControlIdentity,
  type MobileControlPairing,
} from '@/components/MobileControlPanel.vue'
import UiSelect from '@/components/UiSelect.vue'
import CoreModelCatalogViewToggle from '@/components/CoreModelCatalogViewToggle.vue'
import SettingsDraftDialog from '@/components/SettingsDraftDialog.vue'
import {
  readUpdateAutoCheck,
  setUpdateAutoCheck,
  useCoreUpdateState,
  type CoreUpdateState,
} from '@/composables/index.ts'

export type CoreSettingsDensity = 'compact' | 'standard' | 'loose'
export type SettingsCatalogMutation = 'create-provider' | 'update-provider' | 'create-model' | 'update-model' | 'create-model-group' | 'update-model-group' | 'set-model-group-members' | 'create-model-with-provider'

export interface CoreSettingsModel {
  id: string
  provider_id?: string
  provider_name?: string
  model_id?: string
  display_name?: string
  context_window?: number
  max_output_tokens?: number
  thinking_supported?: boolean
  thinking_budget?: number
  temperature?: number
  is_default?: boolean
  capability?: string
  notes?: string
  extra?: Record<string, unknown> | null
}

export interface CoreSettingsProvider {
  id: string
  name?: string
  api_type?: string
  base_url?: string
  has_api_key?: boolean
  extra?: Record<string, unknown> | null
}

export interface CoreSettingsProviderPayload {
  provider_id?: string
  preset_id?: string
  name: string
  api_type: string
  base_url: string
  api_key?: string
  extra?: Record<string, unknown>
  models?: CoreSettingsModelPayload[]
  model_group_name?: string
}

export interface CoreSettingsModelGroup {
  id: string
  name: string
  model_ids: string[]
  revision?: number
  is_system?: boolean
}

export interface CoreSettingsModelPayload {
  model_record_id?: string
  provider_id: string
  provider_name?: string
  model_id: string
  display_name: string
  context_window: number
  max_output_tokens: number
  thinking_supported: boolean
  thinking_budget: number
  temperature: number
  is_default?: boolean
  capability?: string
  notes?: string
  extra?: Record<string, unknown>
}

const props = withDefaults(defineProps<{
  models: CoreSettingsModel[]
  providers: CoreSettingsProvider[]
  modelGroups?: CoreSettingsModelGroup[]
  catalogView?: CoreModelCatalogView
  /** Section the settings surface opens on (e.g. the rail's account entry). */
  section?: string
  /** Hide the built-in left nav: the host renders it in the workspace drawer. */
  hideNav?: boolean
  /** Controlled section from the host's drawer nav. */
  activeSection?: string
  density: CoreSettingsDensity
  theme: ThemeData
  contentWidth?: number
  themeMode?: ThemeMode
  themeSchedule?: ThemeSchedule
  effectiveThemeMode?: 'light' | 'dark'
  allowEnvironmentImport?: boolean
  commandShellPlatform?: 'windows' | 'linux' | 'mobile' | 'web' | 'other'
  permissionPreset?: CorePermissionPreset
  allowAccessOutsideWorkdir?: boolean
  requestRpc?: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  /** Await the host's existing persistence/revision handling before closing. */
  persistCatalog?: (operation: SettingsCatalogMutation, payload: Record<string, unknown>) => Promise<void>
  updateState?: CoreUpdateState
  remoteGatewayStatus?: MobileControlGatewayStatus | null
  remotePairing?: MobileControlPairing | null
  remoteGatewayLoading?: boolean
  remoteGatewayError?: string
  remoteGatewayAvailable?: boolean
  remoteAccountStatus?: MobileControlAccountStatus | null
  remoteAccountIdentity?: MobileControlIdentity | null
  remoteAccountLoading?: boolean
  remoteAccountDevices?: MobileControlAccountDevice[]
}>(), {
  modelGroups: () => [],
  catalogView: 'provider',
  commandShellPlatform: 'other',
  section: undefined,
})

const emit = defineEmits<{
  close: []
  'section-change': [id: string]
  'update:density': [density: CoreSettingsDensity]
  'update:content-width': [width: number]
  'update:theme-mode': [mode: ThemeMode]
  'update:theme-schedule': [schedule: ThemeSchedule]
  'import-environment': []
  'reopen-onboarding': []
  'update-permission-preset': [preset: CorePermissionPreset]
  'update-allow-outside-workdir': [value: boolean]
  'reset-theme': []
  'apply-preset': [preset: ThemePreset]
  'update-stops': [area: ThemeArea, stops: ThemeStop[]]
  'update-angle': [area: ThemeArea, angle: number]
  'update-opacity': [area: ThemeArea, opacity: number]
  'update-text-color': [area: ThemeArea, color: string]
  'update-fill-mode': [area: ThemeArea, mode: ThemeFillMode]
  'update-glass-level': [area: ThemeArea, level: ThemeGlassPreference]
  'update-image': [area: ThemeArea, dataUrl: string]
  'update-image-fit': [area: ThemeArea, fit: ThemeImageFit]
  'update-process-icon-color': [color: string]
  'add-stop': [area: ThemeArea]
  'remove-stop': [area: ThemeArea, index: number]
  'sort-stops': [area: ThemeArea]
  'create-provider': [payload: CoreSettingsProviderPayload]
  'update-provider': [payload: CoreSettingsProviderPayload]
  'delete-provider': [providerId: string]
  'create-model': [payload: CoreSettingsModelPayload]
  'update-model': [payload: CoreSettingsModelPayload]
  'delete-model': [modelRecordId: string]
  'set-default-model': [modelId: string]
  'update:catalogView': [value: CoreModelCatalogView]
  'create-model-group': [payload: { name: string }]
  'update-model-group': [payload: { group_id: string; name: string }]
  'delete-model-group': [groupId: string]
  'set-model-group-members': [payload: { group_id: string; model_ids: string[] }]
  'create-model-with-provider': [payload: Record<string, unknown>]
  'remote-gateway-start': []
  'remote-gateway-stop': []
  'remote-pairing-create': []
  'remote-device-revoke': [deviceId: string]
  'remote-account-submit': [payload: MobileControlAccountPayload]
  'remote-account-logout': []
}>()

const sections = CORE_SETTINGS_SECTIONS
const draftGuard = createSettingsDraftGuard()
const resolvedSection = ref(props.activeSection || props.section || sections[0]?.id || '')
function beforeSectionChange(_id: string, proceed: () => void) {
  draftGuard.requestNavigation(proceed, { section: resolvedSection.value })
}
function onSectionChange(id: string) {
  if (resolvedSection.value === 'models' && id !== 'models') closeEditors()
  resolvedSection.value = id
  emit('section-change', id)
}
function requestSection(id: string) {
  if (id === resolvedSection.value) return
  beforeSectionChange(id, () => onSectionChange(id))
}
watch(() => props.activeSection, id => { if (id) requestSection(id) })

// ── Update check state (共享实例由 App.vue 传入以便启动时自动检查；缺省自建) ──
const updateAutoCheck = ref(readUpdateAutoCheck())
function toggleUpdateAutoCheck() {
  updateAutoCheck.value = !updateAutoCheck.value
  setUpdateAutoCheck(updateAutoCheck.value)
}
async function openUpdateReleasePage() {
  if (updateReleaseUrl.value) {
    await openUpdatePage(updateReleaseUrl.value)
  }
}

const densityOptions: Array<{ value: CoreSettingsDensity; label: string }> = [
  { value: 'compact', get label() { return t("紧凑") } },
  { value: 'standard', get label() { return t("标准") } },
  { value: 'loose', get label() { return t("宽松") } },
]

type CommandShellPreference = 'auto' | 'wsl' | 'git-bash' | 'powershell'
const commandShellOptions = [
  { value: 'auto', get label() { return t("自动") } },
  { value: 'wsl', label: 'WSL' },
  { value: 'git-bash', label: 'Git Bash' },
  { value: 'powershell', label: 'PowerShell' },
]
const commandShellPreference = ref<CommandShellPreference>('auto')
const savedCommandShellPreference = ref<CommandShellPreference>('auto')
const commandShellLoading = ref(false)
const commandShellSaving = ref(false)
const commandShellError = ref('')

function normalizeCommandShellPreference(value: unknown): CommandShellPreference {
  return value === 'wsl' || value === 'git-bash' || value === 'powershell' ? value : 'auto'
}

async function fetchCommandShellSettings() {
  if (props.commandShellPlatform !== 'windows') return
  const rpc = props.requestRpc || defaultRequestRpc
  commandShellLoading.value = true
  commandShellError.value = ''
  try {
    const result = await rpc('settings.get', { namespace: 'core.commandShell' })
    const value = result.value && typeof result.value === 'object'
      ? result.value as Record<string, unknown>
      : {}
    const preference = normalizeCommandShellPreference(value.preference)
    commandShellPreference.value = preference
    savedCommandShellPreference.value = preference
  } catch (e) {
    commandShellError.value = e instanceof Error ? e.message : String(e)
  } finally {
    commandShellLoading.value = false
  }
}

async function updateCommandShellPreference(rawPreference: string) {
  const preference = normalizeCommandShellPreference(rawPreference)
  const previous = savedCommandShellPreference.value
  if (preference === previous || commandShellSaving.value) return

  commandShellPreference.value = preference
  commandShellSaving.value = true
  commandShellError.value = ''
  try {
    const rpc = props.requestRpc || defaultRequestRpc
    await rpc('settings.update', {
      namespace: 'core.commandShell',
      value: { preference },
    })
    savedCommandShellPreference.value = preference
  } catch (e) {
    commandShellPreference.value = previous
    commandShellError.value = e instanceof Error ? e.message : String(e)
  } finally {
    commandShellSaving.value = false
  }
}

type ProviderEditor = Required<Omit<CoreSettingsProviderPayload, 'provider_id' | 'model_group_name'>> & {
  mode: 'create' | 'update'
  provider_id?: string
  model_group_name?: string
  api_key: string
  extra_json: string
}

type ModelEditor = CoreSettingsModelPayload & {
  mode: 'create' | 'update'
  extra_json: string
  origin_group_id?: string
  provider_mode?: 'existing' | 'new'
  base_url?: string
  new_provider_name?: string
  new_provider_api_type?: string
  new_provider_api_key?: string
}

const providerEditor = ref<ProviderEditor | null>(null)
const modelEditor = ref<ModelEditor | null>(null)
const modelGroupEditor = ref<{ mode: 'create' | 'update'; group_id?: string; name: string } | null>(null)
const groupMembersEditor = ref<{ group_id: string; model_ids: string[] } | null>(null)
const noticeText = ref('')
// Validation feedback shown INSIDE the editor overlay — noticeText renders
// behind the overlay and was invisible while editing (audit 17 S3).
const editorError = ref('')
const catalogSaving = ref(false)
const catalogDraft = useSettingsDraft({
  guard: draftGuard,
  section: 'models', label: () => t('模型与供应商'),
  read: () => ({ provider: providerEditor.value, model: modelEditor.value, group: modelGroupEditor.value,
    members: groupMembersEditor.value ? { ...groupMembersEditor.value, model_ids: [...groupMembersEditor.value.model_ids].sort() } : null }),
  restore: saved => {
    providerEditor.value = saved.provider
    modelEditor.value = saved.model
    modelGroupEditor.value = saved.group
    groupMembersEditor.value = saved.members
    editorError.value = ''
  },
  busy: catalogSaving,
  error: editorError,
  save: async () => {
    const form = editorPopoverEl.value?.querySelector('form')
    if (form && !form.reportValidity()) {
      editorError.value = t('请填写必填项并检查输入格式。')
      return false
    }
    if (providerEditor.value) return submitProvider()
    if (modelEditor.value) return submitModel()
    if (modelGroupEditor.value) return submitModelGroup()
    if (groupMembersEditor.value) return submitGroupMembers()
    return true
  },
})
watch([providerEditor, modelEditor, modelGroupEditor, groupMembersEditor], () => catalogDraft.accept(), { flush: 'sync' })

async function persistCatalog(operation: SettingsCatalogMutation, payload: object): Promise<boolean> {
  if (catalogSaving.value) return false
  catalogSaving.value = true
  editorError.value = ''
  try {
    if (props.persistCatalog) await props.persistCatalog(operation, payload as Record<string, unknown>)
    else {
      // Compatibility for event-driven embedders. The application supplies
      // persistCatalog so a failed write never dismisses its editor.
      const notify = emit as (event: SettingsCatalogMutation, payload: object) => void
      notify(operation, payload)
    }
    closeEditors()
    return true
  } catch (cause) {
    editorError.value = cause instanceof Error ? cause.message : String(cause)
    return false
  } finally {
    catalogSaving.value = false
  }
}
// ── Global AGENTS.md (项目规则) editor state ──
const agentsDraft = ref('')
const agentsLoading = ref(false)
const agentsSaving = ref(false)
const agentsError = ref('')
const agentsSettingsDraft = useSettingsDraft({
  guard: draftGuard,
  section: 'agents', label: () => t('全局约束'), read: () => agentsDraft.value,
  restore: value => { agentsDraft.value = value; agentsError.value = '' },
  save: saveGlobalAgentsMd, busy: agentsSaving, error: agentsError,
})

async function fetchGlobalAgentsMd() {
  const rpc = props.requestRpc || defaultRequestRpc
  agentsLoading.value = true
  agentsError.value = ''
  try {
    const result = await rpc('config.agents_md.get')
    const agentsMd = result.agents_md as { content?: string; exists?: boolean } | undefined
    agentsDraft.value = agentsMd?.content ?? ''
    agentsSettingsDraft.accept()
  } catch (e) {
    agentsError.value = e instanceof Error ? e.message : String(e)
  } finally {
    agentsLoading.value = false
  }
}

async function saveGlobalAgentsMd() {
  const rpc = props.requestRpc || defaultRequestRpc
  agentsSaving.value = true
  agentsError.value = ''
  try {
    const content = agentsDraft.value
    await rpc('config.agents_md.set', { content })
    agentsSettingsDraft.accept(content)
    await fetchGlobalAgentsMd()
    return true
  } catch (e) {
    agentsError.value = e instanceof Error ? e.message : String(e)
    return false
  } finally {
    agentsSaving.value = false
  }
}

// ── Global load_context.jsonc (上下文与记忆) editor state ──
interface ContextAdditionDraft {
  name: string
  priority: number
  kind: string
}

const contextAdditions = ref<ContextAdditionDraft[]>([])
const contextExcept = ref<string[]>([])
const contextExceptDraft = ref('')
const contextLoading = ref(false)
const contextSaving = ref(false)
const contextError = ref('')
const contextSettingsDraft = useSettingsDraft({
  guard: draftGuard,
  section: 'agents', label: () => t('全局上下文加载'),
  read: () => ({ addition: contextAdditions.value, except: contextExcept.value, pendingExcept: contextExceptDraft.value }),
  restore: value => {
    contextAdditions.value = value.addition; contextExcept.value = value.except
    contextExceptDraft.value = value.pendingExcept; contextError.value = ''
  }, save: saveLoadContext, busy: contextSaving, error: contextError,
})

function addContextExcept() {
  const name = contextExceptDraft.value.trim()
  if (!name) return
  if (!contextExcept.value.includes(name)) contextExcept.value.push(name)
  contextExceptDraft.value = ''
}

async function fetchLoadContext() {
  const rpc = props.requestRpc || defaultRequestRpc
  contextLoading.value = true
  contextError.value = ''
  try {
    const result = await rpc('config.load_context.get')
    const additions = Array.isArray(result.addition) ? result.addition : []
    contextAdditions.value = additions.map(item => ({
      name: String((item as Record<string, unknown>).name ?? ''),
      priority: Number((item as Record<string, unknown>).priority ?? 50),
      kind: String((item as Record<string, unknown>).kind ?? 'system'),
    }))
    contextExcept.value = Array.isArray(result.except)
      ? result.except.map(item => String(item))
      : []
    contextExceptDraft.value = ''
    contextSettingsDraft.accept()
  } catch (e) {
    contextError.value = e instanceof Error ? e.message : String(e)
  } finally {
    contextLoading.value = false
  }
}

async function saveLoadContext() {
  const rpc = props.requestRpc || defaultRequestRpc
  contextSaving.value = true
  contextError.value = ''
  try {
    addContextExcept()
    await rpc('config.load_context.set', {
      addition: contextAdditions.value
        .filter(item => item.name.trim())
        .map(item => ({ name: item.name.trim(), priority: Number(item.priority) || 50, kind: item.kind })),
      except: contextExcept.value.filter(name => name.trim()),
    })
    contextSettingsDraft.accept()
    await fetchLoadContext()
    return true
  } catch (e) {
    contextError.value = e instanceof Error ? e.message : String(e)
    return false
  } finally {
    contextSaving.value = false
  }
}

// ── Context compaction settings (上下文压缩, core.contextCompaction) ──
const CONTEXT_COMPACTION_DEFAULT_RETAINED_STEPS = 0
const CONTEXT_COMPACTION_MIN_RETAINED_STEPS = 0
const CONTEXT_COMPACTION_MAX_RETAINED_STEPS = 100

const contextCompactionRetainedSteps = ref(CONTEXT_COMPACTION_DEFAULT_RETAINED_STEPS)
const contextCompactionLoading = ref(false)
const contextCompactionSaving = ref(false)
const contextCompactionError = ref('')
const compactionSettingsDraft = useSettingsDraft({
  guard: draftGuard,
  section: 'agents', label: () => t('上下文压缩'), read: () => contextCompactionRetainedSteps.value,
  restore: value => { contextCompactionRetainedSteps.value = value; contextCompactionError.value = '' },
  save: saveContextCompactionSettings, busy: contextCompactionSaving, error: contextCompactionError,
})

function normalizeContextCompactionRetainedSteps(value: unknown): number {
  if (value === null || value === undefined || (typeof value === 'string' && !value.trim())) {
    return CONTEXT_COMPACTION_DEFAULT_RETAINED_STEPS
  }
  const rawSteps = Number(value)
  if (!Number.isFinite(rawSteps)) return CONTEXT_COMPACTION_DEFAULT_RETAINED_STEPS
  return Math.min(
    CONTEXT_COMPACTION_MAX_RETAINED_STEPS,
    Math.max(CONTEXT_COMPACTION_MIN_RETAINED_STEPS, Math.floor(rawSteps)),
  )
}

async function fetchContextCompactionSettings() {
  const rpc = props.requestRpc || defaultRequestRpc
  contextCompactionLoading.value = true
  contextCompactionError.value = ''
  try {
    const result = await rpc('settings.get', { namespace: 'core.contextCompaction' })
    const value = (result.value ?? {}) as Record<string, unknown>
    contextCompactionRetainedSteps.value = normalizeContextCompactionRetainedSteps(value.retained_steps)
    compactionSettingsDraft.accept()
  } catch (e) {
    contextCompactionError.value = e instanceof Error ? e.message : String(e)
  } finally {
    contextCompactionLoading.value = false
  }
}

async function saveContextCompactionSettings() {
  const rpc = props.requestRpc || defaultRequestRpc
  contextCompactionSaving.value = true
  contextCompactionError.value = ''
  try {
    // Native min/max validation does not run because this row is not a form;
    // normalize the value before persisting it.
    const retainedSteps = normalizeContextCompactionRetainedSteps(contextCompactionRetainedSteps.value)
    contextCompactionRetainedSteps.value = retainedSteps
    await rpc('settings.update', {
      namespace: 'core.contextCompaction',
      value: { retained_steps: retainedSteps },
    })
    compactionSettingsDraft.accept(retainedSteps)
    return true
  } catch (e) {
    contextCompactionError.value = e instanceof Error ? e.message : String(e)
    return false
  } finally {
    contextCompactionSaving.value = false
  }
}

function closeEditors() {
  providerEditor.value = null
  modelEditor.value = null
  modelGroupEditor.value = null
  groupMembersEditor.value = null
  editorError.value = ''
}

const defaultRequestRpc = async (_method: string, _params?: Record<string, unknown>) => {
  throw new Error('requestRpc not provided — connect CoreSettings to a CoreAppServerClient')
}

// 放在 defaultRequestRpc 之后实例化（const TDZ：setup 顶层立即求值）
const update = props.updateState ?? useCoreUpdateState(props.requestRpc || defaultRequestRpc)
// 解构到 setup 顶层：模板中的嵌套 ref 不会自动解包（普通对象属性），
// 顶层 ref 才会被 Vue 模板解包并得到正确的类型推断。
const {
  status: updateStatus,
  currentVersion: updateCurrentVersion,
  latestVersion: updateLatestVersion,
  releaseNotes: updateReleaseNotes,
  releaseUrl: updateReleaseUrl,
  sourceLabel: updateSourceLabel,
  noInstallerForPlatform: updateNoInstallerForPlatform,
  error: updateError,
  installSupported: updateInstallSupported,
  installHint: updateInstallHint,
  installState: updateInstallState,
  installMessage: updateInstallMessage,
  installError: updateInstallError,
  installProgressLabel: updateInstallProgressLabel,
  packageSizeLabel: updatePackageSizeLabel,
  check: checkForUpdates,
  download: downloadUpdate,
  downloadInstaller,
  runInstaller,
} = update

const permissionPreset = computed<CorePermissionPreset>(() => (
  props.permissionPreset === 'auto' || props.permissionPreset === 'full_access'
    ? props.permissionPreset
    : 'ask'
))
const permissionPresetLabel = computed(() => CORE_PERMISSION_PRESET_LABELS[permissionPreset.value])
const effectiveAllowAccessOutsideWorkdir = computed(() => (
  permissionPreset.value === 'full_access' || Boolean(props.allowAccessOutsideWorkdir)
))
function toggleAllowOutsideWorkdir() {
  if (permissionPreset.value === 'full_access') return
  emit('update-allow-outside-workdir', !Boolean(props.allowAccessOutsideWorkdir))
}
const permissionPresetOptions = (['ask', 'auto', 'full_access'] as CorePermissionPreset[]).map((id) => ({
  id,
  label: CORE_PERMISSION_PRESET_LABELS[id],
  description: CORE_PERMISSION_PRESET_DESCRIPTIONS[id],
}))

function selectPermissionPreset(preset: CorePermissionPreset) {
  emit('update-permission-preset', preset)
}
const providerPresets = PROVIDER_PRESETS

const providerCount = computed(() => props.providers.length)
const selectedProviderId = ref<string | null>(null)
const selectedModelGroupId = ref<string | null>(null)
const providerQuery = ref('')
const groupQuery = ref('')
const modelQuery = ref('')
const selectedProvider = computed(() =>
  props.providers.find(provider => provider.id === selectedProviderId.value) || props.providers[0] || null,
)
const selectedProviderModels = computed(() =>
  selectedProvider.value
    ? props.models.filter(model => model.provider_id === selectedProvider.value?.id)
    : [],
)
const selectedModelGroup = computed(() =>
  props.modelGroups.find(group => group.id === selectedModelGroupId.value) || props.modelGroups[0] || null,
)
const selectedGroupModels = computed(() => {
  const ids = new Set(selectedModelGroup.value?.model_ids || [])
  return props.models.filter(model => ids.has(model.id))
})
const filteredModelGroups = computed(() => {
  const query = groupQuery.value.toLocaleLowerCase()
  if (!query) return props.modelGroups
  return props.modelGroups.filter(group => [group.name, group.id]
    .some(value => String(value || '').toLocaleLowerCase().includes(query)))
})
const filteredProviders = computed(() => {
  const query = providerQuery.value.toLocaleLowerCase()
  if (!query) return props.providers
  return props.providers.filter(provider => [provider.name, provider.id, provider.api_type]
    .some(value => String(value || '').toLocaleLowerCase().includes(query)))
})
const filteredSelectedProviderModels = computed(() => {
  const query = modelQuery.value.toLocaleLowerCase()
  if (!query) return selectedProviderModels.value
  return selectedProviderModels.value.filter(model => [model.display_name, model.model_id, model.id, model.capability]
    .some(value => String(value || '').toLocaleLowerCase().includes(query)))
})
const filteredSelectedGroupModels = computed(() => {
  const query = modelQuery.value.toLocaleLowerCase()
  if (!query) return selectedGroupModels.value
  return selectedGroupModels.value.filter(model => [model.display_name, model.model_id, model.id, model.capability]
    .some(value => String(value || '').toLocaleLowerCase().includes(query)))
})

function providerTypeLabel(apiType?: string): string {
  if (apiType === 'anthropic') return 'Anthropic'
  if (apiType === 'openai') return 'OpenAI compatible'
  return apiType || t("自定义接口")
}

function selectProvider(providerId: string) {
  selectedProviderId.value = providerId
  modelQuery.value = ''
}

function selectModelGroup(groupId: string) {
  selectedModelGroupId.value = groupId
  modelQuery.value = ''
}

function modelProviderName(model: CoreSettingsModel): string {
  return props.providers.find(provider => provider.id === model.provider_id)?.name
    || model.provider_name
    || model.provider_id
    || t("未关联供应商")
}

// ── UiSelect option lists for provider/model editors ──
const providerPresetOptions = computed(() => [
  { value: '', get label() { return t("自定义") } },
  ...PROVIDER_PRESETS.map(preset => ({
    value: preset.id,
    label: preset.label,
    group: PROVIDER_PRESET_GROUP_LABELS[preset.group],
  })),
])
const selectedProviderPreset = computed(() => (
  providerPresets.find(preset => preset.id === providerEditor.value?.preset_id) || null
))

function openProviderApiKeyPage() {
  const url = selectedProviderPreset.value?.apiKeyUrl
  if (url) void openExternalUrl(url)
}
const apiTypeOptions = [
  { value: 'openai', label: 'OpenAI compatible' },
  { value: 'anthropic', label: 'Anthropic' },
]
const lcKindOptions = [
  { value: 'system', label: 'system' },
  { value: 'memory', label: 'memory' },
]
const capabilityOptions = [
  { value: '', get label() { return t("自动（内置声明）") } },
  { value: 'text', get label() { return t("文本（不支持图片）") } },
  { value: 'multimodal', get label() { return t("多模态（支持图片）") } },
]
const providerOptions = computed(() =>
  props.providers.map(p => ({ value: p.id, label: p.name || p.id })),
)
const groupModelProviderOptions = computed(() => [
  ...providerOptions.value,
  { value: '__new__', get label() { return t("＋ 新建供应商") } },
])

function onProviderPresetChange(value: string) {
  const editor = providerEditor.value
  if (!editor) return
  editor.preset_id = value
  applyProviderPreset()
}

const settingsThemeStyle = computed(() => {
  const lightMain = relativeLuminance(props.theme.mainText) < 0.45
  return {
    '--settings-backdrop-background': themeAreaBackground(props.theme, 'backdrop'),
    '--settings-backdrop-text': props.theme.backdropText,
    '--settings-main-background': themeAreaBackground(props.theme, 'main'),
    '--settings-main-text': props.theme.mainText,
    // main 区首停点纯色：卡片实色底（渐变值不可用于 color-mix）
    '--settings-main-solid': props.theme.mainStops[0]?.color || '#111111',
    // 卡片/浮层面板：main 实色 + 文字色 4% 微调，不透明、与内容区有层级
    '--settings-card-background': 'color-mix(in srgb, var(--settings-main-solid) 96%, var(--settings-main-text) 4%)',
    '--settings-card-text': props.theme.mainText,
    '--settings-control-background': themeAreaBackground(props.theme, 'control'),
    '--settings-control-text': props.theme.controlText,
    // control 区首停点纯色：color-mix 混透明用的实色底（渐变值不可用于 color-mix）
    '--settings-control-solid': props.theme.controlStops[0]?.color || '#3a3834',
    // 暗色分支不重复字面量：layout.css 的 --settings-* fallback 即 :root 真值（单一来源）
    ...(lightMain ? {
      '--settings-panel-2': '#f0efeb',
      '--settings-line': '#d4d0cc',
      '--settings-muted': '#8a8580',
    } : {}),
  }
})

const previewStyleFor = (area: ThemeArea, textColor: string) => ({
  background: themeAreaBackground(props.theme, area),
  backgroundImage: themeAreaImageLayer(props.theme, area),
  backgroundSize: themeAreaImageSize(props.theme, area),
  backgroundRepeat: themeAreaImageRepeat(props.theme, area),
  backgroundPosition: 'center',
  backdropFilter: themeAreaGlassFilter(props.theme, area),
  color: textColor,
})
const themePreviewStyle = computed(() => previewStyleFor('backdrop', props.theme.backdropText))
const themePreviewMainStyle = computed(() => previewStyleFor('main', props.theme.mainText))
const themePreviewComposerStyle = computed(() => previewStyleFor('composer', props.theme.composerText))
const themePreviewControlStyle = computed(() => previewStyleFor('control', props.theme.controlText))

function modelsForProvider(providerId: string): CoreSettingsModel[] {
  return props.models.filter((model) => model.provider_id === providerId)
}

function startProviderCreate() {
  catalogDraft.requestReplace(() => {
    closeEditors()
    providerEditor.value = {
      mode: 'create',
      preset_id: '',
      name: '',
      api_type: 'openai',
      base_url: '',
      api_key: '',
      extra: {},
      extra_json: '{}',
      models: [],
    }
  })
}

function startProviderUpdate(provider: CoreSettingsProvider) {
  catalogDraft.requestReplace(() => {
    closeEditors()
    providerEditor.value = {
      mode: 'update',
      preset_id: '',
      provider_id: provider.id,
      name: provider.name || '',
      api_type: provider.api_type || 'openai',
      base_url: provider.base_url || '',
      api_key: '',
      extra: provider.extra || {},
      extra_json: JSON.stringify(provider.extra || {}, null, 2),
      models: [],
    }
  })
}

async function submitProvider() {
  const editor = providerEditor.value
  if (!editor) return
  const extra = parseExtraJson(editor.extra_json)
  if (!extra) return
  const payload: CoreSettingsProviderPayload = {
    ...(editor.provider_id ? { provider_id: editor.provider_id } : {}),
    ...(editor.preset_id ? { preset_id: editor.preset_id } : {}),
    name: editor.name,
    api_type: editor.api_type,
    base_url: editor.base_url,
    ...(editor.api_key.trim() ? { api_key: editor.api_key.trim() } : {}),
    extra,
  }
  if (editor.mode === 'create' && editor.preset_id) {
    const preset = providerPresets.find(candidate => candidate.id === editor.preset_id)
    if (preset) {
      if ((preset as typeof preset & { group?: string }).group === 'free') payload.model_group_name = 'Free'
      payload.models = preset.models.map(model => ({
        provider_id: '',
        model_id: model.modelId,
        display_name: model.displayName,
        context_window: model.contextWindow,
        max_output_tokens: model.maxOutputTokens,
        thinking_supported: model.thinkingSupported,
        thinking_budget: model.thinkingBudget,
        temperature: model.temperature,
        // NOT a global default: the backend only uses this to seed the
        // main-chat scene when no model has ever been used there. Adding a
        // provider must never change the model a running session uses.
        is_default: model.modelId === preset.defaultModelId,
        extra: providerPresetModelExtra(model),
      }))
    }
  }
  return persistCatalog(editor.mode === 'create' ? 'create-provider' : 'update-provider', payload)
}

function applyProviderPreset() {
  const editor = providerEditor.value
  if (!editor) return
  const preset = providerPresets.find(candidate => candidate.id === editor.preset_id)
  if (!preset) return
  editor.name = preset.name
  editor.api_type = preset.apiType
  editor.base_url = preset.baseUrl
  // 模板可预置 API Key；免费模型也可能要求用户申请真实凭据。
  editor.api_key = preset.defaultApiKey || ''
  editor.extra = { ...(preset.extra || {}), adapter_profile_id: preset.adapterProfile }
  editor.extra_json = JSON.stringify(editor.extra, null, 2)
}

function startSelectedModelCreate() {
  const provider = selectedProvider.value
  if (!provider) {
    noticeText.value = t("请先新增供应商，再添加模型")
    return
  }
  startModelCreateForProvider(provider)
}

function startModelCreateForProvider(provider: CoreSettingsProvider) {
  catalogDraft.requestReplace(() => {
    closeEditors()
    modelEditor.value = {
      mode: 'create',
      provider_id: provider?.id || '',
      provider_name: provider?.name || '',
      model_id: '',
      display_name: '',
      context_window: 128000,
      max_output_tokens: 16384,
      thinking_supported: false,
      thinking_budget: 10000,
      temperature: 0.7,
      capability: '',
      notes: '',
      extra: {},
      extra_json: '{}',
    }
  })
}

function startModelGroupCreate() {
  catalogDraft.requestReplace(() => {
    closeEditors()
    modelGroupEditor.value = { mode: 'create', name: '' }
  })
}

function startModelGroupUpdate(group: CoreSettingsModelGroup) {
  catalogDraft.requestReplace(() => {
    closeEditors()
    modelGroupEditor.value = { mode: 'update', group_id: group.id, name: group.name }
  })
}

async function submitModelGroup() {
  const editor = modelGroupEditor.value
  if (!editor?.name.trim()) return
  return persistCatalog(editor.mode === 'create' ? 'create-model-group' : 'update-model-group',
    editor.mode === 'create' ? { name: editor.name.trim() } : { group_id: editor.group_id || '', name: editor.name.trim() })
}

function startGroupMembersEdit() {
  catalogDraft.requestReplace(() => {
    closeEditors()
    const group = selectedModelGroup.value
    if (!group) return
    groupMembersEditor.value = { group_id: group.id, model_ids: [...group.model_ids] }
  })
}

async function submitGroupMembers() {
  const editor = groupMembersEditor.value
  if (!editor) return
  return persistCatalog('set-model-group-members', { group_id: editor.group_id, model_ids: [...new Set(editor.model_ids)] })
}

function removeModelFromSelectedGroup(modelId: string) {
  const group = selectedModelGroup.value
  if (!group) return
  emit('set-model-group-members', {
    group_id: group.id,
    model_ids: group.model_ids.filter(id => id !== modelId),
  })
}

function startGroupModelCreate() {
  catalogDraft.requestReplace(() => {
    closeEditors()
    const group = selectedModelGroup.value
    if (!group) return
    const provider = props.providers[0]
    modelEditor.value = {
      mode: 'create',
      origin_group_id: group.id,
      provider_mode: provider ? 'existing' : 'new',
      provider_id: provider?.id || '__new__',
      provider_name: provider?.name || '',
      base_url: provider?.base_url || '',
      new_provider_name: '',
      new_provider_api_type: 'openai',
      new_provider_api_key: '',
      model_id: '',
      display_name: '',
      context_window: 128000,
      max_output_tokens: 16384,
      thinking_supported: false,
      thinking_budget: 10000,
      temperature: 0.7,
      capability: '',
      notes: '',
      extra: {},
      extra_json: '{}',
    }
  })
}

function onModelProviderChange(providerId: string) {
  const editor = modelEditor.value
  if (!editor) return
  editor.provider_id = providerId
  if (!editor.origin_group_id) return
  if (providerId === '__new__') {
    editor.provider_mode = 'new'
    editor.provider_name = ''
    editor.base_url = ''
    return
  }
  const provider = props.providers.find(item => item.id === providerId)
  editor.provider_mode = 'existing'
  editor.provider_name = provider?.name || ''
  editor.base_url = provider?.base_url || ''
}

function startModelUpdate(model: CoreSettingsModel) {
  catalogDraft.requestReplace(() => {
    closeEditors()
    modelEditor.value = {
      mode: 'update',
      model_record_id: model.id,
      provider_id: model.provider_id || '',
      provider_name: model.provider_name || '',
      model_id: model.model_id || '',
      display_name: model.display_name || '',
      // `??` — a legitimate 0 (e.g. thinking_budget=0 disables the reasoning
      // budget) must round-trip instead of silently becoming the default
      // (audit 17 S3).
      context_window: model.context_window ?? 128000,
      max_output_tokens: model.max_output_tokens ?? 16384,
      thinking_supported: model.thinking_supported === true,
      thinking_budget: model.thinking_budget ?? 10000,
      temperature: model.temperature ?? 0.7,
      capability: model.capability || '',
      notes: model.notes || '',
      extra: model.extra || {},
      extra_json: JSON.stringify(model.extra || {}, null, 2),
    }
  })
}

async function submitModel() {
  const editor = modelEditor.value
  if (!editor) return
  editorError.value = ''
  if (!editor.provider_id) {
    editorError.value = t("请先选择供应商")
    return
  }
  const extra = parseExtraJson(editor.extra_json)
  if (!extra) return
  const payload: CoreSettingsModelPayload = {
    ...(editor.model_record_id ? { model_record_id: editor.model_record_id } : {}),
    provider_id: editor.provider_id,
    provider_name: editor.provider_name,
    model_id: editor.model_id,
    display_name: editor.display_name,
    context_window: editor.context_window,
    max_output_tokens: editor.max_output_tokens,
    thinking_supported: editor.thinking_supported,
    thinking_budget: editor.thinking_budget,
    temperature: editor.temperature,
    capability: editor.capability,
    notes: editor.notes,
    extra,
  }
  if (editor.origin_group_id) {
    if (!editor.base_url?.trim()) {
      editorError.value = t("按组新增模型时必须填写 API 基础 URL")
      return
    }
    const existingProvider = props.providers.find(item => item.id === editor.provider_id)
    if (
      editor.provider_mode === 'existing'
      && existingProvider?.base_url?.replace(/\/$/, '') !== editor.base_url.replace(/\/$/, '')
    ) {
      editorError.value = t("API 基础 URL 必须与所选供应商一致")
      return
    }
    if (editor.provider_mode === 'new' && (!editor.new_provider_name?.trim() || !editor.new_provider_api_key?.trim())) {
      editorError.value = t("新供应商需要填写名称和 API Key")
      return
    }
    return persistCatalog('create-model-with-provider', {
      group_id: editor.origin_group_id,
      model: {
        model_id: editor.model_id,
        display_name: editor.display_name,
        context_window: editor.context_window,
        max_output_tokens: editor.max_output_tokens,
        temperature: editor.temperature,
        thinking_supported: editor.thinking_supported,
        thinking_budget: editor.thinking_budget,
        capability: editor.capability,
        notes: editor.notes,
        adapter_profile_id: String(extra.adapter_profile_id || ''),
        request_body: extra.request_body && typeof extra.request_body === 'object' ? extra.request_body : {},
      },
      provider: editor.provider_mode === 'new'
        ? {
            mode: 'new',
            name: editor.new_provider_name?.trim(),
            base_url: editor.base_url.trim(),
            api_type: editor.new_provider_api_type || 'openai',
            api_key: editor.new_provider_api_key,
          }
        : {
            mode: 'existing',
            provider_id: editor.provider_id,
            base_url: editor.base_url.trim(),
          },
    })
  }
  return persistCatalog(editor.mode === 'create' ? 'create-model' : 'update-model', payload)
}

function parseExtraJson(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
    noticeText.value = ''
    editorError.value = ''
    return parsed as Record<string, unknown>
  } catch {
    editorError.value = t("高级适配 JSON 必须是对象")
    return null
  }
}

function getStops(area: ThemeArea): ThemeStop[] {
  return props.theme[`${area}Stops` as keyof ThemeData] as ThemeStop[]
}

function getAngle(area: ThemeArea): number {
  return props.theme[`${area}Angle` as keyof ThemeData] as number
}

function getOpacity(area: ThemeArea): number {
  return area === 'backdrop' ? 1 : props.theme[`${area}Opacity` as keyof ThemeData] as number
}

function getTextColor(area: ThemeArea): string {
  return props.theme[`${area}Text` as keyof ThemeData] as string
}

function getFillMode(area: ThemeArea): ThemeFillMode {
  return themeAreaFill(props.theme, area)
}

function getGlassLevel(area: ThemeArea): ThemeGlassPreference {
  return themeAreaGlass(props.theme, area)
}

function getImage(area: ThemeArea): string {
  return themeAreaImage(props.theme, area)
}

function getImageFit(area: ThemeArea): ThemeImageFit {
  return themeAreaImageFit(props.theme, area)
}

const presets = THEME_PRESETS

// user:“我只要切换界面，编辑就自动取消了，那它不是永远不可能编辑到主界面吗”+
// (设置页只负责入口：打开状态是应用级单例，编辑器由应用层挂载，切走设置页不中断编辑。)
const { studioOpen } = useThemeStudio()
function openThemeStudio(): void {
  studioOpen.value = true
}

// All exits share actual draft comparisons, including the host's rail.
const editorOverlayEl = ref<HTMLElement | null>(null)
const editorPopoverEl = ref<HTMLElement | null>(null)

function requestCloseSettings() {
  draftGuard.requestNavigation(() => emit('close'))
}
function requestCloseEditors() {
  catalogDraft.requestReplace(closeEditors)
}

defineExpose({ requestNavigation: draftGuard.requestNavigation, requestSection })

useOutsidePointerDismiss({
  overlay: editorOverlayEl,
  card: editorPopoverEl,
  isActive: () => !draftGuard.open.value && Boolean(providerEditor.value || modelEditor.value || modelGroupEditor.value || groupMembersEditor.value),
  onDismiss: requestCloseEditors,
})

// 就地渲染后设置只有主卡宽：窗口宽度与这一栏的可用宽度不是一回事，而 WebView
// 又不支持容器查询。用 ResizeObserver 按实际宽度折叠工作台，两栏装不下时改单栏。
const settingsRootEl = ref<HTMLElement | null>(null)
const narrowSurface = ref(false)
let settingsResizeObserver: ResizeObserver | null = null

function measureSettingsSurface(): void {
  const width = settingsRootEl.value?.clientWidth ?? 0
  narrowSurface.value = width > 0 && width < 900
}

function onKeydown(e: KeyboardEvent) {
  if (!splitKeyboardActive()) return
  if (e.key === 'Escape' && !draftGuard.open.value) {
    requestCloseSettings()
  }
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  if (typeof ResizeObserver !== 'undefined') {
    settingsResizeObserver = new ResizeObserver(measureSettingsSurface)
    if (settingsRootEl.value) settingsResizeObserver.observe(settingsRootEl.value)
    measureSettingsSurface()
  }
  void fetchGlobalAgentsMd()
  void fetchLoadContext()
  void fetchContextCompactionSettings()
  void fetchCommandShellSettings()
})
onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
  settingsResizeObserver?.disconnect()
  settingsResizeObserver = null
})
</script>

<!-- user:“将大的前端文件拆分成小块”+(设置页样式独立维护，保留组件作用域)。 -->
<!-- user:“还有大文件拆分”+(3059 行的设置样式按区块拆成六份，标签顺序即原文件顺序，
     层叠与作用域保持不变) -->
<style scoped src="../styles/core-settings-base.css"></style>
<style scoped src="../styles/core-settings-models.css"></style>
<style scoped src="../styles/core-settings-model-editor.css"></style>
<style scoped src="../styles/core-settings-workspace.css"></style>
<style scoped src="../styles/core-settings-surface.css"></style>
<style scoped src="../styles/core-settings-permissions.css"></style>
