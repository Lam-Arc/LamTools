import { t } from '@/i18n/index.ts'

import type { GuideChapter, GuideOptions } from '@/guide/types.ts'

/**
 * 引导的全部文案与顺序。
 *
 * user:“包括但不限于agent流程，如模型配置，一套完整的对话工作流程包括切换
 *      模式权限模型思考等级，审批等”
 * user:“还有ping环和桌宠，库，定时任务，super agent，插件等，你自行设计”
 * +(章节顺序按「一个完全没碰过电脑的人第一次打开 Sunday」的真实顺序排：
 *   会点会打字 → 知道我是谁 → 认识界面 → 看一遍完整对话 → 三个旋钮 →
 *   其余房间 → 桌面上的 Ping/桌宠 → 模型配置 → 毕业。)
 *
 * 写作规则（改文案时请守住）：
 * 1. 一句话说一件事，不堆术语；必须出现的名词紧跟一句解释。
 * 2. 不给用户制造“我是不是点错了”的恐惧：每一步都留可退的路。
 * 3. 不复述按钮文字，而是说明“按了会发生什么”。
 */

function basicsChapter(): GuideChapter {
  return {
    id: 'basics',
    get title() { return t("先会三件小事") },
    get summary() { return t("点一下、打字、滚动。会了这三样，整台电脑都能用。") },
    steps: [
      {
        id: 'basics-click',
        kind: 'practice',
        exercise: 'click',
        get title() { return t("第一件：点一下") },
        get body() {
          return t("把鼠标挪到下面这个圆点上，用食指按一下鼠标左键，再松开。这就叫「点一下」。")
        },
        get hint() { return t("用触控板：一根手指轻点一下就是点击。") },
      },
      {
        id: 'basics-type',
        kind: 'practice',
        exercise: 'type',
        get title() { return t("第二件：打字") },
        get body() {
          return t("先在下面的方框里点一下，看到竖线在闪，再用键盘敲出「你好」两个字。")
        },
        get hint() { return t("打错了按键盘上的 Backspace 删掉，不会弄坏任何东西。") },
      },
      {
        id: 'basics-scroll',
        kind: 'practice',
        exercise: 'scroll',
        get title() { return t("第三件：滚动") },
        get body() {
          return t("把鼠标放在下面这块区域里，用食指拨一下鼠标中间的轮子，让里面的字往上走。")
        },
        get hint() { return t("触控板：两根手指上下划。") },
      },
    ],
  }
}

function welcomeChapter(): GuideChapter {
  return {
    id: 'welcome',
    get title() { return t("我是谁") },
    get summary() { return t("一个住在你电脑里的帮手，不是网页，也不是聊天软件。") },
    steps: [
      {
        id: 'welcome-hello',
        kind: 'story',
        scene: 'welcome',
        get title() { return t("我是 Sunday，住在你电脑里") },
        get body() {
          return t("你可以把我当成一个会用电脑的帮手。你说要做什么，我来动手：看文件、整理资料、改表格、跑命令、查网页。")
        },
        get bullets() {
          return [t("不用记命令，说人话就行"), t("做错了可以叫停"), t("这套引导随时能点左边的「?」重看")]
        },
      },
      {
        id: 'welcome-trust',
        kind: 'story',
        scene: 'trust',
        get title() { return t("三件让你放心的事") },
        get body() {
          return t("第一，你的文件默认只留在这台电脑上。第二，我要删东西、发东西、动重要文件之前，会先停下来问你。第三，任何时候你都能按红色的停止按钮让我停。")
        },
      },
      {
        id: 'welcome-loop',
        kind: 'story',
        scene: 'loop',
        get title() { return t("跟我打交道，就三步") },
        get body() {
          return t("你说清楚要什么；我一边做，一边把过程摊开给你看；遇到要你点头的地方，我停下来等你。")
        },
      },
    ],
  }
}

