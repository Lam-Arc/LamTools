<template>
  <Teleport to="body">
    <div
      class="settings-overlay"
      @click.self="requestCloseSettings"
    >
      <div class="settings-card" :style="settingsThemeStyle">
        <SettingsShell
          :sections="sections"
          title="Core 设置"
          :settings-theme-style="settingsThemeStyle"
          @close="requestCloseSettings"
        >
          <template #default="{ activeSection }">
      <section v-if="activeSection === 'models'" class="settings-panel">
        <header class="settings-title">
          <h1>模型与供应商</h1>
          <p>共享 Core 配置。更改会在所有接入 Core 的界面中生效。</p>
        </header>

        <div v-if="noticeText" class="settings-notice">{{ noticeText }}</div>

        <div class="provider-actions">
          <button class="small-btn primary" type="button" data-provider-create @click="startProviderCreate">新增供应商</button>
          <button class="small-btn quiet" type="button" data-model-create @click="startModelCreate">新增模型</button>
          <button v-if="allowEnvironmentImport" class="small-btn quiet" type="button" @click="$emit('import-environment')">从当前环境导入</button>
          <button class="small-btn quiet" type="button" data-reopen-onboarding @click="$emit('reopen-onboarding')">重新显示首次引导</button>
        </div>

        <div v-if="providers.length" class="provider-list">
          <section v-for="provider in providers" :key="provider.id" class="provider-group">
            <header class="provider-head">
              <div class="provider-identity">
                <strong>{{ provider.name || provider.id }}</strong>
                <span>{{ provider.has_api_key ? '已配置密钥' : '未配置密钥' }} · {{ provider.base_url || provider.id }}</span>
              </div>
              <div class="row-actions">
                <button class="text-btn" type="button" :data-provider-edit="provider.id" @click="startProviderUpdate(provider)">编辑</button>
                <button class="text-btn danger" type="button" :data-provider-delete="provider.id" @click="$emit('delete-provider', provider.id)">删除</button>
              </div>
            </header>
            <div class="model-list">
                <div v-for="model in modelsForProvider(provider.id)" :key="model.id" class="model-row">
                  <div class="model-identity">
                    <strong>{{ model.display_name || model.model_id || model.id }}</strong>
                    <span>
                      {{ model.model_id || model.id }}{{ model.thinking_supported ? ' · 支持推理' : '' }}
                      <span v-if="model.capability" class="capability-badge" :class="model.capability">{{ model.capability === 'multimodal' ? '多模态' : '文本' }}</span>
                    </span>
                  </div>
                  <div class="row-actions">
                    <button class="text-btn" :class="{ active: model.is_default }" type="button" :data-model-default="model.id" @click="$emit('set-default-model', model.id)">
                      <Star :size="12" :stroke-width="1.8" :fill="model.is_default ? 'currentColor' : 'none'" aria-hidden="true" /> 默认
                    </button>
                    <button class="text-btn" type="button" :data-model-edit="model.id" @click="startModelUpdate(model)">编辑</button>
                    <button class="text-btn danger" type="button" :data-model-delete="model.id" @click="$emit('delete-model', model.id)">删除</button>
                  </div>
                </div>
                <p v-if="!modelsForProvider(provider.id).length" class="model-empty">暂无模型</p>
            </div>
          </section>
        </div>
        <div v-else class="setting-card">
          <h3>暂无配置</h3>
          <p>Core 配置接口尚未返回可用的供应商或模型。</p>
        </div>
      </section>

      <section v-if="activeSection === 'appearance'" class="settings-panel">
        <header class="settings-title">
          <h1>界面</h1>
          <p>主题和密度只影响当前 Core 界面。</p>
        </header>

        <div class="setting-card">
          <h3>界面密度</h3>
          <div class="density-options" role="group" aria-label="界面密度">
            <button
              v-for="option in densityOptions"
              :key="option.value"
              type="button"
              :data-density="option.value"
              :class="{ active: density === option.value }"
              @click="$emit('update:density', option.value)"
            >{{ option.label }}</button>
          </div>
          <label v-if="contentWidth" class="field">内容宽度
            <input
              :value="contentWidth"
              type="range"
              min="560"
              max="1120"
              step="20"
              @input="$emit('update:content-width', Number(($event.target as HTMLInputElement).value))"
            />
          </label>
        </div>

        <ThemeEditor
          product-name="LamTools Core"
          content-description="Core 工作区"
          :get-stops="getStops"
          :get-angle="getAngle"
          :get-opacity="getOpacity"
          :get-text-color="getTextColor"
          :presets="presets"
          :presets-by-group="presetsByGroup"
          :theme-preview-style="themePreviewStyle"
          :theme-preview-main-style="themePreviewMainStyle"
          :theme-preview-composer-style="themePreviewComposerStyle"
          :theme-preview-control-style="themePreviewControlStyle"
          @reset-theme="$emit('reset-theme')"
          @apply-preset="(preset) => $emit('apply-preset', preset)"
          @update-stops="(area, stops) => $emit('update-stops', area, stops)"
          @update-angle="(area, angle) => $emit('update-angle', area, angle)"
          @update-opacity="(area, opacity) => $emit('update-opacity', area, opacity)"
          @update-text-color="(area, color) => $emit('update-text-color', area, color)"
          @add-stop="(area) => $emit('add-stop', area)"
          @remove-stop="(area, index) => $emit('remove-stop', area, index)"
          @sort-stops="(area) => $emit('sort-stops', area)"
        />
      </section>

      <section v-if="activeSection === 'skills'" class="settings-panel">
        <CoreSkillsEditor :request-rpc="requestRpc || defaultRequestRpc" />
      </section>

      <section v-if="activeSection === 'loadtools'" class="settings-panel">
        <!-- KeepAlive: switching sections must not destroy editor draft
             state (audit 17 S3 — the SettingsShell :key remount used to
             wipe every unsaved draft). -->
        <KeepAlive>
          <CoreLoadToolsEditor :request-rpc="requestRpc || defaultRequestRpc" />
        </KeepAlive>
      </section>

      <section v-if="activeSection === 'imagegen'" class="settings-panel">
        <KeepAlive>
          <CoreImageGenEditor :request-rpc="requestRpc || defaultRequestRpc" />
        </KeepAlive>
      </section>

      <section v-if="activeSection === 'websearch'" class="settings-panel">
        <KeepAlive>
          <CoreWebSearchEditor :request-rpc="requestRpc || defaultRequestRpc" />
        </KeepAlive>
      </section>

      <section v-if="activeSection === 'hooks'" class="settings-panel">
        <KeepAlive>
          <CoreHooksEditor :request-rpc="requestRpc || defaultRequestRpc" />
        </KeepAlive>
      </section>

      <section v-if="activeSection === 'permissions'" class="settings-panel">
        <header class="settings-title">
          <h1>权限策略</h1>
        </header>
        <article class="setting-card">
          <h3>放行模式</h3>
          <div class="permission-list">
            <div v-for="tier in permissionTiers" :key="tier.id" class="permission-row">
              <div class="permission-row-top" :class="{ active: permissionMode === tier.id }" @click="$emit('update-permission-mode', tier.id)" role="button" tabindex="0" :aria-pressed="permissionMode === tier.id ? 'true' : 'false'" :aria-label="'选择' + tier.label" @keydown.enter.prevent="$emit('update-permission-mode', tier.id)" @keydown.space.prevent="$emit('update-permission-mode', tier.id)">
                <button type="button" class="permission-row-header" @click.stop="expandedTier = expandedTier === tier.id ? null : tier.id">
                  {{ tier.label }}
                </button>
                <span class="permission-radio" :class="{ active: permissionMode === tier.id }" aria-hidden="true">
                  <span class="permission-radio-dot" />
                </span>
              </div>
              <div v-if="expandedTier === tier.id" class="permission-tools">
                <template v-if="tier.id === 'full_edit'">
                  <p class="permission-tools-full">完全放行</p>
                </template>
                <template v-else>
                  <div v-for="tool in tier.tools" :key="tool" class="permission-tool-row">{{ tool }}</div>
                </template>
              </div>
            </div>
          </div>
        </article>
        <article class="setting-card">
          <h3>工作目录访问</h3>
          <div class="dream-row">
            <label class="dream-toggle">
              <input
                type="checkbox"
                data-allow-outside-workdir
                :checked="allowAccessOutsideWorkdir"
                @change="toggleAllowOutsideWorkdir"
              />
              <span class="dream-toggle-label">允许访问工作目录以外</span>
            </label>
            <span class="muted">开启后 Agent 可读写工作目录之外的任意路径（敏感文件仍受拦截）</span>
          </div>
        </article>
      </section>

      <section v-if="activeSection === 'agents'" class="settings-panel">
        <header class="settings-title">
          <h1>上下文与记忆</h1>
          <p>全局上下文三件套，对所有项目生效。注入顺序：全局 AGENTS.md（优先级 5）→ 全局 memory.md（15）→ 项目 AGENTS.md / MEMORY.md（10 / 20）；load_context 的 addition/except 全局叠加到每个工作区。</p>
        </header>
        <article class="setting-card">
          <div class="subhead">
            <span class="muted subhead-title">
              全局约束
              <span class="subhead-sub">AGENTS.md · .lam/core/config/</span>
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
          <p class="hook-meta">保存到 <code>.lam/core/config/AGENTS.md</code>（统一配置目录）。项目级规则请在「项目设置 → 项目规则」内编辑，两者会相加注入系统提示词。</p>
        </article>

        <article class="setting-card">
          <div class="subhead">
            <span class="muted subhead-title">
              全局记忆
              <span class="subhead-sub">memory.md · .lam/core/config/</span>
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
          <p class="hook-meta">保存到 <code>.lam/core/config/memory.md</code>。CLI：<code>core memory get/set</code>。</p>
        </article>

        <article class="setting-card">
          <div class="subhead">
            <span class="muted subhead-title">
              全局上下文加载
              <span class="subhead-sub">load_context.jsonc · .lam/core/config/</span>
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
          <p class="hook-meta">保存到 <code>.lam/core/config/load_context.jsonc</code>，全局叠加到每个工作区（工作区自己的 load_context.jsonc 在其上叠加）。CLI：<code>core load-context get/set</code>。</p>
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
            <label class="dream-toggle">
              <input v-model="dreamingEnabled" type="checkbox" :disabled="dreamingLoading" @change="saveDreamingSettings" />
              <span class="dream-toggle-label">自动记忆整理</span>
            </label>
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
          <p class="hook-meta">内容写入 <code>&lt;workRoot&gt;/MEMORY.md</code>，下个会话自动加载；<code>/dream</code> 命令始终可手动触发；短期记忆存 SQLite（<code>core_memories</code> 表）。CLI：<code>core memory dream show/config</code>。</p>
        </article>
      </section>

      <section v-if="activeSection === 'workflow'" class="settings-panel">
        <header class="settings-title">
          <h1>工作流</h1>
          <p class="settings-subhead">管理与创建 Workflow，并控制是否暴露为 Agent 工具。</p>
        </header>
        <article class="setting-card">
          <div class="subhead">
            <h3>已创建的工作流</h3>
            <div class="subhead-actions">
              <button class="small-btn" type="button" @click="refreshWorkflowList">
                <RefreshCw :size="13" :stroke-width="1.8" aria-hidden="true" /> 刷新
              </button>
            </div>
          </div>
          <div v-if="workflowListLoading" class="model-empty">加载中…</div>
          <div v-else-if="workflowList.length" class="provider-list">
            <div v-for="wf in workflowList" :key="wf.name" class="provider-group">
              <div class="provider-head">
                <strong>{{ wf.name }}</strong>
                <span v-if="wf.exposed" class="tool-status ok">已暴露</span>
                <span v-else class="tool-status">未暴露</span>
                <div class="row-actions">
                  <button
                    type="button"
                    class="text-btn"
                    :class="{ 'is-on': wf.exposed }"
                    @click="$emit('toggle-workflow-exposed', wf.name, !wf.exposed)"
                  >{{ wf.exposed ? '取消暴露' : '暴露为工具' }}</button>
                </div>
              </div>
              <div class="model-list">
                <div class="model-row">
                  <div class="model-identity">
                    <span>{{ wf.nodes.length }} 个节点 · {{ wf.edges.length }} 条连线</span>
                    <span v-if="wf.description" class="hook-meta">{{ wf.description }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <p v-else class="model-empty">暂无工作流。在侧栏点击「工作流」进入画布模式创建。</p>
        </article>
      </section>

      <section v-if="activeSection === 'subagent'" class="settings-panel">
        <KeepAlive>
          <CoreSubAgentEditor :request-rpc="requestRpc || defaultRequestRpc" :models="models" />
        </KeepAlive>
      </section>

      <section v-if="activeSection === 'about'" class="settings-panel">
        <header class="settings-title">
          <h1>关于与更新</h1>
          <p>当前版本与软件更新（更新源：GitHub Releases）。</p>
        </header>
        <article class="setting-card">
          <h3>版本信息</h3>
          <div class="about-version-row">
            <span>当前版本 <strong data-current-version>{{ updateCurrentVersion }}</strong></span>
            <button class="small-btn quiet" type="button" data-check-updates :disabled="updateStatus === 'checking'" @click="checkForUpdates()">
              {{ updateStatus === 'checking' ? '正在检查…' : '检查更新' }}
            </button>
          </div>
          <p v-if="updateStatus === 'up_to_date'" class="about-status" data-update-up-to-date>
            已是最新版本（v{{ updateLatestVersion }}）
          </p>
          <p v-else-if="updateStatus === 'check_failed'" class="about-status error" data-update-error>
            检查失败：{{ updateError }}（检查网络后重试）
          </p>
        </article>
        <article v-if="updateStatus === 'update_available'" class="setting-card" data-update-available>
          <h3>发现新版本 v{{ updateLatestVersion }}</h3>
          <p v-if="updateReleaseNotes" class="about-notes">{{ updateReleaseNotes }}</p>
          <div class="about-actions">
            <button class="small-btn primary" type="button" data-download-update @click="downloadUpdate()">下载安装包</button>
            <button class="small-btn quiet" type="button" data-open-release-page @click="openUpdateReleasePage">查看发布说明</button>
          </div>
          <p class="muted">下载完成后请先退出 LamCore，再运行安装包完成升级。</p>
        </article>
        <article class="setting-card">
          <h3>自动检查</h3>
          <div class="dream-row">
            <label class="dream-toggle">
              <input
                type="checkbox"
                data-update-auto-check
                :checked="updateAutoCheck"
                @change="toggleUpdateAutoCheck"
              />
              <span class="dream-toggle-label">启动时自动检查更新</span>
            </label>
            <span class="muted">发现新版本时会在顶部显示提示条</span>
          </div>
        </article>
      </section>
    </template>
  </SettingsShell>

      <!-- Floating editor overlay for provider/model edit forms.
           内联渲染即可：Teleport 目标是自身祖先（settings-card），传送等同原地；
           且 ref+Teleport 组合在测试环境（Teleport stub）会触发渲染递归。 -->
      <div v-if="providerEditor || modelEditor" class="editor-overlay" @click.self="closeEditors">
          <div class="editor-popover">
            <!-- Validation errors must render INSIDE the popover — the outer
                 noticeText sits behind the overlay's dim/blur and was
                 invisible to the user (audit 17 S3). -->
            <p v-if="editorError" class="skill-error editor-error" role="alert">{{ editorError }}</p>
            <!-- Provider editor -->
            <form v-if="providerEditor" :data-provider-form="providerEditor.mode" class="config-form" @submit.prevent="submitProvider" @input="markSettingsDirty">
              <div class="editor-popover-head">
                <h3>{{ providerEditor.mode === 'create' ? '新增供应商' : '编辑供应商' }}</h3>
                <button type="button" class="editor-popover-close" @click="providerEditor = null">
                  <X :size="14" :stroke-width="1.8" aria-hidden="true" />
                </button>
              </div>
              <label v-if="providerEditor.mode === 'create'" class="field">官方模板
                <UiSelect
                  :model-value="providerEditor.preset_id"
                  :options="providerPresetOptions"
                  placeholder="自定义"
                  aria-label="官方模板"
                  @update:model-value="onProviderPresetChange"
                />
              </label>
              <div v-if="providerEditor.preset_id" class="preset-summary field-wide">
                <strong>{{ providerEditor.name }}</strong>
                <span>{{ providerEditor.base_url }} · 将自动添加模板内模型</span>
              </div>
              <label v-if="providerEditor.mode === 'update' || !providerEditor.preset_id" class="field">名称
                <input v-model.trim="providerEditor.name" data-provider-name required />
              </label>
              <label v-if="providerEditor.mode === 'update' || !providerEditor.preset_id" class="field">服务地址
                <input v-model.trim="providerEditor.base_url" data-provider-base-url type="url" required />
              </label>
              <label class="field">API Key
                <input
                  v-model="providerEditor.api_key"
                  data-provider-api-key
                  type="password"
                  autocomplete="new-password"
                  :required="providerEditor.mode === 'create'"
                  :placeholder="providerEditor.mode === 'update' ? '留空以保留现有密钥' : ''"
                />
              </label>
              <details class="settings-advanced field-wide">
                <summary>高级设置</summary>
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
            <form v-if="modelEditor" :data-model-form="modelEditor.mode" class="config-form" @submit.prevent="submitModel" @input="markSettingsDirty">
              <div class="editor-popover-head">
                <h3>{{ modelEditor.mode === 'create' ? '新增模型' : '编辑模型' }}</h3>
                <button type="button" class="editor-popover-close" @click="modelEditor = null">
                  <X :size="14" :stroke-width="1.8" aria-hidden="true" />
                </button>
              </div>
              <label class="field">供应商
                <UiSelect
                  :model-value="modelEditor.provider_id"
                  :options="providerOptions"
                  data-model-provider-id
                  aria-label="供应商"
                  @update:model-value="modelEditor!.provider_id = $event"
                />
              </label>
              <label class="field">模型标识
                <input v-model.trim="modelEditor.model_id" data-model-id required />
              </label>
              <label class="field">显示名称
                <input v-model.trim="modelEditor.display_name" data-model-display-name placeholder="选填" />
              </label>
              <label class="field field-wide">备注
                <textarea v-model.trim="modelEditor.notes" rows="2" spellcheck="false" placeholder="选填，如限速、用途、注意事项等"></textarea>
              </label>
              <details class="settings-advanced field-wide">
                <summary>高级参数</summary>
                <div class="advanced-fields model-advanced-fields">
                  <label class="field">上下文窗口
                    <input v-model.number="modelEditor.context_window" type="number" min="1" />
                  </label>
                  <label class="field">最大输出
                    <input v-model.number="modelEditor.max_output_tokens" type="number" min="1" />
                  </label>
                  <label class="field">推理预算
                    <input v-model.number="modelEditor.thinking_budget" type="number" min="0" />
                  </label>
                  <label class="field">Temperature
                    <input v-model.number="modelEditor.temperature" type="number" min="0" max="2" step="0.1" />
                  </label>
                  <label class="field checkbox-field">
                    <input v-model="modelEditor.thinking_supported" type="checkbox" /> 支持推理
                  </label>
                  <label class="field">能力分类
                    <UiSelect
                      :model-value="modelEditor.capability ?? ''"
                      :options="capabilityOptions"
                      direction="up"
                      aria-label="能力分类"
                      @update:model-value="modelEditor!.capability = $event ?? ''"
                    />
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
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RefreshCw, Star, X } from 'lucide-vue-next'
import { PROVIDER_PRESETS } from '../data/provider-presets'
import { THEME_PRESETS } from '../data/theme-presets'
import {
  gradientFromStops,
  relativeLuminance,
  type ThemeArea,
  type ThemeData,
  type ThemePreset,
  type ThemeStop,
} from '../helpers/theme'
import SettingsShell, { type SettingsSection } from './SettingsShell.vue'
import ThemeEditor from './ThemeEditor.vue'
import CoreSkillsEditor from './CoreSkillsEditor.vue'
import CoreHooksEditor from './CoreHooksEditor.vue'
import CoreSubAgentEditor from './CoreSubAgentEditor.vue'
import CoreLoadToolsEditor from './CoreLoadToolsEditor.vue'
import CoreImageGenEditor from './CoreImageGenEditor.vue'
import CoreWebSearchEditor from './CoreWebSearchEditor.vue'
import UiSelect from './UiSelect.vue'
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
  capability?: string
  notes?: string
  extra?: Record<string, unknown>
}

