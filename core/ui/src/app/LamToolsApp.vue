<template>
  <TitleBar
    :hide-on-mobile="runtime.platform === 'mobile'"
    :show-in-preview="props.showPreviewTitleBar"
    :left-pinned="leftPinned"
    :right-pinned="rightPinned"
    :effective-theme-mode="effectiveThemeMode"
    :mode-label="activeAppMode.title"
    :mode-title="nextAppModeTitle"
    :can-toggle-mode="appModes.length > 1"
    :mobile-pairing-code="remotePairing?.code"
    :mobile-pairing-expires-at-ms="remotePairing?.expiresAtMs"
    :mobile-pairing-loading="remoteGatewayLoading"
    :account-status="effectiveAccountStatus"
    :account-devices="effectiveAccountDevices"
    @toggle-left-pinned="toggleLeftPinned"
    @toggle-right-pinned="toggleRightPinned"
    @cycle-mode="cycleAppMode"
    @mobile-pairing-create="createRemotePairing"
  />
  <div v-if="backendCrashed" class="core-update-banner" role="alert" data-backend-crashed-banner>
    <span class="core-update-banner-text">后端进程已停止响应（可能已崩溃）。请重启应用以恢复。</span>
  </div>
  <div v-if="updateBannerVisible" class="core-update-banner" data-update-banner>
    <span class="core-update-banner-text">{{ updateBannerText }}</span>
    <button
      v-if="updateBannerAction === 'install'"
      class="core-update-banner-action"
      type="button"
      data-update-banner-install
      @click="installUpdateNow()"
    >立即安装</button>
    <button
      v-else
      class="core-update-banner-action"
      type="button"
      :disabled="updateInstallState === 'downloading'"
      data-update-banner-download
      @click="startUpdateDownload()"
    >{{ updateInstallState === 'downloading' ? '下载中…' : '下载更新' }}</button>
    <button class="core-update-banner-close" type="button" aria-label="关闭提示" @click="dismissUpdateBanner">✕</button>
  </div>
  <CoreSettings
    v-if="showSettings"
    :models="availableModels"
    :providers="availableProviders"
    :model-groups="modelGroups"
    :catalog-view="modelCatalogView"
    :section="settingsSection"
    :density="density"
    :theme="theme"
    :content-width="contentWidth"
    :show-right-panel-header="false"
    :theme-mode="themeMode"
    :effective-theme-mode="effectiveThemeMode"
    :permission-preset="defaultPermissionPreset"
    :allow-access-outside-workdir="allowAccessOutsideWorkdir"
    :command-shell-platform="commandShellPlatform"
    :request-rpc="requestConfigOperation"
    :update-state="updateState"
    :remote-gateway-status="remoteGatewayStatus"
    :remote-pairing="remotePairing"
    :remote-gateway-loading="remoteGatewayLoading"
    :remote-gateway-error="effectiveAccountError || remoteGatewayError"
    :remote-gateway-available="remoteGatewayAvailable"
    :remote-account-status="effectiveAccountStatus"
    :remote-account-identity="remoteAccountIdentity"
    :remote-account-loading="effectiveAccountLoading"
    :remote-account-devices="effectiveAccountDevices"
    @close="showSettings = false"
    @update:density="uiPreferences.setDensity"
    @update:content-width="uiPreferences.setContentWidth"
    @update:theme-mode="uiPreferences.setThemeMode"
    @reset-theme="uiPreferences.resetTheme"
    @apply-preset="uiPreferences.applyThemePreset"
    @update-stops="uiPreferences.updateThemeStops"
    @update-angle="uiPreferences.updateThemeAngle"
    @update-opacity="uiPreferences.updateThemeOpacity"
    @update-text-color="uiPreferences.updateThemeText"
    @update-process-icon-color="uiPreferences.updateProcessIconColor"
    @add-stop="uiPreferences.addStop"
    @remove-stop="uiPreferences.removeStop"
    @sort-stops="uiPreferences.sortStops"
    @update-permission-preset="updatePermissionPreset"
    @update-allow-outside-workdir="updateAllowAccessOutsideWorkdir"
    @create-provider="createProvider"
    @update-provider="updateProvider"
    @delete-provider="deleteProvider"
	@create-model="createModel"
	    @update-model="updateModel"
	    @delete-model="deleteModel"
    @set-default-model="setDefaultModel"
    @update:catalog-view="updateModelCatalogView"
    @create-model-group="createModelGroup"
    @update-model-group="updateModelGroup"
    @delete-model-group="deleteModelGroup"
    @set-model-group-members="setModelGroupMembers"
    @create-model-with-provider="createModelWithProvider"
    @remote-gateway-start="startRemoteGateway"
    @remote-gateway-stop="stopRemoteGateway"
    @remote-pairing-create="createRemotePairing"
    @remote-device-revoke="revokeRemoteDevice"
    @remote-account-submit="submitEffectiveAccount"
    @remote-account-logout="logoutEffectiveAccount"
    @reopen-onboarding="reopenOnboarding"
  />
        <PluginsShell
          v-if="showPlugins"
          :request-rpc="requestConfigOperation"
          :transport="transport"
          :theme="theme"
          :initial-section="pluginsSection"
    @capabilities-changed="handleCapabilitiesChanged"
    @close="closePlugins"
  />
  <AccountShell
    v-if="showAccount"
    :account-status="effectiveAccountStatus"
    :devices="effectiveAccountDevices"
    :loading="remoteAccountLoading"
    :error="remoteGatewayError"
    :theme="theme"
    :on-logout="logoutEffectiveAccount"
    :on-open-settings="openAccountSettings"
    :on-refresh="refreshRemoteAccount"
    @close="showAccount = false"
  />
  <OnboardingWizard
    v-if="showOnboarding"
    :providers="availableProviders"
    :models="availableModels"
    :default-model-id="defaultModelId"
    :theme="theme"
    :loading="wizardLoading"
    :error="wizardError"
    @create-provider="onboardingCreateProvider"
    @skip="skipOnboarding"
    @finish="finishOnboarding"
  />
  <WorkspaceShell
    ref="shellRef"
    product-name="Sunday"
    sidebar-title="Sunday"
    :storage-key="settingsStorageKey"
    :density="density"
    :theme="theme"
    :content-width="contentWidth"
    :show-sidebar-header="false"
    :show-sidebar-header-action="false"
    :show-sidebar-search-action="showMobileFooterFallback"
    :show-sidebar-plugins-action="showMobileFooterFallback"
    :show-sidebar-settings-action="appRuntime.platform !== 'mobile' || showMobileFooterFallback"
    :show-right-panel="appRuntime.platform !== 'mobile'"
    :show-right-panel-header="false"
    :main-content-full-bleed="activePluginMode?.pluginId === 'workflow'"
    :workflow-mode="activePluginMode?.pluginId === 'workflow'"
    :composer-has-value="Boolean(composerText.trim())"
    :composer-disabled="composerInputDisabled"
    :composer-send-disabled="composerSendDisabled"
    :composer-placeholder="composerPlaceholder"
    :composer-action-mode="composerActionMode"
    :hide-composer="shouldHideComposer"
    :empty-session="isEmptySession"
    :composer-session-key="activeSessionId"
    :composer-session-ready="!historyLoading"
    v-model:stage-open="stageOpen"
    @new-session="handleShellNewSession"
    @update:left-open="onLeftDrawerChange"
    @update:left-pinned="syncLeftPinned"
    @update:right-pinned="syncRightPinned"
    @settings="openSettings"
    @plugins="openPlugins"
    @search="openSearch"
    @composer-submit="submitComposer"
    @composer-drop="handleComposerDrop"
  >
    <template #primary>
      <div class="core-project-primary-actions">
        <div class="core-project-primary-row">
          <button
            v-if="sidebarPrimaryActionLabel"
            class="sidebar-create-project"
            type="button"
            data-sidebar-primary-action
            :title="sidebarPrimaryActionLabel"
            :aria-label="sidebarPrimaryActionLabel"
            @click="invokeSidebarPrimaryAction"
          >
            <span aria-hidden="true">＋</span><span>{{ sidebarPrimaryActionLabel }}</span>
          </button>
          <button
            v-if="appRuntime.platform === 'mobile' && !activePluginMode"
            class="sidebar-sync-project"
            type="button"
            title="同步项目"
            aria-label="同步项目"
            data-sidebar-sync-project
            @click="emit('sync-request')"
          ><MonitorSmartphone :size="17" :stroke-width="1.9" aria-hidden="true" /></button>
        </div>
        <CoreProjectCreate
          v-if="showProjectCreate && !activePluginMode"
          :loading="projectCreateLoading"
          :error="projectCreateError"
          :transport="transport"
          :local-only="appRuntime.capabilities.localProjects?.value === true"
          @submit="createProject"
          @cancel="closeProjectCreate"
        />
        <CoreProjectPicker
          v-if="showProjectPicker && !activePluginMode"
          :projects="projects"
          @select="selectRegisteredProject"
          @cancel="showProjectPicker = false"
        />
      </div>
    </template>

    <template #sidebar-body>
      <component
        :is="activePluginSurface.sidebar.component"
        v-if="activePluginSurface?.sidebar?.component"
        v-bind="readPluginSurface(activePluginSurface.sidebar.componentProps, {})"
      />
      <SessionSidebar
        v-else
        :project-groups="sidebarGroups"
        :has-projects="sidebarHasProjects"
        :project-session-limit="8"
        pin-storage-key="lamtools-core.sidebar.pinned-projects"
        :active-session-id="sidebarActiveSessionId"
        :busy-project-ids="sidebarBusyProjectIds"
        :allow-project-new-session="sidebarAllowProjectNewSession"
        :allow-project-delete="sidebarAllowProjectDelete"
        :allow-project-click="sidebarAllowProjectClick"
        :allow-project-context-menu="sidebarAllowProjectContextMenu"
        :allow-session-delete="sidebarAllowSessionDelete"
        :allow-session-context-menu="sidebarAllowSessionContextMenu"
        :new-session-label="sidebarNewSessionLabel"
        :local-filter="appRuntime.platform === 'mobile'"
        @select-session="handleSidebarSession"
        @select-project="handleSidebarProject"
        @new-session="handleSidebarNewSession"
        @delete-project="deleteProject"
        @project-context-menu="openProjectActions"
        @rename-project="openProjectRename"
        @delete-session="deleteSession"
        @rename-session="renameSessionFromSidebar"
        @export-session="exportSession"
      >
        <template #empty>
          <div class="sidebar-empty-projects" data-sidebar-empty-projects>
            <div v-if="!activePluginMode" class="sidebar-empty-backdrop" aria-hidden="true">暂无</div>
          </div>
        </template>
        <!-- 桌面：全局搜索、资料库、长期安排、插件并作一排同规格图标。 -->
        <template v-if="appRuntime.platform !== 'mobile'" #toolbar-actions>
          <RailAction
            action-id="search"
            label="搜索"
            description="跨项目查找会话、消息、方案与文件。"
            tip-placement="below"
            @click="openSearch"
          >
            <Search :size="16" :stroke-width="1.8" />
          </RailAction>
          <RailAction
            action-id="library"
            label="资料库"
            description="浏览「方案/」文件夹里的方案，点开读全文，就绪后可直接开工。"
            tip-placement="below"
            @click="openLibrary"
          >
            <Library :size="16" :stroke-width="1.8" />
          </RailAction>
          <RailAction
            action-id="arrange"
            label="长期安排"
            description="查看并调整长期任务安排，让 Sunday 按计划继续执行。"
            tip-placement="below"
            @click="openArrange"
          >
            <CalendarClock :size="16" :stroke-width="1.8" />
          </RailAction>
          <RailAction
            action-id="plugins"
            label="插件"
            description="管理已安装的插件，开关它们带来的界面与工具。"
            tip-placement="below"
            @click="openPlugins"
          >
            <Puzzle :size="16" :stroke-width="1.8" />
          </RailAction>
        </template>
      </SessionSidebar>
    </template>

    <template v-if="showSidebarFooter" #sidebar-footer>
      <!-- 手机降级页脚（无 hover 可依赖）：仍是带文字的竖排行，与今天一致。 -->
      <div v-if="showMobileFooterFallback" class="drawer-footer-stack">
        <button
          v-for="option in mobileModeOptions"
          :key="option.id"
          class="sidebar-action"
          type="button"
          :aria-pressed="option.id === activeMobileModeId"
          :data-mobile-footer-mode="option.id"
          @click="selectAppModeByKey(option.id)"
        >
          <span aria-hidden="true"><Check v-if="option.id === activeMobileModeId" :size="14" :stroke-width="1.8" /><Blocks v-else :size="14" :stroke-width="1.8" /></span>
          <span>{{ option.label }}</span>
        </button>
        <button class="sidebar-action" type="button" data-mobile-footer-account @click="emit('open-account')">
          <span aria-hidden="true"><UserRound :size="14" :stroke-width="1.8" /></span><span>登录 / 账号</span>
        </button>
        <button class="sidebar-action" type="button" data-mobile-footer-library @click="openLibrary">
          <span aria-hidden="true"><Library :size="14" :stroke-width="1.8" /></span><span>资料库</span>
        </button>
        <button class="sidebar-action" type="button" data-mobile-footer-arrange @click="openArrange">
          <span aria-hidden="true"><CalendarClock :size="14" :stroke-width="1.8" /></span><span>长期安排</span>
        </button>
      </div>
      <!-- 桌面底部只留账号显示 + 设置（设置由左侧栏自身提供）。 -->
      <button
        v-else
        class="drawer-footer-account"
        type="button"
        data-sidebar-account
        :title="accountLabel"
        @click="openAccount"
      >
        <UserRound :size="16" :stroke-width="1.8" aria-hidden="true" />
        <span class="drawer-footer-account__label">{{ accountLabel }}</span>
      </button>
    </template>

    <template #main-header>
      <div v-if="appRuntime.platform !== 'mobile' && activePluginMode" class="workspace-plugin-header" data-plugin-header></div>
      <div v-else-if="appRuntime.platform !== 'mobile' && activeSessionId" class="thread-header" data-session-header>
        <CoreSessionTitleEditor
          :title="activeSessionTitle"
          :rename="renameActiveSession"
        />
        <button
          type="button"
          class="stage-toggle-btn"
          :class="{ active: stageOpen }"
          :title="stageOpen ? '关闭视窗' : '打开视窗'"
          @click="toggleStage"
        >
          <ChevronDown v-if="stageOpen" :size="14" :stroke-width="1.8" aria-hidden="true" />
          <ChevronUp v-else :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
    </template>

    <template #main-content>
      <!-- 整版界面：搜索 / 资料库 / 长期安排 互斥地占住聊天区域，返回或 Esc 退出。 -->
      <template v-if="fullAreaView">
        <CoreArrangeManager
          v-if="showArrange"
          class="full-area-view"
          :work-root="currentWorkRoot()"
          :request-rpc="requestConfigOperation"
          @back="closeFullArea"
        />
        <SearchShell
          v-else-if="showSearch"
          class="full-area-view"
          :request-rpc="requestConfigOperation"
          :sessions="sessions"
          :on-jump="jumpToSearchedMessage"
          :active-mode-id="activeAppModeKey"
          :on-study-hit="jumpToStudySearchHit"
          :theme="theme"
          :on-open-session="openSessionFromSearch"
          :on-open-plugins="openPluginsFromSearch"
          :commands="searchCommands"
          @close="closeFullArea"
        />
        <PlanLibraryView
          v-else-if="showLibrary"
          class="full-area-view"
          :client="projectClient"
          :project-id="activeProjectId ?? selectedProjectId"
          :refresh-signal="libraryRefreshTick"
          @back="closeFullArea"
          @start-plan="startPlanFromLibrary"
          @edit-plan="openPlanFileInStage"
        />
      </template>
      <div
        v-if="activePluginMode"
        v-show="!pluginUsesCoreThread && !fullAreaView"
        class="plugin-mode-surface"
      >
        <PluginModeHost
          :plugin-id="activePluginMode.pluginId"
          :mode-id="activePluginMode.id"
        />
      </div>
      <CoreStartPage
        v-if="!fullAreaView && !activePluginMode && showCoreStartPage"
        :has-project="projects.length > 0"
        :recent-projects="recentCoreProjects"
        @new-project="openProjectCreate()"
        @select-project="showProjectPicker = true"
        @new-session="createStartPageSession"
        @open-recent-project="openRecentProject"
      />
      <template v-else-if="!fullAreaView && (!activePluginMode || pluginUsesCoreThread)">
        <ChatOutlineNavigator
          v-if="!isEmptySession"
          ref="outlineNavigator"
          :session-id="activeSessionId"
          :messages="messages"
          :request-rpc="appRuntime.requestRpc"
          :scroll-container="threadScrollEl"
          @select="locateMessage"
        />
        <section
          ref="threadScrollEl"
          class="thread"
          :class="{ 'thread--empty-session': isEmptySession }"
          @scroll.passive="handleThreadScroll"
          @wheel="handleThreadWheel"
        >
        <div class="thread-history-cap-slot">
          <Transition
            :css="false"
            @enter="enterHistoryCap"
            @leave="leaveHistoryCap"
            @enter-cancelled="cancelHistoryCapMotion"
            @leave-cancelled="cancelHistoryCapMotion"
          >
            <div
              v-if="historyPageNetworkLoading"
              ref="historyCapEl"
              class="thread-history-cap"
              role="status"
              aria-live="polite"
            >
              <LoaderCircle class="thread-history-cap-icon" :size="14" :stroke-width="1.8" aria-hidden="true" />
              <span>正在加载更早消息</span>
            </div>
          </Transition>
        </div>
        <HistoryLoadingIndicator :active="historyLoading" />
        <div
          v-if="isEmptySession"
          class="empty-session-hero"
          data-empty-session-hero
        >
          <SundayLogo class="empty-session-logo" :size="136" animated />
          <h1 class="empty-session-title">{{ emptySessionGreeting }}</h1>
        </div>
        <ChatThread
          v-else
          :messages="messages"
          :show-empty-state="!historyLoading"
          :assistant-model-labels="assistantModelLabels"
          :process-expanded-ids="processExpandedIds"
          :message-actions="true"
          :transport="transport"
          :project-id="activePluginMode ? undefined : (activeProjectId ?? selectedProjectId)"
          :work-root="activePluginMode ? undefined : activeProject?.workRoot"
          :active-turn-id="activeTurnId"
          :turn-active="activeTurnRunning"
          :locked-message-ids="lockedMessageIds"
          :auto-plot-math="activeAppModeKey === 'study:study'"
          @toggle-process="toggleProcess"
          @decision-select="approvalController.handleDecision"
          @fork-message="handleForkMessage"
          @rollback-message="handleRollbackMessage"
          @edit-message="handleEditMessage"
        />
        <div v-if="pendingPlaceholder" class="user-row">
          <div class="user-stack">
            <div class="user-bubble user-bubble--placeholder">{{ pendingPlaceholder.content }}</div>
          </div>
        </div>
        <Transition name="thread-jump-latest">
          <button
            v-if="!isEmptySession && !threadScroll.autoFollow.value"
            type="button"
            class="thread-jump-latest optical-glass"
            aria-label="回到最新消息"
            title="回到最新消息"
            @click="threadScroll.scrollToBottom(true)"
          >
            <span
              v-if="activeTurnRunning"
              ref="latestActivityIndicator"
              class="thread-jump-latest-spinner"
              aria-hidden="true"
            >
              <LoaderCircle :size="16" :stroke-width="1.8" />
            </span>
            <ArrowDown v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
          </button>
        </Transition>
        <div
          v-if="!isEmptySession"
          ref="threadBottomSentinel"
          class="thread-bottom-sentinel"
          aria-hidden="true"
        ></div>
        </section>
      </template>
    </template>

    <template #modals>
      <div v-if="activePluginMode" class="workspace-plugin-modal" data-plugin-modal></div>
      <CoreProjectSettings
        v-if="showProjectSettings && selectedProject && !activePluginMode"
        :project="{
          id: selectedProject.id,
          name: selectedProject.name,
          workRoot: selectedProject.workRoot,
          iconKey: selectedProject.iconKey,
          colorKey: selectedProject.colorKey,
        }"
        :session-id="projectSettingsSessionId"
        :theme="theme"
        :request-rpc="requestConfigOperation"
        :models="availableModels"
        :project-name-draft="projectNameDraft"
        :agents-content="agentsContent"
        :agents-loading="agentsLoading"
        :agents-saving="agentsSaving"
        :agents-error="agentsError"
        :project-action-loading="projectActionLoading"
        :project-action-error="projectActionError"
        @close="closeProjectSettings"
        @rename-project="renameProject"
        @update-project-visual="updateProjectVisual"
        @save-agents="saveAgents"
        @refresh-agents="refreshAgentsContent"
      />
    </template>

    <template #runtime-overlay>
      <RuntimeChecklistCard v-if="!activePluginMode" :step-groups="stepGroups" />
    </template>

    <template #composer-preamble>
      <div v-if="activeGoal" class="core-goal-area optical-glass" :data-status="activeGoal.status">
        <CoreGoalStrip :goal="activeGoal" @cancel="handleCancelGoal" />
        <CoreQueuedInputTray
          v-model:draft="queuedInputDraft"
          :items="queuedInputs"
          :editing-id="editingQueuedInputId"
          :can-guide="canGuideQueuedInput"
          :submitting-ids="queueController.submittingItemIds.value"
          @edit="(item) => queueController.beginEdit(item as CoreQueuedInput)"
          @save="(item) => queueController.save(item as CoreQueuedInput)"
          @cancel="queueController.cancelEdit"
          @delete="(item) => queueController.remove(item as CoreQueuedInput)"
          @guide="(item) => queueController.guide(item as CoreQueuedInput)"
        />
      </div>
      <CoreQueuedInputTray
        v-else
        v-model:draft="queuedInputDraft"
        :items="queuedInputs"
        :editing-id="editingQueuedInputId"
        :can-guide="canGuideQueuedInput"
        :submitting-ids="queueController.submittingItemIds.value"
        @edit="(item) => queueController.beginEdit(item as CoreQueuedInput)"
        @save="(item) => queueController.save(item as CoreQueuedInput)"
        @cancel="queueController.cancelEdit"
        @delete="(item) => queueController.remove(item as CoreQueuedInput)"
        @guide="(item) => queueController.guide(item as CoreQueuedInput)"
      />
    </template>

    <template #composer-popover>
      <CommandPalette
        v-if="commandPaletteVisible"
        :commands="commandPalette.filteredCommands.value"
        :active-index="commandPalette.activeIndex.value"
        @select="liveComposerController.selectCommand"
      />
    </template>

    <template #composer-textarea>
      <CorePendingDecisionPanel
        v-if="composerTakenOver"
        :items="pendingDecisions"
        :channel-ready="approvalChannelReady"
        @decision-select="handlePendingDecisionSelect"
      />
      <template v-else>
        <AttachmentTray
          :attachments="pendingAttachments"
          :transport="transport"
          @remove="removeAttachment"
          @retry="retryPendingAttachment"
          @preview="previewPendingAttachment"
          @open="openPendingAttachment"
        />
        <div class="composer-input-wrap">
          <textarea
            ref="composerTextareaEl"
            v-model="composerText"
            :class="{ 'composer-input--recognized': hasComposerRecognizedCommand }"
            :disabled="composerInputDisabled"
            :placeholder="composerPlaceholder"
            rows="1"
            @input="handleComposerInput"
            @click="updateComposerCursor"
            @keyup="handleComposerKeyup"
            @keydown="handleComposerKeydown"
            @paste="handleComposerPaste"
            @contextmenu="openComposerContextMenu"
          />
        </div>
      </template>
    </template>

    <template #composer-tools>
      <CoreExecutionControls
        :model-value="selectedModelId"
        :thinking-mode="selectedThinkingMode"
        :shallow-thinking-enabled="shallowThinkingEnabled"
        :active-mode="activeMode"
        :mode-options="modeOptions"
        :runtime-mode-label="runtimeModeLabel"
        :permission-preset="permissionPreset"
        :model-options="modelOptions"
        :catalog-view="modelCatalogView"
        :thinking-mode-options="thinkingModeOptions"
        shallow-label="Shallow"
        @update:model-value="executionControls.selectModel"
        @update:catalog-view="updateModelCatalogView"
        @update:thinking-mode="executionControls.selectThinkingMode"
        @update:shallow-thinking-enabled="setShallowThinking"
        @update:active-mode="executionControls.selectMode"
        @update:permission-preset="executionControls.selectPermissionPreset"
      >
        <template #leading>
          <AttachmentSourceMenu
            :categorized="appRuntime.platform === 'mobile'"
            :disabled="!appRuntime.capabilities.files"
            @select="chooseAttachments"
          />
        </template>
        <template #after-runtime>
          <CoreWorkspaceMenu
            v-if="appRuntime.platform === 'mobile' && appRuntime.workspaceControl"
            :active-id="appRuntime.workspaceControl.activeId.value"
            :options="appRuntime.workspaceControl.options.value"
            @select="appRuntime.workspaceControl.select"
          />
        </template>
      </CoreExecutionControls>
    </template>

    <template #stage="{ open: stageIsOpen, toggle: stageToggle }">
      <StagePane
        v-if="stageIsOpen"
        ref="stagePaneRef"
        :tabs="stageTabs"
        :active-id="stageActiveId"
        @activate="stageActivate"
        @close="stageClose"
        @update-content="stageUpdateContent"
        @save="stageSave"
        @toggle-preview="stageTogglePreview"
      />
    </template>

    <template #right-panel>
      <RightSidebarHost
        :project-id="activeProjectId"
        :work-root="activeProject?.workRoot || null"
        :session-id="activeSessionId"
        :request-rpc="requestConfigOperation"
        :transport="transport"
        :messages="messages"
        :context-window="executionControls.activeModel.value?.context_window"
        :runtime-status="latestStatus"
        :runtime-mode-label="runtimeModeLabel"
        :stage-open="stageOpen"
        :mode="rightPanelMode"
        :artifact-signal="lastWorkbenchEvent"
        :open-artifact="openArtifactInStage"
        :active-plugin-id="activePluginMode?.pluginId || null"
        :active-mode-id="activePluginMode?.id || null"
        :plugin-contributions="activePluginSidebarContributions"
        :locate-sub-agent="locateSubAgentRun"
        @mode-change="handleRightPanelMode"
      >
        <template #stage>
          <FileTreePanel
            v-if="activeProjectId"
            :project-id="activeProjectId"
            :client="projectClient"
            @open-file="openFileInStage"
          />
        </template>
      </RightSidebarHost>
    </template>
  </WorkspaceShell>

  <ContextMenuHost />
  <SelectionAssistant
    :session-id="activeSessionId"
    :mode="activeAppModeKey"
    :theme-mode="effectiveThemeMode"
    :jump="jumpToStudyMark"
  />

  <!-- 全窗口拖拽上传遮罩：拖入文件时亮起，松开即上传到当前会话 -->
  <div
    v-if="dragActive"
    class="attachment-drop-overlay"
    @dragover.prevent
    @drop.prevent="handleAttachmentDrop"
  >
    <div class="attachment-drop-card">
      <Upload class="attachment-drop-icon" :size="28" aria-hidden="true" />
      <p class="attachment-drop-title">松开鼠标上传附件</p>
      <p class="attachment-drop-hint">添加到当前会话</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onMounted,
  onUnmounted,
  ref,
  watch,
} from 'vue'
import { gsap } from 'gsap'
import {
  ArrowDown,
  Blocks,
  CalendarClock,
  Check,
  ChevronDown,
  ChevronUp,
  ClipboardPaste,
  Copy,
  FolderOpen,
  LoaderCircle,
  MonitorPlay,
  MonitorSmartphone,
  Library,
  PanelLeft,
  PanelRight,
  Plus,
  Puzzle,
  Scissors,
  Settings,
  TextSelect,
  Upload,
  UserRound,
} from 'lucide-vue-next'
import type {
  CoreAttachment,
  CoreSessionListItem,
  CoreSubAgentRun,
} from '../types'
import { isInternalSession, isPluginOwnedSession } from '../sessions/visibility'
import { createModeSessionState } from '../sessions/mode-state'
import {
  buildCoreProjectGroups,
  type CoreProject,
  type CoreProjectColorKey,
  type CoreProjectCreatePayload,
  type CoreProjectIconKey,
} from '../projects/types'
import { createCoreProjectClient } from '../projects/client'
import { createCoreProjectWorkspaceActions } from '../projects/workspace'
import {
  lockedMessageIdsBeforeCompaction,
  selectPendingCoreDecisions,
  type CoreQueuedInput,
} from '../appServer'
import type { LamToolsTransport, TransportHttpResponse } from '../transport'
import type { LamToolsRuntime, RuntimeFileSource } from './runtime'
import { buildCoreComposerHighlightSegments } from '../composer/inputItems'
import { buildCurrentTurnChecklistGroups } from '../runtime/checklist'
import {
  coreApplyHistoryScrollCeiling,
  coreHistoryAutoLoadThreshold,
  coreShouldAutoLoadHistory,
  readUpdateAutoCheck,
  useCoreAutoFollowScroll,
  useCoreExecutionControlsState,
  useCoreGoals,
  usePendingAttachments,
  useCoreUiPreferences,
  useCoreUpdateState,
  useCheckpoints,
  createCoreConnectionErrorToastGate,
  showToast,
} from '../composables'

