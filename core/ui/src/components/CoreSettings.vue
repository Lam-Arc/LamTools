<template>
  <div
    ref="settingsRootEl"
    class="full-area-column full-area-surface settings-root" data-ui-id="settings.root"
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

      <section v-if="activeSection === 'pet'" class="settings-panel">
        <CorePetEditor />
      </section>

      <section v-if="activeSection === 'models'" class="settings-panel models-panel">
        <CoreModelCatalog
          :models="models"
          :providers="providers"
          :model-groups="modelGroups"
          :catalog-view="catalogView"
          :request-rpc="requestRpc"
          :persist-catalog="persistCatalog"
          :draft-guard="draftGuard"
          :allow-environment-import="allowEnvironmentImport"
          @update:catalog-view="(value) => $emit('update:catalogView', value)"
          @create-provider="(payload) => $emit('create-provider', payload)"
          @update-provider="(payload) => $emit('update-provider', payload)"
          @delete-provider="(id) => $emit('delete-provider', id)"
          @create-model="(payload) => $emit('create-model', payload)"
          @update-model="(payload) => $emit('update-model', payload)"
          @delete-model="(id) => $emit('delete-model', id)"
          @set-default-model="(id) => $emit('set-default-model', id)"
          @create-model-group="(payload) => $emit('create-model-group', payload)"
          @update-model-group="(payload) => $emit('update-model-group', payload)"
          @delete-model-group="(id) => $emit('delete-model-group', id)"
          @set-model-group-members="(payload) => $emit('set-model-group-members', payload)"
          @create-model-with-provider="(payload) => $emit('create-model-with-provider', payload)"
          @import-environment="$emit('import-environment')"
        />
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
import { useThemeStudio } from '@/composables/useThemeStudio.ts'
import { createSettingsDraftGuard, useSettingsDraft } from '@/composables/useSettingsDraftGuard.ts'
import { ToggleLeft, ToggleRight, X } from 'lucide-vue-next'
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
import SettingsShell from '@/components/SettingsShell.vue'
import CoreModelCatalog from '@/components/CoreModelCatalog.vue'
import { CORE_SETTINGS_SECTIONS, type SettingsSection } from '@/components/settingsSections.ts'
import ThemeEditor from '@/components/ThemeEditor.vue'
import CoreSubAgentEditor from '@/components/CoreSubAgentEditor.vue'
import CoreGeneralEditor from '@/components/CoreGeneralEditor.vue'
import CorePetEditor from '@/components/CorePetEditor.vue'
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
import SettingsDraftDialog from '@/components/SettingsDraftDialog.vue'
import {
  readUpdateAutoCheck,
  setUpdateAutoCheck,
  useCoreUpdateState,
  type CoreUpdateState,
} from '@/composables/index.ts'

export type CoreSettingsDensity = 'compact' | 'standard' | 'loose'

import type {
  CoreSettingsModel,
  CoreSettingsModelGroup,
  CoreSettingsModelPayload,
  CoreSettingsProvider,
  CoreSettingsProviderPayload,
  SettingsCatalogMutation,
} from '@/components/model-catalog/types.ts'

export type {
  CoreSettingsModel,
  CoreSettingsModelGroup,
  CoreSettingsModelPayload,
  CoreSettingsProvider,
  CoreSettingsProviderPayload,
  SettingsCatalogMutation,
} from '@/components/model-catalog/types.ts'

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
  resolvedSection.value = id
  emit('section-change', id)
}
function requestSection(id: string) {
  if (id === resolvedSection.value) return
  beforeSectionChange(id, () => onSectionChange(id))
}
watch(() => props.activeSection, id => { if (id) requestSection(id) })

// All exits share actual draft comparisons, including the host's rail.
function requestCloseSettings() {
  draftGuard.requestNavigation(() => emit('close'))
}
defineExpose({ requestNavigation: draftGuard.requestNavigation, requestSection })

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

const lcKindOptions = [
  { value: 'system', label: 'system' },
  { value: 'memory', label: 'memory' },
]

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
