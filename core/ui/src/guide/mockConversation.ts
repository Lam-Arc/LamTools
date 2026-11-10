import { t } from '@/i18n/index.ts'
import type { CoreMessage, MessagePart } from '@/types.ts'

/**
 * 教学示例会话：一段完全在本机演出来的 agent 流程。
 *
 * user:“可以自动建一个教学示例会话，使用mock数据流演示并走过完整agent流程
 *      （不调用真实API）”+
 * (这里只产出「消息长什么样」，不碰网络、不写数据库、不启动真正的回合。组件
 *  按阶段推进；每一步的解说单独给出，让旁白和画面永远对得上。)
 *
 * 演示的任务刻意选最日常的一件：整理下载文件夹。它同时覆盖了读文件、
 * 征求许可、写文件三种动作，看完正好理解「审批」到底在拦什么。
 */

export type MockStage = 'idle' | 'thinking' | 'reading' | 'approval' | 'writing' | 'denied' | 'answered'

export type MockAction = 'send' | 'advance' | 'allow-once' | 'trust-kind' | 'deny'

export interface MockChoice {
  id: 'allow-once' | 'trust-kind' | 'deny'
  label: string
  description: string
  tone: 'approve' | 'trust' | 'deny'
}

export const MOCK_CHOICES: MockChoice[] = [
  {
    id: 'allow-once',
    get label() { return t("允许这一次") },
    get description() { return t("只处理这一回，下次还会再问你") },
    tone: 'approve',
  },
  {
    id: 'trust-kind',
    get label() { return t("以后这类都允许") },
    get description() { return t("同类操作不再打断你；危险的仍然会问") },
    tone: 'trust',
  },
  {
    id: 'deny',
    get label() { return t("先不要") },
    get description() { return t("我什么都不动，等你改主意") },
    tone: 'deny',
  },
]

export const MOCK_USER_TEXT = '帮我把下载文件夹整理一下，按图片、文档、压缩包分好'

export interface MockConversationState {
  stage: MockStage
  /** 用户点过发送没有。 */
  sent: boolean
  /** 用户选的审批项。 */
  choice: MockChoice['id'] | null
  /** 选过「以后这类都允许」：结局里要提一句。 */
  trusted: boolean
  /** 拒绝过：结局要一直走「什么都没动」那一支，不能因为推进阶段被冲掉。 */
  denied: boolean
}

export function createMockConversation(): MockConversationState {
  return { stage: 'idle', sent: false, choice: null, trusted: false, denied: false }
}

/**
 * 状态推进。返回新对象，方便测试直接对拍每一步。
 * 非法动作原样返回，不抛错——用户乱点不该把教学演崩。
 */
export function reduceMockConversation(state: MockConversationState, action: MockAction): MockConversationState {
  switch (action) {
    case 'send':
      return state.stage === 'idle' ? { ...state, stage: 'thinking', sent: true } : state
    case 'advance':
      if (state.stage === 'thinking') return { ...state, stage: 'reading' }
      if (state.stage === 'reading') return { ...state, stage: 'approval' }
      if (state.stage === 'writing' || state.stage === 'denied') return { ...state, stage: 'answered' }
      return state
    case 'allow-once':
    case 'trust-kind':
    case 'deny': {
      if (state.stage !== 'approval') return state
      if (action === 'deny') return { ...state, stage: 'denied', choice: action, denied: true }
      return { ...state, stage: 'writing', choice: action, trusted: action === 'trust-kind', denied: false }
    }
    default:
      return state
  }
}

