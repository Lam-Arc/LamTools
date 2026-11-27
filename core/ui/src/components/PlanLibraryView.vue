<template>
  <div
    class="plan-library-view library-surface full-area-view"
    :aria-busy="loading"
    :style="{ '--library-zoom': String(zoom) }"
    @wheel="onZoomWheel"
  >
    <FullAreaActions :to-band="bandActions">
      <!-- 编辑：一个「确认」收尾——保存（若有改动）并直接回到阅读 -->
      <template v-if="mode === 'editor' && selected">
        <button
          class="library-button library-button--primary"
          type="button"
          :disabled="saving"
          data-library-editor-confirm
          @click="confirmEditor"
        >{{ saving ? t("保存中…") : t("确认") }}</button>
      </template>
      <!-- 列表 / 文件夹：工具栏动作；阅读：文档动作 -->
      <template v-else-if="mode === 'reader' && selected">
        <button
          class="library-button library-button--primary"
          type="button"
          :disabled="selected.status !== 'ready'"
          :title="startTitle"
          data-library-start
          @click="emit('start-plan', selected)"
        >{{ t("开工") }}</button>
        <button class="library-button" type="button" @click="openEditor(selected)">{{ t("编辑") }}</button>
        <button
          class="library-button library-button--danger"
          type="button"
          :data-library-delete="confirmingDelete ? 'confirm' : 'arm'"
          @click="removeSelected"
          @blur="confirmingDelete = false"
        >{{ confirmingDelete ? t("确认删除") : t("删除") }}</button>
      </template>
      <template v-else>
        <button class="icon-button" type="button" :disabled="loading" :aria-label="t('刷新')" :title="t('刷新')" data-library-refresh @click="reload">
          <RefreshCw :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <!-- 资料库跟随项目文件夹：没选项目就没有可写的位置，按钮先别装作能按。 -->
        <button class="library-button" type="button" :disabled="!activeProjectId" :title="activeProjectId ? '' : t('先进入一个项目的方案')" data-library-create-folder @click="openDialog('create-folder')">{{ t("新建文件夹") }}</button>
        <button class="library-button" type="button" :disabled="!activeProjectId || !importPlanFile" :title="importPlanFile ? '' : t('当前环境不支持选择文件')" data-library-import @click="importPlanFromFile">{{ t("导入") }}</button>
        <button class="library-button library-button--primary" type="button" :disabled="!activeProjectId" :title="activeProjectId ? '' : t('先进入一个项目的方案')" data-library-create @click="openDialog('create-plan')">
          <Plus :size="14" :stroke-width="1.8" aria-hidden="true" />{{ t("新建方案") }}</button>
      </template>
    </FullAreaActions>

    <div class="library-mobile-head">
      <button class="library-back" type="button" :aria-label="t('返回')" :title="t('返回')" @click="onBackClick">
        <ArrowLeft :size="16" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <p v-if="mode === 'reader' && selected" class="library-crumb" data-library-crumb>{{ activeProjectName }}<span class="crumb-sep" aria-hidden="true">›</span> {{ truncateTitle(displayTitle(selected)) }}
      </p>
      <!-- 文件夹可以嵌套：面包屑逐层可点，最后一段是当前层。 -->
      <nav v-else-if="openFolder" class="library-crumb" data-library-crumb :aria-label="t('位置')">
        <button v-if="projectOptions.length" type="button" class="crumb-link" data-library-crumb-projects @click="leaveProject">{{ t("方案") }}</button>
        <span v-if="projectOptions.length" class="crumb-sep" aria-hidden="true">›</span>
        <button type="button" class="crumb-link" @click="goToFolder('')">{{ activeProjectName }}</button>
        <template v-for="(step, index) in folderTrail" :key="step.dir">
          <span class="crumb-sep" aria-hidden="true">›</span>
          <button
            type="button"
            class="crumb-link"
            :class="{ 'crumb-link--current': index === folderTrail.length - 1 }"
            :aria-current="index === folderTrail.length - 1 ? 'page' : undefined"
            :data-library-crumb-step="step.dir"
            @click="goToFolder(step.dir)"
          >{{ step.name }}</button>
        </template>
      </nav>
      <div v-else class="library-head-copy">
        <h1 class="library-title">{{ atProjectLevel ? t("方案") : activeProjectName }}</h1>
        <p class="library-subtitle">{{ atProjectLevel ? t("所有项目的方案都在这里 — 选一个项目进去看。") : t("「{0}」文件夹里的方案 — 点开读全文，就绪后开工。", { 0: dirName }) }}</p>
      </div>
    </div>

    <!-- user:“库本身的全局与项目划分也仅是一个文件划分”+(库根列所有项目；进项目才读写它的「方案/」)。 -->
    <div v-if="atProjectLevel && projectOptions.length" class="folder-grid" role="list" data-plan-projects>
      <article
        v-for="project in projectOptions"
        :key="project.id"
        class="folder-card"
        role="listitem"
        tabindex="0"
        :aria-label="t('打开 {0} 的方案', { 0: project.name })"
        :data-plan-project="project.id"
        @click="enterProject(project)"
        @keydown.enter.prevent="enterProject(project)"
      >
        <span class="folder-card-icon" aria-hidden="true"><Folder :size="18" :stroke-width="1.6" /></span>
        <span class="folder-card-name">{{ project.name }}</span>
        <span class="folder-card-count">{{ project.id === projectId ? t("当前项目") : t("进入方案") }}</span>
      </article>
    </div>
    <p v-else-if="atProjectLevel" class="full-area-note">{{ t("还没有项目 — 先建一个项目，方案会写进它的「方案」文件夹。") }}</p>

    <!-- ── 阅读子页 ── -->
    <section v-else-if="mode === 'reader' && selected" class="library-reader" :aria-label="t('方案阅读')" data-library-reader>
      <header class="library-reader-head">
        <h2 class="library-reader-title">{{ displayTitle(selected) }}</h2>
        <p class="library-reader-meta">
          <span class="plan-type-badge" :data-plan-type="selected.type || 'none'">{{ selected.type_label || t('未分类') }}</span>
          <span class="library-status" :data-plan-status="selected.design_status">{{ designStatusLabel(selected.design_status) }}</span>
          <span v-if="selected.impl_status !== 'none'" class="library-status" :data-plan-impl="selected.impl_status">{{ implStatusLabel(selected.impl_status) }}</span>
          <button v-if="selected.topic" class="library-link plan-topic" type="button" :title="t('只看这个专题')" data-plan-topic @click="focusTopic(selected.topic)">{{ t("专题 · {0}", { 0: selected.topic }) }}</button>
          <span v-if="contentUpdatedAt">{{ t("更新于") }}{{ contentUpdatedAt }}</span>
          <button class="library-link" type="button" data-plan-meta-toggle @click="toggleMetaEditor">{{ t("信息") }}</button>
        </p>
      </header>
      <!-- 元数据面板：只改 frontmatter，正文不动。 -->
      <div v-if="metaEditing" class="plan-meta-panel" data-plan-meta-panel>
        <label class="plan-meta-field">
          <span>{{ t("类型") }}</span>
          <select v-model="metaDraft.type" data-plan-meta-type>
            <option value="">{{ t("未分类") }}</option>
            <option v-for="item in PLAN_TYPE_OPTIONS" :key="item.code" :value="item.code">{{ item.label }}</option>
          </select>
        </label>
        <label class="plan-meta-field">
          <span>{{ t("设计状态") }}</span>
          <select v-model="metaDraft.design_status" data-plan-meta-design>
            <option value="draft">{{ t("草案") }}</option>
            <option value="active">{{ t("生效") }}</option>
            <option value="archived">{{ t("已归档") }}</option>
            <option value="deprecated">{{ t("已废弃") }}</option>
          </select>
        </label>
        <label class="plan-meta-field">
          <span>{{ t("实施状态") }}</span>
          <select v-model="metaDraft.impl_status" data-plan-meta-impl>
            <option value="none">{{ t("未实施") }}</option>
            <option value="doing">{{ t("实施中") }}</option>
            <option value="review">{{ t("待验收") }}</option>
            <option value="accepted">{{ t("已验收") }}</option>
          </select>
        </label>
        <label class="plan-meta-field">
          <span>{{ t("专题") }}</span>
          <input v-model="metaDraft.topic" type="text" :placeholder="t('可选，例如：Sunday Memory')" data-plan-meta-topic />
        </label>
        <div class="plan-meta-actions">
          <button class="library-button" type="button" @click="metaEditing = false">{{ t("取消") }}</button>
          <button class="library-button library-button--primary" type="button" :disabled="metaSaving" data-plan-meta-save @click="saveMeta">{{ metaSaving ? t("保存中…") : t("保存信息") }}</button>
        </div>
        <p v-if="metaError" class="full-area-note full-area-note--error" role="alert">{{ metaError }}</p>
      </div>

      <!-- Agent 动作：都是给方案带上文的一次会话任务，不另建执行系统。 -->
      <div class="plan-agent-actions" data-plan-actions>
        <button v-for="action in PLAN_ACTIONS" :key="action.id" class="library-button" type="button" :data-plan-action="action.id" :title="action.hint" @click="startPlanAction(action.id)">{{ action.label }}</button>
        <span class="plan-actions-gap" aria-hidden="true" />
        <button class="library-button" type="button" data-plan-export @click="exportPlan">{{ t("导出") }}</button>
        <button class="library-button" type="button" data-plan-copy @click="copyPlanContent">{{ t("复制全文") }}</button>
      </div>

      <p v-if="contentLoading" class="full-area-note" role="status">{{ t("正在打开…") }}</p>
      <p v-else-if="contentError" class="full-area-note full-area-note--error" role="alert">{{ contentError }}</p>
      <template v-else>
        <nav v-if="toc.length > 1" class="plan-toc" :aria-label="t('文档目录')" data-plan-toc>
          <p class="plan-toc-title">{{ t("目录") }}</p>
          <button v-for="item in toc" :key="item.id" class="plan-toc-link" type="button" :data-plan-toc-item="item.text" @click="scrollToHeading(item.text)">{{ item.text }}</button>
        </nav>
        <article ref="readerDocEl" class="library-document">
          <MarkdownRenderer :content="documentBody" />
        </article>
      </template>

      <section v-if="relatedPlans.length || sessionLinks.length" class="plan-relations" data-plan-relations>
        <p class="plan-toc-title">{{ t("关联") }}</p>
        <div class="plan-relation-list">
          <button v-for="plan in relatedPlans" :key="plan.path" class="plan-relation" type="button" :data-plan-relation="plan.path" @click="openEntry(plan)">
            <span class="plan-type-badge plan-type-badge--small">{{ plan.type_label }}</span>{{ displayTitle(plan) }}
          </button>
          <span v-for="session in sessionLinks" :key="session" class="plan-relation plan-relation--session" :data-plan-session="session">{{ t("会话") }} · {{ session }}</span>
        </div>
      </section>
    </section>

    <!-- ── 编辑子页：资料库自己的编辑器，写方案原文，不跳文件工作台 ── -->
    <section v-else-if="mode === 'editor' && selected" class="library-editor" :aria-label="t('方案编辑')" data-library-editor>
      <header class="library-editor-head">
        <h2 class="library-editor-title">{{ displayTitle(selected) }}</h2>
        <p class="library-editor-meta">
          <span :class="dirty ? 'library-editor-state library-editor-state--dirty' : 'library-editor-state'" data-library-editor-state>
            {{ dirty ? t("未保存") : t("已保存") }}
          </span>
          <span class="library-editor-path">{{ selected.path }}</span>
        </p>
      </header>
      <p v-if="editorLoading" class="full-area-note" role="status">{{ t("正在打开…") }}</p>
      <template v-else>
        <DocumentEditor ref="editorInput" id-prefix="library-editor" :title="displayTitle(selected)" v-model="draft">
          <template #preview="{ content }">
            <MarkdownRenderer :content="content" />
          </template>
        </DocumentEditor>
        <p v-if="saveError" class="full-area-note full-area-note--error" role="alert">{{ saveError }}</p>
      </template>
    </section>

    <template v-else>
      <!-- ── 工具栏：搜索 + 视图切换 ── -->
      <div class="library-toolbar" data-library-toolbar>
        <!-- user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(共享搜索框并保留本页查询和无障碍标签)。 -->
        <LibrarySearchField v-model="query" :label="t('搜索资料库')" :input-attrs="{ 'data-library-search': '' }" />
        <!-- user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(共享视图切换并保留本页的状态与保存方式)。 -->
        <LibraryViewToggle v-model="viewMode" data-library-view-toggle />
      </div>

      <!-- 方案筛选：类型 / 专题 / 实施状态与排序；项目根层没有可筛的内容，不显示。 -->
      <div v-if="activeProjectId" class="library-filters" data-plan-filters>
        <label class="library-filter">
          <span>{{ t("类型") }}</span>
          <select v-model="typeFilter" data-plan-filter-type>
            <option value="">{{ t("全部类型") }}</option>
            <option v-for="item in PLAN_TYPE_OPTIONS" :key="item.code" :value="item.code">{{ item.label }}</option>
          </select>
        </label>
        <label v-if="topicOptions.length" class="library-filter">
          <span>{{ t("专题") }}</span>
          <select v-model="topicFilter" data-plan-filter-topic>
            <option value="">{{ t("全部专题") }}</option>
            <option v-for="topic in topicOptions" :key="topic" :value="topic">{{ topic }}</option>
          </select>
        </label>
        <label class="library-filter">
          <span>{{ t("实施") }}</span>
          <select v-model="implFilter" data-plan-filter-impl>
            <option value="">{{ t("全部") }}</option>
            <option value="none">{{ t("未实施") }}</option>
            <option value="doing">{{ t("实施中") }}</option>
            <option value="review">{{ t("待验收") }}</option>
            <option value="accepted">{{ t("已验收") }}</option>
          </select>
        </label>
        <label class="library-filter">
          <span>{{ t("排序") }}</span>
          <select v-model="sortMode" data-plan-sort>
            <option value="updated">{{ t("最近修改") }}</option>
            <option value="name">{{ t("名称") }}</option>
            <option value="type">{{ t("类型") }}</option>
          </select>
        </label>
        <button v-if="filtersActive" class="library-link" type="button" data-plan-clear-filters @click="clearPlanFilters">{{ t("清除筛选") }}</button>
      </div>

      <!-- ── 筛选页签 ── -->
      <div class="filter-tabs" role="group" :aria-label="t('筛选资料库')" data-library-tabs>
        <button
          v-for="tab in TABS"
          :key="tab.id"
          type="button"
          :class="{ active: activeTab === tab.id }"
          :aria-pressed="activeTab === tab.id"
          :data-library-tab="tab.id"
          @click="activeTab = tab.id"
        >{{ tab.label }}</button>
      </div>

      <p v-if="loading && !entries.length && !folders.length" class="full-area-note" role="status">{{ t("正在读取资料库…") }}</p>
      <p v-else-if="error" class="full-area-note full-area-note--error" role="alert">
        {{ error }}<button class="library-link" type="button" @click="reload">{{ t("重试") }}</button>
      </p>

      <template v-else>
        <!-- ── 子文件夹：根上的「文件夹」页签，以及文件夹详情里的下一层 ── -->
        <!-- user:“确保视觉、功能和交互不退化”+(卡片内菜单的回车只操作菜单，不触发卡片打开)。 -->
        <div v-if="showFolderGrid" class="folder-grid" role="list" data-library-folders>
          <article
            v-for="folder in childFolders"
            :key="folder.path"
            class="folder-card"
            role="listitem"
            tabindex="0"
            :aria-label="t('打开文件夹 {0}', { 0: folder.name })"
            :data-library-folder="folder.dir"
            @click="goToFolder(folder.dir)"
            @keydown.enter.self.prevent="goToFolder(folder.dir)"
            @contextmenu="openFolderMenu($event, folder)"
          >
            <span class="folder-card-icon" aria-hidden="true"><Folder :size="18" :stroke-width="1.6" /></span>
            <span class="folder-card-name">{{ folder.name }}</span>
            <span class="folder-card-count">{{ folder.count }} {{ t("份方案") }}</span>
            <button class="card-menu-btn" type="button" :aria-label="t('{0} 的操作', { 0: folder.name })" @click.stop="openFolderMenu($event, folder)">
              <MoreHorizontal :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </article>
        </div>

        <!-- ── 空态 ── -->
        <div v-if="folderTabActive && childFolders.length === 0 && !searching" class="full-area-empty" data-folders-empty>
          <span class="full-area-empty-icon" aria-hidden="true"><Folder :size="18" :stroke-width="1.8" /></span>
          <h2 class="full-area-empty-title">{{ openFolder ? t("这里还没有子文件夹") : t("创建你的第一个文件夹") }}</h2>
          <p class="full-area-empty-hint">{{ t("创建文件夹，整理资料库中的方案。") }}</p>
          <button class="library-button library-button--primary" type="button" data-folders-create @click="openDialog('create-folder')">{{ t("创建文件夹") }}</button>
        </div>
        <div v-else-if="!openFolder && entries.length === 0" class="full-area-empty" data-library-empty>
          <span class="full-area-empty-icon" aria-hidden="true"><BookOpen :size="18" :stroke-width="1.8" /></span>
          <h2 class="full-area-empty-title">{{ t("还没有方案") }}</h2>
          <p class="full-area-empty-hint">{{ t("在聊天里说出你的想法，助手会一边问一边把方案写进「") }}{{ dirName }}{{ t("」文件夹；写好后就出现在这里。 方案是一篇普通的 Markdown 文档，你也可以直接新建一篇来写。") }}</p>
          <button class="library-button library-button--primary" type="button" data-library-empty-create @click="openDialog('create-plan')">{{ t("新建方案") }}</button>
        </div>
        <!-- user:“去找四个库中用户体验最差的点，处理掉”+(先分“真没有方案”，再分“没匹配”：
             搜索没命中时给一键清除，不再说库是空的、也不再留白)。 -->
        <div v-else-if="searching && !listEntries.length" class="full-area-empty" data-library-no-results>
          <span class="full-area-empty-icon" aria-hidden="true"><SearchX :size="18" :stroke-width="1.8" /></span>
          <h2 class="full-area-empty-title">{{ t("没有匹配的文件") }}</h2>
          <p class="full-area-empty-hint">{{ t("换个关键词，或清除筛选条件。") }}</p>
          <button class="library-button" type="button" data-library-clear-filters @click="clearFilters">{{ t("清除筛选") }}</button>
        </div>
        <div v-else-if="openFolder && !showFolderGrid && folderEntries.length === 0" class="folder-empty" data-folder-empty>
          <Upload :size="18" :stroke-width="1.6" aria-hidden="true" />
          <p>{{ t("这个文件夹还是空的 — 点右上角「新建方案」，它会建在这里。") }}</p>
        </div>
        <p v-else-if="!openFolder && filteredEntries.length === 0" class="full-area-note tab-empty" data-library-tab-empty>
          {{ activeTab === 'favorites' ? t("还没有收藏的方案 — 在方案卡片的菜单里「添加到收藏」。") : t("这个状态下暂无方案。") }}
        </p>

        <!-- ── 方案本体（网格 / 列表）：文件夹详情与主列表共用一块 ── -->
        <template v-if="!folderTabActive && listEntries.length">
        <div v-if="viewMode === 'grid'" class="plan-grid" role="list">
          <article
            v-for="entry in listEntries"
            :key="entry.path"
            class="plan-card"
            role="listitem"
            tabindex="0"
            :aria-label="t('打开 {0}', { 0: displayTitle(entry) })"
            :data-library-entry="entry.name"
            @click="openEntry(entry)"
            @keydown.enter.self.prevent="openEntry(entry)"
            @contextmenu="openEntryMenu($event, entry)"
          >
            <div class="plan-card-preview">
              <p class="plan-card-summary">{{ entry.summary || t("还没有摘要 — 打开写第一段。") }}</p>
              <FileText :size="26" :stroke-width="1.4" aria-hidden="true" class="plan-card-glyph" />
            </div>
            <button class="card-menu-btn" type="button" :aria-label="t('{0} 的操作', { 0: displayTitle(entry) })" @click.stop="openEntryMenu($event, entry)">
              <MoreHorizontal :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
            <h4 class="plan-card-title">{{ displayTitle(entry) }}</h4>
            <div class="plan-card-tags">
              <span class="plan-type-badge plan-type-badge--small" :data-plan-type="entry.type || 'none'">{{ entry.type_label || t('未分类') }}</span>
              <span v-if="entry.topic" class="plan-topic-chip">{{ entry.topic }}</span>
            </div>
            <div class="plan-card-foot">
              <span class="library-status" :data-plan-status="entry.design_status">{{ designStatusLabel(entry.design_status) }}</span>
              <Star v-if="entry.favorite" :size="12" :stroke-width="1.8" :aria-label="t('已收藏')" class="plan-card-star" />
              <span class="plan-card-time">{{ shortDate(entry.updated_at) }}</span>
            </div>
          </article>
        </div>

        <ul v-else class="library-items" role="list">
          <li v-for="entry in listEntries" :key="entry.path">
            <div
              class="library-row"
              role="button"
              tabindex="0"
              :data-library-entry="entry.name"
              @click="openEntry(entry)"
              @keydown.enter.self.prevent="openEntry(entry)"
              @contextmenu="openEntryMenu($event, entry)"
            >
              <div class="library-item-top">
                <span class="library-item-title">{{ displayTitle(entry) }}</span>
                <span class="plan-type-badge plan-type-badge--small" :data-plan-type="entry.type || 'none'">{{ entry.type_label || t('未分类') }}</span>
                <Star v-if="entry.favorite" :size="12" :stroke-width="1.8" :aria-label="t('已收藏')" class="plan-card-star" />
                <span class="library-status" :data-plan-status="entry.design_status">{{ designStatusLabel(entry.design_status) }}</span>
              </div>
              <div class="library-item-bottom">
                <span class="library-item-summary">{{ entry.summary || t("（还没有摘要）") }}</span>
                <span class="library-item-time">{{ updatedLabel(entry.updated_at) }}</span>
              </div>
              <button class="card-menu-btn" type="button" :aria-label="t('{0} 的操作', { 0: displayTitle(entry) })" @click.stop="openEntryMenu($event, entry)">
                <MoreHorizontal :size="15" :stroke-width="1.8" aria-hidden="true" />
              </button>
            </div>
          </li>
        </ul>
        </template>
      </template>
    </template>

    <!-- ── 新建 / 重命名对话框 ── -->
    <!-- user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(命名表单共享结构，保留各页面的校验及提交)。 -->
    <Transition name="library-dialog">
      <LibraryNameDialog v-if="dialog" v-model="dialog.value" :title="dialogTitle" :field-label="dialog.kind === 'create-folder' ? t('文件夹名称') : t('方案名称')" :placeholder="dialog.kind === 'create-folder' ? t('例如：迭代计划') : t('例如：导出显示进度')" :busy="dialog.busy" :error="dialog.error" :submit-label="dialog.kind === 'rename' ? t('重命名') : t('创建')" :input-attrs="{ 'data-library-dialog-input': dialog.kind }" :submit-attrs="{ 'data-library-dialog-submit': '' }" data-library-dialog @cancel="closeDialog" @submit="submitDialog">
        <!-- 类型可留空：先建一篇空白方案，之后再定也不迟（A11）。 -->
        <template #extra>
          <label v-if="dialog.kind === 'create-plan'" class="dialog-field">
            <span>{{ t("类型（可选）") }}</span>
            <select v-model="createType" data-library-dialog-type>
              <option value="">{{ t("未分类 — 先写内容，之后再定") }}</option>
              <option v-for="item in PLAN_TYPE_OPTIONS" :key="item.code" :value="item.code">{{ item.label }}</option>
            </select>
          </label>
        </template>
      </LibraryNameDialog>
    </Transition>

    <!-- ── 放弃未保存修改的确认 ── -->
    <LibraryConfirmDialog :open="pendingDiscard" :title="t('放弃修改')" :aria-label="t('确认放弃修改')" :cancel-label="t('继续编辑')" :confirm-label="t('放弃修改')" :confirm-attrs="{ 'data-library-discard-confirm': '' }" data-library-discard @cancel="pendingDiscard = false" @confirm="discardEditor">
      「{{ selected ? displayTitle(selected) : '' }}{{ t("」还有没保存的内容，离开就会丢掉。") }}
    </LibraryConfirmDialog>

    <!-- ── 删除确认 ── -->
    <!-- user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(方案删除沿用共享确认框并保留不可恢复的警告)。 -->
    <LibraryConfirmDialog :open="Boolean(pendingDelete)" :title="t('删除方案')" :aria-label="t('确认删除')" :confirm-label="t('删除')" :confirm-attrs="{ 'data-library-confirm-delete': '' }" data-library-confirm @cancel="pendingDelete = null" @confirm="confirmDelete">
      「{{ pendingDelete ? displayTitle(pendingDelete) : '' }}{{ t("」将被删除，且无法恢复。") }}
    </LibraryConfirmDialog>
  </div>
