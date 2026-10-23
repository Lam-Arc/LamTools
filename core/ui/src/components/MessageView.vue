<template>
  <!-- inheritAttrs: false — 模板根节点是 div + Teleport 双根，自动继承会把 class/attrs 丢掉；
       显式把 $attrs 绑到消息根节点，保证 class（如 sub-line-chat）能落到 DOM 上 -->
  <div ref="rootEl" class="message-view" v-bind="$attrs" @contextmenu="onContextMenu">
      <!-- Per-message override: product provides full rendering -->
      <slot
        v-if="$slots['message-product']"
        name="message-product"
        :message="msg"
      />

      <!-- 机器写入的子系统事件（成员完成唤醒）：安静的系统行，不是用户气泡。 -->
      <CoreSystemEventRow
        v-else-if="systemEvent(msg)"
        :event="(systemEvent(msg) as CoreSystemEvent)"
      />

      <!-- User message -->
      <div v-else-if="msg.role === 'user'" class="user-row">
        <div class="user-stack" :class="{ 'user-stack--editing': editingMessageId === msg.id }">
          <div v-if="editingMessageId === msg.id" class="user-bubble user-bubble--editing">
            <AutoTextarea
              ref="editInputRef"
              v-model="editDraft"
              class="user-edit-input"
              :min-rows="2"
              :max-rows="6"
              :aria-label="t('编辑消息')"
              @keydown.ctrl.enter.prevent="confirmEditMessage(msg)"
              @keydown.meta.enter.prevent="confirmEditMessage(msg)"
              @keydown.esc.prevent="cancelEditMessage"
            />
            <div class="user-edit-actions">
              <button
                type="button"
                class="user-edit-button user-edit-button--primary"
                data-user-edit-confirm
                @click="confirmEditMessage(msg)"
              >{{ t("发送") }}</button>
              <button
                type="button"
                class="user-edit-button"
                data-user-edit-cancel
                @click="cancelEditMessage"
              >{{ t("取消") }}</button>
            </div>
          </div>
          <template v-else>
            <div class="user-bubble" data-context-selection-scope>
              {{ msg.content }}
            </div>
          </template>
          <MessageAttachmentDeck
            v-if="messageAttachments(msg).length"
            :attachments="messageAttachments(msg)"
            :transport="transport"
            :project-id="projectId"
            :work-root="workRoot"
            side="right"
            :aria-label="t('消息附件')"
          />
          <!-- Hover actions: copy / edit / fork / roll back (hidden while editing
               this message). Only the last context-compaction boundary is
               excluded: those turns no longer have their original text. -->
          <div
            v-if="messageActions && editingMessageId !== msg.id && userActionable(msg)"
            class="user-actions"
            data-user-actions
          >
            <button
              type="button"
              class="assistant-action"
              :class="{ 'assistant-action--copied': copiedActionId === msg.id }"
              :title="copiedActionId === msg.id ? t('已复制') : t('复制消息')"
              :aria-label="copiedActionId === msg.id ? t('已复制') : t('复制消息')"
              data-user-copy
              @click="copyAssistantMessage(msg)"
            >
              <Copy v-if="copiedActionId !== msg.id" :size="15" :stroke-width="1.8" aria-hidden="true" />
              <Check v-else :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
            <template v-if="!isActionLocked(msg)">
              <button
                type="button"
                class="assistant-action"
                :title="t('编辑消息')"
                :aria-label="t('编辑消息')"
                data-user-edit
                @click="startEditMessage(msg)"
              >
                <Pencil :size="15" :stroke-width="1.8" aria-hidden="true" />
              </button>
              <button
                type="button"
                class="assistant-action"
                :title="t('从此处另开会话')"
                :aria-label="t('从此处另开会话')"
                data-user-fork
                @click="emit('fork-message', userActionPayload(msg))"
              >
                <GitFork :size="15" :stroke-width="1.8" aria-hidden="true" />
              </button>
              <button
                type="button"
                class="assistant-action"
                :title="t('删除此消息及之后内容')"
                :aria-label="t('删除此消息及之后内容')"
                data-user-rollback
                @click="emit('rollback-message', userActionPayload(msg))"
              >
                <Undo2 :size="15" :stroke-width="1.8" aria-hidden="true" />
              </button>
            </template>
          </div>
        </div>
      </div>

      <!-- System message (lifecycle, status, errors) -->
      <div v-else-if="msg.role === 'system'" class="system-row">
        <div class="system-bubble" :class="systemBubbleClass(msg)" data-context-selection-scope>
          <span class="system-icon">
            <component :is="systemIcon(msg)" :size="14" :stroke-width="1.8" aria-hidden="true" />
          </span>
          <span class="system-text">{{ msg.content }}</span>
        </div>
      </div>

      <!-- Assistant message: answer stream + process stream -->
      <div v-else class="assistant-row">
        <div
          class="assistant-message"
          data-context-selection-scope
          :class="{ 'assistant-message--live': isLiveMessage(msg), 'assistant-message--complete': !isLiveMessage(msg) }"
        >
          <div class="assistant-meta">
            <span class="assistant-label">{{ assistantLabel }}</span>
            <span
              v-if="assistantTimestamp"
              class="assistant-timestamp"
              :title="assistantTimestamp.expanded"
              :aria-label="t('时间 {0}', { 0: assistantTimestamp.expanded })"
              data-message-timestamp
            >
              <span class="assistant-timestamp__compact">{{ assistantTimestamp.compact }}</span>
              <span class="assistant-timestamp__expanded" aria-hidden="true">{{ assistantTimestamp.expanded }}</span>
            </span>
            <span
              v-if="isLiveMessage(msg) && !isInitialWaitingMessage(msg) && isCompactionOnlyMessage(msg)"
              class="assistant-live-state"
            >
              <span class="stream-spinner" />
              {{ liveStatusText(msg) }}
            </span>
            <button
              v-if="(isLiveMessage(msg) || processSummary(msg).count > 0) && !isCompactionOnlyMessage(msg)"
              type="button"
              class="process-summary"
              @click="emit('toggle-process', msg.id)"
            >
              <span v-if="isLiveMessage(msg) && !isInitialWaitingMessage(msg)" class="process-summary-state">
                <span class="stream-spinner" />
                <span>{{ liveStatusText(msg) }}</span>
              </span>
              <span v-if="isLiveMessage(msg) && liveDetailText(msg)" class="process-summary-detail">{{ liveDetailText(msg) }}</span>
              <span class="process-summary-icon" :class="processBarStatus(msg)" />
              <span v-if="!isLiveMessage(msg)" class="process-summary-text">{{ processSummary(msg).text }}</span>
            </button>
          </div>

          <div
            v-if="mobileProgressVisible"
            class="mobile-turn-progress"
            :class="`mobile-turn-progress--${mobileProgress?.status}`"
            role="status"
            aria-live="polite"
            :aria-label="t('执行进度：{0}', { 0: mobileProgress?.label })"
          >
            <span class="mobile-turn-progress__label">{{ mobileProgress?.label }}</span>
            <span class="mobile-turn-progress__track" aria-hidden="true">
              <span class="mobile-turn-progress__fill" />
            </span>
          </div>

          <div v-if="mobileRuntimeWarnings.length" class="mobile-runtime-warning" role="status">
            <span class="mobile-runtime-warning__label">{{ t("扩展提示") }}</span>
            <span v-for="warning in mobileRuntimeWarnings" :key="warning">{{ warning }}</span>
          </div>

          <div v-if="terminalErrorText(msg)" class="assistant-terminal-error" role="alert">
            <span class="assistant-terminal-error__label">{{ t("运行失败") }}</span>
            <span>{{ terminalErrorText(msg) }}</span>
          </div>

          <div v-if="isInitialWaitingMessage(msg)" class="initial-waiting-indicator" :aria-label="t('请求中')">
            <span v-if="shouldShowShallowThinkingPending(msg)" class="shallow-thinking-pending" role="status" aria-live="polite">
              shallow thinking<span class="shallow-thinking-dots" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span>
            </span>
            <span v-else class="stream-spinner" />
          </div>

          <!-- One process renderer for both live and completed messages. The
               projection has already removed the unique final answer part. -->
          <template v-if="processParts(msg).length > 0 || shouldShowShallowThinkingPending(msg)">
            <div
              v-if="shouldShowShallowThinkingPending(msg)"
              class="process-step process-step--reasoning shallow-thinking-pending-row"
            >
              <div class="reasoning-body reasoning-body--pending">
                <span class="shallow-thinking-pending" role="status" aria-live="polite">
                  shallow thinking<span class="shallow-thinking-dots" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span>
                </span>
              </div>
            </div>

            <Transition :css="false" @enter="panelEnter" @leave="panelLeave">
            <div
                  v-if="isProcessExpanded(msg) || isLiveMessage(msg)"
                  class="process-stream"
                  :class="{ 'process-stream--live': isLiveMessage(msg), 'process-stream--complete': !isLiveMessage(msg) }"
                >
              <template
                v-for="group in compactGroups(groupParts(processParts(msg)))"
                :key="group.kind === 'process-group' ? processGroupId(group) : group.part.id"
              >
                <template v-if="group.kind === 'process-group'">
                  <div
                    class="process-group"
                    @mouseenter="cancelGroupAutoCollapse(processGroupId(group))"
                    @mouseleave="scheduleGroupAutoCollapse(processGroupId(group))"
                  >
                    <button
                      type="button"
                      class="process-group-summary process-card-header"
                      :class="{ 'process-group-summary--running': groupHasRunningPart(group) }"
                      :aria-expanded="isGroupExpanded(processGroupId(group))"
                      :aria-label="group.summary"
                      @click="toggleGroupExpand(processGroupId(group))"
                    >
                      <component
                        :is="processIcon(processGroupCurrentPart(group))"
                        class="process-card-state-icon"
                        :class="processIconStateClass(processGroupCurrentPart(group))"
                        :size="15"
                        :stroke-width="1.8"
                        aria-hidden="true"
                      />
                      <Transition name="process-caption" mode="out-in">
                        <span
                          :key="processTitleSnapshot(processGroupCurrentPart(group))"
                          v-beam="groupHasRunningPart(group)"
                          class="process-group-text process-card-preview"
                        >{{ processTitleSnapshot(processGroupCurrentPart(group)) }}</span>
                      </Transition>
                      <span
                        v-if="!isGroupExpanded(processGroupId(group))"
                        class="process-group-count"
                        aria-hidden="true"
                      >{{ group.parts.length }} {{ t("步") }}</span>
                    </button>
                    <Transition :css="false" @enter="panelEnter" @leave="panelLeave">
                    <div v-if="isGroupExpanded(processGroupId(group))" class="process-group-body">
                      <div
                        v-for="part in group.parts"
                        :key="part.id"
                        v-memo="partMemo(part, isLiveMessage(msg))"
                        class="part-wrap"
                        :data-part-id="part.id"
                      >
                        <div
                          v-if="part.partType === 'reasoning'"
                          :class="['process-step', 'process-step--reasoning', 'process-step--' + part.status]"
                          @mouseenter="cancelPartAutoCollapse(part.id)"
                          @mouseleave="schedulePartAutoCollapse(part.id)"
                        >
                          <button
                            type="button"
                            class="reasoning-toggle process-card-header"
                            :aria-expanded="isPartExpanded(part, isLiveMessage(msg))"
                            :aria-label="processAccessibleLabel(part)"
                            @click="togglePartExpand(part, isLiveMessage(msg))"
                          >
                            <component :is="processIcon(part)" class="process-card-state-icon" :class="processIconStateClass(part)" :size="15" :stroke-width="1.8" aria-hidden="true" />
                            <Transition name="process-caption" mode="out-in">
                              <span :key="processTitleSnapshot(part)" v-beam="part.status === 'running'" class="process-step-title process-card-preview">{{ processTitleSnapshot(part) }}</span>
                            </Transition>
                            <span v-if="reasoningDuration(part)" class="reasoning-duration">{{ reasoningDuration(part) }}</span>
                          </button>
                          <Transition :css="false" @enter="panelEnter" @leave="panelLeave">
                          <div
                            v-if="isPartExpanded(part, isLiveMessage(msg))"
                            class="reasoning-body"
                            :class="processCardBodyStateClass(part, isLiveMessage(msg))"
                            @click="promotePartCard(part.id, $event)"
                          >
                            <slot name="reasoning-content" :content="part.content ?? ''" :live="isLiveMessage(msg)">
                              <MarkdownRenderer class="process-step-detail" :content="part.content ?? ''" />
                            </slot>
                          </div>
                          </Transition>
                        </div>
                        <div
                          v-else-if="(part.partType === 'tool_call' || part.partType === 'tool_result') && !isControlTool(part)"
                          class="process-step process-step--tool"
                          :class="['process-step--' + part.status, { 'process-step--sub-agent': isSubAgentToolRow(part) }]"
                          @mouseenter="cancelPartAutoCollapse(part.id)"
                          @mouseleave="schedulePartAutoCollapse(part.id)"
                        >
                          <button
                            type="button"
                            class="tool-card-header process-card-header"
                            :class="[{ 'has-detail': hasToolDisplay(part), 'has-flag': Boolean(toolRowFlagTone(part)), 'process-tool-row': !isCommandTool(part), 'tool-card-header--command': isCommandTool(part) }, toolColorClass(part)]"
                            :aria-expanded="isSubAgentToolRow(part) ? undefined : (hasToolDisplay(part) ? shouldShowToolBody(part, isLiveMessage(msg)) : undefined)"
                            :aria-label="processAccessibleLabel(part)"
                            :disabled="subAgentRowsInert && isSubAgentToolRow(part)"
                            @click="activateToolRow(part, isLiveMessage(msg))"
                          >
                            <component :is="processIcon(part)" class="process-card-state-icon" :class="processIconStateClass(part)" :size="15" :stroke-width="1.8" aria-hidden="true" />
                            <Transition name="process-caption" mode="out-in">
                              <span :key="processTitleSnapshot(part)" v-beam="part.status === 'running'" class="process-step-title tool-row-summary process-card-preview">{{ processTitleSnapshot(part) }}</span>
                            </Transition>
                            <span
                              v-if="toolRowFlagTone(part)"
                              class="process-tool-flag"
                              :class="`process-tool-flag--${toolRowFlagTone(part)}`"
                            ><template v-if="toolRowFlagTone(part) === 'stat'"><span class="process-tool-flag-add">+{{ toolRowFlagStat(part).added }}</span><span class="process-tool-flag-del">−{{ toolRowFlagStat(part).removed }}</span></template><template v-else>{{ toolRowFlagText(part) }}</template></span>
                          </button>
                          <Transition :css="false" @enter="panelEnter" @leave="panelLeave">
                          <div
                            v-if="shouldShowToolBody(part, isLiveMessage(msg))"
                            class="tool-card-body"
                            :class="[{ 'tool-card-body--row': !isCommandTool(part) }, processCardBodyStateClass(part, isLiveMessage(msg))]"
                            @click="promotePartCard(part.id, $event)"
                          >
                            <pre v-if="displayToolError(part)" class="tool-output tool-output--error">{{ displayToolError(part) }}</pre>
                            <!-- 内容搜索命中清单：`路径:行号: 内容` 逐行成单，替代整段原始文本 -->
                            <div v-else-if="displayToolResult(part) && isContentSearchTool(part) && contentSearchHits(part).length" class="search-hit-list" :class="{ 'search-hit-list--wrap': isToolWrapEnabled(part.id) }">
                              <div v-for="(hit, hitIndex) in contentSearchHits(part)" :key="hitIndex" class="search-hit-row">
                                <span class="search-hit-loc"><span class="search-hit-file" :title="hit.path">{{ hit.path }}</span><span class="search-hit-line">:{{ hit.line }}</span></span>
                                <span class="search-hit-text">{{ hit.text }}</span>
                              </div>
                              <div v-for="note in contentSearchNotes(part)" :key="note" class="search-hit-note">{{ note }}</div>
                            </div>
                            <!-- 网页获取：标题与正文摘要先行，原始全文收进可展开区 -->
                            <div v-else-if="displayToolResult(part) && isWebFetchTool(part)" class="web-fetch-card">
                              <div v-if="webFetchTitle(part)" class="web-fetch-title">{{ webFetchTitle(part) }}</div>
                              <p class="web-fetch-summary">{{ webFetchSummary(part) || t("未提取到正文摘要。") }}</p>
                              <details class="web-fetch-more">
                                <summary class="web-fetch-more-toggle">{{ t("查看全文") }}</summary>
                                <pre class="web-fetch-raw" :class="{ 'web-fetch-raw--wrap': isToolWrapEnabled(part.id) }" @click="toggleToolWrap(part.id)">{{ displayToolResult(part) }}</pre>
                              </details>
                            </div>
                            <div v-else-if="displayToolResult(part) && isFileTool(part)" class="diff-block" :class="[fileDiffClass(part), { 'diff-block--wrap': isToolWrapEnabled(part.id) }]">
                              <div class="diff-header">
                                <span class="diff-file">{{ diffHeaderText(part) }}</span>
                                <button type="button" class="wrap-toggle" @click.stop="toggleToolWrap(part.id)">{{ isToolWrapEnabled(part.id) ? 'wrap' : 'scroll' }}</button>
                              </div>
                              <div class="diff-lines">
                                <div v-for="(line, li) in diffDisplayLines(part)" :key="li" class="diff-line" :class="diffLineClass(line, part)">
                                  <span class="diff-line-num">{{ diffLineGutter(line, li, part) }}</span>
                                  <span class="diff-line-content">{{ diffLineContent(line, part) }}</span>
                                </div>
                              </div>
                            </div>
                            <div v-else-if="testArtifact(part)" class="test-result-card" :class="testResultClass(part)">
                              <div class="test-result-head">
                                <span class="test-result-state">{{ testResultTitle(part) }}</span>
                                <span class="test-result-command">{{ testResultCommand(part) }}</span>
                              </div>
                              <div class="test-result-meta">
                                <span v-for="item in testResultMeta(part)" :key="item">{{ item }}</span>
                              </div>
                              <pre v-if="testResultOutput(part)" class="test-result-output">{{ testResultOutput(part) }}</pre>
                            </div>
                            <div v-else-if="displayToolInputPreview(part)" class="tool-output tool-input-preview">
                              <div class="tool-output-meta">
                                <span>{{ toolInputPreviewMeta(part) }}</span>
                              </div>
                              <pre class="tool-output-content" :class="{ 'tool-output-content--wrap': isToolWrapEnabled(part.id) }" @click="toggleToolWrap(part.id)">{{ displayToolInputPreview(part) }}</pre>
                            </div>
                            <div v-else-if="displayToolResult(part) && isCommandTool(part)" class="command-output">
                              <div class="command-terminal-chrome" aria-hidden="true">
                                <span class="command-terminal-light command-terminal-light--close" />
                                <span class="command-terminal-light command-terminal-light--minimize" />
                                <span class="command-terminal-light command-terminal-light--maximize" />
                                <span class="command-terminal-title">run command</span>
                              </div>
                              <div class="command-terminal-body">
                                <strong class="command-output-command">$ {{ commandDisplayText(part) }}</strong>
                                <pre class="command-output-result">{{ commandOutputText(part) }}</pre>
                              </div>
                            </div>
                            <div v-else-if="displayToolResult(part)" class="tool-output">
                              <div v-if="toolMetaItems(part).length > 0" class="tool-output-meta">
                                <span v-for="item in toolMetaItems(part)" :key="item">{{ item }}</span>
                              </div>
                              <pre class="tool-output-content">{{ toolOutputContent(part) }}</pre>
                            </div>
                            <div v-if="imageArtifacts(part).length" class="tool-image-row">
                              <figure
                                v-for="artifact in imageArtifacts(part)"
                                :key="artifactKey(artifact)"
                                class="tool-image-card"
                                :class="{ 'tool-image-card--placeholder': !imageSrc(artifact) }"
                                :ref="(element) => registerImageCard(element, artifact)"
                                @click="openImagePreview(artifact)"
                              >
                                <img v-if="imageSrc(artifact)" :src="imageSrc(artifact)" :alt="imageAlt(artifact)" loading="lazy" />
                                <div v-else class="tool-image-placeholder">
                                  <ImageIcon :size="18" :stroke-width="1.7" aria-hidden="true" />
                                  <span class="tool-image-placeholder__name">{{ imageAlt(artifact) }}</span>
                                  <span v-if="artifactSizeLabel(artifact)" class="tool-image-placeholder__size">{{ artifactSizeLabel(artifact) }}</span>
                                  <button
                                    v-if="artifactLoadFailedFor(artifact)"
                                    type="button"
                                    class="tool-image-placeholder__retry"
                                    @click.stop="retryArtifactSource(artifact)"
                                  >{{ t("图片暂时取不到，重试") }}</button>
                                </div>
                              </figure>
                            </div>
                            <!-- 兜底明细只在既无错误块、也无任何结果块（命中清单/网页卡/文件 diff/
                                 测试卡/输入预览/终端窗/通用结果，凡有结果文本必有其一）时才补位；
                                 图片行另起一条 v-if 链，这条曾与它们并存，同一段内容被画两遍。 -->
                            <pre v-else-if="!isContentSearchTool(part) && !isWebFetchTool(part) && !displayToolInputPreview(part) && !displayToolError(part) && !displayToolResult(part) && readableProcessDetail(part)" class="tool-output">{{ readableProcessDetail(part) }}</pre>
                          </div>
                          </Transition>
                        </div>
                        <div
                          v-else-if="isModelRetryPart(part)"
                          class="model-retry-bar"
                          role="status"
                          aria-live="polite"
                          :title="modelRetryDetail(part)"
                        >
                          <span class="model-retry-bar__label">{{ t("重试中") }} {{ modelRetryCounts(part).attempt }}/{{ modelRetryCounts(part).maxRetries }}</span>
                          <div class="model-retry-bar__track" aria-hidden="true">
                            <div
                              v-for="i in modelRetryCounts(part).maxRetries"
                              :key="i"
                              class="model-retry-bar__segment"
                              :class="{ 'model-retry-bar__segment--filled': i <= modelRetryCounts(part).attempt }"
                            />
                          </div>
                          <span v-if="modelRetryDetail(part)" class="model-retry-bar__detail">{{ modelRetryDetail(part) }}</span>
                        </div>
                      </div>
                    </div>
                    </Transition>
                  </div>
                </template>

                <template v-else-if="group.kind === 'process' && group.part">
                  <div
                    v-if="group.part.partType === 'reasoning'"
                    :class="['process-step', 'process-step--reasoning', 'process-step--' + group.part.status]"
                    @mouseenter="cancelPartAutoCollapse(group.part.id)"
                    @mouseleave="schedulePartAutoCollapse(group.part.id)"
                  >
                    <button
                      type="button"
                      class="reasoning-toggle process-card-header"
                      :aria-expanded="isPartExpanded(group.part, isLiveMessage(msg))"
                      :aria-label="processAccessibleLabel(group.part)"
                      @click="togglePartExpand(group.part, isLiveMessage(msg))"
                    >
                      <component :is="processIcon(group.part)" class="process-card-state-icon" :class="processIconStateClass(group.part)" :size="15" :stroke-width="1.8" aria-hidden="true" />
                      <Transition name="process-caption" mode="out-in">
                        <span :key="processTitleSnapshot(group.part)" v-beam="group.part.status === 'running'" class="process-step-title process-card-preview">{{ processTitleSnapshot(group.part) }}</span>
                      </Transition>
                      <span v-if="reasoningDuration(group.part)" class="reasoning-duration">{{ reasoningDuration(group.part) }}</span>
                    </button>
                    <Transition :css="false" @enter="panelEnter" @leave="panelLeave">
                    <div
                      v-if="isPartExpanded(group.part, isLiveMessage(msg))"
                      class="reasoning-body"
                      :class="processCardBodyStateClass(group.part, isLiveMessage(msg))"
                      @click="promotePartCard(group.part.id, $event)"
                    >
                      <slot name="reasoning-content" :content="group.part.content ?? ''" :live="isLiveMessage(msg)">
                        <MarkdownRenderer class="process-step-detail" :content="group.part.content ?? ''" />
                      </slot>
                    </div>
                    </Transition>
                  </div>

                  <div
                    v-else-if="(group.part.partType === 'tool_call' || group.part.partType === 'tool_result') && !isControlTool(group.part)"
                    class="process-step process-step--tool"
                    :class="['process-step--' + group.part.status, { 'process-step--sub-agent': isSubAgentToolRow(group.part) }]"
                    @mouseenter="cancelPartAutoCollapse(group.part.id)"
                    @mouseleave="schedulePartAutoCollapse(group.part.id)"
                  >
                    <button
                      type="button"
                      class="tool-card-header process-card-header"
                      :class="[{ 'has-detail': hasToolDisplay(group.part), 'has-flag': Boolean(toolRowFlagTone(group.part)), 'process-tool-row': !isCommandTool(group.part), 'tool-card-header--command': isCommandTool(group.part) }, toolColorClass(group.part)]"
                      :aria-expanded="isSubAgentToolRow(group.part) ? undefined : (!isCommandTool(group.part) && hasToolDisplay(group.part) ? shouldShowToolBody(group.part, isLiveMessage(msg)) : undefined)"
                      :aria-label="processAccessibleLabel(group.part)"
                      :disabled="subAgentRowsInert && isSubAgentToolRow(group.part)"
                      @click="activateToolRow(group.part, isLiveMessage(msg))"
                    >
                      <component :is="processIcon(group.part)" class="process-card-state-icon" :class="processIconStateClass(group.part)" :size="15" :stroke-width="1.8" aria-hidden="true" />
                      <Transition name="process-caption" mode="out-in">
                        <span :key="processTitleSnapshot(group.part)" v-beam="group.part.status === 'running'" class="process-step-title tool-row-summary process-card-preview">{{ processTitleSnapshot(group.part) }}</span>
                      </Transition>
                      <span
                        v-if="toolRowFlagTone(group.part)"
                        class="process-tool-flag"
                        :class="`process-tool-flag--${toolRowFlagTone(group.part)}`"
                      ><template v-if="toolRowFlagTone(group.part) === 'stat'"><span class="process-tool-flag-add">+{{ toolRowFlagStat(group.part).added }}</span><span class="process-tool-flag-del">−{{ toolRowFlagStat(group.part).removed }}</span></template><template v-else>{{ toolRowFlagText(group.part) }}</template></span>
                    </button>
                    <span v-if="!displayToolInputPreview(group.part) && !hasToolDisplay(group.part) && !group.part.toolArgs && readableProcessDetail(group.part)" class="process-step-detail">{{ readableProcessDetail(group.part) }}</span>
                    <Transition :css="false" @enter="panelEnter" @leave="panelLeave">
                    <div
                      v-if="shouldShowToolBody(group.part, isLiveMessage(msg))"
                      class="tool-card-body"
                      :class="[{ 'tool-card-body--row': !isCommandTool(group.part) }, processCardBodyStateClass(group.part, isLiveMessage(msg))]"
                      @click="promotePartCard(group.part.id, $event)"
                    >
                      <pre v-if="displayToolError(group.part)" class="tool-output tool-output--error">{{ displayToolError(group.part) }}</pre>
                      <!-- 内容搜索命中清单：`路径:行号: 内容` 逐行成单，替代整段原始文本 -->
                      <div v-else-if="displayToolResult(group.part) && isContentSearchTool(group.part) && contentSearchHits(group.part).length" class="search-hit-list" :class="{ 'search-hit-list--wrap': isToolWrapEnabled(group.part.id) }">
                        <div v-for="(hit, hitIndex) in contentSearchHits(group.part)" :key="hitIndex" class="search-hit-row">
                          <span class="search-hit-loc"><span class="search-hit-file" :title="hit.path">{{ hit.path }}</span><span class="search-hit-line">:{{ hit.line }}</span></span>
                          <span class="search-hit-text">{{ hit.text }}</span>
                        </div>
                        <div v-for="note in contentSearchNotes(group.part)" :key="note" class="search-hit-note">{{ note }}</div>
                      </div>
                      <!-- 网页获取：标题与正文摘要先行，原始全文收进可展开区 -->
                      <div v-else-if="displayToolResult(group.part) && isWebFetchTool(group.part)" class="web-fetch-card">
                        <div v-if="webFetchTitle(group.part)" class="web-fetch-title">{{ webFetchTitle(group.part) }}</div>
                        <p class="web-fetch-summary">{{ webFetchSummary(group.part) || t("未提取到正文摘要。") }}</p>
                        <details class="web-fetch-more">
                          <summary class="web-fetch-more-toggle">{{ t("查看全文") }}</summary>
                          <pre class="web-fetch-raw" :class="{ 'web-fetch-raw--wrap': isToolWrapEnabled(group.part.id) }" @click="toggleToolWrap(group.part.id)">{{ displayToolResult(group.part) }}</pre>
                        </details>
                      </div>
                      <!-- File tools: diff-style block with line numbers -->
                      <div v-else-if="displayToolResult(group.part) && isFileTool(group.part)" class="diff-block" :class="[fileDiffClass(group.part), { 'diff-block--wrap': isToolWrapEnabled(group.part.id) }]">
                        <div class="diff-header">
                          <span class="diff-file">{{ diffHeaderText(group.part) }}</span>
                          <button type="button" class="wrap-toggle" @click.stop="toggleToolWrap(group.part.id)">{{ isToolWrapEnabled(group.part.id) ? 'wrap' : 'scroll' }}</button>
                        </div>
                        <div class="diff-lines">
                            <div v-for="(line, li) in diffDisplayLines(group.part)" :key="li" class="diff-line" :class="diffLineClass(line, group.part)">
                              <span class="diff-line-num">{{ diffLineGutter(line, li, group.part) }}</span>
                              <span class="diff-line-content">{{ diffLineContent(line, group.part) }}</span>
                          </div>
                        </div>
                      </div>
                      <div v-else-if="testArtifact(group.part)" class="test-result-card" :class="testResultClass(group.part)">
                        <div class="test-result-head">
                          <span class="test-result-state">{{ testResultTitle(group.part) }}</span>
                          <span class="test-result-command">{{ testResultCommand(group.part) }}</span>
                        </div>
                        <div class="test-result-meta">
                          <span v-for="item in testResultMeta(group.part)" :key="item">{{ item }}</span>
                        </div>
                        <pre v-if="testResultOutput(group.part)" class="test-result-output">{{ testResultOutput(group.part) }}</pre>
                      </div>
                        <div v-else-if="displayToolInputPreview(group.part)" v-auto-follow-scroll="displayToolInputPreview(group.part)" class="tool-output tool-input-preview">
                        <div class="tool-output-meta">
                          <span>{{ toolInputPreviewMeta(group.part) }}</span>
                        </div>
                        <pre class="tool-output-content" :class="{ 'tool-output-content--wrap': isToolWrapEnabled(group.part.id) }" @click="toggleToolWrap(group.part.id)">{{ displayToolInputPreview(group.part) }}</pre>
                      </div>
                      <!-- Non-file tools: plain code block -->
                      <div v-else-if="displayToolResult(group.part) && isCommandTool(group.part)" class="command-output">
                        <div class="command-terminal-chrome" aria-hidden="true">
                          <span class="command-terminal-light command-terminal-light--close" />
                          <span class="command-terminal-light command-terminal-light--minimize" />
                          <span class="command-terminal-light command-terminal-light--maximize" />
                          <span class="command-terminal-title">run command</span>
                        </div>
                        <div class="command-terminal-body">
                          <strong class="command-output-command">$ {{ commandDisplayText(group.part) }}</strong>
                          <pre class="command-output-result">{{ commandOutputText(group.part) }}</pre>
                        </div>
                      </div>
                      <div v-else-if="displayToolResult(group.part) && !isFileTool(group.part)" class="tool-output">
                        <div v-if="toolMetaItems(group.part).length > 0" class="tool-output-meta">
                          <span v-for="item in toolMetaItems(group.part)" :key="item">{{ item }}</span>
                        </div>
                          <pre class="tool-output-content" :class="{ 'tool-output-content--wrap': isToolWrapEnabled(group.part.id) }" @click="toggleToolWrap(group.part.id)">{{ toolOutputContent(group.part) }}</pre>
                      </div>
                      <div v-if="imageArtifacts(group.part).length" class="tool-image-row">
                        <figure
                          v-for="artifact in imageArtifacts(group.part)"
                          :key="artifactKey(artifact)"
                          class="tool-image-card"
                          :class="{ 'tool-image-card--placeholder': !imageSrc(artifact) }"
                          :ref="(element) => registerImageCard(element, artifact)"
                          @click="openImagePreview(artifact)"
                        >
                          <img v-if="imageSrc(artifact)" :src="imageSrc(artifact)" :alt="imageAlt(artifact)" loading="lazy" />
                          <div v-else class="tool-image-placeholder">
                            <ImageIcon :size="18" :stroke-width="1.7" aria-hidden="true" />
                            <span class="tool-image-placeholder__name">{{ imageAlt(artifact) }}</span>
                            <span v-if="artifactSizeLabel(artifact)" class="tool-image-placeholder__size">{{ artifactSizeLabel(artifact) }}</span>
                            <button
                              v-if="artifactLoadFailedFor(artifact)"
                              type="button"
                              class="tool-image-placeholder__retry"
                              @click.stop="retryArtifactSource(artifact)"
                            >{{ t("图片暂时取不到，重试") }}</button>
                          </div>
                        </figure>
                      </div>
                      <!-- 同上：既无错误块也无任何结果块时才补兜底明细。 -->
                      <pre v-else-if="!isContentSearchTool(group.part) && !isWebFetchTool(group.part) && !displayToolInputPreview(group.part) && !displayToolError(group.part) && !displayToolResult(group.part) && readableProcessDetail(group.part)" class="tool-output">{{ readableProcessDetail(group.part) }}</pre>
                    </div>
                    </Transition>
                  </div>

                  <div
                    v-else-if="group.part.partType === 'model_text' && group.part.content"
                  >
                    <MarkdownRenderer
                      class="part-text-content"
                      :content="group.part.content ?? ''"
                      :streaming="isLiveMessage(msg)"
                    />
                  </div>

                  <!-- 运行中插进去的引导指令：形状仍是右侧气泡（一眼认出是自己的
                       话），但住在过程区里，随过程一起展开/收起。还没被模型接手的
                       那一条用虚线 + 呼吸标明"待生效"。 -->
                  <div
                    v-else-if="group.part.partType === 'guidance'"
                    class="process-guidance"
                  >
                    <div class="user-guide-label" data-user-guide-label>{{ t("引导") }}</div>
                    <div
                      class="user-bubble"
                      :class="{ 'user-bubble--pending': isPendingGuidancePart(group.part) }"
                    >{{ group.part.content }}</div>
                  </div>

                  <div v-else-if="group.part.partType === 'error'" class="process-step process-step--error">
                    <button
                      type="button"
                      class="process-inline-toggle"
                      @click="togglePartExpand(group.part, isLiveMessage(msg))"
                    >
                      <span v-if="group.part.status === 'error'" class="process-step-marker process-step-marker--error" />
                      <span class="process-step-title">{{ group.part.label || t("出错") }}</span>
                      <span class="process-step-detail">{{ processDetailPreview(group.part) }}</span>
                    </button>
                    <Transition :css="false" @enter="panelEnter" @leave="panelLeave">
                    <div v-if="isPartExpanded(group.part, isLiveMessage(msg))" class="process-detail-panel process-detail-panel--error">
                      <button type="button" class="process-detail-copy" @click.stop="copyProcessDetail(group.part)">{{ t("复制") }}</button>
                      <pre>{{ fullProcessDetail(group.part) }}</pre>
                    </div>
                    </Transition>
                  </div>

                  <div
                    v-else-if="isModelRetryPart(group.part)"
                    class="model-retry-bar"
                    role="status"
                    aria-live="polite"
                    :title="modelRetryDetail(group.part)"
                  >
                    <span class="model-retry-bar__label">{{ t("重试中") }} {{ modelRetryCounts(group.part).attempt }}/{{ modelRetryCounts(group.part).maxRetries }}</span>
                    <div class="model-retry-bar__track" aria-hidden="true">
                      <div
                        v-for="i in modelRetryCounts(group.part).maxRetries"
                        :key="i"
                        class="model-retry-bar__segment"
                        :class="{ 'model-retry-bar__segment--filled': i <= modelRetryCounts(group.part).attempt }"
                      />
                    </div>
                    <span v-if="modelRetryDetail(group.part)" class="model-retry-bar__detail">{{ modelRetryDetail(group.part) }}</span>
                  </div>

                  <div v-else-if="group.part.partType === 'status'" class="process-step process-step--info" :class="'process-step--' + group.part.status">
                    <button
                      v-if="hasExpandableProcessDetail(group.part)"
                      type="button"
                      class="process-inline-toggle"
                      @click="togglePartExpand(group.part, isLiveMessage(msg))"
                    >
                      <span v-if="group.part.status === 'error'" class="process-step-marker process-step-marker--error" />
                      <span class="process-step-title">{{ group.part.label || t("状态") }}</span>
                      <span class="process-step-detail">{{ processDetailPreview(group.part) }}</span>
                    </button>
                    <template v-else>
                      <span v-if="group.part.status === 'error'" class="process-step-marker process-step-marker--error" />
                      <span class="process-step-title">{{ group.part.label || t("状态") }}</span>
                      <span class="process-step-detail">{{ group.part.detail || group.part.content }}</span>
                    </template>
                    <Transition :css="false" @enter="panelEnter" @leave="panelLeave">
                    <div v-if="hasExpandableProcessDetail(group.part) && isPartExpanded(group.part, isLiveMessage(msg))" class="process-detail-panel">
                      <button type="button" class="process-detail-copy" @click.stop="copyProcessDetail(group.part)">{{ t("复制") }}</button>
                      <pre>{{ fullProcessDetail(group.part) }}</pre>
                    </div>
                    </Transition>
                  </div>

                  <div
                    v-else-if="group.part.partType === 'decision'"
                    class="decision-card"
                    :class="'decision-card--' + group.part.status"
                  >
                    <div class="decision-card-head">
                      <span v-if="group.part.status === 'error'" class="process-step-marker process-step-marker--error" />
                      <CircleHelp v-else class="decision-card-icon" :size="15" :stroke-width="2" aria-hidden="true" />
                      <span class="decision-card-kind">{{ decisionKindLabel(group.part) }}</span>
                      <span v-if="decisionStatusLabel(group.part)" class="decision-card-status">{{ decisionStatusLabel(group.part) }}</span>
                    </div>
                    <p class="decision-card-title">{{ decisionTitle(group.part) }}</p>
                    <p v-if="decisionDetail(group.part)" class="decision-card-detail">{{ decisionDetail(group.part) }}</p>
                    <ol v-if="group.part.status === 'pending' && decisionOptions(group.part).length > 0" class="decision-options">
                      <li v-for="(option, index) in decisionOptions(group.part)" :key="option.id" class="decision-option-group">
                        <span class="decision-option-index" aria-hidden="true">{{ index + 1 }}</span>
                        <button
                          type="button"
                          class="decision-option"
                          :class="{
                            'decision-option--approve': option.id === 'approve',
                            'decision-option--deny': option.id === 'deny',
                          }"
                          @click="emit('decision-select', { partId: group.part.id, option, response: decisionOptionResponse(group.part, option) })"
                        >
                          <span class="decision-option-label">{{ option.label }}</span>
                        </button>
                        <span v-if="option.description" class="decision-option-desc">{{ option.description }}</span>
                      </li>
                    </ol>
                    <details v-if="canGuideDecision(group.part)" class="decision-guide">
                      <summary class="decision-guide-toggle">{{ t("其他处理方式") }}</summary>
                      <div class="decision-guide-fields">
                        <textarea
                          class="decision-guide-input"
                          :data-decision-guide="group.part.id"
                          :value="decisionGuideDraft(group.part)"
                          :placeholder="t('说明希望如何处理…')"
                          rows="1"
                          @input="updateDecisionGuideDraft(group.part, $event)"
                        />
                        <button
                          type="button"
                          class="decision-guide-submit"
                          :disabled="!decisionGuideDraft(group.part).trim()"
                          @click="submitDecisionGuide(group.part)"
                        >{{ t("提交") }}</button>
                      </div>
                    </details>
                  </div>

                      <div
                        v-else-if="isSubLinePart(group.part)"
                        class="sub-line-block"
                        :class="'sub-line--' + group.part.status"
                        :data-part-id="group.part.id"
                      >
                        <div class="sub-line-head">
                          <!-- 子代理那一行只有一件事：点整行打开右侧分屏（过程流在面板里
                               完整可见，行内就地展开是冗余，已按用户口径移除）。 -->
                          <button
                            type="button"
                            class="sub-line-heading"
                            :disabled="subAgentRowsInert"
                            :title="subAgentRowsInert ? agentTitle(group.part) : t('打开 ') + agentTitle(group.part)"
                            @click="openSubAgentPane(group.part)"
                          >
                            <span v-if="group.part.status === 'error'" class="process-step-marker process-step-marker--error" />
                            <span v-beam="group.part.status === 'running'" class="sub-line-title">{{ agentTitle(group.part) }}</span>
                            <span class="sub-line-status">{{ agentStatusLabel(group.part) }}</span>
                          </button>
                        </div>
                        <div v-if="agentDeliveryMeta(group.part).length > 0" class="sub-line-delivery-meta">
                          <span v-for="item in agentDeliveryMeta(group.part)" :key="item">{{ item }}</span>
                        </div>
                      </div>

                  <div
                    v-else-if="isChecklistPart(group.part)"
                    class="checklist-card"
                    :class="'checklist-card--' + group.part.status"
                  >
                    <div class="checklist-card-head">
                      <span v-if="group.part.status === 'error'" class="process-step-marker process-step-marker--error" />
                      <span class="process-step-title">{{ controlTitle(group.part) }}</span>
                    </div>
                    <ol class="checklist-items">
                      <li v-for="item in checklistItems(group.part)" :key="item.id" class="checklist-item" :class="'checklist-item--' + item.status">
                        <span class="checklist-box"><Check v-if="item.checked" :size="10" :stroke-width="2.4" aria-hidden="true" /></span>
                        <span class="checklist-text">{{ item.text }}</span>
                      </li>
                    </ol>
                  </div>

                  <div
                    v-else-if="group.part.partType === 'plan' || group.part.partType === 'todo_update'"
                    class="process-step process-step--info"
                    :class="'process-step--' + group.part.status"
                  >
                    <span v-if="group.part.status === 'error'" class="process-step-marker process-step-marker--error" />
                    <span class="process-step-title">{{ group.part.label || livePartTitle(group.part) }}</span>
                    <span class="process-step-detail">{{ group.part.detail || group.part.content }}</span>
                  </div>

                  <div
                    v-else-if="group.part.partType === 'compaction'"
                    class="compaction-step"
                    :class="'compaction-step--' + compactionStatus(group.part)"
                  >
                    <button
                      type="button"
                      class="compaction-toggle process-card-header"
                      :disabled="!canToggleCompaction(group.part)"
                      :aria-expanded="isCompactionExpanded(group.part)"
                      :aria-controls="'compaction-summary-' + group.part.id"
                      :aria-label="compactionAccessibleLabel(group.part)"
                      @click="canToggleCompaction(group.part) && toggleToolExpand(group.part.id)"
                    >
                      <component
                        :is="processIcon(group.part)"
                        class="process-card-state-icon"
                        :class="compactionIconStateClass(group.part)"
                        :size="15"
                        :stroke-width="1.8"
                        aria-hidden="true"
                      />
                      <Transition name="process-caption" mode="out-in">
                        <span
                          :key="compactionDetail(group.part)"
                          v-beam="isRunningCompaction(group.part)"
                          class="compaction-token-detail process-step-detail process-card-preview"
                        >{{ compactionDetail(group.part) }}</span>
                      </Transition>
                    </button>
                    <div
                      v-if="shouldShowCompactionSummary(group.part)"
                      :id="'compaction-summary-' + group.part.id"
                      class="compaction-summary"
                      aria-live="polite"
                      aria-atomic="false"
                    >
                      <pre class="compaction-summary-text" :class="{ 'compaction-summary-text--streaming': isRunningCompaction(group.part) }">{{ compactionPreview(group.part) }}</pre>
                    </div>
                  </div>
                </template>
              </template>
            </div>
            </Transition>

            <div v-if="answerContent(msg)" class="assistant-answer">
              <slot name="assistant-content" :content="answerContent(msg)" :live="isLiveMessage(msg)">
                <MarkdownRenderer class="part-text-content" :content="answerContent(msg)" :streaming="isLiveMessage(msg)" :auto-plot-math="autoPlotMath" />
              </slot>
            </div>
          </template>

          <!-- Fallback: no parts → render flat content -->
          <slot v-else name="assistant-content" :content="answerContent(msg)">
            <MarkdownRenderer class="assistant-answer" :content="answerContent(msg)" :streaming="isLiveMessage(msg)" :auto-plot-math="autoPlotMath" />
          </slot>

          <!-- 本轮 artifact 产出统一挂到消息结尾；父级抑制避免子代理嵌套重复。 -->
          <Transition :css="false" @enter="artifactsEnter" @leave="fadeSlideLeave">
            <MessageAttachmentDeck
              v-if="messageArtifacts.length && !artifactsPanelSuppressed"
              class="message-artifacts"
              :artifacts="messageArtifacts"
              :transport="transport"
              :project-id="projectId"
              :work-root="workRoot"
              side="left"
              :heading="t('本轮产出')"
              :aria-label="t('本轮产出')"
            />
          </Transition>

          <!-- 输出中（turn 运行中，与 stop 按钮同步）：文字区域最下方三个圆点逐个显现循环 -->
          <div v-if="isActiveTurnMessage(msg)" class="streaming-dots" role="status" :aria-label="t('正在输出')">
            <span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"></span>
          </div>

          <!-- Message footer slot (for global stats line etc.) -->
          <slot name="message-footer" :message="msg" />

          <!-- Hover actions: copy / fork / roll back at this turn boundary.
               Turns before the last context compaction are excluded. -->
          <div
            v-if="messageActions && assistantActionable(msg) && !isActionLocked(msg)"
            class="assistant-actions"
            data-assistant-actions
          >
            <button
              type="button"
              class="assistant-action"
              :class="{ 'assistant-action--copied': copiedActionId === msg.id }"
              :title="copiedActionId === msg.id ? t('已复制') : t('复制回复')"
              :aria-label="copiedActionId === msg.id ? t('已复制') : t('复制回复')"
              data-message-copy
              @click="copyAssistantMessage(msg)"
            >
              <Copy v-if="copiedActionId !== msg.id" :size="15" :stroke-width="1.8" aria-hidden="true" />
              <Check v-else :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
            <button
              type="button"
              class="assistant-action"
              :title="t('从此处另开会话')"
              :aria-label="t('从此处另开会话')"
              data-message-fork
              @click="emit('fork-message', assistantActionPayload(msg))"
            >
              <GitFork :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
            <button
              type="button"
              class="assistant-action"
              :title="t('删除此轮及之后内容')"
              :aria-label="t('删除此轮及之后内容')"
              data-message-rollback
              @click="emit('rollback-message', assistantActionPayload(msg))"
            >
              <Undo2 :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
  </div>

  <Teleport to="body">
    <div v-if="previewImageSrc" ref="imagePreviewOverlayEl" class="image-preview-overlay" @keydown.esc="previewImageSrc = ''">
      <img ref="imagePreviewEl" :src="previewImageSrc" :alt="previewImageAlt" class="image-preview-full" />
      <button type="button" class="image-preview-close" :aria-label="t('关闭预览')" @click="previewImageSrc = ''">
        <X :size="18" :stroke-width="2" aria-hidden="true" />
      </button>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { t, uiLanguage } from '../i18n/index'

