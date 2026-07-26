<template>
  <div class="chat-thread">
    <div v-if="messages.length === 0" class="sidebar-empty">
      <slot name="empty">
        <span>暂无消息，发送一个任务。</span>
      </slot>
    </div>

    <template v-for="msg in messages" :key="msg.id">
      <!-- Per-message override: product provides full rendering -->
      <slot
        v-if="$slots['message-product']"
        name="message-product"
        :message="msg"
      />

      <!-- User message -->
      <div v-else-if="msg.role === 'user'" class="user-row">
        <div class="user-stack">
          <div class="user-bubble">{{ msg.content }}</div>
          <div v-if="attachmentParts(msg).length" class="message-attachment-list" aria-label="消息附件">
            <div
              v-for="part in attachmentParts(msg)"
              :key="part.id"
              class="message-attachment-pill"
            >
              <span class="message-attachment-kind">{{ attachmentKind(part) }}</span>
              <span class="message-attachment-name">{{ attachmentName(part) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- System message (lifecycle, status, errors) -->
      <div v-else-if="msg.role === 'system'" class="system-row">
        <div class="system-bubble" :class="systemBubbleClass(msg)">
          <span class="system-icon">{{ systemIcon(msg) }}</span>
          <span class="system-text">{{ msg.content }}</span>
        </div>
      </div>

      <!-- Assistant message: answer stream + process stream -->
      <div v-else class="assistant-row">
        <div class="assistant-message" :class="{ 'assistant-message--live': isLiveMessage(msg) }">
          <div class="assistant-meta">
            <span class="assistant-label">{{ assistantLabel }}</span>
            <span v-if="isLiveMessage(msg) && !isInitialWaitingMessage(msg)" class="assistant-live-state">
              <span class="stream-spinner" />
              {{ liveStatusText(msg) }}
            </span>
          </div>

          <div v-if="terminalErrorText(msg)" class="assistant-terminal-error" role="alert">
            <span class="assistant-terminal-error__label">运行失败</span>
            <span>{{ terminalErrorText(msg) }}</span>
          </div>

          <div v-if="isInitialWaitingMessage(msg)" class="initial-waiting-indicator" aria-label="请求中">
            <span v-if="shouldShowShallowThinkingPending(msg)" class="shallow-thinking-pending" role="status" aria-live="polite">
              shallow thinking<span class="shallow-thinking-dots" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span>
            </span>
            <span v-else class="stream-spinner" />
          </div>

          <!-- ── Part-based rendering ── -->
          <template v-if="(msg.parts && msg.parts.length > 0) || shouldShowShallowThinkingPending(msg)">
            <div
              v-if="shouldShowShallowThinkingPending(msg) && !isLiveMessage(msg) && !isInitialWaitingMessage(msg)"
              class="process-step process-step--reasoning shallow-thinking-pending-row"
            >
              <div class="reasoning-body reasoning-body--pending">
                <span class="shallow-thinking-pending" role="status" aria-live="polite">
                  shallow thinking<span class="shallow-thinking-dots" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span>
                </span>
              </div>
            </div>
            <template v-if="isTimelineMessage(msg)">
              <template v-if="isLiveMessage(msg)">
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
                <template
                  v-for="group in compactGroups(groupParts(timelineParts(msg)))"
                  :key="group.kind === 'process-group' ? `live-tl-pg-${processGroupId(group)}` : group.part.id"
                >
                  <div v-if="part.partType === 'text' && part.content" class="assistant-answer">
                    <slot name="assistant-content" :content="part.content">
                      <MarkdownRenderer class="part-text-content part-text-content--streaming" :content="part.content" :streaming="true" />
                    </slot>
                  </div>

                  <div v-else-if="part.partType === 'model_text' && part.content" class="assistant-answer assistant-answer--process">
                    <slot name="assistant-content" :content="part.content">
                      <MarkdownRenderer class="part-text-content part-text-content--streaming" :content="part.content" :streaming="true" />
                    </slot>
                  </div>

                  <div
                    v-else-if="part.partType === 'reasoning'"
                    class="process-step process-step--reasoning"
                  >
                    <button
                      type="button"
                      class="reasoning-toggle"
                      @click="togglePartExpand(part, true)"
                    >
                      <span class="process-step-marker" />
                      <span class="process-step-title">思考</span>
                      <span v-if="reasoningDuration(part, true)" class="reasoning-duration">{{ reasoningDuration(part, true) }}</span>
                      <span class="tool-expand-chevron">{{ isPartExpanded(part, true) ? '▾' : '▸' }}</span>
                    </button>
                    <div v-if="isPartExpanded(part, true)" class="reasoning-body">
                      <slot name="reasoning-content" :content="part.content" :live="true">
                        <MarkdownRenderer class="process-step-detail part-text-content--streaming" :content="part.content" :streaming="true" />
                      </slot>
                    </div>
                  </div>

                  <div
                    v-else-if="part.partType === 'decision'"
                    class="decision-card"
                    :class="'decision-card--' + part.status"
                  >
                    <div class="decision-card-head">
                      <span class="process-step-marker" />
                      <span class="decision-card-title">{{ decisionTitle(part) }}</span>
                      <span class="decision-card-status">{{ decisionStatusLabel(part) }}</span>
                    </div>
                    <p v-if="decisionDetail(part)" class="decision-card-detail">{{ decisionDetail(part) }}</p>
                    <p v-if="decisionResponseText(part)" class="decision-card-decision">{{ decisionResponseText(part) }}</p>
                    <div v-if="part.status === 'pending' && decisionOptions(part).length > 0" class="decision-options">
                      <div v-for="option in decisionOptions(part)" :key="option.id" class="decision-option-group">
                        <button
                          type="button"
                          class="decision-option"
                          :class="{
                            'decision-option--approve': option.id === 'approve',
                            'decision-option--deny': option.id === 'deny',
                          }"
                          @click="emit('decision-select', { partId: part.id, option, response: decisionOptionResponse(part, option) })"
                        >
                          <span class="decision-option-label">{{ option.label }}</span>
                        </button>
                        <span v-if="option.description" class="decision-option-desc">{{ option.description }}</span>
                      </div>
                    </div>
                    <details v-if="canGuideDecision(part)" class="decision-guide">
                      <summary class="decision-guide-toggle">其他处理方式</summary>
                      <div class="decision-guide-fields">
                        <textarea
                          class="decision-guide-input"
                          :value="decisionGuideDraft(part)"
                          placeholder="说明希望如何处理…"
                          rows="2"
                          @input="updateDecisionGuideDraft(part, $event)"
                        />
                        <button
                          type="button"
                          class="decision-guide-submit"
                          :disabled="!decisionGuideDraft(part).trim()"
                          @click="submitDecisionGuide(part)"
                        >
                          提交
                        </button>
                      </div>
                    </details>
                  </div>

                  <div v-else-if="isHighValueLivePart(part)" class="process-stream process-stream--live process-stream--inline">
                    <div
                      v-if="(part.partType === 'tool_call' || part.partType === 'tool_result') && !isControlTool(part)"
                      class="process-step process-step--tool"
                      :class="['process-step--' + part.status, toolColorClass(part)]"
                    >
                      <button
                        type="button"
                        class="tool-card-header"
                        :class="[{ 'has-detail': hasToolDisplay(part), 'process-tool-row': !isCommandTool(part), 'tool-card-header--command': isCommandTool(part) }, toolColorClass(part)]"
                        :aria-expanded="!isCommandTool(part) && hasToolDisplay(part) ? shouldShowToolBody(part, true) : undefined"
                        @click="togglePartExpand(part, true)"
                      >
                        <span v-if="isCommandTool(part)" class="process-step-marker" />
                        <template v-if="isCommandTool(part)">
                          <span class="tool-type-tag" :class="toolColorClass(part)">{{ toolTypeLabel(part) }}</span>
                          <span class="process-step-title">{{ readableProcessTitle(part) }}</span>
                          <span v-if="shouldShowToolArgsPreview(part)" class="tool-args-preview">{{ toolArgsPreview(part.toolArgs || {}) }}</span>
                        </template>
                        <template v-else>
                          <span class="tool-row-name">{{ toolTypeLabel(part) }}</span>
                          <span class="process-step-title tool-row-summary">{{ readableProcessTitle(part) }}</span>
                          <span v-if="shouldShowToolArgsPreview(part)" class="tool-args-preview tool-row-args">{{ toolArgsPreview(part.toolArgs || {}) }}</span>
                          <span class="tool-row-status">{{ toolStatusLabel(part) }}</span>
                        </template>
                        <span
                          v-if="hasToolDisplay(part)"
                          class="tool-expand-chevron"
                        >{{ shouldShowToolBody(part, true) ? '▾' : '▸' }}</span>
                      </button>
                      <div
                        v-if="shouldShowToolBody(part, true)"
                        class="tool-card-body"
                        :class="{ 'tool-card-body--row': !isCommandTool(part) }"
                      >
                        <pre v-if="displayToolError(part)" class="tool-output tool-output--error" @click.stop="copyToolErrorText(part)" title="点击复制错误信息">{{ displayToolError(part) }}</pre>
                        <div v-if="displayToolResult(part) && isFileTool(part)" class="diff-block" :class="[fileDiffClass(part), { 'diff-block--wrap': isToolWrapEnabled(part.id) }]">
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
                        <div v-else-if="displayToolInputPreview(part)" v-auto-follow-scroll="displayToolInputPreview(part)" class="tool-output tool-input-preview">
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
                          <pre class="tool-output-content" :class="{ 'tool-output-content--wrap': isToolWrapEnabled(part.id) }" @click="toggleToolWrap(part.id)">{{ toolOutputContent(part) }}</pre>
                        </div>
                        <pre v-else-if="readableProcessDetail(part)" class="tool-output">{{ readableProcessDetail(part) }}</pre>
                      </div>
                    </div>

                    <div v-else-if="isModelRetryPart(part)" class="model-retry-bar">
                      <div class="model-retry-bar__track">
                        <div
                          v-for="i in modelRetryCounts(part).maxRetries"
                          :key="i"
                          class="model-retry-bar__segment"
                          :class="{ 'model-retry-bar__segment--filled': i <= modelRetryCounts(part).attempt }"
                        />
                      </div>
                      <span class="model-retry-bar__label">重试中 {{ modelRetryCounts(part).attempt }}/{{ modelRetryCounts(part).maxRetries }}</span>
                    </div>

                    <div v-else class="process-timeline">
                      <div
                        class="process-step"
                        :class="['process-step--' + part.status, part.status === 'completed' ? 'process-step--compact' : 'process-step--current']"
                      >
                        <span class="process-step-marker" />
                        <span class="tool-type-tag" :class="processColorClass(part)">{{ processKindLabel(part) }}</span>
                        <span class="process-step-title">{{ readableProcessTitle(part) }}</span>
                        <span v-if="readableProcessDetail(part)" class="process-step-detail">{{ readableProcessDetail(part) }}</span>
                      </div>
                    </div>
                  </div>
                </template>

              </template>

              <template v-else>
                <button
                  v-if="processSummary(msg).count > 0 && !isCompactionOnlyMessage(msg)"
                  type="button"
                  class="process-toggle"
                  @click="emit('toggle-process', msg.id)"
                >
                  <span class="process-toggle-icon" :class="processBarStatus(msg)" />
                  <span class="process-toggle-text">{{ processSummary(msg).text }}</span>
                  <span class="process-toggle-hint">{{ isProcessExpanded(msg) ? '收起过程' : '查看过程' }}</span>
                  <span class="process-toggle-chevron">{{
                    isProcessExpanded(msg) ? '▾' : '▸'
                  }}</span>
                </button>

                <div v-if="isProcessExpanded(msg)" class="process-stream process-stream--history">
                  <template
                    v-for="group in compactGroups(groupParts(processParts(msg)))"
                    :key="group.kind === 'context-group' ? `context-${group.items.map((item) => item.id).join('-')}` : group.kind === 'process-group' ? processGroupId(group) : group.part.id"
                  >
                    <div v-if="group.kind === 'context-group'" class="process-step process-step--context" :class="'process-step--' + (group.status || 'pending')">
                      <button
                        type="button"
                        class="context-group-header"
                        @click="toggleToolExpand(contextGroupId(group))"
                      >
                        <span class="process-step-marker" />
                        <span class="process-step-title">{{ group.label }}</span>
                        <span class="process-step-detail">{{ group.detail }}</span>
                        <span class="tool-expand-chevron">{{ isToolExpanded(contextGroupId(group)) ? '▾' : '▸' }}</span>
                      </button>
                      <div v-if="isToolExpanded(contextGroupId(group))" class="context-tool-list">
                        <div
                          v-for="item in group.items"
                          :key="item.id"
                          class="context-tool-row"
                        >
                          <div class="context-tool-head">
                            <span class="tool-row-name">{{ toolTypeLabel(item) }}</span>
                            <span class="process-step-title tool-row-summary">{{ readableProcessTitle(item) }}</span>
                            <span v-if="shouldShowToolArgsPreview(item)" class="tool-args-preview tool-row-args">{{ toolArgsPreview(item.toolArgs || {}) }}</span>
                          </div>
                          <div v-if="hasToolDisplay(item)" class="tool-output context-tool-output">
                            <div v-if="toolMetaItems(item).length > 0" class="tool-output-meta">
                              <span v-for="meta in toolMetaItems(item)" :key="meta">{{ meta }}</span>
                            </div>
                            <pre class="tool-output-content">{{ toolOutputContent(item) }}</pre>
                          </div>
                        </div>
                      </div>
                    </div>

                    <template v-else-if="group.kind === 'process-group'">
                      <div class="process-group">
                        <button
                          type="button"
                          class="process-group-summary"
                          @click="toggleGroupExpand(processGroupId(group))"
                        >
                          <span class="process-step-marker" />
                          <span class="process-group-text">{{ group.summary }}</span>
                          <span class="process-group-chevron">{{ isGroupExpanded(processGroupId(group)) ? '▾' : '▸' }}</span>
                        </button>
                        <div v-if="isGroupExpanded(processGroupId(group))" class="process-group-body">
                          <template v-for="part in group.parts" :key="part.id">
                            <div v-if="part.partType === 'reasoning'" class="process-step process-step--reasoning">
                              <button type="button" class="reasoning-toggle" @click="togglePartExpand(part, false)">
                                <span class="process-step-marker" />
                                <span class="process-step-title">思考</span>
                                <span v-if="reasoningDuration(part)" class="reasoning-duration">{{ reasoningDuration(part) }}</span>
                                <span class="tool-expand-chevron">{{ isPartExpanded(part, false) ? '▾' : '▸' }}</span>
                              </button>
                              <div v-if="isPartExpanded(part, false)" class="reasoning-body">
                                <slot name="reasoning-content" :content="part.content" :live="false">
                                  <MarkdownRenderer class="process-step-detail" :content="part.content" />
                                </slot>
                              </div>
                            </div>
                            <div
                              v-else-if="(part.partType === 'tool_call' || part.partType === 'tool_result') && !isControlTool(part)"
                              class="process-step process-step--tool"
                              :class="'process-step--' + part.status"
                            >
                              <button
                                type="button"
                                class="tool-card-header"
                                :class="[{ 'has-detail': hasToolDisplay(part), 'process-tool-row': !isCommandTool(part), 'tool-card-header--command': isCommandTool(part) }, toolColorClass(part)]"
                                @click="togglePartExpand(part, false)"
                              >
                                <span v-if="isCommandTool(part)" class="process-step-marker" />
                                <template v-if="isCommandTool(part)">
                                  <span class="tool-type-tag" :class="toolColorClass(part)">{{ toolTypeLabel(part) }}</span>
                                  <span class="process-step-title">{{ readableProcessTitle(part) }}</span>
                                  <span v-if="shouldShowToolArgsPreview(part)" class="tool-args-preview">{{ toolArgsPreview(part.toolArgs || {}) }}</span>
                                </template>
                                <template v-else>
                                  <span class="tool-row-name">{{ toolTypeLabel(part) }}</span>
                                  <span class="process-step-title tool-row-summary">{{ readableProcessTitle(part) }}</span>
                                  <span v-if="shouldShowToolArgsPreview(part)" class="tool-args-preview tool-row-args">{{ toolArgsPreview(part.toolArgs || {}) }}</span>
                                  <span class="tool-row-status">{{ toolStatusLabel(part) }}</span>
                                </template>
                                <span v-if="hasToolDisplay(part)" class="tool-expand-chevron">{{ shouldShowToolBody(part, false) ? '▾' : '▸' }}</span>
                              </button>
                              <div v-if="shouldShowToolBody(part, false)" class="tool-card-body" :class="{ 'tool-card-body--row': !isCommandTool(part) }">
                                <pre v-if="displayToolError(part)" class="tool-output tool-output--error">{{ displayToolError(part) }}</pre>
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
                              </div>
                            </div>
                          </template>
                        </div>
                      </div>
                    </template>

                    <template v-else-if="group.kind === 'process' && group.part">
                      <div
                        v-if="(group.part.partType === 'tool_call' || group.part.partType === 'tool_result') && !isControlTool(group.part)"
                        class="process-step process-step--tool"
                        :class="'process-step--' + group.part.status"
                      >
                        <button
                          type="button"
                          class="tool-card-header"
                          :class="[{ 'has-detail': hasToolDisplay(group.part), 'process-tool-row': !isCommandTool(group.part), 'tool-card-header--command': isCommandTool(group.part) }, toolColorClass(group.part)]"
                          :aria-expanded="!isCommandTool(group.part) && hasToolDisplay(group.part) ? shouldShowToolBody(group.part, false) : undefined"
                          @click="togglePartExpand(group.part, false)"
                        >
                          <span v-if="isCommandTool(group.part)" class="process-step-marker" />
                          <template v-if="isCommandTool(group.part)">
                            <span class="tool-type-tag" :class="toolColorClass(group.part)">{{ toolTypeLabel(group.part) }}</span>
                            <span class="process-step-title">{{ readableProcessTitle(group.part) }}</span>
                            <span v-if="shouldShowToolArgsPreview(group.part)" class="tool-args-preview">{{ toolArgsPreview(group.part.toolArgs || {}) }}</span>
                          </template>
                          <template v-else>
                            <span class="tool-row-name">{{ toolTypeLabel(group.part) }}</span>
                            <span class="process-step-title tool-row-summary">{{ readableProcessTitle(group.part) }}</span>
                            <span v-if="shouldShowToolArgsPreview(group.part)" class="tool-args-preview tool-row-args">{{ toolArgsPreview(group.part.toolArgs || {}) }}</span>
                            <span class="tool-row-status">{{ toolStatusLabel(group.part) }}</span>
                          </template>
                          <span
                            v-if="hasToolDisplay(group.part)"
                            class="tool-expand-chevron"
                          >{{ shouldShowToolBody(group.part, false) ? '▾' : '▸' }}</span>
                        </button>
                        <div
                          v-if="shouldShowToolBody(group.part, false)"
                          class="tool-card-body"
                          :class="{ 'tool-card-body--row': !isCommandTool(group.part) }"
                        >
                          <pre v-if="displayToolError(group.part)" class="tool-output tool-output--error">{{ displayToolError(group.part) }}</pre>
                          <div v-if="displayToolResult(group.part) && isFileTool(group.part)" class="diff-block" :class="[fileDiffClass(group.part), { 'diff-block--wrap': isToolWrapEnabled(group.part.id) }]">
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
                          <div v-else-if="displayToolResult(group.part)" class="tool-output">
                            <div v-if="toolMetaItems(group.part).length > 0" class="tool-output-meta">
                              <span v-for="item in toolMetaItems(group.part)" :key="item">{{ item }}</span>
                            </div>
                            <pre class="tool-output-content" :class="{ 'tool-output-content--wrap': isToolWrapEnabled(group.part.id) }" @click="toggleToolWrap(group.part.id)">{{ toolOutputContent(group.part) }}</pre>
                          </div>
                          <pre v-else-if="readableProcessDetail(group.part)" class="tool-output">{{ readableProcessDetail(group.part) }}</pre>
                        </div>
                      </div>

                      <div
                        v-else-if="group.part.partType === 'reasoning'"
                        class="process-step process-step--reasoning"
                      >
                        <button
                          type="button"
                          class="reasoning-toggle"
                          @click="togglePartExpand(group.part, false)"
                        >
                          <span class="process-step-marker" />
                          <span class="process-step-title">思考</span>
                          <span v-if="reasoningDuration(group.part)" class="reasoning-duration">{{ reasoningDuration(group.part) }}</span>
                          <span class="tool-expand-chevron">{{ isPartExpanded(group.part, false) ? '▾' : '▸' }}</span>
                        </button>
                        <div v-if="isPartExpanded(group.part, false)" class="reasoning-body">
                          <slot name="reasoning-content" :content="group.part.content" :live="false">
                            <MarkdownRenderer class="process-step-detail" :content="group.part.content" />
                          </slot>
                        </div>
                      </div>

                      <div
                        v-else-if="group.part.partType === 'model_text' && group.part.content"
                      >
                        <slot name="assistant-content" :content="group.part.content">
                          <MarkdownRenderer class="part-text-content" :content="group.part.content" />
                        </slot>
                      </div>

                      <div
                        v-else-if="group.part.partType === 'decision'"
                        class="decision-card"
                        :class="'decision-card--' + group.part.status"
                      >
                        <div class="decision-card-head">
                          <span class="process-step-marker" />
                          <span class="decision-card-title">{{ decisionTitle(group.part) }}</span>
                          <span class="decision-card-status">{{ decisionStatusLabel(group.part) }}</span>
                        </div>
                        <p v-if="decisionDetail(group.part)" class="decision-card-detail">{{ decisionDetail(group.part) }}</p>
                        <p v-if="decisionResponseText(group.part)" class="decision-card-decision">{{ decisionResponseText(group.part) }}</p>
                        <div v-if="group.part.status === 'pending' && decisionOptions(group.part).length > 0" class="decision-options">
                          <div v-for="option in decisionOptions(group.part)" :key="option.id" class="decision-option-group">
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
                          </div>
                        </div>
                        <details v-if="canGuideDecision(group.part)" class="decision-guide">
                          <summary class="decision-guide-toggle">其他处理方式</summary>
                          <div class="decision-guide-fields">
                            <textarea
                              class="decision-guide-input"
                              :value="decisionGuideDraft(group.part)"
                              placeholder="说明希望如何处理…"
                              rows="2"
                              @input="updateDecisionGuideDraft(group.part, $event)"
                            />
                            <button
                              type="button"
                              class="decision-guide-submit"
                              :disabled="!decisionGuideDraft(group.part).trim()"
                              @click="submitDecisionGuide(group.part)"
                            >
                              提交
                            </button>
                          </div>
                        </details>
                      </div>

                      <div
                        v-else-if="isSubLinePart(group.part)"
                        class="sub-line-block"
                      >
                        <button
                          type="button"
                          class="sub-line-heading"
                          @click="togglePartExpand(group.part, false)"
                        >
                          <span class="process-step-marker" />
                          <span class="sub-line-title">{{ agentTitle(group.part) }}</span>
                          <span class="sub-line-status">{{ agentStatusLabel(group.part) }}</span>
                          <span class="tool-expand-chevron sub-line-chevron">{{ isPartExpanded(group.part, false) ? '▾' : '▸' }}</span>
                        </button>
                        <div v-if="agentDeliveryMeta(group.part).length > 0" class="sub-line-delivery-meta">
                          <span v-for="item in agentDeliveryMeta(group.part)" :key="item">{{ item }}</span>
                        </div>
                        <div v-if="isPartExpanded(group.part, false)" class="sub-line-body">
                          <ChatThread
                            class="sub-line-chat"
                            :messages="agentSubMessages(group.part)"
                            :assistant-label="agentTitle(group.part)"
                            :process-expanded-ids="agentProcessExpandedIds(group.part)"
                            @toggle-process="toggleAgentProcess"
                            @decision-select="emit('decision-select', $event)"
                          >
                            <template #assistant-content="slotProps">
                              <slot name="assistant-content" v-bind="slotProps">
                                <MarkdownRenderer
                                  class="part-text-content"
                                  :content="slotProps.content"
                                  :streaming="Boolean(slotProps.live)"
                                />
                              </slot>
                            </template>
                            <template #reasoning-content="slotProps">
                              <slot name="reasoning-content" v-bind="slotProps">
                                <MarkdownRenderer
                                  class="process-step-detail"
                                  :content="slotProps.content"
                                  :streaming="Boolean(slotProps.live)"
                                />
                              </slot>
                            </template>
                          </ChatThread>
                        </div>
                      </div>

                      <div
                        v-else-if="group.part.partType === 'compaction'"
                        class="compaction-step"
                        :class="'compaction-step--' + compactionStatus(group.part)"
                      >
                        <button
                          type="button"
                          class="compaction-toggle"
                          :disabled="!canToggleCompaction(group.part)"
                          :aria-expanded="isCompactionExpanded(group.part)"
                          :aria-controls="'compaction-summary-' + group.part.id"
                          @click="canToggleCompaction(group.part) && toggleToolExpand(group.part.id)"
                        >
                          <span class="process-step-marker" aria-hidden="true" />
                          <span class="process-step-title">{{ compactionTitle(group.part) }}</span>
                          <span class="process-step-detail">{{ compactionDetail(group.part) }}</span>
                          <span v-if="canToggleCompaction(group.part)" class="tool-expand-chevron" aria-hidden="true">{{ isCompactionExpanded(group.part) ? '▾' : '▸' }}</span>
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

                      <div
                        v-else-if="isChecklistPart(group.part)"
                        class="checklist-card"
                        :class="'checklist-card--' + group.part.status"
                      >
                        <div class="checklist-card-head">
                          <span class="process-step-marker" />
                          <span class="process-step-title">{{ controlTitle(group.part) }}</span>
                        </div>
                        <ol class="checklist-items">
                          <li v-for="item in checklistItems(group.part)" :key="item.id" class="checklist-item" :class="'checklist-item--' + item.status">
                            <span class="checklist-box">{{ item.checked ? '✓' : '' }}</span>
                            <span class="checklist-text">{{ item.text }}</span>
                          </li>
                        </ol>
                      </div>

                      <div v-else-if="isModelRetryPart(group.part)" class="model-retry-bar">
                        <div class="model-retry-bar__track">
                          <div
                            v-for="i in modelRetryCounts(group.part).maxRetries"
                            :key="i"
                            class="model-retry-bar__segment"
                            :class="{ 'model-retry-bar__segment--filled': i <= modelRetryCounts(group.part).attempt }"
                          />
                        </div>
                        <span class="model-retry-bar__label">重试中 {{ modelRetryCounts(group.part).attempt }}/{{ modelRetryCounts(group.part).maxRetries }}</span>
                      </div>

                      <div v-else class="process-step process-step--info" :class="'process-step--' + group.part.status">
                        <button
                          v-if="hasExpandableProcessDetail(group.part)"
                          type="button"
                          class="process-inline-toggle"
                          @click="togglePartExpand(group.part, false)"
                        >
                          <span class="process-step-marker" />
                          <span v-if="showProcessKindTag(group.part)" class="tool-type-tag" :class="processColorClass(group.part)">{{ processKindLabel(group.part) }}</span>
                          <span class="process-step-title">{{ readableProcessTitle(group.part) }}</span>
                          <span class="process-step-detail">{{ processDetailPreview(group.part) }}</span>
                          <span class="tool-expand-chevron">{{ isPartExpanded(group.part, false) ? '▾' : '▸' }}</span>
                        </button>
                        <template v-else>
                          <span class="process-step-marker" />
                          <span v-if="showProcessKindTag(group.part)" class="tool-type-tag" :class="processColorClass(group.part)">{{ processKindLabel(group.part) }}</span>
                          <span class="process-step-title">{{ readableProcessTitle(group.part) }}</span>
                          <span v-if="readableProcessDetail(group.part)" class="process-step-detail">{{ readableProcessDetail(group.part) }}</span>
                        </template>
                        <div v-if="hasExpandableProcessDetail(group.part) && isPartExpanded(group.part, false)" class="process-detail-panel">
                          <button type="button" class="process-detail-copy" @click.stop="copyProcessDetail(group.part)">复制</button>
                          <pre>{{ fullProcessDetail(group.part) }}</pre>
                        </div>
                      </div>
                    </template>
                  </template>
                </div>

                <div v-if="answerContent(msg)" class="assistant-answer">
                  <slot name="assistant-content" :content="answerContent(msg)">
                    <MarkdownRenderer class="part-text-content" :content="answerContent(msg)" />
                  </slot>
                </div>
                <template v-else>
                  <div
                    v-for="(group, gi) in textGroups(processParts(msg))"
                    :key="'timeline-txt-' + gi"
                    class="assistant-answer"
                  >
                    <slot name="assistant-content" :content="group.content">
                      <MarkdownRenderer class="part-text-content" :content="group.content" />
                    </slot>
                  </div>
                </template>
              </template>
            </template>

            <!-- Non-timeline live: inline chronological rendering with status indicator -->
            <div
              v-if="!isTimelineMessage(msg) && isLiveMessage(msg) && !isInitialWaitingMessage(msg)"
              class="process-stream process-stream--live"
            >
              <div class="process-current">
                <span class="stream-spinner" />
                <span class="process-current-title">{{ liveStatusText(msg) }}</span>
                <span v-if="liveDetailText(msg)" class="process-current-detail">{{ liveDetailText(msg) }}</span>
              </div>

              <div v-if="shouldShowShallowThinkingPending(msg)" class="shallow-thinking-pending shallow-thinking-pending--process" role="status" aria-live="polite">
                shallow thinking<span class="shallow-thinking-dots" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span>
              </div>

              <!-- Live parts inline with streaming -->
              <template
                v-for="group in compactGroups(groupParts(processParts(msg)))"
                :key="group.kind === 'context-group' ? `live-ctx-${group.items.map((item) => item.id).join('-')}` : group.kind === 'process-group' ? `live-pg-${processGroupId(group)}` : `live-${group.part.id}`"
              >
                <!-- model_text: stream inline -->
                <div v-if="group.kind === 'process' && group.part.partType === 'model_text' && group.part.content">
                  <MarkdownRenderer
                    class="part-text-content part-text-content--streaming"
                    :content="group.part.content"
                    :streaming="true"
                  />
                </div>

                <!-- reasoning: inline during live -->
                <div
                  v-else-if="group.kind === 'process' && group.part.partType === 'reasoning'"
                  class="process-step process-step--reasoning"
                >
                  <button type="button" class="reasoning-toggle" @click="togglePartExpand(group.part, true)">
                    <span class="process-step-marker" />
                    <span class="process-step-title">思考</span>
                    <span class="tool-expand-chevron">{{ isPartExpanded(group.part, true) ? '▾' : '▸' }}</span>
                  </button>
                  <div :class="['reasoning-body', { 'reasoning-body--closed': !isPartExpanded(group.part, true) }]">
                    <slot name="reasoning-content" :content="group.part.content" :live="true">
                      <MarkdownRenderer class="process-step-detail" :content="group.part.content" />
                    </slot>
                  </div>
                </div>

                <!-- tool: compact during live -->
                <div
                  v-else-if="group.kind === 'process' && (group.part.partType === 'tool_call' || group.part.partType === 'tool_result') && !isControlTool(group.part)"
                  class="process-step process-step--tool"
                  :class="'process-step--' + group.part.status"
                >
                  <button
                    type="button"
                    class="tool-card-header process-tool-row"
                    :class="{ 'has-detail': hasToolDisplay(group.part) }"
                    @click="togglePartExpand(group.part, true)"
                  >
                    <span class="tool-row-name">{{ toolTypeLabel(group.part) }}</span>
                    <span class="process-step-title tool-row-summary">{{ readableProcessTitle(group.part) }}</span>
                    <span class="tool-row-status" :class="{ 'tool-row-status--retry': toolRetryLabel(group.part) }">{{ toolRetryLabel(group.part) || toolStatusLabel(group.part) }}</span>
                    <span v-if="hasToolDisplay(group.part)" class="tool-expand-chevron">{{ shouldShowToolBody(group.part, true) ? '▾' : '▸' }}</span>
                  </button>
                  <div :class="['tool-card-body', 'tool-card-body--row', { 'tool-card-body--closed': !shouldShowToolBody(group.part, true) }]">
                    <pre v-if="displayToolError(group.part)" class="tool-output tool-output--error">{{ displayToolError(group.part) }}</pre>
                    <pre v-else-if="displayToolResult(group.part)" class="tool-output-content">{{ displayToolResult(group.part) }}</pre>
                  </div>
                </div>

                <!-- process-group: batched reasoning + tools during live -->
                <template v-else-if="group.kind === 'process-group'">
                  <div class="process-group">
                    <button
                      type="button"
                      class="process-group-summary"
                      @click="toggleGroupExpand(processGroupId(group))"
                    >
                      <span class="process-step-marker" />
                      <span class="process-group-text">{{ group.summary }}</span>
                      <span class="process-group-chevron">{{ isGroupExpanded(processGroupId(group)) ? '▾' : '▸' }}</span>
                    </button>
                    <div v-if="isGroupExpanded(processGroupId(group))" class="process-group-body">
                      <template v-for="part in group.parts" :key="part.id">
                        <div v-if="part.partType === 'reasoning'" class="process-step process-step--reasoning">
                          <button type="button" class="reasoning-toggle" @click="togglePartExpand(part, true)">
                            <span class="process-step-marker" />
                            <span class="process-step-title">思考</span>
                            <span class="tool-expand-chevron">{{ isPartExpanded(part, true) ? '▾' : '▸' }}</span>
                          </button>
                          <div :class="['reasoning-body', { 'reasoning-body--closed': !isPartExpanded(part, true) }]">
                            <slot name="reasoning-content" :content="part.content" :live="true">
                              <MarkdownRenderer class="process-step-detail" :content="part.content" />
                            </slot>
                          </div>
                        </div>
                        <div
                          v-else-if="(part.partType === 'tool_call' || part.partType === 'tool_result') && !isControlTool(part)"
                          class="process-step process-step--tool"
                          :class="'process-step--' + part.status"
                        >
                          <button
                            type="button"
                            class="tool-card-header process-tool-row"
                            :class="{ 'has-detail': hasToolDisplay(part) }"
                            @click="togglePartExpand(part, true)"
                          >
                            <span class="tool-row-name">{{ toolTypeLabel(part) }}</span>
                            <span class="process-step-title tool-row-summary">{{ readableProcessTitle(part) }}</span>
                            <span class="tool-row-status" :class="{ 'tool-row-status--retry': toolRetryLabel(part) }">{{ toolRetryLabel(part) || toolStatusLabel(part) }}</span>
                            <span v-if="hasToolDisplay(part)" class="tool-expand-chevron">{{ shouldShowToolBody(part, true) ? '▾' : '▸' }}</span>
                          </button>
                          <div :class="['tool-card-body', 'tool-card-body--row', { 'tool-card-body--closed': !shouldShowToolBody(part, true) }]">
                            <pre v-if="displayToolError(part)" class="tool-output tool-output--error">{{ displayToolError(part) }}</pre>
                            <pre v-else-if="displayToolResult(part)" class="tool-output-content">{{ displayToolResult(part) }}</pre>
                          </div>
                        </div>
                      </template>
                    </div>
                  </div>
                </template>

                <!-- model retry: progress bar during live -->
                <div
                  v-else-if="group.kind === 'process' && isModelRetryPart(group.part)"
                  class="model-retry-bar"
                >
                  <span class="model-retry-bar__label">重试中 {{ modelRetryCounts(group.part).attempt }}/{{ modelRetryCounts(group.part).maxRetries }}</span>
                  <div class="model-retry-bar__track">
                    <div
                      v-for="i in modelRetryCounts(group.part).maxRetries"
                      :key="i"
                      class="model-retry-bar__segment"
                      :class="{ 'model-retry-bar__segment--filled': i <= modelRetryCounts(group.part).attempt }"
                    />
                  </div>
                </div>
              </template>
            </div>

            <div v-if="!isTimelineMessage(msg) && !isLiveMessage(msg)" class="process-stream process-stream--history">
              <template
                v-for="group in compactGroups(groupParts(processParts(msg)))"
                :key="group.kind === 'context-group' ? `context-${group.items.map((item) => item.id).join('-')}` : group.kind === 'process-group' ? processGroupId(group) : group.part.id"
              >
                <div v-if="group.kind === 'context-group'" class="process-step process-step--context" :class="'process-step--' + (group.status || 'pending')">
                  <button
                    type="button"
                    class="context-group-header"
                    @click="toggleToolExpand(contextGroupId(group))"
                  >
                    <span class="process-step-marker" />
                    <span class="process-step-title">{{ group.label }}</span>
                    <span class="process-step-detail">{{ group.detail }}</span>
                    <span class="tool-expand-chevron">{{ isToolExpanded(contextGroupId(group)) ? '▾' : '▸' }}</span>
                  </button>
                  <div v-if="isToolExpanded(contextGroupId(group))" class="context-tool-list">
                    <div
                      v-for="item in group.items"
                      :key="item.id"
                      class="context-tool-row"
                    >
                      <div class="context-tool-head">
                        <span class="tool-row-name">{{ toolTypeLabel(item) }}</span>
                        <span class="process-step-title tool-row-summary">{{ readableProcessTitle(item) }}</span>
                        <span v-if="shouldShowToolArgsPreview(item)" class="tool-args-preview tool-row-args">{{ toolArgsPreview(item.toolArgs || {}) }}</span>
                      </div>
                      <div v-if="hasToolDisplay(item)" class="tool-output context-tool-output">
                        <div v-if="toolMetaItems(item).length > 0" class="tool-output-meta">
                          <span v-for="meta in toolMetaItems(item)" :key="meta">{{ meta }}</span>
                        </div>
                        <pre class="tool-output-content">{{ toolOutputContent(item) }}</pre>
                      </div>
                    </div>
                  </div>
                </div>

                <template v-else-if="group.kind === 'process-group'">
                  <div class="process-group">
                    <button
                      type="button"
                      class="process-group-summary"
                      @click="toggleGroupExpand(processGroupId(group))"
                    >
                      <span class="process-step-marker" />
                      <span class="process-group-text">{{ group.summary }}</span>
                      <span class="process-group-chevron">{{ isGroupExpanded(processGroupId(group)) ? '▾' : '▸' }}</span>
                    </button>
                    <div v-if="isGroupExpanded(processGroupId(group))" class="process-group-body">
                      <template v-for="part in group.parts" :key="part.id">
                        <div v-if="part.partType === 'reasoning'" class="process-step process-step--reasoning">
                          <button type="button" class="reasoning-toggle" @click="togglePartExpand(part, false)">
                            <span class="process-step-marker" />
                            <span class="process-step-title">思考</span>
                            <span v-if="reasoningDuration(part)" class="reasoning-duration">{{ reasoningDuration(part) }}</span>
                            <span class="tool-expand-chevron">{{ isPartExpanded(part, false) ? '▾' : '▸' }}</span>
                          </button>
                          <div :class="['reasoning-body', { 'reasoning-body--closed': !isPartExpanded(part, false) }]">
                            <slot name="reasoning-content" :content="part.content" :live="false">
                              <MarkdownRenderer class="process-step-detail" :content="part.content" />
                            </slot>
                          </div>
                        </div>
                        <div
                          v-else-if="(part.partType === 'tool_call' || part.partType === 'tool_result') && !isControlTool(part)"
                          class="process-step process-step--tool"
                          :class="'process-step--' + part.status"
                        >
                          <button
                            type="button"
                            class="tool-card-header"
                            :class="[{ 'has-detail': hasToolDisplay(part), 'process-tool-row': !isCommandTool(part), 'tool-card-header--command': isCommandTool(part) }, toolColorClass(part)]"
                            @click="togglePartExpand(part, false)"
                          >
                            <span v-if="isCommandTool(part)" class="process-step-marker" />
                            <template v-if="isCommandTool(part)">
                              <span class="tool-type-tag" :class="toolColorClass(part)">{{ toolTypeLabel(part) }}</span>
                              <span class="process-step-title">{{ readableProcessTitle(part) }}</span>
                              <span v-if="shouldShowToolArgsPreview(part)" class="tool-args-preview">{{ toolArgsPreview(part.toolArgs || {}) }}</span>
                            </template>
                            <template v-else>
                              <span class="tool-row-name">{{ toolTypeLabel(part) }}</span>
                              <span class="process-step-title tool-row-summary">{{ readableProcessTitle(part) }}</span>
                              <span v-if="shouldShowToolArgsPreview(part)" class="tool-args-preview tool-row-args">{{ toolArgsPreview(part.toolArgs || {}) }}</span>
                              <span class="tool-row-status">{{ toolStatusLabel(part) }}</span>
                            </template>
                            <span v-if="hasToolDisplay(part)" class="tool-expand-chevron">{{ shouldShowToolBody(part, false) ? '▾' : '▸' }}</span>
                          </button>
                          <div v-if="shouldShowToolBody(part, false)" class="tool-card-body" :class="{ 'tool-card-body--row': !isCommandTool(part) }">
                            <pre v-if="displayToolError(part)" class="tool-output tool-output--error">{{ displayToolError(part) }}</pre>
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
                          </div>
                        </div>
                      </template>
                    </div>
                  </div>
                </template>

                <template v-else-if="group.kind === 'process' && group.part">
                  <div
                    v-if="group.part.partType === 'reasoning'"
                    class="process-step process-step--reasoning"
                  >
                    <button
                      type="button"
                      class="reasoning-toggle"
                      @click="togglePartExpand(group.part, false)"
                    >
                      <span class="process-step-marker" />
                      <span class="process-step-title">思考</span>
                      <span v-if="reasoningDuration(group.part)" class="reasoning-duration">{{ reasoningDuration(group.part) }}</span>
                      <span class="tool-expand-chevron">{{ isPartExpanded(group.part, false) ? '▾' : '▸' }}</span>
                    </button>
                    <div :class="['reasoning-body', { 'reasoning-body--closed': !isPartExpanded(group.part, false) }]">
                      <slot name="reasoning-content" :content="group.part.content" :live="false">
                        <MarkdownRenderer class="process-step-detail" :content="group.part.content" />
                      </slot>
                    </div>
                  </div>

                  <div
                    v-else-if="(group.part.partType === 'tool_call' || group.part.partType === 'tool_result') && !isControlTool(group.part)"
                    class="process-step process-step--tool"
                    :class="'process-step--' + group.part.status"
                  >
                    <button
                      type="button"
                      class="tool-card-header"
                      :class="[{ 'has-detail': hasToolDisplay(group.part), 'process-tool-row': !isCommandTool(group.part), 'tool-card-header--command': isCommandTool(group.part) }, toolColorClass(group.part)]"
                      :aria-expanded="!isCommandTool(group.part) && hasToolDisplay(group.part) ? shouldShowToolBody(group.part, false) : undefined"
                      @click="togglePartExpand(group.part, false)"
                    >
                      <span v-if="isCommandTool(group.part)" class="process-step-marker" />
                      <template v-if="isCommandTool(group.part)">
                        <span class="tool-type-tag" :class="toolColorClass(group.part)">{{ toolTypeLabel(group.part) }}</span>
                        <span class="process-step-title">{{ readableProcessTitle(group.part) }}</span>
                        <span v-if="shouldShowToolArgsPreview(group.part)" class="tool-args-preview">{{ toolArgsPreview(group.part.toolArgs || {}) }}</span>
                      </template>
                      <template v-else>
                        <span class="tool-row-name">{{ toolTypeLabel(group.part) }}</span>
                        <span class="process-step-title tool-row-summary">{{ readableProcessTitle(group.part) }}</span>
                        <span v-if="shouldShowToolArgsPreview(group.part)" class="tool-args-preview tool-row-args">{{ toolArgsPreview(group.part.toolArgs || {}) }}</span>
                        <span class="tool-row-status" :class="{ 'tool-row-status--retry': toolRetryLabel(group.part) }">{{ toolRetryLabel(group.part) || toolStatusLabel(group.part) }}</span>
                      </template>
                      <span
                        v-if="hasToolDisplay(group.part)"
                        class="tool-expand-chevron"
                      >{{ shouldShowToolBody(group.part, false) ? '▾' : '▸' }}</span>
                    </button>
                    <span v-if="!hasToolDisplay(group.part) && !group.part.toolArgs && readableProcessDetail(group.part)" class="process-step-detail">{{ readableProcessDetail(group.part) }}</span>
                    <div
                      :class="['tool-card-body', { 'tool-card-body--row': !isCommandTool(group.part), 'tool-card-body--closed': !shouldShowToolBody(group.part, false) }]"
                    >
                      <pre v-if="displayToolError(group.part)" class="tool-output tool-output--error">{{ displayToolError(group.part) }}</pre>
                      <!-- File tools: diff-style block with line numbers -->
                      <div v-if="displayToolResult(group.part) && isFileTool(group.part)" class="diff-block" :class="[fileDiffClass(group.part), { 'diff-block--wrap': isToolWrapEnabled(group.part.id) }]">
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
                      <pre v-else-if="readableProcessDetail(group.part)" class="tool-output">{{ readableProcessDetail(group.part) }}</pre>
                    </div>
                  </div>

                  <div
                    v-else-if="group.part.partType === 'model_text' && group.part.content"
                  >
                    <MarkdownRenderer
                      class="part-text-content"
                      :content="group.part.content"
                    />
                  </div>

                  <div v-else-if="group.part.partType === 'error'" class="process-step process-step--error">
                    <button
                      type="button"
                      class="process-inline-toggle"
                      @click="togglePartExpand(group.part, false)"
                    >
                      <span class="process-step-marker" />
                      <span class="process-step-title">{{ group.part.label || '出错' }}</span>
                      <span class="process-step-detail">{{ processDetailPreview(group.part) }}</span>
                      <span class="tool-expand-chevron">{{ isPartExpanded(group.part, false) ? '▾' : '▸' }}</span>
                    </button>
                    <div v-if="isPartExpanded(group.part, false)" class="process-detail-panel process-detail-panel--error">
                      <button type="button" class="process-detail-copy" @click.stop="copyProcessDetail(group.part)">复制</button>
                      <pre>{{ fullProcessDetail(group.part) }}</pre>
                    </div>
                  </div>

                  <div v-else-if="isModelRetryPart(group.part)" class="model-retry-bar">
                    <span class="model-retry-bar__label">重试中 {{ modelRetryCounts(group.part).attempt }}/{{ modelRetryCounts(group.part).maxRetries }}</span>
                    <div class="model-retry-bar__track">
                      <div
                        v-for="i in modelRetryCounts(group.part).maxRetries"
                        :key="i"
                        class="model-retry-bar__segment"
                        :class="{ 'model-retry-bar__segment--filled': i <= modelRetryCounts(group.part).attempt }"
                      />
                    </div>
                  </div>

                  <div v-else-if="group.part.partType === 'status'" class="process-step process-step--info" :class="'process-step--' + group.part.status">
                    <button
                      v-if="hasExpandableProcessDetail(group.part)"
                      type="button"
                      class="process-inline-toggle"
                      @click="togglePartExpand(group.part, false)"
                    >
                      <span class="process-step-marker" />
                      <span class="process-step-title">{{ group.part.label || '状态' }}</span>
                      <span class="process-step-detail">{{ processDetailPreview(group.part) }}</span>
                      <span class="tool-expand-chevron">{{ isPartExpanded(group.part, false) ? '▾' : '▸' }}</span>
                    </button>
                    <template v-else>
                      <span class="process-step-marker" />
                      <span class="process-step-title">{{ group.part.label || '状态' }}</span>
                      <span class="process-step-detail">{{ group.part.detail || group.part.content }}</span>
                    </template>
                    <div v-if="hasExpandableProcessDetail(group.part) && isPartExpanded(group.part, false)" class="process-detail-panel">
                      <button type="button" class="process-detail-copy" @click.stop="copyProcessDetail(group.part)">复制</button>
                      <pre>{{ fullProcessDetail(group.part) }}</pre>
                    </div>
                  </div>

                  <div
                    v-else-if="group.part.partType === 'decision'"
                    class="decision-card"
                    :class="'decision-card--' + group.part.status"
                  >
                    <div class="decision-card-head">
                      <span class="process-step-marker" />
                      <span class="decision-card-title">{{ decisionTitle(group.part) }}</span>
                      <span class="decision-card-status">{{ decisionStatusLabel(group.part) }}</span>
                    </div>
                    <p v-if="decisionDetail(group.part)" class="decision-card-detail">{{ decisionDetail(group.part) }}</p>
                    <p v-if="decisionResponseText(group.part)" class="decision-card-decision">{{ decisionResponseText(group.part) }}</p>
                    <div v-if="group.part.status === 'pending' && decisionOptions(group.part).length > 0" class="decision-options">
                      <div v-for="option in decisionOptions(group.part)" :key="option.id" class="decision-option-group">
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
                      </div>
                    </div>
                    <details v-if="canGuideDecision(group.part)" class="decision-guide">
                      <summary class="decision-guide-toggle">其他处理方式</summary>
                      <div class="decision-guide-fields">
                        <textarea
                          class="decision-guide-input"
                          :value="decisionGuideDraft(group.part)"
                          placeholder="说明希望如何处理…"
                          rows="2"
                          @input="updateDecisionGuideDraft(group.part, $event)"
                        />
                        <button
                          type="button"
                          class="decision-guide-submit"
                          :disabled="!decisionGuideDraft(group.part).trim()"
                          @click="submitDecisionGuide(group.part)"
                        >
                          提交
                        </button>
                      </div>
                    </details>
                  </div>

                      <div
                        v-else-if="isSubLinePart(group.part)"
                        class="sub-line-block"
                      >
                        <button
                          type="button"
                          class="sub-line-heading"
                          @click="togglePartExpand(group.part, false)"
                        >
                          <span class="process-step-marker" />
                          <span class="sub-line-title">{{ agentTitle(group.part) }}</span>
                          <span class="sub-line-status">{{ agentStatusLabel(group.part) }}</span>
                          <span class="tool-expand-chevron sub-line-chevron">{{ isPartExpanded(group.part, false) ? '▾' : '▸' }}</span>
                        </button>
                        <div v-if="agentDeliveryMeta(group.part).length > 0" class="sub-line-delivery-meta">
                          <span v-for="item in agentDeliveryMeta(group.part)" :key="item">{{ item }}</span>
                        </div>
                        <div v-if="isPartExpanded(group.part, false)" class="sub-line-body">
                          <ChatThread
                            class="sub-line-chat"
                            :messages="agentSubMessages(group.part)"
                            :assistant-label="agentTitle(group.part)"
                            :process-expanded-ids="agentProcessExpandedIds(group.part)"
                            @toggle-process="toggleAgentProcess"
                            @decision-select="emit('decision-select', $event)"
                          >
                            <template #assistant-content="slotProps">
                              <slot name="assistant-content" v-bind="slotProps">
                                <MarkdownRenderer
                                  class="part-text-content"
                                  :content="slotProps.content"
                                  :streaming="Boolean(slotProps.live)"
                                />
                              </slot>
                            </template>
                            <template #reasoning-content="slotProps">
                              <slot name="reasoning-content" v-bind="slotProps">
                                <MarkdownRenderer
                                  class="process-step-detail"
                                  :content="slotProps.content"
                                  :streaming="Boolean(slotProps.live)"
                                />
                              </slot>
                            </template>
                          </ChatThread>
                        </div>
                      </div>

                  <div
                    v-else-if="isChecklistPart(group.part)"
                    class="checklist-card"
                    :class="'checklist-card--' + group.part.status"
                  >
                    <div class="checklist-card-head">
                      <span class="process-step-marker" />
                      <span class="process-step-title">{{ controlTitle(group.part) }}</span>
                    </div>
                    <ol class="checklist-items">
                      <li v-for="item in checklistItems(group.part)" :key="item.id" class="checklist-item" :class="'checklist-item--' + item.status">
                        <span class="checklist-box">{{ item.checked ? '✓' : '' }}</span>
                        <span class="checklist-text">{{ item.text }}</span>
                      </li>
                    </ol>
                  </div>

                  <div
                    v-else-if="group.part.partType === 'plan' || group.part.partType === 'todo_update'"
                    class="process-step process-step--info"
                    :class="'process-step--' + group.part.status"
                  >
                    <span class="process-step-marker" />
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
                      class="compaction-toggle"
                      :disabled="!canToggleCompaction(group.part)"
                      :aria-expanded="isCompactionExpanded(group.part)"
                      :aria-controls="'compaction-summary-' + group.part.id"
                      @click="canToggleCompaction(group.part) && toggleToolExpand(group.part.id)"
                    >
                      <span class="process-step-marker" aria-hidden="true" />
                      <span class="process-step-title">{{ compactionTitle(group.part) }}</span>
                      <span class="process-step-detail">{{ compactionDetail(group.part) }}</span>
                      <span v-if="canToggleCompaction(group.part)" class="tool-expand-chevron" aria-hidden="true">{{ isCompactionExpanded(group.part) ? '▾' : '▸' }}</span>
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

                      </template>

          <!-- Fallback: no parts → render flat content -->
          <slot v-else name="assistant-content" :content="answerContent(msg)">
            <MarkdownRenderer class="assistant-answer" :content="answerContent(msg)" />
          </slot>

          <!-- Message footer slot (for global stats line etc.) -->
          <slot name="message-footer" :message="msg" />
        </div>
      </div>
    </template>

    <slot name="tail" />
  </div>
</template>

<script setup lang="ts">
import type { CoreAttachment, CoreMessage, MessagePart, MessagePartStatus } from '../types'
import { ref, watch } from 'vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import { autoFollowScrollDirective as vAutoFollowScroll } from '../directives/autoFollowScroll'

defineOptions({ name: 'ChatThread' })

defineSlots<{
  empty?: () => unknown
  tail?: () => unknown
  'message-product'?: (props: { message: CoreMessage }) => unknown
  'assistant-content'?: (props: { content: string; live?: boolean }) => unknown
  'reasoning-content'?: (props: { content: string; live?: boolean }) => unknown
  'message-footer'?: (props: { message: CoreMessage }) => unknown
}>()

const props = withDefaults(
  defineProps<{
    messages: CoreMessage[]
    assistantLabel?: string
    /** Set of message ids whose process section is expanded */
    processExpandedIds?: Set<string>
  }>(),
  {
    assistantLabel: 'Assistant',
    processExpandedIds: () => new Set(),
  },
)

const emit = defineEmits<{
  'toggle-process': [messageId: string]
  'decision-select': [payload: { partId: string; option: DecisionOption; response: string }]
}>()

const decisionGuideDrafts = ref<Record<string, string>>({})

// ── Helpers ──

interface DecisionOption {
  id: string
  label: string
  description?: string
  response?: string
}

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
const toolWrapIds = ref<Set<string>>(new Set())
const subLineProcessCollapsedIds = ref<Set<string>>(new Set())

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
  
  // Clear any pending auto-collapse timer
  const timer = partCompletionTimers.get(partId)
  if (timer) { clearTimeout(timer); partCompletionTimers.delete(partId) }
  
  // Toggle expanded state
  if (isPartExpanded(part, live)) {
    autoExpandedPartIds.value = new Set([...autoExpandedPartIds.value].filter(id => id !== partId))
  } else {
    autoExpandedPartIds.value = new Set([...autoExpandedPartIds.value, partId])
  }
}