import AttachmentTray from '../components/AttachmentTray.vue'
import AttachmentSourceMenu from '../components/AttachmentSourceMenu.vue'
import ChatThread from '../components/ChatThread.vue'
import ChatOutlineNavigator from '../components/ChatOutlineNavigator.vue'
import CommandPalette from '../components/CommandPalette.vue'
import RailAction from '../components/RailAction.vue'
import CoreExecutionControls from '../components/CoreExecutionControls.vue'
import CoreWorkspaceMenu from '../components/CoreWorkspaceMenu.vue'
import CoreQueuedInputTray from '../components/CoreQueuedInputTray.vue'
import CorePendingDecisionPanel from '../components/CorePendingDecisionPanel.vue'
import CoreArrangeManager from '../components/CoreArrangeManager.vue'
import CoreGoalStrip from '../components/CoreGoalStrip.vue'
import HistoryLoadingIndicator from '../components/HistoryLoadingIndicator.vue'
import FileTreePanel from '../components/FileTreePanel.vue'
import type { StageResource, StageKind } from '../types'
import type { ArtifactRevision, ProjectArtifact } from '../types'
import CoreProjectCreate from '../components/CoreProjectCreate.vue'
import CoreProjectPicker from '../components/CoreProjectPicker.vue'
import CoreStartPage, { type CoreRecentProject } from '../components/CoreStartPage.vue'
import CoreSessionTitleEditor from '../components/CoreSessionTitleEditor.vue'
import { ContextMenuHost } from '../components/context-menu'
import SelectionAssistant from '../study/SelectionAssistant.vue'
import type { MarkAnchor } from '../study/types'
import { selectionEvents } from '../study/annotations'
import { openContextMenu } from '../components/context-menu/context-menu'
import type { ContextMenuEntry } from '../components/context-menu/types'
import OnboardingWizard from '../components/OnboardingWizard.vue'
import PluginsShell from '../components/PluginsShell.vue'
import AccountShell from '../components/AccountShell.vue'
import SearchShell, { type SearchCommand, type StudySearchHit } from '../components/SearchShell.vue'
import PlanLibraryView, { type PlanLibraryEntry } from '../components/PlanLibraryView.vue'
import type {
  CoreSettingsModelPayload,
  CoreSettingsProviderPayload,
} from '../components/CoreSettings.vue'
import type {
  MobileControlAccountContext,
  MobileControlAccountDevice,
  MobileControlAccountPayload,
  MobileControlAccountStatus,
  MobileControlGatewayStatus,
  MobileControlIdentity,
  MobileControlPairing,
} from '../components/MobileControlPanel.vue'
import CoreProjectSettings from '../components/CoreProjectSettings.vue'
import SundayLogo from '../components/SundayLogo.vue'
import RuntimeChecklistCard from '../components/RuntimeChecklistCard.vue'
import SessionSidebar, { type SessionExportFormat } from '../components/SessionSidebar.vue'
import WorkspaceShell from '../components/WorkspaceShell.vue'
import RightSidebarHost from '../components/RightSidebarHost.vue'
import TitleBar from '../components/TitleBar.vue'
import PluginModeHost from '../components/PluginModeHost.vue'
import { refreshPluginUIModes } from '../plugins/api'
import { listModes } from '../plugins/registry'
import {
  provideCorePluginModeContext,
  readPluginSurface,
  createPluginModeRuntime,
} from '../plugins/context'
import type { PluginModeSurface } from '../plugins/context'
import type { PluginMode } from '../plugins/types'
import type { CoreModelCatalogView, CorePermissionPreset } from '../composer/execution'
import { copyText } from '../helpers/clipboard'

const CoreSettings = defineAsyncComponent(() => import('../components/CoreSettings.vue'))
const StagePane = defineAsyncComponent(() => import('../components/StagePane.vue'))

type StagePaneInstance = InstanceType<(typeof import('../components/StagePane.vue'))['default']>

type RawSession = {
  id: string
  title: string
  status?: string
  created_at?: string
  createdAt?: string
  updated_at?: string
  updatedAt?: string
  metadata?: Record<string, unknown>
}

type SessionExportExtension = 'md' | 'txt' | 'jsonl' | 'json' | 'zip'

type RawModel = {
  id: string
  provider_id?: string
  model_id?: string
  display_name?: string
  context_window?: number
  max_output_tokens?: number
  thinking_supported?: boolean
  thinking_budget?: number
  reasoning_off_supported?: boolean
  temperature?: number
  capability?: string
  notes?: string
  extra?: Record<string, unknown> | null
}

type RawProvider = {
  id: string
  name: string
  api_type?: string
  base_url?: string
  has_api_key?: boolean
  extra?: Record<string, unknown> | null
}

type RawModelGroup = {
  id: string
  name: string
  model_ids: string[]
  revision?: number
  is_system?: boolean
}

const props = defineProps<{
  runtime: LamToolsRuntime
  accountContext?: MobileControlAccountContext
  mobileCommandDockAvailable?: boolean
  showPreviewTitleBar?: boolean
}>()
const emit = defineEmits<{
  'left-drawer-change': [value: boolean]
  'account-submit': [payload: MobileControlAccountPayload]
  'account-logout': []
  'open-account': []
  'mobile-mode-state': [payload: {
    label: string
    title: string
    canToggle: boolean
    activeId: string
    options: Array<{ id: string; label: string }>
  }]
  'sync-request': []
}>()

function onLeftDrawerChange(value: boolean): void {
  emit('left-drawer-change', value)
}
const appRuntime = props.runtime
const showMobileFooterFallback = computed(() => appRuntime.platform === 'mobile' && props.mobileCommandDockAvailable !== true)
const showSidebarFooter = computed(() => appRuntime.platform !== 'mobile' || showMobileFooterFallback.value)
const commandShellPlatform = (() => {
  if (appRuntime.platform === 'mobile') return 'mobile' as const
  if (appRuntime.platform !== 'desktop') return 'web' as const
  const host = typeof navigator === 'undefined' ? '' : `${navigator.platform} ${navigator.userAgent}`
  if (/windows|win32|win64/i.test(host)) return 'windows' as const
  if (/linux/i.test(host)) return 'linux' as const
  return 'other' as const
})()
const workbench = appRuntime.workbench
const transport = appRuntime.transport
const projectClient = appRuntime.projectClient || createCoreProjectClient(transport)
const connectionErrorToastGate = createCoreConnectionErrorToastGate({
  isConnected: () => workbench.connectionState.value === 'open',
})
watch(workbench.connectionState, (state) => connectionErrorToastGate.onConnectionState(state), { immediate: true })
onUnmounted(() => connectionErrorToastGate.dispose())