function interfaceChapter(): GuideChapter {
  return {
    id: 'interface',
    get title() { return t("认识这张脸") },
    get summary() { return t("这四样东西认全，剩下的自己摸就行。") },
    steps: [
      {
        id: 'interface-rail',
        kind: 'spotlight',
        target: '[data-app-rail]',
        placement: 'right',
        get title() { return t("左边这一列是「大门」") },
        get body() {
          return t("从上到下依次是：聊天、调用台、Super-agent、定时任务、资料库、插件、设置。名字记不住没关系，鼠标停上去会显示中文。")
        },
        get hint() { return t("不管去到哪一页，点最上面的「聊天」都能回到对话。") },
      },
      {
        id: 'interface-composer',
        kind: 'spotlight',
        target: '[data-ui-id="shell.composer"]',
        placement: 'top',
        get title() { return t("这个长条，是你说话的地方") },
        get body() {
          return t("点进去，打一句话，按 Enter 我就开始干活。想换行就按 Shift+Enter，不会发出去。")
        },
        get hint() { return t("输入框左边的回形针，是把文件递给我看。") },
      },
      {
        id: 'interface-runtime',
        kind: 'spotlight',
        target: '[data-core-runtime-menu]',
        placement: 'top',
        get title() { return t("这两个词决定我怎么干活") },
        get body() {
          return t("左边是运行模式，决定我用哪套本事；右边是权限审批，决定我做事到什么程度要先问你。")
        },
      },
      {
        id: 'interface-model',
        kind: 'spotlight',
        target: '[data-core-model-thinking-menu]',
        placement: 'top',
        get title() { return t("这里决定用哪个脑子、想多深") },
        get body() {
          return t("左边是模型，右边是思考强度。小事选轻一点快一点，难题选高一点准一点。")
        },
      },
    ],
  }
}

function demoChapter(): GuideChapter {
  return {
    id: 'demo',
    get title() { return t("看一遍完整对话") },
    get summary() { return t("一段本地假会话：不会联网，不会花钱，也不会动你的文件。") },
    steps: [
      {
        id: 'demo-play',
        kind: 'demo',
        get title() { return t("我带你走一遍") },
        get body() {
          return t("下面是一个练习用的假会话。你可以自己点「发送」，也可以亲手点一次审批，看看我停下来问你的时候是什么样子。")
        },
      },
    ],
  }
}

function knobsChapter(): GuideChapter {
  return {
    id: 'knobs',
    get title() { return t("三个旋钮") },
    get summary() { return t("审批、模型、思考强度。调错了不会坏，最多慢一点或笨一点。") },
    steps: [
      {
        id: 'knobs-permission',
        kind: 'spotlight',
        target: '[data-core-runtime-menu]',
        placement: 'top',
        get title() { return t("审批：什么时候要我点头") },
        get body() {
          return t("默认是「询问」，也是最稳的：日常小动作我自己做，真正会改动东西的动作先问你。「自动」放宽一档，「完全访问」基本不再拦。")
        },
        get hint() { return t("拿不准就用「询问」。慢一点，但不会出事。") },
      },
      {
        id: 'knobs-model',
        kind: 'spotlight',
        target: '[data-core-model-thinking-menu]',
        placement: 'top',
        get title() { return t("模型：用哪个大脑") },
        get body() {
          return t("不同模型价钱和本事不一样。贵的更会啃复杂问题，免费的适合日常整理和聊天。不是越贵越好，够用就行。")
        },
      },
      {
        id: 'knobs-thinking',
        kind: 'spotlight',
        target: '[data-core-model-thinking-menu]',
        placement: 'top',
        get title() { return t("思考强度：让它想多久") },
        get body() {
          return t("调高之后，它会先在肚子里打草稿再回答，难题更靠谱，但更慢、更费额度。改标题、翻译这种小事，调低反而顺手。")
        },
        get hint() { return t("打开模型卡片就能拉这根滑条，改完立刻生效，不用确认。") },
      },
    ],
  }
}