/** 当前这一幕的旁白。 */
export function mockCaption(state: MockConversationState): { title: string; why: string } {
  switch (state.stage) {
    case 'idle':
      return {
        get title() { return t("先按一次发送") },
        get why() { return t("左边是你打的字。按下面的发送键，我就开始干活。") },
      }
    case 'thinking':
      return {
        get title() { return t("第一步：我在想你这句话该怎么做") },
        get why() { return t("这一步叫「思考」。思考强度调得越高，这里停得越久，但想得更周全。") },
      }
    case 'reading':
      return {
        get title() { return t("第二步：先看清楚现状，再动手") },
        get why() { return t("我只读，不改。读取这类不碰坏东西的动作，一般不会来打扰你。") },
      }
    case 'approval':
      return {
        get title() { return t("第三步：要动你的文件了，我停下来问你") },
        get why() { return t("这就是「审批」。它不是走过场：你不点，我就不动。想清楚再选，选错也能撤回。") },
      }
    case 'writing':
      return {
        get title() { return t("第四步：动手，过程摆在明面上") },
        get why() { return t("它做了什么、动了几个文件，都写在过程里。不满意随时可以叫停。") },
      }
    case 'denied':
      return {
        get title() { return t("你说了先不要") },
        get why() { return t("拒绝是有效的：我一点没动。你随时可以换个说法，或者自己来。") },
      }
    case 'answered':
      return {
        get title() { return t("完成：给你结果，也告诉你东西在哪") },
        get why() { return t("收尾时它会把做过的事、产出在哪说清楚，不用你自己猜。") },
      }
  }
}

function part(base: MessagePart): MessagePart {
  return base
}

/** 学生这一侧发出去的那句话。 */
export function mockUserMessage(state: MockConversationState): CoreMessage | null {
  if (!state.sent) return null
  return {
    id: 'guide-demo-user',
    role: 'user',
    content: MOCK_USER_TEXT,
    timestamp: new Date().toISOString(),
    parts: [{ id: 'guide-demo-user-text', partType: 'text', status: 'completed', content: MOCK_USER_TEXT }],
  }
}

function reasoningPart(state: MockConversationState): MessagePart | null {
  if (state.stage === 'idle' || state.stage === 'thinking') {
    return part({
      id: 'guide-demo-reasoning',
      partType: 'reasoning',
      status: state.stage === 'thinking' ? 'running' : 'completed',
      get label() { return t("思考") },
      get content() {
        return t("先看看下载文件夹里有什么，按图片、文档、压缩包分好，再动手移动。移动会改文件，所以要先问过一次。心里先有个分法，再动手。")
      },
    })
  }
  return part({
    id: 'guide-demo-reasoning',
    partType: 'reasoning',
    status: 'completed',
    get label() { return t("思考") },
    get content() {
      return t("先看看下载文件夹里有什么，按图片、文档、压缩包分好，再动手移动。移动会改文件，所以要先问过一次。心里先有个分法，再动手。")
    },
  })
}

function readPart(state: MockConversationState): MessagePart | null {
  const beforeRead = state.stage === 'idle' || state.stage === 'thinking'
  if (beforeRead) return null
  return part({
    id: 'guide-demo-read',
    partType: 'tool_call',
    status: 'completed',
    get label() { return t("查看目录") },
    toolName: 'list_dir',
    toolArgs: { path: '下载文件夹' },
    get toolResult() {
      return t("共 37 个文件：图片 18、文档 9、压缩包 6、其他 4。没有重名冲突。")
    },
  })
}

function decisionPart(state: MockConversationState): MessagePart | null {
  if (state.stage === 'idle' || state.stage === 'thinking' || state.stage === 'reading') return null
  const pending = state.stage === 'approval'
  return part({
    id: 'guide-demo-decision',
    partType: 'decision',
    status: pending ? 'pending' : 'completed',
    toolName: 'move_files',
    toolArgs: {
      get title() { return t("把 37 个文件按类型移动") },
      get reason() { return t("要把 37 个文件按类型移动到 4 个子文件夹。不会删除任何文件。") },
      options: MOCK_CHOICES.map(choice => ({
        id: choice.id,
        get label() { return choice.label },
        get description() { return choice.description },
      })),
    },
  })
}