import type { CoreAttachment, CoreMessage, MessagePart, ToolArtifact } from '../types'
import type { LamToolsTransport, TransportHttpResponse } from '../transport'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch, type DirectiveBinding } from 'vue'
import { gsap } from 'gsap'
import {
  Brain,
  Check,
  CircleHelp,
  Copy,
  FilePenLine,
  FileText,
  Folder,
  GitBranch,
  GitFork,
  Globe,
  Hourglass,
  Image as ImageIcon,
  Info,
  Inbox,
  Minimize2,
  Pencil,
  Power,
  PowerOff,
  Search,
  Send,
  Terminal,
  TriangleAlert,
  Undo2,
  UserRoundPlus,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-vue-next'
import {
  assistantSegmentTurnId,
  // Decision presentation/selection semantics live in `pendingDecisions.ts` so
  // the in-thread card and the composer takeover panel cannot drift apart.
  coreDecisionDetail as decisionDetail,
  coreDecisionKindLabel as decisionKindLabel,
  coreDecisionOptionResponse as decisionOptionResponse,
  coreDecisionOptions as decisionOptions,
  coreDecisionTitle as decisionTitle,
  projectAssistantMessageParts,
} from '../appServer'
import type { CoreDecisionOption as DecisionOption } from '../appServer'
import { coreSubAgentRef, type CoreSubAgentRef } from '../agents/subAgentProjection'
import { formatSubAgentElapsed, normalizeSubAgentType } from '../agents/subAgentDisplay'
import { copyText } from '../helpers/clipboard'
import { autoGrowTextarea } from '../helpers/autoGrowTextarea'
import { workspaceRelativePath } from '../helpers/workspacePath'
import { useOutsidePointerDismiss } from '../composables/useOutsidePointerDismiss'
import { useNarrowViewport } from '../composables/useNarrowViewport'
import { useProcessSummaryClock } from '../composables/useProcessSummaryClock'
import AutoTextarea from './AutoTextarea.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import CoreSystemEventRow from './CoreSystemEventRow.vue'
import { isCoreSystemEvent, type CoreSystemEvent } from '../appServer/systemEvents'
import MessageAttachmentDeck from './MessageAttachmentDeck.vue'
import { artifactListingReference, artifactPathsInText, normalizeArtifactReference, shouldListTurnArtifact, workspaceRelativeFromReportPath } from '../artifacts/model'
import { isNativeContextTarget, openContextMenu } from './context-menu/context-menu'
import type { ContextMenuEntry } from './context-menu/types'
import MessageView from './MessageView.vue'
import { autoFollowScrollDirective as vAutoFollowScroll } from '../directives/autoFollowScroll'
import { panelEnter, panelLeave } from '../motion/expandPanel'
import { fadeSlideEnter, fadeSlideLeave } from '../motion/fadeSlide'

/**
 * 运行态标题流光（工具行 / sub-agent 行通用）：v-beam 挂在标题元素上，
 * 给 running 态文字添加「文字本身渐变流动」效果。
 * WebView2 下纯 CSS animation（left/transform/background-position 均无效）不触发重绘，
 * 只有每帧直接写内联样式才可靠。
 */
const flowEls = new Set<HTMLElement>()
let flowRaf = 0
let flowPos = 200
let flowLast = 0
let flowSkip = 0
const FLOW_SPEED = 0.036 // %/毫秒：background-size 200%，一次循环 200/0.036 ≈ 5.6s

function parseColorToRgb(color: string): [number, number, number] {
  // 用临时元素让浏览器把任意颜色格式归一化为 rgb/rgba
  const probe = document.createElement('div')
  probe.style.color = color
  document.body.appendChild(probe)
  const computed = window.getComputedStyle(probe).color
  probe.remove()
  const m = computed.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
  return m ? [parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10)] : [242, 239, 235]
}