const props = defineProps<{
  models: CoreSettingsModel[]
  providers: CoreSettingsProvider[]
  density: CoreSettingsDensity
  theme: ThemeData
  contentWidth?: number
  allowEnvironmentImport?: boolean
  permissionMode?: 'read_only' | 'limited_edit' | 'full_edit'
  allowAccessOutsideWorkdir?: boolean
  requestRpc?: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  workflows?: WorkflowListItem[]
  workflowListLoading?: boolean
  updateState?: CoreUpdateState
}>()

const emit = defineEmits<{
  close: []
  'update:density': [density: CoreSettingsDensity]
  'update:content-width': [width: number]
  'import-environment': []
  'reopen-onboarding': []
  'update-permission-mode': [mode: 'read_only' | 'limited_edit' | 'full_edit']
  'update-allow-outside-workdir': [value: boolean]
  'reset-theme': []
  'apply-preset': [preset: ThemePreset]
  'update-stops': [area: ThemeArea, stops: ThemeStop[]]
  'update-angle': [area: ThemeArea, angle: number]
  'update-opacity': [area: ThemeArea, opacity: number]
  'update-text-color': [area: ThemeArea, color: string]
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
  'refresh-workflows': []
  'toggle-workflow-exposed': [name: string, exposed: boolean]
}>()

