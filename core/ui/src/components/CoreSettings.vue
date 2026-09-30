<template>
  <div class="full-area-column full-area-surface" :style="settingsThemeStyle">
    <SettingsShell
          :sections="sections"
          title="Sunday 设置"
          :initial-section="props.section"
          :settings-theme-style="settingsThemeStyle"
          @close="requestCloseSettings"
        >
          <template #default="{ activeSection }">
      <section v-if="activeSection === 'models'" class="settings-panel models-panel">
        <header class="settings-title models-title">
          <div class="models-title-copy">
            <h1>模型与供应商</h1>
            <p>管理模型接入、供应商配置与默认模型选择。</p>
          </div>
          <CoreModelCatalogViewToggle
            :model-value="catalogView"
            @update:model-value="$emit('update:catalogView', $event)"
          />
        </header>

        <div v-if="noticeText" class="settings-notice">{{ noticeText }}</div>

        <div v-if="catalogView === 'group' || providers.length" class="models-workspace settings-surface">
          <div class="models-workspace-body">
          <aside v-if="catalogView === 'provider'" class="provider-rail" aria-label="供应商列表">
            <div class="provider-rail-head">
              <div class="provider-rail-title">
                <strong>供应商</strong>
                <span>{{ providerCount }}</span>
              </div>
            </div>

            <label class="resource-search provider-search">
              <span class="sr-only">搜索供应商</span>
              <input v-model.trim="providerQuery" type="search" placeholder="搜索供应商" />
            </label>

            <div class="provider-picker" role="listbox" aria-label="选择供应商">
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
                  <span>{{ modelsForProvider(provider.id).length }} 个模型</span>
                </span>
                <span class="provider-picker-state" :class="{ 'is-configured': provider.has_api_key }">
                  <span class="provider-picker-state-dot" aria-hidden="true" />
                  <span>{{ provider.has_api_key ? '已就绪' : '待配置' }}</span>
                </span>
              </button>
              <div v-if="!filteredProviders.length" class="provider-rail-empty">
                <strong>没有匹配的供应商</strong>
                <small>换个关键词试试</small>
              </div>
            </div>

            <div class="provider-rail-footer">
              <button class="provider-create-btn" type="button" data-provider-create @click="startProviderCreate">
                <span aria-hidden="true">＋</span>
                <span>新增供应商</span>
              </button>
              <div class="provider-rail-links">
                <button v-if="allowEnvironmentImport" class="text-btn" type="button" @click="$emit('import-environment')">从当前环境导入</button>
                <button class="text-btn" type="button" data-reopen-onboarding @click="$emit('reopen-onboarding')">重新显示首次引导</button>
              </div>
            </div>
          </aside>

          <aside v-else class="provider-rail" aria-label="模型组列表">
            <div class="provider-rail-head">
              <div class="provider-rail-title">
                <strong>模型组</strong>
                <span>{{ modelGroups.length }}</span>
              </div>
            </div>
            <label class="resource-search provider-search">
              <span class="sr-only">搜索模型组</span>
              <input v-model.trim="groupQuery" type="search" placeholder="搜索模型组" />
            </label>
            <div class="provider-picker" role="listbox" aria-label="选择模型组">
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
                  <span>{{ group.model_ids.length }} 个模型</span>
                </span>
              </button>
              <div v-if="!filteredModelGroups.length" class="provider-rail-empty">
                <strong>{{ groupQuery ? '没有匹配的模型组' : '还没有模型组' }}</strong>
                <small>{{ groupQuery ? '换个关键词试试' : '创建分组来整理常用模型' }}</small>
              </div>
            </div>
            <div class="provider-rail-footer">
              <button class="provider-create-btn" type="button" data-model-group-create @click="startModelGroupCreate">
                <span aria-hidden="true">＋</span>
                <span>新建模型组</span>
              </button>
            </div>
          </aside>

          <section v-if="catalogView === 'provider' && selectedProvider" class="provider-detail" aria-label="供应商详情">
            <header class="provider-detail-head">
              <div class="provider-detail-identity">
                <span class="provider-detail-context">当前供应商</span>
                <div class="provider-name-line">
                  <h2>{{ selectedProvider.name || selectedProvider.id }}</h2>
                  <span class="provider-type">{{ providerTypeLabel(selectedProvider.api_type) }}</span>
                </div>
                <div class="provider-meta">
                  <span class="provider-url" :title="selectedProvider.base_url || selectedProvider.id">{{ selectedProvider.base_url || selectedProvider.id }}</span>
                  <span class="provider-state" :class="{ 'is-configured': selectedProvider.has_api_key }">
                    <span class="provider-state-dot" aria-hidden="true" />
                    {{ selectedProvider.has_api_key ? '已就绪 · 已配置密钥' : '待配置 · 缺少 API Key' }}
                  </span>
                </div>
              </div>
              <div class="provider-head-actions">
                <button class="text-btn" type="button" :data-provider-edit="selectedProvider.id" @click="startProviderUpdate(selectedProvider)">编辑</button>
                <button class="text-btn danger" type="button" :data-provider-delete="selectedProvider.id" @click="$emit('delete-provider', selectedProvider.id)">删除</button>
              </div>
            </header>

            <section class="model-section">
              <header class="model-section-head">
                <div class="model-section-title">
                  <h2>模型</h2>
                  <span>{{ selectedProviderModels.length }} 个模型</span>
                </div>
                <div class="model-section-tools">
                  <label class="resource-search model-search">
                    <span class="sr-only">搜索模型</span>
                    <input v-model.trim="modelQuery" type="search" placeholder="搜索模型" />
                  </label>
                  <button class="small-btn primary" type="button" data-model-create @click="startSelectedModelCreate">＋ 新增模型</button>
                </div>
              </header>
              <div class="model-list">
                <div v-for="model in filteredSelectedProviderModels" :key="model.id" class="model-row" :class="{ 'is-default': model.is_default }">
                  <div class="model-leading">
                    <div class="model-identity">
                      <div class="model-name-line">
                        <strong>{{ model.display_name || model.model_id || model.id }}</strong>
                        <span v-if="model.is_default" class="model-default-badge">预设首选</span>
                      </div>
                      <span class="model-meta">
                        <span class="model-id">{{ model.model_id || model.id }}</span>
                      </span>
                    </div>
                  </div>
                  <div class="model-capabilities" aria-label="模型能力">
                    <span class="model-capability">聊天</span>
                    <span v-if="model.thinking_supported" class="model-capability">推理</span>
                    <span v-if="model.capability === 'multimodal'" class="model-capability">视觉</span>
                    <span v-else-if="model.capability === 'text'" class="model-capability">文本</span>
                  </div>
                  <div class="row-actions">
                    <button v-if="!model.is_default" class="text-btn model-default-btn" type="button" :data-model-default="model.id" @click="$emit('set-default-model', model.id)">设为预设首选</button>
                    <button class="text-btn" type="button" :data-model-edit="model.id" @click="startModelUpdate(model)">编辑</button>
                    <button class="text-btn danger" type="button" :data-model-delete="model.id" @click="$emit('delete-model', model.id)">删除</button>
                  </div>
                </div>
                <div v-if="!filteredSelectedProviderModels.length" class="model-empty">
                  <div>
                    <strong>{{ modelQuery ? '没有匹配的模型' : '该供应商下还没有模型' }}</strong>
                    <span>{{ modelQuery ? '换个关键词试试' : `为 ${selectedProvider.name || selectedProvider.id} 添加第一个模型` }}</span>
                  </div>
                  <button v-if="!modelQuery" class="small-btn quiet" type="button" @click="startSelectedModelCreate">新增模型</button>
                </div>
              </div>
            </section>
          </section>

          <section v-else-if="catalogView === 'group' && selectedModelGroup" class="provider-detail" aria-label="模型组详情">
            <header class="provider-detail-head">
              <div class="provider-detail-identity">
                <span class="provider-detail-context">当前模型组</span>
                <div class="provider-name-line"><h2>{{ selectedModelGroup.name }}</h2></div>
                <div class="provider-meta"><span>{{ selectedGroupModels.length }} 个模型，可来自多个供应商</span></div>
              </div>
              <div class="provider-head-actions">
                <button class="text-btn" type="button" :data-model-group-edit="selectedModelGroup.id" @click="startModelGroupUpdate(selectedModelGroup)">重命名</button>
                <button class="text-btn danger" type="button" :data-model-group-delete="selectedModelGroup.id" @click="$emit('delete-model-group', selectedModelGroup.id)">删除组</button>
              </div>
            </header>
            <section class="model-section">
              <header class="model-section-head">
                <div class="model-section-title">
                  <h2>模型</h2><span>{{ selectedGroupModels.length }} 个模型</span>
                </div>
                <div class="model-section-tools">
                  <label class="resource-search model-search">
                    <span class="sr-only">搜索模型</span>
                    <input v-model.trim="modelQuery" type="search" placeholder="搜索模型" />
                  </label>
                  <button class="small-btn quiet" type="button" data-model-group-members @click="startGroupMembersEdit">添加已有模型</button>
                  <button class="small-btn primary" type="button" data-group-model-create @click="startGroupModelCreate">＋ 新增模型</button>
                </div>
              </header>
              <div class="model-list">
                <div v-for="model in filteredSelectedGroupModels" :key="model.id" class="model-row" :class="{ 'is-default': model.is_default }">
                  <div class="model-leading">
                    <div class="model-identity">
                      <div class="model-name-line">
                        <strong>{{ model.display_name || model.model_id || model.id }}</strong>
                        <span v-if="model.is_default" class="model-default-badge">预设首选</span>
                      </div>
                      <span class="model-meta">{{ modelProviderName(model) }} · {{ model.model_id || model.id }}</span>
                    </div>
                  </div>
                  <div class="row-actions">
                    <button v-if="!model.is_default" class="text-btn model-default-btn" type="button" @click="$emit('set-default-model', model.id)">设为预设首选</button>
                    <button class="text-btn" type="button" :data-model-edit="model.id" @click="startModelUpdate(model)">编辑</button>
                    <button class="text-btn danger" type="button" :data-model-group-remove="model.id" @click="removeModelFromSelectedGroup(model.id)">移出组</button>
                  </div>
                </div>
                <div v-if="!filteredSelectedGroupModels.length" class="model-empty">
                  <div>
                    <strong>{{ modelQuery ? '没有匹配的模型' : '该组还没有模型' }}</strong>
                    <span>{{ modelQuery ? '换个关键词试试' : '添加现有模型，或创建一个新模型' }}</span>
                  </div>
                </div>
              </div>
            </section>
          </section>

          <section v-else-if="catalogView === 'provider'" class="models-empty-state models-empty-state--main" aria-label="供应商空状态">
            <div class="models-empty-mark" aria-hidden="true"><span>+</span></div>
            <div class="models-empty-copy">
              <h2>还没有供应商</h2>
              <p>从左侧添加一个模型供应商，开始使用 Sunday。</p>
            </div>
          </section>
          <section v-else class="models-empty-state models-empty-state--main" aria-label="模型组空状态">
            <div class="models-empty-mark" aria-hidden="true"><span>+</span></div>
            <div class="models-empty-copy"><h2>还没有模型组</h2><p>创建一个模型组来整理所有供应商下的模型。</p></div>
            <button class="small-btn primary" type="button" data-model-group-create @click="startModelGroupCreate">新建模型组</button>
          </section>
          </div>
        </div>

        <section v-else class="models-empty-state models-empty-state--full settings-surface" aria-label="供应商空状态">
          <div class="models-empty-mark" aria-hidden="true"><span>＋</span></div>
          <div class="models-empty-copy">
            <h2>还没有供应商</h2>
            <p>添加一个 OpenAI Compatible 或其他模型供应商</p>
          </div>
          <button class="small-btn primary" type="button" data-provider-create @click="startProviderCreate">新增供应商</button>
        </section>
      </section>

      <section v-if="activeSection === 'appearance'" class="settings-panel settings-panel--appearance">
        <header class="settings-title">
          <h1>界面</h1>
          <p>主题和密度只影响当前 Sunday 界面。</p>
        </header>

        <ThemeEditor
          product-name="Sunday"
          content-description="Sunday 工作区"
          :density="density"
          :density-options="densityOptions"
          :content-width="contentWidth"
          :theme-mode="themeMode"
          :effective-theme-mode="effectiveThemeMode"
          :get-stops="getStops"
          :get-angle="getAngle"
          :get-opacity="getOpacity"
          :get-text-color="getTextColor"
          :process-icon-color="theme.processIconColor"
          :presets="presets"
          :theme-preview-style="themePreviewStyle"
          :theme-preview-main-style="themePreviewMainStyle"
          :theme-preview-composer-style="themePreviewComposerStyle"
          :theme-preview-control-style="themePreviewControlStyle"
          @reset-theme="$emit('reset-theme')"
          @apply-preset="(preset) => $emit('apply-preset', preset)"
          @update:theme-mode="(mode) => $emit('update:theme-mode', mode)"
          @update:density="(value) => $emit('update:density', value as CoreSettingsDensity)"
          @update:content-width="(value) => $emit('update:content-width', value)"
          @update:stops="(area: ThemeArea, stops: ThemeStop[]) => $emit('update-stops', area, stops)"
          @update:angle="(area: ThemeArea, angle: number) => $emit('update-angle', area, angle)"
          @update:opacity="(area: ThemeArea, opacity: number) => $emit('update-opacity', area, opacity)"
          @update:text-color="(area: ThemeArea, color: string) => $emit('update-text-color', area, color)"
          @update:process-icon-color="(color: string) => $emit('update-process-icon-color', color)"
          @add-stop="(area) => $emit('add-stop', area)"
          @remove-stop="(area, index) => $emit('remove-stop', area, index)"
          @sort-stops="(area) => $emit('sort-stops', area)"
        />
      </section>

      <section v-if="activeSection === 'loadtools'" class="settings-panel">
        <article v-if="commandShellPlatform === 'windows' || commandShellPlatform === 'linux'" class="setting-card command-shell-card" data-command-shell-card>
          <div class="subhead">
            <span class="muted subhead-title">
              命令行
              <span class="subhead-sub">本机命令工具使用的 shell</span>
            </span>
            <div v-if="commandShellPlatform === 'windows'" class="subhead-actions">
              <button class="text-btn" type="button" :disabled="commandShellLoading || commandShellSaving" data-command-shell-refresh @click="fetchCommandShellSettings">刷新</button>
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
            <span v-if="commandShellSaving" class="muted" role="status">正在保存…</span>
          </div>
          <p v-if="commandShellPlatform === 'windows'" class="hook-meta">自动模式按 WSL → Git Bash → PowerShell 的顺序选择可用 shell；手动选择的 shell 不可用时也会按此顺序回退。</p>
          <p v-else class="hook-meta">Linux 直接运行本机命令，不提供 Windows shell 选择。</p>
          <p v-if="commandShellError" class="skill-error" role="alert" data-command-shell-error>{{ commandShellError }}</p>
        </article>
        <!-- KeepAlive: switching sections must not destroy editor draft
             state (audit 17 S3 — the SettingsShell :key remount used to
             wipe every unsaved draft). -->
        <KeepAlive>
          <CoreLoadToolsEditor :request-rpc="requestRpc || defaultRequestRpc" />
        </KeepAlive>
      </section>

      <section v-if="activeSection === 'permissions'" class="settings-panel permissions-panel">
        <header class="settings-title">
          <h1>权限</h1>
          <p>控制新会话的默认权限；当前任务可以在输入框中临时调整。</p>
        </header>

        <div class="settings-surface permissions-surface">
          <section class="permission-summary" aria-label="当前默认状态">
            <div class="permission-summary-copy">
              <span class="permission-section-label">当前默认状态</span>
              <h2>新会话将从这里开始</h2>
              <p>这些设置只作为新会话的起点，不会静默改变已经运行的任务。</p>
            </div>
            <dl class="permission-summary-metrics">
              <div>
                <dt>权限审批</dt>
                <dd>{{ permissionPresetLabel }}</dd>
              </div>
              <div>
                <dt>文件边界</dt>
                <dd>{{ effectiveAllowAccessOutsideWorkdir ? '允许工作目录外' : '工作目录外需确认' }}</dd>
              </div>
            </dl>
          </section>

          <section class="permission-section">
            <div class="permission-section-heading">
              <div>
                <h2>新会话默认</h2>
                <p>权限审批与输入框保持一致；工具清单由“工具模式”管理。</p>
              </div>
              <span class="permission-section-hint">当前会话可临时切换</span>
            </div>

            <div class="permission-setting-group">
              <div class="permission-setting-copy">
                <strong>权限审批</strong>
                <span>决定工具执行前是否需要你确认。</span>
              </div>
              <div class="permission-choice-grid permission-choice-grid--approval" role="group" aria-label="权限审批">
                <button
                  v-for="option in permissionPresetOptions"
                  :key="option.id"
                  type="button"
                  class="permission-choice"
                  :class="{ 'is-selected': permissionPreset === option.id }"
                  :aria-label="'选择' + option.label"
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
                <h2>安全边界</h2>
                <p>控制文件操作的默认范围；更高风险的规则仍由 Sunday 强制执行。</p>
              </div>
            </div>

            <div class="permission-boundary-row">
              <div class="permission-setting-copy">
                <strong>工作目录外访问</strong>
                <span>{{ permissionPreset === 'full_access' ? '完全访问模式会临时允许访问工作目录之外的路径。' : allowAccessOutsideWorkdir ? '允许读写工作目录之外的路径。' : '工作目录外的读写与命令行访问会先征求你的确认，批准后本次执行。' }}</span>
              </div>
              <button
                type="button"
                class="permission-switch"
                data-allow-outside-workdir
                :class="{ 'is-on': effectiveAllowAccessOutsideWorkdir }"
                :disabled="permissionPreset === 'full_access'"
                aria-label="允许访问工作目录以外"
                :aria-pressed="effectiveAllowAccessOutsideWorkdir ? 'true' : 'false'"
                @click="toggleAllowOutsideWorkdir"
              >
                <span class="permission-switch-track" aria-hidden="true"><span /></span>
                <span>{{ permissionPreset === 'full_access' ? '完全访问已包含' : allowAccessOutsideWorkdir ? '已允许' : '需确认' }}</span>
              </button>
            </div>

            <ul class="permission-safety-list">
              <li><span class="permission-safety-dot" aria-hidden="true" />敏感路径（如 .env、SSH 凭据）写入和编辑仍会阻断。</li>
              <li><span class="permission-safety-dot" aria-hidden="true" />高危命令默认需要运行前确认（自动批准模式除外）。</li>
              <li><span class="permission-safety-dot" aria-hidden="true" />插件与 MCP 的 hard block 不能从此页解除。</li>
            </ul>
          </section>

          <section class="permission-session-note" aria-label="当前会话说明">
            <span class="permission-session-note-mark" aria-hidden="true">i</span>
            <div>
              <strong>当前会话</strong>
              <p>输入框里的“询问 / 自动 / 完全访问”是当前会话的实时状态；切换到自动或完全访问会立即放行待审批操作。</p>
            </div>
          </section>

          <details class="permission-related-settings">
            <summary>
              <span>
                <strong>相关设置</strong>
                <small>逐工具白名单、工具模式与扩展权限分别管理</small>
              </span>
            </summary>
            <div class="permission-related-list">
              <div>
                <strong>工具模式</strong>
                <span>控制模型能看到哪些工具，以及工具在思索 / 执行模式下的暴露方式。</span>
              </div>
              <div>
                <strong>插件与 MCP</strong>
                <span>扩展自身的审批等级与 hard block 由各自的管理入口负责。</span>
              </div>
              <div>
                <strong>高级工具白名单</strong>
                <span><code>access_tools.jsonc</code> 负责逐工具能力边界，不在这里重复配置。</span>
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
          <h1>上下文与记忆</h1>
          <p>全局上下文三件套，对所有项目生效。注入顺序：全局 AGENTS.md（优先级 5）→ 全局 memory.md（15）→ 项目 AGENTS.md / MEMORY.md（10 / 20）；load_context 的 addition/except 全局叠加到每个工作区。</p>
        </header>
        <div class="settings-surface settings-surface--stack">
        <article class="setting-card">
          <div class="subhead">
            <span class="muted subhead-title">
              全局约束
              <span v-if="commandShellPlatform === 'mobile'" class="subhead-sub">AGENTS.md · 移动端全局规则</span>
              <span v-else class="subhead-sub">AGENTS.md · .lam/core/config/</span>
            </span>
            <div class="subhead-actions">
              <button class="text-btn" type="button" :disabled="agentsLoading" @click="fetchGlobalAgentsMd">刷新</button>
              <button class="text-btn" type="button" :disabled="agentsLoading || agentsSaving" @click="saveGlobalAgentsMd">保存</button>
            </div>
          </div>
          <textarea
            v-model="agentsDraft"
            class="guide-editor"
            rows="10"
            spellcheck="false"
            :placeholder="agentsLoading ? '加载中…' : '# 全局约束\n对所有项目生效的指令。项目级 AGENTS.md 会在此基础上叠加…'"
            :disabled="agentsLoading"
          />
          <p v-if="agentsError" class="skill-error" role="alert">{{ agentsError }}</p>
          <p v-if="commandShellPlatform === 'mobile'" class="hook-meta">保存在此设备的应用私有 SQLite 配置中。项目级规则请在「项目设置 → 项目规则」内编辑，两者会相加注入系统提示词。</p>
          <p v-else class="hook-meta">保存到 <code>.lam/core/config/AGENTS.md</code>（统一配置目录）。项目级规则请在「项目设置 → 项目规则」内编辑，两者会相加注入系统提示词。</p>
        </article>

        <article class="setting-card">
          <div class="subhead">
            <span class="muted subhead-title">
              全局记忆
              <span v-if="commandShellPlatform === 'mobile'" class="subhead-sub">memory.md · 移动端全局记忆</span>
              <span v-else class="subhead-sub">memory.md · .lam/core/config/</span>
            </span>
            <div class="subhead-actions">
              <button class="text-btn" type="button" :disabled="memoryLoading" @click="fetchGlobalMemory">刷新</button>
              <button class="text-btn" type="button" :disabled="memoryLoading || memorySaving" @click="saveGlobalMemory">保存</button>
            </div>
          </div>
          <textarea
            v-model="memoryDraft"
            class="guide-editor"
            rows="10"
            spellcheck="false"
            :placeholder="memoryLoading ? '加载中…' : '# 全局记忆\n跨项目长期记忆，以 memory 优先级注入每个会话；工作区 MEMORY.md 会叠加在它之后…'"
            :disabled="memoryLoading"
          />
          <p v-if="memoryError" class="skill-error" role="alert">{{ memoryError }}</p>
          <p v-if="commandShellPlatform === 'mobile'" class="hook-meta">保存在此设备的应用私有 SQLite 配置中，仅供本机移动端工作区使用。</p>
          <p v-else class="hook-meta">保存到 <code>.lam/core/config/memory.md</code>。CLI：<code>core memory get/set</code>。</p>
        </article>

        <article class="setting-card">
          <div class="subhead">
            <span class="muted subhead-title">
              全局上下文加载
              <span v-if="commandShellPlatform === 'mobile'" class="subhead-sub">load_context.jsonc · 移动端全局加载规则</span>
              <span v-else class="subhead-sub">load_context.jsonc · .lam/core/config/</span>
            </span>
            <div class="subhead-actions">
              <button class="text-btn" type="button" :disabled="contextLoading" @click="fetchLoadContext">刷新</button>
              <button class="text-btn" type="button" :disabled="contextLoading || contextSaving" @click="saveLoadContext">保存</button>
            </div>
          </div>

          <div class="lc-block">
            <div class="lc-label">追加加载的文件（addition）</div>
            <div v-for="(item, index) in contextAdditions" :key="index" class="lc-row">
              <input v-model="item.name" class="lc-input lc-name" spellcheck="false" placeholder="文件名（如 TEAM_RULES.md）" :disabled="contextLoading" />
              <input v-model.number="item.priority" type="number" class="lc-input lc-priority" title="注入优先级（越小越靠前）" :disabled="contextLoading" />
              <UiSelect
                :model-value="item.kind"
                :options="lcKindOptions"
                class="lc-kind"
                :disabled="contextLoading"
                aria-label="加载类型"
                @update:model-value="item.kind = $event"
              />
              <button class="text-btn danger" type="button" :disabled="contextSaving" @click="contextAdditions.splice(index, 1)">移除</button>
            </div>
            <button class="small-btn quiet" type="button" :disabled="contextLoading" @click="contextAdditions.push({ name: '', priority: 50, kind: 'system' })">＋ 追加文件</button>
          </div>

          <div class="lc-block">
            <div class="lc-label">排除的默认上下文文件（except）</div>
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
                placeholder="如 AGENTS.md / MEMORY.md"
                :disabled="contextLoading"
                @keydown.enter.prevent="addContextExcept"
              />
              <button class="small-btn quiet" type="button" :disabled="contextLoading || !contextExceptDraft.trim()" @click="addContextExcept">添加</button>
            </div>
          </div>

          <p v-if="contextError" class="skill-error" role="alert">{{ contextError }}</p>
          <p v-if="commandShellPlatform === 'mobile'" class="hook-meta">保存在此设备的应用私有 SQLite 配置中，全局规则叠加到本机工作区。</p>
          <p v-else class="hook-meta">保存到 <code>.lam/core/config/load_context.jsonc</code>，全局叠加到每个工作区（工作区自己的 load_context.jsonc 在其上叠加）。CLI：<code>core load-context get/set</code>。</p>
        </article>

        <article class="setting-card">
          <div class="subhead">
            <span class="muted subhead-title">
              记忆整理
              <span class="subhead-sub">Dreaming · 自动沉淀会话记忆</span>
            </span>
            <div class="subhead-actions">
              <button class="text-btn" type="button" :disabled="dreamingLoading" @click="fetchDreamingSettings">刷新</button>
            </div>
          </div>
          <div class="dream-row">
            <div class="dream-toggle">
          <button
            type="button"
            class="toggle-btn"
            :class="{ 'is-on': dreamingEnabled }"
            :aria-label="'自动记忆整理'"
            :aria-pressed="dreamingEnabled ? 'true' : 'false'"
            :disabled="dreamingSaving"
            @click="toggleDreamingSettings"
          >
            <ToggleRight v-if="dreamingEnabled" :size="16" :stroke-width="1.8" aria-hidden="true" />
            <ToggleLeft v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
          </button>
              <span class="dream-toggle-label">自动记忆整理</span>
            </div>
            <span class="muted">每轮会话结束时自动把值得长期保留的内容蒸馏到工作区 MEMORY.md</span>
          </div>
          <div class="dream-row">
            <label class="dream-min-turns" for="dream-min-turns-input">
              最小触发间隔（轮）
            </label>
            <input
              id="dream-min-turns-input"
              v-model.number="dreamingMinTurns"
              type="number"
              class="lc-input lc-priority"
              min="1"
              max="20"
              :disabled="dreamingLoading"
              @input="markSettingsDirty"
            />
            <button class="small-btn quiet" type="button" :disabled="dreamingLoading || dreamingSaving" @click="saveDreamingSettings">保存</button>
          </div>
          <p v-if="dreamingError" class="skill-error" role="alert">{{ dreamingError }}</p>
          <p v-if="commandShellPlatform === 'mobile'" class="hook-meta">整理后的内容写入当前工作区的 MEMORY.md，下个会话自动加载；短期记忆保存在此设备的应用私有 SQLite 中。</p>
          <p v-else class="hook-meta">内容写入 <code>&lt;workRoot&gt;/MEMORY.md</code>，下个会话自动加载；<code>/dream</code> 命令始终可手动触发；短期记忆存 SQLite（<code>core_memories</code> 表）。CLI：<code>core memory dream show/config</code>。</p>
        </article>

        <article class="setting-card" data-context-compaction-card>
          <div class="subhead">
            <span class="muted subhead-title">
              上下文压缩
              <span class="subhead-sub">保留最近的 Step</span>
            </span>
            <div class="subhead-actions">
              <button
                class="text-btn"
                type="button"
                data-context-compaction-refresh
                :disabled="contextCompactionLoading"
                @click="fetchContextCompactionSettings"
              >刷新</button>
            </div>
          </div>
          <div class="dream-row">
            <label class="dream-min-turns" for="context-compaction-retained-steps-input">
              压缩保留最近 Step 数
            </label>
            <input
              id="context-compaction-retained-steps-input"
              v-model.number="contextCompactionRetainedSteps"
              data-context-compaction-retained-steps
              type="number"
              class="lc-input lc-priority"
              min="0"
              max="100"
              step="1"
              :disabled="contextCompactionLoading"
              @input="markSettingsDirty"
            />
            <button
              class="small-btn quiet"
              type="button"
              data-context-compaction-save
              :disabled="contextCompactionLoading || contextCompactionSaving"
              @click="saveContextCompactionSettings"
            >保存</button>
          </div>
          <p v-if="contextCompactionError" class="skill-error" role="alert">{{ contextCompactionError }}</p>
          <p class="hook-meta">一个 Step 是一次模型响应及其后续工具结果；默认保留 0 个 Step，历史会全部汇总；随后程序会将最新 20 条用户指令原文追加为编号的“Recent user messages”段落。令牌预算不足时较早条目会静默丢弃。</p>
        </article>
        </div>
      </section>

      <section v-if="activeSection === 'subagent'" class="settings-panel">
        <KeepAlive>
          <CoreSubAgentEditor :request-rpc="requestRpc || defaultRequestRpc" :models="models" />
        </KeepAlive>
      </section>

      <section v-if="activeSection === 'about'" class="settings-panel">
        <header class="settings-title">
          <h1>关于与更新</h1>
          <p>当前版本与软件更新（优先读取官网更新清单，官网不可达时回退 GitHub Releases）。</p>
        </header>
        <div class="settings-surface settings-surface--stack">
        <article class="setting-card">
          <h3>版本信息</h3>
          <div class="about-version-row">
            <span>当前版本 <strong data-current-version>{{ updateCurrentVersion }}</strong></span>
            <button class="small-btn quiet" type="button" data-check-updates :disabled="updateStatus === 'checking'" @click="checkForUpdates()">
              {{ updateStatus === 'checking' ? '正在检查…' : '检查更新' }}
            </button>
          </div>
          <p v-if="updateStatus === 'up_to_date' && updateNoInstallerForPlatform" class="about-status" data-update-no-installer>
            已发布 v{{ updateLatestVersion }}，但没有适用于本平台的安装包（可到发布页查看）
          </p>
          <p v-else-if="updateStatus === 'up_to_date'" class="about-status" data-update-up-to-date>
            已是最新版本（v{{ updateLatestVersion }}<template v-if="updateSourceLabel"> · 来源：{{ updateSourceLabel }}</template>）
          </p>
          <p v-else-if="updateStatus === 'check_failed'" class="about-status error" data-update-error>
            检查失败：{{ updateError }}（检查网络后重试）
          </p>
        </article>
        <article v-if="updateStatus === 'update_available'" class="setting-card" data-update-available>
          <h3>发现新版本 v{{ updateLatestVersion }}<span v-if="updateSourceLabel" class="muted"> · 来源：{{ updateSourceLabel }}</span></h3>
          <p v-if="updateReleaseNotes" class="about-notes">{{ updateReleaseNotes }}</p>
          <div class="about-actions">
            <!-- 清单带 sha256 时由宿主下载并校验，再交给平台安装器；没有摘要就退回浏览器下载页。 -->
            <button
              v-if="updateInstallSupported"
              class="small-btn primary"
              type="button"
              data-download-installer
              :disabled="updateInstallState === 'downloading' || updateInstallState === 'installing'"
              @click="downloadInstaller()"
            >{{ updateInstallState === 'downloading' ? (updateInstallProgressLabel || '正在下载…') : updateInstallState === 'downloaded' ? '重新下载' : '下载安装包' }}</button>
            <button
              v-if="updateInstallSupported && updateInstallState === 'downloaded'"
              class="small-btn primary"
              type="button"
              data-run-installer
              @click="runInstaller()"
            >立即安装</button>
            <button
              v-else-if="!updateInstallSupported"
              class="small-btn primary"
              type="button"
              data-download-update
              @click="downloadUpdate()"
            >下载安装包</button>
            <button class="small-btn quiet" type="button" data-open-release-page @click="openUpdateReleasePage">查看发布说明</button>
          </div>
          <p v-if="updateInstallError" class="about-status error" data-install-error>{{ updateInstallError }}</p>
          <p v-else-if="updateInstallMessage" class="about-status" data-install-status>{{ updateInstallMessage }}</p>
          <p v-if="updateInstallState === 'downloading'" class="about-status" data-install-progress>
            {{ updateInstallProgressLabel || '正在下载…' }}
          </p>
          <p v-if="updateInstallSupported" class="muted">
            {{ updateInstallHint || '下载完成后点击「立即安装」。' }}<template v-if="updatePackageSizeLabel">安装包约 {{ updatePackageSizeLabel }}。</template>
          </p>
          <p v-else class="muted">下载完成后请先退出 Sunday，再运行安装包完成升级。</p>
        </article>
        <article class="setting-card">
          <h3>自动检查</h3>
          <div class="dream-row">
            <div class="dream-toggle">
          <button
            type="button"
            class="toggle-btn"
            data-update-auto-check
            :class="{ 'is-on': updateAutoCheck }"
            :aria-label="'启动时自动检查更新'"
            :aria-pressed="updateAutoCheck ? 'true' : 'false'"
            @click="toggleUpdateAutoCheck"
          >
            <ToggleRight v-if="updateAutoCheck" :size="16" :stroke-width="1.8" aria-hidden="true" />
            <ToggleLeft v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
          </button>
              <span class="dream-toggle-label">启动时自动检查更新</span>
            </div>
            <span class="muted">发现新版本时会在顶部显示提示条</span>
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
            <!-- Validation errors must render INSIDE the popover — the outer
                 noticeText sits behind the overlay's dim/blur and was
                 invisible to the user (audit 17 S3). -->
            <p v-if="editorError" class="skill-error editor-error" role="alert">{{ editorError }}</p>
            <form v-if="modelGroupEditor" data-model-group-form class="config-form" @submit.prevent="submitModelGroup">
              <div class="editor-popover-head field-wide">
                <div>
                  <span class="editor-overline">模型组</span>
                  <h3>{{ modelGroupEditor.mode === 'create' ? '新建模型组' : '重命名模型组' }}</h3>
                  <p>模型可同时存在于多个组；删除组不会删除模型。</p>
                </div>
                <button type="button" class="editor-popover-close" @click="modelGroupEditor = null">
                  <X :size="14" :stroke-width="1.8" aria-hidden="true" />
                </button>
              </div>
              <label class="field field-wide">名称
                <input v-model.trim="modelGroupEditor.name" data-model-group-name required maxlength="80" placeholder="例如：Free" />
              </label>
              <div class="editor-actions field-wide">
                <button type="button" class="small-btn quiet" @click="modelGroupEditor = null">取消</button>
                <button class="small-btn primary" type="submit">保存</button>
              </div>
            </form>

            <form v-else-if="groupMembersEditor" data-model-group-members-form class="config-form" @submit.prevent="submitGroupMembers">
              <div class="editor-popover-head field-wide">
                <div>
                  <span class="editor-overline">模型组成员</span>
                  <h3>添加已有模型</h3>
                  <p>选择要放入 {{ selectedModelGroup?.name || '当前组' }} 的模型。</p>
                </div>
                <button type="button" class="editor-popover-close" @click="groupMembersEditor = null">
                  <X :size="14" :stroke-width="1.8" aria-hidden="true" />
                </button>
              </div>
              <div class="group-member-list field-wide">
                <label v-for="model in models" :key="model.id" class="group-member-option">
                  <input v-model="groupMembersEditor.model_ids" type="checkbox" :value="model.id" />
                  <span><strong>{{ model.display_name || model.model_id || model.id }}</strong><small>{{ modelProviderName(model) }}</small></span>
                </label>
                <span v-if="!models.length" class="muted">暂无可添加的模型</span>
              </div>
              <div class="editor-actions field-wide">
                <button type="button" class="small-btn quiet" @click="groupMembersEditor = null">取消</button>
                <button class="small-btn primary" type="submit">保存成员</button>
              </div>
            </form>

            <!-- Provider editor -->
            <form v-else-if="providerEditor" :data-provider-form="providerEditor.mode" class="config-form" @submit.prevent="submitProvider" @input="markSettingsDirty">
              <div class="editor-popover-head field-wide">
                <div>
                  <span class="editor-overline">供应商配置</span>
                  <h3>{{ providerEditor.mode === 'create' ? '新增供应商' : '编辑供应商' }}</h3>
                  <p>{{ providerEditor.mode === 'create' ? '连接一个可用的模型服务。' : '更新连接信息，已有密钥不会被覆盖。' }}</p>
                </div>
                <button type="button" class="editor-popover-close" @click="providerEditor = null">
                  <X :size="14" :stroke-width="1.8" aria-hidden="true" />
                </button>
              </div>
              <section v-if="providerEditor.mode === 'create'" class="editor-section field-wide">
                <div class="editor-section-heading">
                  <strong>快速开始</strong>
                  <span>使用官方模板自动填充连接信息和模型。</span>
                </div>
                <label class="field">官方模板
                  <UiSelect
                    :model-value="providerEditor.preset_id"
                    :options="providerPresetOptions"
                    data-provider-preset
                    placeholder="自定义"
                    aria-label="官方模板"
                    @update:model-value="onProviderPresetChange"
                  />
                </label>
                <div v-if="providerEditor.preset_id" class="preset-summary">
                  <strong>{{ providerEditor.name }}</strong>
                  <span>{{ providerEditor.base_url }} · 将自动添加模板内模型</span>
                  <button
                    v-if="selectedProviderPreset?.apiKeyUrl"
                    class="text-btn"
                    type="button"
                    data-provider-api-key-link
                    @click="openProviderApiKeyPage"
                  >点此申请 API key</button>
                </div>
              </section>

              <section class="editor-section editor-section--grid field-wide">
                <div class="editor-section-heading field-wide">
                  <strong>连接信息</strong>
                  <span>这些信息用于连接模型服务。</span>
                </div>
                <label v-if="providerEditor.mode === 'update' || !providerEditor.preset_id" class="field">名称
                  <input v-model.trim="providerEditor.name" data-provider-name required />
                </label>
                <label v-if="providerEditor.mode === 'update' || !providerEditor.preset_id || selectedProviderPreset?.baseUrlEditable" class="field">服务地址
                  <input v-model.trim="providerEditor.base_url" data-provider-base-url type="url" required />
                </label>
                <label class="field field-wide">API Key
                  <input
                    v-model="providerEditor.api_key"
                    data-provider-api-key
                    type="password"
                    autocomplete="new-password"
                    :required="providerEditor.mode === 'create'"
                    :placeholder="providerEditor.mode === 'update' ? '留空以保留现有密钥' : ''"
                  />
                </label>
              </section>

              <details class="settings-advanced editor-section field-wide">
                <summary>
                  <span>
                    <strong>高级设置</strong>
                    <small>接口类型与适配参数</small>
                  </span>
                </summary>
                <div class="advanced-fields">
                  <label class="field">接口类型
                    <UiSelect
                      :model-value="providerEditor.api_type"
                      :options="apiTypeOptions"
                      data-provider-api-type
                      direction="up"
                      aria-label="接口类型"
                      @update:model-value="providerEditor!.api_type = $event"
                    />
                  </label>
                  <label class="field field-wide">高级适配 JSON
                    <textarea v-model="providerEditor.extra_json" rows="5" spellcheck="false" placeholder="{}"></textarea>
                  </label>
                </div>
              </details>
              <div class="editor-actions field-wide">
                <button type="button" class="small-btn quiet" @click="providerEditor = null">取消</button>
                <button class="small-btn primary" type="submit">{{ providerEditor.mode === 'create' ? '添加供应商' : '保存供应商' }}</button>
              </div>
            </form>

            <!-- Model editor -->
            <form v-else-if="modelEditor" :data-model-form="modelEditor.mode" class="config-form model-editor-form" @submit.prevent="submitModel" @input="markSettingsDirty">
              <div class="editor-popover-head field-wide">
                <div>
                  <span class="editor-overline">模型配置</span>
                  <h3>{{ modelEditor.mode === 'create' ? '新增模型' : '编辑模型' }}</h3>
                  <p>{{ modelEditor.mode === 'create' ? '为供应商添加一个可调用的模型。' : '更新模型标识、能力和运行参数。' }}</p>
                </div>
                <button type="button" class="editor-popover-close" @click="modelEditor = null">
                  <X :size="14" :stroke-width="1.8" aria-hidden="true" />
                </button>
              </div>
              <section class="editor-section model-editor-basics field-wide">
                <div class="model-editor-provider">
                  <span>{{ modelEditor.origin_group_id ? '供应商' : '添加到' }}</span>
                  <UiSelect
                    :model-value="modelEditor.provider_id"
                    :options="modelEditor.origin_group_id ? groupModelProviderOptions : providerOptions"
                    data-model-provider-id
                    aria-label="供应商"
                    @update:model-value="onModelProviderChange"
                  />
                </div>
                <template v-if="modelEditor.origin_group_id">
                  <label class="field field-wide">API 基础 URL
                    <input v-model.trim="modelEditor.base_url" data-model-base-url type="url" required placeholder="https://api.example.com/v1" />
                    <small v-if="modelEditor.provider_mode === 'existing'">必须与所选供应商的 API 基础 URL 一致。</small>
                  </label>
                  <div v-if="modelEditor.provider_mode === 'new'" class="model-editor-secondary field-wide">
                    <label class="field">供应商名称
                      <input v-model.trim="modelEditor.new_provider_name" data-model-new-provider-name required placeholder="例如：我的供应商" />
                    </label>
                    <label class="field">接口类型
                      <UiSelect
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
                <label class="field model-editor-id">模型 ID
                  <input v-model.trim="modelEditor.model_id" data-model-id required placeholder="例如 deepseek-v4-flash" />
                  <small>向供应商 API 发送的模型标识。</small>
                </label>
                <div class="model-editor-secondary">
                  <label class="field">显示名称
                    <input v-model.trim="modelEditor.display_name" data-model-display-name placeholder="选填，留空时使用模型 ID" />
                  </label>
                  <label class="field">备注
                    <textarea v-model.trim="modelEditor.notes" rows="2" spellcheck="false" placeholder="选填，如限速、用途、注意事项等"></textarea>
                  </label>
                </div>
              </section>
              <section class="editor-section model-editor-capabilities field-wide">
                <div class="editor-section-heading">
                  <strong>能力</strong>
                  <span>决定模型是否接收图片，以及是否启用推理参数。</span>
                </div>
                <div class="model-editor-capability-controls">
                  <label class="field">能力分类
                    <UiSelect
                      :model-value="modelEditor.capability ?? ''"
                      :options="capabilityOptions"
                      direction="up"
                      aria-label="能力分类"
                      @update:model-value="modelEditor!.capability = $event ?? ''"
                    />
                  </label>
                  <div class="model-reasoning-control">
                    <div>
                      <strong>支持推理</strong>
                      <span>启用推理预算</span>
                    </div>
                    <button
                      type="button"
                      class="toggle-btn"
                      :class="{ 'is-on': modelEditor.thinking_supported }"
                      aria-label="支持推理"
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
                    <strong>运行与适配</strong>
                    <small>上下文、输出、Temperature 与高级适配</small>
                  </span>
                </summary>
                <div class="advanced-fields model-advanced-fields">
                  <label class="field">上下文窗口
                    <input v-model.number="modelEditor.context_window" type="number" min="1" />
                  </label>
                  <label class="field">最大输出
                    <input v-model.number="modelEditor.max_output_tokens" type="number" min="1" />
                  </label>
                  <label class="field">Temperature
                    <input v-model.number="modelEditor.temperature" type="number" min="0" max="2" step="0.1" />
                  </label>
                  <label class="field">推理预算
                    <input v-model.number="modelEditor.thinking_budget" type="number" min="0" />
                  </label>
                  <label class="field field-wide">高级适配 JSON
                    <textarea v-model="modelEditor.extra_json" rows="5" spellcheck="false" placeholder="{}"></textarea>
                  </label>
                </div>
              </details>
              <div class="editor-actions field-wide">
                <button type="button" class="small-btn quiet" @click="modelEditor = null">取消</button>
                <button class="small-btn primary" type="submit">{{ modelEditor.mode === 'create' ? '添加模型' : '保存模型' }}</button>
              </div>
            </form>
          </div>
        </div>
      </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useOutsidePointerDismiss } from '../composables/useOutsidePointerDismiss'