function flowTick(ts: number) {
  // Re-arm unconditionally so the rAF chain can never stall; only the style
  // write is throttled (~20fps = every 3rd frame). Conditional re-arming
  // (skip this frame unless counter % 3 === 0) deadlocks on the first tick
  // because frame 1 never re-arms frame 2.
  flowRaf = requestAnimationFrame(flowTick)
  flowSkip += 1
  if (flowSkip % 3 !== 0) return
  if (flowLast) flowPos -= (ts - flowLast) * FLOW_SPEED
  flowLast = ts
  if (flowPos < 0) flowPos = 200
  for (const el of flowEls) el.style.backgroundPositionX = `${flowPos}%`
}
function mountFlowText(el: HTMLElement): void {
    if (flowEls.has(el)) return
    // prefers-reduced-motion：不注入流光，标题保持静态（无动效回退）
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    // 避免 color-mix（旧版 WebView2/Chromium<111 不支持），用 JS 算出主题文字色的 RGB
    const themeText = window.getComputedStyle(el).getPropertyValue('--theme-main-text').trim() || '#f2efeb'
    const [r, g, b] = parseColorToRgb(themeText)
    el.style.setProperty('--flow-r', String(r))
    el.style.setProperty('--flow-g', String(g))
    el.style.setProperty('--flow-b', String(b))
    el.classList.add('flow-text')
    el.style.backgroundPositionX = '200%'
    flowEls.add(el)
    if (flowEls.size === 1) flowRaf = requestAnimationFrame(flowTick)
}

function unmountFlowText(el: HTMLElement): void {
    el.classList.remove('flow-text')
    el.style.backgroundPositionX = ''
    el.style.removeProperty('--flow-r')
    el.style.removeProperty('--flow-g')
    el.style.removeProperty('--flow-b')
    flowEls.delete(el)
    if (flowEls.size === 0 && flowRaf) {
      cancelAnimationFrame(flowRaf)
      flowRaf = 0
    }
}

const vBeam = {
  mounted(el: HTMLElement, binding: DirectiveBinding<boolean | undefined>) {
    if (binding.value !== false) mountFlowText(el)
  },
  updated(el: HTMLElement, binding: DirectiveBinding<boolean | undefined>) {
    if (binding.value === false) unmountFlowText(el)
    else mountFlowText(el)
  },
  unmounted(el: HTMLElement) {
    unmountFlowText(el)
  },
}

defineOptions({ name: 'MessageView', inheritAttrs: false })

defineSlots<{
  'message-product'?: (props: { message: CoreMessage }) => unknown
  'assistant-content'?: (props: { content: string; live?: boolean }) => unknown
  'reasoning-content'?: (props: { content: string; live?: boolean }) => unknown
  'message-footer'?: (props: { message: CoreMessage }) => unknown
}>()

const props = withDefaults(
  defineProps<{
    /** Single message rendered by this component (stable reference from the projection cache). */
    msg: CoreMessage
    assistantLabel?: string
    /** Set of message ids whose process section is expanded */
    processExpandedIds?: Set<string>
    /** Show hover actions (copy / fork / roll back) under assistant replies */
    messageActions?: boolean
    /** Connection-neutral backend used to load artifact bytes. */
    transport: LamToolsTransport
    /** Project id whose work_root contains the image artifact paths */
    projectId?: string | null
    /** Project work_root — enables direct local file reads in Tauri (asset protocol) */
    workRoot?: string | null
    /** 当前 active turn id（与 turnActive 搭配：消息属于运行中的 turn 时显示底部三圆点） */
    activeTurnId?: string | null
    /** 当前 turn 是否在运行（与 composer stop 按钮同一信号源） */
    turnActive?: boolean
    /** 当前 turn 的精确状态；等待/中断/终态不推进耗时。 */
    turnStatus?: string
    /** 位于最后一次上下文压缩之前、因而不再提供编辑/分叉/回退的消息 id。 */
    lockedMessageIds?: Set<string>
    /** 挂载时播放入场动效（新消息淡入；初始批次/历史加载不播）。
        注意不能做成 directive：本组件多根（div + Teleport），运行时 directive 不生效。 */
    motionEnter?: boolean
    /** 「本轮产出」面板抑制（由父消息向下传播）：本轮运行中，子代理 sub-line 段
        的面板同样隐藏，轮次结束才出现 */
    suppressArtifactsPanel?: boolean
  /** 面板内部：子代理行明确不可点（面板不消费"打开子代理"事件，别让用户以为点了没反应）。 */
  subAgentRowsInert?: boolean
    /** Automatically plot supported display-math formulas in final answers. */
    autoPlotMath?: boolean
  }>(),
  {
    assistantLabel: 'Assistant',
    processExpandedIds: () => new Set(),
    messageActions: false,
    projectId: null,
    workRoot: null,
    activeTurnId: null,
    turnActive: false,
    turnStatus: 'idle',
    lockedMessageIds: () => new Set(),
    motionEnter: false,
    suppressArtifactsPanel: false,
  subAgentRowsInert: false,
    autoPlotMath: false,
  },
)

const emit = defineEmits<{
  'toggle-process': [messageId: string]
  'decision-select': [payload: { partId: string; option: DecisionOption; response: string }]
  'fork-message': [payload: AssistantActionPayload]
  'rollback-message': [payload: AssistantActionPayload]
  'edit-message': [payload: EditMessagePayload]
  /** 打开右侧子代理分屏：只带身份，由壳体从当前消息投影里解析出运行。 */
  'open-sub-agent': [ref: CoreSubAgentRef]
}>()

function openSubAgentPane(part: MessagePart): void {
  emit('open-sub-agent', coreSubAgentRef(part))
}

const assistantTimestamp = computed(() => formatAssistantTimestamp(props.msg.timestamp))

type MobileTurnProgress = {
  label: string
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  expires_at?: number
}

const mobileProgress = computed<MobileTurnProgress | null>(() => {
  const raw = (props.msg.metadata as Record<string, unknown> | undefined)?.mobile_turn_progress
  if (!raw || typeof raw !== 'object') return null
  const progress = raw as Record<string, unknown>
  if (typeof progress.label !== 'string' || !['running', 'completed', 'failed', 'cancelled'].includes(String(progress.status))) return null
  return progress as MobileTurnProgress
})
const mobileRuntimeWarnings = computed(() => {
  const raw = (props.msg.metadata as Record<string, unknown> | undefined)?.mobile_runtime_warnings
  return Array.isArray(raw) ? raw.filter((warning): warning is string => typeof warning === 'string') : []
})
const mobileProgressVisible = ref(false)
let mobileProgressTimer: ReturnType<typeof setTimeout> | undefined
watch(mobileProgress, progress => {
  if (mobileProgressTimer) clearTimeout(mobileProgressTimer)
  mobileProgressTimer = undefined
  const remaining = progress?.status === 'running' ? Infinity : Number(progress?.expires_at) - Date.now()
  mobileProgressVisible.value = !!progress && remaining > 0
  if (Number.isFinite(remaining) && remaining > 0) {
    mobileProgressTimer = setTimeout(() => { mobileProgressVisible.value = false }, remaining)
  }
}, { immediate: true })
onBeforeUnmount(() => { if (mobileProgressTimer) clearTimeout(mobileProgressTimer) })