async function requestJson<T = unknown>(
  path: string,
  options: { method?: string; body?: unknown; headers?: Record<string, string> } = {},
): Promise<T> {
  return await appRuntime.requestJson<T>(path, {
    method: options.method || 'GET',
    headers: options.headers || (options.body === undefined ? undefined : { 'Content-Type': 'application/json' }),
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
}

const projects = ref<CoreProject[]>([])
const sessions = workbench.sessions
const activeSessionId = workbench.activeSessionId
const historyLoadingSessionId = ref<string | null>(null)
const snapshot = workbench.snapshot
const lastWorkbenchEvent = workbench.lastEvent
const composerText = workbench.composerText
const composerCursor = workbench.composerCursor
const composerTextareaEl = ref<HTMLTextAreaElement | null>(null)
const composerErrorText = ref('')

// Status/error notifications go through the global toast service (single
// queue, auto-expiry per kind, dismissible) instead of the shell's two fixed
// slots — the old path left several error sources pinned forever.
function setRuntimeStatus(text: string, duration = 3000) {
  showToast('notice', text, duration)
}

const loadError = ref<string | null>(null)

function setLoadError(text: string) {
  loadError.value = text
}
const showProjectCreate = ref(false)
const projectCreateLoading = ref(false)
const projectCreateError = ref('')
const showProjectPicker = ref(false)
const selectedProjectId = ref<string | null>(null)
const projectNameDraft = ref('')
const projectActionLoading = ref(false)
const projectActionError = ref('')
const showProjectSettings = ref(false)

const RECENT_PROJECTS_STORAGE_KEY = 'lamtools-core.recent-projects'
const recentProjectOpenings = ref<CoreRecentProject[]>(readRecentProjectOpenings())

function readRecentProjectOpenings(): CoreRecentProject[] {
  try {
    const raw = window.localStorage.getItem(RECENT_PROJECTS_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    if (!Array.isArray(parsed)) return []
    return parsed.flatMap((entry): CoreRecentProject[] => (
      entry
      && typeof entry.id === 'string'
      && typeof entry.openedAt === 'string'
        ? [{
            id: entry.id,
            name: typeof entry.name === 'string' ? entry.name : '未命名项目',
            workRoot: typeof entry.workRoot === 'string' ? entry.workRoot : '',
            openedAt: entry.openedAt,
          }]
        : []
    )).slice(0, 6)
  } catch {
    return []
  }
}

function rememberRecentProject(project: CoreProject): void {
  const nextEntry: CoreRecentProject = {
    id: project.id,
    name: project.name,
    workRoot: project.workRoot,
    openedAt: new Date().toISOString(),
  }
  recentProjectOpenings.value = [
    nextEntry,
    ...recentProjectOpenings.value.filter((entry) => entry.id !== project.id),
  ].slice(0, 6)
  try {
    window.localStorage.setItem(RECENT_PROJECTS_STORAGE_KEY, JSON.stringify(recentProjectOpenings.value))
  } catch {
    // Recent projects are a convenience only; a restricted storage context
    // must never stop the workspace from opening a project.
  }
}
const agentsProjectId = ref<string | null>(null)
const agentsContent = ref('')
const agentsLoading = ref(false)
const agentsSaving = ref(false)
const agentsError = ref('')
const shellRef = ref<InstanceType<typeof WorkspaceShell> | null>(null)
const leftPinned = ref(true)
const rightPinned = ref(false)
const sendingDisabled = ref(false)

function toggleLeftPinned() {
  shellRef.value?.toggleLeftPinned()
}
function syncLeftPinned(value: boolean) {
  leftPinned.value = value
}
function toggleRightPinned() {
  shellRef.value?.toggleRightPinned()
}
function syncRightPinned(value: boolean) {
  rightPinned.value = value
}
const settingsStorageKey = 'lamtools.core.ui'
const showSettings = ref(false)
/** Section the settings surface opens on; the rail's account entry targets it. */
const settingsSection = ref<string | undefined>(undefined)
const showPlugins = ref(false)
// 整版界面状态：搜索 / 资料库 / 长期安排 互斥地占住聊天区域，返回或 Esc 退出；
// 打开同一个入口相当于退出（与旧浮层的开合直觉一致）。
const fullAreaView = ref<'library' | 'search' | 'arrange' | null>(null)
const showSearch = computed(() => fullAreaView.value === 'search')
const showArrange = computed(() => fullAreaView.value === 'arrange')
const showLibrary = computed(() => fullAreaView.value === 'library')
const libraryRefreshTick = ref(0)
function openFullArea(view: 'library' | 'search' | 'arrange'): void {
  fullAreaView.value = fullAreaView.value === view ? null : view
}
function closeFullArea(): void {
  fullAreaView.value = null
}
const remoteGatewayStatus = ref<MobileControlGatewayStatus | null>(null)
const remotePairing = ref<MobileControlPairing | null>(null)
const remoteGatewayLoading = ref(false)
const remoteGatewayError = ref('')
const remoteAccountStatus = ref<MobileControlAccountStatus | null>(null)
const remoteAccountIdentity = ref<MobileControlIdentity | null>(null)
const remoteAccountLoading = ref(false)
const effectiveAccountStatus = computed(() => props.accountContext === undefined
  ? remoteAccountStatus.value
  : props.accountContext.status)
const effectiveAccountDevices = computed<MobileControlAccountDevice[]>(() => {
  if (props.accountContext !== undefined) return props.accountContext.devices
  const devices: MobileControlAccountDevice[] = []
  if (remoteAccountStatus.value) {
    devices.push({
      nodeId: remoteAccountStatus.value.nodeId,
      label: 'LamTools Desktop',
      detail: '当前桌面工作环境',
      platform: 'desktop',
      online: Boolean(remoteGatewayStatus.value?.relayConnected),
      current: true,
    })
  }
  for (const device of remoteGatewayStatus.value?.trustedDevices || []) {
    devices.push({
      nodeId: device.deviceId,
      label: device.name || device.deviceId,
      detail: '已配对移动设备',
      platform: device.platform || 'mobile',
      online: Boolean(device.lastSeenMs && Date.now() - device.lastSeenMs < 60_000),
    })
  }
  return devices
})
const effectiveAccountLoading = computed(() => props.accountContext?.loading ?? remoteAccountLoading.value)
const effectiveAccountError = computed(() => props.accountContext?.error || '')

function submitEffectiveAccount(payload: MobileControlAccountPayload): void {
  if (props.accountContext !== undefined) emit('account-submit', payload)
  else void saveRemoteAccount(payload)
}

function logoutEffectiveAccount(): void {
  if (props.accountContext !== undefined) emit('account-logout')
  else void logoutRemoteAccount()
}

const remoteGatewayAvailable = computed(() => (
  typeof (window as any).__LAMTOOLS_REMOTE_STATUS__ === 'function'
))

async function refreshRemoteAccount(): Promise<void> {
  const status = (window as any).__LAMTOOLS_REMOTE_ACCOUNT_STATUS__ as (() => Promise<MobileControlAccountStatus | null>) | undefined
  const identity = (window as any).__LAMTOOLS_REMOTE_ACCOUNT_IDENTITY__ as (() => Promise<MobileControlIdentity>) | undefined
  if (status) {
    try {
      remoteAccountStatus.value = await status()
    } catch (error) {
      remoteGatewayError.value = messageFromError(error)
    }
  }
  if (identity) {
    try {
      remoteAccountIdentity.value = await identity()
    } catch (error) {
      remoteGatewayError.value = messageFromError(error)
    }
  }
}

async function saveRemoteAccount(payload: MobileControlAccountPayload): Promise<void> {
  const save = (window as any).__LAMTOOLS_REMOTE_ACCOUNT_SAVE__ as ((session: Record<string, unknown>) => Promise<MobileControlAccountStatus>) | undefined
  const identityCall = (window as any).__LAMTOOLS_REMOTE_ACCOUNT_IDENTITY__ as ((scope?: { serverId: string; username: string }) => Promise<MobileControlIdentity>) | undefined
  if (!save || !identityCall) return
  remoteAccountLoading.value = true
  remoteGatewayError.value = ''
  const restartGateway = Boolean(remoteGatewayStatus.value?.enabled)
  try {
    const baseUrl = normalizeRemoteServerBaseUrl(
      payload.baseUrl || import.meta.env.VITE_LAMTOOLS_RELAY_URL || 'https://47.114.43.99.nip.io',
    )
    const auth = await requestRemoteAccountJson(
      baseUrl,
      `/v1/auth/${payload.mode}`,
      { username: payload.username.trim(), password: payload.password },
    )
    const authTokens = parseRemoteAccountTokens(auth)
    if (!authTokens) throw new Error('服务器返回了无效的登录凭据')
    const identity = await identityCall({ serverId: authTokens.serverId, username: payload.username.trim() })
    remoteAccountIdentity.value = identity
    const registration = await requestRemoteAccountJson(
      baseUrl,
      '/v1/nodes/register',
      {
        nodeId: identity.nodeId,
        publicKey: identity.publicKey,
        displayName: 'LamTools Desktop',
        platform: 'desktop',
        capabilities: ['workspace_host', 'agent_runtime', 'filesystem', 'terminal'],
      },
      authTokens.accessToken,
    )
    const node = parseRemoteAccountNode(registration.node)
    if (!node) throw new Error('服务器未返回有效的桌面 Node')
    const boundTokens = parseRemoteAccountTokens(registration.tokens) || authTokens
    const saved = await save({
      baseUrl,
      serverId: boundTokens.serverId,
      username: payload.username.trim(),
      nodeId: node.nodeId,
      publicKey: node.publicKey,
      accessToken: boundTokens.accessToken,
      refreshToken: boundTokens.refreshToken,
      accessExpiresAtMs: boundTokens.accessExpiresAtMs,
      refreshExpiresAtMs: boundTokens.refreshExpiresAtMs,
    })
    remoteAccountStatus.value = saved || {
      baseUrl,
      serverId: boundTokens.serverId,
      username: payload.username.trim(),
      nodeId: node.nodeId,
      accessExpiresAtMs: boundTokens.accessExpiresAtMs,
      refreshExpiresAtMs: boundTokens.refreshExpiresAtMs,
    }
    // Saving a new account intentionally stops the old Relay connection in
    // Rust. Restore the user's previous gateway intent after credentials are
    // safely stored.
    if (restartGateway) {
      const start = (window as any).__LAMTOOLS_REMOTE_START__ as (() => Promise<MobileControlGatewayStatus>) | undefined
      if (start) remoteGatewayStatus.value = await start()
    }
  } catch (error) {
    remoteGatewayError.value = messageFromError(error)
  } finally {
    remoteAccountLoading.value = false
  }
}

async function logoutRemoteAccount(): Promise<void> {
  const logout = (window as any).__LAMTOOLS_REMOTE_ACCOUNT_LOGOUT__ as (() => Promise<void>) | undefined
  if (!logout) return
  remoteAccountLoading.value = true
  remoteGatewayError.value = ''
  try {
    await logout()
    remoteAccountStatus.value = null
    remotePairing.value = null
    remoteGatewayStatus.value = await readRemoteGatewayStatus()
  } catch (error) {
    remoteGatewayError.value = messageFromError(error)
  } finally {
    remoteAccountLoading.value = false
  }
}

async function readRemoteGatewayStatus(): Promise<MobileControlGatewayStatus | null> {
  const status = (window as any).__LAMTOOLS_REMOTE_STATUS__ as (() => Promise<MobileControlGatewayStatus>) | undefined
  return status ? await status() : null
}

async function requestRemoteAccountJson(
  baseUrl: string,
  path: string,
  body: Record<string, unknown>,
  accessToken?: string,
): Promise<Record<string, unknown>> {
  let response: Response
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify(body),
      cache: 'no-store',
    })
  } catch (error) {
    throw new Error(`无法连接服务器：${messageFromError(error)}`)
  }
  const payload = await response.json().catch(() => null) as unknown
  const record = isRecordValue(payload) ? payload : {}
  if (!response.ok) {
    const message = typeof record.message === 'string'
      ? record.message
      : typeof record.error === 'string' ? record.error : `服务器请求失败（${response.status}）`
    throw new Error(message)
  }
  return record
}

function normalizeRemoteServerBaseUrl(raw: string): string {
  let url: URL
  try {
    url = new URL(raw.trim())
  } catch {
    throw new Error('服务器地址格式无效')
  }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('服务器地址必须使用 HTTP 或 HTTPS')
  const marker = url.pathname.indexOf('/v1/')
  url.pathname = (marker >= 0 ? url.pathname.slice(0, marker) : url.pathname).replace(/\/+$/, '') || '/'
  url.search = ''
  url.hash = ''
  return url.toString().replace(/\/$/, '')
}

function parseRemoteAccountTokens(value: unknown): {
  serverId: string
  accessToken: string
  refreshToken: string
  accessExpiresAtMs: number
  refreshExpiresAtMs: number
} | null {
  const record = isRecordValue(value) ? (isRecordValue(value.tokens) ? value.tokens : value) : {}
  const serverId = stringValue(record.serverId || record.server_id)
  const accessToken = stringValue(record.accessToken || record.access_token)
  const refreshToken = stringValue(record.refreshToken || record.refresh_token)
  const accessExpiresAtMs = numberValue(record.accessExpiresAtMs || record.access_expires_at_ms)
  const refreshExpiresAtMs = numberValue(record.refreshExpiresAtMs || record.refresh_expires_at_ms)
  if (!serverId || !accessToken || !refreshToken || !accessExpiresAtMs || !refreshExpiresAtMs) return null
  return { serverId, accessToken, refreshToken, accessExpiresAtMs, refreshExpiresAtMs }
}

function parseRemoteAccountNode(value: unknown): { nodeId: string; publicKey: string } | null {
  if (!isRecordValue(value)) return null
  const nodeId = stringValue(value.nodeId || value.node_id)
  const publicKey = stringValue(value.publicKey || value.public_key)
  return nodeId && publicKey ? { nodeId, publicKey } : null
}