</template>

<script setup lang="tsx">
import { useSplitKeyboardScope } from '@/split/keyboardScope'
const splitKeyboardActive = useSplitKeyboardScope()
import { t } from '@/i18n/index.ts'
import LibraryViewToggle from '@/components/LibraryViewToggle.vue'
import LibrarySearchField from '@/components/LibrarySearchField.vue'
import LibraryConfirmDialog from '@/components/LibraryConfirmDialog.vue'
import LibraryNameDialog from '@/components/LibraryNameDialog.vue'

/**
 * PlanLibraryView — the 资料库 as one full-area view.
 *
 * A plan (方案) is a markdown document in the project's 「方案/」 folder; the
 * agent drafts and edits those files during ordinary conversation. The view
 * follows the library standard: toolbar (search + view toggle + create),
 * filter tabs (全部 / 收藏 / 文件夹 / 状态), a card grid with a list variant,
 * a per-item context menu, folder detail pages, and a reader sub-page — the
 * header band tracks where you are via `heading`.
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  BookOpen,
  FileText,
  Folder,
  MoreHorizontal,
  Plus,
  RefreshCw,
  SearchX,
  Star,
  Trash2,
  Upload,
} from 'lucide-vue-next'
import type { CorePlanLibraryEntry, CorePlanLibraryFolder, CorePlanMetaPatch, CorePlanType, CoreProjectClient } from '@/projects/client.ts'
import FullAreaActions from '@/components/FullAreaActions.vue'
import DocumentEditor from '@/components/DocumentEditor.vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import { useLibraryZoom } from '@/composables/useLibraryZoom.ts'
import { openContextMenu, type ContextMenuEntry } from '@/components/context-menu/index.ts'

export type PlanLibraryEntry = CorePlanLibraryEntry

/** 方案详情里的 Agent 动作：都是给方案带上文的一次会话任务。 */
export type PlanAction = 'discuss' | 'review' | 'revise' | 'execute' | 'check'

