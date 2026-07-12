import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { h } from 'vue';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import ChatThread from '../src/components/ChatThread.vue';
import type { CoreMessage } from '../src/types';

const __dirname = dirname(fileURLToPath(import.meta.url));

describe('ChatThread process cards', () => {
  it('renders assistant Markdown through the shared default renderer', () => {
    const wrapper = mount(ChatThread, {
      props: {
        messages: [{
          id: 'markdown-answer',
          role: 'assistant',
          content: '最终 **正文**',
          timestamp: '',
          parts: [],
        }],
      },
    });

    expect(wrapper.find('.markdown-body strong').text()).toBe('正文');
    expect(wrapper.text()).not.toContain('**正文**');
  });

  it('renders a tool part as one process step only', () => {
    const messages: CoreMessage[] = [{
      id: 'm-tool',
      role: 'assistant',
      content: 'Done.',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-tool',
        partType: 'tool_call',
        status: 'completed',
        content: '[stdout]\nok',
        detail: '[stdout]\nok',
        toolResult: '[stdout]\nok',
        label: 'run_command',
        toolName: 'run_command',
        toolArgs: { command: 'echo ok' },
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-tool']),
      },
    });

    expect(wrapper.findAll('.process-step')).toHaveLength(1);
    expect(wrapper.findAll('.process-step--info')).toHaveLength(0);
    expect(wrapper.find('.tool-card-header').text()).toContain('run_command');
    expect(wrapper.find('.tool-card-header').text()).toContain('echo ok');
  });

  it('renders compaction rows with localized title and token detail', () => {
    const messages: CoreMessage[] = [{
      id: 'm-compaction',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-compaction',
        partType: 'compaction',
        status: 'completed',
        content: '[Compacted Context]\n1. Current Goal\n- Continue.',
        label: 'compaction',
        before_tokens: 351051,
        after_tokens: 153000,
        target_tokens: 153600,
        removed_messages: 42,
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-compaction']),
      },
    });

    const row = wrapper.find('.compaction-step');
    expect(row.text()).toContain('上下文已压缩');
    expect(row.text()).toContain('351051 -> 153000 tokens');
    expect(row.text()).toContain('42 条消息');
    expect(row.text()).toContain('点击查看摘要');
    expect(row.text()).not.toContain('Compacted Context');
    expect(row.text()).not.toContain('compaction点击查看');
  });

  it('shows a bounded compaction summary only after explicit expansion', async () => {
    const longSummary = [
      '[Compacted Context]',
      ...Array.from({ length: 20 }, (_, index) => `summary line ${index + 1}`),
      'tail should stay hidden',
    ].join('\n');
    const messages: CoreMessage[] = [{
      id: 'm-compaction-expanded',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-compaction-expanded',
        partType: 'compaction',
        status: 'completed',
        content: longSummary,
        label: 'compaction',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-compaction-expanded']),
      },
    });

    expect(wrapper.find('.compaction-summary').exists()).toBe(false);

    await wrapper.find('.compaction-toggle').trigger('click');

    const summary = wrapper.find('.compaction-summary');
    expect(summary.exists()).toBe(true);
    expect(summary.text()).toContain('[Compacted Context]');
    expect(summary.text()).toContain('summary line 9');
    expect(summary.text()).toContain('内容较长，已折叠显示。');
    expect(summary.text()).not.toContain('summary line 11');
    expect(summary.text()).not.toContain('tail should stay hidden');
    expect(wrapper.find('.compaction-body').exists()).toBe(false);
  });

  it('renders skipped compaction without an empty summary affordance', () => {
    const messages: CoreMessage[] = [{
      id: 'm-compaction-skipped',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-compaction-skipped',
        partType: 'compaction',
        status: 'completed',
        content: '',
        label: '暂无可压缩上下文',
        compaction_status: 'skipped',
        message: 'Not enough history to compact',
        compacted_messages: 0,
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-compaction-skipped']),
      },
    });

    const row = wrapper.find('.compaction-step');
    expect(row.text()).toContain('暂无可压缩上下文');
    expect(row.text()).toContain('Not enough history to compact');
    expect(row.text()).not.toContain('点击查看摘要');
    expect(wrapper.find('.compaction-summary').exists()).toBe(false);
  });

  it('keeps compaction expanded content below the title row', () => {
    const source = readFileSync(resolve(__dirname, '../src/components/ChatThread.vue'), 'utf8');
    const compactionRule = source.match(/\.compaction-step\s*\{[^}]+\}/)?.[0] || '';
    const summaryRule = source.match(/\.compaction-summary\s*\{[^}]+\}/)?.[0] || '';

    expect(compactionRule).toContain('display: block');
    expect(compactionRule).toContain('width: 100%');
    expect(summaryRule).toContain('margin: 6px 0 0 18px');
    expect(source).not.toContain('class="process-step process-step--compaction"');
    expect(source).not.toContain('class="compaction-summary-label"');
  });

  it('renders command output as a terminal window', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-command-meta',
      role: 'assistant',
      content: 'Done.',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-command-meta',
        partType: 'tool_call',
        status: 'completed',
        label: 'run_command',
        toolName: 'run_command',
        toolArgs: { command: 'npm test', cwd: 'E:/LamTools' },
        toolResult: '[stdout]\nok\n[exit_code] 0\n[duration_seconds] 1.25',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-command-meta']),
      },
    });

    await wrapper.find('.tool-card-header').trigger('click');

    expect(wrapper.find('.command-terminal-chrome').exists()).toBe(true);
    expect(wrapper.findAll('.command-terminal-light')).toHaveLength(3);
    expect(wrapper.find('.command-terminal-title').text()).toBe('run command');
    expect(wrapper.find('.command-output-command').text()).toContain('$ npm test');
    expect(wrapper.find('.command-output-result').text()).toContain('ok');
    expect(wrapper.find('.command-output-result').text()).not.toContain('[exit_code]');
    expect(wrapper.find('.command-output-result').text()).not.toContain('[duration_seconds]');
  });

  it('renders browser checks with the real tool name', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-browser-check',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-browser-check',
        partType: 'tool_call',
        status: 'error',
        label: 'HTTP 502',
        toolName: 'browser_check',
        toolArgs: { url: 'http://localhost:8080/index.html', expect: '本地知识库工作台' },
        toolResult: '[browser_check http://localhost:8080/index.html] HTTP 502\ncontent_type: unknown\nbytes: 0\nexpect: 本地知识库工作台\nexpect_found: false',
        toolError: '[browser_check http://localhost:8080/index.html] HTTP 502',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-browser-check']),
      },
    });

    const header = wrapper.find('.tool-card-header');
    expect(header.text()).toContain('browser_check');
    expect(header.text()).not.toContain('HTTP 502');
    expect(header.text()).not.toContain('WEB');
    expect(header.text()).not.toContain('TEST');
  });

  it('renders write diffs as scrollable full content with wrap toggle', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-write',
      role: 'assistant',
      content: 'Done.',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-write',
        partType: 'tool_call',
        status: 'completed',
        label: 'write_file',
        toolName: 'write_file',
        toolArgs: { path: 'notes.txt' },
        toolResult: 'Created notes.txt: 12 chars, 3 lines.\n--- preview ---\n  1 | old preview\n--- end preview ---',
        artifacts: [{
          kind: 'file_change',
          uri: 'notes.txt',
          content: '+++ b/notes.txt\n@@ -0,0 +1,5 @@\n+first\n+second\n+middle line must stay visible\n+fourth\n+fifth',
          metadata: { path: 'notes.txt', action: 'create', new_line_count: 5 },
        }],
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-write']),
      },
    });

    expect(wrapper.find('.diff-block').exists()).toBe(false);

    await wrapper.find('.tool-card-header').trigger('click');

    expect(wrapper.find('.diff-block').exists()).toBe(true);
    expect(wrapper.find('.diff-block--write').exists()).toBe(true);
    expect(wrapper.find('.diff-block').text()).toContain('middle line must stay visible');
    expect(wrapper.find('.diff-block').text()).not.toContain('old preview');
    expect(wrapper.find('.diff-block--wrap').exists()).toBe(false);

    await wrapper.find('.wrap-toggle').trigger('click');

    expect(wrapper.find('.diff-block--wrap').exists()).toBe(true);
  });

  it('uses file paths as the main title for file write steps', () => {
    const messages: CoreMessage[] = [{
      id: 'm-write-title',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-write-title',
        partType: 'tool_call',
        status: 'completed',
        label: 'write_file',
        toolName: 'write_file',
        toolArgs: { path: 'notes.txt' },
        toolResult: 'Created notes.txt: 12 chars, 3 lines.',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-write-title']),
      },
    });

    const title = wrapper.find('.tool-card-header .process-step-title');
    expect(title.text()).toBe('写入 notes.txt');
    expect(wrapper.find('.tool-card-header').text()).not.toContain('文件 notes.txt');
  });

  it('renders running write tool input preview before final result', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-write-preview',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-write-preview',
        partType: 'tool_call',
        status: 'running',
        label: 'write_file',
        toolName: 'write_file',
        toolArgs: { path: 'index.html' },
        inputPreview: {
          field: 'content',
          content: '<html>\n<body>Live</body>',
          chars: 24,
          truncated: false,
        },
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-write-preview']),
      },
    });

    await wrapper.find('.tool-card-header').trigger('click');

    const body = wrapper.find('.tool-card-body');
    expect(body.exists()).toBe(true);
    expect(wrapper.find('.tool-card-header').text()).toContain('index.html');
    expect(body.text()).toContain('<body>Live</body>');
  });

  it('prefers even a tiny running write input preview over progress detail', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-write-preview-tiny',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-write-preview-tiny',
        partType: 'tool_call',
        status: 'running',
        label: 'write_file',
        detail: '参数生成中：36 chars',
        content: '参数生成中：36 chars',
        toolName: 'write_file',
        inputPreview: {
          field: 'content',
          content: '<',
          chars: 1,
          truncated: false,
        },
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-write-preview-tiny']),
      },
    });

    await wrapper.find('.tool-card-header').trigger('click');

    const body = wrapper.find('.tool-card-body');
    expect(body.exists()).toBe(true);
    expect(body.find('.tool-input-preview').exists(), body.html()).toBe(true);
    expect(body.find('.tool-input-preview').text()).toContain('<');
    expect(body.text()).not.toContain('参数生成中：36 chars');
  });

  it('emits a normal reply payload when a decision option is selected', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-decision',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-decision',
        partType: 'decision',
        status: 'pending',
        content: 'Need a decision',
        label: 'Choose direction',
        toolName: 'decision_point',
        toolArgs: {
          title: 'Choose direction',
          options: [
            {
              id: 'fast',
              label: 'Fast path',
              description: 'Use the smaller change',
              response: 'Use fast path',
            },
          ],
        },
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-decision']),
      },
    });

    await wrapper.find('.decision-option').trigger('click');

    const emitted = wrapper.emitted('decision-select');
    expect(emitted).toHaveLength(1);
    expect(emitted?.[0]?.[0]).toMatchObject({
      partId: 'p-decision',
      response: 'Use fast path',
      option: {
        id: 'fast',
        label: 'Fast path',
      },
    });
  });

  it('renders agent metadata as a nested timeline', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-agent',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-agent',
        partType: 'agent_summary',
        status: 'completed',
        content: 'Use the smaller implementation.\n\n- Keep the nested timeline.',
        detail: 'Use the smaller implementation.\n\n- Keep the nested timeline.',
        toolResult: 'Use the smaller implementation.\n\n- Keep the nested timeline.',
        label: 'Agent completed',
        toolName: 'sub_agent',
        toolArgs: {
          agent: 'sub',
          task: 'Audit Writer tool display\n\n## Scope\nCheck the nested timeline.',
        },
        metadata: {
          agent_name: 'repo_reader',
          agent_index: '001',
          mode: 'review',
          valid_design: true,
          winner_name: 'smaller implementation',
          reasoning_blocks: [
            { content: 'Inspect the component flow before changing UI.' },
          ],
          tool_calls: [
            {
              name: 'read_file',
              arguments: { path: 'core/ui/src/components/ChatThread.vue' },
              status: 'completed',
              output: 'Read component source.',
            },
            {
              name: 'write_file',
              arguments: { path: 'src/index.html' },
              status: 'completed',
              output: 'Created src/index.html: 42 chars, 2 lines. --- preview ---\n1 | <main>Hello</main>\n2 | <script src=\"app.js\"></script>\n--- end preview ---',
            },
          ],
        },
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-agent']),
      },
    });

    const block = wrapper.find('.sub-line-block');
    expect(block.exists()).toBe(true);
    expect(block.find('.sub-line-heading').text()).toContain('001 · repo_reader');
    expect(block.find('.sub-line-heading').text()).not.toContain('子任务');
    expect(block.find('.sub-line-heading.tool-card-header').exists()).toBe(false);
    expect(block.find('.sub-line-chat .user-bubble').exists()).toBe(true);
    expect(block.find('.sub-line-chat .user-bubble').text()).toContain('## Scope');
    expect(block.findAll('.process-step--tool').length).toBeGreaterThan(1);
    expect(block.findAll('.tool-card-header').length).toBeGreaterThan(1);
    expect(block.find('.process-step--reasoning').exists()).toBe(true);
    expect(block.find('.process-step--reasoning').text()).toContain('Inspect the component flow');

    await block.find('.reasoning-toggle').trigger('click');
    expect(block.find('.process-step--reasoning').text()).not.toContain('Inspect the component flow');
    await block.find('.reasoning-toggle').trigger('click');
    expect(block.find('.process-step--reasoning').text()).toContain('Inspect the component flow');

    expect(block.find('.sub-line-chat .assistant-answer .part-text-content').exists()).toBe(true);
    expect(block.text()).toContain('Inspect the component flow');
    expect(block.text()).toContain('## Scope');
    expect(block.text()).toContain('smaller implementation');
    expect(block.text()).not.toContain('调用子 Agent');
    expect(block.text()).toContain('Context');
    expect(block.text()).toContain('write_file');
    const writeHeader = block.findAll('.tool-card-header').find(header => header.text().includes('write_file'));
    expect(writeHeader).toBeTruthy();
    await writeHeader!.trigger('click');

    const writeDiff = block.find('.diff-block--write');
    expect(writeDiff.exists()).toBe(true);
    expect(writeDiff.text()).toContain('src/index.html');
    expect(writeDiff.text()).toContain('<main>Hello</main>');
    expect(block.text()).toContain('Use the smaller implementation.');
  });

  it('renders sub agent process through the same ChatThread timeline renderer', () => {
    const messages: CoreMessage[] = [{
      id: 'm-agent-shared-renderer',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-agent-shared-renderer',
        partType: 'agent_summary',
        status: 'completed',
        content: '子 agent 已完成复核。',
        toolResult: '子 agent 已完成复核。',
        toolName: 'sub_agent',
        toolArgs: {
          agent: 'sub',
          task: '复核子线渲染是否复用主线逻辑',
        },
        metadata: {
          agent_name: 'retrospective_analyst',
          agent_index: '001',
          subLineParts: [
            {
              id: 'sub-reasoning',
              partType: 'reasoning',
              status: 'completed',
              content: '先读取子任务，再复用主线过程块展示。',
            },
          ],
        },
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-agent-shared-renderer']),
      },
    });

    const block = wrapper.find('.sub-line-block');
    expect(block.find('.chat-thread').exists()).toBe(true);
    expect(block.find('.sub-line-nested-process').exists()).toBe(false);
    expect(block.find('.assistant-meta').text()).toContain('001 · retrospective_analyst');
    expect(block.find('.reasoning-body').text()).toContain('先读取子任务');
    expect(block.find('.sub-line-assistant-answer').exists()).toBe(false);
    expect(block.find('.assistant-answer').text()).toContain('子 agent 已完成复核。');
  });

  it('renders agent final answer as user-facing conclusion', () => {
    const messages: CoreMessage[] = [{
      id: 'm-agent-json',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-agent-json',
        partType: 'agent_summary',
        status: 'completed',
        label: 'Completed: sub_agent',
        toolName: 'sub_agent',
        toolArgs: { name: 'sub_agent', task: '实现仪表盘页面' },
        content: '已创建首页、样式和交互脚本。',
        detail: '已创建首页、样式和交互脚本。',
        toolResult: '已创建首页、样式和交互脚本。',
        metadata: {
          agent: 'worker',
          agent_index: '002',
          role: 'implementation',
        },
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-agent-json']),
      },
    });

    const blockText = wrapper.find('.sub-line-block').text();
    expect(blockText).toContain('002 · worker');
    expect(blockText).not.toContain('执行子任务');
    expect(blockText).toContain('已创建首页、样式和交互脚本。');
    expect(blockText).not.toContain('Agent: sub');
    expect(blockText).not.toContain('"handoff"');
    expect(blockText).not.toContain('"confidence"');
  });

  it('prefers agent content over tool-name detail for sub-line conclusion', () => {
    const messages: CoreMessage[] = [{
      id: 'm-agent-content',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-agent-content',
        partType: 'agent_summary',
        status: 'completed',
        label: 'sub_agent',
        toolName: 'sub_agent',
        toolArgs: { agent: 'retrospective-analyst', task: '复盘失败过程' },
        content: '# 复盘报告\n\n子 agent 的完整结论。',
        detail: 'sub_agent',
        toolResult: '# 复盘报告\n\n子 agent 的完整结论。',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-agent-content']),
      },
    });

    const answerText = wrapper.find('.sub-line-chat .part-text-content').text();
    expect(answerText).toContain('子 agent 的完整结论。');
    expect(answerText).not.toBe('sub_agent');
  });

  it('renders structured checklist parts as checkbox items', () => {
    const messages: CoreMessage[] = [{
      id: 'm-checklist',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-checklist',
        partType: 'plan',
        status: 'running',
        content: '',
        label: '计划',
        toolName: 'write_checklist',
        toolArgs: {
          steps: [
            { id: 's1', description: 'Build the page shell', status: 'completed' },
            { id: 's2', description: 'Add responsive styling', status: 'pending' },
          ],
        },
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-checklist']),
      },
    });

    expect(wrapper.find('.checklist-card').exists()).toBe(true);
    expect(wrapper.find('.checklist-card').text()).toContain('s1. Build the page shell');
    expect(wrapper.find('.checklist-card').text()).toContain('s2. Add responsive styling');
    expect(wrapper.find('.checklist-item--completed').exists()).toBe(true);
  });

  it('renders live reasoning as an expandable reasoning block', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-live-reasoning',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { live: true, timeline: true },
      parts: [{
        id: 'p-reasoning',
        partType: 'reasoning',
        status: 'running',
        label: '思考',
        content: 'Inspecting files before writing the final answer.',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: { messages },
    });

    expect(wrapper.find('.process-step--reasoning').exists()).toBe(true);
    expect(wrapper.find('.reasoning-body').exists()).toBe(true);
    expect(wrapper.find('.reasoning-body').text()).toContain('Inspecting files');
  });

  it('does not add a generic current row for transcript live timeline messages', () => {
    const messages: CoreMessage[] = [{
      id: 'm-live-transcript',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { live: true, timeline: true, liveStatus: '正在处理' },
      parts: [{
        id: 'p-live-transcript-reasoning',
        partType: 'reasoning',
        status: 'running',
        label: '思考',
        content: 'Inspecting files before writing.',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-completed-decision']),
      },
    });

    expect(wrapper.find('.process-step--reasoning').exists()).toBe(true);
    expect(wrapper.find('.process-current').exists()).toBe(false);
  });

  it('renders live transcript model text as visible process text', () => {
    const messages: CoreMessage[] = [{
      id: 'm-live-model-text',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { live: true, timeline: true, liveStatus: '正在处理' },
      parts: [{
        id: 'p-model-text',
        partType: 'model_text',
        status: 'running',
        label: '正文',
        content: 'Streaming model text is visible.',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-completed-decision']),
      },
    });

    expect(wrapper.find('.assistant-answer--process').exists()).toBe(true);
    expect(wrapper.find('.assistant-answer--process').text()).toContain('Streaming model text is visible.');
  });

  it('shows a shallow thinking placeholder without forcing the message into live rendering', () => {
    const messages: CoreMessage[] = [{
      id: 'm-live-shallow-pending',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true, shallowThinkingPending: true },
      parts: [],
    }];

    const wrapper = mount(ChatThread, {
      props: { messages },
    });

    const pending = wrapper.find('.shallow-thinking-pending');
    expect(pending.exists()).toBe(true);
    expect(pending.text()).toContain('shallow thinking...');
    expect(wrapper.find('.assistant-message--live').exists()).toBe(false);
  });

  it('shows the shallow thinking placeholder during initial waiting', () => {
    const messages: CoreMessage[] = [{
      id: 'm-live-shallow-initial',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { live: true, initialWaiting: true, shallowThinkingPending: true },
      parts: [],
    }];

    const wrapper = mount(ChatThread, {
      props: { messages },
    });

    expect(wrapper.find('.initial-waiting-indicator').text()).toContain('shallow thinking...');
  });

  it('hides the shallow thinking placeholder after reasoning content arrives', () => {
    const messages: CoreMessage[] = [{
      id: 'm-live-shallow-reasoning',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { live: true, timeline: true, shallowThinkingPending: true },
      parts: [{
        id: 'p-live-shallow-reasoning',
        partType: 'reasoning',
        status: 'running',
        label: '思考',
        content: '[结论]\n先整理目标。',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: { messages },
    });

    expect(wrapper.find('.shallow-thinking-pending').exists()).toBe(false);
    expect(wrapper.find('.reasoning-body').text()).toContain('先整理目标');
  });

  it('renders historical non-final model text inside the expanded process area', () => {
    const messages: CoreMessage[] = [{
      id: 'm-history-model-text',
      role: 'assistant',
      content: 'Final answer.',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-model-text-history',
        partType: 'model_text',
        status: 'completed',
        label: '正文',
        content: 'Intermediate model text.',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-history-model-text']),
      },
    });

    expect(wrapper.find('.process-step--model-text').exists()).toBe(true);
    expect(wrapper.find('.process-step--model-text').text()).toContain('Intermediate model text.');
    expect(wrapper.find('.assistant-message').text()).toContain('Final answer.');
  });

  it('normalizes protocol model text labels in the expanded process area', () => {
    const messages: CoreMessage[] = [{
      id: 'm-history-raw-model-text',
      role: 'assistant',
      content: 'Final answer.',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-raw-model-text-history',
        partType: 'model_text',
        status: 'completed',
        label: 'model text',
        content: '有什么我可以帮你的吗?',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-history-raw-model-text']),
      },
    });

    const processText = wrapper.find('.process-step--model-text');
    expect(processText.find('.process-step-title').text()).toBe('正文');
    expect(processText.find('.process-text-content').text()).toBe('有什么我可以帮你的吗?');
    expect(processText.text()).not.toContain('model text');
  });

  it('shows command tool information in expanded historical process', () => {
    const messages: CoreMessage[] = [{
      id: 'm-history-command',
      role: 'assistant',
      content: '已删除。',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [
        {
          id: 'p-command-reasoning',
          partType: 'reasoning',
          status: 'completed',
          label: '思考',
          content: 'Need to delete the file.',
        },
        {
          id: 'p-command-tool',
          partType: 'tool_call',
          status: 'completed',
          label: 'run_command',
          toolName: 'run_command',
          toolArgs: {
            command: "if (Test-Path genshin_guide_5.7.md) { Remove-Item genshin_guide_5.7.md }",
            timeout: 10,
          },
          toolResult: '[exit_code: 0]\n[stdout]\n已删除',
          content: '[exit_code: 0]\n[stdout]\n已删除',
        },
      ],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-history-command']),
      },
    });

    const text = wrapper.find('.process-stream--history').text();
    expect(text).toContain('思考');
    expect(text).toContain('run_command');
    expect(text).toContain('Remove-Item genshin_guide_5.7.md');
  });

  it('renders live waiting decisions with selectable options', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-live-decision',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { live: true, timeline: true, liveStatus: '等待用户处理' },
      parts: [{
        id: 'p-live-decision',
        partType: 'decision',
        status: 'pending',
        content: 'Approve command execution?',
        label: '等待授权',
        toolName: 'run_command',
        toolArgs: {
          command: 'npm test',
          options: [
            { id: 'approve', label: '批准', response: 'approve' },
            { id: 'deny', label: '拒绝', response: 'deny' },
          ],
        },
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: { messages },
    });

    expect(wrapper.find('.decision-card').exists()).toBe(true);
    expect(wrapper.findAll('.decision-option')).toHaveLength(2);

    await wrapper.find('.decision-option').trigger('click');

    expect(wrapper.emitted('decision-select')?.[0]?.[0]).toMatchObject({
      partId: 'p-live-decision',
      response: 'approve',
    });
  });

  it('submits custom guidance from a pending decision card', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-live-decision-guide',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { live: true, timeline: true, liveStatus: '等待用户处理' },
      parts: [{
        id: 'p-live-decision-guide',
        partType: 'decision',
        status: 'pending',
        content: 'Approve command execution?',
        label: '等待授权',
        toolName: 'run_command',
        toolArgs: {
          command: 'del README.md',
          options: [
            { id: 'approve', label: '批准', response: 'approve' },
            { id: 'deny', label: '拒绝', response: 'deny' },
          ],
        },
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: { messages },
    });

    await wrapper.find('.decision-guide-input').setValue('不要删除，改为重命名。');
    await wrapper.find('.decision-guide-submit').trigger('click');

    expect(wrapper.emitted('decision-select')?.[0]?.[0]).toMatchObject({
      partId: 'p-live-decision-guide',
      option: { id: 'guide' },
      response: '不要删除，改为重命名。',
    });
  });

  it('renders a completed decision with the selected action and no active options', () => {
    const messages: CoreMessage[] = [{
      id: 'm-completed-decision',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: {},
      parts: [{
        id: 'p-completed-decision',
        partType: 'decision',
        status: 'completed',
        content: 'Approve command execution?',
        label: '等待授权',
        toolName: 'run_command',
        toolArgs: {
          command: 'del README.md',
          options: [
            { id: 'approve', label: '批准', response: 'approve' },
            { id: 'deny', label: '拒绝', response: 'deny' },
          ],
        },
        metadata: {
          waitingResponse: {
            action: 'guide',
            response: '不要删除，改为重命名。',
          },
        },
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-completed-decision']),
      },
    });

    expect(wrapper.find('.decision-card-decision').text()).toContain('已选择：其他');
    expect(wrapper.find('.decision-card-decision').text()).toContain('不要删除，改为重命名。');
    expect(wrapper.findAll('.decision-option')).toHaveLength(0);
    expect(wrapper.find('.decision-guide').exists()).toBe(false);
  });

  it('lets products render expanded reasoning content through a slot by default', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-reasoning-slot',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-reasoning-slot',
        partType: 'reasoning',
        status: 'completed',
        label: '思考',
        content: '```ts\nconst value = 1\n```',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-reasoning-slot']),
      },
      slots: {
        'reasoning-content': ({ content }: { content: string }) => h('pre', { class: 'rendered-reasoning' }, content),
      },
    });

    expect(wrapper.find('.rendered-reasoning').exists()).toBe(true);
    expect(wrapper.find('.rendered-reasoning').text()).toContain('const value = 1');

    await wrapper.find('.reasoning-toggle').trigger('click');
    expect(wrapper.find('.rendered-reasoning').exists()).toBe(false);
  });

  it('expands completed reasoning by default and lets the user collapse it', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-completed-reasoning',
      role: 'assistant',
      content: 'Done.',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-reasoning-done',
        partType: 'reasoning',
        status: 'completed',
        label: '思考',
        content: 'Completed reasoning should be visible by default.',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-completed-reasoning']),
      },
    });

    expect(wrapper.find('.process-step--reasoning').exists()).toBe(true);
    expect(wrapper.find('.reasoning-body').exists()).toBe(true);
    expect(wrapper.find('.reasoning-body').text()).toContain('Completed reasoning');

    await wrapper.find('.reasoning-toggle').trigger('click');

    expect(wrapper.find('.reasoning-body').exists()).toBe(false);
  });

  it('collapses historical process sections by default and lets the parent reopen them', async () => {
    const messages: CoreMessage[] = [{
      id: 'm-process-reasoning',
      role: 'assistant',
      content: 'Done.',
      timestamp: '2026-06-18T00:00:00.000Z',
      parts: [{
        id: 'p-process-reasoning',
        partType: 'reasoning',
        status: 'completed',
        label: '思考',
        content: 'Historical reasoning stays visible after completion.',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(),
      },
    });

    expect(wrapper.find('.process-toggle').text()).toContain('查看过程');
    expect(wrapper.find('.process-stream--history').exists()).toBe(false);

    await wrapper.find('.process-toggle').trigger('click');
    expect(wrapper.emitted('toggle-process')?.[0]).toEqual(['m-process-reasoning']);

    await wrapper.setProps({ processExpandedIds: new Set(['m-process-reasoning']) });
    expect(wrapper.find('.process-stream--history').exists()).toBe(true);
    expect(wrapper.find('.reasoning-body').exists()).toBe(true);
    expect(wrapper.find('.reasoning-body').text()).toContain('Historical reasoning');
  });

  it('does not create an internal scroll container for reasoning bodies', () => {
    const source = readFileSync(resolve(__dirname, '../src/components/ChatThread.vue'), 'utf8');
    const reasoningBodyRule = source.match(/\.reasoning-body\s*\{[^}]+\}/)?.[0] || '';
    const nestedReasoningBodyRule = source.match(/\.sub-line-block\s+\.reasoning-body\s*\{[^}]+\}/)?.[0] || '';

    expect(reasoningBodyRule).toContain('max-height: none');
    expect(reasoningBodyRule).toContain('overflow: visible');
    expect(reasoningBodyRule).not.toContain('overflow: auto');
    expect(nestedReasoningBodyRule).toContain('max-height: none');
    expect(nestedReasoningBodyRule).toContain('overflow: visible');
    expect(nestedReasoningBodyRule).not.toContain('overflow: auto');
  });

  it('renders process model text as a separated block', () => {
    const source = readFileSync(resolve(__dirname, '../src/components/ChatThread.vue'), 'utf8');
    const modelTextRule = source.match(/\.process-step--model-text\s*\{[^}]+\}/)?.[0] || '';
    const modelTextContentRule = source.match(/\.process-text-content\s*\{[^}]+\}/)?.[0] || '';

    expect(modelTextRule).toContain('display: grid');
    expect(modelTextRule).toContain('min-width: 0');
    expect(modelTextContentRule).toContain('display: block');
    expect(modelTextContentRule).toContain('overflow-wrap: anywhere');
  });

  it('expands non-live reasoning snapshots even if their persisted status is running', () => {
    const messages: CoreMessage[] = [{
      id: 'm-history-running',
      role: 'assistant',
      content: 'Done.',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-running-snapshot',
        partType: 'reasoning',
        status: 'running',
        label: '思考',
        content: 'This was persisted from a streaming snapshot.',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-history-running']),
      },
    });

    expect(wrapper.find('.process-step--reasoning').exists()).toBe(true);
    expect(wrapper.find('.reasoning-body').exists()).toBe(true);
    expect(wrapper.find('.reasoning-body').text()).toContain('persisted from a streaming snapshot');
  });

  it('keeps completed reasoning expanded while the turn is still live', () => {
    const messages: CoreMessage[] = [{
      id: 'm-live-completed-reasoning',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { live: true, timeline: true },
      parts: [{
        id: 'p-live-completed-reasoning',
        partType: 'reasoning',
        status: 'completed',
        label: '思考',
        content: 'Earlier model call reasoning is complete.',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: { messages },
    });

    expect(wrapper.find('.process-step--reasoning').exists()).toBe(true);
    expect(wrapper.find('.reasoning-body').exists()).toBe(true);
    expect(wrapper.find('.reasoning-body').text()).toContain('Earlier model call reasoning is complete.');
  });

  it('keeps all tool details expanded while the turn is still live', () => {
    const messages: CoreMessage[] = [{
      id: 'm-live-tools',
      role: 'assistant',
      content: '',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { live: true, timeline: true },
      parts: [
        {
          id: 'p-tool-running',
          partType: 'tool_call',
          status: 'running',
          label: 'run_command',
          toolName: 'run_command',
          toolArgs: { command: 'npm test' },
          toolResult: 'running output',
        },
        {
          id: 'p-tool-completed',
          partType: 'tool_call',
          status: 'completed',
          label: 'read_file',
          toolName: 'read_file',
          toolArgs: { path: 'app.js' },
          toolResult: 'completed output',
        },
      ],
    }];

    const wrapper = mount(ChatThread, {
      props: { messages },
    });

    const bodies = wrapper.findAll('.tool-card-body');
    expect(bodies).toHaveLength(2);
    expect(bodies[0].text()).toContain('running output');
    expect(bodies[1].text()).toContain('completed output');
  });

  it('shows only runtime metrics in the collapsed process bar', () => {
    const messages: CoreMessage[] = [{
      id: 'm-metrics',
      role: 'assistant',
      content: 'Done.',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: {
        timeline: true,
        processMetrics: {
          duration_ms: 12_300,
          input_tokens: 120,
          output_tokens: 45,
          total_tokens: 165,
          cache_hit_rate: 0.5,
          llm_calls: 2,
        },
      },
      parts: [{
        id: 'p-reasoning',
        partType: 'reasoning',
        status: 'completed',
        label: '思考',
        content: 'Inspecting files.',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: { messages },
    });

    const text = wrapper.find('.process-toggle-text').text();
    expect(text).toBe('模型调用 2 次 · 耗时 12 s · Token 165 · 命中率 50%');
    expect(text).not.toContain('总输入');
    expect(text).not.toContain('总输出');
    expect(text).not.toContain('LLM');
    expect(text).not.toContain('已处理');
    expect(text).not.toContain('思考');
  });

  it('falls back to process counts when collapsed metrics are missing', () => {
    const messages: CoreMessage[] = [{
      id: 'm-missing-metrics',
      role: 'assistant',
      content: 'Done.',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true, processMetrics: {} },
      parts: [{
        id: 'p-reasoning',
        partType: 'reasoning',
        status: 'completed',
        label: '思考',
        content: 'Inspecting files.',
      }, {
        id: 'p-tool',
        partType: 'tool_call',
        status: 'error',
        label: 'run_command',
        toolName: 'run_command',
        content: 'pytest failed',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: { messages },
    });

    expect(wrapper.find('.process-toggle-text').text()).toBe('1 个工具 · 1 段思考 · 1 个失败');
  });

  it('renders live process above live answer text', () => {
    const messages: CoreMessage[] = [{
      id: 'm-live-order',
      role: 'assistant',
      content: 'Final answer is streaming.',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { live: true, liveStatus: '正在处理' },
      parts: [{
        id: 'p-live-tool',
        partType: 'tool_call',
        status: 'running',
        label: 'run_command',
        toolName: 'run_command',
        detail: 'Running tests',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: { messages },
    });

    const html = wrapper.find('.assistant-message').html();
    expect(html.indexOf('process-stream--live')).toBeLessThan(html.indexOf('Final answer is streaming.'));
  });

  it('does not compute historical reasoning duration from wall clock when completion time is missing', () => {
    const messages: CoreMessage[] = [{
      id: 'm-historical-running-reasoning',
      role: 'assistant',
      content: 'Done.',
      timestamp: '2026-06-18T00:00:00.000Z',
      metadata: { timeline: true },
      parts: [{
        id: 'p-running-reasoning',
        partType: 'reasoning',
        status: 'running',
        label: '思考',
        content: 'Historical reasoning without a terminal timestamp.',
        startedAt: '2026-06-18T00:00:00.000Z',
      }],
    }];

    const wrapper = mount(ChatThread, {
      props: {
        messages,
        processExpandedIds: new Set(['m-historical-running-reasoning']),
      },
    });

    expect(wrapper.text()).not.toContain('Thought for');
  });
});
