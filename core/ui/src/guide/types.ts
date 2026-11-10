/**
 * 新手引导的数据模型。
 *
 * user:“为sunday做引导，流程与展示方式自主设计，说人话”
 * user:“诉求是让哪怕没接触过电脑的小白也能用明白sunday”
 * +(引导不是一份产品说明书，而是一条按顺序走的路：先补电脑基本功，再指认真实
 *   界面，再用一段本地假会话把完整 agent 流程演一遍，最后交代那些不常驻在
 *   聊天窗口里的功能。)
 *
 * 这里只放「长什么样」，不放「怎么渲染」。渲染由 GuideHost 决定，
 * 这样内容可以单独测试、单独改文案，不用碰动画代码。
 */

export type GuideMode = 'quick' | 'full'

/** 需要「真的把用户带过去」的整版分区。 */
export type GuideArea = 'direct' | 'superagent' | 'arrange' | 'library' | 'plugins' | 'settings'

export type GuidePlacement = 'auto' | 'top' | 'bottom' | 'left' | 'right'

/** 开场/过渡用的插画场景：全部是内联 SVG，不依赖外部图片。 */
export type GuideScene = 'welcome' | 'trust' | 'loop' | 'provider' | 'ping' | 'pet' | 'done'

interface GuideStepBase {
  id: string
  title: string
  /** 主体解说。允许分几段，用换行分隔；渲染时保持大字号、短句。 */
  body: string
  /** 小字补充，可省。用来放「做不到怎么办」这类兜底。 */
  hint?: string
}

/** 只讲故事、没有要点的下一步。 */
export interface GuideStoryStep extends GuideStepBase {
  kind: 'story'
  scene: GuideScene
  /** 可选的三条要点，渲染成带勾的短列表。 */
  bullets?: string[]
}

/** 零基础练习：必须真的完成动作才放行，但永远留一个「我做不到」的出口。 */
export interface GuidePracticeStep extends GuideStepBase {
  kind: 'practice'
  exercise: 'click' | 'type' | 'scroll'
}

/** 指向真实界面：在活着的界面上挖一个洞，把该看的地方点亮。 */
export interface GuideSpotlightStep extends GuideStepBase {
  kind: 'spotlight'
  /** 真实 DOM 选择器。找不到时这一步会被自动跳过，不把用户卡死在空屏上。 */
  target: string
  placement?: GuidePlacement
  /** 必须点中目标才继续；用于「点一下这里试试」的教学。 */
  waitForClick?: boolean
  /** 可以真的切到某个整版分区去瞄一眼。 */
  openArea?: GuideArea
  openLabel?: string
}

/** 剧场：本地 mock 会话，不调用任何真实 API。 */
export interface GuideDemoStep extends GuideStepBase {
  kind: 'demo'
}

export type GuideStep = GuideStoryStep | GuidePracticeStep | GuideSpotlightStep | GuideDemoStep

export interface GuideChapter {
  id: string
  title: string
  /** 目录里的一句话说明。 */
  summary: string
  steps: GuideStep[]
}

export interface GuideOptions {
  mode: GuideMode
  /** 完全没碰过电脑：追加最前面的电脑基本功章节。 */
  beginner: boolean
  /** 已经配过模型：把「配模型」那章换成「以后在哪改」。 */
  hasProvider: boolean
}