const props = defineProps<{
  /** The switchable project client (desktop HTTP or the phone's standalone bridge). */
  client: CoreProjectClient
  /** The project whose 「方案/」 folder this library reads. */
  projectId?: string | null
  /** Bumped by the host when a turn finishes — the cue to rescan the folder. */
  refreshSignal?: number
  /** Desktop sends actions into the header band; phones render them in place. */
  bandActions?: boolean
  /** 顶部条标题的根名：在资料库里这项叫「方案」。 */
  rootLabel?: string
  /** 全部项目（id/name）：库根列出所有项目的方案位置，项目只是文件归属。 */
  projects?: Array<{ id: string; name: string }>
  /** 从现有文件导入：桌面返回源路径，其它环境返回文件名与正文；未注入表示不支持。 */
  importPlanFile?: () => Promise<{ path?: string; name?: string; text?: string } | null>
}>()

const emit = defineEmits<{
  back: []
  'start-plan': [entry: PlanLibraryEntry]
  /** 讨论 / 审查 / 修订 / 实施 / 检查落实情况：由宿主起会话并预制提示词。 */
  'plan-action': [payload: { entry: PlanLibraryEntry; action: PlanAction }]
  /** 顶部条标题跟随内部子页（列表 / 文件夹 / 阅读 / 编辑）。 */
  heading: [payload: { title: string; subtitle: string }]
}>()