import { ToggleLeft, ToggleRight, X } from 'lucide-vue-next'
import { PROVIDER_PRESETS, PROVIDER_PRESET_GROUP_LABELS, providerPresetModelExtra } from '../data/provider-presets'
import { THEME_PRESETS } from '../data/theme-presets'
import {
  CORE_PERMISSION_PRESET_DESCRIPTIONS,
  CORE_PERMISSION_PRESET_LABELS,
  type CoreModelCatalogView,
  type CorePermissionPreset,
} from '../composer/execution'
import {
  gradientFromStops,
  relativeLuminance,
  type ThemeArea,
  type ThemeData,
  type ThemeMode,
  type ThemePreset,
  type ThemeStop,
} from '../helpers/theme'
import { openUpdatePage } from '../helpers/update'
import { openExternalUrl } from '../helpers/openUrl'
import SettingsShell, { type SettingsSection } from './SettingsShell.vue'
import ThemeEditor from './ThemeEditor.vue'
import CoreSubAgentEditor from './CoreSubAgentEditor.vue'
import CoreLoadToolsEditor from './CoreLoadToolsEditor.vue'
import MobileControlPanel, {
  type MobileControlAccountDevice,
  type MobileControlAccountPayload,
  type MobileControlAccountStatus,
  type MobileControlGatewayStatus,
  type MobileControlIdentity,
  type MobileControlPairing,
} from './MobileControlPanel.vue'
import UiSelect from './UiSelect.vue'
import CoreModelCatalogViewToggle from './CoreModelCatalogViewToggle.vue'
import {
  readUpdateAutoCheck,
  setUpdateAutoCheck,
  useCoreUpdateState,
  type CoreUpdateState,
} from '../composables'