export interface WorkflowListItem {
  name: string
  description: string
  nodes: { id: string }[]
  edges: { id: string }[]
  exposed: boolean
  tool_name: string
}

const workflowList = computed(() => props.workflows ?? [])
function refreshWorkflowList() {
  emit('refresh-workflows')
}

const sections: SettingsSection[] = [
  { id: 'models', label: '模型与供应商', icon: 'database' },
  { id: 'appearance', label: '界面', icon: 'palette' },
  { id: 'loadtools', label: '工具模式', icon: 'list-checks' },
  { id: 'imagegen', label: '生图', icon: 'image' },
  { id: 'websearch', label: '搜索', icon: 'search' },
  { id: 'skills', label: 'Skills', icon: 'sparkles' },
  { id: 'hooks', label: 'Hooks', icon: 'plug' },
  { id: 'permissions', label: '权限', icon: 'lock' },
  { id: 'agents', label: '上下文与记忆', icon: 'file-code' },
  { id: 'workflow', label: '工作流', icon: 'workflow' },
  { id: 'subagent', label: 'Sub agent', icon: 'bot' },
  { id: 'about', label: '关于与更新', icon: 'info' },
]

// ── Update check state (共享实例由 App.vue 传入以便启动时自动检查；缺省自建) ──
const updateAutoCheck = ref(readUpdateAutoCheck())
function toggleUpdateAutoCheck(event: Event) {
  const input = event.target as HTMLInputElement
  updateAutoCheck.value = input.checked
  setUpdateAutoCheck(input.checked)
}
async function openUpdateReleasePage() {
  if (updateReleaseUrl.value) {
    const { openUpdatePage } = await import('../helpers/update')
    await openUpdatePage(updateReleaseUrl.value)
  }
}