function formatAssistantTimestamp(value: string | undefined): { compact: string; expanded: string } | null {
  const date = value ? new Date(value) : null
  if (!date || Number.isNaN(date.getTime())) return null
  const pad = (part: number) => String(part).padStart(2, '0')
  const compact = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  const expanded = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${compact}:${pad(date.getSeconds())}`
  return { compact, expanded }
}

// ── 消息入场动效（motionEnter prop，ChatThread 传入）：新消息挂载时淡入。
//    mount-only + transform/opacity + 局部元素，不写响应式状态、不动兄弟节点
//    （对齐 perf 文档红线；reduced-motion / 无 rAF 环境直切）。
const rootEl = ref<HTMLElement | null>(null)

// 组件级 GSAP 作用域 context（对齐 gsap-frameworks 规范）：本轮产出面板等
// Transition 钩子里创建的 tween 全部挂进 ctx，卸载时一次 revert 清理。
const gsapCtx = gsap.context(() => {}, rootEl)

onMounted(() => {
  if (!props.motionEnter || !rootEl.value) return
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  if (typeof requestAnimationFrame !== 'function') return
  gsap.fromTo(
    rootEl.value,
    { autoAlpha: 0, y: 8 },
    {
      autoAlpha: 1,
      y: 0,
      duration: 0.22,
      ease: 'power2.out',
      overwrite: true,
      clearProps: 'autoAlpha,transform',
    },
  )
})

onBeforeUnmount(() => {
  // 消息入场 tween（mount-only）与 ctx 内新动画（本轮产出面板）统一清理
  if (rootEl.value) gsap.killTweensOf(rootEl.value)
  gsapCtx.revert()
})

// ── Transition 入场钩子（本轮产出面板）：tween 挂进 gsapCtx，
//    由 ctx.revert() 统一清理；离场走 fadeSlideLeave 瞬时直切（出现类元素移除无需动画）。
function artifactsEnter(el: Element, done: () => void): void {
  gsapCtx.add(() => fadeSlideEnter(el, done))
}

interface AssistantActionPayload {
  turnId: string
  content: string
}

interface EditMessagePayload {
  turnId: string
  content: string
  /** 原消息附件（已上传，随编辑重新发送，无需重新上传） */
  attachments?: CoreAttachment[]
}

const decisionGuideDrafts = ref<Record<string, string>>({})

// ── Helpers ──

interface AgentTimelineItem {
  id: string
  title: string
  detail: string
  status: string
  kind: 'reasoning' | 'tool' | 'step' | 'conclusion'
  toolName?: string
  toolArgs?: Record<string, unknown>
  toolResult?: string
  toolError?: string
  artifacts?: MessagePart['artifacts']
  metadata?: Record<string, unknown>
}

interface AgentSubstep {
  label: string
  value: string
  status: string
}

interface ChecklistItem {
  id: string
  text: string
  status: string
  checked: boolean
}

const toolExpandedIds = ref<Set<string>>(new Set())
// Explicit wrap choices only. The default follows the viewport: a phone has no
// room to pan a long diff line sideways, so a tool card wraps there unless the
// reader taps the toggle back to scroll.
const toolWrapChoices = ref<Map<string, boolean>>(new Map())
const narrowViewport = useNarrowViewport()
const fullyExpandedPartIds = ref<Set<string>>(new Set())
const processTitleSnapshots = ref<Record<string, string>>({})
let processTitleTimer: ReturnType<typeof setInterval> | null = null
const subAgentTitleNow = ref(Date.now())
let subAgentTitleTimer: ReturnType<typeof setInterval> | null = null

// v-memo dependency for a single part card. A stable part reference + stable
// derived booleans lets Vue skip rebuilding that part's whole vnode subtree on
// stream ticks — without this, every delta re-patched ALL parts of a large live
// message (thousands of tool cards), which is the runtime-core self-time spike.
function partMemo(part: MessagePart, live: boolean): unknown[] {
  return [
    uiLanguage.value,
    part,
    isPartExpanded(part, live),
    // `live` 与 `autoPlotMath` 都参与 v-memo 子树里的渲染（streaming 样式、
    // 推理时长、数学自动绘图），漏掉它们时这两者变化不会重渲染
    // （2026-09-25 审计 P3）。
    live,
    props.autoPlotMath,
    fullyExpandedPartIds.value.has(part.id),
    processTitleSnapshot(part),
    toolExpandedIds.value.has(part.id),
    isToolWrapEnabled(part.id),
    decisionGuideDrafts.value[part.id],
  ]
}

function toggleToolExpand(partId: string) {
  const next = new Set(toolExpandedIds.value)
  if (next.has(partId)) {
    next.delete(partId)
  } else {
    next.add(partId)
  }
  toolExpandedIds.value = next
}

function isToolExpanded(partId: string): boolean {
  return toolExpandedIds.value.has(partId)
}

function togglePartExpand(part: MessagePart, live = false) {
  const partId = part.id
  cancelPartAutoCollapse(partId)
  
  // A click is an explicit user decision. Keep it separate from automatic
  // expansion so a completion timer can never close a manually opened part.
  if (isPartExpanded(part, live)) {
    userExpandedPartIds.value = new Set([...userExpandedPartIds.value].filter(id => id !== partId))
    userCollapsedPartIds.value = new Set([...userCollapsedPartIds.value, partId])
    fullyExpandedPartIds.value = new Set([...fullyExpandedPartIds.value].filter(id => id !== partId))
  } else {
    userExpandedPartIds.value = new Set([...userExpandedPartIds.value, partId])
    userCollapsedPartIds.value = new Set([...userCollapsedPartIds.value].filter(id => id !== partId))
    fullyExpandedPartIds.value = new Set([...fullyExpandedPartIds.value].filter(id => id !== partId))
  }
}

function promotePartCard(partId: string, event: MouseEvent) {
  const target = event.target instanceof Element ? event.target : null
  if (target?.closest('button, a, input, textarea, select, [role="button"]')) return
  if (!userExpandedPartIds.value.has(partId) || fullyExpandedPartIds.value.has(partId)) return
  fullyExpandedPartIds.value = new Set([...fullyExpandedPartIds.value, partId])
}

function processCardBodyStateClass(part: MessagePart, live = false): string {
  return isPartExpanded(part, live) && fullyExpandedPartIds.value.has(part.id)
    ? 'process-card-body--expanded'
    : 'process-card-body--preview'
}

function toggleGroupExpand(groupId: string) {
  cancelGroupAutoCollapse(groupId)
  const next = new Set(expandedGroupIds.value)
  if (next.has(groupId)) {
    next.delete(groupId)
  } else {
    next.add(groupId)
  }
  expandedGroupIds.value = next
}

function isGroupExpanded(groupId: string): boolean {
  return expandedGroupIds.value.has(groupId)
}

/** A live group keeps growing while reasoning and tool parts stream in, so its
 * identity is its first member and not the member list: expanding a group and
 * having the next tool row arrive must land on the same id, otherwise the group
 * the user opened on purpose silently closes under them. */
function processGroupId(group: PartGroupProcessGroup): string {
  return group.parts[0]?.id ?? ''
}

function isPartExpanded(part: MessagePart, live = false): boolean {
  if (userCollapsedPartIds.value.has(part.id)) return false
  if (part.partType === 'error') return true // Errors always expanded
  if (userExpandedPartIds.value.has(part.id)) return true
  if (isSubLinePart(part)) return false // Sub-agents collapsed by default
  
  // Reasoning, tool, status: collapsed by default unless toggled
  if (part.partType === 'reasoning' || part.partType === 'tool_call' || part.partType === 'tool_result') {
    return false
  }
  if (part.partType === 'status') {
    return false
  }
  
  // Default collapsed for others unless explicitly expanded
  return false
}

// ── Explicit expansion + pointer-leave auto-collapse ──
const userExpandedPartIds = ref<Set<string>>(new Set())
const userCollapsedPartIds = ref<Set<string>>(new Set())
const expandedGroupIds = ref<Set<string>>(new Set())
const partCompletionTimers = new Map<string, ReturnType<typeof setTimeout>>()
const groupCollapseTimers = new Map<string, ReturnType<typeof setTimeout>>()

function schedulePartAutoCollapse(partId: string) {
  if (!userExpandedPartIds.value.has(partId)) return
  const existing = partCompletionTimers.get(partId)
  if (existing) clearTimeout(existing)
  const timer = setTimeout(() => {
    userExpandedPartIds.value = new Set([...userExpandedPartIds.value].filter(id => id !== partId))
    userCollapsedPartIds.value = new Set([...userCollapsedPartIds.value, partId])
    fullyExpandedPartIds.value = new Set([...fullyExpandedPartIds.value].filter(id => id !== partId))
    partCompletionTimers.delete(partId)
  }, 5000)
  partCompletionTimers.set(partId, timer)
}

function cancelPartAutoCollapse(partId: string) {
  const timer = partCompletionTimers.get(partId)
  if (!timer) return
  clearTimeout(timer)
  partCompletionTimers.delete(partId)
}

function scheduleGroupAutoCollapse(groupId: string) {
  if (!expandedGroupIds.value.has(groupId)) return
  const existing = groupCollapseTimers.get(groupId)
  if (existing) clearTimeout(existing)
  const timer = setTimeout(() => {
    expandedGroupIds.value = new Set([...expandedGroupIds.value].filter(id => id !== groupId))
    groupCollapseTimers.delete(groupId)
  }, 5000)
  groupCollapseTimers.set(groupId, timer)
}

function cancelGroupAutoCollapse(groupId: string) {
  const timer = groupCollapseTimers.get(groupId)
  if (!timer) return
  clearTimeout(timer)
  groupCollapseTimers.delete(groupId)
}

function refreshProcessTitleSnapshots() {
  const next: Record<string, string> = {}
  for (const part of processParts(props.msg)) {
    next[part.id] = buildProcessTitleSnapshot(part)
  }
  const current = processTitleSnapshots.value
  const currentKeys = Object.keys(current)
  const nextKeys = Object.keys(next)
  const changed = currentKeys.length !== nextKeys.length
    || nextKeys.some(key => current[key] !== next[key])
  if (changed) processTitleSnapshots.value = next
}

watch(uiLanguage, refreshProcessTitleSnapshots)

function stopProcessTitleTimer() {
  if (!processTitleTimer) return
  clearInterval(processTitleTimer)
  processTitleTimer = null
}

// ── Retry label for tool status ──
function toolRetryLabel(part: MessagePart): string {
  const meta = (part.metadata || {}) as Record<string, unknown>
  const retryCount = typeof meta.retry_count === 'number' ? meta.retry_count
    : typeof meta.retryCount === 'number' ? meta.retryCount : 0
  const maxRetries = typeof meta.max_retries === 'number' ? meta.max_retries
    : typeof meta.maxRetries === 'number' ? meta.maxRetries : 0
  if (part.status === 'running' && retryCount > 0) {
    return maxRetries > 0 ? t("重试中 {0}/{1}", { 0: retryCount, 1: maxRetries }) : t("重试中")
  }
  return ''
}

// ── Model retry progress bar helpers ──
function isModelRetryPart(part: MessagePart): boolean {
  if (part.partType !== 'status') return false
  return /模型请求重试/.test(String(part.content || ''))
}

function modelRetryCounts(part: MessagePart): { attempt: number; maxRetries: number } {
  const text = String(part.content || '')
  const match = text.match(/\((\d+)\/(\d+)\)/)
  if (match) {
    return { attempt: parseInt(match[1], 10) || 0, maxRetries: parseInt(match[2], 10) || 0 }
  }
  return { attempt: 1, maxRetries: 0 }
}

function modelRetryDetail(part: MessagePart): string {
  const detail = String(part.detail || '').trim()
  if (detail) return detail
  const meta = (part.metadata || {}) as Record<string, unknown>
  const error = typeof meta.error === 'string' ? meta.error.trim() : ''
  const delay = typeof meta.delay_seconds === 'number' ? meta.delay_seconds : null
  if (error && delay !== null) return t("{0}s 后重试：{1}", { 0: delay, 1: error })
  return error
}

function isSubLinePart(part: MessagePart): boolean {
  return part.partType === 'sub_line' || part.partType === 'agent_summary'
}

/**
 * 委派工具那一行（生命周期 create/close 与信箱收发）：投影按 selectors 的
 * `normalizeCoreItemDisplayType` 把它保留成普通工具行（专用文案与图标另行钉住），
 * 所以它走工具卡渲染，但点击语义与其余子代理行一致——点整行打开右侧分屏，
 * 行尾箭头才就地展开（用户 2026-10-12 报的就是这处缺动作）。
 */
function isSubAgentToolRow(part: MessagePart): boolean {
  const name = String(part.toolName || '').trim().toLowerCase()
  return name === 'sub_agent' || name === 'subagent'
    || name === 'sub_agent_message' || name === 'sub_agent_receive'
}

/** 工具行点击：委派子代理那一行打开右侧分屏，其余工具行就地展开卡片。 */
function activateToolRow(part: MessagePart, live = false): void {
  if (isSubAgentToolRow(part)) {
    // 面板内部这些行不可点：不抛事件，也不给任何反馈。
    if (!props.subAgentRowsInert) openSubAgentPane(part)
    return
  }
  togglePartExpand(part, live)
}

function attachmentParts(message: CoreMessage): MessagePart[] {
  return (message.parts || []).filter(part => part.partType === 'attachment')
}

function attachmentFromPart(part: MessagePart): CoreAttachment | null {
  const raw = part.metadata?.attachment
  if (!raw || typeof raw !== 'object') return null
  return raw as CoreAttachment
}

function messageAttachments(message: CoreMessage): CoreAttachment[] {
  return attachmentParts(message)
    .map(part => attachmentFromPart(part))
    .filter((attachment): attachment is CoreAttachment => attachment !== null)
}

function toggleToolWrap(partId: string) {
  const next = new Map(toolWrapChoices.value)
  next.set(partId, !isToolWrapEnabled(partId))
  toolWrapChoices.value = next
}

function isToolWrapEnabled(partId: string): boolean {
  return toolWrapChoices.value.get(partId) ?? narrowViewport.value
}

function hasToolDisplay(part: MessagePart): boolean {
  if (
    part.status === 'running'
    && !part.toolResult
    && !part.toolError
    && !part.inputPreview?.content
    && !fileArtifactContent(part)
  ) return false
  return Boolean(displayToolResult(part) || displayToolError(part) || displayToolInputPreview(part) || readableProcessDetail(part))
}

function shouldShowToolBody(part: MessagePart, live = false): boolean {
  // 委派子代理那一行没有行内正文：点整行开右侧面板，过程流在那里完整可见
  // （用户 2026-10-12 口径：不要双行为）。
  if (isSubAgentToolRow(part)) return false
  if (!hasToolDisplay(part)) return false
  return isPartExpanded(part, live)
}

function reasoningDuration(part: MessagePart, live = false): string {
  if (!part.startedAt) return ''
  if (!part.completedAt && (!live || part.status !== 'running')) return ''
  const start = new Date(part.startedAt).getTime()
  const end = part.completedAt ? new Date(part.completedAt).getTime() : Date.now()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return ''
  const seconds = Math.round((end - start) / 1000)
  if (seconds < 1) return ''
  return `Thought for ${seconds}s`
}

function toolArgsPreview(args: Record<string, unknown>): string {
  const chips = toolArgChips(args)
  if (chips.length > 0) return chips.join(' · ')

  const entries = Object.entries(args).filter(([, v]) => v != null && v !== '')
  if (entries.length === 0) return ''
  const parts = entries.slice(0, 3).map(([k, v]) => {
    const val = typeof v === 'string' ? v : JSON.stringify(v)
    const truncated = val.length > 40 ? val.slice(0, 40) + '…' : val
    return `${k}: ${truncated}`
  })
  const more = entries.length > 3 ? ` +${entries.length - 3}` : ''
  return `(${parts.join(', ')}${more})`
}

function shouldShowToolArgsPreview(part: MessagePart): boolean {
  if (!part.toolArgs || Object.keys(part.toolArgs).length === 0) return false
  if (isCommandTool(part)) return false
  const target = processTarget(part)
  const name = (part.toolName || part.label || '').toLowerCase()
  return !(target && processActionTitle(name, target))
}

function toolArgChips(args: Record<string, unknown>): string[] {
  const chips: string[] = []
  const file = args.path || args.file || args.file_path
  if (file) chips.push(t("文件 {0}", { 0: compactPath(String(file)) }))

  // 记忆工具分「项目档 / 全局档」：不标档位时，同一条路径在两档各读一次
  // 会显示成两张一模一样的卡片，看起来像重复调用。
  const scope = String(args.scope || '')
  if (scope === 'project') chips.push(t("档位 项目档"))
  else if (scope === 'global') chips.push(t("档位 全局档"))

  const start = args.start_line || args.startLine || args.line_start
  const end = args.end_line || args.endLine || args.line_end
  if (start && end) chips.push(t("范围 {0}-{1} 行", { 0: start, 1: end }))
  else if (start) chips.push(t("从第 {0} 行", { 0: start }))

  const pattern = args.pattern || args.query
  if (pattern && !file) chips.push(t("搜索 {0}", { 0: compactDetail(String(pattern), 44) }))

  const command = args.command || args.cmd
  if (command) chips.push(t("命令 {0}", { 0: compactDetail(String(command), 64) }))

  return chips
}

function toolColorClass(part: MessagePart): string {
  if (isUnavailableToolNotice(part)) return 'tool-color--warn'
  if (isControlTool(part)) return 'tool-color--default'
  const name = (part.toolName || '').toLowerCase()
  if (name.includes('browser') || name.includes('web') || name.includes('fetch') || name.includes('http')) return 'tool-color--web'
  if (name.includes('read') || name.includes('list') || name.includes('glob') || name.includes('grep') || name.includes('search')) return 'tool-color--read'
  if (name.includes('write') || name.includes('edit') || name.includes('patch') || name.includes('create')) return 'tool-color--write'
  if (name.includes('command') || name.includes('run') || name.includes('exec') || name.includes('bash')) return 'tool-color--exec'
  if (name.includes('git') || name.includes('commit') || name.includes('branch')) return 'tool-color--git'
  if (name.includes('test') || name.includes('verify') || name.includes('check')) return 'tool-color--test'
  if (name.includes('delete') || name.includes('remove')) return 'tool-color--del'
  return 'tool-color--default'
}

function processColorClass(part: MessagePart): string {
  if (part.partType === 'decision') return 'tool-color--web'
  if (isSubLinePart(part)) return 'tool-color--git'
  if (part.partType === 'compaction') return 'tool-color--default'
  if (isControlTool(part)) return 'tool-color--default'
  if (part.partType === 'error') return 'tool-color--del'
  if (part.partType === 'file_diff') return 'tool-color--write'
  if (part.partType === 'command_output') return 'tool-color--exec'
  return toolColorClass(part)
}

function isFileTool(part: MessagePart): boolean {
  if (unavailableToolName(part)) return false
  if (fileArtifact(part)) return true
  const name = (part.toolName || '').toLowerCase()
  return /read_file|write_file|edit_file|create_file|delete_range|list_dir|glob|grep|search_content/.test(name)
}

function fileDiffClass(part: MessagePart): string {
  const name = (part.toolName || '').toLowerCase()
  if (/write_file|edit_file|create_file/.test(name)) return 'diff-block--write'
  if (/read_file|list_dir|glob|grep|search_content/.test(name)) return 'diff-block--read'
  return ''
}

// ── 因地制宜批次一：收起行尾部的结果小标记 ──
// 命令行看成败与运行时长，文件改动看增删行数，测试行看结论；成功绿、失败红，
// 与任务状态色语义一致。标记只是收起行的摘要，展开体保持各自原有形态。
function commandElapsedLabel(part: MessagePart): string {
  const start = part.startedAt ? new Date(part.startedAt).getTime() : Number.NaN
  if (!Number.isFinite(start)) return ''
  const end = part.completedAt ? new Date(part.completedAt).getTime() : Date.now()
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  return seconds >= 1 ? `${seconds}s` : ''
}

function commandExitCode(part: MessagePart): number | null {
  const meta = (part.metadata || {}) as Record<string, unknown>
  const raw = meta.exit_code ?? meta.exitCode
  const direct = raw === undefined || raw === null ? Number.NaN : Number(raw)
  if (Number.isFinite(direct)) return direct
  const match = /\[exit_code[:\s]+(-?\d+)\s*\]/i.exec(displayToolResult(part))
  return match ? Number(match[1]) : null
}

function fileDiffStat(part: MessagePart): { added: number; removed: number } | null {
  // 只统计写类工具的统一差异：读类输出即使长得像差异也不是改动量。
  if (fileDiffClass(part) !== 'diff-block--write') return null
  const result = displayToolResult(part)
  if (!result || !isUnifiedDiff(part)) return null
  let added = 0
  let removed = 0
  for (const line of result.split('\n')) {
    if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@')) continue
    if (line.startsWith('+')) added += 1
    else if (line.startsWith('-')) removed += 1
  }
  return added || removed ? { added, removed } : null
}

type ToolRowFlagTone = 'good' | 'bad' | 'muted' | 'stat' | 'info'

function toolRowFlagTone(part: MessagePart): ToolRowFlagTone | '' {
  const memory = memoryRowDirection(part)
  if (memory) return memory === 'read' ? 'muted' : 'info'
  if (testArtifact(part)) return testArtifactMetadata(part).passed === true ? 'good' : 'bad'
  if (isCommandTool(part)) {
    if (part.status === 'running') return commandElapsedLabel(part) ? 'muted' : ''
    if (part.status === 'error' || part.toolError) return 'bad'
    const exit = commandExitCode(part)
    if (exit !== null && exit !== 0) return 'bad'
    return part.status === 'completed' ? 'good' : ''
  }
  return fileDiffStat(part) ? 'stat' : ''
}

function toolRowFlagText(part: MessagePart): string {
  const memory = memoryRowDirection(part)
  if (memory) return memory === 'read' ? t("读") : t("写")
  if (testArtifact(part)) {
    const meta = testArtifactMetadata(part)
    if (meta.passed === true) return t("✓ 通过")
    return meta.summary === 'timed_out' ? t("✗ 超时") : t("✗ 失败")
  }
  if (isCommandTool(part)) {
    if (part.status === 'running') return commandElapsedLabel(part)
    if (part.status === 'error' || part.toolError) return t("✗ 失败")
    const exit = commandExitCode(part)
    if (exit !== null && exit !== 0) return t("✗ 退出码 {0}", { 0: exit })
    return part.status === 'completed' ? '✓' : ''
  }
  return ''
}

function toolRowFlagStat(part: MessagePart): { added: number; removed: number } {
  return fileDiffStat(part) ?? { added: 0, removed: 0 }
}

// ── 因地制宜批次二：搜索、网页、记忆的专属形态 ──

// 内容搜索：`路径:行号: 内容` 逐行成命中清单，替代整段原始文本块。
function isContentSearchTool(part: MessagePart): boolean {
  const name = (part.toolName || '').toLowerCase()
  return /grep|search_content|search_files/.test(name)
}

interface ContentSearchHit { path: string; line: string; text: string }

function contentSearchHits(part: MessagePart): ContentSearchHit[] {
  const result = displayToolResult(part)
  if (!result) return []
  const hits: ContentSearchHit[] = []
  for (const line of result.split('\n')) {
    const match = /^(.+?):(\d+):\s?(.*)$/.exec(line)
    if (match) hits.push({ path: match[1], line: match[2], text: match[3] })
  }
  return hits
}

function contentSearchNotes(part: MessagePart): string[] {
  const result = displayToolResult(part)
  if (!result) return []
  return result.split('\n').filter(line => /^\[\.\.\./.test(line.trim()))
}

// 网页获取：突出页面标题与正文开头摘要，原始全文收进"查看全文"。
function isWebFetchTool(part: MessagePart): boolean {
  const name = (part.toolName || '').toLowerCase()
  return /fetch|http|browser|crawl|read_url|open_url|web_page|webpage/.test(name) && !/search/.test(name)
}

function decodeBasicEntities(text: string): string {
  return text
    .replace(/&nbsp;/gi, ' ')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/g, '\'')
    .replace(/&apos;/gi, '\'')
    .replace(/&amp;/gi, '&')
}

function webFetchTitle(part: MessagePart): string {
  const result = displayToolResult(part)
  if (!result) return ''
  const titleTag = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(result)
  if (titleTag?.[1]) return decodeBasicEntities(titleTag[1].replace(/\s+/g, ' ').trim())
  const markdown = /^#\s+(.+)$/m.exec(result)
  return markdown?.[1] ? decodeBasicEntities(markdown[1].trim()) : ''
}

function webFetchSummary(part: MessagePart): string {
  const result = displayToolResult(part)
  if (!result) return ''
  const text = decodeBasicEntities(result
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim())
  if (!text) return ''
  return text.length > 200 ? `${text.slice(0, 200)}…` : text
}

// 记忆：读写方向标记——read/list 是读，其余动作都是写。
function memoryRowDirection(part: MessagePart): 'read' | 'write' | '' {
  if ((part.toolName || '').toLowerCase() !== 'memory') return ''
  const action = String((part.toolArgs || {}).action || '').toLowerCase()
  if (!action) return ''
  return action === 'read' || action === 'list' ? 'read' : 'write'
}

function isUnifiedDiff(part: MessagePart): boolean {
  const result = displayToolResult(part)
  return /^@@\s+-\d/m.test(result) || /^\+\+\+\s+/m.test(result) || /^---\s+/m.test(result)
}

function diffLineClass(line: string, part: MessagePart): string {
  if (!isUnifiedDiff(part)) return ''
  if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@')) return 'diff-line--meta'
  if (line.startsWith('+')) return 'diff-line--add'
  if (line.startsWith('-')) return 'diff-line--del'
  return ''
}

function diffDisplayLines(part: MessagePart): string[] {
  const lines = displayToolResult(part).split('\n')
  if (!isUnifiedDiff(part)) return lines
  return lines.filter(line => !line.startsWith('+++ ') && !line.startsWith('--- '))
}

function diffLineGutter(line: string, index: number, part: MessagePart): string {
  if (!isUnifiedDiff(part)) return String(index + 1)
  if (line.startsWith('+') && !line.startsWith('+++')) return '+'
  if (line.startsWith('-') && !line.startsWith('---')) return '-'
  return ''
}

function diffLineContent(line: string, part: MessagePart): string {
  if (!isUnifiedDiff(part)) return line
  if (line.startsWith('+') && !line.startsWith('+++')) return line.slice(1)
  if (line.startsWith('-') && !line.startsWith('---')) return line.slice(1)
  return humanizeDiffMetaLine(line)
}

function humanizeDiffMetaLine(line: string): string {
  const match = line.match(/^@@\s+-(\d+),?(\d*)\s+\+(\d+),?(\d*)\s+@@/)
  if (!match) return line
  const oldCount = Number(match[2] || 1)
  const newCount = Number(match[4] || 1)
  if (oldCount === 0 && newCount > 0) return t("新增 {0} 行", { 0: newCount })
  if (newCount === 0 && oldCount > 0) return t("删除 {0} 行", { 0: oldCount })
  return t("修改范围：原 {0} 行起，新 {1} 行起", { 0: match[1], 1: match[3] })
}

function diffHeaderText(part: MessagePart): string {
  const artifact = fileArtifact(part)
  const artifactPath = String(artifact?.metadata?.path || artifact?.uri || '')
  if (artifactPath) return artifactPath
  const args = part.toolArgs || {}
  // file path
  const path = String(args.path || args.file || args.file_path || '')
  if (path) return path
  const result = displayToolResult(part)
  const diffPath = result.match(/^\+\+\+\s+b\/(.+)$/m) || result.match(/^---\s+a\/(.+)$/m)
  if (diffPath?.[1]) return diffPath[1]
  // command
  const cmd = args.command || args.cmd || ''
  if (cmd) {
    const cmdArgs = Array.isArray(args.args) ? args.args.join(' ') : ''
    return cmdArgs ? `${cmd} ${cmdArgs}` : String(cmd)
  }
  // run_command may have the command as first positional arg
  if (typeof args === 'object') {
    const vals = Object.values(args).filter(v => typeof v === 'string' && v.length > 0 && v.length < 200)
    if (vals.length > 0) return String(vals[0])
  }
  return part.toolName || ''
}

function isLiveMessage(msg: CoreMessage): boolean {
  return !!(msg.metadata as Record<string, unknown>)?.live
}

/** The machine-authored system event stamped by the projection, if any. */
function systemEvent(msg: CoreMessage): CoreSystemEvent | null {
  const value = (msg.metadata as Record<string, unknown> | undefined)?.systemEvent
  return isCoreSystemEvent(value) ? value : null
}

/**
 * 消息所属 turn 当前正在运行（与 composer stop 按钮的 isCoreActiveTurnStatus 同步）。
 * 显示条件：turnActive（running/waiting/interrupting）且该消息属于 active turn。
 */
function isActiveTurnMessage(msg: CoreMessage): boolean {
  return props.turnActive === true
    && typeof props.activeTurnId === 'string' && props.activeTurnId !== ''
    && assistantSegmentTurnId(msg.id) === props.activeTurnId
}

const processSummaryClockEnabled = computed(() => (
  props.turnStatus === 'running'
  && isActiveTurnMessage(props.msg)
  && !isLiveMessage(props.msg)
  && processStartTimestamp(props.msg) !== null
  && processDurationMetric(props.msg) === null
  && processEndTimestamp(props.msg) === null
))
const processSummaryNow = useProcessSummaryClock(processSummaryClockEnabled)

function isInitialWaitingMessage(msg: CoreMessage): boolean {
  return !!(msg.metadata as Record<string, unknown>)?.initialWaiting
}

function shouldShowShallowThinkingPending(msg: CoreMessage): boolean {
  const metadata = (msg.metadata || {}) as Record<string, unknown>
  return Boolean(metadata.shallowThinkingPending)
    && !hasReasoningContent(msg)
    && !hasAnswerContent(msg)
}

function hasReasoningContent(msg: CoreMessage): boolean {
  return processParts(msg).some(part => (
    part.partType === 'reasoning'
    && String(part.content || '').trim().length > 0
  ))
}

const projectionCache = new WeakMap<CoreMessage, {
  parts: MessagePart[] | undefined
  processParts: MessagePart[] | undefined
  content: string
  answerText: string | undefined
  projection: ReturnType<typeof projectAssistantMessageParts>
}>()

function assistantPartsProjection(msg: CoreMessage): ReturnType<typeof projectAssistantMessageParts> {
  const cached = projectionCache.get(msg)
  if (
    cached
    && cached.parts === msg.parts
    && cached.processParts === msg.processParts
    && cached.content === msg.content
    && cached.answerText === msg.answerText
  ) {
    return cached.projection
  }

  const raw = Array.isArray(msg.processParts) && typeof msg.answerText === 'string'
    ? {
        processParts: msg.processParts,
        answerPart: msg.answerPart ?? null,
        answerText: msg.answerText,
      }
    : projectAssistantMessageParts(msg.parts || [], msg.content || '', { live: isLiveMessage(msg) })
  // Short-circuit the filter: the projection runs per stream frame, and a
  // message with nothing to drop must keep its original array identity.
  const hasDroppedPart = raw.processParts.some(
    part => isAnsweredDecision(part) || isMergedChecklistPart(part),
  )
  const projection = hasDroppedPart
    ? {
        ...raw,
        processParts: raw.processParts.filter(
          part => !isAnsweredDecision(part) && !isMergedChecklistPart(part),
        ),
      }
    : raw
  projectionCache.set(msg, {
    parts: msg.parts,
    processParts: msg.processParts,
    content: msg.content,
    answerText: msg.answerText,
    projection,
  })
  return projection
}

/**
 * 审批/决策卡只在需要用户处理时占位：答复一落定（completed）就整卡撤出过程时间线，
 * 不再以「已记录 / 已选择」的形态挂在对话末尾。未答复（pending）与提交中必须保留，
 * 否则用户看不到问题、无法回答。
 */
function isAnsweredDecision(part: MessagePart): boolean {
  return part.partType === 'decision' && part.status === 'completed'
}

/**
 * 同一轮里模型可以一次提交多条计划更新；每条更新都会拿到同一份「更新后」的计划，
 * 于是同一份计划被连续画成多张一样的卡。被合并的更新整卡撤出时间线，本轮只留
 * 最后那张卡（内容即更新后的计划）。
 */
function isMergedChecklistPart(part: MessagePart): boolean {
  const metadata = (part.metadata || {}) as Record<string, unknown>
  return metadata.checklist_merged === true
}

function processParts(msg: CoreMessage): MessagePart[] {
  return assistantPartsProjection(msg).processParts
}

watch(
  () => isLiveMessage(props.msg),
  (live) => {
    refreshProcessTitleSnapshots()
    stopProcessTitleTimer()
    if (live) processTitleTimer = setInterval(refreshProcessTitleSnapshots, 2000)
  },
  { immediate: true },
)

function syncSubAgentTitleTimer(): void {
  if (subAgentTitleTimer) {
    clearInterval(subAgentTitleTimer)
    subAgentTitleTimer = null
  }
  const hasLiveSubAgent = processParts(props.msg).some(part => (
    isSubLinePart(part) && (part.status === 'running' || part.status === 'pending')
  ))
  if (hasLiveSubAgent) {
    subAgentTitleNow.value = Date.now()
    subAgentTitleTimer = setInterval(() => { subAgentTitleNow.value = Date.now() }, 1000)
  }
}

watch(
  () => processParts(props.msg).map(part => `${part.id}:${part.status}:${part.completedAt || ''}`).join('|'),
  syncSubAgentTitleTimer,
  { immediate: true },
)

function systemBubbleClass(msg: CoreMessage): string {
  const meta = (msg.metadata || {}) as Record<string, unknown>
  if (meta.systemKind === 'error' || meta.systemKind === 'failed') return 'system-bubble--error'
  if (meta.systemKind === 'done' || meta.systemKind === 'completed') return 'system-bubble--done'
  if (meta.systemKind === 'waiting') return 'system-bubble--waiting'
  return 'system-bubble--info'
}

function systemIcon(msg: CoreMessage): LucideIcon {
  const meta = (msg.metadata || {}) as Record<string, unknown>
  if (meta.systemKind === 'error' || meta.systemKind === 'failed') return X
  if (meta.systemKind === 'done' || meta.systemKind === 'completed') return Check
  if (meta.systemKind === 'waiting') return Hourglass
  return Info
}

function isProcessExpanded(msg: CoreMessage): boolean {
  // During live streaming: auto-expand so user sees process unfolding (like GPT)
  if (isLiveMessage(msg)) return true
  // 运行中的回合里，被引导切开的前一段不再是"最后一条回复"（live 落到后一段），
  // 若按完成态折叠，用户正看着的那段过程文字会当场收进卡里——回合还在跑就保持
  // 展开，回合结束后仍旧回落到完成态折叠。
  if (isActiveTurnMessage(msg)) return true
  // Compaction is already a concise status row. Keep it visible so native
  // summary deltas and the terminal result are never hidden by a second,
  // redundant process disclosure.
  if (isCompactionOnlyMessage(msg)) return true
  // Completed process is collapsed by default; user can reopen it explicitly.
  return props.processExpandedIds?.has(msg.id) ?? false
}

function isCompactionOnlyMessage(msg: CoreMessage): boolean {
  const meaningfulParts = processParts(msg).filter(part => part.partType !== 'status')
  return meaningfulParts.length > 0
    && meaningfulParts.every(part => part.partType === 'compaction')
}

function isControlTool(part: MessagePart): boolean {
  const name = (part.toolName || part.label || '').toLowerCase()
  return /decision_point|write_checklist|update_checklist|verify_design|ask_clarification|chat_only|self_critique|question/.test(name)
}

/** Tools whose rows stay on their own line inside a message's process stream:
 * sub-agent hand-offs (delegating, messaging, receiving), skill loads, and
 * memory reads/writes — a memory call is a fact the operator tracks across the
 * turn, so folding it into "调用了 N 个工具" hides the tier and path it touched. */
const STANDALONE_PROCESS_TOOLS = new Set([
  'sub_agent',
  'subagent',
  'sub_agent_message',
  'sub_agent_receive',
  'load_skill',
  'memory',
])

function isStandaloneProcessPart(part: MessagePart): boolean {
  if (isSubLinePart(part)) return true
  const name = (part.toolName || part.label || '').trim().toLowerCase()
  return STANDALONE_PROCESS_TOOLS.has(name)
}

// ── Body/process projection: newest model text owns the body; replaced text becomes process ──

interface PartGroupProcess {
  kind: 'process'
  part: MessagePart
}

interface PartGroupProcessGroup {
  kind: 'process-group'
  parts: MessagePart[]
  summary: string
}

type PartGroup = PartGroupProcess | PartGroupProcessGroup

interface TextGroup {
  content: string
}

function liveStatusText(msg: CoreMessage): string {
  const metadata = (msg.metadata || {}) as Record<string, unknown>
  return String(metadata.liveStatus || metadata.statusText || t("正在处理"))
}

function liveDetailText(msg: CoreMessage): string {
  const metadata = (msg.metadata || {}) as Record<string, unknown>
  return String(metadata.liveDetail || metadata.detail || '').trim()
}

function hasAnswerContent(msg: CoreMessage): boolean {
  return Boolean(answerContent(msg).trim())
}

function terminalErrorText(msg: CoreMessage): string {
  const parts = processParts(msg)
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index]
    if (part.partType !== 'status' || part.status !== 'error') continue
    return String(part.detail || part.content || '').trim()
  }
  return ''
}

function answerContent(msg: CoreMessage): string {
  return assistantPartsProjection(msg).answerText
}

// ── User message hover actions: copy / edit ──

const editingMessageId = ref('')
const editDraft = ref('')
const editInputRef = ref<{ focus: () => void } | null>(null)

/** Extract the turn id from a `{turn_id}:user` message id (queue guide
 *  messages `…:user:guide:…` don't match and are not editable). */
function userTurnId(msg: CoreMessage): string {
  const id = String(msg.id || '')
  return id.endsWith(':user') ? id.slice(0, id.length - ':user'.length) : ''
}

/** 待生效的引导：已经发出、还没被模型接手（真实条目落库后会换成实色气泡）。 */
function isPendingGuidancePart(part: MessagePart): boolean {
  return (part.metadata as Record<string, unknown> | undefined)?.guidancePending === true
}

function userActionable(msg: CoreMessage): boolean {
  return Boolean(userTurnId(msg) && String(msg.content || '').trim())
}

/**
 * True for messages the backend already replaced with a context summary.
 * Edit/fork/rollback have no original text to work on there, so the entries
 * stay hidden; no checkpoint or pending change is required otherwise.
 */
function isActionLocked(msg: CoreMessage): boolean {
  return props.lockedMessageIds.has(String(msg.id || ''))
}

function userActionPayload(msg: CoreMessage): AssistantActionPayload {
  return { turnId: userTurnId(msg), content: String(msg.content || '') }
}

function startEditMessage(msg: CoreMessage) {
  editDraft.value = String(msg.content || '')
  editingMessageId.value = msg.id
  // 打开编辑即落好光标，不必再点一次输入框
  void nextTick(() => editInputRef.value?.focus())
}

function cancelEditMessage() {
  editingMessageId.value = ''
  editDraft.value = ''
}

function confirmEditMessage(msg: CoreMessage) {
  const content = editDraft.value.trim()
  if (!content) return
  emit('edit-message', {
    turnId: userTurnId(msg),
    content,
    attachments: attachmentParts(msg)
      .map(part => attachmentFromPart(part))
      .filter((attachment): attachment is CoreAttachment => attachment !== null),
  })
  cancelEditMessage()
}

// ── Assistant reply hover actions ──

const copiedActionId = ref('')
let copiedActionTimer: ReturnType<typeof setTimeout> | null = null

function assistantTurnId(msg: CoreMessage): string {
  const id = String(msg.id || '')
  if (!id.startsWith('assistant:')) return ''
  const rest = id.slice('assistant:'.length)
  if (!rest || rest.startsWith('waiting:')) return ''
  // Mid-turn guide messages split a turn into several assistant segments
  // (`assistant:<turn>` for the first, `assistant:<turn>#<n>` for later ones;
  // turn ids contain colons, so `#` is the segment marker); fork/rollback
  // target the whole turn, so strip the segment suffix.
  const hash = rest.indexOf('#')
  return hash >= 0 ? rest.slice(0, hash) : rest
}