export type CoreSettingsDensity = 'compact' | 'standard' | 'loose'

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
  density: CoreSettingsDensity
  theme: ThemeData
  contentWidth?: number
  themeMode?: ThemeMode
  effectiveThemeMode?: 'light' | 'dark'
  allowEnvironmentImport?: boolean
  commandShellPlatform?: 'windows' | 'linux' | 'mobile' | 'web' | 'other'
  permissionPreset?: CorePermissionPreset
  allowAccessOutsideWorkdir?: boolean
  requestRpc?: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
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
  'update:density': [density: CoreSettingsDensity]
  'update:content-width': [width: number]
  'update:theme-mode': [mode: ThemeMode]
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

const sections: SettingsSection[] = [
  { id: 'models', label: '模型与供应商', icon: 'database' },
  { id: 'appearance', label: '界面', icon: 'palette' },
  { id: 'loadtools', label: '工具模式', icon: 'list-checks' },
  { id: 'permissions', label: '权限', icon: 'lock' },
  { id: 'mobile-control', label: '手机控制', icon: 'smartphone' },
  { id: 'agents', label: '上下文与记忆', icon: 'file-code' },
  { id: 'subagent', label: 'Sub agent', icon: 'bot' },
  { id: 'about', label: '关于与更新', icon: 'info' },
]

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
  { value: 'compact', label: '紧凑' },
  { value: 'standard', label: '标准' },
  { value: 'loose', label: '宽松' },
]