const dirName = '方案'
const rootLabel = computed(() => props.rootLabel || t("资料库"))

/**
 * user:“库本身的全局与项目划分也仅是一个文件划分”+(方案库不再绑定当前项目：
 * 有项目清单时先列所有项目的位置，进哪个项目才读写哪个项目的「方案/」)。
 */
const projectOptions = computed(() => props.projects ?? [])
const activeProjectId = ref(projectOptions.value.length ? '' : (props.projectId ?? ''))
const atProjectLevel = computed(() => !activeProjectId.value)
const activeProjectName = computed(() =>
  projectOptions.value.find(project => project.id === activeProjectId.value)?.name ?? t("资料库"))

/* ---- 卡片墙缩放：Ctrl+滚轮增减，资料与方案共用一档 ---- */
const { zoom, onZoomWheel } = useLibraryZoom()
const entries = ref<PlanLibraryEntry[]>([])
const folders = ref<CorePlanLibraryFolder[]>([])
const loading = ref(false)
const error = ref('')

const TABS = [
  { id: 'all', get label() { return t("全部") } },
  { id: 'favorites', get label() { return t("收藏") } },
  { id: 'folders', get label() { return t("文件夹") } },
  { id: 'draft', get label() { return t("草案") } },
  { id: 'active', get label() { return t("生效") } },
  { id: 'archived', get label() { return t("已归档") } },
  { id: 'deprecated', get label() { return t("已废弃") } },
] as const
type TabId = (typeof TABS)[number]['id']
const activeTab = ref<TabId>('all')
const query = ref('')

type ViewMode = 'grid' | 'list'
const VIEW_STORAGE_KEY = 'lamtools.core.library.view'
const viewMode = ref<ViewMode>(readStoredView())
function readStoredView(): ViewMode {
  try {
    return window.localStorage.getItem(VIEW_STORAGE_KEY) === 'list' ? 'list' : 'grid'
  } catch {
    return 'grid'
  }
}
watch(viewMode, (value) => {
  try {
    window.localStorage.setItem(VIEW_STORAGE_KEY, value)
  } catch { /* 无存储时仅当前会话生效 */ }
})

/* ---- 子页导航：列表 ↔ 文件夹 ↔ 阅读 ↔ 编辑，顶部条标题随动 ---- */
const mode = ref<'listing' | 'reader' | 'editor'>('listing')
const openFolder = ref('')
const readerFrom = ref<'listing' | 'folder'>('listing')
const selected = ref<PlanLibraryEntry | null>(null)
const content = ref('')
const contentLoading = ref(false)
const contentError = ref('')
const contentUpdatedAt = ref('')
const confirmingDelete = ref(false)