function assistantActionable(msg: CoreMessage): boolean {
  return Boolean(assistantTurnId(msg) && answerContent(msg))
}

function assistantActionPayload(msg: CoreMessage): AssistantActionPayload {
  return { turnId: assistantTurnId(msg), content: answerContent(msg) }
}

function messageCopyContent(msg: CoreMessage): string {
  return msg.role === 'user' ? String(msg.content || '') : answerContent(msg)
}

function copyMessage(msg: CoreMessage): Promise<void> {
  const content = messageCopyContent(msg)
  return content ? copyText(content) : Promise.resolve()
}

function hasSelectedMessageText(): boolean {
  const selection = typeof window !== 'undefined' ? window.getSelection() : null
  return Boolean(selection && !selection.isCollapsed && selection.toString().trim())
}

function onContextMenu(event: MouseEvent): void {
  if (!props.messageActions || hasSelectedMessageText() || isNativeContextTarget(event.target)) return

  const msg = props.msg
  const items: ContextMenuEntry[] = []
  const locked = isActionLocked(msg)
  if (userActionable(msg)) {
    items.push({ id: 'copy', get label() { return t("复制消息") }, icon: Copy, action: () => copyMessage(msg) })
    if (!locked) {
      items.push(
        { type: 'separator', id: 'user-action-separator' },
        { id: 'edit', get label() { return t("编辑消息") }, icon: Pencil, action: () => startEditMessage(msg) },
        { id: 'fork', get label() { return t("从此处另开会话") }, icon: GitFork, action: () => emit('fork-message', userActionPayload(msg)) },
        { id: 'rollback', get label() { return t("回滚") }, icon: Undo2, destructive: true, action: () => emit('rollback-message', userActionPayload(msg)) },
      )
    }
  } else if (assistantActionable(msg)) {
    items.push({ id: 'copy', get label() { return t("复制回复") }, icon: Copy, action: () => copyMessage(msg) })
    if (!locked) {
      items.push(
        { type: 'separator', id: 'message-fork-separator' },
        { id: 'fork', get label() { return t("从此处另开会话") }, icon: GitFork, action: () => emit('fork-message', assistantActionPayload(msg)) },
        { id: 'rollback', get label() { return t("回滚") }, icon: Undo2, destructive: true, action: () => emit('rollback-message', assistantActionPayload(msg)) },
      )
    }
  }
  if (!items.length) return
  openContextMenu({
    event,
    items,
    ownerId: `message:${msg.id}`,
    ariaLabel: t("{0}操作", { 0: msg.role === 'user' ? t("用户消息") : t("助手回复") }),
    panelAttributes: { 'data-message-menu': msg.id },
  })
}

async function copyAssistantMessage(msg: CoreMessage) {
  const content = messageCopyContent(msg)
  if (!content) return
  try {
    await copyText(content)
  } catch {
    // Clipboard can be unavailable in an embedded desktop context.
  }
  copiedActionId.value = msg.id
  if (copiedActionTimer) clearTimeout(copiedActionTimer)
  copiedActionTimer = setTimeout(() => { copiedActionId.value = '' }, 1400)
}

onBeforeUnmount(() => {
  if (copiedActionTimer) clearTimeout(copiedActionTimer)
  stopProcessTitleTimer()
  if (subAgentTitleTimer) clearInterval(subAgentTitleTimer)
  subAgentTitleTimer = null
  for (const timer of partCompletionTimers.values()) clearTimeout(timer)
  partCompletionTimers.clear()
  for (const timer of groupCollapseTimers.values()) clearTimeout(timer)
  groupCollapseTimers.clear()
})

function processGroupCurrentPart(group: PartGroupProcessGroup): MessagePart {
  return [...group.parts].reverse().find(part => part.status === 'running')
    || group.parts[group.parts.length - 1]
}

function processIcon(part: MessagePart): LucideIcon {
  if (part.status === 'error') return TriangleAlert
  if (part.status === 'pending') return Hourglass
  if (part.partType === 'reasoning') return Brain
  if (part.partType === 'compaction') return Minimize2
  const subAgentEvent = subAgentEventKind(part)
  if (subAgentEvent === 'created') return UserRoundPlus
  if (subAgentEvent === 'enabled') return Power
  if (subAgentEvent === 'closed') return PowerOff
  if (subAgentEvent === 'message_sent') return Send
  if (subAgentEvent === 'message_received') return Inbox
  const name = String(part.toolName || part.label || '').toLowerCase()
  if (/command|shell|exec|bash|powershell|run|npm|python/.test(name)) return Terminal
  if (/write|edit|patch|apply|create/.test(name)) return FilePenLine
  if (/read|cat|get-content|open/.test(name)) return FileText
  if (/list|ls|dir/.test(name)) return Folder
  if (/grep|rg|search|find|glob/.test(name)) return Search
  if (/fetch|browser|http|web/.test(name)) return Globe
  if (/git|commit|branch/.test(name)) return GitBranch
  if (/question|ask|decision/.test(name)) return CircleHelp
  return Wrench
}

function processIconStateClass(part: MessagePart): string {
  return `process-card-state-icon--${part.status || 'completed'}`
}

function processAccessibleLabel(part: MessagePart): string {
  const state = part.status === 'running'
    ? t("运行中")
    : part.status === 'error'
      ? t("失败")
      : part.status === 'pending'
        ? t("等待中")
        : t("已完成")
  const title = readableProcessTitle(part)
  const snapshot = processTitleSnapshot(part)
  const base = snapshot === title ? `${title}，${state}` : `${title}，${state}，${snapshot}`
  // 委派子代理那一行点下去开的是右侧分屏（面板内部不可点，就不说"打开"）。
  if (isSubAgentToolRow(part)) return props.subAgentRowsInert ? t("{0}，不可点击", { 0: base }) : t("{0}，打开子代理面板", { 0: base })
  return base
}

function processTitleSnapshot(part: MessagePart): string {
  return processTitleSnapshots.value[part.id] || buildProcessTitleSnapshot(part)
}

function buildProcessTitleSnapshot(part: MessagePart): string {
  if (part.partType !== 'reasoning') return readableProcessTitle(part)
  return latestSemanticUnit(processDynamicText(part)) || readableProcessTitle(part)
}

function processDynamicText(part: MessagePart): string {
  if (part.partType === 'reasoning') return String(part.content || part.detail || '')
  const input = String(part.inputPreview?.content || '')
  const result = String(part.toolError || part.toolResult || part.content || part.detail || '')
  if (isWriteTool(part) && input) return input
  if (result) return result
  if (input) return input
  return processTarget(part) || readableProcessTitle(part)
}

function latestSemanticUnit(value: string): string {
  const normalized = value.replace(/\r\n?/g, '\n').trim()
  if (!normalized) return ''
  const lines = normalized.split(/\n+/).map(line => line.trim()).filter(Boolean)
  const lastLine = lines[lines.length - 1] || ''
  const units = lastLine.match(/[^。！？!?；;…]+(?:[。！？!?；;…]+|$)/g) || [lastLine]
  const tail = (units[units.length - 1] || lastLine)
    .replace(/^(?:[-*+]\s+|\d+[.)]\s+)/, '')
    .replace(/\s+/g, ' ')
    .trim()
  return tail || lastLine
}

function livePartTitle(part: MessagePart): string {
  if (part.label) return part.label
  if (part.toolName) return part.toolName
  const map: Partial<Record<MessagePart['partType'], string>> = {
    reasoning: '思考',
    model_text: '正文',
    tool_call: '调用工具',
    tool_result: '工具返回',
    file_diff: '文件改动',
    command_output: '命令输出',
    plan: '规划',
    todo_update: '更新任务',
    status: '状态',
    error: '出错',
    decision: '等待确认',
    sub_line: '过程',
    agent_summary: '过程',
    compaction: '上下文已压缩',
  }
  return map[part.partType] || t("处理中")
}

function modelTextTitle(part: MessagePart): string {
  const label = String(part.label || '').trim()
  if (!label) return t("正文")
  const normalized = label.toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ')
  if (normalized === 'model text' || normalized === 'agent message' || normalized === 'agentmessage') {
    return t("正文")
  }
  return label
}

function readableProcessTitle(part: MessagePart): string {
  const unavailableTool = unavailableToolName(part)
  if (unavailableTool) return t("工具不可用：{0}", { 0: unavailableTool })
  if (isUnavailableToolNotice(part)) return t("工具不可用")
  const subAgentTitle = subAgentEventTitle(part)
  if (subAgentTitle) return subAgentTitle
  if (part.partType === 'decision') return decisionTitle(part)
  if (isSubLinePart(part)) return agentTitle(part)
  if (part.partType === 'compaction') return part.label || t("上下文已压缩")
  if (isControlTool(part)) return controlTitle(part)
  if (part.partType === 'error') return part.label || t("出错")
  if (part.partType === 'status') return part.label || t("状态")
  if (part.partType === 'model_text') return modelTextTitle(part)
  if (part.partType === 'reasoning') return part.label || t("思考")
  if (part.partType === 'file_diff') return part.label || t("文件改动")
  if (part.partType === 'command_output') return part.label || t("命令输出")

  if (part.partType === 'tool_call' || part.partType === 'tool_result') {
    const target = processTarget(part)
    const name = (part.toolName || part.label || '').toLowerCase()
    const actionTitle = processActionTitle(name, target)
    if (actionTitle) return actionTitle
    if (/command|shell|exec|bash|powershell|run|npm|python/.test(name)) return t("运行命令")
    return readableToolTitle(name, target) || part.toolName || part.label || livePartTitle(part)
  }

  const target = processTarget(part)
  const name = (part.toolName || part.label || '').toLowerCase()
  const actionTitle = processActionTitle(name, target)
  if (actionTitle) return actionTitle
  if (/command|shell|exec|bash|powershell|run|npm|python/.test(name)) return t("运行命令")
  return readableToolTitle(name, target) || part.label || part.toolName || livePartTitle(part)
}

function processActionTitle(name: string, target: string): string {
  if (/command|shell|exec|bash|powershell|run|npm|python/.test(name)) return target ? t("运行 {0}", { 0: target }) : t("运行命令")
  if (/read|cat|get-content|open/.test(name)) return target ? t("读取 {0}", { 0: target }) : t("读取文件")
  if (/list|ls|dir/.test(name)) return target ? t("列出 {0}", { 0: target }) : t("列出目录")
  if (/grep|rg|search|find|glob/.test(name)) return target ? t("搜索 {0}", { 0: target }) : t("搜索内容")
  if (/write|create/.test(name)) return target ? t("创建 {0}", { 0: target }) : t("创建文件")
  if (/edit|patch|apply/.test(name)) return target ? t("编辑 {0}", { 0: target }) : t("编辑文件")
  if (/fetch|browser|http/.test(name)) return target ? t("获取网页 {0}", { 0: target }) : t("获取网页")
  if (/delete|remove/.test(name)) return target ? t("删除 {0}", { 0: target }) : t("删除内容")
  return ''
}

function readableToolTitle(name: string, target: string): string {
  if (/git/.test(name)) return name.includes('diff') ? t("查看 git 差异") : t("查看 git 状态")
  if (/question|ask/.test(name)) return t("提问")
  if (/sub_agent|subagent/.test(name)) return target ? t("委派子代理：{0}", { 0: target }) : t("委派子代理")
  if (/skill/.test(name)) return target ? t("加载技能 · {0}", { 0: target }) : t("加载技能")
  if (/goal/.test(name)) return t("管理目标")
  if (/arrange/.test(name)) return t("管理定时任务")
  if (/mcp/.test(name)) return t("调用 MCP 工具")
  if (/checklist/.test(name)) return t("更新任务清单")
  return ''
}

function readableProcessDetail(part: MessagePart): string {
  const unavailableTool = unavailableToolName(part)
  if (unavailableTool) return unavailableToolMessage(unavailableTool)

  const error = String(part.toolError || '').trim()
  if (error) return error

  const result = String(part.detail || part.content || part.toolResult || '').trim()
  if (!result) return ''
  if (isLowValueControlResult(part, result)) return ''
  const title = readableProcessTitle(part)
  if (result === title || result === part.label || result === part.toolName) return ''
  if (part.partType === 'tool_call' || part.partType === 'tool_result') return result
  if (part.partType === 'compaction') return compactionDetail(part)
  return compactDetail(result)
}

function fullProcessDetail(part: MessagePart): string {
  return String(part.detail || part.content || part.toolError || part.toolResult || '').trim()
}

function processDetailPreview(part: MessagePart): string {
  const detail = fullProcessDetail(part)
  return detail ? compactDetail(detail, 180) : readableProcessDetail(part)
}

function hasExpandableProcessDetail(part: MessagePart): boolean {
  if (part.partType !== 'error' && part.partType !== 'status') return false
  return Boolean(fullProcessDetail(part))
}

async function copyProcessDetail(part: MessagePart) {
  const detail = fullProcessDetail(part)
  if (!detail) return
  try {
    await navigator.clipboard?.writeText(detail)
  } catch {
    // Clipboard can be unavailable in embedded desktop contexts.
  }
}

async function copyToolErrorText(part: MessagePart) {
  const error = displayToolError(part)
  if (!error) return
  try {
    await navigator.clipboard?.writeText(error)
  } catch {
    // Clipboard can be unavailable in embedded desktop contexts.
  }
}

function compactionDetail(part: MessagePart): string {
  const metadata = part.metadata || {}
  const rawPart = part as unknown as Record<string, unknown>
  const status = compactionStatus(part)
  const reason = String(rawPart.reason || metadata.reason || '').trim()
  if (status === 'not_needed') {
    return t("{0}原上下文已保留", { 0: reason === 'no_gain' ? t("未获得收益 · ") : '' })
  }
  if (status === 'failed') {
    const failure = String(
      rawPart.message || rawPart.error || metadata.message || metadata.error || part.detail || '',
    ).trim()
    return failure ? t("原上下文已保留 · {0}", { 0: compactDetail(failure, 180) }) : t("原上下文已保留")
  }
  const before = rawPart.before_tokens ?? rawPart.beforeTokens ?? metadata.before_tokens ?? metadata.beforeTokens
  const after = rawPart.after_tokens ?? rawPart.afterTokens ?? metadata.after_tokens ?? metadata.afterTokens
  const segment = rawPart.segment ?? metadata.segment
  const segments = rawPart.segments ?? metadata.segments
  const pieces: string[] = []
  const beforeText = compactTokenCount(before)
  const afterText = compactTokenCount(after)
  if (beforeText && afterText && (status !== 'running' || beforeText !== afterText)) {
    pieces.push(t("{0} 至 {1}", { 0: beforeText, 1: afterText }))
  } else if (part.detail) {
    pieces.push(String(part.detail))
  }
  if (status === 'running' && typeof segment === 'number' && typeof segments === 'number' && segments > 0) {
    pieces.push(t("第 {0}/{1} 段", { 0: segment, 1: segments }))
  } else if (typeof segments === 'number' && segments > 1) {
    pieces.push(t("{0} 段", { 0: segments }))
  }
  return pieces.join(' · ')
}

type SubAgentEventKind = '' | 'created' | 'enabled' | 'closed' | 'message_sent' | 'message_received'

function subAgentEventKind(part: MessagePart): SubAgentEventKind {
  const toolName = String(part.toolName || part.label || '').trim().toLowerCase()
  if (toolName === 'sub_agent_receive') return 'message_received'
  if (toolName === 'sub_agent_message') return 'message_sent'
  if (toolName !== 'sub_agent' && toolName !== 'subagent') return ''
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const result = metadataRecord(meta.metadata)
  const action = String(args.action || result.action || meta.action || '').toLowerCase()
  const lifecycle = String(
    result.lifecycle_action
    || result.lifecycleAction
    || meta.lifecycle_action
    || meta.lifecycleAction
    || '',
  ).toLowerCase()
  if (action === 'close' || lifecycle === 'closed') return 'closed'
  if (action !== 'create') return ''
  return lifecycle === 'enabled' || lifecycle === 'reopened' ? 'enabled' : 'created'
}

function subAgentEventTitle(part: MessagePart): string {
  const kind = subAgentEventKind(part)
  if (!kind) return ''
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const result = metadataRecord(meta.metadata)
  const name = compactDetail(String(args.name || result.name || meta.name || 'Sub Agent').trim(), 64)
  const state = part.status
  const isPending = state === 'pending'
  const isRunning = state === 'running'
  const isError = state === 'error'
  const statePrefix = isRunning ? t("正在") : isPending ? t("等待") : ''
  if (kind === 'closed') {
    if (isError) return t("关闭 {0} 失败", { 0: name })
    if (isRunning || isPending) return t("{0}关闭 {1}", { 0: statePrefix, 1: name })
    return t("关闭了 {0}", { 0: name })
  }
  if (kind === 'message_sent') {
    if (isError) return t("向 {0} 发送消息失败", { 0: name })
    if (isRunning || isPending) return t("{0}向 {1} 发送消息", { 0: statePrefix, 1: name })
    return t("向 {0} 发送了消息", { 0: name })
  }
  if (kind === 'message_received') {
    if (isError) return t("接收 {0} 消息失败", { 0: name })
    if (isRunning || isPending) return t("{0}接收 {1} 的消息", { 0: statePrefix, 1: name })
    return t("收到了 {0} 的消息", { 0: name })
  }
  const model = compactDetail(String(result.model_id || result.model || args.model || '').trim(), 40)
  const reasoning = compactDetail(String(result.reasoning_level || result.reasoningLevel || args.reasoning_level || '').trim(), 24)
  const config = [model, reasoning].filter(Boolean).join(' ')
  const verb = kind === 'enabled' ? t("启用") : t("创建")
  if (isError) return t("{0} {1} 失败{2}", { 0: verb, 1: name, 2: config ? ` · ${config}` : '' })
  if (isRunning || isPending) return `${statePrefix}${verb} ${name}${config ? ` · ${config}` : ''}`
  return t("{0} {1}{2}", { 0: kind === 'enabled' ? t("启用了") : t("创建了"), 1: name, 2: config ? ` · ${config}` : '' })
}