function toggleGroupExpand(groupId: string) {
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

function processGroupId(group: PartGroupProcessGroup): string {
  return group.parts.map(p => p.id).join('-')
}

function isPartExpanded(part: MessagePart, live = false): boolean {
  // All parts default collapsed; only expanded when explicitly toggled
  if (part.partType === 'error') return true // Errors always expanded
  if (isSubLinePart(part)) return autoExpandedPartIds.value.has(part.id) // Sub-agents collapsed by default
  
  // Reasoning, tool, status: collapsed by default unless toggled
  if (part.partType === 'reasoning' || part.partType === 'tool_call' || part.partType === 'tool_result') {
    return autoExpandedPartIds.value.has(part.id)
  }
  if (part.partType === 'status') {
    return autoExpandedPartIds.value.has(part.id)
  }
  
  // Default collapsed for others unless explicitly expanded
  return false
}

// ── Auto expand/collapse state ──
const autoExpandedPartIds = ref<Set<string>>(new Set())
const expandedGroupIds = ref<Set<string>>(new Set())
const partCompletionTimers = new Map<string, ReturnType<typeof setTimeout>>()

function schedulePartAutoCollapse(partId: string) {
  const existing = partCompletionTimers.get(partId)
  if (existing) clearTimeout(existing)
  const timer = setTimeout(() => {
    autoExpandedPartIds.value = new Set(
      [...autoExpandedPartIds.value].filter(id => id !== partId)
    )
    partCompletionTimers.delete(partId)
  }, 1000)
  partCompletionTimers.set(partId, timer)
}

// Watch parts for status changes to auto-expand/collapse
watch(
  () => {
    // Collect all parts across all messages
    const ids: string[] = []
    for (const msg of props.messages) {
      for (const part of (msg.parts || [])) {
        ids.push(`${part.id}:${part.status}`)
      }
    }
    return ids.join('|')
  },
  () => {
    for (const msg of props.messages) {
      // Only auto-expand/collapse for live streaming messages
      if (!isLiveMessage(msg)) continue
      for (const part of (msg.parts || [])) {
        if (part.partType === 'reasoning' || part.partType === 'tool_call' || part.partType === 'tool_result') {
          if (part.status === 'running') {
            // Running parts enter the set so they're visible during streaming
            autoExpandedPartIds.value = new Set([...autoExpandedPartIds.value, part.id])
            // Clear any collapse timer
            const timer = partCompletionTimers.get(part.id)
            if (timer) { clearTimeout(timer); partCompletionTimers.delete(part.id) }
          } else if (part.status === 'completed') {
            // Completed parts schedule auto-collapse
            if (autoExpandedPartIds.value.has(part.id)) {
              schedulePartAutoCollapse(part.id)
            }
          }
        }
      }
    }
  },
  { immediate: true }
)

// ── Retry label for tool status ──
function toolRetryLabel(part: MessagePart): string {
  const meta = (part.metadata || {}) as Record<string, unknown>
  const retryCount = typeof meta.retry_count === 'number' ? meta.retry_count
    : typeof meta.retryCount === 'number' ? meta.retryCount : 0
  const maxRetries = typeof meta.max_retries === 'number' ? meta.max_retries
    : typeof meta.maxRetries === 'number' ? meta.maxRetries : 0
  if (part.status === 'running' && retryCount > 0) {
    return maxRetries > 0 ? `重试中 ${retryCount}/${maxRetries}` : '重试中'
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

function isSubLinePart(part: MessagePart): boolean {
  return part.partType === 'sub_line' || part.partType === 'agent_summary'
}

function agentAssistantMessageId(part: MessagePart): string {
  return `${part.id}:assistant`
}

function agentSubMessages(part: MessagePart): CoreMessage[] {
  const messages: CoreMessage[] = []
  const assignment = agentAssignmentText(part)
  if (assignment) {
    messages.push({
      id: `${part.id}:assignment`,
      role: 'user',
      content: assignment,
      timestamp: '',
      parts: [],
    })
  }

  const processParts = agentTimelineParts(part)
  const conclusion = agentConclusion(part)
  if (processParts.length > 0 || conclusion) {
    messages.push({
      id: agentAssistantMessageId(part),
      role: 'assistant',
      content: conclusion,
      timestamp: '',
      parts: processParts,
      metadata: {
        timeline: processParts.length > 0 ? true : undefined,
        live: part.status === 'running' ? true : undefined,
        liveStatus: agentStatusLabel(part),
      },
    })
  }
  return messages
}

function agentProcessExpandedIds(part: MessagePart): Set<string> {
  const messageId = agentAssistantMessageId(part)
  if (subLineProcessCollapsedIds.value.has(messageId)) return new Set()
  return new Set([messageId])
}

function toggleAgentProcess(messageId: string) {
  const next = new Set(subLineProcessCollapsedIds.value)
  if (next.has(messageId)) {
    next.delete(messageId)
  } else {
    next.add(messageId)
  }
  subLineProcessCollapsedIds.value = next
}

function attachmentParts(message: CoreMessage): MessagePart[] {
  return (message.parts || []).filter(part => part.partType === 'attachment')
}

function attachmentFromPart(part: MessagePart): CoreAttachment | null {
  const raw = part.metadata?.attachment
  if (!raw || typeof raw !== 'object') return null
  return raw as CoreAttachment
}

function attachmentName(part: MessagePart): string {
  const attachment = attachmentFromPart(part)
  return attachment?.label || attachment?.filename || part.label || 'attachment'
}

function attachmentKind(part: MessagePart): string {
  const attachment = attachmentFromPart(part)
  const previewType = String(attachment?.preview_type || '').toLowerCase()
  if (previewType === 'image') return 'IMG'
  if (previewType === 'pdf') return 'PDF'
  if (previewType === 'text') return 'TXT'
  return 'FILE'
}

function toggleToolWrap(partId: string) {
  const next = new Set(toolWrapIds.value)
  if (next.has(partId)) next.delete(partId)
  else next.add(partId)
  toolWrapIds.value = next
}

function isToolWrapEnabled(partId: string): boolean {
  return toolWrapIds.value.has(partId)
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
  if (!hasToolDisplay(part)) return false
  return isPartExpanded(part, live)
}

function contextGroupId(group: PartGroupContext): string {
  return `context-${group.items.map(item => item.id).join('-')}`
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
  if (file) chips.push(`文件 ${compactPath(String(file))}`)

  const start = args.start_line || args.startLine || args.line_start
  const end = args.end_line || args.endLine || args.line_end
  if (start && end) chips.push(`范围 ${start}-${end} 行`)
  else if (start) chips.push(`从第 ${start} 行`)

  const pattern = args.pattern || args.query
  if (pattern && !file) chips.push(`搜索 ${compactDetail(String(pattern), 44)}`)

  const command = args.command || args.cmd
  if (command) chips.push(`命令 ${compactDetail(String(command), 64)}`)

  return chips
}

function toolTypeLabel(part: MessagePart): string {
  if (isUnavailableToolNotice(part)) return 'WARN'
  if (isControlTool(part)) return 'PROC'
  const name = (part.toolName || '').toLowerCase()
  return name || 'tool'
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

function toolStatusLabel(part: MessagePart): string {
  if (part.status === 'running') return '运行中'
  if (part.status === 'error') return '失败'
  if (part.status === 'pending') return '等待中'
  return '已完成'
}

function showProcessKindTag(part: MessagePart): boolean {
  return part.partType !== 'reasoning' && part.partType !== 'plan' && part.partType !== 'todo_update' && part.partType !== 'compaction'
}

function processKindLabel(part: MessagePart): string {
  if (part.partType === 'decision') return 'ASK'
  if (isSubLinePart(part)) return 'SUB'
  if (part.partType === 'compaction') return 'CTX'
  if (isControlTool(part)) return 'PROC'
  if (part.partType === 'error') return 'ERR'
  if (part.partType === 'file_diff') return 'DIFF'
  if (part.partType === 'command_output') return 'EXEC'
  if (part.partType === 'tool_call' || part.partType === 'tool_result') return toolTypeLabel(part)
  return 'INFO'
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
  if (oldCount === 0 && newCount > 0) return `新增 ${newCount} 行`
  if (newCount === 0 && oldCount > 0) return `删除 ${oldCount} 行`
  return `修改范围：原 ${match[1]} 行起，新 ${match[3]} 行起`
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

function isInitialWaitingMessage(msg: CoreMessage): boolean {
  return !!(msg.metadata as Record<string, unknown>)?.initialWaiting
}

function isTimelineMessage(msg: CoreMessage): boolean {
  return !!(msg.metadata as Record<string, unknown>)?.timeline
}

function shouldShowShallowThinkingPending(msg: CoreMessage): boolean {
  const metadata = (msg.metadata || {}) as Record<string, unknown>
  return Boolean(metadata.shallowThinkingPending)
    && !hasReasoningContent(msg)
    && !hasAnswerContent(msg)
}

function hasReasoningContent(msg: CoreMessage): boolean {
  return (msg.parts || []).some(part => (
    part.partType === 'reasoning'
    && String(part.content || '').trim().length > 0
  ))
}

function timelineParts(msg: CoreMessage): MessagePart[] {
  return processParts(msg)
}

function latestNonEmptyModelTextPart(msg: CoreMessage): MessagePart | undefined {
  const parts = msg.parts || []
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index]
    if (part.partType !== 'model_text') continue
    const content = normalizedBodyText(part.content)
    if (!content) continue
    return part
  }
  return undefined
}

function normalizedBodyText(value: unknown): string {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function currentBodyModelTextPart(msg: CoreMessage): MessagePart | undefined {
  const latest = latestNonEmptyModelTextPart(msg)
  if (!latest) return undefined
  const explicitBody = normalizedBodyText(msg.content)
  if (!explicitBody || isLiveMessage(msg)) return latest
  return normalizedBodyText(latest.content) === explicitBody ? latest : undefined
}

function processParts(msg: CoreMessage): MessagePart[] {
  // All parts are rendered inline chronologically — no body filtering.
  return msg.parts || []
}

function answerTextKey(msg: CoreMessage): string {
  return currentBodyModelTextPart(msg)?.id || msg.id
}

function systemBubbleClass(msg: CoreMessage): string {
  const meta = (msg.metadata || {}) as Record<string, unknown>
  if (meta.systemKind === 'error' || meta.systemKind === 'failed') return 'system-bubble--error'
  if (meta.systemKind === 'done' || meta.systemKind === 'completed') return 'system-bubble--done'
  if (meta.systemKind === 'waiting') return 'system-bubble--waiting'
  return 'system-bubble--info'
}

function systemIcon(msg: CoreMessage): string {
  const meta = (msg.metadata || {}) as Record<string, unknown>
  if (meta.systemKind === 'error' || meta.systemKind === 'failed') return '✕'
  if (meta.systemKind === 'done' || meta.systemKind === 'completed') return '✓'
  if (meta.systemKind === 'waiting') return '⏳'
  return 'ℹ'
}

function isProcessExpanded(msg: CoreMessage): boolean {
  // During live streaming: auto-expand so user sees process unfolding (like GPT)
  if (isLiveMessage(msg)) return true
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
  return /decision_point|write_checklist|update_checklist|verify_design|ask_clarification|chat_only|self_critique/.test(name)
}

// ── Body/process projection: newest model text owns the body; replaced text becomes process ──

interface PartGroupProcess {
  kind: 'process'
  part: MessagePart
}

interface PartGroupContext {
  kind: 'context-group'
  status: MessagePartStatus
  label: string
  detail: string
  items: MessagePart[]
}

interface PartGroupProcessGroup {
  kind: 'process-group'
  parts: MessagePart[]
  summary: string
}

type PartGroup = PartGroupProcess | PartGroupContext | PartGroupProcessGroup

interface TextGroup {
  content: string
}

interface LiveProcessItem {
  id: string
  title: string
  detail: string
  status: MessagePartStatus
  compact: boolean
}

function liveStatusText(msg: CoreMessage): string {
  const metadata = (msg.metadata || {}) as Record<string, unknown>
  return String(metadata.liveStatus || metadata.statusText || '正在处理')
}

function liveDetailText(msg: CoreMessage): string {
  const metadata = (msg.metadata || {}) as Record<string, unknown>
  return String(metadata.liveDetail || metadata.detail || '').trim()
}

function hasAnswerContent(msg: CoreMessage): boolean {
  if (answerContent(msg)) return true
  return textGroups(processParts(msg)).some(group => group.content.trim())
}

function terminalErrorText(msg: CoreMessage): string {
  const parts = msg.parts || []
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index]
    if (part.partType !== 'status' || part.status !== 'error') continue
    return String(part.detail || part.content || '').trim()
  }
  return ''
}

function answerContent(msg: CoreMessage): string {
  const liveModelText = currentBodyModelTextPart(msg)
  if (isLiveMessage(msg) && liveModelText) return String(liveModelText.content || '').trim()
  const explicitBody = String(msg.content || '').trim()
  if (explicitBody) return explicitBody
  return String(liveModelText?.content || '').trim()
}

function liveProcessItems(msg: CoreMessage): LiveProcessItem[] {
  const parts = processParts(msg)
  if (hasAnswerContent(msg)) {
    return parts
      .filter(isHighValueLivePart)
      .map((part): LiveProcessItem => ({
        id: part.id,
        title: livePartTitle(part),
        detail: livePartDetail(part),
        status: part.status,
        compact: part.status === 'completed',
      }))
      .slice(-8)
  }

  const groups = groupParts(parts)
  const items = groups.map((group): LiveProcessItem => {
    if (group.kind === 'context-group') {
      return {
        id: `context-${group.items.map((item) => item.id).join('-')}`,
        title: group.label,
        detail: group.detail,
        status: group.status,
        compact: group.status === 'completed',
      }
    }
    return {
      id: group.part.id,
      title: livePartTitle(group.part),
      detail: livePartDetail(group.part),
      status: group.part.status,
      compact: group.part.status === 'completed',
    }
  })
  return items.slice(-8)
}

function isHighValueLivePart(part: MessagePart): boolean {
  if (isLowValueControlResult(part, String(part.detail || part.content || part.toolResult || ''))) return false
  if (part.partType === 'text' || part.partType === 'reasoning' || part.partType === 'model_text' || part.partType === 'plan' || part.partType === 'todo_update') {
    return false
  }
  if (part.partType === 'status') return true
  if (part.partType === 'compaction') return true
  if (part.partType === 'tool_call' || part.partType === 'tool_result' || part.partType === 'file_diff' || part.partType === 'command_output') {
    return true
  }
  if (isSubLinePart(part) || part.partType === 'decision' || part.partType === 'error') {
    return true
  }
  return Boolean(part.toolName || part.toolResult || part.toolError)
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
  return map[part.partType] || '处理中'
}

function livePartDetail(part: MessagePart): string {
  const detail = String(part.detail || part.content || part.toolError || part.toolResult || '').trim()
  if (detail) return detail
  if (part.toolArgs && Object.keys(part.toolArgs).length > 0) return toolArgsPreview(part.toolArgs)
  return ''
}

function modelTextTitle(part: MessagePart): string {
  const label = String(part.label || '').trim()
  if (!label) return '正文'
  const normalized = label.toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ')
  if (normalized === 'model text' || normalized === 'agent message' || normalized === 'agentmessage') {
    return '正文'
  }
  return label
}

function readableProcessTitle(part: MessagePart): string {
  const unavailableTool = unavailableToolName(part)
  if (unavailableTool) return `工具不可用：${unavailableTool}`
  if (isUnavailableToolNotice(part)) return '工具不可用'
  if (part.partType === 'decision') return decisionTitle(part)
  if (isSubLinePart(part)) return agentTitle(part)
  if (part.partType === 'compaction') return part.label || '上下文已压缩'
  if (isControlTool(part)) return controlTitle(part)
  if (part.partType === 'error') return part.label || '出错'
  if (part.partType === 'status') return part.label || '状态'
  if (part.partType === 'model_text') return modelTextTitle(part)
  if (part.partType === 'reasoning') return part.label || '思考'
  if (part.partType === 'file_diff') return part.label || '文件改动'
  if (part.partType === 'command_output') return part.label || '命令输出'

  if (part.partType === 'tool_call' || part.partType === 'tool_result') {
    const target = processTarget(part)
    const name = (part.toolName || part.label || '').toLowerCase()
    const actionTitle = processActionTitle(name, target)
    if (actionTitle) return actionTitle
    if (/command|shell|exec|bash|powershell|run|npm|python/.test(name)) return target ? `命令 ${target}` : part.toolName || '命令'
    return part.toolName || part.label || livePartTitle(part)
  }

  const target = processTarget(part)
  const name = (part.toolName || part.label || '').toLowerCase()
  const actionTitle = processActionTitle(name, target)
  if (actionTitle) return actionTitle
  if (/command|shell|exec|bash|powershell|run|npm|python/.test(name)) return target ? `命令 ${target}` : '命令'
  if (/agent|subagent/.test(name)) return target ? `Agent：${target}` : 'Agent'
  return part.label || part.toolName || livePartTitle(part)
}

function processActionTitle(name: string, target: string): string {
  if (/read|cat|get-content|open/.test(name)) return target ? `读取 ${target}` : '读取文件'
  if (/list|ls|dir/.test(name)) return target ? `列出 ${target}` : '列出目录'
  if (/grep|rg|search|find|glob/.test(name)) return target ? `搜索 ${target}` : '搜索内容'
  if (/write|create/.test(name)) return target ? `写入 ${target}` : '写入文件'
  if (/edit|patch|apply/.test(name)) return target ? `修改 ${target}` : '修改文件'
  if (/delete|remove/.test(name)) return target ? `删除 ${target}` : '删除内容'
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
    return `${reason === 'no_gain' ? '未获得收益 · ' : ''}原上下文已保留`
  }
  if (status === 'failed') {
    const failure = String(
      rawPart.message || rawPart.error || metadata.message || metadata.error || part.detail || '',
    ).trim()
    return failure ? `原上下文已保留 · ${compactDetail(failure, 180)}` : '原上下文已保留'
  }
  if (status === 'running') return ''
  const before = rawPart.before_tokens ?? rawPart.beforeTokens ?? metadata.before_tokens ?? metadata.beforeTokens
  const after = rawPart.after_tokens ?? rawPart.afterTokens ?? metadata.after_tokens ?? metadata.afterTokens
  const segments = rawPart.segments ?? metadata.segments
  const pieces: string[] = []
  if (typeof before === 'number' && typeof after === 'number') {
    pieces.push(`${before} → ${after} tokens`)
  } else if (part.detail) {
    pieces.push(String(part.detail))
  }
  if (typeof segments === 'number' && segments > 1) pieces.push(`${segments} 段`)
  return pieces.join(' · ')
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
  if (status === 'running') return '正在压缩上下文'
  if (status === 'not_needed') return '无需压缩'
  if (status === 'failed') return '压缩未完成'
  return '上下文已压缩'
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
  if (!preview) return '生成工具输入'
  const field = preview.field ? `生成 ${preview.field}` : '生成工具输入'
  const chars = Number.isFinite(preview.chars) ? `${preview.chars} chars` : ''
  const truncated = preview.truncated ? '已截断' : ''
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

function fileArtifactContent(part: MessagePart): string {
  const artifact = fileArtifact(part)
  return typeof artifact?.content === 'string' ? artifact.content.trim() : ''
}

function fileArtifactMetaText(part: MessagePart): string {
  const artifact = fileArtifact(part)
  const meta = artifact?.metadata || {}
  const segments: string[] = []
  const action = String(meta.action || '')
  if (action === 'create') segments.push('新增')
  else if (action === 'overwrite') segments.push('覆盖')
  else if (action === 'edit') segments.push('编辑')
  const lineCount = meta.line_count ?? meta.new_line_count
  if (typeof lineCount === 'number') segments.push(`${lineCount} 行`)
  if (typeof meta.size_bytes === 'number') segments.push(`${meta.size_bytes} B`)
  if (meta.truncated === true) segments.push('已截断')
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
  if (meta.passed === true) return '测试通过'
  if (meta.summary === 'timed_out') return '测试超时'
  return '测试失败'
}

function testResultCommand(part: MessagePart): string {
  const command = testArtifactMetadata(part).command || part.toolArgs?.command || ''
  return command ? compactDetail(String(command), 120) : '未提供命令'
}

function testResultMeta(part: MessagePart): string[] {
  const meta = testArtifactMetadata(part)
  const items: string[] = []
  if (meta.exit_code !== undefined && meta.exit_code !== null) items.push(`退出码 ${meta.exit_code}`)
  if (typeof meta.duration_seconds === 'number') items.push(`${meta.duration_seconds.toFixed(2)} 秒`)
  if (meta.timed_out === true) items.push('超时')
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
    .replace(/^file:\s*/i, '文件 · ')
    .replace(/^END OF FILE\b\s*[—-]?\s*/i, '文件结束 · ')
    .replace(/^exit_code[:\]\s]*/i, '退出码 ')
    .replace(/^duration_seconds[:\]\s]*/i, '耗时 ')
    .replace(/^timed_out[:\]\s]*/i, '超时 ')
    .replace(/^command[:\]\s]*/i, '命令 ')
    .replace(/^cwd[:\]\s]*/i, '目录 ')
    .replace(/\blines\b/g, '行')
    .replace(/\bmodified\b/g, '修改于')
    .replace(/\bbytes read successfully\b/g, '字节读取完成')
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
  return `工具 ${name} 不可用：请求了当前环境没有注册的工具。`
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
  if (display && index) return `${index} · ${display}`
  if (display) return display
  if (index) return `${index} · sub`
  return 'sub'
}