/* ---- 编辑子页：写方案原文，资料库自己的编辑器 ---- */
const draft = ref('')
const editorBaseline = ref('')
const editorLoading = ref(false)
const saving = ref(false)
const saveError = ref('')
const pendingDiscard = ref(false)
const editorInput = ref<{ focus: () => void; setPreviewing: (value: boolean) => void } | null>(null)
const dirty = computed(() => draft.value !== editorBaseline.value)

/* ---- 对话框（新建 / 新建文件夹 / 重命名）与删除确认 ---- */
type DialogKind = 'create-plan' | 'create-folder' | 'rename'
const dialog = ref<{ kind: DialogKind; value: string; error: string; busy: boolean; target?: PlanLibraryEntry } | null>(null)
const pendingDelete = ref<PlanLibraryEntry | null>(null)

/** 设计状态四档（PRD §8.1）：草案 / 生效 / 已归档 / 已废弃。 */
const DESIGN_STATUS_LABELS: Record<PlanLibraryEntry['design_status'], string> = {
  draft: '草案',
  active: '生效',
  archived: '已归档',
  deprecated: '已废弃',
}

function designStatusLabel(status: PlanLibraryEntry['design_status']): string {
  return DESIGN_STATUS_LABELS[status] ?? t("草案")
}

/** 实施状态四档（PRD §8.2），研究 / 审查 / 报告等可以一直是「未实施」。 */
const IMPL_STATUS_LABELS: Record<PlanLibraryEntry['impl_status'], string> = {
  none: '未实施',
  doing: '实施中',
  review: '待验收',
  accepted: '已验收',
}

function implStatusLabel(status: PlanLibraryEntry['impl_status']): string {
  return IMPL_STATUS_LABELS[status] ?? t("未实施")
}

/** 一级分类与扩展分类共用一份选项；扩展分类排在后面，不抢一级入口。 */
const PLAN_TYPE_OPTIONS: Array<{ code: CorePlanType; get label(): string }> = [
  { code: 'PRD', get label() { return t("PRD · 产品需求文档") } },
  { code: 'SPEC', get label() { return t("SPEC · 技术规范") } },
  { code: 'DESIGN', get label() { return t("DESIGN · 设计方案") } },
  { code: 'RESEARCH', get label() { return t("RESEARCH · 调研方案") } },
  { code: 'EXP', get label() { return t("EXP · 实验方案") } },
  { code: 'PLAN', get label() { return t("PLAN · 实施方案") } },
  { code: 'AUDIT', get label() { return t("AUDIT · 审查方案") } },
  { code: 'REPORT', get label() { return t("REPORT · 结果报告") } },
  { code: 'ARCH', get label() { return t("ARCH · 架构设计") } },
  { code: 'ADR', get label() { return t("ADR · 架构决策记录") } },
  { code: 'RFC', get label() { return t("RFC · 提案与讨论") } },
  { code: 'POC', get label() { return t("POC · 概念验证") } },
  { code: 'TEST', get label() { return t("TEST · 测试方案") } },
  { code: 'MIG', get label() { return t("MIG · 迁移方案") } },
  { code: 'SOP', get label() { return t("SOP · 标准操作流程") } },
  { code: 'RCA', get label() { return t("RCA · 根因分析") } },
]

/** Agent 动作条：点下去由宿主决定在哪个项目、哪个会话里执行。 */
const PLAN_ACTIONS: Array<{ id: PlanAction; get label(): string; get hint(): string }> = [
  { id: 'discuss', get label() { return t("讨论") }, get hint() { return t("和助手讨论这份方案的目标、范围与前提") } },
  { id: 'review', get label() { return t("审查") }, get hint() { return t("请助手审查方案的合理性与可行性") } },
  { id: 'revise', get label() { return t("修订") }, get hint() { return t("按新想法修订这份方案，不重复创建") } },
  { id: 'execute', get label() { return t("实施") }, get hint() { return t("按这份方案开工，在新会话里推进") } },
  { id: 'check', get label() { return t("检查落实情况") }, get hint() { return t("对照方案核对实际做到了哪一步") } },
]

function displayTitle(entry: PlanLibraryEntry): string {
  return entry.title || entry.name.replace(/\.md$/i, '')
}

function truncateTitle(text: string): string {
  return text.length > 24 ? `${text.slice(0, 24)}…` : text
}

/**
 * 正文：去掉开头的 frontmatter（状态/摘要已在标题行给出）与首个 H1（标题行已给出），
 * 让读者看到的是一篇干净的文档，而不是带着元数据的一大块粗体。
 */
const documentBody = computed(() => stripPlanChrome(content.value))

function stripPlanChrome(markdown: string): string {
  let body = markdown
  if (body.startsWith('---')) {
    const close = body.indexOf(closingFence, 3)
    if (close !== -1) body = body.slice(body.indexOf(newline, close + 1) + 1)
  }
  return body.replace(leadingHeading, '')
}

/** Markdown 里的三处字面量：收尾分隔线、换行、首个标题行。 */
const closingFence = '\n---'
const newline = '\n'
const leadingHeading = /^\s*#\s+[^\n]*\n/

const startTitle = computed(() => {
  if (!selected.value) return ''
  if (selected.value.status === 'ready') return t("把这份方案交给当前会话执行")
  return t("方案就绪后才能开工 — 在聊天里对助手说\"可以开工了\"，它会更新方案状态")
})