function compactTokenCount(value: unknown): string {
  const tokens = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(tokens) || tokens < 0) return ''
  const compact = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(tokens / 1000)
  return `${compact}k`
}

function compactionStatus(part: MessagePart): string {
  const metadata = part.metadata || {}
  const rawPart = part as unknown as Record<string, unknown>
  const explicit = String(rawPart.compaction_status || rawPart.compactionStatus || metadata.compaction_status || metadata.compactionStatus || '').trim()
  if (explicit === 'skipped') return 'not_needed'
  if (explicit === 'cancelled' || explicit === 'error') return 'failed'
  if (explicit) return explicit
  if (part.status === 'running' || part.status === 'pending') return 'running'
  if (part.status === 'error') return 'failed'
  return 'compacted'
}

function isRunningCompaction(part: MessagePart): boolean {
  return compactionStatus(part) === 'running'
}

function hasCompactionSummary(part: MessagePart): boolean {
  return Boolean(String(part.content || '').trim())
}

function canToggleCompaction(part: MessagePart): boolean {
  return compactionStatus(part) === 'compacted' && hasCompactionSummary(part)
}

function isCompactionExpanded(part: MessagePart): boolean {
  return isRunningCompaction(part) ? hasCompactionSummary(part) : isToolExpanded(part.id)
}

function shouldShowCompactionSummary(part: MessagePart): boolean {
  return hasCompactionSummary(part) && isCompactionExpanded(part)
}

function compactionTitle(part: MessagePart): string {
  const label = String(part.label || '').trim()
  if (label && label.toLowerCase() !== 'compaction') return label
  const status = compactionStatus(part)
  if (status === 'running') return t("正在压缩上下文")
  if (status === 'not_needed') return t("无需压缩")
  if (status === 'failed') return t("压缩未完成")
  return t("上下文已压缩")
}

function compactionPreview(part: MessagePart): string {
  return String(part.content || '').trim()
}

function displayToolResult(part: MessagePart): string {
  const artifactText = fileArtifactContent(part)
  if (artifactText && isUsableFileArtifact(part, artifactText)) return artifactText
  const editDiff = editArgsAsDiff(part)
  if (editDiff) return editDiff
  if (displayToolInputPreview(part)) return ''
  if (part.status === 'running' && !part.toolResult) return ''
  const raw = sanitizeUnavailableToolText(String(part.toolResult || (isWriteTool(part) ? part.detail || part.content || '' : ''))).trim()
  if (!raw) return ''
  return formatWritePreviewAsDiff(part, raw)
}

function isUsableFileArtifact(part: MessagePart, content: string): boolean {
  const name = String(part.toolName || part.label || '').toLowerCase()
  if (!name.includes('edit_file')) return true
  return /^---\s+.+\n\+\+\+\s+.+\n@@\s+-\d/m.test(content)
}

function editArgsAsDiff(part: MessagePart): string {
  const name = String(part.toolName || part.label || '').toLowerCase()
  if (!name.includes('edit_file') || part.status === 'running') return ''
  const args = part.toolArgs || {}
  const oldText = args.old_string ?? args.old_text
  const newText = args.new_string ?? args.new_text
  if (typeof oldText !== 'string' || typeof newText !== 'string') return ''

  const path = String(args.path || args.file || args.file_path || 'file')
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')
  return [
    `--- a/${path}`,
    `+++ b/${path}`,
    `@@ -1,${oldLines.length} +1,${newLines.length} @@`,
    ...oldLines.map(line => `-${line}`),
    ...newLines.map(line => `+${line}`),
  ].join('\n')
}

function isCommandTool(part: MessagePart): boolean {
  const name = String(part.toolName || part.label || '').toLowerCase()
  return part.partType === 'command_output' || /command|shell|exec|bash|powershell|run_command/.test(name)
}

function commandDisplayText(part: MessagePart): string {
  const args = part.toolArgs || {}
  const direct = args.command || args.cmd
  if (direct) return String(direct)
  const meta = splitToolOutput(displayToolResult(part) || readableProcessDetail(part)).meta
  const commandMeta = meta.split(' · ').find(item => item.trim().startsWith('命令 '))
  if (commandMeta) return commandMeta.replace(/^命令\s*/, '').trim()
  return readableProcessTitle(part)
}

function commandOutputText(part: MessagePart): string {
  const output = splitToolOutput(displayToolResult(part) || readableProcessDetail(part)).content.trim()
  return output || '[no output]'
}

function displayToolError(part: MessagePart): string {
  return sanitizeUnavailableToolText(String(part.toolError || '')).trim()
}

function displayToolInputPreview(part: MessagePart): string {
  if (part.status !== 'running') return ''
  return String(part.inputPreview?.content || '')
}

function toolInputPreviewMeta(part: MessagePart): string {
  const preview = part.inputPreview
  if (!preview) return t("生成工具输入")
  const field = preview.field ? t("生成 {0}", { 0: preview.field }) : t("生成工具输入")
  const chars = Number.isFinite(preview.chars) ? `${preview.chars} chars` : ''
  const truncated = preview.truncated ? t("已截断") : ''
  return [field, chars, truncated].filter(Boolean).join(' · ')
}

function toolOutputContent(part: MessagePart): string {
  const text = displayToolResult(part) || readableProcessDetail(part)
  return splitToolOutput(text).content
}

function toolMetaText(part: MessagePart): string {
  const text = displayToolResult(part) || readableProcessDetail(part)
  const meta = splitToolOutput(text).meta
  const artifactMeta = fileArtifactMetaText(part)
  const argsMeta = part.toolArgs ? toolArgsPreview(part.toolArgs) : ''
  return [argsMeta, artifactMeta, meta].filter(Boolean).join(' · ')
}

function toolMetaItems(part: MessagePart): string[] {
  return toolMetaText(part).split(' · ').map(item => item.trim()).filter(Boolean)
}

function fileArtifact(part: MessagePart) {
  return part.artifacts?.find(artifact => artifact.kind === 'file_change' || artifact.kind === 'file_read')
}

const IMAGE_URI_RE = /\.(png|jpe?g|webp|gif)$/i

/**
 * 后端只在大图超过内联上限时、且在发送那一刻把内联正文换成引用：这类条目带
 * `availability: "reference"`，metadata 里的 data URL 键已被丢掉，正文要按需从
 * path/uri 取（durable 副本未变，取不到不等于内容丢了）。
 */
function isArtifactReference(artifact: { availability?: string } | null | undefined): boolean {
  return String(artifact?.availability || '').trim().toLowerCase() === 'reference'
}

/** 内联正文（data URL）的唯一判定入口：引用条目一律没有，也不该再当图片源用。 */
function inlineImageDataUrl(
  artifact: { availability?: string; metadata?: Record<string, unknown> } | null | undefined,
): string {
  if (isArtifactReference(artifact)) return ''
  const dataUrl = artifact?.metadata?.image_data_url
  return typeof dataUrl === 'string' && dataUrl.startsWith('data:image') ? dataUrl : ''
}

function isImageArtifact(
  artifact: ToolArtifact,
): artifact is ToolArtifact & { artifact_id?: string } {
  return artifact.kind === 'image'
    || (typeof artifact.uri === 'string' && IMAGE_URI_RE.test(artifact.uri))
    || Boolean(inlineImageDataUrl(artifact))
    // 引用条目不再带内联正文：真实 MIME 类型是"这是图片"的另一条依据。
    || (typeof artifact.mime_type === 'string' && artifact.mime_type.toLowerCase().startsWith('image/'))
}

function imageArtifacts(part: MessagePart): Array<ToolArtifact & { artifact_id?: string }> {
  return (part.artifacts || []).filter(isImageArtifact)
}

const artifactUrls = reactive<Record<string, string>>({})
/** 按需取字节失败过的条目：界面据此显示取不到的提示与重试，而不是破图。 */
const artifactLoadFailed = reactive<Record<string, boolean>>({})

function artifactKey(artifact: {
  uri?: string
  path?: string
  artifact_id?: string
  availability?: string
  metadata?: Record<string, unknown>
}): string {
  return String(
    artifact.artifact_id
    || artifact.uri
    || artifact.path
    || artifact.metadata?.path
    || inlineImageDataUrl(artifact)
    || '',
  )
}

function artifactLoadFailedFor(artifact: Parameters<typeof artifactKey>[0]): boolean {
  const key = artifactKey(artifact)
  return Boolean(key) && artifactLoadFailed[key] === true
}

/** 占位卡上的体积说明：字节还没取回时就先告诉用户这是多大的东西。 */
function artifactSizeLabel(artifact: {
  size_bytes?: unknown
  metadata?: Record<string, unknown>
}): string {
  const raw = Number(
    artifact.size_bytes
    ?? artifact.metadata?.size_bytes
    ?? artifact.metadata?.new_size_bytes
    ?? 0,
  )
  if (!Number.isFinite(raw) || raw <= 0) return ''
  if (raw < 1024) return `${Math.round(raw)} B`
  const kb = raw / 1024
  if (kb < 1024) return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)} KB`
  const mb = kb / 1024
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`
}

function compactionIconStateClass(part: MessagePart): string {
  return `process-card-state-icon--${compactionStatus(part)}`
}

function compactionAccessibleLabel(part: MessagePart): string {
  const detail = compactionDetail(part)
  return detail ? `${compactionTitle(part)}，${detail}` : compactionTitle(part)
}

function artifactPath(artifact: { uri?: string; artifact_id?: string; metadata?: Record<string, unknown> }): string {
  let path = typeof artifact.uri === 'string' && artifact.uri
    ? artifact.uri
    : (typeof (artifact as { path?: string }).path === 'string' ? String((artifact as { path?: string }).path) : '')
  if (props.projectId && artifact.artifact_id) {
    const query = path ? `?path=${encodeURIComponent(path)}` : ''
    return `/projects/${encodeURIComponent(props.projectId)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/file${query}`
  }
  if (path.startsWith('attachment://')) {
    return `/attachments/${encodeURIComponent(path.slice('attachment://'.length))}/download`
  }
  if (props.projectId && path.startsWith('workspace://')) path = path.slice('workspace://'.length)
  if (props.projectId && path) {
    return `/projects/${encodeURIComponent(props.projectId)}/files/raw?path=${encodeURIComponent(path)}`
  }
  return ''
}

function imageSrc(artifact: { uri?: string; path?: string; artifact_id?: string; availability?: string; metadata?: Record<string, unknown> }): string {
  // read_file 图片结果：只有内联的 base64 data URL 才直接内联渲染；被换成引用的
  // 条目没有内联正文，落到下面的按需取字节（path/uri → 本地文件或 HTTP）。
  const dataUrl = inlineImageDataUrl(artifact)
  if (dataUrl) return dataUrl
  let path = typeof artifact.uri === 'string' ? artifact.uri : (artifact.path || '')
  if (path.startsWith('workspace://')) path = path.slice('workspace://'.length)
  // Tauri 桌面端：work_root 内相对路径（.lam/artifacts/...）直接读本地文件
  // （asset protocol），不绕后端 HTTP——新旧消息的 uri 均为无前缀相对路径
  const localFileSrc = (window as { __LAMTOOLS_FILE_SRC__?: (abs: string) => string }).__LAMTOOLS_FILE_SRC__
  const relative = workspaceRelativePath(path)
  if (
    typeof localFileSrc === 'function'
    && props.workRoot
    && relative
    && !relative.startsWith('attachment://')
    && !/^https?:\/\//i.test(relative)
  ) {
    const abs = `${String(props.workRoot).replace(/\\+$/, '')}\\${relative.replace(/\//g, '\\')}`
    const src = localFileSrc(abs)
    if (src) return src
  }
  return artifactUrls[artifactKey(artifact)] || ''
}

function imageAlt(artifact: { name?: string; uri?: string }): string {
  return artifact.name || (typeof artifact.uri === 'string' ? artifact.uri.split('/').pop() || t("生成图片") : t("生成图片"))
}

const previewImageSrc = ref('')
const previewImageAlt = ref('')
const imagePreviewOverlayEl = ref<HTMLElement | null>(null)
const imagePreviewEl = ref<HTMLElement | null>(null)

useOutsidePointerDismiss({
  overlay: imagePreviewOverlayEl,
  card: imagePreviewEl,
  isActive: () => Boolean(previewImageSrc.value),
  onDismiss: () => { previewImageSrc.value = '' },
})

/** Artifact 面板的位置固定在最终答案之后；只有显式的父级抑制才会隐藏它。 */
const artifactsPanelSuppressed = computed(() => {
  return props.suppressArtifactsPanel === true
})

/**
 * 汇报文本里点到、且经查真实存在的文件（2026-10-12 用户口径：不限于本回合写出的
 * 那些）。存在性靠工作区文件接口问一次；查不到、或路径越出工作区，都不进产物区，
 * 也不凭空造卡片。每个引用只问一次，失败的下次重算再试。
 */
const reportPathStates = ref<Record<string, 'exists' | 'missing'>>({})
const reportPathChecks = new Set<string>()

async function verifyReportPaths(): Promise<void> {
  const projectId = props.projectId
  if (!projectId || isLiveMessage(props.msg)) return
  const text = answerContent(props.msg)
  if (!text) return
  const references = artifactPathsInText(text)
    .map(value => workspaceRelativeFromReportPath(value, props.workRoot))
    .filter(Boolean)
    .slice(0, 24)
  for (const reference of references) {
    if (reference in reportPathStates.value || reportPathChecks.has(reference)) continue
    reportPathChecks.add(reference)
    try {
      const response = await props.transport.request<TransportHttpResponse>({
        kind: 'http',
        method: 'GET',
        path: `/projects/${encodeURIComponent(projectId)}/files/content?path=${encodeURIComponent(reference)}`,
      })
      const exists = response.status >= 200 && response.status < 300
      reportPathStates.value = { ...reportPathStates.value, [reference]: exists ? 'exists' : 'missing' }
    } catch {
      // 网络/传输失败不算"不存在"：放掉这次，下次内容变化时再问。
      reportPathChecks.delete(reference)
    }
  }
}

watch(
  () => [props.msg.id, isLiveMessage(props.msg), props.msg.content, props.workRoot, props.projectId] as const,
  () => { void verifyReportPaths() },
  { immediate: true },
)

const messageArtifacts = computed<Array<ToolArtifact & { artifact_id?: string }>>(() => {
  const raw: Array<ToolArtifact & { artifact_id?: string }> = []
  for (const part of props.msg.parts || []) collectOutputArtifacts(part, raw)
  // 本轮产出只收三类（用户规则 2026-10-12）：本回合被收进资料库的文件、汇报文本里
  // 以相对或绝对路径点到且真实存在的文件、以及本回合写出且被点到/入库的文件。
  // 生成图片不套这些规则。
  const libraryPaths = collectLibraryFiledPaths(props.msg.parts || [])
  const reportText = answerContent(props.msg)
  const listed = raw.filter(artifact => shouldListTurnArtifact(artifact, {
    reportText,
    libraryPaths,
    workRoot: props.workRoot,
  }))
  const referenced = new Set(listed.map(artifact => artifactListingReference(artifact)).filter(Boolean))
  for (const [reference, state] of Object.entries(reportPathStates.value)) {
    if (state !== 'exists' || referenced.has(reference)) continue
    listed.push({ kind: 'file_change', uri: reference, path: reference, metadata: { path: reference } })
  }
  // 归一化键去重：artifact_id → uri → path。同一文件在多个 part 重复出现时只保留
  // 一项，同一 uri 优先保留带 artifact_id 的权威条目。内联 data URL 不是身份——
  // 大图被换成引用后它就不存在了，键必须仍然成立（否则同一张图会画两遍，或者两张
  // 不同的图并成一项）。
  const seen = new Map<string, ToolArtifact & { artifact_id?: string }>()
  for (const artifact of listed) {
    const idKey = artifact.artifact_id || ''
    const uriKey = typeof artifact.uri === 'string' ? artifact.uri : ''
    const pathKey = typeof artifact.path === 'string' && artifact.path
      ? artifact.path
      : String(artifact.metadata?.path || '')
    // 内联正文只作最后的兜底身份（老的 base64 图没有 id/uri）：引用条目没有它，
    // 身份就落在标识符或 uri/path 上。
    const lookupKey = uriKey || pathKey || inlineImageDataUrl(artifact)
    if (idKey) {
      const prevById = [...seen.values()].find(a => a.artifact_id === idKey)
      if (prevById) continue
      if (lookupKey && seen.has(lookupKey)) {
        const prev = seen.get(lookupKey)
        if (!prev || prev.artifact_id) continue
        seen.delete(lookupKey) // 无 id 的同 uri 条目让位给带 id 的
      }
      seen.set(lookupKey || idKey, artifact)
    } else if (lookupKey) {
      if (seen.has(lookupKey)) continue
      seen.set(lookupKey, artifact)
    } else {
      // 无任何可归一化键（极罕见）：直接保留，避免丢图
      seen.set(`no-key-${seen.size}`, artifact)
    }
  }
  // 同一文件的相对/绝对两种写法（正反斜杠）合并成一项：引用归一后同名只留一次，
  // 带 artifact_id 的权威条目优先（都不带 id 时保留先出现的），顺序保持原样。
  const merged: Array<ToolArtifact & { artifact_id?: string }> = []
  const referenceIndexes = new Map<string, number>()
  for (const artifact of seen.values()) {
    const reference = artifactListingReference(artifact)
    const index = reference ? referenceIndexes.get(reference) : undefined
    if (index === undefined) {
      if (reference) referenceIndexes.set(reference, merged.length)
      merged.push(artifact)
      continue
    }
    const prev = merged[index]
    if (!prev.artifact_id && artifact.artifact_id) merged[index] = artifact
  }
  return merged
})

async function loadArtifactSource(
  artifact: { uri?: string; path?: string; artifact_id?: string; availability?: string; metadata?: Record<string, unknown> },
  force = false,
): Promise<boolean> {
  const key = artifactKey(artifact)
  if (!key) return false
  if (!force && artifactUrls[key]) return true
  // 内联正文在手：没有任何字节要取。
  if (inlineImageDataUrl(artifact)) return true
  const path = artifactPath(artifact)
  if (!path) {
    artifactLoadFailed[key] = true
    return false
  }
  try {
    const response = await props.transport.request<TransportHttpResponse>({ kind: 'http', method: 'GET', path })
    if (response.status < 200 || response.status >= 300) {
      artifactLoadFailed[key] = true
      return false
    }
    artifactUrls[key] = URL.createObjectURL(new Blob([Uint8Array.from(response.body)], {
      type: response.headers['content-type'] || 'application/octet-stream',
    }))
    artifactLoadFailed[key] = false
    return true
  } catch {
    // 取不到不等于内容丢了：durable 副本仍在，这里只标记失败让界面给出重试。
    artifactLoadFailed[key] = true
    return false
  }
}

/** 引用条目的重试入口：清掉失败标记后强制再取一次。 */
function retryArtifactSource(artifact: Parameters<typeof loadArtifactSource>[0]): void {
  const key = artifactKey(artifact)
  if (key) artifactLoadFailed[key] = false
  void loadArtifactSource(artifact, true)
}

// 图片按需取字节：进入视口（或所在过程卡被展开后）才去取，不再在消息变化时把整条
// 消息的图片一次性拉一遍。没有 IntersectionObserver 的环境（测试/老宿主）退回立即取。
const pendingImageLoads = new Map<Element, ToolArtifact & { artifact_id?: string }>()
let imageObserver: IntersectionObserver | null = null

function registerImageCard(
  element: Element | { $el?: Element } | null | undefined,
  artifact: ToolArtifact & { artifact_id?: string },
): void {
  const target = element instanceof Element ? element : element?.$el
  if (!target) return
  if (typeof IntersectionObserver === 'undefined') {
    void loadArtifactSource(artifact)
    return
  }
  if (!imageObserver) {
    imageObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const observed = entry.target
        imageObserver?.unobserve(observed)
        const pending = pendingImageLoads.get(observed)
        pendingImageLoads.delete(observed)
        if (pending) void loadArtifactSource(pending)
      }
    }, { rootMargin: '240px' })
  }
  pendingImageLoads.set(target, artifact)
  imageObserver.observe(target)
}

function collectOutputArtifacts(
  part: MessagePart,
  out: Array<ToolArtifact & { artifact_id?: string }>,
): void {
  for (const artifact of part.artifacts || []) {
    // The contextual deck is for generated images and file changes only.
    // Command/file-read evidence belongs to the process timeline, not to the
    // message-local成果 deck, even when an old snapshot carries an image URI.
    if (artifact.kind === 'file_read' || artifact.kind === 'command_output') continue
    if (artifact.kind === 'file_change' || isImageArtifact(artifact)) out.push(artifact)
  }
  const subLineParts = (part.metadata as { subLineParts?: MessagePart[] } | undefined)?.subLineParts
  if (Array.isArray(subLineParts)) {
    for (const sub of subLineParts) collectOutputArtifacts(sub, out)
  }
}

/**
 * 本回合经资料库工具登记的文件：工具结果的元数据带 artifact_id + path
 * （register 动作独有；list/favorite/folder/remove/restore 都不是这个形状）。
 * 投影把工具结果元数据提升到部件元数据上，这里把两种落位都读一遍。
 */
function collectLibraryFiledPaths(parts: MessagePart[]): Set<string> {
  const paths = new Set<string>()
  const visit = (list: MessagePart[]): void => {
    for (const part of list) {
      if (part.toolName === 'library') {
        const metadata = (part.metadata || {}) as Record<string, unknown>
        const nested = typeof metadata.metadata === 'object' && metadata.metadata
          ? metadata.metadata as Record<string, unknown>
          : (metadata.payload as { metadata?: unknown } | undefined)?.metadata as Record<string, unknown> | undefined
        if (nested && typeof nested.artifact_id === 'string' && typeof nested.path === 'string') {
          const reference = normalizeArtifactReference(nested.path)
          if (reference) paths.add(reference)
        }
      }
      const subLineParts = (part.metadata as { subLineParts?: MessagePart[] } | undefined)?.subLineParts
      if (Array.isArray(subLineParts)) visit(subLineParts)
    }
  }
  visit(parts)
  return paths
}

// 之前这里在消息变化时把整条消息的图片一次性取一遍；被换成引用的图片按需取
// （见 registerImageCard），这条广播不再需要。
onBeforeUnmount(() => {
  imageObserver?.disconnect()
  imageObserver = null
  pendingImageLoads.clear()
  for (const url of Object.values(artifactUrls)) URL.revokeObjectURL(url)
})

async function openImagePreview(artifact: NonNullable<MessagePart['artifacts']>[number]): Promise<void> {
  await loadArtifactSource(artifact)
  // 取不到就不打开：预览层只显示已经拿到的字节，不给破图。
  previewImageSrc.value = imageSrc(artifact)
  previewImageAlt.value = imageAlt(artifact)
}