const densityOptions: Array<{ value: CoreSettingsDensity; label: string }> = [
  { value: 'compact', label: '紧凑' },
  { value: 'standard', label: '标准' },
  { value: 'loose', label: '宽松' },
]

type ProviderEditor = Required<Omit<CoreSettingsProviderPayload, 'provider_id'>> & {
  mode: 'create' | 'update'
  provider_id?: string
  api_key: string
  extra_json: string
}

type ModelEditor = CoreSettingsModelPayload & { mode: 'create' | 'update'; extra_json: string }

const providerEditor = ref<ProviderEditor | null>(null)
const modelEditor = ref<ModelEditor | null>(null)
const noticeText = ref('')
// Validation feedback shown INSIDE the editor overlay — noticeText renders
// behind the overlay and was invisible while editing (audit 17 S3).
const editorError = ref('')
const expandedTier = ref<string | null>(null)

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
  } catch (e) {
    dreamingError.value = e instanceof Error ? e.message : String(e)
  } finally {
    dreamingSaving.value = false
  }
}

function closeEditors() {
  providerEditor.value = null
  modelEditor.value = null
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
  error: updateError,
  check: checkForUpdates,
  download: downloadUpdate,
} = update

const permissionMode = computed(() => props.permissionMode || 'full_edit')
function toggleAllowOutsideWorkdir(event: Event) {
  const input = event.target as HTMLInputElement
  emit('update-allow-outside-workdir', input.checked)
}
const permissionTiers = [
  {
    id: 'read_only' as const, label: '只读调查',
    tools: ['read_file', 'list_dir', 'search_files', 'search_content', 'web_search', 'web_fetch', 'git_status', 'git_diff', 'load_skill', 'sub_agent'],
  },
  {
    id: 'limited_edit' as const, label: '有限编辑',
    tools: ['read_file', 'list_dir', 'search_files', 'search_content', 'web_search', 'web_fetch', 'git_status', 'git_diff', 'load_skill', 'sub_agent', 'write_file', 'edit_file'],
  },
  {
    id: 'full_edit' as const, label: '完全编辑',
    tools: [] as string[],
  },
]
const providerPresets = PROVIDER_PRESETS