function roomsChapter(): GuideChapter {
  return {
    id: 'rooms',
    get title() { return t("其余六个房间") },
    get summary() { return t("除了聊天，Sunday 还有五个能干活的地方，外加一个设置。") },
    steps: [
      {
        id: 'rooms-direct',
        kind: 'spotlight',
        target: '[data-rail-entry="direct"]',
        placement: 'right',
        openArea: 'direct',
        get openLabel() { return t("进去看一眼") },
        get title() { return t("调用台：不聊天，直接问一句") },
        get body() {
          return t("把它当计算器用：问一句、拿一句答案，不留下整段对话。翻译、改写、算个数都合适。")
        },
      },
      {
        id: 'rooms-superagent',
        kind: 'spotlight',
        target: '[data-rail-entry="superagent"]',
        placement: 'right',
        openArea: 'superagent',
        get openLabel() { return t("进去看一眼") },
        get title() { return t("Super-agent：把一整件事交出去") },
        get body() {
          return t("不是问一句答一句，而是给它一个目标，它自己拆步骤、自己检查、最后把结果交给你。适合「把这个文件夹整理好」这种一整摊事。")
        },
      },
      {
        id: 'rooms-arrange',
        kind: 'spotlight',
        target: '[data-rail-entry="arrange"]',
        placement: 'right',
        openArea: 'arrange',
        get openLabel() { return t("进去看一眼") },
        get title() { return t("定时任务：让它按点自己干") },
        get body() {
          return t("比如每天早上八点，把昨天下载文件夹里的新东西列个清单给你。设一次，之后它自己跑。")
        },
      },
      {
        id: 'rooms-library',
        kind: 'spotlight',
        target: '[data-rail-entry="library"]',
        placement: 'right',
        openArea: 'library',
        get openLabel() { return t("进去看一眼") },
        get title() { return t("资料库：它给你留下的东西都在这") },
        get body() {
          return t("做出来的表格、图、报告，还有你收藏的内容，都归在这里。忘了放哪，来这翻。")
        },
      },
      {
        id: 'rooms-plugins',
        kind: 'spotlight',
        target: '[data-rail-entry="plugins"]',
        placement: 'right',
        openArea: 'plugins',
        get openLabel() { return t("进去看一眼") },
        get title() { return t("插件：给它加新本事") },
        get body() {
          return t("默认它只会基本操作。装上插件，它才能接别家服务、连你的账号。装之前看清楚它要什么权限。")
        },
      },
      {
        id: 'rooms-settings',
        kind: 'spotlight',
        target: '[data-rail-entry="settings"]',
        placement: 'right',
        openArea: 'settings',
        get openLabel() { return t("进去看一眼") },
        get title() { return t("设置：换模型、开桌宠、调权限都在这") },
        get body() {
          return t("找不到某个开关时，先来设置里翻一遍。界面、权限、桌宠、Ping 全在里面。")
        },
      },
    ],
  }
}

function desktopChapter(): GuideChapter {
  return {
    id: 'desktop',
    get title() { return t("桌面上的两个小家伙") },
    get summary() { return t("Ping 环和桌宠。它们是可选的，不想要随时关。") },
    steps: [
      {
        id: 'desktop-ping',
        kind: 'story',
        scene: 'ping',
        get title() { return t("Ping 环：指哪问哪") },
        get body() {
          return t("在桌面上按 Ctrl+Alt+Space，会浮出一个环。圈住屏幕上一块地方，就能问我这是什么、或者让我照着改。")
        },
        get hint() { return t("快捷键和环形菜单都能在设置 → Ping 里改，也能整个关掉。") },
      },
      {
        id: 'desktop-pet',
        kind: 'story',
        scene: 'pet',
        get title() { return t("桌宠：桌面上的小家伙") },
        get body() {
          return t("它待在桌面角落，表情就是我的状态：在想、在干活、在等你确认。点它能直接说话。")
        },
        get hint() { return t("不想要就去设置 → 桌宠把它收起来，聊天功能一点不受影响。") },
      },
    ],
  }
}