function fileArtifactContent(part: MessagePart): string {
  const artifact = fileArtifact(part)
  return typeof artifact?.content === 'string' ? artifact.content.trim() : ''
}

function fileArtifactMetaText(part: MessagePart): string {
  const artifact = fileArtifact(part)
  const meta = artifact?.metadata || {}
  const segments: string[] = []
  const action = String(meta.action || '')
  if (action === 'create') segments.push(t("新增"))
  else if (action === 'overwrite') segments.push(t("覆盖"))
  else if (action === 'edit') segments.push(t("编辑"))
  const lineCount = meta.line_count ?? meta.new_line_count
  if (typeof lineCount === 'number') segments.push(t("{0} 行", { 0: lineCount }))
  if (typeof meta.size_bytes === 'number') segments.push(`${meta.size_bytes} B`)
  if (meta.truncated === true) segments.push(t("已截断"))
  return segments.join(' · ')
}

function testArtifact(part: MessagePart) {
  return part.artifacts?.find(artifact => artifact.kind === 'test_result')
}

function testArtifactMetadata(part: MessagePart): Record<string, unknown> {
  return testArtifact(part)?.metadata || {}
}

function testResultClass(part: MessagePart): string {
  const meta = testArtifactMetadata(part)
  return meta.passed === true ? 'test-result-card--passed' : 'test-result-card--failed'
}

function testResultTitle(part: MessagePart): string {
  const meta = testArtifactMetadata(part)
  if (meta.passed === true) return t("测试通过")
  if (meta.summary === 'timed_out') return t("测试超时")
  return t("测试失败")
}

function testResultCommand(part: MessagePart): string {
  const command = testArtifactMetadata(part).command || part.toolArgs?.command || ''
  return command ? compactDetail(String(command), 120) : t("未提供命令")
}

function testResultMeta(part: MessagePart): string[] {
  const meta = testArtifactMetadata(part)
  const items: string[] = []
  if (meta.exit_code !== undefined && meta.exit_code !== null) items.push(t("退出码 {0}", { 0: meta.exit_code }))
  if (typeof meta.duration_seconds === 'number') items.push(t("{0} 秒", { 0: meta.duration_seconds.toFixed(2) }))
  if (meta.timed_out === true) items.push(t("超时"))
  return items
}

function testResultOutput(part: MessagePart): string {
  const artifact = testArtifact(part)
  if (typeof artifact?.content === 'string' && artifact.content.trim()) return artifact.content.trim()
  return toolOutputContent(part)
}

function splitToolOutput(text: string): { content: string; meta: string } {
  const lines = String(text || '').split(/\r?\n/)
  const meta: string[] = []
  const content: string[] = []
  for (const line of lines) {
    const trimmed = line.trim()
    if (/^\[file:\s*.+\]$/i.test(trimmed)) {
      meta.push(formatToolMeta(trimmed.slice(1, -1)))
    } else if (/^\[END OF FILE\b.+\]$/i.test(trimmed)) {
      meta.push(formatToolMeta(trimmed.slice(1, -1)))
    } else if (/^\[(exit_code|duration_seconds|timed_out|command|cwd)\b[:\]\s]/i.test(trimmed)) {
      meta.push(formatToolMeta(bracketMetaPayload(trimmed)))
    } else {
      content.push(line)
    }
  }
  return {
    content: content.join('\n').trim(),
    meta: meta.join(' · '),
  }
}

function bracketMetaPayload(line: string): string {
  const match = line.match(/^\[([^\]]+)\]\s*(.*)$/)
  if (match) return `${match[1]} ${match[2]}`.trim()
  return line.replace(/^\[/, '').replace(/\]$/, '')
}

function formatToolMeta(meta: string): string {
  return meta
    .replace(/^file:\s*/i, t("文件 · "))
    .replace(/^END OF FILE\b\s*[—-]?\s*/i, t("文件结束 · "))
    .replace(/^exit_code[:\]\s]*/i, t("退出码 "))
    .replace(/^duration_seconds[:\]\s]*/i, t("耗时 "))
    .replace(/^timed_out[:\]\s]*/i, t("超时 "))
    .replace(/^command[:\]\s]*/i, t("命令 "))
    .replace(/^cwd[:\]\s]*/i, t("目录 "))
    .replace(/\blines\b/g, t("行"))
    .replace(/\bmodified\b/g, t("修改于"))
    .replace(/\bbytes read successfully\b/g, t("字节读取完成"))
}

function unavailableToolName(part: MessagePart): string {
  const text = String(part.toolError || part.toolResult || part.detail || part.content || '')
  return unavailableToolNameFromText(text)
}

function isUnavailableToolNotice(part: MessagePart): boolean {
  const text = String(part.toolError || part.toolResult || part.detail || part.content || '')
  return /当前环境没有这个工具|工具\s+.+?\s+不可用|工具不可用|tool .*not available/i.test(text)
}

function unavailableToolNameFromText(text: string): string {
  const rawMatch = text.match(/^\s*\[?Tool ['"]([^'"]+)['"] is not available/i)
  if (rawMatch?.[1]) return rawMatch[1]
  const zhMatch = text.match(/工具\s+([^\s，。:：]+)\s+不可用/)
  return zhMatch?.[1] || ''
}

function sanitizeUnavailableToolText(text: string): string {
  const name = unavailableToolNameFromText(text)
  if (!name) return text
  return unavailableToolMessage(name)
}

function unavailableToolMessage(name: string): string {
  return t("工具 {0} 不可用：请求了当前环境没有注册的工具。", { 0: name })
}

function isWriteTool(part: MessagePart): boolean {
  const name = (part.toolName || part.label || '').toLowerCase()
  return /write|edit|patch|create|apply|delete/.test(name)
}

function formatWritePreviewAsDiff(part: MessagePart, text: string): string {
  if (!isWriteTool(part)) return text
  if (/^(diff --git|--- (?:a\/|\/dev\/null)|\+\+\+ (?:b\/|\/dev\/null)|@@ )/m.test(text)) return text

  const match = text.match(/^(?:Created|Updated|Wrote)\s+(.+?):[\s\S]*?--- preview ---\s*([\s\S]*?)\s*--- end preview ---/i)
  const simpleCreated = text.match(/^\+\s*Created:\s*(.+?)\s*\([^)]*\)\s*\n+([\s\S]*)$/i)
  if (!match && !simpleCreated) return text

  const args = part.toolArgs || {}
  const path = String(args.path || args.file || args.file_path || match?.[1] || simpleCreated?.[1] || 'file')
  const preview = match?.[2] || simpleCreated?.[2] || ''
  const added = preview
    .split(/\r?\n/)
    .map(line => line.replace(/^\s*\d+\s*\|\s?/, ''))
    .filter(line => line.length > 0)

  return [
    `+++ b/${path}`,
    `@@ -0,0 +1,${Math.max(added.length, 1)} @@`,
    ...added.map(line => `+${line}`),
  ].join('\n')
}

function agentDisplayName(name: string): string {
  const cleanName = name
    .trim()
    .replace(/^(agent[:：]\s*)+/i, '')
    .replace(/^completed[:：]\s*/i, '')
    .trim()
  const normalized = cleanName.toLowerCase()
  if (!normalized) return ''
  if (normalized === 'sub_agent' || normalized === 'subagent') return 'sub'
  return compactDetail(cleanName, 40)
}

function agentIndexLabel(part: MessagePart): string {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  return String(meta.agent_index || meta.agentIndex || args.agent_index || args.agentIndex || '').trim()
}

function agentToolLabel(name: string): string {
  return compactDetail(name.trim(), 40)
}

function agentTitle(part: MessagePart): string {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const name = meta.agent || meta.agent_name || args.agent || args.agent_name || args.name || part.label
  const display = agentDisplayName(String(name || ''))
  const index = agentIndexLabel(part)
  const agentName = display || (index ? `${index} · sub` : 'sub')
  const type = agentTypeLabel(part)
  const model = agentModelLabel(part)
  const reasoning = agentReasoningLabel(part)
  const elapsed = agentElapsedLabel(part)
  // Keep this format stable: the right rail and message block use the same
  // compact lifecycle grammar so users can scan type, identity, model,
  // reasoning and duration in one pass.
  return `${type} ${agentName} · ${model} ${reasoning} · ${elapsed}`
}

function agentTypeLabel(part: MessagePart): 'consider' | 'execute' {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  return normalizeSubAgentType(
    part.agentType
    || (part as MessagePart & { type?: unknown }).type
    || meta.type
    || meta.agent_type
    || meta.agentType
    || meta.mode
    || meta.active_mode
    || args.type
    || args.mode
    || '',
  )
}

function agentModelLabel(part: MessagePart): string {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const value = part.model
    || (part as MessagePart & { modelId?: unknown }).modelId
    || meta.model
    || meta.model_id
    || meta.modelId
    || args.model
    || args.model_id
    || args.modelId
  return compactDetail(String(value || '—').trim() || '—', 40)
}

function agentReasoningLabel(part: MessagePart): string {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const value = part.reasoningLevel
    || meta.reasoning_level
    || meta.reasoningLevel
    || meta.reasoning_effort
    || meta.reasoningEffort
    || args.reasoning_level
    || args.reasoningLevel
    || args.reasoning_effort
  return compactDetail(String(value || '—').trim() || '—', 24)
}

function agentElapsedLabel(part: MessagePart): string {
  const meta = part.metadata || {}
  const explicit = part.elapsedMs
    ?? numberValue(meta.elapsedMs)
    ?? numberValue(meta.elapsed_ms)
    ?? numberValue(meta.durationMs)
    ?? numberValue(meta.duration_ms)
  let elapsed = explicit
  if (elapsed === undefined) {
    const start = Date.parse(String(part.startedAt || meta.startedAt || meta.started_at || ''))
    const endValue = part.completedAt || meta.completedAt || meta.completed_at
    const end = endValue
      ? Date.parse(String(endValue))
      : subAgentTitleNow.value
    elapsed = Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, end - start) : 0
  }
  return formatSubAgentElapsed(elapsed)
}

function numberValue(value: unknown): number | undefined {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function agentStatusLabel(part: MessagePart): string {
  if (part.status === 'running') return t("运行中")
  if (part.status === 'error') return t("失败")
  if (part.status === 'pending') return t("等待")
  return t("完成")
}

function agentDeliveryMeta(part: MessagePart): string[] {
  const meta = part.metadata || {}
  const diagnostics = metadataRecord(meta.diagnostics)
  const delivery = metadataRecord(diagnostics.workspace_delivery || meta.workspace_delivery || meta.workspaceDelivery)
  const items: string[] = []
  if (delivery.ok === false) items.push(t("失败"))
  else if (delivery.ok === true || delivery.needs_acceptance === true || delivery.merged === true) items.push(t("完成"))
  const branch = String(delivery.branch || meta.branch || '').trim()
  if (branch) items.push(t("分支 {0}", { 0: compactDetail(branch, 36) }))
  const paths = Array.isArray(delivery.paths) ? delivery.paths : []
  if (paths.length > 0) items.push(t("{0} 个文件", { 0: paths.length }))
  return items
}

function metadataRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as Record<string, unknown>
}

function agentAssignmentText(part: MessagePart): string {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const task = args.task || args.task_description || args.description || meta.task
  const text = task ? String(task).trim() : ''
  if (/^你是一个.+?(Explorer|Worker|Reviewer|子代理|SubAgent)/i.test(text)) return ''
  return text
}

function agentTimelineItems(part: MessagePart): AgentTimelineItem[] {
  const meta = part.metadata || {}
  const items: AgentTimelineItem[] = []
  const winner = meta.winner_name || meta.architecture_agent_winner
  const valid = meta.valid_design
  for (const [index, block] of agentReasoningItems(part).entries()) {
    items.push({
      id: `reasoning-${index}`,
      get title() { return t("思考") },
      detail: block,
      status: 'completed',
      kind: 'reasoning',
    })
  }
  for (const [index, step] of agentSubsteps(part).entries()) {
    items.push({
      id: `step-${index}`,
      title: step.label || t("执行步骤"),
      detail: step.value,
      status: step.status,
      kind: 'step',
    })
  }
  for (const [index, tool] of agentToolCallItems(part).entries()) {
    items.push({
      id: `tool-${index}`,
      title: tool.title,
      detail: tool.detail,
      status: tool.status,
      kind: 'tool',
    })
  }
  if (winner) {
    items.push({
      id: 'winner',
      title: valid === false ? t("候选结论") : t("结论"),
      detail: compactDetail(String(winner), 120),
      status: valid === false ? 'pending' : 'completed',
      kind: 'conclusion',
    })
  }
  return items
}

function agentTimelineParts(part: MessagePart): MessagePart[] {
  const meta = part.metadata || {}
  const rawParts = meta.subLineParts || meta.sub_line_parts
  if (Array.isArray(rawParts)) {
    return rawParts
      .map((item, index) => normalizeSubLineChildPart(part, item, index))
      .filter((item): item is MessagePart => Boolean(item))
  }
  return agentTimelineItems(part).map((item) => agentTimelineItemToPart(part, item))
}

function normalizeSubLineChildPart(parent: MessagePart, raw: unknown, index: number): MessagePart | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const record = raw as Record<string, unknown>
  const partType = String(record.partType || record.part_type || 'tool_call') as MessagePart['partType']
  return {
    id: String(record.id || `${parent.id}-subline-${index}`),
    partType,
    status: normalizeProcessStatus(String(record.status || 'completed')),
    label: record.label === undefined ? undefined : String(record.label),
    detail: record.detail === undefined ? undefined : String(record.detail),
    content: record.content === undefined ? '' : String(record.content),
    toolName: record.toolName === undefined && record.tool_name === undefined ? undefined : String(record.toolName || record.tool_name),
    toolArgs: normalizeRecord(record.toolArgs || record.tool_args),
    toolResult: record.toolResult === undefined && record.tool_result === undefined ? undefined : String(record.toolResult || record.tool_result),
    toolError: record.toolError === undefined && record.tool_error === undefined ? undefined : String(record.toolError || record.tool_error),
    inputPreview: normalizeToolInputPreview(record.inputPreview || record.input_preview),
    artifacts: Array.isArray(record.artifacts) ? record.artifacts as MessagePart['artifacts'] : undefined,
    metadata: {
      ...(normalizeRecord(record.metadata) || {}),
      parentAgentPartId: parent.id,
    },
    startedAt: record.startedAt === undefined && record.started_at === undefined ? undefined : String(record.startedAt || record.started_at),
    completedAt: record.completedAt === undefined && record.completed_at === undefined ? undefined : String(record.completedAt || record.completed_at),
  }
}

function normalizeRecord(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  return value as Record<string, unknown>
}

function normalizeToolInputPreview(value: unknown): MessagePart['inputPreview'] | undefined {
  const record = normalizeRecord(value)
  if (!record) return undefined
  const field = typeof record.field === 'string' ? record.field : ''
  const content = typeof record.content === 'string' ? record.content : ''
  const chars = typeof record.chars === 'number' ? record.chars : content.length
  if (!field || !content) return undefined
  return {
    field,
    content,
    chars,
    truncated: record.truncated === true,
  }
}

function agentTimelineItemToPart(parent: MessagePart, item: AgentTimelineItem): MessagePart {
  const toolName = item.toolName || agentTimelineToolName(item)
  const toolArgs = item.toolArgs || agentToolArgsFromDetail(item.detail)
  return {
    id: `${parent.id}-agent-${item.id}`,
    partType: item.kind === 'reasoning' ? 'reasoning' : 'tool_result',
    status: normalizeProcessStatus(item.status),
    label: item.title,
    detail: item.detail,
    content: item.detail,
    toolName,
    toolArgs,
    toolResult: item.toolResult ?? item.detail,
    toolError: item.toolError ?? (item.status === 'error' || item.status === 'failed' ? item.detail : undefined),
    artifacts: item.artifacts,
    metadata: {
      ...(parent.metadata || {}),
      ...(item.metadata || {}),
      agentTimelineKind: item.kind,
      parentAgentPartId: parent.id,
    },
  }
}

function agentToolArgsFromDetail(detail: string): Record<string, unknown> | undefined {
  const text = String(detail || '')
  const path = text.match(/(?:^|\s)([A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)+)(?:\s|$|:|·)/)?.[1]
  return path ? { path } : undefined
}

function agentTimelineToolName(item: AgentTimelineItem): string {
  const title = item.title.toLowerCase()
  const detail = item.detail.toLowerCase()
  if (item.kind === 'reasoning') return 'thinking'
  if (item.kind === 'conclusion') return 'summary'
  if (/写|改|创建|write|edit|patch|create/.test(title + detail)) return 'write_file'
  if (/列|找|读|搜索|list|read|grep|search|glob/.test(title + detail)) return 'read_file'
  if (/命令|执行|run|exec|command|shell|powershell/.test(title + detail)) return 'run_command'
  if (/测试|验证|检查|test|verify|check/.test(title + detail)) return 'run_test'
  if (/git|commit|branch|merge/.test(title + detail)) return 'git'
  return 'tool'
}

function normalizeProcessStatus(status: string): MessagePart['status'] {
  if (status === 'failed') return 'error'
  if (status === 'done') return 'completed'
  if (status === 'waiting') return 'pending'
  if (status === 'running' || status === 'pending' || status === 'completed' || status === 'error') return status
  return 'completed'
}

function agentReasoningItems(part: MessagePart): string[] {
  const meta = part.metadata || {}
  const raw = meta.reasoning_blocks || meta.reasoningBlocks
  if (!Array.isArray(raw)) return []
  return raw
    .map(item => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return String(item || '').trim()
      return String((item as Record<string, unknown>).content || '').trim()
    })
    .filter(Boolean)
    .slice(0, 8)
}

function agentToolCallItems(part: MessagePart): AgentTimelineItem[] {
  const meta = part.metadata || {}
  return normalizeAgentToolCalls(meta.tool_calls)
}

function normalizeAgentToolCalls(raw: unknown): AgentTimelineItem[] {
  const toolCalls = Array.isArray(raw) ? raw : []
  return toolCalls
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
    .map((record, index) => {
      const name = String(record.name || record.tool_name || record.toolName || '')
      const status = String(record.status || 'completed')
      const args = normalizeAgentToolArgs(record)
      const output = String(record.output || record.result || record.content || record.summary || '').trim()
      const contentPreview = String(record.content_preview || record.contentPreview || '').trim()
      const error = String(record.error || record.tool_error || record.toolError || '').trim()
      return {
        id: `tool-${index}`,
        title: agentToolLabel(name) || name || t("工具"),
        detail: agentToolDetail(args, error || contentPreview || output),
        status: status === 'rejected' ? 'error' : status,
        kind: 'tool',
        toolName: name,
        toolArgs: args,
        toolResult: contentPreview || output,
        toolError: error || (status === 'rejected' || status === 'error' || status === 'failed' ? contentPreview || output : undefined),
        artifacts: normalizeAgentArtifacts(record.artifacts),
        metadata: normalizeAgentMetadata(record.metadata),
      } satisfies AgentTimelineItem
    })
    .slice(0, 8)
}

function normalizeAgentArtifacts(raw: unknown): MessagePart['artifacts'] {
  if (!Array.isArray(raw)) return undefined
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
    .map(item => ({
      kind: String(item.kind || ''),
      uri: item.uri === undefined ? undefined : String(item.uri),
      content: item.content,
      metadata: normalizeAgentMetadata(item.metadata),
    }))
    .filter(item => item.kind)
}

function normalizeAgentMetadata(raw: unknown): Record<string, unknown> | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  return raw as Record<string, unknown>
}

function normalizeAgentToolArgs(record: Record<string, unknown>): Record<string, unknown> {
  const raw = record.arguments || record.args || record.tool_args || record.toolArgs
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) return raw as Record<string, unknown>
  return {}
}