type CommandShellPreference = 'auto' | 'wsl' | 'git-bash' | 'powershell'
const commandShellOptions = [
  { value: 'auto', label: '自动' },
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
// ── Global AGENTS.md (项目规则) editor state ──
const agentsDraft = ref('')
const agentsLoading = ref(false)
const agentsSaving = ref(false)
const agentsError = ref('')

async function fetchGlobalAgentsMd() {
  const rpc = props.requestRpc || defaultRequestRpc
  agentsLoading.value = true
  agentsError.value = ''
  try {
    const result = await rpc('config.agents_md.get')
    const agentsMd = result.agents_md as { content?: string; exists?: boolean } | undefined
    agentsDraft.value = agentsMd?.content ?? ''
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
    await rpc('config.agents_md.set', { content: agentsDraft.value })
    await fetchGlobalAgentsMd()
  } catch (e) {
    agentsError.value = e instanceof Error ? e.message : String(e)
  } finally {
    agentsSaving.value = false
  }
}

// ── Global memory.md (上下文与记忆) editor state ──
const memoryDraft = ref('')
const memoryLoading = ref(false)
const memorySaving = ref(false)
const memoryError = ref('')

async function fetchGlobalMemory() {
  const rpc = props.requestRpc || defaultRequestRpc
  memoryLoading.value = true
  memoryError.value = ''
  try {
    const result = await rpc('config.memory.get')
    memoryDraft.value = String(result.content ?? '')
  } catch (e) {
    memoryError.value = e instanceof Error ? e.message : String(e)
  } finally {
    memoryLoading.value = false
  }
}

async function saveGlobalMemory() {
  const rpc = props.requestRpc || defaultRequestRpc
  memorySaving.value = true
  memoryError.value = ''
  try {
    await rpc('config.memory.set', { content: memoryDraft.value })
    await fetchGlobalMemory()
  } catch (e) {
    memoryError.value = e instanceof Error ? e.message : String(e)
  } finally {
    memorySaving.value = false
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
    await rpc('config.load_context.set', {
      addition: contextAdditions.value
        .filter(item => item.name.trim())
        .map(item => ({ name: item.name.trim(), priority: Number(item.priority) || 50, kind: item.kind })),
      except: contextExcept.value.filter(name => name.trim()),
    })
    await fetchLoadContext()
  } catch (e) {
    contextError.value = e instanceof Error ? e.message : String(e)
  } finally {
    contextSaving.value = false
  }
}

// ── Dreaming settings (记忆整理, app_settings core.dreaming) ──
const dreamingEnabled = ref(false)
const dreamingMinTurns = ref(3)
const dreamingLoading = ref(false)
const dreamingSaving = ref(false)
const dreamingError = ref('')

async function fetchDreamingSettings() {
  const rpc = props.requestRpc || defaultRequestRpc
  dreamingLoading.value = true
  dreamingError.value = ''
  try {
    const result = await rpc('settings.get', { namespace: 'core.dreaming' })
    const value = (result.value ?? {}) as Record<string, unknown>
    dreamingEnabled.value = Boolean(value.enabled)
    const rawTurns = Number(value.min_turns ?? 3)
    dreamingMinTurns.value = Number.isFinite(rawTurns) && rawTurns >= 1 ? Math.floor(rawTurns) : 3
  } catch (e) {
    dreamingError.value = e instanceof Error ? e.message : String(e)
  } finally {
    dreamingLoading.value = false
  }
}

async function saveDreamingSettings() {
  const rpc = props.requestRpc || defaultRequestRpc
  dreamingSaving.value = true
  dreamingError.value = ''
  try {
    // The input is not inside a <form>, so native min/max never fire —
    // enforce the domain here (audit 17 S3).
    const rawTurns = Math.floor(Number(dreamingMinTurns.value))
    const minTurns = Number.isFinite(rawTurns) ? Math.min(20, Math.max(1, rawTurns)) : 3
    dreamingMinTurns.value = minTurns
    await rpc('settings.update', {
      namespace: 'core.dreaming',
      value: { enabled: dreamingEnabled.value, min_turns: minTurns },
    })
    settingsDirty.value = false
    return true
  } catch (e) {
    dreamingError.value = e instanceof Error ? e.message : String(e)
    return false
  } finally {
    dreamingSaving.value = false
  }
}

async function toggleDreamingSettings() {
  const previous = dreamingEnabled.value
  dreamingEnabled.value = !previous
  if (!await saveDreamingSettings()) dreamingEnabled.value = previous
}

// ── Context compaction settings (上下文压缩, core.contextCompaction) ──
const CONTEXT_COMPACTION_DEFAULT_RETAINED_STEPS = 0
const CONTEXT_COMPACTION_MIN_RETAINED_STEPS = 0
const CONTEXT_COMPACTION_MAX_RETAINED_STEPS = 100

const contextCompactionRetainedSteps = ref(CONTEXT_COMPACTION_DEFAULT_RETAINED_STEPS)
const contextCompactionLoading = ref(false)
const contextCompactionSaving = ref(false)
const contextCompactionError = ref('')

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
    // normalize the value before persisting it (the same guard as Dreaming).
    const retainedSteps = normalizeContextCompactionRetainedSteps(contextCompactionRetainedSteps.value)
    contextCompactionRetainedSteps.value = retainedSteps
    await rpc('settings.update', {
      namespace: 'core.contextCompaction',
      value: { retained_steps: retainedSteps },
    })
    settingsDirty.value = false
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
  return apiType || '自定义接口'
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
    || '未关联供应商'
}