function writePart(state: MockConversationState): MessagePart | null {
  if (state.denied) return null
  if (state.stage !== 'writing' && state.stage !== 'answered') return null
  if (state.choice === 'deny') return null
  return part({
    id: 'guide-demo-write',
    partType: 'tool_call',
    status: 'completed',
    get label() { return t("移动文件") },
    toolName: 'move_files',
    toolArgs: { path: '下载文件夹', files: 37, folders: 4 },
    get toolResult() {
      return t("已移动 37 个文件到 4 个文件夹，失败 0 个。原文件没有删除，只换了位置。")
    },
  })
}

function choiceEchoPart(state: MockConversationState): MessagePart | null {
  if (!state.choice) return null
  const chosen = MOCK_CHOICES.find(choice => choice.id === state.choice)
  if (!chosen) return null
  return part({
    id: 'guide-demo-choice',
    partType: 'status',
    status: 'completed',
    get label() { return t("你的选择") },
    content: chosen.label,
  })
}

/** 结论：允许走完是一套，拒绝是另一套。 */
export function mockAnswerText(state: MockConversationState): string {
  if (state.stage !== 'answered' && state.stage !== 'denied') return ''
  if (state.denied) {
    return t("明白，这次不动。下载文件夹我一点没改。 如果你只是想把图片挑出来，我可以只列一份清单，不移动任何文件。要这样吗？")
  }
  const trusted = state.trusted
    ? t("另外，你选了「以后这类都允许」，同类整理下次我会直接做，不再来问你。")
    : t("下次同类操作我还是会先问你。")
  return t("整理好了。下载文件夹里 37 个文件，按类型分进了 4 个文件夹：")
    + '\n\n'
    + '- ' + t("图片 18 个 → 图片/")
    + '\n'
    + '- ' + t("文档 9 个 → 文档/")
    + '\n'
    + '- ' + t("压缩包 6 个 → 压缩包/")
    + '\n'
    + '- ' + t("其他 4 个 → 其他/")
    + '\n\n'
    + t("我没有删任何东西，只是移动。想还原就跟我说「把刚才的整理撤回」。")
    + '\n\n'
    + trusted
}

function statusPart(id: string, label: string): MessagePart {
  return part({ id, partType: 'status', status: 'completed', label })
}

/**
 * 组装这个阶段的助手消息。
 *
 * `answerChars` 用来做逐字出现的假流式：只截结论，不截过程。
 * 传空字符串表示还没开始输出结论。
 *
 * 中间插两条 status 不是为了好看：渲染器会把连续的「思考 + 工具」折叠成
 * 「N 步」，教学演示里每一步都该被看见，状态行正好把折叠切开。
 */
export function mockAssistantMessage(state: MockConversationState, answerChars = Number.POSITIVE_INFINITY): CoreMessage | null {
  if (state.stage === 'idle') return null
  const fullAnswer = mockAnswerText(state)
  const answer = fullAnswer.slice(0, Math.max(0, answerChars))
  const parts: MessagePart[] = []
  const reasoning = reasoningPart(state)
  if (reasoning) parts.push(reasoning)
  if (state.stage !== 'thinking') {
    parts.push(statusPart('guide-demo-status-read', t("先看清楚现状，再决定怎么分")))
  }
  const read = readPart(state)
  if (read) parts.push(read)
  if (state.stage === 'approval' || state.stage === 'writing' || state.stage === 'answered' || state.stage === 'denied') {
    parts.push(statusPart('guide-demo-status-approve', t("这一步会改文件，先问过你")))
  }
  const decision = decisionPart(state)
  if (decision) parts.push(decision)
  const echo = choiceEchoPart(state)
  if (echo) parts.push(echo)
  const write = writePart(state)
  if (write) parts.push(write)
  if (fullAnswer) {
    parts.push({
      id: 'guide-demo-answer',
      partType: 'model_text',
      status: state.stage === 'answered' || state.stage === 'denied' ? 'completed' : 'running',
      content: answer,
    })
  }
  return {
    id: 'guide-demo-assistant',
    role: 'assistant',
    content: answer,
    timestamp: new Date().toISOString(),
    parts,
    metadata: { runtime_model_id: 'guide-demo' },
  }
}
