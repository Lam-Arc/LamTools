import { computed, unref } from 'vue'

// user:“将大的前端文件拆分成小块”+(集中组装整版与分屏共用的页面数据、事件及实例引用)。
export function useCorePageBindings(context: {
  activeAppModeKey: any
  activeProjectId: any
  agentsContent: any
  agentsError: any
  agentsLoading: any
  agentsSaving: any
  allowAccessOutsideWorkdir: any
  appRuntime: any
  arrangeHeading: any
  arrangeRef: any
  availableModels: any
  availableProviders: any
  closeFullArea: any
  closeProjectSettings: any
  commandShellPlatform: any
  contentWidth: any
  createModel: any
  createModelGroup: any
  createModelWithProvider: any
  createProvider: any
  currentWorkRoot: any
  defaultPermissionPreset: any
  deleteModel: any
  deleteModelGroup: any
  deleteProvider: any
  density: any
  effectiveThemeMode: any
  handleCapabilitiesChanged: any
  jumpToSearchedMessage: any
  jumpToStudySearchHit: any
  lastWorkbenchEvent: any
  libraryHeading: any
  libraryRef: any
  libraryRefreshTick: any
  modelCatalogView: any
  modelGroups: any
  openFileFromSearch: any
  openPluginsFromSearch: any
  openSessionFromSearch: any
  persistSettingsCatalog: any
  pluginsSection: any
  projectActionError: any
  projectActionLoading: any
  projectClient: any
  projectNameDraft: any
  projectSettingsRef: any
  projectSettingsSection: any
  projectSettingsSessionId: any
  refreshAgentsContent: any
  renameProject: any
  reopenOnboarding: any
  requestConfigOperation: any
  saveAgents: any
  searchCommands: any
  selectedProject: any
  selectedProjectId: any
  sessions: any
  setDefaultModel: any
  setModelGroupMembers: any
  settingsRef: any
  settingsSection: any
  startPlanFromLibrary: any
  superagentHeading: any
  theme: any
  themeMode: any
  themeSchedule: any
  transport: any
  uiPreferences: any
  updateAllowAccessOutsideWorkdir: any
  updateModel: any
  updateModelCatalogView: any
  updateModelGroup: any
  updatePermissionPreset: any
  updateProjectVisual: any
  updateProvider: any
  updateState: any
  uploadArtifactFiles: any
}) {
  const { activeAppModeKey, activeProjectId, agentsContent, agentsError, agentsLoading, agentsSaving, allowAccessOutsideWorkdir, appRuntime, arrangeHeading, arrangeRef, availableModels, availableProviders, closeFullArea, closeProjectSettings, commandShellPlatform, contentWidth, createModel, createModelGroup, createModelWithProvider, createProvider, currentWorkRoot, defaultPermissionPreset, deleteModel, deleteModelGroup, deleteProvider, density, effectiveThemeMode, handleCapabilitiesChanged, jumpToSearchedMessage, jumpToStudySearchHit, lastWorkbenchEvent, libraryHeading, libraryRef, libraryRefreshTick, modelCatalogView, modelGroups, openFileFromSearch, openPluginsFromSearch, openSessionFromSearch, persistSettingsCatalog, pluginsSection, projectActionError, projectActionLoading, projectClient, projectNameDraft, projectSettingsRef, projectSettingsSection, projectSettingsSessionId, refreshAgentsContent, renameProject, reopenOnboarding, requestConfigOperation, saveAgents, searchCommands, selectedProject, selectedProjectId, sessions, setDefaultModel, setModelGroupMembers, settingsRef, settingsSection, startPlanFromLibrary, superagentHeading, theme, themeMode, themeSchedule, transport, uiPreferences, updateAllowAccessOutsideWorkdir, updateModel, updateModelCatalogView, updateModelGroup, updatePermissionPreset, updateProjectVisual, updateProvider, updateState, uploadArtifactFiles } = context
  return computed<Record<string, Record<string, any>>>(() => ({
  superagent: {
    'class': 'full-area-view',
    'bandActions': appRuntime.platform !== 'mobile',
    'workRoot': currentWorkRoot(),
    'requestRpc': unref(requestConfigOperation),
    'onBack': unref(closeFullArea),
    'onHeading': ($event: any) => { superagentHeading.value = $event },
    'onOpenSession': unref(openSessionFromSearch)
  },
  arrange: {
    ref: (instance: unknown) => { arrangeRef.value = instance as typeof arrangeRef.value },
    'class': 'full-area-view',
    'bandActions': appRuntime.platform !== 'mobile',
    'workRoot': currentWorkRoot(),
    'requestRpc': unref(requestConfigOperation),
    'onBack': unref(closeFullArea),
    'onHeading': ($event: any) => { arrangeHeading.value = $event }
  },
  // user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
  // +(调用台复用同一个配置 RPC 与当前项目；保存到资料库需要项目身份，所以项目一起传。)
  direct: {
    'class': 'full-area-view',
    'requestRpc': unref(requestConfigOperation),
    'projectId': activeProjectId.value ?? selectedProjectId.value,
    'workRoot': currentWorkRoot(),
  },
  search: {
    'class': 'full-area-view',
    'bandActions': appRuntime.platform !== 'mobile',
    'requestRpc': unref(requestConfigOperation),
    'sessions': unref(sessions),
    'onJump': unref(jumpToSearchedMessage),
    'activeModeId': unref(activeAppModeKey),
    'onStudyHit': unref(jumpToStudySearchHit),
    'theme': unref(theme),
    'onOpenSession': unref(openSessionFromSearch),
    'onOpenPlugins': unref(openPluginsFromSearch),
    'onOpenFile': unref(openFileFromSearch),
    'commands': unref(searchCommands),
    'onClose': unref(closeFullArea)
  },
  library: {
    ref: (instance: unknown) => { libraryRef.value = instance as typeof libraryRef.value },
    'class': 'full-area-view',
    'bandActions': appRuntime.platform !== 'mobile',
    'client': unref(projectClient),
    'projectId': activeProjectId.value ?? selectedProjectId.value,
    'workRoot': currentWorkRoot(),
    'transport': unref(transport),
    'requestRpc': unref(requestConfigOperation),
    'artifactSignal': unref(lastWorkbenchEvent),
    'uploadFiles': unref(uploadArtifactFiles),
    'refreshSignal': unref(libraryRefreshTick),
    'platform': appRuntime.platform,
    'onBack': unref(closeFullArea),
    'onStartPlan': unref(startPlanFromLibrary),
    'onHeading': ($event: any) => { libraryHeading.value = $event }
  },
  settings: {
    ref: (instance: unknown) => { settingsRef.value = instance as typeof settingsRef.value },
    'class': 'full-area-view full-area-wide',
    'models': unref(availableModels),
    'providers': unref(availableProviders),
    'modelGroups': unref(modelGroups),
    'catalogView': unref(modelCatalogView),
    'section': unref(settingsSection),
    'activeSection': unref(settingsSection),
    'persistCatalog': unref(persistSettingsCatalog),
    'hideNav': appRuntime.platform !== 'mobile',
    'density': unref(density),
    'theme': unref(theme),
    'contentWidth': unref(contentWidth),
    'showRightPanelHeader': false,
    'themeMode': unref(themeMode),
    'themeSchedule': unref(themeSchedule),
    'effectiveThemeMode': unref(effectiveThemeMode),
    'permissionPreset': unref(defaultPermissionPreset),
    'allowAccessOutsideWorkdir': unref(allowAccessOutsideWorkdir),
    'commandShellPlatform': unref(commandShellPlatform),
    'requestRpc': unref(requestConfigOperation),
    'updateState': unref(updateState),
    'onClose': unref(closeFullArea),
    'onSectionChange': ($event: any) => { settingsSection.value = $event },
    'onUpdate:density': uiPreferences.setDensity,
    'onUpdate:contentWidth': uiPreferences.setContentWidth,
    'onUpdate:themeMode': uiPreferences.setThemeMode,
    'onUpdate:themeSchedule': uiPreferences.setThemeSchedule,
    'onResetTheme': uiPreferences.resetTheme,
    'onApplyPreset': uiPreferences.applyThemePreset,
    'onUpdateStops': uiPreferences.updateThemeStops,
    'onUpdateAngle': uiPreferences.updateThemeAngle,
    'onUpdateOpacity': uiPreferences.updateThemeOpacity,
    'onUpdateTextColor': uiPreferences.updateThemeText,
    'onUpdateFillMode': uiPreferences.updateThemeFill,
    'onUpdateGlassLevel': uiPreferences.updateThemeGlass,
    'onUpdateImage': uiPreferences.updateThemeImage,
    'onUpdateImageFit': uiPreferences.updateThemeImageFit,
    'onUpdateProcessIconColor': uiPreferences.updateProcessIconColor,
    'onAddStop': uiPreferences.addStop,
    'onRemoveStop': uiPreferences.removeStop,
    'onSortStops': uiPreferences.sortStops,
    'onUpdatePermissionPreset': unref(updatePermissionPreset),
    'onUpdateAllowOutsideWorkdir': unref(updateAllowAccessOutsideWorkdir),
    'onCreateProvider': unref(createProvider),
    'onUpdateProvider': unref(updateProvider),
    'onDeleteProvider': unref(deleteProvider),
    'onCreateModel': unref(createModel),
    'onUpdateModel': unref(updateModel),
    'onDeleteModel': unref(deleteModel),
    'onSetDefaultModel': unref(setDefaultModel),
    'onUpdate:catalogView': unref(updateModelCatalogView),
    'onCreateModelGroup': unref(createModelGroup),
    'onUpdateModelGroup': unref(updateModelGroup),
    'onDeleteModelGroup': unref(deleteModelGroup),
    'onSetModelGroupMembers': unref(setModelGroupMembers),
    'onCreateModelWithProvider': unref(createModelWithProvider),
    'onReopenOnboarding': unref(reopenOnboarding)
  },
  plugins: {
    'class': 'full-area-view full-area-wide',
    'bandActions': appRuntime.platform !== 'mobile',
    'requestRpc': unref(requestConfigOperation),
    'transport': unref(transport),
    'theme': unref(theme),
    'initialSection': unref(pluginsSection),
    'activeSection': unref(pluginsSection),
    'hideNav': appRuntime.platform !== 'mobile',
    'onCapabilitiesChanged': unref(handleCapabilitiesChanged),
    'onSectionChange': ($event: any) => { pluginsSection.value = $event },
    'onClose': unref(closeFullArea)
  },
  account: {
    'class': 'full-area-view',
    // RemoteConnectionPanel 靠它区分「出码 / 扫码」；缺了手机就落回桌面分支、没有扫码键。
    'appRuntime': appRuntime,
    'bandActions': appRuntime.platform !== 'mobile',
    'theme': unref(theme)
  },
  project: {
    ref: (instance: unknown) => { projectSettingsRef.value = instance as typeof projectSettingsRef.value },
    'class': 'full-area-view full-area-wide',
    'project': {
            id: selectedProject.value?.id ?? '',
            name: selectedProject.value?.name ?? '',
            workRoot: selectedProject.value?.workRoot ?? '',
            iconKey: selectedProject.value?.iconKey ?? '',
            colorKey: selectedProject.value?.colorKey ?? '',
          },
    'sessionId': unref(projectSettingsSessionId),
    'theme': unref(theme),
    'requestRpc': unref(requestConfigOperation),
    'models': unref(availableModels),
    'projectNameDraft': unref(projectNameDraft),
    'agentsContent': unref(agentsContent),
    'agentsLoading': unref(agentsLoading),
    'agentsSaving': unref(agentsSaving),
    'persistAgents': unref(saveAgents),
    'persistName': unref(renameProject),
    'agentsError': unref(agentsError),
    'projectActionLoading': unref(projectActionLoading),
    'projectActionError': unref(projectActionError),
    'activeSection': unref(projectSettingsSection),
    'hideNav': appRuntime.platform !== 'mobile',
    'onSectionChange': ($event: any) => { projectSettingsSection.value = $event },
    'onClose': unref(closeProjectSettings),
    'onRenameProject': unref(renameProject),
    'onUpdateProjectVisual': unref(updateProjectVisual),
    'onSaveAgents': unref(saveAgents),
    'onRefreshAgents': unref(refreshAgentsContent)
  }
}))
}