// ── UiSelect option lists for provider/model editors ──
const providerPresetOptions = computed(() => [
  { value: '', label: '自定义' },
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
  { value: '', label: '自动（内置声明）' },
  { value: 'text', label: '文本（不支持图片）' },
  { value: 'multimodal', label: '多模态（支持图片）' },
]
const providerOptions = computed(() =>
  props.providers.map(p => ({ value: p.id, label: p.name || p.id })),
)
const groupModelProviderOptions = computed(() => [
  ...providerOptions.value,
  { value: '__new__', label: '＋ 新建供应商' },
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
    '--settings-backdrop-background': gradientFromStops(
      props.theme.backdropAngle,
      props.theme.backdropStops,
      1,
    ),
    '--settings-backdrop-text': props.theme.backdropText,
    '--settings-main-background': gradientFromStops(
      props.theme.mainAngle,
      props.theme.mainStops,
      props.theme.mainOpacity,
    ),
    '--settings-main-text': props.theme.mainText,
    // main 区首停点纯色：卡片实色底（渐变值不可用于 color-mix）
    '--settings-main-solid': props.theme.mainStops[0]?.color || '#111111',
    // 卡片/浮层面板：main 实色 + 文字色 4% 微调，不透明、与内容区有层级
    '--settings-card-background': 'color-mix(in srgb, var(--settings-main-solid) 96%, var(--settings-main-text) 4%)',
    '--settings-card-text': props.theme.mainText,
    '--settings-control-background': gradientFromStops(
      props.theme.controlAngle,
      props.theme.controlStops,
      props.theme.controlOpacity,
    ),
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

const themePreviewStyle = computed(() => ({
  background: gradientFromStops(props.theme.backdropAngle, props.theme.backdropStops, 1),
  color: props.theme.backdropText,
}))
const themePreviewMainStyle = computed(() => ({
  background: gradientFromStops(props.theme.mainAngle, props.theme.mainStops, props.theme.mainOpacity),
  color: props.theme.mainText,
}))
const themePreviewComposerStyle = computed(() => ({
  background: gradientFromStops(props.theme.composerAngle, props.theme.composerStops, props.theme.composerOpacity),
  color: props.theme.composerText,
}))
const themePreviewControlStyle = computed(() => ({
  background: gradientFromStops(props.theme.controlAngle, props.theme.controlStops, props.theme.controlOpacity),
  color: props.theme.controlText,
}))

function modelsForProvider(providerId: string): CoreSettingsModel[] {
  return props.models.filter((model) => model.provider_id === providerId)
}

function startProviderCreate() {
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
}

function startProviderUpdate(provider: CoreSettingsProvider) {
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
}

function submitProvider() {
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
  if (editor.mode === 'create') emit('create-provider', payload)
  else emit('update-provider', payload)
  providerEditor.value = null
  // The parent handles persistence; a submitted editor counts as saved so
  // the close guard does not nag on a clean state (audit 17 S3).
  settingsDirty.value = false
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
    noticeText.value = '请先新增供应商，再添加模型'
    return
  }
  startModelCreateForProvider(provider)
}

function startModelCreateForProvider(provider: CoreSettingsProvider) {
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
}

function startModelGroupCreate() {
  modelGroupEditor.value = { mode: 'create', name: '' }
}

function startModelGroupUpdate(group: CoreSettingsModelGroup) {
  modelGroupEditor.value = { mode: 'update', group_id: group.id, name: group.name }
}

function submitModelGroup() {
  const editor = modelGroupEditor.value
  if (!editor?.name.trim()) return
  if (editor.mode === 'create') emit('create-model-group', { name: editor.name.trim() })
  else emit('update-model-group', { group_id: editor.group_id || '', name: editor.name.trim() })
  modelGroupEditor.value = null
}

function startGroupMembersEdit() {
  const group = selectedModelGroup.value
  if (!group) return
  groupMembersEditor.value = { group_id: group.id, model_ids: [...group.model_ids] }
}

function submitGroupMembers() {
  const editor = groupMembersEditor.value
  if (!editor) return
  emit('set-model-group-members', { group_id: editor.group_id, model_ids: [...new Set(editor.model_ids)] })
  groupMembersEditor.value = null
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
}

function submitModel() {
  const editor = modelEditor.value
  if (!editor) return
  editorError.value = ''
  if (!editor.provider_id) {
    editorError.value = '请先选择供应商'
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
      editorError.value = '按组新增模型时必须填写 API 基础 URL'
      return
    }
    const existingProvider = props.providers.find(item => item.id === editor.provider_id)
    if (
      editor.provider_mode === 'existing'
      && existingProvider?.base_url?.replace(/\/$/, '') !== editor.base_url.replace(/\/$/, '')
    ) {
      editorError.value = 'API 基础 URL 必须与所选供应商一致'
      return
    }
    if (editor.provider_mode === 'new' && (!editor.new_provider_name?.trim() || !editor.new_provider_api_key?.trim())) {
      editorError.value = '新供应商需要填写名称和 API Key'
      return
    }
    emit('create-model-with-provider', {
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
  } else if (editor.mode === 'create') emit('create-model', payload)
  else emit('update-model', payload)
  modelEditor.value = null
  settingsDirty.value = false
}

function parseExtraJson(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
    noticeText.value = ''
    editorError.value = ''
    return parsed as Record<string, unknown>
  } catch {
    editorError.value = '高级适配 JSON 必须是对象'
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

const presets = THEME_PRESETS

// ── Unsaved-changes guard (audit 17 S3) ─────────────────────────
// Any open editor, or a settings form (such as Dreaming or context
// compaction) touched after the last save, makes a close without confirmation
// risky (Esc / backdrop click / header close all discard silently today).
const settingsDirty = ref(false)
const editorOverlayEl = ref<HTMLElement | null>(null)
const editorPopoverEl = ref<HTMLElement | null>(null)


function markSettingsDirty() {
  settingsDirty.value = true
}

function requestCloseSettings() {
  if (settingsDirty.value && !window.confirm('有未保存的修改，确定关闭设置吗？')) return
  emit('close')
}

useOutsidePointerDismiss({
  overlay: editorOverlayEl,
  card: editorPopoverEl,
  isActive: () => Boolean(providerEditor.value || modelEditor.value || modelGroupEditor.value || groupMembersEditor.value),
  onDismiss: closeEditors,
})

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    requestCloseSettings()
  }
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  void fetchGlobalAgentsMd()
  void fetchGlobalMemory()
  void fetchLoadContext()
  void fetchDreamingSettings()
  void fetchContextCompactionSettings()
  void fetchCommandShellSettings()
})
onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
/* ── 上下文与记忆 (global context) editor ── */
.lc-block {
  margin-top: 12px;
}

.lc-label {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
  opacity: 0.85;
}

.lc-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.lc-input {
  padding: 4px 8px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  font-size: 13px;
}

.lc-name {
  flex: 1;
  min-width: 0;
}

.lc-priority {
  width: 84px;
}

.lc-kind {
  width: 110px;
}

/* ── 记忆整理 (Dreaming) card ── */
.dream-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.dream-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.dream-toggle-label {
  font-size: 13px;
  font-weight: 500;
}

.dream-min-turns {
  font-size: 12px;
  color: var(--muted);
  opacity: 0.85;
  min-width: 96px;
}

.lc-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.lc-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 18%, transparent);
  border-radius: 12px;
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
  font-size: 12px;
  font-family: var(--font-mono);
}

.lc-chip-x {
  border: none;
  background: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  padding: 0;
}

/* ── Responsive: full-screen on narrow viewports ── */
@media (max-width: 640px) {
  .settings-card {
    width: 100vw;
    max-height: calc(100dvh - var(--titlebar-offset, 36px));
    border-radius: 0;
  }
}

/* ── Existing settings editor styles ── */
.settings-editor {
  padding: 18px 0;
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 14%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 14%, transparent);
}

.settings-editor h3 {
  margin: 0;
  font-size: 15px;
}

.preset-summary {
  min-width: 0;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
}

.preset-summary strong,
.preset-summary span {
  display: block;
}

.preset-summary strong { font-size: 13px; }
.preset-summary span { margin-top: 3px; color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.settings-advanced {
  margin-top: 2px;
  padding-top: 10px;
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 9%, transparent);
}

.settings-advanced summary {
  width: max-content;
  cursor: pointer;
  color: var(--muted);
  font-size: 13px;
}

.settings-advanced[open] summary { margin-bottom: 12px; color: inherit; }

.advanced-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.model-advanced-fields { grid-template-columns: repeat(3, minmax(0, 1fr)); }

.editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.small-btn.primary {
  background: var(--settings-control-background, #343331);
  color: var(--settings-control-text, var(--text));
}

/* quiet = 文本式按钮（透明底，文字跟随所在 main 面板——不能用 control 文字色，
   否则「亮 main + 暗 control」主题下白字压在浅色面板上不可见） */
.small-btn.quiet {
  background: transparent;
  color: var(--settings-main-text, var(--muted));
}
.small-btn.quiet:hover {
  background: color-mix(in srgb, var(--settings-main-text, var(--text)) var(--alpha-hover), transparent);
  color: var(--settings-main-text, var(--text));
  filter: none;
}

.density-options {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 12%, transparent);
  border-radius: var(--radius-sm);
}

.density-options button {
  min-width: 64px;
  min-height: 32px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--settings-card-text, var(--text));
  font-size: 13px;
}

.density-options button.active {
  background: color-mix(in srgb, var(--settings-main-text, #fff) 14%, transparent);
}

.config-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  align-items: end;
}

.config-form .field {
  display: grid;
  gap: 6px;
  font-size: 13px;
}

.config-form input,
.config-form textarea {
  min-width: 0;
  min-height: 36px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  padding: 0 9px;
}

/* UiSelect 在表单内对齐上面的 control 配方 */
.config-form :deep(.ui-select-trigger) {
  min-height: 36px;
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
}

.lc-row :deep(.ui-select-trigger) {
  min-height: 28px;
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
  font-size: 13px;
}

.config-form textarea {
  min-height: 104px;
  padding: 9px;
  resize: vertical;
}

.config-form .field-wide {
  grid-column: 1 / -1;
}

.permission-list {
  display: grid;
  gap: 12px;
}

.permission-row {
  display: flex;
  flex-direction: column;
  padding: 8px 0;
  border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 50%, transparent);
}

.permission-row:last-child {
  border-bottom: none;
}

.permission-row-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  margin: -4px -10px;
  transition: background 0.12s ease;
}

.permission-row-top:hover {
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
}

.permission-row-top.active {
  background: color-mix(in srgb, var(--green) 10%, transparent);
}

.permission-row-header {
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 14px;
  font-weight: 650;
  text-align: left;
  cursor: inherit;
}

.permission-row-top:hover .permission-row-header {
  color: color-mix(in srgb, var(--blue) 70%, var(--text));
}

.permission-radio {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid color-mix(in srgb, var(--theme-main-text) 45%, transparent);
  background: transparent;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  cursor: default;
}

.permission-radio .permission-radio-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: transparent;
}

.permission-radio.active {
  border-color: var(--green, #4caf50);
}

.permission-radio.active .permission-radio-dot {
  background: var(--green, #4caf50);
}

.permission-radio:hover {
  border-color: color-mix(in srgb, var(--theme-main-text) 70%, transparent);
}

.permission-tools {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 4px 16px;
  padding: 8px 0 4px 0;
}

.permission-tool-row {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
}

.permission-tools-full {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
}

@media (max-width: 720px) {
  .config-form {
    grid-template-columns: 1fr;
  }

  .advanced-fields,
  .model-advanced-fields {
    grid-template-columns: 1fr;
  }

  .permission-tools {
    grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  }
}

.capability-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  background: color-mix(in srgb, var(--settings-main-text, #fff) 10%, transparent);
  color: var(--muted);
}
.capability-badge.multimodal {
  background: color-mix(in srgb, var(--blue, #79bcff) 18%, transparent);
  color: color-mix(in srgb, var(--blue, #79bcff) 80%, var(--text));
}
.capability-badge.text {
  background: color-mix(in srgb, var(--muted) 18%, transparent);
}

/* ── Global AGENTS.md editor ── */
.guide-editor {
  width: 100%;
  min-height: 320px;
  margin-top: 10px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  padding: 9px;
  font-family: var(--font-mono);
  font-size: 13px;
  resize: vertical;
}

.subhead-actions {
  display: flex;
  gap: 6px;
}

.subhead-title {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.subhead-sub {
  font-size: 11px;
  color: color-mix(in srgb, var(--muted) 70%, transparent);
  font-family: var(--font-mono);
  letter-spacing: 0.02em;
}

.hook-meta {
  margin-top: 10px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.skill-error {
  margin: 8px 0 0;
  color: var(--red);
  font-size: 12px;
  line-height: 1.35;
}

/* ── 关于与更新 ── */
.about-version-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.about-status {
  margin: 10px 0 0;
  font-size: 13px;
  color: var(--muted);
}
.about-status.error {
  color: var(--red);
}
.about-notes {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--muted);
  white-space: pre-wrap;
  line-height: 1.5;
  max-height: 160px;
  overflow: auto;
}
.about-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

/* ── 模型与供应商：资源管理页 ── */
.models-panel {
  gap: var(--space-5);
}

.models-title {
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-5);
}

.models-title > .model-catalog-view-toggle {
  flex: 0 0 auto;
}

.group-member-list {
  max-height: min(360px, 52vh);
  overflow-y: auto;
  display: grid;
  gap: var(--space-1);
}

.group-member-option {
  min-height: 42px;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--settings-main-text, var(--theme-main-text));
  cursor: pointer;
}

.group-member-option:hover {
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) var(--alpha-hover), transparent);
}

.group-member-option input {
  flex: 0 0 auto;
}

.group-member-option span {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.group-member-option small {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) 58%, transparent);
}

.models-title-copy {
  min-width: 0;
}

.models-title-copy p {
  max-width: 58ch;
}

.models-header-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--space-2);
}

.models-header-actions .small-btn,
.model-empty .small-btn,
.models-empty-state .small-btn {
  min-height: 36px;
  border-radius: var(--radius-sm);
  padding: 0 var(--space-4);
  font-weight: 650;
}

.models-header-actions .small-btn.quiet {
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 12%, transparent);
}

