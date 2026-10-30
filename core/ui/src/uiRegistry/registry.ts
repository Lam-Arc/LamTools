import type { UiRegistryEntry } from './types.ts'

/**
 * 第一批可编辑元素清单。
 *
 * user:“新增核心功能：主题设置 → 可视化界面编辑器”+
 * (先把外壳与几个主界面的根节点登记下来；子部件按需追加，不要一次性把 DOM 全注册。
 *  标识挂在组件根节点上，由 `data-ui-id` 落到 DOM。)
 */
export const UI_REGISTRY: UiRegistryEntry[] = [
  {
    id: 'shell.root',
    label: '应用外壳',
    owner: 'components/WorkspaceShell.vue',
    properties: [],
    protection: 'protected',
    note: '承载所有面板的根容器，禁止移动与隐藏。',
  },
  {
    id: 'shell.titlebar',
    label: '标题栏',
    owner: 'components/TitleBar.vue',
    parent: 'shell.root',
    properties: ['position', 'size', 'layer', 'color', 'background', 'opacity', 'visibility', 'text'],
    protection: 'editable',
  },
  {
    id: 'shell.app-rail',
    label: '左侧竖栏',
    owner: 'components/AppRail.vue',
    parent: 'shell.root',
    properties: ['position', 'size', 'layer', 'spacing', 'color', 'background', 'radius', 'opacity', 'visibility'],
    protection: 'editable',
  },
  {
    id: 'shell.left-drawer',
    label: '会话抽屉',
    owner: 'components/LeftSidebarShell.vue',
    parent: 'shell.root',
    properties: ['position', 'size', 'spacing', 'radius', 'border', 'color', 'background', 'opacity', 'layer'],
    protection: 'editable',
  },
  {
    id: 'shell.sidebar',
    label: '会话列表',
    owner: 'components/SessionSidebar.vue',
    parent: 'shell.left-drawer',
    // user:“可视化主题与布局编辑器”+(会话列表允许换底色与文字色，便于和侧栏区分)
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'color', 'background', 'text', 'opacity', 'visibility'],
    protection: 'editable',
  },
  {
    // user:“我想让会话列表项与项之间的间距增大……调间距都没有用”+
    // (会话项之间的间距在列表内部的项组容器上，不在根节点；改这里所有分组的行间距一起变。)
    id: 'shell.sidebar-items',
    label: '会话列表项组',
    owner: 'components/SessionSidebar.vue',
    parent: 'shell.sidebar',
    properties: ['position', 'size', 'layer', 'spacing'],
    protection: 'editable',
    note: '会话行与行之间的间距；改一次作用于所有分组。',
  },
  {
    id: 'shell.main',
    label: '内容区',
    owner: 'components/WorkspaceShell.vue',
    parent: 'shell.root',
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'border', 'color', 'background', 'opacity'],
    protection: 'editable',
    // user:“我认为主区和分屏本质是一个容器”+(主区=内容区单屏模式；分屏是同一个内容区的分屏模式)
    note: '聊天内容区：单屏时是主区域，打开分屏后由分屏布局接管，可拖动、可调尺寸，不允许隐藏。',
  },
  {
    id: 'shell.composer',
    label: '输入栏',
    owner: 'components/ComposerBar.vue',
    parent: 'shell.main',
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'border', 'color', 'background', 'opacity'],
    protection: 'editable',
    note: '唯一的输入入口：可拖动、可调尺寸，不允许隐藏。',
  },
  {
    id: 'shell.right-drawer',
    label: '右侧抽屉',
    owner: 'components/WorkspaceShell.vue',
    parent: 'shell.root',
    properties: ['position', 'size', 'spacing', 'radius', 'border', 'color', 'background', 'opacity', 'layer'],
    protection: 'editable',
  },
  {
    id: 'shell.right-rail',
    label: '右侧工具栏',
    owner: 'components/RightSidebarHost.vue',
    parent: 'shell.right-drawer',
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'color', 'background', 'opacity', 'visibility'],
    protection: 'editable',
  },
  {
    id: 'shell.split',
    label: '分屏布局',
    owner: 'components/CoreSplitWorkspace.vue',
    // user:“我认为主区和分屏本质是一个容器”+
    // (分屏不是独立区域，而是内容区的布局模式：挂在 shell.main 下，尺寸写内容区宽度变量。)
    parent: 'shell.main',
    properties: ['position', 'size', 'spacing', 'radius', 'border', 'color', 'background', 'opacity', 'layer'],
    protection: 'editable',
  },
  {
    id: 'chat.thread',
    label: '会话内容',
    owner: 'components/ChatThread.vue',
    parent: 'shell.main',
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'color', 'text', 'opacity'],
    protection: 'editable',
  },
  {
    id: 'template.message',
    label: '消息行',
    kind: 'template',
    owner: 'components/MessageView.vue',
    parent: 'chat.thread',
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'border', 'color', 'background', 'text', 'opacity'],
    protection: 'editable',
    note: '每条消息共用同一套样式，改一次影响全部消息。',
  },
  {
    id: 'template.conversation',
    label: '会话行',
    kind: 'template',
    owner: 'components/SessionSidebar.vue',
    parent: 'shell.sidebar',
    // user:“比如我觉得现在的会话列表中的某一项有点太大了，我想把它缩小一下”+
    // (会话行开放尺寸：拖边线或改数值即可调行高；模板作用于所有分组，实例只改这一条。)
    properties: ['size', 'layer', 'spacing', 'radius', 'color', 'background', 'text', 'opacity'],
    protection: 'editable',
    note: '会话列表里每一行共用同一套样式。',
  },
  {
    // user:“我编辑了一个会话名称，那么所有的会话名称最好都与它一致”+
    // (会话名称登记为模板：改一处，所有会话行的标题一起变。)
    id: 'template.session-title',
    label: '会话名称',
    kind: 'template',
    owner: 'components/SessionSidebar.vue',
    parent: 'template.conversation',
    // user:“装文字它本身就是一个容器，它是可以被拖动拉伸的，就像 PPT 里面一样”+
    // (文字也能拖动与拉伸：容器变大不再裁字。)
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'color', 'text', 'opacity'],
    protection: 'editable',
    note: '所有会话行的标题共用一套文字样式。',
  },
  {
    // user:“我改了这一个项目，那么所有的项目行都应该被同时应用这个改动”+
    // (项目行登记为模板：尺寸/间距/外观改一处全部项目行同步。)
    id: 'template.project',
    label: '项目行',
    kind: 'template',
    owner: 'components/SessionSidebar.vue',
    parent: 'shell.sidebar',
    properties: ['size', 'layer', 'spacing', 'radius', 'color', 'background', 'text', 'opacity'],
    protection: 'editable',
    note: '所有项目行共用一套样式。',
  },
  {
    id: 'template.project-name',
    label: '项目名称',
    kind: 'template',
    owner: 'components/SessionSidebar.vue',
    parent: 'template.project',
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'color', 'text', 'opacity'],
    protection: 'editable',
    note: '所有项目行的名称共用一套文字样式。',
  },
  {
    id: 'page.root',
    label: '整版页面',
    owner: 'components/CoreAppPage.vue',
    parent: 'shell.main',
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'color', 'background', 'opacity'],
    protection: 'editable',
  },
  {
    id: 'settings.root',
    label: '设置页',
    owner: 'components/CoreSettings.vue',
    parent: 'page.root',
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'border', 'color', 'background', 'opacity'],
    protection: 'editable',
    note: '主题编辑器的宿主页面，可拖动、可调尺寸，不允许隐藏。',
  },
  {
    id: 'settings.theme-editor',
    label: '主题编辑器',
    owner: 'components/ThemeEditor.vue',
    parent: 'settings.root',
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'border', 'color', 'background', 'opacity', 'text'],
    protection: 'editable',
  },
  {
    id: 'library.root',
    label: '资料库',
    owner: 'components/LibraryHomeView.vue',
    parent: 'page.root',
    properties: ['position', 'size', 'layer', 'spacing', 'radius', 'border', 'color', 'background', 'text', 'opacity'],
    protection: 'editable',
  },
]