function updatedLabel(epochSeconds: number): string {
  if (!epochSeconds) return ''
  const date = new Date(epochSeconds * 1000)
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function shortDate(epochSeconds: number): string {
  if (!epochSeconds) return ''
  const date = new Date(epochSeconds * 1000)
  const pad = (n: number): string => String(n).padStart(2, '0')
  return t("{0}月{1}日", { 0: pad(date.getMonth() + 1), 1: pad(date.getDate()) })
}

/* ---- 数据 ---- */
async function reload(): Promise<void> {
  if (!activeProjectId.value) return
  loading.value = true
  error.value = ''
  try {
    const response = await props.client.listPlanLibrary(activeProjectId.value)
    entries.value = response.entries
    folders.value = response.folders || []
    // 当前这一层可能在别处被删了；别把用户留在一间不存在的房间里。
    if (openFolder.value && !folders.value.some((folder) => folder.dir === openFolder.value)) {
      openFolder.value = ''
    }
    if (selected.value) {
      const fresh = entries.value.find((entry) => entry.path === selected.value?.path)
      if (!fresh) {
        clearSelection()
      } else {
        selected.value = fresh
        void loadContent()
      }
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

async function loadContent(): Promise<void> {
  const entry = selected.value
  if (!entry || !activeProjectId.value) return
  contentLoading.value = true
  contentError.value = ''
  try {
    const response = await props.client.readFile(activeProjectId.value, entry.path)
    content.value = response.content
    contentUpdatedAt.value = updatedLabel(entry.updated_at)
  } catch (cause) {
    contentError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    contentLoading.value = false
  }
}

function openEntry(entry: PlanLibraryEntry): void {
  confirmingDelete.value = false
  metaEditing.value = false
  readerFrom.value = openFolder.value ? 'folder' : 'listing'
  selected.value = entry
  content.value = ''
  contentError.value = ''
  mode.value = 'reader'
  void loadContent()
}

/** 进编辑子页：写出方案原文，确认后回到阅读页看排版结果。 */
async function openEditor(entry: PlanLibraryEntry): Promise<void> {
  readerFrom.value = openFolder.value ? 'folder' : 'listing'
  selected.value = entry
  content.value = ''
  contentError.value = ''
  saveError.value = ''
  pendingDiscard.value = false
  mode.value = 'editor'
  draft.value = ''
  editorBaseline.value = ''
  editorLoading.value = true
  editorInput.value?.setPreviewing(false)
  try {
    const response = await props.client.readFile(activeProjectId.value!, entry.path)
    content.value = response.content
    draft.value = response.content
    editorBaseline.value = response.content
  } catch (cause) {
    saveError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    editorLoading.value = false
    void nextTick(() => editorInput.value?.focus())
  }
}

/**
 * 编辑页的唯一收尾动作：确认 = 保存（有改动才写盘）并直接回到阅读。
 * 写盘失败时留在编辑页，错误就近显示，改动不丢。
 */
async function confirmEditor(): Promise<void> {
  if (saving.value) return
  if (!dirty.value) {
    leaveEditor()
    return
  }
  await saveEditor()
}

async function saveEditor(): Promise<void> {
  const entry = selected.value
  if (!entry || !activeProjectId.value || saving.value || !dirty.value) return
  saving.value = true
  saveError.value = ''
  try {
    await props.client.writeFile(activeProjectId.value, entry.path, draft.value)
  } catch (cause) {
    saveError.value = cause instanceof Error ? cause.message : String(cause)
    return
  } finally {
    saving.value = false
  }
  content.value = draft.value
  editorBaseline.value = draft.value
  await reload()
  // 回到阅读页：保存后该看的是排版结果，而不是刚写完的原文。
  const fresh = entries.value.find((item) => item.path === entry.path)
  if (fresh) selected.value = fresh
  mode.value = 'reader'
  contentError.value = ''
  contentUpdatedAt.value = updatedLabel(selected.value?.updated_at ?? 0)
}

/** 离开编辑页；有未保存内容先问一句。 */
function requestCloseEditor(): void {
  if (dirty.value) {
    pendingDiscard.value = true
    return
  }
  leaveEditor()
}

function discardEditor(): void {
  pendingDiscard.value = false
  leaveEditor()
}

function leaveEditor(): void {
  draft.value = ''
  editorBaseline.value = ''
  saveError.value = ''
  editorInput.value?.setPreviewing(false)
  mode.value = 'reader'
}

function clearSelection(): void {
  selected.value = null
  content.value = ''
  contentError.value = ''
  draft.value = ''
  editorBaseline.value = ''
  saveError.value = ''
  pendingDiscard.value = false
  confirmingDelete.value = false
}

async function removeSelected(): Promise<void> {
  const entry = selected.value
  if (!entry || !activeProjectId.value) return
  // 两段式确认：第一击蓄势，第二击删除；失焦即解除。
  if (!confirmingDelete.value) {
    confirmingDelete.value = true
    return
  }
  confirmingDelete.value = false
  try {
    await props.client.deletePlanLibraryFile(activeProjectId.value, entry.path)
  } catch (cause) {
    contentError.value = cause instanceof Error ? cause.message : String(cause)
    return
  }
  clearSelection()
  await reload()
}

/** 菜单里发起的删除走这个确认框。 */
async function confirmDelete(): Promise<void> {
  const entry = pendingDelete.value
  if (!entry || !activeProjectId.value) return
  pendingDelete.value = null
  error.value = ''
  try {
    await props.client.deletePlanLibraryFile(activeProjectId.value, entry.path)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    return
  }
  if (selected.value?.path === entry.path) {
    mode.value = 'listing'
    clearSelection()
  }
  await reload()
}

/* ---- 列表筛选 ---- */
/** 搜索时文件夹让位给文件结果；空态据此区分“没匹配”与“库是空的”。 */
const searching = computed(() => Boolean(query.value.trim()))

/* ---- 类型 / 专题 / 实施状态筛选与排序（PRD §7.2）---- */
const typeFilter = ref<CorePlanType | ''>('')
const topicFilter = ref('')
const implFilter = ref<'' | PlanLibraryEntry['impl_status']>('')
const sortMode = ref<'updated' | 'name' | 'type'>('updated')

const topicOptions = computed(() =>
  [...new Set(entries.value.map(entry => entry.topic).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'zh')))
const filtersActive = computed(() => Boolean(typeFilter.value || topicFilter.value || implFilter.value))

function matchesPlanFilters(entry: PlanLibraryEntry, keyword: string): boolean {
  if (typeFilter.value && entry.type !== typeFilter.value) return false
  if (topicFilter.value && entry.topic !== topicFilter.value) return false
  if (implFilter.value && entry.impl_status !== implFilter.value) return false
  if (!keyword) return true
  return entry.title.toLowerCase().includes(keyword)
    || entry.summary.toLowerCase().includes(keyword)
    || entry.name.toLowerCase().includes(keyword)
    || (entry.topic || '').toLowerCase().includes(keyword)
}

function sortPlanEntries(list: PlanLibraryEntry[]): PlanLibraryEntry[] {
  const sorted = [...list]
  if (sortMode.value === 'name') {
    sorted.sort((a, b) => displayTitle(a).localeCompare(displayTitle(b), 'zh'))
  } else if (sortMode.value === 'type') {
    sorted.sort((a, b) => (a.type || 'ZZ').localeCompare(b.type || 'ZZ') || b.updated_at - a.updated_at)
  } else {
    sorted.sort((a, b) => b.updated_at - a.updated_at)
  }
  return sorted
}

const filteredEntries = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  let list = entries.value
  if (activeTab.value === 'favorites') list = list.filter(entry => entry.favorite)
  else if (activeTab.value !== 'all' && activeTab.value !== 'folders') {
    list = list.filter(entry => entry.design_status === activeTab.value)
  }
  return sortPlanEntries(list.filter(entry => matchesPlanFilters(entry, keyword)))
})

const folderEntries = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  const list = entries.value.filter(entry => entry.folder === openFolder.value)
  return sortPlanEntries(list.filter(entry => matchesPlanFilters(entry, keyword)))
})

function clearPlanFilters(): void {
  typeFilter.value = ''
  topicFilter.value = ''
  implFilter.value = ''
}

/** 从阅读页点专题：回到列表并只看这个专题。 */
function focusTopic(topic: string): void {
  mode.value = 'listing'
  clearSelection()
  topicFilter.value = topic
}

/** 网格 / 列表同一块渲染：文件夹详情看夹内，其余看当前筛选结果。 */
const listEntries = computed(() => openFolder.value ? folderEntries.value : filteredEntries.value)

/* ---- 逐层导航：文件夹可以嵌套，openFolder 存库内相对目录（'' = 库根） ---- */
/** 根上的「文件夹」页签：只列这一层的文件夹，不混方案；搜索时让位给文件结果。 */
const folderTabActive = computed(() => !searching.value && !openFolder.value && activeTab.value === 'folders')
const childFolders = computed(() => folders.value.filter(folder => folder.parent === openFolder.value))
const showFolderGrid = computed(() =>
  !searching.value && childFolders.value.length > 0 && (folderTabActive.value || Boolean(openFolder.value)))

/** 从库根到当前层的路径，每一段都能点回去。 */
const folderTrail = computed(() => {
  const parts = openFolder.value ? openFolder.value.split('/') : []
  return parts.map((name, index) => ({ name, dir: parts.slice(0, index + 1).join('/') }))
})

function goToFolder(dir: string): void {
  openFolder.value = dir
  query.value = ''
}

/** 进入一个项目的方案：之后的新建、编辑、删除都落在这个项目里。 */
function enterProject(project: { id: string; name: string }): void {
  activeProjectId.value = project.id
}

/** 回到库根的项目清单。 */
function leaveProject(): void {
  activeProjectId.value = ''
}

/** 搜索没命中时的出口：清掉关键词与状态页签，回到全部方案（留在当前文件夹）。 */
function clearFilters(): void {
  query.value = ''
  activeTab.value = 'all'
  clearPlanFilters()
}