.models-overview {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 12%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 12%, transparent);
}

.models-stat,
.models-overview-default {
  min-width: 0;
  min-height: 68px;
  padding: var(--space-3) var(--space-4);
  display: grid;
  align-content: center;
  gap: var(--space-1);
}

.models-stat + .models-stat,
.models-overview-default {
  border-left: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
}

.models-stat span,
.models-overview-default span {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 54%, transparent);
  font-size: 11px;
}

.models-stat strong {
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 18px;
  line-height: 1;
}

.models-overview-default {
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  column-gap: var(--space-3);
}

.models-overview-default strong {
  min-width: 0;
  overflow: hidden;
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.models-overview-default .is-unset {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 48%, transparent);
  font-weight: 550;
}

.models-secondary-actions {
  min-width: 0;
  min-height: 28px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 58%, transparent);
  font-size: 12px;
}

.models-secondary-actions > span:first-child {
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-weight: 650;
}

.models-secondary-summary {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.models-secondary-spacer {
  flex: 1 1 auto;
}

.models-secondary-actions .text-btn {
  min-height: 28px;
  padding-inline: var(--space-2);
}

.provider-list {
  display: grid;
  gap: var(--space-4);
  border: 0;
}

.provider-group,
.provider-group + .provider-group {
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 13%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 2%, transparent);
}

.provider-head {
  min-height: 76px;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: var(--space-3);
  padding: var(--space-4);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 4%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
}

.provider-mark {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 15px;
  font-weight: 750;
}

.provider-name-line,
.provider-meta,
.model-name-line,
.model-meta {
  min-width: 0;
  display: flex;
  align-items: center;
}

.provider-name-line {
  gap: var(--space-2);
}

.provider-head strong {
  min-width: 0;
  overflow: hidden;
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-state {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  margin-top: 0;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 52%, transparent);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.provider-state.is-configured {
  color: color-mix(in srgb, var(--green) 76%, var(--settings-main-text, var(--theme-main-text, #fff)));
}

.provider-state-dot {
  width: 6px;
  height: 6px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 42%, transparent);
}

.provider-state.is-configured .provider-state-dot {
  background: var(--green);
}

.provider-meta {
  gap: var(--space-2);
  margin-top: var(--space-1);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 54%, transparent);
  font-size: 12px;
}

.provider-meta > span,
.model-meta > span,
.model-name-line > span {
  display: inline-flex;
  margin-top: 0;
}

.provider-type {
  display: inline-flex;
  flex: 0 0 auto;
  margin-top: 0;
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 72%, transparent);
  font-size: 11px;
  font-weight: 650;
}

.provider-url {
  min-width: 0;
  overflow: hidden;
  font-family: var(--font-mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.model-list {
  display: grid;
}

.model-list-head {
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: 0 var(--space-4);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 48%, transparent);
  font-size: 11px;
  font-weight: 650;
}

.model-list-head span:last-child {
  font-family: var(--font-mono);
  font-weight: 550;
}

.model-list-head-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.model-list-head-actions .model-add-btn {
  min-height: 26px;
  padding-inline: var(--space-2);
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-weight: 650;
}

.model-row {
  min-height: 64px;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
  transition: background var(--dur-fast) var(--ease-out);
}

.model-row:hover {
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) var(--alpha-hover), transparent);
}

.model-leading {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.model-name-line {
  gap: var(--space-2);
}

.model-row strong {
  min-width: 0;
  overflow: hidden;
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-default-badge {
  flex: 0 0 auto;
  padding: 2px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--theme-control-text, #fff)) 24%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--settings-control-text, var(--theme-control-text, #fff)) 74%, transparent);
  font-size: 10px;
  font-weight: 700;
}

.model-meta {
  gap: var(--space-2);
  margin-top: var(--space-1);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 54%, transparent);
  font-size: 12px;
}

.model-id {
  min-width: 0;
  overflow: hidden;
  font-family: var(--font-mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-feature {
  flex: 0 0 auto;
  white-space: nowrap;
}

.model-feature--thinking {
  color: color-mix(in srgb, var(--blue) 72%, var(--settings-main-text, var(--theme-main-text, #fff)));
}

.models-panel .capability-badge {
  flex: 0 0 auto;
  margin-left: 0;
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 62%, transparent);
  font-size: 10px;
  font-weight: 700;
}

.models-panel .capability-badge.multimodal {
  background: color-mix(in srgb, var(--blue) 18%, transparent);
  color: color-mix(in srgb, var(--blue) 82%, var(--settings-main-text, var(--theme-main-text, #fff)));
}

.models-panel .capability-badge.text {
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
}

.model-row .row-actions {
  flex: 0 0 auto;
  gap: var(--space-1);
}

.model-row .text-btn,
.provider-head-actions .text-btn {
  min-height: 30px;
  padding-inline: var(--space-2);
}

.model-default-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.model-empty {
  min-height: 58px;
  margin: 0;
  padding: var(--space-3) var(--space-4) var(--space-3) calc(var(--space-4) + 36px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 52%, transparent);
}

.model-empty > div {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.model-empty strong {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 74%, transparent);
  font-size: 13px;
}

.model-empty span {
  font-size: 12px;
}

.models-empty-state {
  min-height: 176px;
  padding: var(--space-6);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  border: 1px dashed color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 20%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 3%, transparent);
}

.models-empty-mark {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 16%, transparent);
  border-radius: var(--radius-sm);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 64%, transparent);
  font-size: 24px;
  font-weight: 350;
}

.models-empty-copy {
  min-width: 0;
  flex: 1 1 auto;
}

.models-empty-copy h2 {
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 16px;
  line-height: 1.3;
}

.models-empty-copy p {
  margin-top: var(--space-1);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 56%, transparent);
  font-size: 13px;
}

/* ── 供应商 / 模型编辑器 ── */
.editor-popover {
  width: min(600px, 100%);
  padding: var(--space-5);
}

.editor-popover .config-form {
  gap: 0;
}

.editor-popover-head {
  align-items: flex-start;
  margin-bottom: var(--space-2);
}

.editor-overline {
  display: block;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 52%, transparent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .02em;
}

.editor-popover-head h3 {
  margin-top: var(--space-1);
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 18px;
}

.editor-popover-head p {
  margin-top: var(--space-1);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 56%, transparent);
  font-size: 12px;
  line-height: 1.45;
}

.editor-section {
  min-width: 0;
  display: grid;
  gap: var(--space-3);
  padding: var(--space-4) 0;
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
}

.editor-section:first-of-type {
  padding-top: var(--space-3);
  border-top: 0;
}

.editor-section--grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: end;
}

.editor-section-heading {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.editor-section-heading strong {
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 13px;
}

.editor-section-heading span,
.editor-section-heading small {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 50%, transparent);
  font-size: 11px;
  line-height: 1.4;
}

.editor-section-heading small {
  display: block;
  font-size: 11px;
}

.editor-popover .field {
  gap: var(--space-2);
}

.editor-popover .preset-summary {
  padding: var(--space-3);
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 5%, transparent);
}

.editor-popover .settings-advanced {
  margin: 0;
  padding: var(--space-3) 0 0;
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
}

.editor-popover .settings-advanced summary {
  width: 100%;
  min-height: 36px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 4%, transparent);
  list-style: none;
}

.editor-popover .settings-advanced summary::-webkit-details-marker {
  display: none;
}

.editor-popover .settings-advanced summary::after {
  content: '+';
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 54%, transparent);
  font-size: 18px;
  font-weight: 350;
  line-height: 1;
}

.editor-popover .settings-advanced[open] summary::after {
  content: '−';
}

.editor-popover .settings-advanced summary > span {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.editor-popover .settings-advanced summary strong {
  font-size: 13px;
}

.editor-popover .settings-advanced summary small {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 50%, transparent);
  font-size: 11px;
}

.editor-popover .settings-advanced[open] summary {
  margin-bottom: var(--space-3);
}

.editor-popover .advanced-fields {
  gap: var(--space-3);
}

.editor-popover .checkbox-field {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 36px;
}

.editor-actions {
  position: sticky;
  bottom: calc(var(--space-5) * -1);
  z-index: var(--z-main-surface, 20);
  margin-top: var(--space-3);
  padding: var(--space-3) 0 0;
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
  background: var(--settings-card-background, var(--settings-main-background, var(--theme-main-background, #111111)));
}

.editor-actions .small-btn {
  min-height: 36px;
  border-radius: var(--radius-sm);
  padding-inline: var(--space-4);
  font-weight: 650;
}

/* 模型编辑器：让模型 ID 与能力成为主流程，低频参数留在折叠区。 */
.editor-popover--model {
  width: min(680px, 100%);
}

.model-editor-form {
  min-width: 0;
}

.model-editor-basics {
  gap: var(--space-4);
}

.model-editor-provider {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: var(--space-3);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 60%, transparent);
  font-size: 12px;
}

.model-editor-provider > span {
  white-space: nowrap;
}

.model-editor-id {
  gap: var(--space-2);
}

.model-editor-id input {
  font-family: var(--font-mono);
}

.model-editor-id small {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 50%, transparent);
  font-size: 11px;
  line-height: 1.4;
}

.model-editor-secondary {
  min-width: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
  gap: var(--space-3);
}

.model-editor-secondary textarea {
  min-height: calc(var(--space-5) * 3);
}

.model-editor-capabilities {
  gap: var(--space-3);
}

.model-editor-capability-controls {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, .7fr);
  align-items: end;
  gap: var(--space-3);
}

.model-reasoning-control {
  min-height: calc(var(--space-5) * 2 + var(--space-1));
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--theme-control-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-background, var(--theme-control-background, #222)) 70%, transparent);
}

.model-reasoning-control > div {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.model-reasoning-control strong {
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 12px;
}

.model-reasoning-control span {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 50%, transparent);
  font-size: 11px;
  line-height: 1.3;
}

.model-reasoning-control .toggle-btn {
  flex: 0 0 auto;
}

.model-editor-runtime {
  padding-top: var(--space-4) !important;
}

.model-advanced-fields {
  grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
}

@media (max-width: 720px) {
  .models-title {
    align-items: stretch;
    flex-direction: column;
  }

  .models-header-actions {
    justify-content: flex-end;
  }

  .provider-head {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .provider-head-actions {
    grid-column: 2;
    justify-content: flex-start;
  }

  .model-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .model-row .row-actions {
    justify-content: flex-end;
    padding-top: var(--space-2);
    border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
  }

  .editor-section--grid {
    grid-template-columns: 1fr;
  }

  .editor-section--grid .field-wide {
    grid-column: 1;
  }

  .model-editor-secondary,
  .model-editor-capability-controls,
  .model-advanced-fields {
    grid-template-columns: 1fr !important;
  }
}

@media (max-width: 480px) {
  .models-overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .models-overview-default {
    grid-column: 1 / -1;
    grid-template-columns: auto minmax(0, 1fr);
    border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
    border-left: 0;
  }

  .models-secondary-actions {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .models-secondary-spacer {
    display: none;
  }

  .provider-head-actions {
    grid-column: 1 / -1;
    justify-content: flex-end;
  }

  .provider-meta {
    align-items: flex-start;
    flex-direction: column;
    gap: var(--space-1);
  }

  .model-meta {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .model-empty {
    align-items: flex-start;
    flex-direction: column;
    padding-left: var(--space-4);
  }

  .models-empty-state {
    align-items: flex-start;
    flex-wrap: wrap;
    padding: var(--space-5);
  }

  .models-empty-copy {
    flex-basis: calc(100% - 56px);
  }

  .models-empty-state .small-btn {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .model-row {
    transition: none;
  }
}

/* ── 模型与供应商：双栏工作区 ── */
.models-panel {
  width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.models-title {
  flex: 0 0 auto;
  align-items: flex-start;
}

.models-workspace {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(200px, .34fr) minmax(0, 1fr);
  align-items: stretch;
  gap: 0;
  overflow: hidden;
}

.provider-rail {
  position: static;
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: var(--space-4) var(--space-3) var(--space-3);
  border: 0;
  border-right: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 12%, transparent);
  border-radius: 0;
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 2%, transparent);
  overflow: hidden;
}

.provider-rail-head {
  min-height: 36px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: 0 var(--space-1) var(--space-2);
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
}

.provider-rail-title {
  display: inline-flex;
  align-items: baseline;
  gap: var(--space-2);
}

.provider-rail-title strong {
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 13px;
}

.provider-rail-title span,
.provider-rail-status {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 48%, transparent);
  font-size: 11px;
}

.provider-rail-status {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-picker {
  min-height: 0;
  max-height: min(420px, 50vh);
  display: grid;
  align-content: start;
  gap: var(--space-1);
  overflow-y: auto;
  padding-top: var(--space-2);
}

.provider-picker-item {
  width: 100%;
  min-width: 0;
  min-height: 58px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}

.provider-picker-item:hover {
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) var(--alpha-hover), transparent);
}

.provider-picker-item.is-selected {
  border-color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 18%, transparent);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) var(--alpha-active), transparent);
}

.provider-picker-mark {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 78%, transparent);
  font-size: 12px;
  font-weight: 750;
}

.provider-picker-copy {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.provider-picker-copy strong,
.provider-picker-copy span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-picker-copy strong {
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 13px;
  font-weight: 700;
}

.provider-picker-copy span {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 48%, transparent);
  font-size: 11px;
}

.provider-picker-state {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 46%, transparent);
  font-size: 10px;
  white-space: nowrap;
}