// ── UiSelect option lists for provider/model editors ──
const providerPresetOptions = computed(() => [
  { value: '', label: '自定义' },
  ...PROVIDER_PRESETS.map(preset => ({ value: preset.id, label: preset.label })),
])
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
      payload.models = preset.models.map(model => ({
        provider_id: '',
        model_id: model.modelId,
        display_name: model.displayName,
        context_window: model.contextWindow,
        max_output_tokens: model.maxOutputTokens,
        thinking_supported: model.thinkingSupported,
        thinking_budget: model.thinkingBudget,
        temperature: model.temperature,
        extra: model.extra,
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
  // 模板可预置 API Key（如 OpenCode Free 的 public），用户可覆盖
  editor.api_key = preset.defaultApiKey || ''
  editor.extra = { ...(preset.extra || {}), adapter_profile_id: preset.adapterProfile }
  editor.extra_json = JSON.stringify(editor.extra, null, 2)
}

function startModelCreate() {
  if (!props.providers.length) {
    noticeText.value = '请先新增供应商，再添加模型'
    return
  }
  const provider = props.providers[0]
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
  const { mode: _mode, extra_json: _extraJson, ...rest } = editor
  const payload = { ...rest, extra }
  if (editor.mode === 'create') emit('create-model', payload)
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

function presetsByGroup(group: ThemePreset['group']): ThemePreset[] {
  return THEME_PRESETS.filter((preset) => preset.group === group)
}

const presets = THEME_PRESETS

// ── Unsaved-changes guard (audit 17 S3) ─────────────────────────
// Any open editor, or a dreaming form that was touched after the last
// save, makes a close without confirmation risky (Esc / backdrop click /
// header close all discard silently today).
const settingsDirty = ref(false)

function markSettingsDirty() {
  settingsDirty.value = true
}

function requestCloseSettings() {
  if (settingsDirty.value && !window.confirm('有未保存的修改，确定关闭设置吗？')) return
  emit('close')
}

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
})
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
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
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
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

/* ── Overlay — full-viewport backdrop with centered card ── */
.settings-overlay {
  position: fixed;
  inset: var(--titlebar-offset, 36px) 0 0 0;
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
}

.settings-card {
  position: relative;
  width: min(960px, calc(100vw - 48px));
  max-height: calc(100dvh - var(--titlebar-offset, 36px) - 48px);
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #f2efeb) 12%, transparent);
  border-radius: var(--radius-lg);
  background: var(--settings-card-background, var(--theme-main-background, #111111));
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Floating editor popover ── */
.editor-overlay {
  position: absolute;
  inset: 0;
  z-index: var(--z-popover);
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
  padding: 24px;
}
.editor-popover {
  width: min(560px, 100%);
  max-height: calc(100% - 48px);
  overflow-y: auto;
  border-radius: var(--radius);
  background: var(--settings-card-background, var(--theme-main-background, #111111));
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 14%, transparent);
  box-shadow: var(--shadow-md);
  padding: 18px 20px;
  color: var(--settings-card-text, var(--settings-main-text, var(--text)));
}
.editor-popover-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.editor-popover-head h3 {
  margin: 0;
  font-size: 15px;
}
.editor-popover-close {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}
.editor-popover-close:hover {
  background: color-mix(in srgb, var(--settings-main-text, #fff) 10%, transparent);
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

.small-btn.quiet { background: transparent; }

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
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
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

.config-form .checkbox-field {
  display: flex;
  align-items: center;
  min-height: 36px;
}

/* ── 主题化 checkbox（对齐 layout.css toggle-line 配方：绿勾选中态）── */
.config-form .checkbox-field input[type="checkbox"],
.dream-toggle input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 15px;
  height: 15px;
  min-width: 15px;
  min-height: 15px;
  margin: 0;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 24%, transparent);
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  position: relative;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  transition: background .12s ease, border-color .12s ease;
}
.config-form .checkbox-field input[type="checkbox"]:checked,
.dream-toggle input[type="checkbox"]:checked {
  border-color: var(--green, #32d17d);
  background: var(--green, #32d17d);
}
.config-form .checkbox-field input[type="checkbox"]:checked::after,
.dream-toggle input[type="checkbox"]:checked::after {
  content: "";
  width: 7px;
  height: 4px;
  border-left: 2px solid color-mix(in srgb, var(--settings-main-text, #fff) 92%, transparent);
  border-bottom: 2px solid color-mix(in srgb, var(--settings-main-text, #fff) 92%, transparent);
  transform: rotate(-45deg) translateY(-1px);
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
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
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
</style>