function isRecordValue(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function numberValue(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

async function refreshRemoteGateway(): Promise<void> {
  const status = (window as any).__LAMTOOLS_REMOTE_STATUS__ as (() => Promise<MobileControlGatewayStatus>) | undefined
  if (!status) return
  try {
    remoteGatewayStatus.value = await status()
    remoteGatewayError.value = ''
  } catch (error) {
    remoteGatewayError.value = messageFromError(error)
  }
}

async function startRemoteGateway(): Promise<void> {
  const start = (window as any).__LAMTOOLS_REMOTE_START__ as (() => Promise<MobileControlGatewayStatus>) | undefined
  if (!start) return
  remoteGatewayLoading.value = true
  remoteGatewayError.value = ''
  try {
    remoteGatewayStatus.value = await start()
  } catch (error) {
    remoteGatewayError.value = messageFromError(error)
  } finally {
    remoteGatewayLoading.value = false
  }
}

async function stopRemoteGateway(): Promise<void> {
  const stop = (window as any).__LAMTOOLS_REMOTE_STOP__ as (() => Promise<MobileControlGatewayStatus>) | undefined
  if (!stop) return
  remoteGatewayLoading.value = true
  remoteGatewayError.value = ''
  try {
    remoteGatewayStatus.value = await stop()
    remotePairing.value = null
  } catch (error) {
    remoteGatewayError.value = messageFromError(error)
  } finally {
    remoteGatewayLoading.value = false
  }
}

async function createRemotePairing(): Promise<void> {
  const create = (window as any).__LAMTOOLS_REMOTE_PAIRING_CREATE__ as (() => Promise<MobileControlPairing>) | undefined
  if (!create) return
  remoteGatewayLoading.value = true
  remoteGatewayError.value = ''
  try {
    if (!remoteGatewayStatus.value?.enabled) {
      const start = (window as any).__LAMTOOLS_REMOTE_START__ as (() => Promise<MobileControlGatewayStatus>) | undefined
      if (!start) throw new Error('手机控制命令将在桌面 Tauri 运行时启用')
      remoteGatewayStatus.value = await start()
      if (!remoteGatewayStatus.value?.enabled) throw new Error('手机控制未能启动')
    }
    remotePairing.value = await create()
  } catch (error) {
    remoteGatewayError.value = messageFromError(error)
  } finally {
    remoteGatewayLoading.value = false
  }
}

async function revokeRemoteDevice(deviceId: string): Promise<void> {
  const revoke = (window as any).__LAMTOOLS_REMOTE_REVOKE__ as ((id: string) => Promise<boolean>) | undefined
  if (!revoke) return
  remoteGatewayLoading.value = true
  remoteGatewayError.value = ''
  try {
    await revoke(deviceId)
    await refreshRemoteGateway()
  } catch (error) {
    remoteGatewayError.value = messageFromError(error)
  } finally {
    remoteGatewayLoading.value = false
  }
}

// Ctrl+K 全局搜索：与侧边栏「搜索」按钮一样切 showSearch（同一 SearchShell 入口）。
// 打开时避免触发浏览器/输入框插件快捷键（旧 SessionSearchDialog 已并入 SearchShell）。
// Ctrl+N / Ctrl+O / Ctrl+B / Ctrl+J 是搜索弹窗里列出的那四条，标签写出来了就得真的能按。
function isTextEntryTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  if (!element) return false
  const tag = element.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || element.isContentEditable === true
}

function handleGlobalSearchKeydown(event: KeyboardEvent): void {
  if (!(event.ctrlKey || event.metaKey)) return
  const key = event.key.toLowerCase()
  if (key === 'k') {
    event.preventDefault()
    openSearch()
    return
  }
  // The rest are document-level actions; inside a text field the browser's own
  // editing keys must win.
  if (isTextEntryTarget(event.target)) return
  if (key === 'n') {
    event.preventDefault()
    void createStartPageSession()
    return
  }
  if (key === 'o') {
    event.preventDefault()
    showProjectPicker.value = true
    return
  }
  if (key === 'b') {
    event.preventDefault()
    toggleLeftPinned()
    return
  }
  if (key === 'j') {
    event.preventDefault()
    toggleStage()
  }
}
const showOnboarding = ref(false)
const wizardLoading = ref(false)
const wizardError = ref('')
// Rust 监视线程发现后端进程退出时置位，顶部横幅提示（audit 20 S3）。
const backendCrashed = ref(false)
const lastEvent = workbench.lastEvent
const pluginModeRuntime = createPluginModeRuntime()
const pluginModes = ref<PluginMode[]>([])
const coreAppMode = {
  pluginId: 'core',
  id: 'agent',
  title: 'Agent',
  entry: '',
  icon: 'agent',
  enabled: true,
  load: async () => ({}) as never,
} as PluginMode
const appModes = computed<PluginMode[]>(() => [coreAppMode, ...pluginModes.value])
const mobileModeOptions = computed(() => appModes.value.map((mode) => ({
  id: mode.pluginId + ':' + mode.id,
  label: mode.title,
})))
const activeAppModeKey = ref('core:agent')
const activeMobileModeId = computed(() => activeAppModeKey.value)
const activeAppMode = computed(() => (
  appModes.value.find((mode) => mode.pluginId + ':' + mode.id === activeAppModeKey.value)
    || coreAppMode
))
const activePluginMode = computed(() => (
  activeAppMode.value.pluginId === 'core' ? null : activeAppMode.value
))
const activePluginSurface = computed<PluginModeSurface | undefined>(() => {
  const mode = activePluginMode.value
  return mode ? pluginModeRuntime.get(mode.pluginId + ':' + mode.id) : undefined
})
const pluginUsesCoreThread = computed(() => (
  Boolean(activePluginMode.value)
  && readPluginSurface(activePluginSurface.value?.useCoreThread, false)
))
const activePluginSidebarContributions = computed(() => (
  readPluginSurface(activePluginSurface.value?.rightSidebar, [])
))
const nextAppModeTitle = computed(() => {
  const modes = appModes.value
  if (modes.length < 2) return '没有可切换的插件模式'
  const index = modes.findIndex((mode) => mode.pluginId + ':' + mode.id === activeAppModeKey.value)
  return '切换到 ' + (modes[(index + 1) % modes.length]?.title || '下一个模式')
})

function modeKey(mode: PluginMode): string {
  return mode.pluginId + ':' + mode.id
}

function isActivePluginSession(): boolean {
  return isPluginOwnedSession(sessions.value.find((session) => session.id === activeSessionId.value))
}

const composerPlaceholder = computed(() => (
  activePluginMode.value
    ? readPluginSurface(activePluginSurface.value?.composerPlaceholder, '输入内容…')
    : '给 Sunday 发送任务...'
))

/**
 * Composer takeover — waiting approvals/questions.
 *
 * While the runtime waits for the user, anything typed into the composer is
 * queued as ordinary turn input (the thread status is `waiting`, so the submit
 * path queues instead of starting a turn) and never answers the request. The
 * composer input area is therefore replaced by the decision panel, which sends
 * its choices through the one existing approval channel.
 */
const pendingDecisions = computed(() => (
  activePluginMode.value ? [] : selectPendingCoreDecisions(workbench.messages.value)
))
const composerTakenOver = computed(() => pendingDecisions.value.length > 0)
const approvalChannelReady = computed(() => workbench.connectionState.value === 'open')

const composerInputDisabled = computed(() => {
  if (activePluginMode.value) {
    return readPluginSurface(activePluginSurface.value?.composerDisabled, true)
  }
  return composerActionMode.value === 'send' && (
    sendingDisabled.value
  )
})

const composerSendDisabled = computed(() => {
  if (activePluginMode.value) {
    const attachmentOnly = readPluginSurface(activePluginSurface.value?.allowAttachmentOnlySubmit, false)
    return composerInputDisabled.value || (!composerText.value.trim() && !(attachmentOnly && pendingAttachments.value.length))
  }
  // A pending decision owns the input area: sending a queued draft from here
  // would look like an answer without answering anything.
  if (composerTakenOver.value) return true
  return composerInputDisabled.value
    || !activeSessionId.value
    || (!composerText.value.trim() && pendingAttachments.value.length === 0)
})

// --- Stage pane state ---
const stageOpen = ref(false)
const stageTabs = ref<StageResource[]>([])
const stageActiveId = ref<string | null>(null)
const stagePaneRef = ref<StagePaneInstance | null>(null)
const rightPanelMode = ref<'runtime' | 'files' | 'artifacts'>('runtime')

function handleRightPanelMode(mode: 'runtime' | 'files' | 'artifacts'): void {
  rightPanelMode.value = mode
  if (mode === 'files' && !stageOpen.value) stageOpen.value = true
}

/**
 * "开工"（资料库）：方案即「方案/」文件夹里的一篇文档，开工把它变成一个普通
 * 会话回合——执行技能自己读回文件、装目标与清单，因此不需要新通道，
 * 桌面与手机走同一条路。
 */
function startPlanFromLibrary(plan: PlanLibraryEntry): void {
  if (!activeSessionId.value) {
    showToast('error', '请先选择一个会话，再从方案开工', 6000)
    return
  }
  closeFullArea()
  composerText.value = buildPlanLibraryExecutionPrompt(plan)
  void submitComposer()
}

/** 资料库阅读页的"编辑"：关掉整版界面，在文件编辑页里直接打开方案文件。 */
function openPlanFileInStage(path: string): void {
  const name = path.split('/').pop() || path
  const ext = name.includes('.') ? (name.split('.').pop() || 'md').toLowerCase() : 'md'
  closeFullArea()
  void openFileInStage({ path, name, ext })
}

/** 开工指令（资料库）：方案即「方案/」里的一篇文档，执行技能自己读回它。 */
function buildPlanLibraryExecutionPrompt(plan: PlanLibraryEntry): string {
  return [
    `执行方案《${plan.title}》（${plan.path}）。`,
    '先用 read_file 读回这份方案，对照仓库现状核对需求与步骤，有出入的地方先记下结论并更新方案文件；',
    '然后按 execute-plan 的流程把目标与步骤装进当前会话的清单，再逐步开工。',
  ].join('')
}

function toggleStage() {
  stageOpen.value = !stageOpen.value
  rightPanelMode.value = stageOpen.value ? 'files' : 'runtime'
}

function stageActivate(id: string) {
  stageActiveId.value = id
}

function stageClose(id: string) {
  const closing = stageTabs.value.find((tab) => tab.id === id)
  if (closing?.url?.startsWith('blob:')) URL.revokeObjectURL(closing.url)
  stageTabs.value = stageTabs.value.filter((t) => t.id !== id)
  if (stageActiveId.value === id) {
    stageActiveId.value = stageTabs.value[0]?.id ?? null
  }
  if (stageTabs.value.length === 0) {
    stageOpen.value = false
  }
}

function stageUpdateContent(payload: { id: string; content: string }) {
  const tab = stageTabs.value.find((t) => t.id === payload.id)
  if (tab) tab.content = payload.content
}

async function stageSave(payload: { id: string; content: string }) {
  const tab = stageTabs.value.find((t) => t.id === payload.id)
  if (!tab || !tab.path) return
  const projectId = activeProjectId.value
  if (!projectId) return
  try {
    await projectClient.writeFile(projectId, tab.path, payload.content)
    stagePaneRef.value?.onSaved()
  } catch {
    // 保存失败：复位 saving 让用户可重试，保持 dirty 状态提示未保存
    stagePaneRef.value?.resetSaving()
  }
}

function stageTogglePreview(id: string, mode: 'code' | 'preview') {
  const tab = stageTabs.value.find((t) => t.id === id)
  if (tab) tab.previewMode = mode
}

const EXT_TO_KIND: Record<string, StageKind> = {
  ts: 'code', tsx: 'code', js: 'code', jsx: 'code', mjs: 'code',
  vue: 'code', py: 'code', rs: 'code', go: 'code', java: 'code',
  json: 'code', css: 'code', scss: 'code', html: 'code',
  yaml: 'code', yml: 'code', toml: 'code', sh: 'code', sql: 'code',
  md: 'markdown',
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image',
  webp: 'image', svg: 'image', bmp: 'image', ico: 'image',
  mp4: 'video', webm: 'video', mov: 'video', avi: 'video',
  mp3: 'audio', wav: 'audio', ogg: 'audio', flac: 'audio',
  pdf: 'pdf',
}

function inferStageKind(ext: string): StageKind {
  return EXT_TO_KIND[ext] ?? 'code'
}

async function openFileInStage(entry: { path: string; name: string; ext: string }) {
  const projectId = activeProjectId.value
  if (!projectId) return
  const kind = inferStageKind(entry.ext)
  const tabId = `file:${entry.path}`
  const existing = stageTabs.value.find((t) => t.id === tabId)
  if (existing) {
    stageActiveId.value = tabId
    if (!stageOpen.value) stageOpen.value = true
    return
  }
  const tab: StageResource = {
    id: tabId,
    kind,
    path: entry.path,
    label: entry.name,
    language: entry.ext,
  }
  if (kind === 'code' || kind === 'markdown') {
    try {
      const result = await projectClient.readFile(projectId, entry.path)
      tab.content = result.content
    } catch {
      tab.content = '// 无法加载文件内容'
    }
  } else if (kind === 'image' || kind === 'video' || kind === 'audio' || kind === 'pdf') {
    try {
      const response = await projectClient.readRawFile(projectId, entry.path)
      tab.url = URL.createObjectURL(new Blob([Uint8Array.from(response.body)], {
        type: response.headers['content-type'] || 'application/octet-stream',
      }))
    } catch {
      tab.url = ''
    }
  }
  stageTabs.value.push(tab)
  stageActiveId.value = tabId
  if (!stageOpen.value) stageOpen.value = true
}

function artifactReferencePath(artifact: ProjectArtifact, revision?: ArtifactRevision): string {
  return String(revision?.path || revision?.uri || artifact.path || artifact.uri || '')
}

function artifactStageKind(artifact: ProjectArtifact, revision?: ArtifactRevision): StageKind {
  const mime = String(revision?.mime_type || artifact.mime_type || '').toLowerCase()
  if (mime.startsWith('image/')) return 'image'
  if (mime.startsWith('video/')) return 'video'
  if (mime.startsWith('audio/')) return 'audio'
  if (mime === 'application/pdf') return 'pdf'
  const name = String(revision?.name || artifact.name || artifactReferencePath(artifact, revision)).split(/[?#]/, 1)[0]
  const ext = name.split('.').pop()?.toLowerCase() || ''
  return inferStageKind(ext)
}

function artifactHttpPath(projectId: string, artifact: ProjectArtifact, revision?: ArtifactRevision): string {
  const reference = artifactReferencePath(artifact, revision)
  const revisionId = String(revision?.revision_id || revision?.id || '')
  // Artifact V2 revisions are immutable blobs. Always route an identified
  // revision through the artifact endpoint; using the workspace path here
  // would silently preview the current file instead of the selected history.
  if (artifact.artifact_id) {
    const query = new URLSearchParams()
    if (revisionId) query.set('revision_id', revisionId)
    if (reference) query.set('path', reference)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return `/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/file${suffix}`
  }
  if (reference.startsWith('attachment://')) {
    return `/attachments/${encodeURIComponent(reference.slice('attachment://'.length))}/download`
  }
  if (reference.startsWith('workspace://')) {
    return `/projects/${encodeURIComponent(projectId)}/files/raw?path=${encodeURIComponent(reference.slice('workspace://'.length))}`
  }
  return reference
    ? `/projects/${encodeURIComponent(projectId)}/files/raw?path=${encodeURIComponent(reference)}`
    : ''
}

async function openArtifactInStage(artifact: ProjectArtifact, revision?: ArtifactRevision): Promise<void> {
  const projectId = activeProjectId.value
  if (!projectId) return
  rightPanelMode.value = 'artifacts'
  const revisionId = String(revision?.revision_id || revision?.id || '')
  const tabId = `artifact:${artifact.artifact_id}${revisionId ? `:${revisionId}` : ''}`
  const existing = stageTabs.value.find(tab => tab.id === tabId)
  if (existing) {
    stageActiveId.value = tabId
    stageOpen.value = true
    return
  }
  const kind = artifactStageKind(artifact, revision)
  const reference = artifactReferencePath(artifact, revision)
  const tab: StageResource = {
    id: tabId,
    kind,
    path: reference,
    label: String(revision?.name || artifact.name || artifact.artifact_id),
  }
  const inlineContent = typeof revision?.content === 'string' ? revision.content : ''
  if (kind === 'code' || kind === 'markdown') {
    if (inlineContent) {
      tab.content = inlineContent
    } else if (reference && !reference.startsWith('attachment://') && !artifact.artifact_id && reference.startsWith('workspace://')) {
      try {
        tab.content = (await projectClient.readFile(projectId, reference.slice('workspace://'.length))).content
      } catch {
        tab.content = '// 无法加载成果内容'
      }
    } else {
      try {
        const path = artifactHttpPath(projectId, artifact, revision)
        const response = await transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path })
        if (response.status < 200 || response.status >= 300) throw new Error(`HTTP ${response.status}`)
        tab.content = new TextDecoder().decode(Uint8Array.from(response.body))
      } catch {
        tab.content = '// 无法加载成果内容'
      }
    }
  } else if (kind === 'image' || kind === 'video' || kind === 'audio' || kind === 'pdf') {
    try {
      const path = artifactHttpPath(projectId, artifact, revision)
      const response = await transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path })
      if (response.status < 200 || response.status >= 300) throw new Error(`HTTP ${response.status}`)
      tab.url = URL.createObjectURL(new Blob([Uint8Array.from(response.body)], {
        type: response.headers['content-type'] || artifact.mime_type || 'application/octet-stream',
      }))
    } catch {
      tab.url = ''
    }
  }
  stageTabs.value.push(tab)
  stageActiveId.value = tabId
  stageOpen.value = true
}
// Split key from the shell's — useShellLayout persists stageOpen/stageHeight
// under 'lamtools.core.ui'; writing the same key from here with a different
// schema silently dropped those fields on every preference save (audit 19 S3).
const uiPreferences = useCoreUiPreferences('lamtools.core.ui.preferences')
const { density, contentWidth, theme, themeMode, effectiveThemeMode } = uiPreferences
const availableModels = ref<RawModel[]>([])
const availableProviders = ref<RawProvider[]>([])
const modelGroups = ref<RawModelGroup[]>([])
const modelGroupsRevision = ref<number | undefined>(undefined)
const modelCatalogView = ref<CoreModelCatalogView>('provider')
const defaultModelId = ref('')
const permissionMode = ref<'read_only' | 'limited_edit' | 'full_edit'>('full_edit')
const defaultPermissionPreset = ref<CorePermissionPreset>('ask')
const allowAccessOutsideWorkdir = ref(false)
const { pendingAttachments, attachmentInputItems, addUploaded, markFailed, removeAttachment, clearAttachments } = usePendingAttachments()
watch(attachmentInputItems, (items) => {
  workbench.attachments.value = items
}, { immediate: true })
watch(workbench.attachments, (items) => {
  if (items.length === 0 && pendingAttachments.value.length > 0) clearAttachments()
})
const threadScrollEl = ref<HTMLElement | null>(null)
const threadBottomSentinel = ref<HTMLElement | null>(null)
const outlineNavigator = ref<{ updateScroll: () => void } | null>(null)
const latestActivityIndicator = ref<HTMLElement | null>(null)
const historyCapEl = ref<HTMLElement | null>(null)
const threadScroll = useCoreAutoFollowScroll(threadScrollEl, { sentinelRef: threadBottomSentinel })
const historyPageLoading = ref(false)
const historyPageNetworkLoading = ref(false)
const COMPOSER_MAX_ROWS = 5
let latestActivityMotion: gsap.MatchMedia | null = null
let latestActivityTween: gsap.core.Tween | null = null
let historyScrollCeiling: number | null = null
let restoringHistoryAnchor = false

function historyCapReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function cancelHistoryCapMotion(element?: Element): void {
  const target = element instanceof HTMLElement ? element : historyCapEl.value
  if (target) gsap.killTweensOf(target)
}

function enterHistoryCap(element: Element, done: () => void): void {
  const target = element as HTMLElement
  cancelHistoryCapMotion(target)
  if (historyCapReducedMotion()) {
    gsap.set(target, { autoAlpha: 1, y: 0 })
    done()
    return
  }
  gsap.fromTo(
    target,
    { autoAlpha: 0, y: -6 },
    { autoAlpha: 1, y: 0, duration: 0.18, ease: 'power2.out', onComplete: done },
  )
}

function leaveHistoryCap(element: Element, done: () => void): void {
  const target = element as HTMLElement
  cancelHistoryCapMotion(target)
  if (historyCapReducedMotion()) {
    gsap.set(target, { autoAlpha: 0, y: 0 })
    done()
    return
  }
  gsap.to(target, {
    autoAlpha: 0,
    y: -4,
    duration: 0.12,
    ease: 'power1.in',
    onComplete: done,
  })
}

interface ThreadHistoryAnchor {
  element: HTMLElement
  viewportOffset: number
}

function captureThreadHistoryAnchor(el: HTMLElement): ThreadHistoryAnchor | null {
  const viewportTop = el.getBoundingClientRect().top
  const candidates = Array.from(el.querySelectorAll<HTMLElement>('[data-message-id]'))
  const element = candidates.find(candidate => candidate.getBoundingClientRect().bottom >= viewportTop)
  if (!element) return null
  return {
    element,
    viewportOffset: element.getBoundingClientRect().top - viewportTop,
  }
}

function restoreThreadHistoryAnchor(el: HTMLElement, anchor: ThreadHistoryAnchor | null): boolean {
  if (!anchor || !anchor.element.isConnected || !el.contains(anchor.element)) return false
  const currentOffset = anchor.element.getBoundingClientRect().top - el.getBoundingClientRect().top
  const delta = currentOffset - anchor.viewportOffset
  if (Math.abs(delta) >= 0.5) el.scrollTop += delta
  return true
}

function afterHistoryLayoutFrame(): Promise<void> {
  if (typeof requestAnimationFrame !== 'function') return Promise.resolve()
  return new Promise(resolve => requestAnimationFrame(() => resolve()))
}

async function loadEarlierMessages(): Promise<void> {
  if (historyPageLoading.value || !hasMoreHistory.value) return
  const sessionId = activeSessionId.value
  if (!sessionId) return
  const el = threadScrollEl.value
  const prevScrollTop = el?.scrollTop ?? 0
  const prevHeight = el?.scrollHeight ?? 0
  const anchor = el ? captureThreadHistoryAnchor(el) : null
  historyScrollCeiling = el?.scrollTop ?? null
  historyPageLoading.value = true
  historyPageNetworkLoading.value = !historyBuffered.value
  try {
    await loadMoreHistory()
    await nextTick()
    if (activeSessionId.value !== sessionId) return
    // Preserve the first visible message at its exact viewport coordinate.
    // Unlike scrollHeight deltas this remains stable with content-visibility
    // estimates and variable-height process cards.
    if (el && el === threadScrollEl.value) {
      restoringHistoryAnchor = true
      try {
        if (!restoreThreadHistoryAnchor(el, anchor) && el.scrollHeight > prevHeight) {
          el.scrollTop = prevScrollTop + (el.scrollHeight - prevHeight)
        }
        historyScrollCeiling = el.scrollTop
        await afterHistoryLayoutFrame()
        restoreThreadHistoryAnchor(el, anchor)
        historyScrollCeiling = el.scrollTop
        threadScroll.handleScroll()
        outlineNavigator.value?.updateScroll()
      } finally {
        restoringHistoryAnchor = false
      }
    }
  } finally {
    historyScrollCeiling = null
    restoringHistoryAnchor = false
    historyPageLoading.value = false
    historyPageNetworkLoading.value = false
  }
}

function handleThreadWheel(event: WheelEvent): void {
  threadScroll.handleWheel(event)
  if (historyPageLoading.value && historyScrollCeiling !== null && event.deltaY < 0) {
    event.preventDefault()
  }
}

function handleThreadScroll(): void {
  const el = threadScrollEl.value
  if (el && !restoringHistoryAnchor) {
    const cappedScrollTop = coreApplyHistoryScrollCeiling(
      el.scrollTop,
      historyScrollCeiling,
      historyPageLoading.value,
    )
    if (cappedScrollTop !== el.scrollTop) {
      el.scrollTop = cappedScrollTop
      outlineNavigator.value?.updateScroll()
      return
    }
  }
  threadScroll.handleScroll()
  // Share the existing passive thread scroll channel with the outline rail;
  // the navigator coalesces geometry work into one animation frame.
  outlineNavigator.value?.updateScroll()
  if (!el || !coreShouldAutoLoadHistory(
    el.scrollTop,
    hasMoreHistory.value,
    historyPageLoading.value,
    coreHistoryAutoLoadThreshold(el.clientHeight),
  )) return
  void loadEarlierMessages().catch(error => setLoadError(messageFromError(error)))
}

const defaultModel = computed(() => (
  availableModels.value.find((model) => model.id === defaultModelId.value) || null
))
const executionControls = useCoreExecutionControlsState({
  models: availableModels,
  providers: availableProviders,
  groups: modelGroups,
  catalogView: modelCatalogView,
  defaultModel,
  storage: window.localStorage,
  initial: { thinkingMode: 'high', permissionPreset: defaultPermissionPreset.value },
  onPermissionPresetSelected: persistSessionPermissionPreset,
  onModelAutoReplaced: (fromModelId: string, toModelId: string) => {
    const label = (id: string) => {
      const model = availableModels.value.find((item) => item.id === id)
      return String(model?.display_name || model?.model_id || id || '')
    }
    showToast('notice', `原模型「${label(fromModelId)}」已不可用，已改用「${label(toModelId)}」`, 8000)
  },
})
const {
  modelOptions,
  selectedModelId,
  selectedThinkingMode,
  shallowThinkingEnabled,
  thinkingModeOptions,
  activeMode,
  permissionPreset,
  selectMode,
} = executionControls

const modeOptions = computed(() =>
  activePluginMode.value ? [] : [
    { value: 'consider', label: '思索' },
    { value: 'execute', label: '执行' },
  ]
)
const assistantModelLabels = computed<Record<string, string>>(() => {
  const labels: Record<string, string> = {}
  for (const model of availableModels.value) {
    const label = String(model.display_name || model.model_id || model.id || '').trim().toUpperCase()
    if (!label) continue
    for (const modelId of [model.id, model.model_id]) {
      if (modelId) labels[modelId] = label
    }
  }
  return labels
})
const runtimeModeLabel = computed(() => (
  activePluginMode.value?.title
    || modeOptions.value.find((option) => option.value === activeMode.value)?.label
    || activeMode.value
    || '模式'
))

const latestStatus = workbench.turnState
const activeTurnId = workbench.activeTurnId
const activeTurnRunning = workbench.turnActive

// 助手刚写完方案时，打开着的资料库自动刷新列表（回合收束即为信号）。
watch(activeTurnRunning, (running, previous) => {
  if (!running && previous && showLibrary.value) libraryRefreshTick.value += 1
})
const rollbackActiveTurn = computed(() => ['running', 'waiting'].includes(latestStatus.value))

function stopLatestActivityMotion(): void {
  latestActivityTween?.kill()
  latestActivityTween = null
  latestActivityMotion?.revert()
  latestActivityMotion = null
  if (latestActivityIndicator.value) {
    gsap.set(latestActivityIndicator.value, { clearProps: 'transform' })
  }
}

function syncLatestActivityMotion(): void {
  stopLatestActivityMotion()
  if (!activeTurnRunning.value) return

  void nextTick(() => {
    const target = latestActivityIndicator.value
    if (!target || !activeTurnRunning.value) return

    latestActivityMotion = gsap.matchMedia()
    latestActivityMotion.add('(prefers-reduced-motion: no-preference)', () => {
      latestActivityTween = gsap.to(target, {
        rotation: 360,
        transformOrigin: '50% 50%',
        duration: 0.9,
        ease: 'none',
        repeat: -1,
      })
      return () => {
        latestActivityTween?.kill()
        latestActivityTween = null
      }
    })
  })
}

watch([activeTurnRunning, latestActivityIndicator], syncLatestActivityMotion, { flush: 'post' })