.provider-picker-state.is-configured {
  color: color-mix(in srgb, var(--green) 76%, var(--settings-main-text, var(--theme-main-text, #fff)));
}

.provider-picker-state-dot {
  width: 6px;
  height: 6px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 38%, transparent);
}

.provider-picker-state.is-configured .provider-picker-state-dot {
  background: var(--green);
}

.provider-rail-empty {
  min-height: 86px;
  display: grid;
  align-content: center;
  gap: var(--space-1);
  padding: var(--space-3) var(--space-2);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 64%, transparent);
  font-size: 12px;
}

.provider-rail-empty small {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 42%, transparent);
  font-size: 11px;
}

.provider-create-btn {
  width: 100%;
  min-height: 36px;
  margin-top: var(--space-3);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  border: 1px dashed color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 20%, transparent);
  border-radius: var(--radius-sm);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 72%, transparent);
  font-size: 12px;
  font-weight: 650;
  transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.provider-create-btn:hover {
  border-color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 34%, transparent);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) var(--alpha-hover), transparent);
  color: var(--settings-main-text, var(--theme-main-text, #fff));
}

.provider-rail-footer {
  margin-top: auto;
  padding-top: var(--space-2);
  display: grid;
  gap: var(--space-1);
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
}

.provider-rail-footer .text-btn {
  min-height: 28px;
  padding-inline: var(--space-2);
  text-align: left;
}

.provider-detail {
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: grid;
  align-content: start;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-4) var(--space-5) var(--space-5);
  overflow-y: auto;
  overscroll-behavior: contain;
}

.provider-detail-head {
  min-width: 0;
  min-height: 76px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-2) 0 var(--space-4);
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 12%, transparent);
}

.provider-detail-identity {
  min-width: 0;
}

.provider-detail-context {
  display: block;
  margin-bottom: var(--space-1);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 46%, transparent);
  font-size: 11px;
}

.provider-detail-identity h2 {
  min-width: 0;
  overflow: hidden;
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 18px;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-detail-identity .provider-meta {
  margin-top: var(--space-1);
}

.provider-detail-head .provider-head-actions {
  align-self: center;
}

.model-section {
  min-width: 0;
  overflow: visible;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.model-section-head {
  min-width: 0;
  min-height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: 0 0 var(--space-4);
  background: transparent;
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
}

.model-section-title {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.model-section-title h2 {
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 15px;
  line-height: 1.3;
}

.model-section-title span {
  overflow: hidden;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 50%, transparent);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-section-head .small-btn {
  min-height: 36px;
  flex: 0 0 auto;
  border-radius: var(--radius-sm);
  padding-inline: var(--space-4);
  font-weight: 650;
}

.model-section .model-row:first-child {
  border-top: 0;
}

.models-empty-state--main {
  min-height: 0;
  height: 100%;
  align-self: stretch;
  border: 0;
  border-radius: 0;
}

/* The settings main surface is already the card. Keep its chrome; the
   provider/model columns grow with their content and the page scrolls. */
:deep(.settings-main--models) {
  border-radius: var(--radius) var(--radius) 0 0;
}

:deep(.settings-main--models .settings-content) {
  height: auto;
  min-height: 0;
}

@media (max-width: 720px) {
  :deep(.settings-main--models) {
    overflow-y: auto;
  }

  :deep(.settings-main--models .settings-content) {
    height: auto;
  }

  .models-panel {
    height: auto;
  }

  .models-workspace {
    grid-template-columns: 1fr;
    height: auto;
    flex: 0 0 auto;
    overflow: visible;
  }

  .provider-rail {
    position: static;
    min-height: 0;
    height: auto;
    border-right: 0;
    border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 12%, transparent);
    overflow: visible;
  }

  .provider-picker {
    display: flex;
    max-height: none;
    overflow-x: auto;
    overflow-y: hidden;
    padding-bottom: var(--space-1);
  }

  .provider-picker-item {
    flex: 0 0 min(230px, 68vw);
  }

  .provider-rail-footer {
    display: flex;
    flex-wrap: wrap;
  }

  .provider-detail-head {
    grid-template-columns: 1fr;
    gap: var(--space-3);
  }

  .provider-detail {
    height: auto;
    padding: var(--space-4) 0 0;
    overflow: visible;
  }

  .provider-detail-head .provider-head-actions {
    justify-content: flex-end;
  }

  .model-section-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .model-section-head .small-btn {
    align-self: flex-end;
  }
}

@media (max-width: 480px) {
  .provider-picker-item {
    flex-basis: min(236px, calc(100vw - 72px));
  }

  .provider-detail-identity .provider-meta {
    align-items: flex-start;
    flex-direction: column;
    gap: var(--space-1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .provider-picker-item,
  .provider-create-btn {
    transition: none;
  }
}

/* ── 模型与供应商：工作台终稿 ── */
.settings-card {
  width: min(1180px, calc(100vw - (var(--space-6) * 2)));
  height: calc(100dvh - var(--titlebar-offset, 36px) - (var(--space-6) + var(--space-4)));
  border-radius: var(--radius);
}

/* 内容自适应高度：面板不随视口撑满，超出部分交给设置页滚动。
   原先的 height:100% 链会把工作区压成视口剩余高度，下沿把内容裁掉。 */
:deep(.settings-main--models .settings-content) {
  width: min(1180px, 100%);
}

.models-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.models-title {
  flex: 0 0 auto;
  align-items: flex-start;
}

.models-workspace {
  flex: 0 0 auto;
  /* 内容再少也保持一个完整工作面；左栏因此不会被压到需要内部滚动。
     两栏都能收缩：就地渲染后设置栏只有主卡宽，任何固定下限都会在窄窗口
     把右栏顶出容器、被主卡的 overflow 裁掉。 */
  min-height: 420px;
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(180px, 244px) minmax(0, 1fr);
  align-items: stretch;
  gap: 0;
  overflow: hidden;
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
}

.provider-rail {
  position: static;
  min-width: 0;
  height: auto;
  display: flex;
  flex-direction: column;
  padding: var(--space-5) var(--space-4) var(--space-4);
  border: 0;
  border-right: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
  border-radius: 0;
  background: transparent;
  overflow: visible;
}

.provider-rail-head {
  min-height: 36px;
  padding: 0 0 var(--space-2);
}

.provider-picker {
  flex: 0 0 auto;
  min-height: 0;
  max-height: none;
  display: grid;
  align-content: start;
  gap: var(--space-1);
  overflow: visible;
  padding: var(--space-2) 0;
}

.provider-picker-item {
  width: 100%;
  min-width: 0;
  min-height: 64px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}

.provider-picker-item:hover {
  background: color-mix(in srgb, var(--blue) 6%, transparent);
}

.provider-picker-item.is-selected {
  border-color: color-mix(in srgb, var(--blue) 30%, transparent);
  background: color-mix(in srgb, var(--blue) 11%, transparent);
}

.provider-picker-item.is-selected .provider-picker-mark {
  background: color-mix(in srgb, var(--blue) 16%, transparent);
  color: var(--blue);
}

.provider-picker-mark {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
}

.provider-picker-copy {
  gap: var(--space-1);
}

.provider-picker-copy strong {
  font-size: 13px;
}

.provider-picker-copy span {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 54%, transparent);
}

.provider-picker-state {
  font-size: 11px;
}

.provider-rail-footer {
  flex: 0 0 auto;
  margin-top: auto;
  padding-top: var(--space-3);
  display: grid;
  gap: var(--space-3);
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
}

.provider-create-btn {
  width: 100%;
  min-height: 40px;
  margin-top: 0;
  border: 1px dashed color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 24%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 72%, transparent);
}

.provider-create-btn:hover {
  border-color: color-mix(in srgb, var(--blue) 40%, transparent);
  background: color-mix(in srgb, var(--blue) 7%, transparent);
  color: var(--settings-main-text, var(--theme-main-text, #fff));
}

.provider-rail-links {
  display: grid;
  gap: var(--space-1);
}

.provider-rail-links .text-btn {
  min-height: 28px;
  padding-inline: var(--space-2);
  text-align: left;
}

.provider-detail {
  min-width: 0;
  height: auto;
  display: grid;
  align-content: start;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5) var(--space-5);
  overflow: visible;
}

.provider-detail-head {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-4);
  padding: 0 0 var(--space-3);
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 12%, transparent);
}

.provider-detail-context {
  margin-bottom: var(--space-1);
}

.provider-detail-identity h2 {
  font-size: 20px;
  font-weight: 720;
}

.provider-url {
  color: var(--blue);
}

.provider-head-actions .text-btn {
  min-height: 32px;
  padding-inline: var(--space-2);
}

.provider-head-actions .text-btn.danger {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 58%, transparent);
}

.provider-head-actions .text-btn.danger:hover {
  color: var(--red);
}

.model-section {
  min-width: 0;
  overflow: visible;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.model-section-head {
  min-width: 0;
  min-height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: 0 0 var(--space-3);
  background: transparent;
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
}

.model-section-title {
  gap: var(--space-1);
}

.model-section-title h2 {
  font-size: 16px;
}

.model-section-title span {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 58%, transparent);
}

.model-section-head .small-btn {
  min-height: 38px;
  border-radius: var(--radius-sm);
  padding-inline: var(--space-4);
}

.model-list {
  display: grid;
}

.model-row {
  min-height: 72px;
  grid-template-columns: minmax(0, 1fr) auto;
  column-gap: var(--space-3);
  row-gap: var(--space-1);
  padding: var(--space-2) 0;
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
  transition: background var(--dur-fast) var(--ease-out);
}

.model-row:hover {
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) var(--alpha-hover), transparent);
}

.model-leading {
  min-width: 0;
  grid-column: 1;
  grid-row: 1;
  gap: var(--space-2);
}

.model-identity {
  min-width: 0;
}

.model-row strong {
  font-size: 15px;
}

.model-meta {
  margin-top: var(--space-1);
}

.model-capabilities {
  min-width: 0;
  grid-column: 1;
  grid-row: 2;
  display: flex;
  align-items: center;
  align-content: center;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.model-capability {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 66%, transparent);
  font-size: 11px;
  line-height: 1;
}

.model-row .row-actions {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: nowrap;
  gap: var(--space-1);
  grid-column: 2;
  grid-row: 1 / span 2;
  align-self: end;
}

.model-row .text-btn {
  min-height: 32px;
  padding-inline: var(--space-2);
}

.model-empty {
  min-height: 140px;
  padding: var(--space-6) 0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-3);
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
  text-align: center;
}

.model-empty > div {
  text-align: center;
}