function agentToolDetail(args: Record<string, unknown>, output: string): string {
  const subject = String(args.path || args.file || args.command || args.query || args.url || '').trim()
  if (subject && output) return `${subject} · ${compactDetail(output, 140)}`
  if (subject) return subject
  if (output) return compactDetail(output, 160)
  const entries = Object.entries(args)
    .filter(([, value]) => value !== undefined && value !== null && String(value).trim())
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${String(value)}`)
  return entries.join(' · ')
}

function agentSubsteps(part: MessagePart): AgentSubstep[] {
  const meta = part.metadata || {}
  const raw = meta.substeps
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
    .map(item => ({
      label: String(item.label || item.title || t("步骤")),
      value: String(item.value || item.summary || item.detail || ''),
      status: String(item.status || 'completed'),
    }))
    .filter(step => step.label || step.value)
    .slice(0, 6)
}

function agentConclusion(part: MessagePart): string {
  const meta = part.metadata || {}
  const finalAnswer = String(meta.final_answer || '').trim()
  if (finalAnswer) return finalAnswer
  if (part.status === 'running') {
    // While the sub-agent runs, part.content only carries the tool-call
    // placeholder projected from the event label (e.g. "sub_agent"), not real
    // output — rendering it flashed a bare "<p>sub_agent</p>" that was later
    // replaced wholesale by the tool_result. Stream the sub-agent's own
    // latest model text instead (child parts carry full accumulated content);
    // fall back to an early tool result, else render nothing.
    const streamed = latestSubLineModelText(part)
    if (streamed) return streamed
    const toolResult = String(part.toolResult || '').trim()
    return toolResult || ''
  }
  const text = String(part.content || part.toolResult || part.detail || '').trim()
  if (!text) return ''
  return text
}

function latestSubLineModelText(part: MessagePart): string {
  const raw = (part.metadata || {}).subLineParts
  if (!Array.isArray(raw)) return ''
  for (let index = raw.length - 1; index >= 0; index -= 1) {
    const item = raw[index] as Record<string, unknown>
    const partType = String(item.partType || item.part_type || '')
    if (partType !== 'model_text' && partType !== 'agentMessage' && partType !== 'text') continue
    const content = String(item.content || '')
    if (content.trim()) return content.trim()
  }
  return ''
}

function controlTitle(part: MessagePart): string {
  const name = (part.toolName || part.label || '').toLowerCase()
  const args = part.toolArgs || {}
  if (name.includes('write_checklist')) {
    const steps = Array.isArray(args.steps) ? args.steps.length : 0
    return steps > 0 ? t("计划：{0} 步", { 0: steps }) : t("计划")
  }
  if (name.includes('update_checklist')) return part.status === 'error' ? t("计划更新失败") : t("更新计划")
  if (name.includes('verify_design')) return part.status === 'error' ? t("验证未通过") : t("验证")
  if (name.includes('decision_point') || name.includes('ask_clarification')) return decisionTitle(part)
  if (name.includes('self_critique')) return t("自检")
  return part.label || t("过程")
}

function isChecklistPart(part: MessagePart): boolean {
  if (isMergedChecklistPart(part)) return false
  const name = (part.toolName || part.label || '').toLowerCase()
  if (!name.includes('write_checklist') && !name.includes('update_checklist')) return false
  return checklistItems(part).length > 0
}

function checklistItems(part: MessagePart): ChecklistItem[] {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const taskPlan = meta.task_plan && typeof meta.task_plan === 'object' && !Array.isArray(meta.task_plan)
    ? meta.task_plan as Record<string, unknown>
    : {}
  const rawSteps = args.steps || meta.plan_steps || taskPlan.steps
  if (Array.isArray(rawSteps)) {
    const items = rawSteps
      .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
      .map((item, index) => {
        const status = String(item.status || (index === 0 ? 'running' : 'pending'))
        const id = String(item.id || `s${index + 1}`)
        const deliverables = Array.isArray(item.deliverables)
          ? item.deliverables.map(value => String(value)).filter(Boolean)
          : []
        const suffix = deliverables.length ? ` -> ${deliverables.join(', ')}` : ''
        return {
          id,
          text: `${id}. ${String(item.description || `Step ${index + 1}`)}${suffix}`,
          status,
          checked: status === 'completed',
        }
      })
    if (items.length > 0) return items
  }
  return parseMarkdownChecklist(part.content || part.detail || part.toolResult || '')
}

function parseMarkdownChecklist(text: string): ChecklistItem[] {
  return String(text || '')
    .split(/\r?\n/)
    .map((line, index) => {
      const match = line.match(/^\s*(?:\d+\.\s*)?-\s+\[([ xX])\]\s+(.+?)\s*$/)
      if (!match) return null
      const checked = match[1].toLowerCase() === 'x'
      return {
        id: `line-${index}`,
        text: match[2],
        status: checked ? 'completed' : 'pending',
        checked,
      }
    })
    .filter((item): item is ChecklistItem => Boolean(item))
}

function isLowValueControlResult(part: MessagePart, result: string): boolean {
  const name = (part.toolName || part.label || '').toLowerCase()
  if (!name.includes('verify_design') || part.status === 'error') return false
  return /验证通过|verification passed|design verified|ok/i.test(result)
}

/** 卡片状态与决策池 lifecycle 一致：待处理 → 处理中 → 完成。 */
function decisionStatusLabel(part: MessagePart): string {
  if (part.status === 'pending') return t("待处理")
  if (part.status === 'running') return t("处理中")
  if (part.status === 'completed') return t("完成")
  if (part.status === 'error') return t("失败")
  return ''
}

function canGuideDecision(part: MessagePart): boolean {
  return part.partType === 'decision' && part.status === 'pending'
}

function decisionGuideDraft(part: MessagePart): string {
  return decisionGuideDrafts.value[part.id] || ''
}

function updateDecisionGuideDraft(part: MessagePart, event: Event): void {
  const target = event.target as HTMLTextAreaElement | null
  decisionGuideDrafts.value = {
    ...decisionGuideDrafts.value,
    [part.id]: target?.value || '',
  }
  autoGrowTextarea(target)
}

function submitDecisionGuide(part: MessagePart): void {
  const response = decisionGuideDraft(part).trim()
  if (!response) return
  emit('decision-select', {
    partId: part.id,
    option: {
      id: 'guide',
      get label() { return t("其他") },
      response: 'guide',
    },
    response,
  })
  decisionGuideDrafts.value = {
    ...decisionGuideDrafts.value,
    [part.id]: '',
  }
  // The cleared field shrinks back to its resting row.
  void nextTick(() => {
    const inputs = rootEl.value?.querySelectorAll<HTMLTextAreaElement>('.decision-guide-input') || []
    for (const input of inputs) {
      if (input.dataset.decisionGuide === part.id) autoGrowTextarea(input)
    }
  })
}

function processTarget(part: MessagePart): string {
  const args = part.toolArgs || {}
  const toolName = String(part.toolName || part.label || '').toLowerCase()
  if (/skill/.test(toolName)) {
    const skillName = args.name || args.skill || args.skill_name
    if (skillName) return String(skillName).trim()
  }
  const raw = args.path || args.file || args.file_path || args.cwd || args.query || args.pattern || args.url
  if (raw) return compactPath(String(raw))
  const command = args.command || args.cmd
  if (command) {
    const extra = Array.isArray(args.args) ? args.args.join(' ') : ''
    return compactDetail(extra ? `${command} ${extra}` : String(command), 96)
  }
  const label = String(part.label || '')
  if (/[\\/]/.test(label)) return compactPath(label)
  return ''
}

function compactPath(path: string): string {
  const normalized = path.replace(/\\/g, '/')
  const parts = normalized.split('/').filter(Boolean)
  if (parts.length <= 3) return normalized
  return `.../${parts.slice(-3).join('/')}`
}

function compactDetail(value: string, limit = 140): string {
  const oneLine = value.replace(/\s+/g, ' ').trim()
  return oneLine.length > limit ? `${oneLine.slice(0, limit)}...` : oneLine
}

/** Extract text parts from parts array (fallback when msg.content is empty) */
function textGroups(parts: MessagePart[]): TextGroup[] {
  const groups: TextGroup[] = []
  let pending = ''
  for (const p of parts) {
    if (p.partType === 'text' || (!p.partType && p.content)) {
      pending += (pending ? '\n' : '') + p.content
    } else {
      const content = pending.trim()
      if (content) groups.push({ content })
      pending = ''
    }
  }
  const content = pending.trim()
  if (content) groups.push({ content })
  return groups
}

const CONTEXT_TOOLS = new Set(['read_file', 'list_dir', 'glob', 'grep', 'search_content', 'search_files', 'read', 'list'])

function groupParts(parts: MessagePart[]): PartGroupProcess[] {
  const groups: PartGroupProcess[] = []
  for (const part of parts) {
    if (part.partType === 'text' || !part.partType) {
      // Text parts are rendered from msg.content — skip here
    } else {
      groups.push({ kind: 'process', part })
    }
  }
  return groups
}

// ── Compact process group summary ──

function groupHasRunningPart(group: PartGroupProcessGroup): boolean {
  return group.parts.some(p => p.status === 'running')
}

function computeProcessGroupSummary(parts: MessagePart[]): string {
  let reasoningSeconds = 0
  let reasoningCount = 0
  let toolCount = 0
  let contextRead = 0
  let contextSearch = 0
  let contextList = 0
  let hasRunning = false
  for (const part of parts) {
    if (part.status === 'running') hasRunning = true
    if (part.partType === 'reasoning') {
      reasoningCount++
      if (part.startedAt && part.completedAt) {
        const start = new Date(part.startedAt).getTime()
        const end = new Date(part.completedAt).getTime()
        if (Number.isFinite(start) && Number.isFinite(end) && end >= start) {
          reasoningSeconds += Math.round((end - start) / 1000)
        }
      }
    } else if (part.partType === 'tool_call' || part.partType === 'tool_result') {
      if (isControlTool(part)) continue
      const name = part.toolName || ''
      if (name === 'read_file' || name === 'read') contextRead++
      else if (name === 'search_content' || name === 'search_files' || name === 'grep' || name === 'glob') contextSearch++
      else if (name === 'list_dir' || name === 'list') contextList++
      else toolCount++
    }
  }

  function buildParts(running: boolean): string[] {
    const parts: string[] = []
    if (running) {
      if (reasoningCount > 0) parts.push(t("思考中…"))
      if (contextRead > 0) parts.push(t("读取了{0}个文件…", { 0: contextRead }))
      if (contextSearch > 0) parts.push(t("搜索了{0}次…", { 0: contextSearch }))
      if (contextList > 0) parts.push(t("浏览了{0}个目录…", { 0: contextList }))
      if (toolCount > 0) parts.push(t("已调用{0}个工具…", { 0: toolCount }))
    } else {
      if (reasoningCount > 0) parts.push(reasoningSeconds > 0 ? t("思考了{0}s", { 0: reasoningSeconds }) : t("思考了一会"))
      if (contextRead > 0) parts.push(t("读取了{0}个文件", { 0: contextRead }))
      if (contextSearch > 0) parts.push(t("搜索了{0}次", { 0: contextSearch }))
      if (contextList > 0) parts.push(t("浏览了{0}个目录", { 0: contextList }))
      if (toolCount > 0) parts.push(t("调用了{0}个工具", { 0: toolCount }))
    }
    return parts
  }

  const summaryParts = buildParts(hasRunning)
  if (summaryParts.length > 0) {
    return summaryParts.join('，')
  }
  return hasRunning ? t("处理中…") : ''
}

function compactGroups(groups: PartGroup[]): PartGroup[] {
  const result: PartGroup[] = []
  let batch: MessagePart[] = []

  function flush() {
    if (batch.length === 0) return
    if (batch.length === 1) {
      result.push({ kind: 'process', part: batch[0] })
    } else {
      result.push({ kind: 'process-group', parts: [...batch], summary: computeProcessGroupSummary(batch) })
    }
    batch = []
  }

  for (const g of groups) {
    if (g.kind === 'process') {
      const pt = g.part.partType
      if (pt === 'reasoning') {
        batch.push(g.part)
      } else if (pt === 'tool_call' || pt === 'tool_result') {
        // Control rows, delegation rows and skill loads keep their own row:
        // folding them into "思考了一会，调用了 N 个工具" hides exactly the
        // moments an operator reads the timeline for.
        if (isControlTool(g.part) || isStandaloneProcessPart(g.part)) {
          flush()
          result.push(g)
        } else {
          batch.push(g.part)
        }
      } else {
        flush()
        result.push(g)
      }
    }
  }
  flush()
  return result
}

// ── Process summary ──

interface ProcessCounts {
  count: number
  text: string
  toolCalls: number
  reasoning: number
  context: number
  compaction: number
  other: number
}

function processSummary(msg: CoreMessage): ProcessCounts {
  const parts = processParts(msg)
  let toolCalls = 0
  let reasoning = 0
  let context = 0
  let compaction = 0
  let other = 0

  for (const p of parts) {
    const name = p.toolName || ''
    if (CONTEXT_TOOLS.has(name)) {
      context++
    } else if (p.partType === 'compaction') {
      compaction++
    } else if (isControlTool(p) || p.partType === 'model_text' || p.partType === 'plan' || p.partType === 'todo_update' || p.partType === 'decision') {
      other++
    } else if (p.partType === 'tool_call' || p.partType === 'tool_result') {
      toolCalls++
    } else if (p.partType === 'reasoning') {
      reasoning++
    } else if (p.partType === 'text' || !p.partType) {
      // text parts rendered from msg.content — skip
    } else {
      other++
    }
  }

  const count = toolCalls + reasoning + context + compaction + other
  const segments = processMetricSegments(msg)
  const text = segments.join(' · ')

  return {
    count,
    text,
    toolCalls,
    reasoning,
    context,
    compaction,
    other,
  }
}

function processMetricSegments(msg: CoreMessage): string[] {
  const start = processStartTimestamp(msg)
  const end = processEndTimestamp(msg)
  let durationMs = processDurationMetric(msg)
  if (durationMs === null && start !== null && end !== null && end >= start) {
    durationMs = end - start
  }
  if (
    durationMs === null
    && start !== null
    && props.turnStatus === 'running'
    && isActiveTurnMessage(msg)
    && !isLiveMessage(msg)
    && processSummaryClockEnabled.value
  ) {
    const now = processSummaryNow.value
    if (now >= start) durationMs = now - start
  }
  return [durationMs !== null ? t("耗时 {0} s", { 0: formatSeconds(durationMs) }) : t("耗时 —")]
}

function processDurationMetric(msg: CoreMessage): number | null {
  const meta = (msg.metadata || {}) as Record<string, unknown>
  const metrics = isRecord(meta.processMetrics)
    ? meta.processMetrics
    : isRecord(meta.runtime_metrics) ? meta.runtime_metrics : {}
  return numberMetric(meta.duration_ms ?? metrics.duration_ms ?? metrics.durationMs)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function processStartTimestamp(msg: CoreMessage): number | null {
  const meta = (msg.metadata || {}) as Record<string, unknown>
  const processMetrics = isRecord(meta.processMetrics) ? meta.processMetrics : {}
  const runtimeMetrics = isRecord(meta.runtime_metrics) ? meta.runtime_metrics : {}
  const message = msg as CoreMessage & Record<string, unknown>
  return firstTimestampMetric(
    meta.started_at, meta.startedAt, meta.start_time, meta.startTime,
    processMetrics.started_at, processMetrics.startedAt, processMetrics.start_time, processMetrics.startTime,
    runtimeMetrics.started_at, runtimeMetrics.startedAt, runtimeMetrics.start_time, runtimeMetrics.startTime,
    message.started_at, message.startedAt, msg.timestamp,
  )
}

function processEndTimestamp(msg: CoreMessage): number | null {
  const meta = (msg.metadata || {}) as Record<string, unknown>
  const processMetrics = isRecord(meta.processMetrics) ? meta.processMetrics : {}
  const runtimeMetrics = isRecord(meta.runtime_metrics) ? meta.runtime_metrics : {}
  const message = msg as CoreMessage & Record<string, unknown>
  return firstTimestampMetric(
    meta.completed_at, meta.completedAt, meta.ended_at, meta.endedAt, meta.finished_at, meta.finishedAt,
    processMetrics.completed_at, processMetrics.completedAt, processMetrics.ended_at, processMetrics.endedAt,
    processMetrics.finished_at, processMetrics.finishedAt,
    runtimeMetrics.completed_at, runtimeMetrics.completedAt, runtimeMetrics.ended_at, runtimeMetrics.endedAt,
    runtimeMetrics.finished_at, runtimeMetrics.finishedAt,
    message.completed_at, message.completedAt, message.ended_at, message.endedAt,
  )
}

function firstTimestampMetric(...values: unknown[]): number | null {
  for (const value of values) {
    const parsed = timestampMetric(value)
    if (parsed !== null) return parsed
  }
  return null
}

function timestampMetric(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    const milliseconds = value < 1_000_000_000_000 ? value * 1000 : value
    return milliseconds > 0 ? milliseconds : null
  }
  if (typeof value !== 'string' || !value.trim()) return null
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

function numberMetric(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed) && parsed >= 0) return parsed
  }
  return null
}

function formatSeconds(ms: number): string {
  if (ms < 0) return 'X'
  if (ms === 0) return '0'
  return String(Math.max(1, Math.round(ms / 1000)))
}

function processBarStatus(msg: CoreMessage): string {
  if (isLiveMessage(msg)) return 'part-dot--running'
  const parts = processParts(msg)
  const hasError = parts.some(p => p.status === 'error')
  if (hasError) return 'part-dot--error'
  if (answerContent(msg)) return 'part-dot--completed'
  const allDone = parts.every(p => p.status === 'completed' || p.status === 'error' || p.partType === 'text')
  if (allDone) return 'part-dot--completed'
  return 'part-dot--running'
}

// ── Context tools ──

interface ContextCounts {
  read: number
  search: number
  list: number
}

function countContextTools(parts: MessagePart[]): ContextCounts {
  const counts: ContextCounts = { read: 0, search: 0, list: 0 }
  for (const p of parts) {
    const name = p.toolName || ''
    if (name === 'read_file' || name === 'read') counts.read++
    else if (name === 'search_content' || name === 'search_files' || name === 'grep' || name === 'glob') counts.search++
    else if (name === 'list_dir' || name === 'list') counts.list++
  }
  return counts
}

function formatContextSummary(c: ContextCounts): string {
  const items: string[] = []
  if (c.read > 0) items.push(`Read ${c.read} file${c.read > 1 ? 's' : ''}`)
  if (c.search > 0) items.push(`Searched ${c.search} ${c.search > 1 ? 'patterns' : 'pattern'}`)
  if (c.list > 0) items.push(`Listed ${c.list} dir${c.list > 1 ? 's' : ''}`)
  return items.join(' · ') || ''
}
</script>

<style>
.mobile-runtime-warning {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-2);
  max-width: 560px;
  margin: var(--space-2) 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid color-mix(in srgb, var(--orange) 35%, transparent);
  border-radius: var(--radius-sm);
  color: var(--theme-main-text);
  background: color-mix(in srgb, var(--orange) 9%, transparent);
  font-size: 12px;
}

.mobile-runtime-warning__label { font-weight: 600; }

.mobile-turn-progress {
  --text: var(--theme-main-text);
  display: grid;
  gap: var(--space-1);
  max-width: 280px;
  margin: var(--space-2) 0;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12px;
}

.mobile-turn-progress__track {
  position: relative;
  display: block;
  height: 4px;
  overflow: hidden;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) 12%, transparent);
}

.mobile-turn-progress__fill {
  position: absolute;
  inset: 0 auto 0 0;
  width: 36%;
  border-radius: inherit;
  background: var(--theme-control-background);
  animation: mobile-turn-progress-sweep 1.4s ease-out infinite alternate;
}

.mobile-turn-progress--completed .mobile-turn-progress__fill,
.mobile-turn-progress--failed .mobile-turn-progress__fill,
.mobile-turn-progress--cancelled .mobile-turn-progress__fill {
  width: 100%;
  animation: none;
}

.mobile-turn-progress--failed .mobile-turn-progress__fill { background: var(--red); }
.mobile-turn-progress--cancelled .mobile-turn-progress__fill { background: var(--orange); }

@keyframes mobile-turn-progress-sweep {
  from { transform: translateX(-100%); }
  to { transform: translateX(280%); }
}

@media (prefers-reduced-motion: reduce) {
  .mobile-turn-progress__fill { animation: none; }
}

/* ── 收起行结果小标记（因地制宜批次一）──
   行尾一枚小字：命令成败/运行时长、文件增删行数、测试结论。
   成功绿、失败红，与任务状态色语义一致；数字走等宽字。
   非命令行是 flex 行，margin-left 推到行尾；命令行是网格行，
   has-flag 扩出第三列（flag 区）承接。 */
.process-tool-flag {
  flex: 0 0 auto;
  margin-left: auto;
  padding-left: 8px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 52%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.4;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.process-tool-flag--good { color: color-mix(in srgb, var(--green) 78%, var(--theme-main-text, #fff) 22%); }
.process-tool-flag--bad { color: color-mix(in srgb, var(--red) 78%, var(--theme-main-text, #fff) 22%); }
.process-tool-flag--stat { display: inline-flex; gap: 5px; padding-left: 8px; }
.process-tool-flag-add { color: color-mix(in srgb, var(--green) 78%, var(--theme-main-text, #fff) 22%); }
.process-tool-flag-del { color: color-mix(in srgb, var(--red) 78%, var(--theme-main-text, #fff) 22%); }
.tool-card-header.has-flag {
  grid-template-columns: auto minmax(0, 1fr) auto;
  grid-template-areas:
    "marker title flag"
    ". args flag";
}
.tool-card-header.has-flag .process-tool-flag {
  grid-area: flag;
  margin-left: 0;
  padding-left: 0;
}

/* 折叠组头的步骤计数：第三列小字，展开后随行列表一并隐藏。 */
.process-group-count {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 45%, transparent);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* ── 搜索命中清单与网页获取的专属形态（因地制宜批次二）── */
.search-hit-list {
  display: grid;
  gap: 1px;
  padding: 2px 0 6px;
}
.search-hit-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  padding: 2px 6px;
  font-size: 12px;
  line-height: 1.45;
}
.search-hit-loc {
  flex: 0 1 auto;
  display: inline-flex;
  min-width: 0;
  overflow: hidden;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: nowrap;
}
.search-hit-file { overflow: hidden; text-overflow: ellipsis; }
.search-hit-line { flex: 0 0 auto; color: color-mix(in srgb, var(--theme-main-text, #fff) 42%, transparent); }
.search-hit-text {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 82%, transparent);
}
.search-hit-list--wrap .search-hit-text { white-space: normal; overflow-wrap: anywhere; }
.search-hit-note { padding: 2px 6px; color: color-mix(in srgb, var(--theme-main-text, #fff) 45%, transparent); font-size: 11px; }
.web-fetch-card { display: grid; gap: 6px; margin: 2px 0 8px; }
.web-fetch-title { color: var(--theme-main-text, #fff); font-size: 13px; font-weight: 650; line-height: 1.35; overflow-wrap: anywhere; }
.web-fetch-summary { margin: 0; color: color-mix(in srgb, var(--theme-main-text, #fff) 65%, transparent); font-size: 12px; line-height: 1.55; overflow-wrap: anywhere; }
.web-fetch-more-toggle { color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent); font-size: 11px; cursor: pointer; }
.web-fetch-more-toggle:hover { color: var(--theme-main-text, #fff); }
.web-fetch-raw {
  max-height: 240px;
  overflow: auto;
  margin: 4px 0 0;
  padding: 8px 10px;
  border-radius: var(--radius-sm, 6px);
  background: color-mix(in srgb, var(--theme-main-sunken-background, transparent) 88%, transparent);
  color: color-mix(in srgb, var(--theme-main-text, #fff) 78%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.5;
  white-space: pre;
  overflow-wrap: normal;
}
.web-fetch-raw--wrap { white-space: pre-wrap; overflow-wrap: anywhere; }

/* 记忆行的读写方向：写是信息性动作，走蓝色；读保持次要灰。 */
.process-tool-flag--info { color: color-mix(in srgb, var(--blue) 78%, var(--theme-main-text, #fff) 22%); }

/* 进行中的清单步骤向右栏清单看齐：绿色文字 + 转圈指示（减弱动态退化为静态）。 */
.checklist-item--running .checklist-text { color: color-mix(in srgb, var(--green) 78%, var(--theme-main-text, #fff) 22%); }
.checklist-item--running .checklist-box { border-color: var(--green); color: transparent; }
.checklist-item--running .checklist-box::after {
  content: '';
  width: 8px;
  height: 8px;
  border: 1px solid color-mix(in srgb, var(--green) 36%, transparent);
  border-top-color: var(--green);
  border-radius: 50%;
  animation: checklist-box-spin 1.2s linear infinite;
}
@keyframes checklist-box-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .checklist-item--running .checklist-box::after { animation: none; }
}

/* Generated image cards inside process details + fullscreen preview. */
.tool-image-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 8px;
  padding: 8px 10px 10px;
}

.tool-image-card {
  margin: 0;
  border-radius: var(--radius-sm, 6px);
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 18%, transparent);
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 6%, transparent);
  cursor: zoom-in;
  line-height: 0;
}

.tool-image-card img {
  width: 100%;
  height: auto;
  display: block;
  object-fit: cover;
  aspect-ratio: 1 / 1;
}

/* 引用条目（大图被后端换成引用）在字节取回之前的占位：名字 + 体积，
   取不到时给重试，绝不留一张破图。 */
.tool-image-card--placeholder {
  cursor: pointer;
  line-height: normal;
}

.tool-image-placeholder {
  aspect-ratio: 1 / 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 10px;
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 62%, transparent);
  font-size: 11px;
  text-align: center;
}

.tool-image-placeholder__name {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 650;
}

.tool-image-placeholder__size {
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 45%, transparent);
  font-family: var(--font-mono, monospace);
  font-variant-numeric: tabular-nums;
}

.tool-image-placeholder__retry {
  margin-top: 2px;
  border: 0;
  border-radius: var(--radius-sm, 6px);
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover), transparent);
  color: inherit;
  padding: 3px 8px;
  font: inherit;
  cursor: pointer;
}

.tool-image-placeholder__retry:hover {
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-active), transparent);
}

.image-preview-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-fullscreen, 100);
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, #000 78%, transparent);
  cursor: zoom-out;
}

.image-preview-full {
  max-width: 92vw;
  max-height: 92vh;
  border-radius: var(--radius);
  box-shadow: 0 18px 60px rgba(0, 0, 0, .55);
  user-select: none;
}

/* 图片预览是内容覆盖层：悬浮在任意图片/黑遮罩之上，
   必须用固定白色系保证可见，不随主题（与 Stage 控件同理）。 */
.image-preview-close {
  position: fixed;
  top: 18px;
  right: 22px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, .25);
  background: rgba(255, 255, 255, .12);
  color: #fff;
  font-size: 15px;
  cursor: pointer;
}
</style>