const coreSessions = computed(() => sessions.value.filter((session) => !isInternalSession(session)))
const coreProjectGroups = computed(() => buildCoreProjectGroups(projects.value, coreSessions.value))
const showCoreStartPage = computed(() => !activePluginMode.value && !activeSessionId.value)
const shouldHideComposer = computed(() => Boolean(fullAreaView.value) || showCoreStartPage.value || readPluginSurface(activePluginSurface.value?.hideComposer, false))
const recentCoreProjects = computed<CoreRecentProject[]>(() => {
  const projectsById = new Map(projects.value.map((project) => [project.id, project]))
  return recentProjectOpenings.value.flatMap((entry): CoreRecentProject[] => {
    const project = projectsById.get(entry.id)
    return project ? [{ ...entry, name: project.name, workRoot: project.workRoot }] : []
  })
})
const sidebarGroups = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.groups, []) : coreProjectGroups.value
})
const sidebarHasProjects = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar
    ? readPluginSurface(sidebar.hasProjects, sidebarGroups.value.length > 0)
    : projects.value.length > 0
})
const sidebarActiveSessionId = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar
    ? readPluginSurface(sidebar.activeSessionId, undefined)
    : (activeSessionId.value || undefined)
})
const sidebarNewSessionLabel = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.newSessionLabel, '新建') : '新建会话'
})
const sidebarAllowProjectNewSession = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowProjectNewSession, false) : true
})
const sidebarAllowProjectDelete = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowProjectDelete, false) : true
})
const sidebarAllowProjectClick = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowProjectClick, false) : true
})
const sidebarAllowProjectContextMenu = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowProjectContextMenu, false) : true
})
const sidebarAllowSessionDelete = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowSessionDelete, false) : true
})
const sidebarAllowSessionContextMenu = computed(() => {
  const sidebar = activePluginSurface.value?.sidebar
  return sidebar ? readPluginSurface(sidebar.allowSessionContextMenu, false) : true
})
const sidebarPrimaryActionLabel = computed(() => (
  activePluginSurface.value?.sidebar
    ? readPluginSurface(activePluginSurface.value.sidebar.primaryActionLabel, '')
    : '新建项目'
))
const activeSessionTitle = computed(() => (
  sessions.value.find((session) => session.id === activeSessionId.value)?.title || 'Session'
))
const selectedProject = computed(() => (
  projects.value.find((project) => project.id === selectedProjectId.value) || null
))
const activeProjectId = computed(() => {
  const session = sessions.value.find((item) => item.id === activeSessionId.value)
  const workRoot = session?.metadata?.work_root
  if (typeof workRoot !== 'string') return null
  const project = projects.value.find((p) => p.workRoot === workRoot)
  return project?.id ?? null
})
const activeProject = computed(() => (
  projects.value.find((project) => project.id === activeProjectId.value) || null
))
const projectSettingsSessionId = computed(() => {
  if (!activeSessionId.value || selectedProject.value?.id !== activeProjectId.value) return undefined
  return activeSessionId.value
})
const projectWorkspace = createCoreProjectWorkspaceActions({
  client: projectClient,
  projects,
  sessions,
  activeSessionId,
  selectSession,
})
const busyProjectIds = projectWorkspace.busyProjectIds
const sidebarBusyProjectIds = computed(() => (
  activePluginMode.value ? [] : busyProjectIds.value
))

const liveComposerController = workbench.composer
const approvalController = workbench.approval
const queueController = workbench.queue
const {
  actionMode: composerActionMode,
  commandCatalog,
  commandPalette,
  paletteVisible: commandPaletteVisible,
} = liveComposerController
workbench.setShallowThinking(shallowThinkingEnabled.value)
workbench.setTurnOptionsProvider(async () => {
  const pluginOptions = await activePluginSurface.value?.turnOptions?.() || {}
  const {
    permission_preset: _permissionPreset,
    active_tier: _activeTier,
    tier_tools: _tierTools,
    approval_policy: _approvalPolicy,
    allow_access_outside_workdir: _allowOutsideWorkdir,
    ...safePluginOptions
  } = pluginOptions
  return { ...executionControls.turnOptions(), ...safePluginOptions }
})
workbench.setComposerCallbacks({
  onError: (text) => { composerErrorText.value = text },
  onStatusText: setRuntimeStatus,
  onTurnStarted: refreshSessions,
  onSubmitStart: () => {
    pendingPlaceholder.value = { id: `placeholder-${Date.now()}`, content: '…' }
  },
  onCommandResult: applyCommandEffects,
})
watch(shallowThinkingEnabled, (value) => workbench.setShallowThinking(value))
const composerHighlightSegments = computed(() => (
  buildCoreComposerHighlightSegments(composerText.value, commandCatalog.value)
))
const hasComposerRecognizedCommand = computed(() => (
  composerHighlightSegments.value.some((segment) => segment.command)
  && composerHighlightSegments.value.every((segment) => segment.command || !segment.text.trim())
))

const { activeGoal, goalError, refreshGoal, handleCancelGoal } = useCoreGoals({
  activeSessionId,
  requestRpc: appRuntime.requestRpc,
})
const { messages, processExpandedIds, toggleProcess, hasMoreHistory, historyBuffered, loadMoreHistory } = workbench
const historyLoading = computed(() => (
  Boolean(activeSessionId.value)
  && historyLoadingSessionId.value === activeSessionId.value
))
const isEmptySession = computed(() => (
  Boolean(activeSessionId.value)
  && !activePluginMode.value
  && !historyLoading.value
  && messages.value.length === 0
))
const EMPTY_SESSION_GREETINGS = ['就当给自己放个假', '芜湖，我来帮忙咯!'] as const
const pickEmptySessionGreeting = () => (
  EMPTY_SESSION_GREETINGS[Math.floor(Math.random() * EMPTY_SESSION_GREETINGS.length)]
)
const emptySessionGreeting = ref<(typeof EMPTY_SESSION_GREETINGS)[number]>(pickEmptySessionGreeting())
watch([activeSessionId, isEmptySession], ([sessionId, empty], [previousSessionId, previousEmpty]) => {
  if (empty && (!previousEmpty || sessionId !== previousSessionId)) {
    emptySessionGreeting.value = pickEmptySessionGreeting()
  }
})

const pendingPlaceholder = ref<{ id: string; content: string } | null>(null)
const stepGroups = computed(() => buildCurrentTurnChecklistGroups(messages.value))

// Checkpoint state still powers the checkpoint graph surfaces, but the
// edit/fork/rollback entries no longer depend on it: a normal user message is
// always actionable unless it predates the last context compaction.
const checkpointController = useCheckpoints(requestConfigOperation)
// Messages the backend already replaced with a context summary: their original
// text is gone, so edit/fork/rollback must not be offered.
const lockedMessageIds = computed(() => lockedMessageIdsBeforeCompaction(messages.value))

provideCorePluginModeContext({
  transport,
  requestRpc: requestConfigOperation,
  requestDirectRpc: (method, params) => appRuntime.requestRpc(method, params || {}),
  projectClient,
  projects,
  sessions,
  selectedProjectId,
  activeSessionId,
  selectedProject,
  activeProjectId,
  activeProject,
  currentWorkRoot,
  setSelectedProjectId: (id) => { selectedProjectId.value = id },
  selectSession,
  refreshSessions,
  setRuntimeStatus,
  availableModels,
  selectedModelId,
  permissionPreset,
  composerText,
  ensureRightPanelOpen,
  lastEvent,
  chat: {
    hasMoreHistory,
    loadMoreHistory,
    messages,
    processExpandedIds,
    toggleProcess,
    activeTurnId,
    activeTurnRunning,
    lockedMessageIds,
    onDecisionSelect: async (payload) => {
      await approvalController.handleDecision(
        payload as Parameters<typeof approvalController.handleDecision>[0],
      )
    },
    onForkMessage: (payload) => handleForkMessage(
      payload as Parameters<typeof handleForkMessage>[0],
    ),
    onRollbackMessage: (payload) => handleRollbackMessage(
      payload as Parameters<typeof handleRollbackMessage>[0],
    ),
    onEditMessage: (payload) => handleEditMessage(
      payload as Parameters<typeof handleEditMessage>[0],
    ),
  },
}, pluginModeRuntime)
// Each error source feeds the toast service via watch; the service handles
// auto-expiry (8s for errors) and de-duplication, so nothing stays pinned.
watch(loadError, (value) => { if (value) connectionErrorToastGate.report(value, 8000) })
watch(composerErrorText, (value) => { if (value) connectionErrorToastGate.report(value, 8000) })
watch(() => approvalController.lastError.value, (value) => { if (value) connectionErrorToastGate.report(value, 8000) })
watch(goalError, (value) => { if (value) connectionErrorToastGate.report(value, 8000) })

const queuedInputs = workbench.queuedInputs
const editingQueuedInputId = queueController.editingId
const queuedInputDraft = queueController.draft
const canGuideQueuedInput = queueController.canGuide

async function loadInitialData() {
  try {
    loadError.value = null
    await Promise.all([
      loadModelOptions(),
      loadModelGroups(),
      loadModelCatalogPreference(),
      loadPermissionMode(),
      refreshProjects(),
      refreshSessions(),
    ])
    await refreshPluginModes()
    if (coreSessions.value[0]) {
      await selectSession(coreSessions.value[0].id)
    } else if (projects.value[0]) {
      selectedProjectId.value = projects.value[0].id
    }
  } catch (error) {
    setLoadError(error instanceof Error ? error.message : String(error))
  }
}

async function refreshProjects() {
  projects.value = await projectClient.list()
}

function handleProjectsSynced(): void {
  void refreshProjects()
}

async function refreshSessions() {
  const loaded = (await requestJson<RawSession[]>('/sessions')).map(toSession)
  // The server session list is authoritative here. The workbench watches the
  // active snapshot and applies live status changes separately, so a delayed
  // refresh cannot freeze the sidebar at the status seen during turn/start.
  sessions.value = loaded
}

function openProjectCreate() {
  projectCreateError.value = ''
  showProjectCreate.value = true
}

function closeProjectCreate() {
  if (projectCreateLoading.value) return
  projectCreateError.value = ''
  showProjectCreate.value = false
}

async function createProject(payload: CoreProjectCreatePayload) {
  projectCreateLoading.value = true
  projectCreateError.value = ''
  try {
    const created = await projectWorkspace.createProject(payload)
    selectedProjectId.value = created.project.id
    rememberRecentProject(created.project)
    showProjectCreate.value = false
  } catch (error) {
    projectCreateError.value = messageFromError(error)
  } finally {
    projectCreateLoading.value = false
  }
}

async function createProjectSession(projectId: string) {
  try {
    await projectWorkspace.createProjectSession(projectId)
  } catch (error) {
    composerErrorText.value = messageFromError(error)
  }
}

function openProjectActions(projectId: string) {
  const project = projects.value.find((item) => item.id === projectId)
  if (!project) return
  selectedProjectId.value = project.id
  projectNameDraft.value = project.name
  projectActionError.value = ''
  showProjectSettings.value = true
  // Load AGENTS.md content for the in-place editor inside project settings.
  void loadAgentsForProject(project.id)
}

function openProjectRename(projectId: string): void {
  openProjectActions(projectId)
  void nextTick(() => {
    const input = document.querySelector<HTMLInputElement>('[data-project-name-input]')
    input?.focus()
    input?.select()
  })
}

async function createStartPageSession(): Promise<void> {
  const project = projects.value.find((item) => item.id === selectedProjectId.value)
    || projects.value[0]
  if (!project) return
  selectedProjectId.value = project.id
  rememberRecentProject(project)
  await createProjectSession(project.id)
}

async function openRecentProject(projectId: string): Promise<void> {
  const project = projects.value.find((item) => item.id === projectId)
  if (!project) return
  selectedProjectId.value = project.id
  rememberRecentProject(project)
  const session = coreSessions.value
    .filter((item) => item.metadata?.work_root === project.workRoot)
    .sort((left, right) => String(right.updatedAt || right.createdAt).localeCompare(String(left.updatedAt || left.createdAt)))[0]
  if (session) {
    await selectSession(session.id)
  } else {
    await createProjectSession(project.id)
  }
}

async function openProject(projectId: string): Promise<void> {
  await Promise.all([refreshProjects(), refreshSessions()])
  await openRecentProject(projectId)
}

async function selectRegisteredProject(projectId: string): Promise<void> {
  showProjectPicker.value = false
  await openRecentProject(projectId)
}

async function loadAgentsForProject(projectId: string) {
  agentsLoading.value = true
  agentsError.value = ''
  try {
    const agents = await projectWorkspace.readAgents(projectId)
    agentsProjectId.value = projectId
    agentsContent.value = agents.content
  } catch (error) {
    agentsError.value = messageFromError(error)
  } finally {
    agentsLoading.value = false
  }
}

async function renameProject(nameFromEditor?: string) {
  const project = selectedProject.value
  if (nameFromEditor !== undefined) projectNameDraft.value = nameFromEditor
  const name = projectNameDraft.value.trim()
  if (!project || !name || projectActionLoading.value) return
  if (name === project.name) {
    projectNameDraft.value = project.name
    return
  }
  projectActionLoading.value = true
  projectActionError.value = ''
  try {
    const updated = await projectWorkspace.renameProject(project.id, name)
    projectNameDraft.value = updated.name
  } catch (error) {
    projectActionError.value = messageFromError(error)
  } finally {
    projectActionLoading.value = false
  }
}

async function deleteProject(projectId: string) {
  const project = projects.value.find((item) => item.id === projectId)
  if (!project || !window.confirm(`确定删除项目「${project.name}」及其会话记录？此操作不可撤销。`)) return
  projectActionLoading.value = true
  projectActionError.value = ''
  try {
    const deleted = await projectWorkspace.deleteProject(project.id)
    if (!deleted) return
    if (selectedProjectId.value === project.id) selectedProjectId.value = null
    if (agentsProjectId.value === project.id) { agentsProjectId.value = null; agentsContent.value = '' }
    if (showProjectSettings.value) closeProjectSettings()
    if (deleted.wasActive) {
      workbench.disconnect()
      liveComposerController.resetForThreadChange()
      activeSessionId.value = null
      if (coreSessions.value[0]) await selectSession(coreSessions.value[0].id)
    }
  } catch (error) {
    projectActionError.value = messageFromError(error)
  } finally {
    projectActionLoading.value = false
  }
}

function closeProjectSettings() {
  showProjectSettings.value = false
}

async function refreshAgentsContent() {
  const projectId = agentsProjectId.value || selectedProjectId.value
  if (!projectId) return
  await loadAgentsForProject(projectId)
}

async function saveAgents(content: string) {
  const projectId = agentsProjectId.value
  if (!projectId) return
  agentsSaving.value = true
  agentsError.value = ''
  try {
    const agents = await projectWorkspace.writeAgents(projectId, content)
    agentsContent.value = agents.content
    setRuntimeStatus('AGENTS.md 已保存')
  } catch (error) {
    agentsError.value = messageFromError(error)
  } finally {
    agentsSaving.value = false
  }
}

async function renameSession(sessionId: string, title: string) {
  const updated = toSession(await requestJson<RawSession>(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: { title },
  }))
  sessions.value = sessions.value.map((session) => session.id === sessionId ? updated : session)
}

async function updateProjectVisual(iconKey: CoreProjectIconKey, colorKey: CoreProjectColorKey) {
  const project = selectedProject.value
  if (!project || projectActionLoading.value) return
  if (project.iconKey === iconKey && project.colorKey === colorKey) return
  projectActionLoading.value = true
  projectActionError.value = ''
  try {
    await projectWorkspace.updateProject(project.id, {
      icon_key: iconKey,
      color_key: colorKey,
    })
  } catch (error) {
    projectActionError.value = messageFromError(error)
  } finally {
    projectActionLoading.value = false
  }
}

async function renameSessionFromSidebar(sessionId: string, title: string): Promise<void> {
  try {
    await renameSession(sessionId, title)
    setRuntimeStatus('会话已重命名')
  } catch (error) {
    composerErrorText.value = messageFromError(error)
  }
}

async function renameActiveSession(title: string) {
  if (!activeSessionId.value) return
  await renameSession(activeSessionId.value, title)
}

function sessionExportExtension(format: SessionExportFormat): SessionExportExtension {
  if (format === 'markdown') return 'md'
  if (format === 'handoff') return 'json'
  return format
}

function exportFileStem(title: string, sessionId: string): string {
  const fallback = `Session-${sessionId.slice(0, 8)}`
  const clean = title
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, '_')
    .replace(/[. ]+$/g, '')
    .slice(0, 80)
  return clean && clean !== '.' && clean !== '..' ? clean : fallback
}