.model-empty strong {
  color: var(--settings-main-text, var(--theme-main-text, #fff));
}

.models-empty-state--main,
.models-empty-state--full {
  min-height: 0;
  height: 100%;
  align-self: stretch;
  justify-content: center;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.models-empty-state--full {
  flex: 1 1 auto;
  height: auto;
  display: flex;
  align-items: center;
  gap: var(--space-5);
  padding: var(--space-6);
}

.models-empty-state--full .models-empty-copy {
  flex: 0 1 auto;
}

/* 就地渲染后设置页只剩主卡宽度（窗口 - 左栏 - 设置导航），两栏工作台在
   ~1180 以下就放不下 564px 的下限；低于它改为单栏，而不是被右边缘裁掉。 */
@media (max-width: 1180px) {
  :deep(.settings-main--models .settings-content) {
    width: 100%;
  }

  .models-workspace {
    grid-template-columns: 1fr;
  }

  .provider-rail {
    padding: var(--space-5) 0;
    border-right: 0;
    border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 12%, transparent);
  }

  .provider-rail-footer {
    margin-top: var(--space-4);
  }

  .provider-rail-links {
    display: flex;
    flex-wrap: wrap;
  }

  .provider-detail {
    padding: var(--space-6) 0 0;
  }

  .model-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .model-capabilities {
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .model-row .row-actions {
    grid-column: 2;
    grid-row: 1;
  }
}

@media (max-width: 480px) {
  .settings-card {
    width: calc(100vw - var(--space-6));
  }

  .provider-detail {
    padding-top: var(--space-5);
  }

  .model-row {
    grid-template-columns: 1fr;
    min-height: 0;
  }

  .model-leading,
  .model-capabilities,
  .model-row .row-actions {
    grid-column: 1;
    grid-row: auto;
  }

  .model-row .row-actions {
    justify-content: flex-start;
    padding-top: var(--space-2);
    border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
  }

  .models-empty-state--full {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .models-empty-copy {
    flex-basis: calc(100% - 56px);
  }

  .models-empty-state--full .small-btn {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .model-row,
  .provider-picker-item,
  .provider-create-btn {
    transition: none;
  }
}

/* ── 模型与供应商：密度收敛 ── */
.settings-card {
  width: min(1240px, calc(100vw - (var(--space-6) * 2)));
}

:deep(.settings-main--models .settings-content) {
  width: min(1240px, 100%);
}

.models-title-copy h1 {
  font-size: 20px;
}

.models-title-copy p {
  font-size: 12px;
}

.provider-detail {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  padding: var(--space-4) var(--space-5) var(--space-5);
}

.provider-detail-head {
  flex: 0 0 auto;
  min-height: calc(var(--space-6) * 2 + var(--space-2));
  align-items: start;
}

.provider-detail-identity {
  display: grid;
  align-content: start;
  gap: var(--space-1);
}

.provider-detail-context,
.provider-detail-identity .provider-meta {
  margin-top: 0;
  margin-bottom: 0;
}

.provider-detail-head .provider-head-actions {
  align-self: center;
}

.model-section {
  flex: 0 0 auto;
}

.provider-detail-context {
  font-size: 10px;
}

.provider-detail-identity h2 {
  font-size: 17px;
}

.provider-meta {
  font-size: 11px;
}

.provider-type {
  font-size: 10px;
}

.model-section-title h2 {
  font-size: 14px;
}

.model-section-title span {
  font-size: 10px;
}

.model-row {
  min-height: 72px;
  grid-template-columns: minmax(0, 1fr) auto;
  column-gap: var(--space-3);
  row-gap: var(--space-1);
  padding: var(--space-2) 0;
  position: relative;
  isolation: isolate;
  background: transparent;
  transition: none;
}

.model-row:hover {
  background: transparent;
}

.model-row::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) var(--alpha-hover), transparent);
  -webkit-mask-image:
    linear-gradient(to right, rgb(0 0 0 / 20%), #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgb(0 0 0 / 20%)),
    linear-gradient(to bottom, transparent, #000 10%, #000 90%, transparent);
  -webkit-mask-repeat: no-repeat;
  -webkit-mask-composite: source-in;
  mask-image:
    linear-gradient(to right, rgb(0 0 0 / 20%), #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgb(0 0 0 / 20%)),
    linear-gradient(to bottom, transparent, #000 10%, #000 90%, transparent);
  mask-repeat: no-repeat;
  mask-composite: intersect;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease-out);
}

.model-row:hover::before {
  opacity: 0.32;
}

.model-leading {
  grid-column: 1;
  grid-row: 1;
  position: relative;
  gap: var(--space-2);
}

.model-name-line {
  min-width: 0;
  align-items: flex-start;
  flex-wrap: wrap;
}

.model-name-line strong {
  flex: 1 1 auto;
  min-width: 0;
}

.model-row strong {
  font-size: 14px;
}

.model-id {
  font-size: 11px;
}

.model-capability {
  min-height: 22px;
  padding-inline: var(--space-1);
  font-size: 10px;
}

.model-row .text-btn {
  min-height: 30px;
  padding-inline: var(--space-1);
  font-size: 11px;
}

.model-row .row-actions {
  flex-wrap: nowrap;
  white-space: nowrap;
  grid-column: 2;
  grid-row: 1 / span 2;
  align-self: end;
}

@media (max-width: 980px) {
  .model-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .model-capabilities {
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .model-row .row-actions {
    grid-column: 2;
    grid-row: 1;
  }
}

@media (max-width: 799px) {
  .model-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .model-capabilities {
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .model-row .row-actions {
    grid-column: 2;
    grid-row: 1;
  }

  .provider-detail {
    padding: var(--space-5) 0 0;
  }
}

@media (max-width: 480px) {
  .settings-card {
    width: calc(100vw - var(--space-6));
  }

  .model-row {
    grid-template-columns: 1fr;
    min-height: 0;
  }

  .model-leading,
  .model-capabilities,
  .model-row .row-actions {
    grid-column: 1;
    grid-row: auto;
  }

  .model-row .row-actions {
    justify-content: flex-start;
    padding-top: var(--space-2);
    border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
  }

  .provider-detail {
    padding-top: var(--space-4);
  }
}

@media (prefers-reduced-motion: reduce) {
  .model-row::before {
    transition: none;
  }
}

/* ── 设置页统一主表面 ── */
.models-workspace.settings-surface {
  display: flex;
  flex-direction: column;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius);
  background: var(--settings-card-background, var(--settings-main-background, var(--theme-main-background, #111111)));
}

.models-workspace-body {
  flex: 1 1 auto;
  min-width: 0;
  display: grid;
  grid-template-columns: 260px minmax(420px, 1fr);
  overflow: visible;
}

.resource-search {
  min-width: 0;
  display: block;
}

.resource-search input {
  width: 100%;
  min-width: 0;
  min-height: 34px;
  padding: 0 var(--space-3);
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  outline: 0;
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  font: inherit;
  font-size: 11px;
}

.resource-search input::placeholder {
  color: color-mix(in srgb, var(--theme-composer-text) 48%, transparent);
}

.provider-search {
  flex: 0 0 auto;
  margin: var(--space-2) 0;
}

.provider-picker-item {
  grid-template-columns: minmax(0, 1fr) auto;
}

.provider-picker-mark {
  display: none;
}

.model-section-head {
  min-height: 58px;
}

.model-section-tools {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
}

.model-search {
  width: min(220px, 30vw);
}

@media (max-width: 959px) {
  .models-workspace-body {
    grid-template-columns: 1fr;
    overflow: visible;
  }

  .provider-rail {
    padding: var(--space-4);
  }

  .provider-search {
    width: min(320px, 100%);
  }

  .provider-picker {
    /* 供应商列表整体展示（纵向），滚动交给设置页，左栏不再需要内部滚动。 */
    display: grid;
    max-height: none;
    overflow: visible;
  }

  .provider-picker-item {
    flex: 0 0 auto;
  }

  .provider-detail {
    padding: var(--space-5);
  }
}

@media (max-width: 600px) {
  .provider-detail {
    padding: var(--space-4);
  }

  .model-section-tools {
    align-items: stretch;
    flex-direction: column;
  }

  .model-section-tools .small-btn,
  .model-search {
    width: 100%;
  }

  .model-section-head {
    align-items: stretch;
  }
}

@media (min-width: 960px) and (max-width: 1199px) {
  .models-workspace,
  .models-workspace-body {
    grid-template-columns: 260px minmax(360px, 1fr);
  }
}

.models-empty-state--full.settings-surface {
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius);
  background: var(--settings-card-background, var(--settings-main-background, var(--theme-main-background, #111111)));
}

/* ── 权限：默认值工作面 ── */
.permissions-panel {
  --permission-main-text: var(--settings-main-text, var(--theme-main-text));
  --permission-control-text: var(--settings-control-text, var(--theme-control-text));
  --permission-control-solid: var(--settings-control-solid, var(--panel-2));
  color: var(--permission-main-text);
}

.permissions-surface {
  display: grid;
  gap: 0;
  overflow: hidden;
}

.permission-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 1.15fr);
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-6);
  background: color-mix(in srgb, var(--permission-main-text) 4%, transparent);
}

.permission-summary-copy,
.permission-section-heading,
.permission-setting-copy,
.permission-session-note > div,
.permission-related-list > div {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.permission-section-label,
.permission-section-hint {
  color: color-mix(in srgb, var(--permission-main-text) 52%, transparent);
  font-size: 11px;
}

.permission-summary h2 {
  font-size: 17px;
  font-weight: 720;
  letter-spacing: -.015em;
}

.permission-summary p,
.permission-section-heading p,
.permission-setting-copy span,
.permission-session-note p,
.permission-related-list span {
  color: color-mix(in srgb, var(--permission-main-text) 58%, transparent);
  font-size: 12px;
  line-height: 1.5;
}

.permission-summary-metrics {
  min-width: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.permission-summary-metrics > div {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.permission-summary-metrics dt {
  color: color-mix(in srgb, var(--permission-main-text) 48%, transparent);
  font-size: 10px;
}

.permission-summary-metrics dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--permission-main-text);
  font-size: 12px;
  font-weight: 680;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.permission-section {
  display: grid;
  gap: var(--space-5);
  padding: var(--space-6);
}

.permission-section-heading {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: var(--space-4);
}

.permission-section-heading h2 {
  font-size: 15px;
  font-weight: 720;
}

.permission-section-hint {
  padding-top: 2px;
  text-align: right;
}

.permission-setting-group {
  display: grid;
  grid-template-columns: minmax(150px, .34fr) minmax(0, 1fr);
  align-items: start;
  gap: var(--space-5);
}

.permission-setting-copy {
  padding-top: var(--space-2);
}

.permission-setting-copy strong,
.permission-session-note strong,
.permission-related-list strong {
  color: var(--permission-main-text);
  font-size: 13px;
  font-weight: 680;
}

.permission-choice-grid {
  min-width: 0;
  display: grid;
  gap: var(--space-2);
}

.permission-choice-grid--approval {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  max-width: 620px;
}

.permission-choice {
  position: relative;
  min-width: 0;
  min-height: 96px;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  align-content: start;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid color-mix(in srgb, var(--permission-control-text) 12%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--permission-control-solid) 72%, transparent);
  color: var(--permission-control-text);
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}

.permission-choice:hover {
  background: color-mix(in srgb, var(--permission-control-text) var(--alpha-hover), transparent);
}

.permission-choice:active {
  transform: translateY(1px);
}

.permission-choice.is-selected {
  border-color: color-mix(in srgb, var(--blue) 42%, transparent);
  background: color-mix(in srgb, var(--blue) var(--alpha-active), var(--permission-control-solid));
}

.permission-choice-state {
  width: 20px;
  height: 20px;
  display: inline-grid;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--permission-control-text) 28%, transparent);
  border-radius: 999px;
  color: var(--blue);
  font-size: 12px;
  font-weight: 760;
  line-height: 1;
}

.permission-choice.is-selected .permission-choice-state {
  border-color: color-mix(in srgb, var(--blue) 72%, transparent);
  background: color-mix(in srgb, var(--blue) 18%, transparent);
}

.permission-choice-copy {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.permission-choice-copy strong {
  overflow: hidden;
  color: var(--permission-control-text);
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.permission-choice-copy small {
  color: color-mix(in srgb, var(--permission-control-text) 62%, transparent);
  font-size: 11px;
  line-height: 1.45;
}

.permission-boundary-section {
  padding-top: 0;
}

.permission-boundary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-5);
}

.permission-switch {
  flex: 0 0 auto;
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  color: color-mix(in srgb, var(--permission-main-text) 68%, transparent);
  font-size: 11px;
  white-space: nowrap;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.permission-switch:hover {
  background: color-mix(in srgb, var(--permission-main-text) var(--alpha-hover), transparent);
  color: var(--permission-main-text);
}

.permission-switch:active {
  background: color-mix(in srgb, var(--permission-main-text) var(--alpha-active), transparent);
}

.permission-switch:disabled {
  opacity: .72;
  cursor: default;
}

.permission-switch-track {
  width: 36px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  padding: 2px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--permission-main-text) 16%, transparent);
  transition: background var(--dur-fast) var(--ease-out);
}

.permission-switch-track span {
  width: 16px;
  height: 16px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--permission-main-text) 68%, transparent);
  transform: translateX(0);
  transition: background var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}

.permission-switch.is-on {
  color: var(--blue);
}

.permission-switch.is-on .permission-switch-track {
  background: color-mix(in srgb, var(--blue) 32%, transparent);
}

.permission-switch.is-on .permission-switch-track span {
  background: var(--blue);
  transform: translateX(16px);
}

.permission-safety-list {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
  color: color-mix(in srgb, var(--permission-main-text) 58%, transparent);
  font-size: 11px;
  line-height: 1.5;
}

.permission-safety-list li {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
}

.permission-safety-dot {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
  margin-top: 5px;
  border-radius: 999px;
  background: var(--green);
}

.permission-session-note {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin: 0 var(--space-6) var(--space-5);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--permission-main-text) 5%, transparent);
}

.permission-session-note-mark {
  flex: 0 0 auto;
  width: 18px;
  height: 18px;
  display: inline-grid;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--permission-main-text) 22%, transparent);
  border-radius: 999px;
  color: color-mix(in srgb, var(--permission-main-text) 64%, transparent);
  font-size: 11px;
  font-weight: 700;
}

.permission-session-note p {
  margin-top: var(--space-1);
}

.permission-related-settings {
  margin: 0 var(--space-6) var(--space-6);
  padding-top: var(--space-4);
  border-top: 1px solid color-mix(in srgb, var(--permission-main-text) 9%, transparent);
}

.permission-related-settings summary {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  cursor: pointer;
  list-style: none;
}

.permission-related-settings summary::-webkit-details-marker {
  display: none;
}

.permission-related-settings summary::after {
  content: '⌄';
  color: color-mix(in srgb, var(--permission-main-text) 48%, transparent);
  font-size: 14px;
  transition: transform var(--dur-fast) var(--ease-out);
}

.permission-related-settings[open] summary::after {
  transform: rotate(180deg);
}

.permission-related-settings summary > span,
.permission-related-list {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.permission-related-settings summary strong {
  font-size: 13px;
}

.permission-related-settings summary small {
  color: color-mix(in srgb, var(--permission-main-text) 52%, transparent);
  font-size: 11px;
}

.permission-related-list {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
  padding-top: var(--space-4);
}

.permission-related-list code {
  color: color-mix(in srgb, var(--permission-main-text) 74%, transparent);
  font-family: var(--font-mono);
  font-size: 10px;
}

@media (max-width: 900px) {
  .permission-summary {
    grid-template-columns: 1fr;
    gap: var(--space-4);
  }

  .permission-setting-group {
    grid-template-columns: 1fr;
    gap: var(--space-3);
  }

  .permission-setting-copy {
    padding-top: 0;
  }
}

@media (max-width: 640px) {
  .permission-summary,
  .permission-section {
    padding: var(--space-4);
  }

  .permission-summary-metrics,
  .permission-choice-grid--approval,
  .permission-related-list {
    grid-template-columns: 1fr;
    max-width: none;
  }

  .permission-section-heading {
    grid-template-columns: 1fr;
    gap: var(--space-2);
  }

  .permission-section-hint {
    text-align: left;
  }

  .permission-boundary-row {
    align-items: flex-start;
    flex-direction: column;
    gap: var(--space-3);
  }

  .permission-session-note {
    margin-inline: var(--space-4);
  }

  .permission-related-settings {
    margin-inline: var(--space-4);
  }
}

@media (prefers-reduced-motion: reduce) {
  .permission-choice,
  .permission-switch,
  .permission-switch-track,
  .permission-switch-track span,
  .permission-related-settings summary::after {
    transition: none;
  }
}
</style>