function providerChapter(options: GuideOptions): GuideChapter {
  if (options.hasProvider) {
    return {
      id: 'provider',
      get title() { return t("模型在哪换") },
      get summary() { return t("你已经配好了，这里只记个门。") },
      steps: [
        {
          id: 'provider-configured',
          kind: 'spotlight',
          target: '[data-rail-entry="settings"]',
          placement: 'right',
          openArea: 'settings',
          get openLabel() { return t("去看看") },
          get title() { return t("你已经有大脑了") },
          get body() {
            return t("以后想换模型、想加一家更便宜的：设置 →「模型与供应商」。填错了也不怕，删掉重来就行。")
          },
        },
      ],
    }
  }
  return {
    id: 'provider',
    get title() { return t("还差一个大脑") },
    get summary() { return t("Sunday 自己不聪明，要接一个模型服务。") },
    steps: [
      {
        id: 'provider-missing',
        kind: 'story',
        scene: 'provider',
        get title() { return t("还差一步：给我一个大脑") },
        get body() {
          return t("Sunday 自己不会思考，要接一个模型服务。去 DeepSeek、通义、智谱这类网站注册，拿到一串以 sk- 开头的钥匙，粘进设置里就行。")
        },
        get bullets() {
          return [t("打开设置 →「模型与供应商」"), t("选一家官方模板，按提示申请钥匙"), t("粘进去，保存，就能开始说话")]
        },
        get hint() { return t("现在不想弄也行：教学示例不用联网，先玩着，回头再配。") },
      },
    ],
  }
}

function finishChapter(): GuideChapter {
  return {
    id: 'finish',
    get title() { return t("毕业") },
    get summary() { return t("三句话记住 Sunday，就可以开始了。") },
    steps: [
      {
        id: 'finish-done',
        kind: 'story',
        scene: 'done',
        get title() { return t("到这儿，你已经会用了") },
        get body() {
          return t("记住三件事就够：在下面长条里打字说话；关键处我会停下来问你；卡住了就点左边的「?」。")
        },
        get bullets() {
          return [t("试着让我把下载文件夹整理一遍"), t("把一篇长文章丢给我，让我讲成人话"), t("让我每天早上提醒你一件事")]
        },
      },
    ],
  }
}

/**
 * 按用户的选择拼出这次要走的章节。
 *
 * quick 只保留「够用」的主干：我是谁 → 认识界面 → 看一遍对话 → 毕业。
 * full 才加上基本功、三个旋钮、其余房间、桌面功能、模型配置。
 */
export function buildGuideChapters(options: GuideOptions): GuideChapter[] {
  const chapters: GuideChapter[] = []
  if (options.beginner) chapters.push(basicsChapter())
  chapters.push(welcomeChapter())
  chapters.push(interfaceChapter())
  chapters.push(demoChapter())
  if (options.mode === 'full') {
    chapters.push(knobsChapter())
    chapters.push(roomsChapter())
    chapters.push(desktopChapter())
    chapters.push(providerChapter(options))
  }
  chapters.push(finishChapter())
  return chapters
}

/** 拉平成一条线性路径，进度、上一句/下一句都只跟这个下标打交道。 */
export function flattenGuideSteps(chapters: GuideChapter[]) {
  const steps: Array<{
    step: GuideChapter['steps'][number]
    chapterId: string
    chapterTitle: string
    chapterIndex: number
    chapterCount: number
    /** 该步在整条路径里的序号（从 1 开始）。 */
    ordinal: number
    total: number
  }> = []
  const total = chapters.reduce((sum, chapter) => sum + chapter.steps.length, 0)
  let ordinal = 0
  chapters.forEach((chapter, chapterIndex) => {
    chapter.steps.forEach((step) => {
      ordinal += 1
      steps.push({
        step,
        chapterId: chapter.id,
        chapterTitle: chapter.title,
        chapterIndex,
        chapterCount: chapters.length,
        ordinal,
        total,
      })
    })
  })
  return steps
}