/** 空文件夹：这一层没有方案，也没有下一层文件夹。 */
function isFolderEmpty(folder: CorePlanLibraryFolder): boolean {
  return folder.count === 0 && !folders.value.some(child => child.parent === folder.dir)
}

/* ---- 阅读页：目录、关联、元数据与导出 ---- */
const readerDocEl = ref<HTMLElement | null>(null)
const metaEditing = ref(false)
const metaSaving = ref(false)
const metaError = ref('')
const metaDraft = ref<{
  type: CorePlanType
  design_status: PlanLibraryEntry['design_status']
  impl_status: PlanLibraryEntry['impl_status']
  topic: string
}>({ type: '', design_status: 'draft', impl_status: 'none', topic: '' })

/** 文档目录：从二级/三级标题生成，点一下滚到对应段落。 */
const toc = computed(() => {
  const items: Array<{ id: string; text: string }> = []
  for (const line of content.value.split('\n')) {
    const match = /^(#{2,3})\s+(.+)$/.exec(line.trim())
    if (!match) continue
    const heading = match[2].trim()
    if (!heading) continue
    items.push({ id: `${items.length}:${heading}`, text: heading })
  }
  return items
})

function scrollToHeading(text: string): void {
  const root = readerDocEl.value
  if (!root) return
  for (const node of Array.from(root.querySelectorAll('h2, h3'))) {
    if ((node.textContent || '').trim() === text) {
      node.scrollIntoView({ block: 'start', behavior: 'smooth' })
      return
    }
  }
}

/** 关联：frontmatter 里点名的文档 + 同一专题下的其它方案。 */
const relatedPlans = computed(() => {
  const current = selected.value
  if (!current) return []
  const found = new Map<string, PlanLibraryEntry>()
  for (const reference of current.related || []) {
    const target = entries.value.find(entry => entry.path === reference || entry.name === reference)
    if (target && target.path !== current.path) found.set(target.path, target)
  }
  if (current.topic) {
    for (const entry of entries.value) {
      if (entry.path !== current.path && entry.topic === current.topic) found.set(entry.path, entry)
    }
  }
  return [...found.values()]
})

const sessionLinks = computed(() =>
  (selected.value?.related || [])
    .filter(item => item.startsWith('会话:'))
    .map(item => item.slice(3)))

function toggleMetaEditor(): void {
  const entry = selected.value
  if (!entry) return
  if (metaEditing.value) {
    metaEditing.value = false
    return
  }
  metaDraft.value = {
    type: entry.type,
    design_status: entry.design_status,
    impl_status: entry.impl_status,
    topic: entry.topic,
  }
  metaError.value = ''
  metaEditing.value = true
}

async function saveMeta(): Promise<void> {
  const entry = selected.value
  if (!entry || !activeProjectId.value || metaSaving.value) return
  metaSaving.value = true
  metaError.value = ''
  try {
    const patch: CorePlanMetaPatch = {
      type: metaDraft.value.type,
      design_status: metaDraft.value.design_status,
      impl_status: metaDraft.value.impl_status,
      topic: metaDraft.value.topic,
    }
    await props.client.setPlanLibraryMeta(activeProjectId.value, entry.path, patch)
    await reload()
    const fresh = entries.value.find(item => item.path === entry.path)
    if (fresh) selected.value = fresh
    metaEditing.value = false
  } catch (cause) {
    metaError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    metaSaving.value = false
  }
}

/** 导出就是一篇普通 Markdown：不依赖 Sunday 也能打开（A10）。 */
function exportPlan(): void {
  const entry = selected.value
  if (!entry || !content.value) return
  const blob = new Blob([content.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = entry.name
  link.click()
  URL.revokeObjectURL(url)
}

async function copyPlanContent(): Promise<void> {
  if (!content.value) return
  try {
    await navigator.clipboard?.writeText(content.value)
  } catch { /* 剪贴板不可用时保持安静：这只是一个便利动作 */ }
}

function startPlanAction(action: PlanAction): void {
  const entry = selected.value
  if (!entry) return
  emit('plan-action', { entry, action })
}

/* ---- 收藏 ---- */
async function toggleFavorite(entry: PlanLibraryEntry): Promise<void> {
  if (!activeProjectId.value) return
  error.value = ''
  try {
    const { entry: updated } = await props.client.favoritePlanLibraryFile(activeProjectId.value, entry.path, !entry.favorite)
    entries.value = entries.value.map(item => item.path === updated.path ? updated : item)
    if (selected.value?.path === updated.path) selected.value = updated
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

/* ---- 从现有文件导入：复制一份进「方案/」，源文件不动（PRD §6.2） ---- */
async function importPlanFromFile(): Promise<void> {
  const picker = props.importPlanFile
  if (!activeProjectId.value || !picker) return
  error.value = ''
  try {
    const picked = await picker()
    if (!picked) return
    if (picked.path) {
      const { entry } = await props.client.importPlanLibraryFile(activeProjectId.value, picked.path, openFolder.value)
      await reload()
      openEntry(entry)
      return
    }
    if (!picked.text) return
    // 没有绝对路径的环境：用选中的文件名建一篇，再把正文写进去；重名自动加序号。
    const stem = (picked.name || t("导入的方案")).replace(/\.md$/i, '')
    let created: PlanLibraryEntry | null = null
    for (let index = 0; index < 50 && !created; index += 1) {
      const candidate = index === 0 ? stem : `${stem} (${index + 1})`
      try {
        created = (await props.client.createPlanLibraryFile(activeProjectId.value, candidate, openFolder.value, '', '')).entry
      } catch (cause) {
        if (index === 49) throw cause
      }
    }
    if (!created) return
    await props.client.writeFile(activeProjectId.value, created.path, picked.text)
    await reload()
    const fresh = entries.value.find(item => item.path === created?.path) ?? created
    openEntry(fresh)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

/* ---- 对话框 ---- */
/** 新建方案时的可选类型；留空就是一篇普通的空白方案（A11）。 */
const createType = ref<CorePlanType>('')

const dialogTitle = computed(() => {
  if (!dialog.value) return ''
  if (dialog.value.kind === 'create-folder') return t("新建文件夹")
  if (dialog.value.kind === 'rename') return t("重命名方案")
  return t("新建方案")
})

function openDialog(kind: DialogKind, target?: PlanLibraryEntry): void {
  if (kind === 'create-plan') createType.value = ''
  dialog.value = {
    kind,
    value: kind === 'rename' ? (target ? displayTitle(target) : '') : '',
    error: '',
    busy: false,
    target,
  }
}

function closeDialog(): void {
  dialog.value = null
}

async function submitDialog(): Promise<void> {
  const current = dialog.value
  if (!current || current.busy || !current.value.trim()) return
  if (!activeProjectId.value) {
    // 按钮已禁用；这里再兜一次，避免对话框以任何方式被打开时静默什么都不做。
    current.error = t("先在左侧选择一个项目")
    return
  }
  const name = current.value.trim()
  current.busy = true
  current.error = ''
  try {
    if (current.kind === 'create-plan') {
      // 在当前上下文里创建：文件夹详情中建进该文件夹，否则建在根目录。
      const { entry } = await props.client.createPlanLibraryFile(activeProjectId.value, name, openFolder.value, createType.value, '')
      await reload()
      closeDialog()
      openEntry(entry)
      return
    }
    if (current.kind === 'create-folder') {
      // 建在当前这一层里；库根就是「方案/」本身。
      const path = openFolder.value ? `${openFolder.value}/${name}` : name
      await props.client.createPlanLibraryFolder(activeProjectId.value, path)
      // 新文件夹建在当前层：切换回文件夹页，让这次操作当场看得见。
      activeTab.value = 'folders'
      await reload()
      closeDialog()
      return
    }
    if (current.kind === 'rename' && current.target) {
      const { entry } = await props.client.renamePlanLibraryFile(activeProjectId.value, current.target.path, name)
      if (selected.value?.path === current.target.path || selected.value?.path === entry.path) selected.value = entry
      await reload()
      closeDialog()
      return
    }
  } catch (cause) {
    if (dialog.value) dialog.value.error = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (dialog.value) dialog.value.busy = false
  }
}

/* ---- 右键菜单 ---- */
function entryMenuItems(entry: PlanLibraryEntry): ContextMenuEntry[] {
  const moveChildren = [
    { id: 'move-root', get label() { return t("库根") }, disabled: !entry.folder, action: () => void moveEntry(entry, '') },
    ...folders.value.map(folder => ({
      id: `move-${folder.path}`,
      // 按层级缩进，嵌套时看得出目标在哪儿。
      label: `${'　'.repeat(folder.dir.split('/').length - 1)}${folder.name}`,
      disabled: entry.folder === folder.dir,
      action: () => void moveEntry(entry, folder.dir),
    })),
  ]
  return [
    {
      id: 'start',
      get label() { return t("开工") },
      disabled: entry.status !== 'ready',
      action: () => emit('start-plan', entry),
    },
    {
      id: 'discuss',
      get label() { return t("与 Agent 讨论") },
      action: () => emit('plan-action', { entry, action: 'discuss' }),
    },
    {
      id: 'review',
      get label() { return t("审查方案") },
      action: () => emit('plan-action', { entry, action: 'review' }),
    },
    {
      id: 'check',
      get label() { return t("检查落实情况") },
      action: () => emit('plan-action', { entry, action: 'check' }),
    },
    { id: 'edit', get label() { return t("编辑") }, action: () => void openEditor(entry) },
    {
      id: 'copy-path',
      get label() { return t("复制路径") },
      action: () => void navigator.clipboard?.writeText(entry.path).catch(() => undefined),
    },
    { type: 'separator' as const, id: 'sep-favorite' },
    {
      id: 'favorite',
      label: entry.favorite ? t("从收藏移除") : t("添加到收藏"),
      action: () => void toggleFavorite(entry),
    },
    {
      id: 'move',
      type: 'submenu',
      get label() { return t("添加到文件夹") },
      disabled: folders.value.length === 0,
      children: moveChildren,
    },
    { type: 'separator' as const, id: 'sep-danger' },
    { id: 'rename', get label() { return t("重命名") }, action: () => openDialog('rename', entry) },
    { id: 'delete', get label() { return t("删除") }, destructive: true, action: () => { pendingDelete.value = entry } },
  ]
}

async function moveEntry(entry: PlanLibraryEntry, folder: string): Promise<void> {
  if (!activeProjectId.value) return
  error.value = ''
  try {
    const { entry: updated } = await props.client.movePlanLibraryFile(activeProjectId.value, entry.path, folder)
    entries.value = entries.value.map(item => item.path === entry.path ? updated : item)
    await reload()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

function openEntryMenu(event: MouseEvent, entry: PlanLibraryEntry): void {
  openContextMenu({
    event,
    items: entryMenuItems(entry),
    ownerId: `library-entry:${entry.path}`,
    ariaLabel: t("{0} 的操作", { 0: displayTitle(entry) }),
    panelAttributes: { 'data-library-menu': entry.path },
  })
}

function openFolderMenu(event: MouseEvent, folder: CorePlanLibraryFolder): void {
  openContextMenu({
    event,
    items: [
      { id: 'open', get label() { return t("打开文件夹") }, action: () => goToFolder(folder.dir) },
      {
        id: 'new-subfolder',
        get label() { return t("在里面新建文件夹") },
        action: () => { goToFolder(folder.dir); openDialog('create-folder') },
      },
      { type: 'separator' as const, id: 'sep' },
      {
        id: 'delete-folder',
        get label() { return t("删除文件夹") },
        destructive: true,
        disabled: !isFolderEmpty(folder),
        action: () => void removeFolder(folder),
      },
    ],
    ownerId: `library-folder:${folder.path}`,
    ariaLabel: t("{0} 的操作", { 0: folder.name }),
    panelAttributes: { 'data-library-folder-menu': folder.path },
  })
}

async function removeFolder(folder: CorePlanLibraryFolder): Promise<void> {
  if (!activeProjectId.value) return
  error.value = ''
  try {
    await props.client.deletePlanLibraryFolder(activeProjectId.value, folder.path)
    if (openFolder.value === folder.dir) openFolder.value = folder.parent
    await reload()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

/* ---- 返回层级 ---- */
function handleBack(): boolean {
  if (mode.value === 'editor') {
    requestCloseEditor()
    return true
  }
  if (mode.value === 'reader') {
    mode.value = 'listing'
    if (readerFrom.value !== 'folder') openFolder.value = ''
    clearSelection()
    return true
  }
  if (openFolder.value) {
    // 逐层退回：先回上一层，最外层再退才是退出资料库。
    openFolder.value = openFolder.value.includes('/')
      ? openFolder.value.slice(0, openFolder.value.lastIndexOf('/'))
      : ''
    return true
  }
  if (activeProjectId.value && projectOptions.value.length) {
    // 从项目里的方案退回项目清单：库是全局的，项目只是位置。
    activeProjectId.value = ''
    return true
  }
  return false
}
function onBackClick(): void {
  if (!handleBack()) emit('back')
}
// user:“内置文本编辑器”+(通用分屏关闭前可保存或保留方案草稿)。
defineExpose({ handleBack, isEditing: () => mode.value === 'editor', hasUnsavedChanges: () => dirty.value || saving.value, savePendingChanges: async () => { if (saving.value) return false; await saveEditor(); return !dirty.value }, discardPendingChanges: leaveEditor })

/* ---- 顶部条标题随子页变化 ---- */
const heading = computed(() => {
  const root = rootLabel.value
  if (atProjectLevel.value) {
    return { title: root, subtitle: t("所有项目的方案都在这里 — 选一个项目进去看。") }
  }
  const project = projectOptions.value.length ? `${activeProjectName.value} › ` : ''
  if (mode.value === 'editor' && selected.value) {
    return { title: `${root} › ${project}${t("编辑")} ${truncateTitle(displayTitle(selected.value))}`, subtitle: '' }
  }
  if (mode.value === 'reader' && selected.value) {
    return { title: `${root} › ${project}${truncateTitle(displayTitle(selected.value))}`, subtitle: '' }
  }
  if (openFolder.value) {
    return { title: `${root} › ${project}${folderTrail.value.map(step => step.name).join(' › ')}`, subtitle: '' }
  }
  return { title: `${root} › ${activeProjectName.value}`, subtitle: t("「{0}」文件夹里的方案 — 点开读全文，就绪后开工。", { 0: dirName }) }
})
watch(heading, (value) => emit('heading', { ...value }), { immediate: true })

/* ---- Esc：先关掉最上面那一层，都不在了才退出整版 ---- */
function onKeydown(event: KeyboardEvent): void {
  if (!splitKeyboardActive()) return
  if (event.key !== 'Escape') return
  if (pendingDiscard.value) { pendingDiscard.value = false; return }
  if (pendingDelete.value) { pendingDelete.value = null; return }
  if (dialog.value) { closeDialog(); return }
  onBackClick()
}

watch(
  () => activeProjectId.value,
  () => {
    mode.value = 'listing'
    openFolder.value = ''
    clearSelection()
    entries.value = []
    folders.value = []
    void reload()
  },
)

watch(
  () => props.refreshSignal,
  () => {
    void reload()
  },
)

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  void reload()
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})

</script>

<!-- 版面样式（工具栏 / 网格 / 阅读 / 编辑 / 对话框）见 styles/library-surface.css：
     资料库与记忆共用同一套配方，由根元素上的 .library-surface 承载。 -->