function localDateStamp(date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

async function exportSession(sessionId: string, format: SessionExportFormat): Promise<void> {
  const session = sessions.value.find((item) => item.id === sessionId)
  const title = session?.title || `Session ${sessionId.slice(0, 8)}`
  const mode = format === 'zip' ? 'full' : format === 'handoff' ? 'handoff' : 'transcript'
  const outputFormat = format === 'zip' ? 'zip' : format === 'handoff' ? 'json' : format

  try {
    const response = await appRuntime.request({
      kind: 'http',
      method: 'POST',
      path: `/sessions/${encodeURIComponent(sessionId)}/export`,
      headers: { 'Content-Type': 'application/json' },
      body: new TextEncoder().encode(JSON.stringify({ mode, format: outputFormat })),
    })
    if (response.status < 200 || response.status >= 300) {
      const errorText = new TextDecoder().decode(response.body)
      throw new Error(errorText || `导出失败（${response.status}）`)
    }

    const blob = new Blob([Uint8Array.from(response.body)], {
      type: response.headers['content-type'] || 'application/octet-stream',
    })
    const extension = sessionExportExtension(format)
    const suffix = format === 'handoff' ? '-handoff' : ''
    const filename = `${exportFileStem(title, sessionId)}-${localDateStamp()}${suffix}.${extension}`
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
    setRuntimeStatus(`已导出：${filename}`)
  } catch (error) {
    composerErrorText.value = messageFromError(error)
  }
}

async function deleteSession(sessionId: string) {
  const session = sessions.value.find((item) => item.id === sessionId)
  const title = session?.title || `Session ${sessionId.slice(0, 8)}`
  if (!window.confirm(`确定删除会话「${title}」？会话、历史、checkpoint、附件记录都会删除。此操作不可撤销。`)) return

  try {
    await requestJson(`/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
  } catch (error) {
    composerErrorText.value = error instanceof Error ? error.message : String(error)
    return
  }
  const deletedActiveSession = activeSessionId.value === sessionId
  if (deletedActiveSession) {
    workbench.disconnect()
    liveComposerController.resetForThreadChange()
    activeSessionId.value = null
  }
  await refreshSessions()
  if (deletedActiveSession && coreSessions.value[0]) await selectSession(coreSessions.value[0].id)
}

async function selectSession(id: string) {
  const session = sessions.value.find((item) => item.id === id)
  historyLoadingSessionId.value = id
  activeSessionId.value = id
  if (!isInternalSession(session)) {
    const workRoot = session?.metadata?.work_root
    const project = typeof workRoot === 'string'
      ? projects.value.find((item) => item.workRoot === workRoot)
      : undefined
    if (project) {
      selectedProjectId.value = project.id
      rememberRecentProject(project)
    }
  }
  restoreSessionModel(id)
  restoreSessionPermissionPreset(id)
  liveComposerController.resetForThreadChange()
  composerErrorText.value = ''
  setRuntimeStatus('', 0)
  threadScroll.reset() // invalidate in-flight scrolls from the previous session
  try {
    await connectLive(id)
  } finally {
    if (historyLoadingSessionId.value === id) historyLoadingSessionId.value = null
  }
  const sessionMetadataReady = Promise.all([
    liveComposerController.loadCommandCatalog(id),
    refreshGoal(id, true),
  ])
  checkpointController.reset()
  checkpointController.beginLoading()
  // Legacy user-message editing still uses a pre-turn checkpoint.  Failure
  // here is deliberately isolated from assistant Fork/Rollback.
  void checkpointController.load(id)
  await Promise.all([
    sessionMetadataReady,
    threadScroll.scrollToBottom(true),
  ])
}

// ── 全局搜索跳转（SearchShell 会话命中 → 打开会话 + 消息锚点定位）──
async function jumpToSearchedMessage(sessionId: string, messageId: string): Promise<void> {
  if (activeSessionId.value !== sessionId) {
    await selectSession(sessionId)
  }
  await locateMessage(messageId)
}

/** Study entities share the global SearchShell. The Study mode owns only the
 * entity-specific resolution after the host has switched modes. */
async function jumpToStudySearchHit(hit: StudySearchHit): Promise<void> {
  if (hit.session_id && hit.message_id) {
    await jumpToSearchedMessage(hit.session_id, hit.message_id)
    return
  }
  const mode = appModes.value.find(candidate => candidate.pluginId === 'study')
  if (!mode) return
  await selectAppMode(mode)
  await nextTick()
  window.dispatchEvent(new CustomEvent('lamtools:study-search-hit', { detail: hit }))
}

function isStudyOwnedSessionId(sessionId: string): boolean {
  if (sessionId === 'study:main') return true
  const session = sessions.value.find(item => item.id === sessionId)
  return session?.metadata?.owner_plugin === 'study'
}

async function jumpToStudyMark(anchor: MarkAnchor): Promise<void> {
  if (anchor.session_id && isStudyOwnedSessionId(anchor.session_id)) {
    const mode = appModes.value.find(m => m.pluginId === 'study')
    if (!mode) throw new Error('Study 未启用')
    await selectAppMode(mode)
    await nextTick()
    selectionEvents.dispatchEvent(new Event('study-chat'))
  } else if (anchor.session_id) {
    await selectAppMode(coreAppMode)
  }
  if (anchor.session_id && anchor.source_type === 'message') {
    await jumpToSearchedMessage(anchor.session_id, anchor.document_id)
  }
}

function locateScrollBehavior(): ScrollBehavior {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ? 'auto'
    : 'smooth'
}

/** 定位消息：轮询目标 DOM（窗口未含则逐步加载更早历史），
 * 命中 → scrollIntoView 居中 + 高亮渐隐（2.6s）。找不到给出提示。 */
async function locateMessage(messageId: string): Promise<void> {
  const selector = `[data-message-id="${CSS.escape(messageId)}"]`
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const el = document.querySelector<HTMLElement>(selector)
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: locateScrollBehavior() })
      el.classList.add('rag-hit-highlight')
      window.setTimeout(() => el.classList.remove('rag-hit-highlight'), 2600)
      return
    }
    if (hasMoreHistory.value) {
      await loadMoreHistory()
      await nextTick()
      await new Promise((resolve) => setTimeout(resolve, 150))
      continue
    }
    break
  }
  showToast('error', '未找到该消息（可能已被删除或属于子会话）', 5000)
}

/** Locate a Sub Agent's source part, expanding its parent process and child
 * timeline before centering and focusing the heading for keyboard users. */
async function locateSubAgentRun(run: CoreSubAgentRun): Promise<void> {
  const messageId = String(run.sourceMessageId || '').trim()
  const sourcePartId = String(run.sourcePartId || '').trim()
  // Remote durable snapshots may only have a source part/call id.  Search the
  // currently mounted transcript first so these rows remain navigable even
  // when the parent message id was generated by an older protocol version.
  if (!messageId && sourcePartId) {
    const directPart = document.querySelector<HTMLElement>(`[data-part-id="${CSS.escape(sourcePartId)}"]`)
    if (directPart) {
      await focusSubAgentSource(directPart)
      return
    }
  }
  if (!messageId) return
  await locateMessage(messageId)
  await nextTick()
  if (!processExpandedIds.value.has(messageId)) toggleProcess(messageId)
  await nextTick()
  const message = document.querySelector<HTMLElement>(`[data-message-id="${CSS.escape(messageId)}"]`)
  if (!message) return
  const part = sourcePartId
    ? message.querySelector<HTMLElement>(`[data-part-id="${CSS.escape(sourcePartId)}"]`)
      || document.querySelector<HTMLElement>(`[data-part-id="${CSS.escape(sourcePartId)}"]`)
    : null
  if (!part) {
    message.scrollIntoView({ block: 'center', behavior: locateScrollBehavior() })
    return
  }
  await focusSubAgentSource(part)
}

async function focusSubAgentSource(part: HTMLElement): Promise<void> {
  const heading = part.querySelector<HTMLButtonElement>('.sub-line-heading')
  if (heading && !part.querySelector('.sub-line-body')) {
    heading.click()
    await nextTick()
  }
  const target = (part.querySelector<HTMLElement>('.sub-line-heading') || part)
  target.scrollIntoView({ block: 'center', behavior: locateScrollBehavior() })
  target.classList.remove('sub-agent-source-highlight')
  target.classList.add('sub-agent-source-highlight')
  window.setTimeout(() => target.classList.remove('sub-agent-source-highlight'), 1200)
  if (target instanceof HTMLButtonElement) target.focus({ preventScroll: true })
}

// Session-scoped model memory: each session remembers its own model choice,
// so switching sessions restores that session's model instead of sharing a
// single global selection. The chosen model is persisted into the session's
// metadata by the selectedModelId watcher below.
function restoreSessionModel(id: string) {
  const session = sessions.value.find((item) => item.id === id)
  if (isPluginOwnedSession(session)) return
  const storedModelId = session?.metadata?.model_id
  if (
    typeof storedModelId === 'string'
    && storedModelId
    && availableModels.value.some((model) => model.id === storedModelId)
  ) {
    executionControls.selectModel(storedModelId)
  }
}

async function refreshAfterRollback() {
  const sessionId = activeSessionId.value
  if (!sessionId) return
  await refreshSessions()
  await selectSession(sessionId)
  await checkpointController.load(sessionId)
}

async function handleForkMessage(payload: { turnId: string; content: string }) {
  const sessionId = activeSessionId.value
  if (!sessionId) {
    composerErrorText.value = '当前没有可分叉的会话'
    return
  }
  if (rollbackActiveTurn.value) {
    composerErrorText.value = '任务运行中，请先停止任务再分叉'
    return
  }
  try {
    const result = await requestConfigOperation('session.fork', {
      session_id: sessionId,
      turn_id: payload.turnId,
    })
    const forkedSessionId = String(result?.session_id || '')
    await refreshSessions()
    if (forkedSessionId) await selectSession(forkedSessionId)
    showToast('notice', '已从此处创建分叉会话；仅复制对话历史，未复制工作区或运行时状态。')
  } catch (error) {
    composerErrorText.value = error instanceof Error ? error.message : String(error)
  }
}

async function handleRollbackMessage(payload: { turnId: string; content: string }) {
  const sessionId = activeSessionId.value
  if (!sessionId) {
    composerErrorText.value = '当前没有可回退的会话'
    return
  }
  if (rollbackActiveTurn.value) {
    composerErrorText.value = '任务运行中，请先停止任务再回退'
    return
  }
  if (!window.confirm('删除这条消息及之后的全部对话？有可用检查点时会一并恢复文件；没有则只清对话。')) return
  try {
    const result = await requestConfigOperation('session.rollback', {
      session_id: sessionId,
      turn_id: payload.turnId,
    })
    await refreshAfterRollback()
    if (result.mode === 'checkpoint') {
      showToast('notice', '已删除此轮及之后内容：对话、运行时和工作区已恢复。')
    } else {
      showToast('notice', '已删除此轮及之后对话；文件、运行时和外部操作未恢复。')
    }
  } catch (error) {
    composerErrorText.value = error instanceof Error ? error.message : String(error)
  }
}

async function handleEditMessage(payload: { turnId: string; content: string; attachments?: CoreAttachment[] }) {
  const sessionId = activeSessionId.value
  if (!sessionId) {
    composerErrorText.value = '当前没有可编辑的会话'
    return
  }
  if (rollbackActiveTurn.value) {
    composerErrorText.value = '任务运行中，请先停止任务再编辑'
    return
  }
  if (!payload.turnId) {
    composerErrorText.value = '这条消息没有可用的回合'
    return
  }
  try {
    // 就地清空这条用户消息及其之后的对话，再以编辑后的内容重发：不依赖检查点，
    // 所以第一条消息也能编辑。会话标题不被改写 —— 原标题原样保留；若原标题是
    // 默认值（缺失/「新会话」/会话 id），重发时走首次消息的正常命名路径重新生成。
    await requestConfigOperation('session.rollback', {
      session_id: sessionId,
      turn_id: payload.turnId,
    })
    await refreshAfterRollback()
    // 携带原消息附件（已在后端上传，直接标记 uploaded 随发送提交，无需重新上传）
    clearAttachments()
    for (const attachment of payload.attachments ?? []) {
      addUploaded({ ...attachment, status: 'uploaded' })
    }
    composerText.value = payload.content
    await submitComposer()
  } catch (error) {
    composerErrorText.value = error instanceof Error ? error.message : String(error)
  }
}

async function connectLive(threadId: string) {
  await workbench.connect(threadId)
}

/**
 * Composer decision panel → the same payload shape the in-thread card emits, so
 * both surfaces share one decision channel (nothing new on the wire).
 */
async function handlePendingDecisionSelect(payload: {
  partId: string
  option: { id?: string; label?: string; response?: string }
  response: string
}) {
  await approvalController.handleDecision(payload)
}

async function submitComposer() {
  composerErrorText.value = ''
  // 停止模式：composer 必为空，须在空文本守卫之前处理，否则 stop 请求永远发不出去
  if (composerActionMode.value === 'stop') {
    try {
      await liveComposerController.submit({ clearComposer: false })
    } catch {
      // error handled by controller
    }
    return
  }
  const text = composerText.value.trim()
  const attachmentOnly = activePluginMode.value
    ? readPluginSurface(activePluginSurface.value?.allowAttachmentOnlySubmit, false)
    : true
  if (!text && !(attachmentOnly && pendingAttachments.value.length)) return

  // No model to inherit and none configured: fail with an explicit prompt
  // instead of sending a turn that would be silently routed to some default.
  if (!activePluginMode.value && availableModels.value.length === 0) {
    showToast('error', '请先添加供应商/模型（设置 → 模型与供应商）', 8000)
    return
  }

  sendingDisabled.value = true

  try {
    await liveComposerController.submit({ clearComposer: true })
  } catch {
    // error handled by controller
  } finally {
    sendingDisabled.value = false
  }
}


async function uploadFiles(files: FileList | File[]) {
  const sessionId = activeSessionId.value
  if (!sessionId) {
    composerErrorText.value = '请先选择会话'
    return
  }
  for (const file of Array.from(files)) {
    const failedId = `failed:${file.name}:${Date.now()}`
    try {
      const projectQuery = !activePluginMode.value && activeProjectId.value
        ? `?project_id=${encodeURIComponent(activeProjectId.value)}`
        : ''
      const multipart = await encodeMultipartFile(file)
      const response = await appRuntime.request({
        kind: 'http',
        method: 'POST',
        path: `/sessions/${encodeURIComponent(sessionId)}/attachments${projectQuery}`,
        headers: { 'Content-Type': multipart.contentType },
        body: multipart.body,
      })
      if (response.status < 200 || response.status >= 300) {
        throw new Error(new TextDecoder().decode(response.body) || '上传失败')
      }
      addUploaded(JSON.parse(new TextDecoder().decode(response.body)) as CoreAttachment)
    } catch (error) {
      markFailed(failedId, file.name, messageFromError(error))
      composerErrorText.value = `附件上传失败：${file.name}`
    }
  }
}

async function chooseAttachments(source: RuntimeFileSource = 'file') {
  const picker = appRuntime.capabilities.files
  if (!picker) {
    composerErrorText.value = '当前环境不支持附件选择'
    return
  }
  try {
    const files = await picker.pick({
      source,
      multiple: source !== 'camera',
      accept: source === 'photos' || source === 'camera' ? 'image/*' : undefined,
    })
    if (files?.length) await uploadFiles(files)
  } catch (error) {
    const message = messageFromError(error)
    composerErrorText.value = message === '设备拒绝了您的请求'
      ? message
      : `打开附件选择器失败：${message}`
  }
}

function handleComposerDrop(event: DragEvent) {
  if (event.dataTransfer?.files.length) void uploadFiles(event.dataTransfer.files)
}

// ── 全窗口拖拽上传：window 级 dragover 亮起遮罩，drop 统一走遮罩上传 ──
const dragActive = ref(false)

function handleWindowDragOver(event: DragEvent) {
  // 仅拦截文件拖拽；插件视图内部拖拽、文本拖选等不干预
  if (event.dataTransfer?.types.includes('Files')) {
    event.preventDefault()
    dragActive.value = true
  }
}

function handleWindowDragLeave(event: DragEvent) {
  // relatedTarget 为 null 表示已拖出窗口（子元素间移动不熄灭）
  if (!event.relatedTarget) dragActive.value = false
}

function handleWindowDrop() {
  // 兜底熄灭：drop 已由目标元素（遮罩/composer）处理上传，这里只保证遮罩收起
  dragActive.value = false
}

function handleAttachmentDrop(event: DragEvent) {
  dragActive.value = false
  if (event.dataTransfer?.files.length) void uploadFiles(event.dataTransfer.files)
}

// ── 粘贴上传：输入框聚焦时 Ctrl+V 图片/文件 → 复用上传管线；纯文本不受影响 ──
function handleComposerPaste(event: ClipboardEvent) {
  const files: File[] = []
  const items = event.clipboardData?.items
  if (items) {
    for (const item of Array.from(items)) {
      if (item.kind === 'file') {
        const file = item.getAsFile()
        if (file) files.push(file)
      }
    }
  }
  // 兜底：items 拿不到时（个别 WebView）退回 files 列表
  if (!files.length) {
    const dropped = event.clipboardData?.files
    if (dropped?.length) files.push(...Array.from(dropped))
  }
  if (files.length) void uploadFiles(files)
}

function retryPendingAttachment(id: string) {
  removeAttachment(id)
  void chooseAttachments()
}

async function previewPendingAttachment(id: string) {
  if (id.startsWith('failed:')) return
  const response = await appRuntime.request({
    kind: 'http',
    method: 'GET',
    path: `/attachments/${encodeURIComponent(id)}/preview`,
  })
  setRuntimeStatus(response.status >= 200 && response.status < 300 ? '附件预览已读取' : '附件预览失败')
}

async function openPendingAttachment(id: string) {
  if (id.startsWith('failed:')) return
  const response = await appRuntime.request({
    kind: 'http',
    method: 'POST',
    path: `/attachments/${encodeURIComponent(id)}/open`,
  })
  if (response.status < 200 || response.status >= 300) setRuntimeStatus('打开附件失败')
}

async function handleComposerKeydown(event: KeyboardEvent) {
  if (sendingDisabled.value) return
  updateComposerCursor()
  await liveComposerController.handleKeydown(event)
}

async function handleComposerKeyup(event: KeyboardEvent) {
  if (sendingDisabled.value) return
  updateComposerCursor()
  await liveComposerController.handleKeyup(event)
}

function handleComposerInput() {
  composerErrorText.value = ''
  resizeComposerTextarea()
  updateComposerCursor()
}

function updateComposerCursor() {
  composerCursor.value = composerTextareaEl.value?.selectionStart ?? composerText.value.length
}

type ComposerSelection = {
  start: number
  end: number
  direction: 'forward' | 'backward' | 'none'
  value: string
}

function restoreComposerSelection(selection: ComposerSelection): HTMLTextAreaElement | null {
  const textarea = composerTextareaEl.value
  if (!textarea) return null
  textarea.focus({ preventScroll: true })
  textarea.setSelectionRange(selection.start, selection.end, selection.direction)
  return textarea
}

function replaceComposerSelection(selection: ComposerSelection, replacement: string): void {
  if (composerText.value !== selection.value) return
  composerText.value = `${selection.value.slice(0, selection.start)}${replacement}${selection.value.slice(selection.end)}`
  composerErrorText.value = ''
  const cursor = selection.start + replacement.length
  composerCursor.value = cursor
  void nextTick(() => {
    const textarea = composerTextareaEl.value
    if (!textarea) return
    textarea.focus({ preventScroll: true })
    textarea.setSelectionRange(cursor, cursor)
    resizeComposerTextarea()
  })
}

async function copyComposerSelection(selection: ComposerSelection): Promise<boolean> {
  const selectedText = selection.value.slice(selection.start, selection.end)
  if (!selectedText) return false
  try {
    await copyText(selectedText)
    restoreComposerSelection(selection)
    return true
  } catch {
    showToast('error', '复制失败：当前环境无法访问剪贴板')
    return false
  }
}

async function cutComposerSelection(selection: ComposerSelection): Promise<void> {
  if (composerInputDisabled.value || !await copyComposerSelection(selection)) return
  replaceComposerSelection(selection, '')
}

async function pasteIntoComposer(selection: ComposerSelection): Promise<void> {
  if (composerInputDisabled.value) return
  try {
    if (!navigator.clipboard?.readText) throw new Error('clipboard unavailable')
    const clipboardText = await navigator.clipboard.readText()
    replaceComposerSelection(selection, clipboardText)
  } catch {
    showToast('error', '粘贴失败：当前环境无法读取剪贴板')
  }
}

function selectAllComposerText(selection: ComposerSelection): void {
  const textarea = restoreComposerSelection(selection)
  textarea?.select()
  composerCursor.value = selection.value.length
}

function openComposerContextMenu(event: MouseEvent): void {
  // On Android, leave textarea editing to the native menu. The custom Paste
  // action reads navigator.clipboard, which WebView may deny even for a tap.
  if (appRuntime.platform === 'mobile') return
  const textarea = composerTextareaEl.value
  if (!textarea) return
  const selection: ComposerSelection = {
    start: textarea.selectionStart,
    end: textarea.selectionEnd,
    direction: textarea.selectionDirection,
    value: textarea.value,
  }
  const hasSelection = selection.start !== selection.end
  const items: ContextMenuEntry[] = [
    {
      id: 'composer-cut',
      label: '剪切',
      icon: Scissors,
      shortcut: 'Ctrl+X',
      disabled: composerInputDisabled.value || !hasSelection,
      action: () => cutComposerSelection(selection),
    },
    {
      id: 'composer-copy',
      label: '复制',
      icon: Copy,
      shortcut: 'Ctrl+C',
      disabled: !hasSelection,
      action: () => copyComposerSelection(selection),
    },
    {
      id: 'composer-paste',
      label: '粘贴',
      icon: ClipboardPaste,
      shortcut: 'Ctrl+V',
      disabled: composerInputDisabled.value,
      action: () => pasteIntoComposer(selection),
    },
    { type: 'separator', id: 'composer-edit-separator' },
    {
      id: 'composer-select-all',
      label: '全选',
      icon: TextSelect,
      shortcut: 'Ctrl+A',
      disabled: !selection.value,
      action: () => selectAllComposerText(selection),
    },
  ]
  openContextMenu({
    event,
    items,
    ownerId: 'composer-input',
    ariaLabel: '输入框编辑操作',
    panelAttributes: { 'data-composer-context-menu': true },
  })
}

function focusComposer(cursor: number) {
  void nextTick(() => {
    const textarea = composerTextareaEl.value
    if (!textarea) return
    textarea.focus()
    textarea.setSelectionRange(cursor, cursor)
  })
}

function clearComposerAfterPersisted(expectedText: string) {
  if (composerText.value.trim() !== expectedText) return
  composerText.value = ''
  void nextTick(resizeComposerTextarea)
}

function resizeComposerTextarea() {
  const element = composerTextareaEl.value
  if (!element) return
  element.style.height = 'auto'
  const style = window.getComputedStyle(element)
  const lineHeight = Number.parseFloat(style.lineHeight) || 22
  const paddingTop = Number.parseFloat(style.paddingTop) || 0
  const paddingBottom = Number.parseFloat(style.paddingBottom) || 0
  const maxHeight = lineHeight * COMPOSER_MAX_ROWS + paddingTop + paddingBottom
  element.style.height = `${Math.min(element.scrollHeight, maxHeight)}px`
  element.style.overflowY = element.scrollHeight > maxHeight ? 'auto' : 'hidden'
}

function setShallowThinking(enabled: boolean) {
  shallowThinkingEnabled.value = enabled
}

async function createProvider(payload: CoreSettingsProviderPayload) {
  try {
    loadError.value = null
    const result = await requestConfigOperation('config.provider.create', payload as unknown as Record<string, unknown>)
    await loadModelOptions()
    if (payload.model_group_name) await ensureCreatedModelsInGroup(payload.model_group_name, result)
    setRuntimeStatus('供应商已添加')
  } catch (error) {
    setLoadError(error instanceof Error ? error.message : String(error))
  }
}

// ---- 首次启动引导 ----

async function checkOnboarding() {
  try {
    const result = await requestConfigOperation('settings.get', { namespace: 'core.onboarding' })
    const value = result.value && typeof result.value === 'object' ? result.value as Record<string, unknown> : {}
    if (value.completed === true) return
  } catch {
    return // 配置服务不可用时 fail-open，不阻塞老用户
  }
  if (availableProviders.value.some((provider) => provider.has_api_key)) return
  showOnboarding.value = true
  // 弹过一次就算“谈过”：立即标记 completed，下次不再自动弹出
  // （除非用户通过“再次显示引导”主动清除标记）。
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.onboarding',
      value: { completed: true, version: 1, completed_at: new Date().toISOString() },
    })
  } catch {
    // 标记失败不阻塞引导展示
  }
}

async function skipOnboarding() {
  showOnboarding.value = false
  // 跳过也算谈过：与 checkOnboarding 的自动标记保持一致。
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.onboarding',
      value: { completed: true, version: 1, completed_at: new Date().toISOString() },
    })
  } catch {
    // 标记失败不阻塞进入主界面
  }
}

async function onboardingCreateProvider(payload: CoreSettingsProviderPayload) {
  wizardError.value = ''
  wizardLoading.value = true
  try {
    loadError.value = null
    const result = await requestConfigOperation('config.provider.create', payload as unknown as Record<string, unknown>)
    await loadModelOptions()
    if (payload.model_group_name) await ensureCreatedModelsInGroup(payload.model_group_name, result)
    setRuntimeStatus('供应商已添加')
  } catch (error) {
    wizardError.value = error instanceof Error ? error.message : String(error)
  } finally {
    wizardLoading.value = false
  }
}

async function finishOnboarding() {
  showOnboarding.value = false
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.onboarding',
      value: { completed: true, version: 1, completed_at: new Date().toISOString() },
    })
  } catch {
    // 标记失败不阻塞进入主界面
  }
}

async function reopenOnboarding() {
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.onboarding',
      value: { completed: false },
    })
  } catch {
    // 忽略：标记清除失败仍允许重开引导
  }
  showOnboarding.value = true
}

async function updateProvider(payload: CoreSettingsProviderPayload) {
  await mutateConfig('config.provider.update', payload, '供应商已更新')
}

async function deleteProvider(providerId: string) {
  if (!window.confirm('删除供应商会同时移除其模型配置，是否继续？')) return
  await mutateConfig('config.provider.delete', { provider_id: providerId }, '供应商已删除')
}

async function createModel(payload: CoreSettingsModelPayload) {
  await mutateConfig('config.models.upsert', { scope: 'global', ...payload }, '模型已添加')
}

async function updateModel(payload: CoreSettingsModelPayload) {
  await mutateConfig('config.models.upsert', { scope: 'global', ...payload }, '模型已更新')
}

async function deleteModel(modelRecordId: string) {
  if (!window.confirm('删除此模型配置，是否继续？')) return
  await mutateConfig('config.models.delete', { scope: 'global', model_id: modelRecordId }, '模型已删除')
}

async function setDefaultModel(modelId: string) {
  await mutateConfig('config.models.set_default', { scope: 'global', model_id: modelId }, '已设为默认模型')
}

async function ensureCreatedModelsInGroup(groupName: string, result: Record<string, unknown>) {
  const createdModels = Array.isArray(result.models) ? result.models : []
  const createdIds = createdModels.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const id = String((item as Record<string, unknown>).id || '').trim()
    return id ? [id] : []
  })
  if (!createdIds.length) return
  await loadModelGroups()
  let group = modelGroups.value.find(item => item.name.toLocaleLowerCase() === groupName.toLocaleLowerCase())
  if (!group) {
    await requestConfigOperation('config.model_group.create', {
      name: groupName,
      ...(modelGroupsRevision.value !== undefined ? { expected_revision: modelGroupsRevision.value } : {}),
    })
    await loadModelGroups()
    group = modelGroups.value.find(item => item.name.toLocaleLowerCase() === groupName.toLocaleLowerCase())
  }
  if (!group) throw new Error(`无法创建模型组 ${groupName}`)
  await requestConfigOperation('config.model_group.members.set', {
    group_id: group.id,
    model_ids: [...new Set([...group.model_ids, ...createdIds])],
    ...(modelGroupsRevision.value !== undefined ? { expected_revision: modelGroupsRevision.value } : {}),
  })
  await loadModelGroups()
}

async function createModelGroup(payload: { name: string }) {
  await mutateModelCatalog('config.model_group.create', {
    ...payload,
    ...(modelGroupsRevision.value !== undefined ? { expected_revision: modelGroupsRevision.value } : {}),
  }, '模型组已创建')
}

async function updateModelGroup(payload: { group_id: string; name: string }) {
  await mutateModelCatalog('config.model_group.update', {
    ...payload,
    ...(modelGroupsRevision.value !== undefined ? { expected_revision: modelGroupsRevision.value } : {}),
  }, '模型组已更新')
}

async function deleteModelGroup(groupId: string) {
  if (!window.confirm('删除模型组只会移除分组关系，不会删除模型。是否继续？')) return
  await mutateModelCatalog('config.model_group.delete', {
    group_id: groupId,
    ...(modelGroupsRevision.value !== undefined ? { expected_revision: modelGroupsRevision.value } : {}),
  }, '模型组已删除')
}

async function setModelGroupMembers(payload: { group_id: string; model_ids: string[] }) {
  await mutateModelCatalog('config.model_group.members.set', {
    ...payload,
    ...(modelGroupsRevision.value !== undefined ? { expected_revision: modelGroupsRevision.value } : {}),
  }, '模型组成员已更新')
}

async function createModelWithProvider(payload: Record<string, unknown>) {
  await mutateModelCatalog('config.model.create_with_provider', {
    ...payload,
    ...(modelGroupsRevision.value !== undefined ? { expected_revision: modelGroupsRevision.value } : {}),
  }, '模型已创建并加入分组')
}

async function mutateModelCatalog(method: string, params: object, successText: string) {
  try {
    loadError.value = null
    await requestConfigOperation(method, params as Record<string, unknown>)
    await Promise.all([loadModelOptions(), loadModelGroups()])
    setRuntimeStatus(successText)
  } catch (error) {
    setLoadError(error instanceof Error ? error.message : String(error))
  }
}

async function loadModelCatalogPreference() {
  try {
    const result = await requestConfigOperation('settings.get', { namespace: 'core.modelCatalog' })
    const value = result.value && typeof result.value === 'object'
      ? result.value as Record<string, unknown>
      : {}
    modelCatalogView.value = value.classification === 'group' ? 'group' : 'provider'
  } catch {
    modelCatalogView.value = 'provider'
  }
}

async function updateModelCatalogView(value: CoreModelCatalogView) {
  if (modelCatalogView.value === value) return
  const previous = modelCatalogView.value
  modelCatalogView.value = value
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.modelCatalog',
      value: { classification: value },
    })
  } catch (error) {
    modelCatalogView.value = previous
    const message = error instanceof Error ? error.message : String(error)
    window.alert(`模型分类方式保存失败，已回滚：${message}`)
  }
}

async function loadPermissionMode() {
  try {
    const result = await requestConfigOperation('settings.get', { namespace: 'core.runtimeControls' })
    const value = result.value && typeof result.value === 'object' ? result.value as Record<string, unknown> : {}
    const mode = value.permission_mode
    if (mode === 'read_only' || mode === 'limited_edit' || mode === 'full_edit') {
      permissionMode.value = mode
    } else {
      await updatePermissionMode(permissionMode.value)
    }
    if (value.permission_preset === 'ask' || value.permission_preset === 'auto' || value.permission_preset === 'full_access') {
      defaultPermissionPreset.value = value.permission_preset
    } else {
      // Accept the legacy policy spelling when present.
      defaultPermissionPreset.value = value.approval_policy === 'auto_approve' ? 'auto' : 'ask'
    }
    allowAccessOutsideWorkdir.value = Boolean(value.allow_access_outside_workdir)
  } catch {
    permissionMode.value = 'full_edit'
    defaultPermissionPreset.value = 'ask'
    allowAccessOutsideWorkdir.value = false
  }
}

async function updatePermissionMode(mode: 'read_only' | 'limited_edit' | 'full_edit') {
  const previous = permissionMode.value
  permissionMode.value = mode
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.runtimeControls',
      value: { permission_mode: mode },
    })
  } catch (e) {
    // Roll back on failure — the UI must never show a security-relevant
    // mode that the backend did not persist (audit 17 S3).
    permissionMode.value = previous
    const message = e instanceof Error ? e.message : String(e)
    window.alert(`权限模式保存失败，已回滚：${message}`)
  }
}

async function updateAllowAccessOutsideWorkdir(value: boolean) {
  const previous = allowAccessOutsideWorkdir.value
  allowAccessOutsideWorkdir.value = value
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.runtimeControls',
      value: { allow_access_outside_workdir: value },
    })
  } catch (e) {
    allowAccessOutsideWorkdir.value = previous
    const message = e instanceof Error ? e.message : String(e)
    window.alert(`工作目录外访问设置保存失败，已回滚：${message}`)
  }
}

async function mutateConfig(method: string, params: object, successText: string) {
  try {
    loadError.value = null
    await requestConfigOperation(method, params as Record<string, unknown>)
    await loadModelOptions()
    setRuntimeStatus(successText)
  } catch (error) {
    setLoadError(error instanceof Error ? error.message : String(error))
  }
}

async function requestConfigOperation(method: string, params: Record<string, unknown> = {}) {
  let lastError: Error | null = null
  const maxRetries = 5
  const baseDelay = 200
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await appRuntime.requestRpc(method, params)
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error))
      if (attempt < maxRetries) {
        await new Promise((r) => setTimeout(r, baseDelay * 2 ** attempt))
        continue
      }
      throw lastError
    }
  }
  throw lastError ?? new Error('Core App Server 连接失败')
}

// ── 软件更新（设置 → 关于与更新；启动时静默自动检查）──
const updateState = useCoreUpdateState(requestConfigOperation)
// 解构到 setup 顶层供模板使用（嵌套 ref 在模板中不会自动解包）
const {
  status: updateStatus,
  latestVersion: updateLatestVersion,
  download: downloadUpdate,
  installSupported: updateInstallSupported,
  installState: updateInstallState,
  installProgressLabel: updateInstallProgressLabel,
} = updateState

/**
 * The banner is the first place a new version shows up, so it offers the same
 * action as the settings card: download and verify in place when the manifest
 * carries a digest, otherwise the download page.
 */
const updateBannerText = computed(() => {
  if (updateInstallState.value === 'downloading') {
    return updateInstallProgressLabel.value || `正在下载 v${updateLatestVersion.value}…`
  }
  if (updateInstallState.value === 'downloaded') {
    return `更新 v${updateLatestVersion.value} 已下载并校验，可以安装了`
  }
  return `发现新版本 v${updateLatestVersion.value}，是否立即下载？`
})
const updateBannerAction = computed<'download' | 'install'>(
  () => (updateInstallState.value === 'downloaded' ? 'install' : 'download'),
)
function startUpdateDownload() {
  if (updateInstallSupported.value) {
    void updateState.downloadInstaller()
    return
  }
  void downloadUpdate()
}
function installUpdateNow() {
  void updateState.runInstaller()
}
const updateBannerDismissed = ref(false)
const updateBannerVisible = computed(
  () => updateStatus.value === 'update_available' && !updateBannerDismissed.value,
)
function dismissUpdateBanner() {
  updateBannerDismissed.value = true
}

function currentWorkRoot(): string {
  const session = sessions.value.find((item) => item.id === activeSessionId.value)
  const workRoot = session?.metadata?.work_root
  return typeof workRoot === 'string' ? workRoot : ''
}

async function updatePermissionPreset(preset: CorePermissionPreset) {
  const previous = defaultPermissionPreset.value
  defaultPermissionPreset.value = preset
  try {
    await requestConfigOperation('settings.update', {
      namespace: 'core.runtimeControls',
      value: { permission_preset: preset },
    })
  } catch (e) {
    defaultPermissionPreset.value = previous
    const message = e instanceof Error ? e.message : String(e)
    window.alert(`默认审批策略保存失败，已回滚：${message}`)
  }
}

function restoreSessionPermissionPreset(id: string): void {
  const session = sessions.value.find((item) => item.id === id)
  const preferences = session?.metadata?.runtime_preferences
  const preset = preferences && typeof preferences === 'object' && !Array.isArray(preferences)
    ? (preferences as Record<string, unknown>).permission_preset
    : undefined
  // A legacy session is canonicalized by the backend on listing. If an old
  // client still returns no preference block, use the safe UI default; never
  // copy the currently selected session's preset across the boundary.
  executionControls.restorePermissionPreset(preset ?? defaultPermissionPreset.value)
}

let permissionPersistence = Promise.resolve()
let permissionPersistenceGeneration = 0

function persistSessionPermissionPreset(preset: CorePermissionPreset): Promise<void> {
  const sessionId = activeSessionId.value
  const session = sessions.value.find((item) => item.id === sessionId)
  if (!sessionId || !session) return Promise.resolve()
  const generation = ++permissionPersistenceGeneration

  permissionPersistence = permissionPersistence.then(async () => {
    // Keep writes ordered so a quick ask → auto → full_access sequence cannot
    // leave the session with an older response that arrived last.
    try {
      const result = await requestConfigOperation('session.permissions.set', {
        thread_id: sessionId,
        permission_preset: preset,
      })
      const updated = result.session as RawSession
      if (generation !== permissionPersistenceGeneration) return
      sessions.value = sessions.value.map((item) => (
        item.id === sessionId ? { ...item, metadata: updated.metadata } : item
      ))
    } catch (error) {
      // Keep the chain usable for a later selection and surface the failed
      // session write without touching global runtimeControls.
      if (generation === permissionPersistenceGeneration) {
        composerErrorText.value = `权限偏好保存失败：${messageFromError(error)}`
      }
    }
  })
  return permissionPersistence
}

async function refreshPluginModes(): Promise<void> {
  try {
    await refreshPluginUIModes(requestConfigOperation)
    pluginModes.value = listModes()
    if (!appModes.value.some((mode) => modeKey(mode) === activeAppModeKey.value)) {
      activeAppModeKey.value = 'core:agent'
      if (isActivePluginSession()) {
        workbench.disconnect()
        liveComposerController.resetForThreadChange()
        activeSessionId.value = null
        if (coreSessions.value[0]) await selectSession(coreSessions.value[0].id)
      }
    }
  } catch (error) {
    console.error('[plugins] UI mode list failed', error)
    pluginModes.value = []
    if (activePluginMode.value) {
      activeAppModeKey.value = 'core:agent'
      if (isActivePluginSession()) {
        workbench.disconnect()
        liveComposerController.resetForThreadChange()
        activeSessionId.value = null
        if (coreSessions.value[0]) await selectSession(coreSessions.value[0].id)
      }
    }
  }
}

async function handleCapabilitiesChanged(refreshDesktop: boolean): Promise<void> {
  const refreshDesktopPlugins = (window as {
    __LAMTOOLS_REFRESH_DESKTOP_PLUGINS__?: () => Promise<void>
  }).__LAMTOOLS_REFRESH_DESKTOP_PLUGINS__
  if (refreshDesktop && refreshDesktopPlugins) await refreshDesktopPlugins()
  await refreshPluginModes()
  if (activeSessionId.value) await liveComposerController.loadCommandCatalog(activeSessionId.value)
}

async function applyCommandEffects(result: Record<string, unknown>): Promise<void> {
  const effects = Array.isArray(result.effects) ? result.effects : []
  for (const rawEffect of effects) {
    if (!rawEffect || typeof rawEffect !== 'object') continue
    const effect = rawEffect as Record<string, unknown>
    if (effect.type !== 'desktop_plugin' || effect.action !== 'show') {
      throw new Error('命令返回了当前版本不支持的界面操作')
    }
    const pluginId = String(effect.plugin_id || '').trim()
    const showDesktopPlugin = (window as {
      __LAMTOOLS_SHOW_DESKTOP_PLUGIN__?: (pluginId: string) => Promise<void>
    }).__LAMTOOLS_SHOW_DESKTOP_PLUGIN__
    if (!pluginId || !showDesktopPlugin) {
      throw new Error('桌宠命令仅能在 LamTools 桌面端执行')
    }
    try {
      await showDesktopPlugin(pluginId)
    } catch (initialError) {
      const refreshDesktopPlugins = (window as {
        __LAMTOOLS_REFRESH_DESKTOP_PLUGINS__?: () => Promise<void>
      }).__LAMTOOLS_REFRESH_DESKTOP_PLUGINS__
      if (!refreshDesktopPlugins) throw initialError
      await refreshDesktopPlugins()
      let latestError: unknown = initialError
      for (let attempt = 0; attempt < 20; attempt += 1) {
        await new Promise(resolve => window.setTimeout(resolve, 100))
        try {
          await showDesktopPlugin(pluginId)
          latestError = null
          break
        } catch (error) {
          latestError = error
        }
      }
      if (latestError) throw latestError
    }
  }
}

const switchModeSession = createModeSessionState({
  mode: activeAppModeKey,
  session: activeSessionId,
  draft: composerText,
  sessions: () => sessions.value,
  reset: () => liveComposerController.resetForThreadChange(),
  select: selectSession,
})

async function selectAppMode(mode: PluginMode): Promise<void> {
  if (!appModes.value.some((candidate) => modeKey(candidate) === modeKey(mode))) return
  await switchModeSession(modeKey(mode))
}

function cycleAppMode(): void {
  const modes = appModes.value
  if (modes.length < 2) return
  const index = modes.findIndex((mode) => modeKey(mode) === activeAppModeKey.value)
  void selectAppMode(modes[(index + 1) % modes.length])
}

function selectAppModeByKey(id: string): void {
  const mode = appModes.value.find((candidate) => modeKey(candidate) === id)
  if (mode) void selectAppMode(mode)
}

watch([activeAppMode, appModes], ([mode, modes]) => {
  emit('mobile-mode-state', {
    label: mode.title,
    title: nextAppModeTitle.value,
    canToggle: modes.length > 1,
    activeId: modeKey(mode),
    options: modes.map((candidate) => ({ id: modeKey(candidate), label: candidate.title })),
  })
}, { immediate: true })

function invokeSidebarPrimaryAction(): void {
  const action = activePluginSurface.value?.sidebar?.onPrimaryAction
  if (action) {
    void Promise.resolve(action()).catch((error) => {
      composerErrorText.value = messageFromError(error)
    })
    return
  }
  openProjectCreate()
}

function handleShellNewSession(): void {
  invokeSidebarPrimaryAction()
}

function handleSidebarSession(id: string): void {
  const action = activePluginSurface.value?.sidebar?.onSelectSession
  if (action) {
    void Promise.resolve(action(id)).catch((error) => {
      composerErrorText.value = messageFromError(error)
    })
    return
  }
  void selectSession(id)
}

function handleSidebarProject(id: string): void {
  const action = activePluginSurface.value?.sidebar?.onSelectProject
  if (action) {
    void Promise.resolve(action(id)).catch((error) => {
      composerErrorText.value = messageFromError(error)
    })
    return
  }
  openProjectActions(id)
}

function handleSidebarNewSession(projectGroupId: string): void {
  const action = activePluginSurface.value?.sidebar?.onNewSession
  if (action) {
    void Promise.resolve(action(projectGroupId)).catch((error) => {
      composerErrorText.value = messageFromError(error)
    })
    return
  }
  void createProjectSession(projectGroupId)
}

function openSettings(section?: string): void {
  settingsSection.value = section
  showSettings.value = true
  void refreshRemoteGateway()
  void refreshRemoteAccount()
}

/** Rail account entry: show the account state, and open settings on it. */
const accountLabel = computed(() => {
  const username = remoteAccountStatus.value?.username?.trim()
  return username || '登录 / 账号'
})

/** The account screen is its own surface; the settings section keeps the forms. */
const showAccount = ref(false)

function openAccount(): void {
  showAccount.value = true
  void refreshRemoteAccount()
}

function openAccountSettings(): void {
  showAccount.value = false
  openSettings('mobile-control')
}

function openSearch(): void {
  openFullArea('search')
}

function openLibrary(): void {
  openFullArea('library')
}

function openArrange(): void {
  openFullArea('arrange')
}

/** Which plugins section the next open should land on (search hits target one). */
const pluginsSection = ref<string | undefined>(undefined)

function openPlugins(section?: string): void {
  pluginsSection.value = section
  showPlugins.value = true
}

function openPluginsFromSearch(target: { section: 'plugins' | 'skills' | 'hooks'; id?: string }): void {
  closeFullArea()
  openPlugins(target.section)
}

/** A task hit with no message to land on: open it like the sidebar does. */
function openSessionFromSearch(sessionId: string): void {
  closeFullArea()
  void selectSession(sessionId)
}

/**
 * The shortcut rows the search dialog shows while the query is empty.
 * Only commands this host really has: the phone has no terminal or preview, so
 * it passes fewer of them instead of advertising what it cannot do.
 */
const searchCommands = computed<SearchCommand[]>(() => {
  const commands: SearchCommand[] = [
    { id: 'new-task', label: '新任务', group: '建议', shortcut: 'Ctrl+N', icon: Plus, run: () => void createStartPageSession() },
    { id: 'open-workspace', label: '打开工作区', group: '建议', shortcut: 'Ctrl+O', icon: FolderOpen, run: () => { showProjectPicker.value = true } },
    { id: 'settings', label: '设置', group: '建议', icon: Settings, run: () => openSettings() },
    { id: 'toggle-sidebar', label: '切换侧栏', group: '面板', shortcut: 'Ctrl+B', icon: PanelLeft, run: () => toggleLeftPinned() },
  ]
  if (appRuntime.platform !== 'mobile') {
    commands.push(
      { id: 'toggle-preview', label: '切换预览', group: '面板', shortcut: 'Ctrl+J', icon: MonitorPlay, run: () => toggleStage() },
      { id: 'toggle-right-panel', label: '切换右侧栏', group: '面板', icon: PanelRight, run: () => toggleRightPinned() },
    )
  }
  return commands
})

function closePlugins(): void {
  showPlugins.value = false
  void refreshPluginModes()
}

function ensureRightPanelOpen(): void {
  if (!rightPinned.value) toggleRightPinned()
}

watch(pluginModes, () => {
  if (!appModes.value.some((mode) => modeKey(mode) === activeAppModeKey.value)) {
    activeAppModeKey.value = 'core:agent'
  }
})

function syncActiveSessionStatus(status: string) {
  const sessionId = activeSessionId.value
  if (!sessionId) return
  const index = sessions.value.findIndex((item) => item.id === sessionId)
  if (index < 0) return
  const next = [...sessions.value]
  next[index] = { ...next[index], status, updatedAt: new Date().toISOString() }
  sessions.value = next
}

async function loadModelOptions() {
  try {
    const providersResponse = await requestConfigOperation('config.providers.list')
    const modelsResponse = await requestConfigOperation('config.models.list')
    availableProviders.value = Array.isArray(providersResponse.providers)
      ? providersResponse.providers as RawProvider[]
      : []
    availableModels.value = Array.isArray(modelsResponse.models)
      ? modelsResponse.models as RawModel[]
      : []
    // There is no global default model: the composer inherits the main-chat
    // scene's most recently used model. An empty value means "nothing to
    // inherit" — the composer then shows no model rather than some default.
    const sceneModels = (modelsResponse as { scene_models?: Record<string, unknown> }).scene_models
    const sceneModelId = sceneModels && typeof sceneModels.chat === 'string' ? sceneModels.chat : ''
    defaultModelId.value = sceneModelId
  } catch {
    availableModels.value = []
    availableProviders.value = []
    defaultModelId.value = ''
  }
}

// Backend notices: an external edit to provider/model/settings files, or a
// model substituted because the inherited one disappeared. Both were silent
// before; the user must be told which config changed or which model ran.
async function drainConfigNotices() {
  try {
    const response = await requestConfigOperation('config.notices.drain')
    const notices = Array.isArray(response.notices) ? response.notices : []
    for (const notice of notices) {
      const message = String((notice as { message?: unknown })?.message || '').trim()
      if (message) showToast('notice', message, 8000)
    }
  } catch {
    // Notice delivery must never break the app.
  }
}

let configNoticeTimer: ReturnType<typeof setInterval> | null = null

function startConfigNoticePolling(): void {
  if (configNoticeTimer !== null) return
  configNoticeTimer = setInterval(() => {
    void drainConfigNotices()
  }, 15000)
}

function toSession(raw: RawSession): CoreSessionListItem {
  return {
    id: raw.id,
    title: raw.title || raw.id,
    createdAt: raw.created_at || raw.createdAt || '',
    updatedAt: raw.updated_at || raw.updatedAt,
    status: raw.status,
    metadata: raw.metadata,
  }
}

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

async function loadModelGroups() {
  try {
    const response = await requestConfigOperation('config.model_groups.list')
    const rawGroups = Array.isArray(response.groups) ? response.groups : []
    modelGroups.value = rawGroups.flatMap((item) => {
      if (!item || typeof item !== 'object') return []
      const record = item as Record<string, unknown>
      const id = String(record.id || '').trim()
      if (!id) return []
      return [{
        id,
        name: String(record.name || id),
        model_ids: Array.isArray(record.model_ids)
          ? record.model_ids.map(value => String(value)).filter(Boolean)
          : [],
        revision: Number.isFinite(Number(record.revision)) ? Number(record.revision) : undefined,
        is_system: record.is_system === true,
      }]
    })
    const revision = Number(response.revision)
    modelGroupsRevision.value = Number.isFinite(revision) ? revision : undefined
  } catch (error) {
    modelGroups.value = []
    modelGroupsRevision.value = undefined
    throw error
  }
}

async function encodeMultipartFile(file: File): Promise<{ body: Uint8Array; contentType: string }> {
  const boundary = `----LamToolsBoundary${globalThis.crypto?.randomUUID?.() || Date.now()}`
  const encoder = new TextEncoder()
  const filename = file.name.replace(/["\r\n]/g, '_')
  const head = encoder.encode(
    `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: ${file.type || 'application/octet-stream'}\r\n\r\n`,
  )
  const content = new Uint8Array(await file.arrayBuffer())
  const tail = encoder.encode(`\r\n--${boundary}--\r\n`)
  const body = new Uint8Array(head.length + content.length + tail.length)
  body.set(head)
  body.set(content, head.length)
  body.set(tail, head.length + content.length)
  return { body, contentType: `multipart/form-data; boundary=${boundary}` }
}

watch(composerText, () => {
  void nextTick(resizeComposerTextarea)
})

// Persist the model chosen while a session is active into that session's
// metadata (PATCH /sessions/:id) — the per-session model memory that
// restoreSessionModel() reads back on every session switch. Best-effort: a
// failed save must not undo the local selection.
watch(selectedModelId, (modelId) => {
  const sessionId = activeSessionId.value
  const session = sessions.value.find((item) => item.id === sessionId)
  if (!sessionId || !session || isPluginOwnedSession(session)) return
  const metadata: Record<string, unknown> = { ...(session.metadata || {}) }
  if (modelId) metadata.model_id = modelId
  else delete metadata.model_id
  void requestJson(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: { metadata },
  })
    .then((updated) => {
      const raw = updated as RawSession
      sessions.value = sessions.value.map((item) =>
        item.id === sessionId ? { ...item, metadata: raw.metadata } : item,
      )
    })
    .catch(() => { /* best-effort persistence */ })
})

watch(messages, (newVal, oldVal) => {
  const oldIds = new Set((oldVal || []).map(m => m.id))
  const newUserMsgs = (newVal || []).filter(m => !oldIds.has(m.id) && m.role === 'user')
  if (newUserMsgs.length > 0) pendingPlaceholder.value = null
  // 滚动跟随由底部哨兵单一通道驱动；这里不再按消息变化隐式写 scrollTop。
}, { deep: true })

watch([activeSessionId, messages, latestStatus], ([threadId]) => {
  void refreshGoal(threadId)
})

// Sync pin state from WorkspaceShell when it mounts
watch(shellRef, (shell) => {
  if (shell) {
    leftPinned.value = shell.leftPinned
    rightPinned.value = shell.rightPinned
  }
})

function openLeftSidebar(): void {
  shellRef.value?.openLeftDrawer()
}

function handleStudyOpenSearch(): void {
  openSearch()
}

defineExpose({
  openLeftSidebar,
  cycleAppMode,
  selectAppModeByKey,
  refreshPluginModes,
  openSearch,
  openLibrary,
  openSettings,
  openPlugins,
  openArrange,
  openProject,
})

onMounted(() => {
  void uiPreferences.load()
  // 全窗口拖拽上传：window 级监听亮起遮罩（Tauri 需 dragDropEnabled: false 才走 HTML5 事件）
  window.addEventListener('dragover', handleWindowDragOver)
  window.addEventListener('dragleave', handleWindowDragLeave)
  window.addEventListener('drop', handleWindowDrop)
  // Ctrl+K 全局搜索（与侧边栏「搜索」同一个 SearchShell——统一入口）
  window.addEventListener('keydown', handleGlobalSearchKeydown)
  window.addEventListener('lamtools:open-search', handleStudyOpenSearch)
  window.addEventListener('lamtools:projects-synced', handleProjectsSynced)
  // The scroll composable owns the sentinel observer; the host only resets
  // per-session intent and lands the canonical surface at the latest message.
  watch([threadScrollEl, threadBottomSentinel], () => {
    threadScroll.reset()
    void threadScroll.scrollToBottom(true)
  }, { immediate: true })
  void loadInitialData().then(() => checkOnboarding())
  void refreshRemoteGateway()
  void refreshRemoteAccount()
  // External config edits and model substitutions must reach the user even
  // when no settings surface is open.
  startConfigNoticePolling()
  void drainConfigNotices()
  // 启动时静默检查更新（仅 Tauri 桌面环境，且用户未关闭「启动时自动检查更新」）
  if ((window as any).__TAURI_INTERNALS__ && readUpdateAutoCheck()) {
    void updateState.check()
  }
  // 后端进程崩溃检测（Rust 侧监视线程发 backend-crashed）→ 显示恢复横幅
  // （audit 20 S3）。浏览器环境无 Tauri API，动态 import 静默跳过。
  if ((window as any).__TAURI_INTERNALS__) {
    void import('@tauri-apps/api/event').then(({ listen }) => {
      void listen('backend-crashed', () => {
        backendCrashed.value = true
      })
    }).catch(() => {})
  }
})

onUnmounted(() => {
  window.removeEventListener('dragover', handleWindowDragOver)
  window.removeEventListener('dragleave', handleWindowDragLeave)
  window.removeEventListener('drop', handleWindowDrop)
  window.removeEventListener('keydown', handleGlobalSearchKeydown)
  window.removeEventListener('lamtools:open-search', handleStudyOpenSearch)
  window.removeEventListener('lamtools:projects-synced', handleProjectsSynced)
  if (configNoticeTimer !== null) {
    clearInterval(configNoticeTimer)
    configNoticeTimer = null
  }
  stopLatestActivityMotion()
  cancelHistoryCapMotion()
  historyScrollCeiling = null
  restoringHistoryAnchor = false
  workbench.disconnect()
})
</script>

<style>
@import '../styles/variables.css';
@import '../styles/base.css';
@import '../styles/layout.css';
@import '../styles/theme-editor.css';

.plugin-mode-surface {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
}

.plugin-mode-surface > .plugin-mode-host {
  height: 100%;
}

.runtime-checklist-mobile {
  display: none;
}

@media (max-width: 640px) {
  .runtime-checklist-mobile {
    display: block;
    margin-bottom: var(--space-3);
  }
}

/* ── 新版本提示条（fixed 在标题栏下方，36px = --titlebar-offset） ── */
.core-update-banner {
  position: fixed;
  top: 36px;
  left: 0;
  right: 0;
  z-index: var(--z-modal, 80);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: var(--panel);
  border-bottom: 1px solid var(--line, rgba(128, 128, 128, 0.25));
  font-size: 13px;
}
.core-update-banner-text {
  flex: 1;
  color: var(--text);
}
.core-update-banner-action {
  border: 1px solid var(--line, rgba(128, 128, 128, 0.25));
  border-radius: 6px;
  padding: 4px 12px;
  background: var(--accent, rgba(255, 255, 255, 0.08));
  color: var(--text);
  cursor: pointer;
}
.core-update-banner-close {
  border: none;
  background: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 13px;
  padding: 2px 6px;
}

/* ── 全窗口拖拽上传遮罩 ── */
.attachment-drop-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal, 80);
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--theme-main-background) 88%, transparent);
  backdrop-filter: blur(3px);
}
.attachment-drop-card {
  display: grid;
  place-items: center;
  gap: 8px;
  padding: 40px 64px;
  border: 2px dashed color-mix(in srgb, var(--green) 55%, transparent);
  border-radius: 16px;
  background: color-mix(in srgb, var(--theme-main-subtle-background) 78%, transparent);
}
.attachment-drop-icon {
  color: var(--green);
}
.attachment-drop-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--theme-main-text);
}
.attachment-drop-hint {
  margin: 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text) 60%, transparent);
}

.wf-create-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal, 80);
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.34);
  backdrop-filter: blur(2px);
}
.wf-create-card {
  width: 320px;
  max-width: calc(100vw - 32px);
  padding: 16px;
  border-radius: 14px;
  background: var(--theme-main-background);
  border: 1px solid var(--theme-main-border);
  box-shadow: var(--shadow);
  display: grid;
  gap: 10px;
}
.wf-create-head {
  margin: 0;
}
.wf-create-head h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--theme-main-text);
}
.wf-create-input {
  width: 100%;
  height: 30px;
  box-sizing: border-box;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: 7px;
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  padding: 0 8px;
  font: inherit;
  font-size: 13px;
  outline: 0;
}
.wf-create-input:focus {
  border-color: color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
}
.wf-create-error {
  margin: 0;
  font-size: 11px;
  color: var(--red);
}
.wf-create-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}
.wf-create-actions .text-btn,
.wf-create-actions .primary-btn {
  height: 28px;
  padding: 0 12px;
  border-radius: 7px;
  border: 0;
  font-size: 12px;
  cursor: pointer;
}
.wf-create-actions .text-btn {
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 65%, transparent);
}
.wf-create-actions .primary-btn {
  background: color-mix(in srgb, var(--blue) 80%, transparent);
  color: color-mix(in srgb, var(--theme-backdrop-text) 90%, transparent);
  font-weight: 600;
}
.wf-create-actions .primary-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.stage-toggle-btn {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 65%, transparent);
  cursor: pointer;
  font-size: 14px;
  display: grid;
  place-items: center;
  transition: background 0.15s, color 0.15s;
}
.stage-toggle-btn:hover {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
  color: var(--text, #f2efeb);
}
.stage-toggle-btn.active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active), transparent);
  color: var(--text, #f2efeb);
}

/* The zero-height sticky slot keeps the paging status above the viewport
   without inserting a new row into the message layout. */
.thread-history-cap-slot {
  position: sticky;
  top: var(--space-6, 32px);
  z-index: var(--z-edge-trigger, 35);
  height: 0;
  margin-block-end: calc(-1 * var(--space-4, 16px));
  display: flex;
  justify-content: center;
  overflow: visible;
  pointer-events: none;
}
.thread-history-cap {
  --text: var(--theme-main-text);
  display: inline-flex;
  align-items: center;
  gap: var(--space-2, 8px);
  width: fit-content;
  margin-top: var(--space-2, 8px);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius);
  background: var(--theme-main-background);
  color: color-mix(in srgb, var(--text) 72%, transparent);
  box-shadow: var(--shadow-sm);
  font-size: 12px;
  line-height: 1;
  will-change: transform, opacity;
}
.thread-history-cap-icon {
  flex: 0 0 auto;
  animation: thread-history-cap-spin 0.9s linear infinite;
  will-change: transform;
}

.thread-bottom-sentinel {
  width: 100%;
  height: 1px;
  margin-block-start: calc(-1 * var(--space-4, 16px));
  transform: translateY(calc(
    var(--composer-bottom-offset, 0px) +
    var(--composer-rest-bottom, 16px) +
    var(--composer-clearance, 24px) - 1px
  ));
  pointer-events: none;
}
@keyframes thread-history-cap-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .thread-history-cap-icon {
    animation: none;
    will-change: auto;
  }
}

/* ── "回到最新" floating affordance ──
   Anchored to the bottom of the .thread scroll container via sticky
   positioning (the .workspace-main ancestor is itself position:fixed,
   so a fixed-positioned button would escape the content column). Stays
   below the composer (z-edge-trigger < z-composer) and follows the
   chat-area text color because the glass reveals the chat surface. */
.thread-jump-latest {
  --text: var(--theme-main-text);
  --optical-glass-overlay: transparent;
  position: sticky;
  bottom: var(--space-2, 8px);
  justify-self: center;
  z-index: var(--z-edge-trigger, 35);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--space-6, 32px);
  height: var(--space-6, 32px);
  padding: 0;
  overflow: hidden;
  isolation: isolate;
  border-radius: 50%;
  color: var(--text);
  cursor: pointer;
  transition:
    filter var(--dur-base) var(--ease-out),
    transform var(--dur-base) var(--ease-out);
}
.thread-jump-latest:hover {
  filter: brightness(1.015);
  transform: translateY(-1px);
}
.thread-jump-latest:active {
  transform: translateY(1px) scale(.98);
}
.thread-jump-latest:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 72%, transparent);
  outline-offset: 2px;
}
.thread-jump-latest-spinner {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
}
.thread-jump-latest-spinner svg {
  display: block;
}
/* enter from just below; leave by fading. Reduced-motion drops the slide. */
.thread-jump-latest-enter-active,
.thread-jump-latest-leave-active {
  transition: opacity .18s ease, transform .18s ease;
}
.thread-jump-latest-enter-from,
.thread-jump-latest-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
@media (prefers-reduced-motion: reduce) {
  .thread-jump-latest,
  .thread-jump-latest:hover,
  .thread-jump-latest:active,
  .thread-jump-latest-enter-active,
  .thread-jump-latest-leave-active {
    transition: opacity .18s ease;
    transform: none;
  }
  .thread-jump-latest-enter-from,
  .thread-jump-latest-leave-to {
    transform: none;
  }
}

</style>