function agentStatusLabel(part: MessagePart): string {
  if (part.status === 'running') return '运行中'
  if (part.status === 'error') return '失败'
  if (part.status === 'pending') return '等待'
  return '完成'
}

function agentDeliveryMeta(part: MessagePart): string[] {
  const meta = part.metadata || {}
  const diagnostics = metadataRecord(meta.diagnostics)
  const delivery = metadataRecord(diagnostics.workspace_delivery || meta.workspace_delivery || meta.workspaceDelivery)
  const items: string[] = []
  if (delivery.ok === false) items.push('失败')
  else if (delivery.ok === true || delivery.needs_acceptance === true || delivery.merged === true) items.push('完成')
  const branch = String(delivery.branch || meta.branch || '').trim()
  if (branch) items.push(`分支 ${compactDetail(branch, 36)}`)
  const paths = Array.isArray(delivery.paths) ? delivery.paths : []
  if (paths.length > 0) items.push(`${paths.length} 个文件`)
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
      title: '思考',
      detail: block,
      status: 'completed',
      kind: 'reasoning',
    })
  }
  for (const [index, step] of agentSubsteps(part).entries()) {
    items.push({
      id: `step-${index}`,
      title: step.label || '执行步骤',
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
      title: valid === false ? '候选结论' : '结论',
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
        title: agentToolLabel(name) || name || '工具',
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
      label: String(item.label || item.title || '步骤'),
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
  const text = String(part.content || part.toolResult || part.detail || '').trim()
  if (!text) return ''
  return text
}

function controlTitle(part: MessagePart): string {
  const name = (part.toolName || part.label || '').toLowerCase()
  const args = part.toolArgs || {}
  if (name.includes('write_checklist')) {
    const steps = Array.isArray(args.steps) ? args.steps.length : 0
    return steps > 0 ? `计划：${steps} 步` : '计划'
  }
  if (name.includes('update_checklist')) return part.status === 'error' ? '计划更新失败' : '更新计划'
  if (name.includes('verify_design')) return part.status === 'error' ? '验证未通过' : '验证'
  if (name.includes('decision_point') || name.includes('ask_clarification')) return decisionTitle(part)
  if (name.includes('self_critique')) return '自检'
  return part.label || '过程'
}

function isChecklistPart(part: MessagePart): boolean {
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

function decisionTitle(part: MessagePart): string {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const title = args.title || args.question || meta.title || meta.question || part.label
  return title ? `需要确认：${compactDetail(String(title), 56)}` : '等待确认'
}

function decisionStatusLabel(part: MessagePart): string {
  if (part.status === 'pending') return '等待选择'
  if (part.status === 'running') return '处理中'
  if (part.status === 'error') return '失败'
  return '已记录'
}

function decisionResponseText(part: MessagePart): string {
  const response = decisionResponse(part)
  if (!response) return ''
  const action = String(response.action || '').toLowerCase()
  const rawText = String(response.response || '').trim()
  const labels: Record<string, string> = {
    approve: '批准',
    deny: '拒绝',
    guide: '其他',
  }
  const label = labels[action] || compactDetail(action || rawText || '已处理', 32)
  if (action === 'guide' && rawText && rawText !== action) {
    return `已选择：${label} - ${compactDetail(rawText, 160)}`
  }
  return `已选择：${label}`
}

function decisionResponse(part: MessagePart): Record<string, unknown> | null {
  const meta = part.metadata || {}
  const response = meta.waitingResponse
  if (response && typeof response === 'object' && !Array.isArray(response)) {
    return response as Record<string, unknown>
  }
  const waitingRequest = meta.waitingRequest
  if (waitingRequest && typeof waitingRequest === 'object' && !Array.isArray(waitingRequest)) {
    const nested = (waitingRequest as Record<string, unknown>).response
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
      return nested as Record<string, unknown>
    }
  }
  return null
}

function decisionDetail(part: MessagePart): string {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const detail = args.reason || args.description || meta.reason || meta.description || part.detail || part.content
  const title = args.title || args.question || meta.title || meta.question || part.label
  if (!detail || detail === title) return ''
  return compactDetail(String(detail), 240)
}

function decisionOptions(part: MessagePart): DecisionOption[] {
  const args = part.toolArgs || {}
  const meta = part.metadata || {}
  const raw = args.options || meta.options
  if (!Array.isArray(raw)) {
    return part.status === 'pending'
      ? [{ id: 'confirm', label: '确认并继续', description: '按当前方案继续执行' }]
      : []
  }
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
    .map((item, index) => ({
      id: String(item.id || item.value || `option-${index + 1}`),
      label: String(item.label || item.title || item.id || `选项 ${index + 1}`),
      description: String(item.description || item.detail || ''),
      response: item.response ? String(item.response) : undefined,
    }))
    .filter(option => option.label)
}

function decisionOptionResponse(part: MessagePart, option: DecisionOption): string {
  if (option.response) return option.response
  const title = decisionTitle(part).replace(/^需要确认：/, '')
  const lines = [`我选择：${option.label}`]
  if (option.description) lines.push(`原因/说明：${option.description}`)
  if (title && title !== '等待确认') lines.push(`对应决策：${title}`)
  return lines.join('\n')
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
}

function submitDecisionGuide(part: MessagePart): void {
  const response = decisionGuideDraft(part).trim()
  if (!response) return
  emit('decision-select', {
    partId: part.id,
    option: {
      id: 'guide',
      label: '其他',
      response: 'guide',
    },
    response,
  })
  decisionGuideDrafts.value = {
    ...decisionGuideDrafts.value,
    [part.id]: '',
  }
}

function processTarget(part: MessagePart): string {
  const args = part.toolArgs || {}
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

function groupParts(parts: MessagePart[]): (PartGroupProcess | PartGroupContext)[] {
  const groups: (PartGroupProcess | PartGroupContext)[] = []
  let contextBatch: MessagePart[] = []

  function flushContext() {
    if (contextBatch.length === 0) return
    const allDone = contextBatch.every(p => p.status === 'completed' || p.status === 'error')
    const counts = countContextTools(contextBatch)
    groups.push({
      kind: 'context-group',
      status: allDone ? 'completed' : 'running',
      label: 'Context',
      detail: formatContextSummary(counts),
      items: [...contextBatch],
    })
    contextBatch = []
  }

  for (const part of parts) {
    const name = part.toolName || ''
    if (CONTEXT_TOOLS.has(name)) {
      contextBatch.push(part)
    } else if (part.partType === 'text' || !part.partType) {
      // Text parts are rendered from msg.content — skip here
    } else {
      flushContext()
      groups.push({ kind: 'process', part })
    }
  }
  flushContext()
  return groups
}

// ── Compact process group summary ──

function computeProcessGroupSummary(parts: MessagePart[]): string {
  let reasoningSeconds = 0
  let reasoningCount = 0
  let toolCount = 0
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
      toolCount++
    }
  }
  if (hasRunning) {
    if (reasoningCount > 0 && toolCount > 0) {
      return `思考中…，已调用${toolCount}个工具`
    }
    if (toolCount > 0) {
      return `已调用${toolCount}个工具…`
    }
    if (reasoningCount > 0) {
      return `思考中…`
    }
    return '处理中…'
  }
  if (reasoningCount > 0 && toolCount > 0) {
    return `思考了${reasoningSeconds}s，调用了${toolCount}个工具`
  }
  if (toolCount > 0) {
    return `连续调用了${toolCount}个工具`
  }
  if (reasoningCount > 0) {
    return `思考了${reasoningSeconds}s`
  }
  return ''
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
    if (g.kind === 'context-group') {
      flush()
      result.push(g)
    } else if (g.kind === 'process') {
      const pt = g.part.partType
      if (pt === 'reasoning' || pt === 'tool_call' || pt === 'tool_result') {
        batch.push(g.part)
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
  const meta = (msg.metadata || {}) as Record<string, unknown>
  const metrics = ((meta.processMetrics || meta.runtime_metrics || {}) as Record<string, unknown>) || {}
  const durationMs = numberMetric(metrics.duration_ms ?? metrics.durationMs)
  const inputTokens = numberMetric(metrics.input_tokens ?? metrics.inputTokens ?? metrics.prompt_tokens ?? metrics.promptTokens)
  const outputTokens = numberMetric(metrics.output_tokens ?? metrics.outputTokens ?? metrics.completion_tokens ?? metrics.completionTokens)
  const totalTokens = numberMetric(metrics.total_tokens ?? metrics.totalTokens) >= 0
    ? numberMetric(metrics.total_tokens ?? metrics.totalTokens)
    : inputTokens >= 0 || outputTokens >= 0
      ? Math.max(inputTokens, 0) + Math.max(outputTokens, 0)
      : -1
  const llmCalls = numberMetric(metrics.llm_calls ?? metrics.llmCalls ?? metrics.model_calls ?? metrics.modelCalls)
  const cacheHitRate = cacheHitRateMetric(metrics, inputTokens)
  const segments: string[] = []
  if (llmCalls >= 0) segments.push(`模型调用 ${formatCount(llmCalls)} 次`)
  if (durationMs >= 0) segments.push(`耗时 ${formatSeconds(durationMs)} s`)
  if (totalTokens >= 0) segments.push(`Token ${formatCount(totalTokens)}`)
  if (cacheHitRate >= 0) segments.push(`命中率 ${formatPercent(cacheHitRate)}`)
  return segments.length > 0 ? segments : processFallbackSegments(msg)
}

function cacheHitRateMetric(metrics: Record<string, unknown>, inputTokens: number): number {
  const direct = numberMetric(metrics.cache_hit_rate ?? metrics.cacheHitRate)
  if (direct >= 0) return direct
  const cachedTokens = numberMetric(metrics.cached_tokens ?? metrics.cachedTokens)
  if (cachedTokens >= 0 && inputTokens > 0) return cachedTokens / inputTokens
  if (inputTokens >= 0) return 0
  return -1
}

function numberMetric(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return -1
}

function formatSeconds(ms: number): string {
  if (ms < 0) return 'X'
  if (ms === 0) return '0'
  return String(Math.max(1, Math.round(ms / 1000)))
}

function formatCount(value: number): string {
  return value >= 0 ? String(Math.round(value)) : 'X'
}

function formatPercent(value: number): string {
  if (value < 0) return 'X'
  const normalized = value > 1 ? value : value * 100
  if (!Number.isFinite(normalized)) return 'X'
  return `${Math.round(normalized)}%`
}

function processFallbackSegments(msg: CoreMessage): string[] {
  const counts = processItemCounts(processParts(msg))
  const segments: string[] = []
  if (counts.toolCalls > 0) segments.push(`${counts.toolCalls} 个工具`)
  if (counts.reasoning > 0) segments.push(`${counts.reasoning} 段思考`)
  if (counts.context > 0) segments.push(`${counts.context} 次上下文`)
  if (counts.compaction > 0) segments.push(`${counts.compaction} 次压缩`)
  if (counts.failed > 0) segments.push(`${counts.failed} 个失败`)
  if (segments.length > 0) return segments
  return [`${counts.total} 个过程`]
}

function processItemCounts(parts: MessagePart[]): {
  total: number
  toolCalls: number
  reasoning: number
  context: number
  compaction: number
  failed: number
} {
  let total = 0
  let toolCalls = 0
  let reasoning = 0
  let context = 0
  let compaction = 0
  let failed = 0

  for (const part of parts) {
    if (part.partType === 'text' || !part.partType) continue
    total++
    if (part.status === 'error') failed++
    const name = part.toolName || ''
    if (CONTEXT_TOOLS.has(name)) {
      context++
    } else if (part.partType === 'compaction') {
      compaction++
    } else if (part.partType === 'reasoning') {
      reasoning++
    } else if (part.partType === 'tool_call' || part.partType === 'tool_result') {
      toolCalls++
    }
  }
  return { total, toolCalls, reasoning, context, compaction, failed }
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
.chat-thread {
  width: min(var(--content-width), 100%);
  margin: 0 auto;
  display: grid;
  grid-auto-rows: max-content;
  align-content: start;
  gap: 16px;
  min-width: 0;
}

/* ── System messages ── */
.chat-thread .system-row {
  display: flex;
  justify-content: center;
  padding: 8px 16px;
}
.system-bubble {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  border-radius: var(--radius-lg);
  font-size: 13px;
  max-width: 640px;
  line-height: 1.45;
}
.system-bubble--info {
  background: color-mix(in srgb, var(--blue) 12%, transparent);
  color: var(--blue);
  border: 1px solid color-mix(in srgb, var(--blue) 25%, transparent);
}
.system-bubble--done {
  background: color-mix(in srgb, var(--green) 12%, transparent);
  color: var(--green);
  border: 1px solid color-mix(in srgb, var(--green) 25%, transparent);
}
.system-bubble--error {
  background: color-mix(in srgb, var(--red) 14%, transparent);
  color: var(--red);
  border: 1px solid color-mix(in srgb, var(--red) 30%, transparent);
}
.system-bubble--waiting {
  background: color-mix(in srgb, var(--orange) 12%, transparent);
  color: var(--orange);
  border: 1px solid color-mix(in srgb, var(--orange) 25%, transparent);
}
.system-icon {
  font-size: 14px;
  flex-shrink: 0;
}
.assistant-terminal-error {
  display: flex;
  gap: 8px;
  margin: 8px 0 4px;
  padding: 8px 10px;
  border-left: 2px solid color-mix(in srgb, var(--red) 72%, transparent);
  background: color-mix(in srgb, var(--red) 7%, transparent);
  color: color-mix(in srgb, var(--red) 78%, var(--theme-main-text, #fff) 22%);
  font-size: 12px;
  line-height: 1.5;
}
.assistant-terminal-error__label {
  flex: none;
  font-weight: 700;
}
.shallow-thinking-pending {
  display: inline-flex;
  align-items: baseline;
  min-width: 0;
  color: color-mix(in srgb, var(--green) 72%, var(--theme-main-text, #fff) 28%);
  font-size: 12px;
  font-weight: 650;
  line-height: 1.45;
}
.shallow-thinking-pending--process {
  margin-left: 22px;
}
.shallow-thinking-pending-row {
  padding: 1px 0 2px;
}
.reasoning-body--pending {
  margin-top: 0;
  margin-bottom: 4px;
  padding-bottom: 0;
}
.shallow-thinking-dots {
  display: inline-flex;
  width: 1.2em;
}
.shallow-thinking-dots span {
  animation: shallow-thinking-dot 1.2s ease-in-out infinite;
}
.shallow-thinking-dots span:nth-child(2) {
  animation-delay: .15s;
}
.shallow-thinking-dots span:nth-child(3) {
  animation-delay: .3s;
}

/* ── Process step color coding ── */
.process-step--completed .process-step-marker {
  background: var(--green);
  box-shadow: 0 0 6px color-mix(in srgb, var(--green) 50%, transparent);
}
.process-step--error .process-step-marker {
  background: var(--red);
  box-shadow: 0 0 6px color-mix(in srgb, var(--red) 50%, transparent);
}
.process-step--running .process-step-marker {
  background: var(--blue);
  animation: process-pulse 1.4s ease-in-out infinite;
}
.process-step--pending .process-step-marker {
  background: var(--muted);
}
@keyframes process-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .4; }
}
@keyframes shallow-thinking-dot {
  0%, 70%, 100% { opacity: .28; }
  35% { opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .shallow-thinking-dots span {
    animation: none;
    opacity: 1;
  }
}

/* ── Part dot status colors ── */
.part-dot--completed { color: var(--green); }
.part-dot--error { color: var(--red); }
.part-dot--running { color: var(--blue); }

/* ── Expandable tool cards ── */
.process-stream--history {
  align-items: stretch;
  counter-reset: reasoning-step;
}
.process-stream--live,
.process-stream--inline {
  counter-reset: reasoning-step;
}
.process-stream--history .process-step {
  max-width: 100%;
}
.chat-thread .process-stream--history .process-step--context,
.chat-thread .process-stream--history .process-step--tool {
  display: block !important;
  grid-template-columns: none !important;
}
.process-step--tool {
  display: block;
  width: 100%;
  min-width: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  padding: 0;
  box-shadow: none;
  overflow: visible;
}
.process-stream--history .process-step--tool + .process-step--tool {
  margin-top: 2px;
}
.process-stream--history .process-step--tool:has(.tool-card-header--command) + .process-step--tool,
.process-stream--history .process-step--tool + .process-step--tool:has(.tool-card-header--command) {
  margin-top: 8px;
}
.tool-card-header {
  position: relative;
  z-index: 0;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  min-height: 28px;
  display: grid;
  grid-template-columns: 12px minmax(0, max-content) minmax(0, 1fr) minmax(12px, max-content);
  grid-template-areas:
    "marker type title chevron"
    ". args args args";
  align-items: center;
  column-gap: 6px;
  row-gap: 4px;
  border: none;
  background: none;
  color: inherit;
  cursor: default;
  padding: 1px 0 7px;
  font-size: inherit;
  text-align: left;
  overflow: hidden;
}
.tool-card-header .process-step-marker {
  grid-area: marker;
}
.tool-card-header .tool-type-tag {
  grid-area: type;
}
.tool-card-header .process-step-title {
  grid-area: title;
  min-width: 0;
}
.tool-card-header .process-step-title:empty {
  display: none;
}
.tool-card-header .tool-expand-chevron {
  grid-area: chevron;
  justify-self: end;
  align-self: center;
}
.tool-card-header.has-detail {
  cursor: pointer;
}
.tool-card-header.has-detail:hover .process-step-title {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 86%, transparent);
}
.process-tool-row {
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: nowrap;
  gap: 8px;
  border-radius: 0;
  background: transparent;
  padding: 4px 6px;
  transition: background-color 160ms ease-out, color 160ms ease-out;
}
.tool-row-name {
  flex: 0 0 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 82%, transparent);
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 650;
}
.process-tool-row .process-step-title {
  flex: 0 1 auto;
}
.process-tool-row.has-detail:hover {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 4%, transparent);
}
.process-tool-row:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 72%, transparent);
  outline-offset: 1px;
}
.tool-row-summary {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 450;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 58%, transparent);
}
.tool-row-args {
  display: none;
}
.tool-row-status {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-size: 11px;
  font-weight: 550;
  white-space: nowrap;
}
.tool-row-status--retry {
  color: var(--orange);
  cursor: pointer;
}

/* ── Model retry progress bar ── */
.model-retry-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
}
.model-retry-bar__label {
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 550;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 44%, transparent);
  white-space: nowrap;
}
.model-retry-bar__track {
  flex: 0 1 auto;
  display: flex;
  gap: 1px;
  height: 4px;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 6%, transparent);
  border-radius: 2px;
}
.model-retry-bar__segment {
  flex: 0 0 2px;
  height: 100%;
  background: transparent;
  border-radius: 0.5px;
  transition: background-color 0.2s ease;
}
.model-retry-bar__segment--filled {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 26%, transparent);
}
.tool-card-header--command .tool-type-tag {
  grid-area: type;
  min-width: 0;
  max-width: min(160px, 36vw);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 1px 5px;
  border-radius: 3px;
  background: color-mix(in srgb, #ff9142 20%, transparent);
  color: #ff9142;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .5px;
}
.tool-card-header--command .process-step-title {
  grid-area: title;
  font-weight: 600;
}
.tool-card-header--command .process-step-marker {
  background: color-mix(in srgb, #ff9142 20%, transparent);
  color: #ff9142;
}
.process-step--tool .process-step-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0;
  color: var(--theme-main-text, var(--text));
}
.tool-expand-chevron {
  flex: 0 0 auto;
  align-self: start;
  font-size: 10px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  justify-self: end;
}
.tool-card-body {
  position: relative;
  z-index: 0;
  clear: both;
  margin-top: 8px;
  padding-left: 0;
  width: 100%;
  min-width: 0;
  overflow: auto;
  max-height: 800px;
  opacity: 1;
  transition: max-height 0.28s cubic-bezier(0.2, 0.8, 0.2, 1),
              opacity 0.22s ease,
              margin 0.28s cubic-bezier(0.2, 0.8, 0.2, 1),
              padding 0.28s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.tool-card-body--closed {
  max-height: 0;
  opacity: 0;
  margin-top: 0;
  margin-bottom: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.tool-card-body--row {
  margin: 2px 0 10px 18px;
  width: calc(100% - 18px);
}
.tool-color--warn + .tool-card-body,
.tool-color--warn .tool-card-body {
  opacity: .82;
}
.process-inline-toggle {
  grid-column: 1 / -1;
  display: flex;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  min-width: 0;
  border: 0;
  background: transparent;
  color: inherit;
  padding: 0;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.process-inline-toggle .process-step-title {
  flex: 0 0 auto;
}
.process-inline-toggle .process-step-detail {
  flex: 1 1 auto;
  min-width: 0;
}
.process-detail-panel {
  grid-column: 1 / -1;
  margin: 6px 0 8px 22px;
  position: relative;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--bg) 34%, transparent);
}
.process-detail-panel--error {
  border-color: color-mix(in srgb, var(--red) 32%, transparent);
}
.process-detail-panel pre {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  padding: 28px 10px 9px;
  color: var(--theme-main-text, var(--text));
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
.process-detail-copy {
  position: absolute;
  top: 5px;
  right: 6px;
  min-height: 20px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 12%, transparent);
  border-radius: 4px;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 6%, transparent);
  color: color-mix(in srgb, var(--theme-main-text, #fff) 70%, transparent);
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
}
.process-step--error .process-step-detail {
  white-space: normal;
  overflow: visible;
  text-overflow: clip;
  word-break: break-word;
}
.process-step--context {
  display: block;
  width: 100%;
  min-width: 0;
}
.context-group-header {
  width: 100%;
  display: grid;
  grid-template-columns: auto minmax(0, max-content) minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  border: none;
  background: none;
  color: inherit;
  padding: 0;
  font-size: inherit;
  cursor: pointer;
  text-align: left;
}
.context-group-header .process-step-detail {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.context-group-header:hover .process-step-title {
  text-decoration: underline;
  text-underline-offset: 2px;
}
.context-tool-list {
  display: grid;
  gap: 2px;
  margin-top: 6px;
  padding-left: 24px;
  min-width: 0;
}
.context-tool-row {
  min-width: 0;
  width: 100%;
  padding: 5px 0 7px;
  overflow: hidden;
}
.context-tool-head {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(84px, max-content) minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}
.context-tool-head .tool-args-preview {
  display: none;
}
.context-tool-output {
  margin-top: 4px;
  max-height: 220px;
  overflow: auto;
}
.tool-output {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: var(--theme-main-soft-background, color-mix(in srgb, var(--theme-main-text, #fff) 5%, transparent));
  border: 1px solid var(--theme-main-border, color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent));
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  color: var(--theme-main-text, var(--text));
  max-height: 320px;
  overflow: auto;
}
.tool-output-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  width: 100%;
  max-width: 100%;
  margin-bottom: 7px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 62%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.4;
}
.tool-output-meta span {
  min-width: 0;
  padding: 2px 7px;
  border: 1px solid var(--theme-main-border, color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent));
  border-radius: 5px;
  background: var(--theme-main-subtle-background, color-mix(in srgb, var(--theme-main-text, #fff) 4%, transparent));
  white-space: normal;
  overflow-wrap: anywhere;
}
.tool-output-content {
  margin: 0;
  font: inherit;
  color: inherit;
  white-space: pre;
  word-break: normal;
  min-width: max-content;
  cursor: pointer;
}
.tool-output-content--wrap {
  white-space: pre-wrap;
  word-break: break-word;
  min-width: 0;
}
.tool-output--error {
  border-color: color-mix(in srgb, var(--red) 30%, transparent);
  background: color-mix(in srgb, var(--red) 6%, transparent);
  color: var(--red);
  cursor: pointer;
  user-select: all;
}
.tool-output--error:hover {
  background: color-mix(in srgb, var(--red) 10%, transparent);
}
.tool-card-body--row .tool-output,
.context-tool-output {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.tool-card-body--row .tool-output-meta span,
.context-tool-output .tool-output-meta span {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.tool-card-body--row .tool-output--error {
  background: transparent;
}
.command-output {
  width: 100%;
  min-width: 0;
  display: grid;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 18%, transparent);
  border-radius: 10px;
  background: #050806;
  color: #6ee36b;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
.command-terminal-chrome {
  min-width: 0;
  min-height: 32px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
  background: linear-gradient(180deg, #2f3438 0%, #24282c 100%);
}
.command-terminal-light {
  width: 10px;
  height: 10px;
  flex: 0 0 auto;
  border-radius: 999px;
}
.command-terminal-light--close {
  background: #ff5f56;
}
.command-terminal-light--minimize {
  background: #ffbd2e;
}
.command-terminal-light--maximize {
  background: #27c93f;
}
.command-terminal-title {
  min-width: 0;
  margin-left: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  font-weight: 650;
  line-height: 1;
  color: rgba(255, 255, 255, 0.62);
}
.command-terminal-body {
  min-width: 0;
  display: grid;
  gap: 10px;
  padding: 13px 15px 15px;
  background:
    radial-gradient(circle at 18px 18px, rgba(110, 227, 107, 0.08), transparent 34px),
    #050806;
}
.command-output-command {
  min-width: 0;
  display: block;
  overflow-wrap: anywhere;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.45;
  font-weight: 720;
  color: #75ec72;
  text-shadow: 0 0 8px rgba(117, 236, 114, 0.2);
}
.command-output-result {
  min-width: 0;
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.5;
  font-weight: 400;
  color: #6ee36b;
  text-shadow: 0 0 8px rgba(110, 227, 107, 0.16);
}

.process-step--model-text {
  width: 100%;
  min-width: 0;
  display: grid;
  gap: 6px;
  padding: 2px 0 8px;
}

.process-text-head {
  min-width: 0;
  display: inline-grid;
  grid-template-columns: max-content minmax(0, max-content);
  align-items: center;
  gap: 7px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 62%, transparent);
  font-size: 12px;
  line-height: 1.35;
  font-weight: 680;
}

.process-step--model-text .process-step-marker {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 42%, transparent);
}

.process-text-content {
  display: block;
  min-width: 0;
  margin-left: 20px;
  max-width: 76ch;
  color: var(--theme-main-text, var(--text));
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.checklist-card {
  min-width: 0;
  display: grid;
  gap: 8px;
  padding: 10px 11px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 4%, transparent);
}

.decision-card {
  --decision-attention: color-mix(in srgb, #b49a60 72%, var(--theme-main-text, #fff) 28%);
  min-width: 0;
  display: grid;
  gap: 9px;
  padding: 7px 0 9px 14px;
  border-left: 2px solid color-mix(in srgb, var(--theme-main-text, #fff) 18%, transparent);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.decision-card-head,
.checklist-card-head {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.decision-card-title {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--theme-main-text, var(--text));
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
}

.decision-card-status {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 62%, transparent);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.35;
  white-space: nowrap;
}

.decision-card--pending {
  border-left-color: var(--decision-attention);
}

.decision-card--pending .process-step-marker {
  background: var(--decision-attention);
}

.decision-card-detail {
  margin: 0;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.decision-options {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0;
  padding-top: 4px;
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 9%, transparent);
}

.decision-option-group {
  width: 100%;
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(76px, max-content) minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 8%, transparent);
}

.decision-option-group:last-child {
  border-bottom: 0;
}

.decision-option {
  min-width: 76px;
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--theme-main-text, var(--text));
  padding: 7px 2px;
  cursor: pointer;
  text-align: left;
  transition: color 160ms ease;
}

.decision-option:hover {
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 78%, var(--decision-attention) 22%);
}

.decision-option:focus-visible,
.decision-guide-toggle:focus-visible,
.decision-guide-submit:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 78%, transparent);
  outline-offset: 2px;
}

.decision-option--approve {
  color: color-mix(in srgb, var(--green) 82%, var(--theme-main-text, #fff) 18%);
}

.decision-option--approve:hover {
  background: transparent;
  color: color-mix(in srgb, var(--green) 94%, var(--theme-main-text, #fff) 6%);
}

.decision-option--deny {
  background: transparent;
  color: color-mix(in srgb, var(--red) 82%, var(--theme-main-text, #fff) 18%);
}

.decision-option--deny:hover {
  background: transparent;
  color: color-mix(in srgb, var(--red) 94%, var(--theme-main-text, #fff) 6%);
}

.decision-option-label {
  font-size: 12px;
  font-weight: 600;
  line-height: 1.35;
}

.decision-option-desc {
  min-width: 0;
  max-width: none;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-size: 11px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.decision-card-decision {
  margin: 0;
  color: color-mix(in srgb, var(--green) 76%, var(--theme-main-text, #fff) 24%);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.decision-guide {
  padding-top: 1px;
}

.decision-guide-toggle {
  width: max-content;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 64%, transparent);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.45;
  cursor: pointer;
}

.decision-guide-toggle:hover {
  color: var(--theme-main-text, var(--text));
}
.process-step--tool .tool-row-summary {
  font-size: 11.5px;
  font-weight: 450;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 58%, transparent);
}

.decision-guide-fields {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 7px;
  align-items: end;
  margin-top: 8px;
}

.decision-guide-input {
  min-width: 0;
  width: 100%;
  resize: vertical;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent);
  border-radius: 7px;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 5%, transparent);
  color: var(--theme-main-text, var(--text));
  padding: 7px 8px;
  font: inherit;
  font-size: 12px;
  line-height: 1.45;
}

.decision-guide-input:focus {
  outline: 2px solid color-mix(in srgb, var(--blue) 68%, transparent);
  outline-offset: 1px;
  border-color: color-mix(in srgb, var(--blue) 46%, transparent);
}

.decision-guide-submit {
  border: 1px solid color-mix(in srgb, var(--blue) 38%, transparent);
  border-radius: 7px;
  background: color-mix(in srgb, var(--blue) 12%, transparent);
  color: var(--theme-main-text, var(--text));
  padding: 7px 9px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.45;
  white-space: nowrap;
  cursor: pointer;
}

.decision-guide-submit:disabled {
  cursor: not-allowed;
  opacity: .45;
}

.sub-line-block {
  position: relative;
  min-width: 0;
  display: grid;
  gap: 8px;
  margin-left: 4px;
  padding-left: 22px;
}

.sub-line-block::before {
  content: "";
  position: absolute;
  left: 6px;
  top: 4px;
  bottom: 4px;
  width: 1px;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 16%, transparent);
}

/* ── Compact process group summary ── */
.process-group-summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  width: 100%;
  padding: 4px 0;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: inherit;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s ease;
  opacity: 0.8;
}
.process-group-summary:hover {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 4%, transparent);
  opacity: 1;
}
.process-group-text {
  min-width: 0;
  font-size: 12px;
  line-height: 1.4;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 72%, transparent);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.process-group-chevron {
  flex-shrink: 0;
  font-size: 11px;
  opacity: 0.55;
}
.process-group-body {
  padding: 4px 0 4px 12px;
  border-left: 2px solid color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent);
}

.sub-line-heading {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  gap: 8px;
  align-items: center;
  width: 100%;
  padding: 4px 0;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: inherit;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s ease;
}
.sub-line-heading:hover {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 4%, transparent);
}

.sub-line-chevron {
  flex-shrink: 0;
  font-size: 11px;
  opacity: 0.55;
}

.sub-line-title {
  min-width: 0;
  color: var(--theme-main-text, var(--text));
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.sub-line-status {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-size: 11px;
  line-height: 1.35;
  white-space: nowrap;
}

.sub-line-delivery-meta {
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-left: 18px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 58%, transparent);
  font-size: 11px;
  line-height: 1.35;
}

.sub-line-delivery-meta span {
  padding: 2px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 5%, transparent);
}

.sub-line-body {
  display: grid;
  gap: 8px;
}

.sub-line-block .user-row {
  padding: 1px 0 4px;
}

.sub-line-block .user-bubble {
  max-width: min(76%, 520px);
  border-radius: 14px;
  border-bottom-right-radius: 6px;
  padding: 7px 10px;
  font-size: 12px;
  line-height: 1.5;
}

.sub-line-block .assistant-answer {
  margin-top: 4px;
}

.sub-line-block .assistant-answer,
.sub-line-block .part-text-content {
  font-size: 12px;
  line-height: 1.55;
}

.sub-line-block .process-step {
  font-size: 11px;
  line-height: 1.42;
}

.sub-line-block .process-step--tool {
  border-radius: 0;
  padding: 0;
}

.sub-line-block .tool-card-header {
  grid-template-columns: 10px max-content minmax(0, max-content) auto;
  column-gap: 5px;
  row-gap: 3px;
}

.sub-line-block .tool-type-tag {
  font-size: 9px;
  padding: 1px 4px;
}

.sub-line-block .tool-card-body {
  margin-top: 6px;
}

.sub-line-block .tool-output {
  padding: 7px 9px;
  font-size: 11px;
  line-height: 1.45;
  max-height: 260px;
}

.sub-line-block .tool-output-meta {
  font-size: 10px;
}

.sub-line-block .tool-output-meta span {
  padding: 1px 5px;
}

.sub-line-block .tool-args-preview,
.sub-line-block .diff-header,
.sub-line-block .diff-file,
.sub-line-block .diff-line-num {
  font-size: 10px;
}

.sub-line-block .tool-args-preview {
  margin-left: 0;
}

.sub-line-block .diff-lines {
  font-size: 11px;
  line-height: 1.5;
}

.sub-line-block .diff-line {
  grid-template-columns: 30px minmax(0, 1fr);
  min-height: 18px;
}

.sub-line-block .diff-line-num {
  width: 30px;
  padding: 0 5px 0 7px;
}

.sub-line-block .diff-line-content {
  padding: 0 8px 0 7px;
}

.sub-line-block .reasoning-toggle {
  min-height: 24px;
  gap: 6px;
}

.sub-line-block .process-step--reasoning .process-step-title {
  font-size: 11px;
}

.sub-line-block .reasoning-duration {
  font-size: 10px;
}

.sub-line-block .reasoning-body {
  margin: 2px 0 6px 20px;
  max-height: none;
  overflow: visible;
  font-size: 12px;
  line-height: 1.55;
}

.checklist-card {
  border-color: color-mix(in srgb, var(--blue) 18%, transparent);
  background: color-mix(in srgb, var(--theme-main-text, #fff) 3%, transparent);
}

.checklist-card-head .process-step-title {
  font-size: 13px;
  font-weight: 600;
}

.checklist-items {
  display: grid;
  gap: 7px;
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: checklist-item;
}

.checklist-item {
  min-width: 0;
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  counter-increment: checklist-item;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 72%, transparent);
  font-size: 12px;
  line-height: 1.45;
}

.checklist-item::before {
  content: counter(checklist-item) ".";
  color: color-mix(in srgb, var(--theme-main-text, #fff) 44%, transparent);
  font-variant-numeric: tabular-nums;
}

.checklist-box {
  grid-column: 2;
  width: 14px;
  height: 14px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 28%, transparent);
  border-radius: 3px;
  display: inline-grid;
  place-items: center;
  color: var(--green);
  font-size: 11px;
  line-height: 1;
}

.checklist-text {
  grid-column: 3;
  min-width: 0;
  overflow-wrap: anywhere;
}

.checklist-item--completed .checklist-text {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 48%, transparent);
  text-decoration: line-through;
  text-decoration-thickness: 1px;
}

.test-result-card {
  min-width: 0;
  display: grid;
  gap: 7px;
  margin: 2px 0;
  padding: 0;
}
.test-result-head {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 8px;
}
.test-result-state {
  font-size: 12px;
  font-weight: 700;
  color: var(--theme-main-text, var(--text));
}
.test-result-card--passed .test-result-state {
  color: var(--green);
}
.test-result-card--failed .test-result-state {
  color: var(--red);
}
.test-result-command {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
}
.test-result-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.test-result-meta span {
  padding: 0;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
}
.test-result-meta span + span::before {
  content: "·";
  margin-right: 6px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 32%, transparent);
}
.test-result-output {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  padding: 3px 0 0;
  color: var(--theme-main-text, var(--text));
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ── Reasoning collapsible panel ── */
.process-step--reasoning {
  display: block;
  width: 100%;
  min-width: 0;
  padding: 2px 0;
  counter-increment: reasoning-step;
}
.process-step--reasoning + .process-step--reasoning {
  margin-top: 3px;
}
.reasoning-toggle {
  width: 100%;
  min-width: 0;
  min-height: 28px;
  display: grid;
  grid-template-columns: max-content minmax(0, max-content) auto;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: none;
  border-radius: 6px;
  padding: 2px 6px 2px 0;
  cursor: pointer;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 74%, transparent);
  font: inherit;
  text-align: left;
  transition: background .14s ease, color .14s ease;
}
.reasoning-toggle:hover {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 4%, transparent);
  color: color-mix(in srgb, var(--theme-main-text, #fff) 88%, transparent);
}
.process-step--reasoning .process-step-marker {
  display: none;
}
.process-step--reasoning .process-step-title {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 66%, transparent);
  font-size: 12px;
  font-weight: 680;
}
.reasoning-duration {
  min-width: 0;
  max-width: min(240px, 40vw);
  justify-self: start;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 60%, transparent);
  font-style: normal;
}
.reasoning-body {
  margin: 3px 0 8px 24px;
  max-height: 800px;
  overflow: auto;
  padding: 2px 0 6px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 62%, transparent);
  font-size: 13px;
  line-height: 1.65;
  font-style: normal;
  text-wrap: pretty;
  opacity: 1;
  transition: max-height 0.28s cubic-bezier(0.2, 0.8, 0.2, 1),
              opacity 0.22s ease,
              margin 0.28s cubic-bezier(0.2, 0.8, 0.2, 1),
              padding 0.28s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.reasoning-body--closed {
  max-height: 0;
  opacity: 0;
  margin-top: 0;
  margin-bottom: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.reasoning-body .process-step-detail {
  display: block;
  overflow: visible;
  color: inherit;
  white-space: pre-wrap;
  word-break: break-word;
  -webkit-line-clamp: unset;
}

.compaction-step {
  display: block;
  width: 100%;
  min-width: 0;
  padding: 2px 0;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 62%, transparent);
}
.compaction-toggle {
  display: grid;
  grid-template-columns: 12px minmax(0, max-content) minmax(0, 1fr) minmax(12px, max-content);
  align-items: center;
  column-gap: 6px;
  width: 100%;
  min-width: 0;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  color: inherit;
  font: inherit;
  text-align: left;
}
.compaction-toggle:disabled {
  cursor: default;
}
.compaction-toggle:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--accent, #79bcff) 72%, transparent);
  outline-offset: 3px;
  border-radius: 4px;
}
.compaction-toggle .process-step-title {
  min-width: 0;
  white-space: nowrap;
}
.compaction-toggle .process-step-detail {
  min-width: 0;
  overflow-wrap: anywhere;
}
.compaction-toggle .tool-expand-chevron {
  justify-self: end;
}
.compaction-toggle:hover .process-step-title {
  color: var(--accent, #79bcff);
}
.compaction-toggle:disabled:hover .process-step-title {
  color: inherit;
}
.compaction-step--running .process-step-marker {
  background: var(--orange);
  animation: part-pulse 1s ease-in-out infinite;
}
.compaction-step--compacted .process-step-marker {
  background: var(--green);
}
.compaction-step--not_needed .process-step-marker {
  background: color-mix(in srgb, var(--theme-main-text, #fff) 34%, transparent);
}
.compaction-step--failed .process-step-marker {
  background: var(--red);
}
.compaction-summary {
  box-sizing: border-box;
  width: min(100%, 720px);
  margin: 6px 0 0 18px;
  padding: 2px 0 6px;
  border: 0;
  background: transparent;
}
.compaction-summary-text {
  margin: 0;
  max-height: 320px;
  overflow: auto;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 72%, transparent);
  font-family: inherit;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.compaction-summary-text--streaming::after {
  content: "";
  display: inline-block;
  width: 1px;
  height: 1em;
  margin-left: 3px;
  transform: translateY(2px);
  background: currentColor;
  opacity: .58;
  animation: stream-caret 900ms steps(2, start) infinite;
}
@media (prefers-reduced-motion: reduce) {
  .compaction-step--running .process-step-marker,
  .compaction-summary-text--streaming::after {
    animation: none;
  }
}

/* ── Tool args preview ── */
.tool-args-preview {
  grid-area: args;
  min-width: 0;
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 56%, transparent);
  font-family: var(--font-mono);
  max-width: min(100%, 760px);
  overflow-wrap: anywhere;
  white-space: normal;
  justify-self: start;
}

/* ── Diff-style file blocks ── */
.diff-block {
  min-width: 0;
  width: 100%;
  max-width: 100%;
  margin: 0;
  color: var(--theme-main-text, var(--text));
  max-height: 400px;
  overflow: auto;
}
.diff-header {
  min-width: 0;
  min-height: 29px;
  box-sizing: border-box;
  padding: 5px 0;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  border-bottom: 1px solid var(--theme-main-border, color-mix(in srgb, var(--theme-main-text, #fff) 10%, transparent));
  display: flex;
  align-items: center;
  gap: 8px;
  position: sticky;
  top: 0;
  z-index: 2;
}
.wrap-toggle {
  flex: 0 0 auto;
  margin-left: auto;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 68%, transparent);
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.2;
  padding: 2px 0 2px 6px;
  cursor: pointer;
}
.wrap-toggle:hover {
  color: var(--theme-main-text, var(--text));
  text-decoration: underline;
  text-underline-offset: 2px;
}
.diff-block--read .diff-header {
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 78%, transparent);
}
.diff-block--write .diff-header {
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 78%, transparent);
}
.diff-file {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 11px;
}
.diff-lines {
  min-width: max-content;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  min-width: 100%;
}
.diff-block:not(.diff-block--wrap) .diff-lines {
  min-width: max-content;
}
.diff-block--wrap .diff-lines {
  min-width: 0;
}
.diff-line {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  min-height: 20px;
}
.diff-line:nth-child(even) {
  background: var(--theme-main-subtle-background, color-mix(in srgb, var(--theme-main-text, #fff) 2%, transparent));
}
.diff-line-num {
  width: 34px;
  padding: 0 6px 0 10px;
  text-align: right;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 38%, transparent);
  font-size: 11px;
  user-select: none;
  border-right: 1px solid var(--theme-main-border, color-mix(in srgb, var(--theme-main-text, #fff) 9%, transparent));
  background: var(--theme-main-subtle-background, color-mix(in srgb, var(--theme-main-text, #fff) 3%, transparent));
}
.diff-line-content {
  white-space: pre;
  word-break: normal;
  color: var(--theme-main-text, var(--text));
  padding: 0 10px 0 8px;
  min-width: 0;
}
.diff-block--wrap .diff-line-content {
  white-space: pre-wrap;
  word-break: break-word;
}
/* Diff line markers — follows Claude Code unified diff style */
.diff-line--add {
  background: color-mix(in srgb, var(--green) 7%, var(--theme-main-subtle-background, transparent));
}
.diff-line--add .diff-line-content {
  color: color-mix(in srgb, var(--green) 72%, var(--theme-main-text, #fff) 28%);
}
.diff-line--add .diff-line-num {
  color: color-mix(in srgb, var(--green) 76%, var(--theme-main-text, #fff) 24%);
  font-weight: 700;
}
.diff-line--del {
  background: color-mix(in srgb, var(--red) 7%, var(--theme-main-subtle-background, transparent));
}
.diff-line--del .diff-line-content {
  color: color-mix(in srgb, var(--red) 74%, var(--theme-main-text, #fff) 26%);
}
.diff-line--del .diff-line-num {
  color: color-mix(in srgb, var(--red) 78%, var(--theme-main-text, #fff) 22%);
  font-weight: 700;
}
.diff-line--meta {
  background: color-mix(in srgb, var(--blue) 5%, var(--theme-main-subtle-background, transparent));
}
.diff-line--meta .diff-line-content {
  color: color-mix(in srgb, var(--theme-main-text, #fff) 60%, transparent);
}
@media (max-width: 720px) {
  .process-tool-row {
    gap: 6px;
    padding-inline: 2px;
  }
  .tool-card-body--row {
    margin-left: 10px;
    width: calc(100% - 10px);
  }
  .context-tool-list {
    padding-left: 14px;
  }
  .context-tool-head {
    grid-template-columns: minmax(72px, max-content) minmax(0, 1fr);
  }
}
@media (prefers-reduced-motion: reduce) {
  .process-tool-row,
  .tool-card-body--row {
    animation: none;
    transition: none;
  }
  .reasoning-body,
  .tool-card-body {
    transition: none !important;
  }
  .reasoning-body--closed,
  .tool-card-body--closed {
    max-height: none;
    opacity: 1;
  }
}
</style>
