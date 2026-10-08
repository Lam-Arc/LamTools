// Shared beat helpers: get the window into a known state, pick a model, ask a
// prompt, and wait for the turn.  Beats stay short and readable because of this.

import { sleep } from '../driver/sunday.mjs'

export const DEFAULT_MODEL =
  process.env.DEMO_MODEL_ID || 'command-code-deepseek-deepseek-v4.1-flash'
export const DEFAULT_PROVIDER_LABEL = process.env.DEMO_PROVIDER_LABEL || 'Command Code'

/** Bring the window to a composer-ready state, creating a session if needed. */
export async function newSession(ctx, { hold = 700 } = {}) {
  const { actor, page } = ctx

  const startPage = page.locator('[data-start-new-session]')
  const emptyProject = page.locator('[data-project-empty-new]')

  if (await startPage.count() && (await startPage.first().isVisible().catch(() => false))) {
    await actor.click('[data-start-new-session]', { label: '新建会话（起始页）' })
  } else if (
    (await emptyProject.count()) &&
    (await emptyProject.first().isVisible().catch(() => false))
  ) {
    await actor.click('[data-project-empty-new]', { label: '新建会话（项目内）' })
  } else {
    await actor.click('[data-project-menu-trigger]', { label: '打开项目菜单' })
    await actor.click('[data-project-new]', { label: '新建会话（项目菜单）' })
  }

  await page.waitForSelector('.core-send-stop-button', { timeout: 30000 })
  await hold0(hold)
}

/** Pick a model in the composer, opening whichever submenu is needed. */
export async function pickModel(
  ctx,
  { model = DEFAULT_MODEL, providerLabel = DEFAULT_PROVIDER_LABEL, thinking = null, keepOpen = false } = {},
) {
  const { actor, page, note } = ctx

  // Scenes remember their model, so a fresh session usually already shows the
  // right one.  Typing the choice again would be a no-op the video can't show.
  const trigger = page.locator('.core-model-thinking-menu__trigger')
  const shown = (await trigger.first().innerText().catch(() => '')).trim()
  if (shown && shown.toLowerCase().includes(modelLabelHint(model))) {
    await actor.move('.core-model-thinking-menu__trigger', { label: `沿用模型 ${model}` })
    note(`model already ${model}`)
    if (thinking) await setThinking(ctx, thinking)
    return
  }

  // The list only renders after the 模型 row is opened, each provider group can
  // be collapsed, and the panel remembers the last opened row — so re-clicking
  // that row closes it again.  Everything below is written to be idempotent.
  const triggerSelector = '.core-model-thinking-menu__trigger'
  const sectionSelector = '[data-model-thinking-section="model"]'
  const optionSelector = `[data-model-thinking-model-option="${model}"]:visible`
  const hasOption = async () => (await page.locator(optionSelector).count()) > 0
  const menuOpen = async () =>
    (await page.locator(triggerSelector).first().getAttribute('aria-expanded').catch(() => null)) ===
    'true'

  if (!(await menuOpen())) {
    await actor.clickDirect(triggerSelector, { label: '打开模型菜单' })
  }
  for (let attempt = 0; attempt < 2 && !(await hasOption()); attempt += 1) {
    if (await visible(page.locator(sectionSelector))) {
      await actor.clickDirect(sectionSelector, { label: '展开模型列表' })
      note(`model row clicked (attempt ${attempt + 1}), options=${await page.locator(optionSelector).count()} raw=${await page.locator('[data-model-thinking-model-option]').count()}`)
    } else {
      note(`model row not visible (attempt ${attempt + 1}), menuOpen=${await menuOpen()}`)
    }
  }
  for (let attempt = 0; attempt < 2 && !(await hasOption()); attempt += 1) {
    const collapsed = page.locator(
      '[data-model-thinking-provider] .core-model-thinking-menu__provider-chevron--collapsed',
    )
    if (!(await collapsed.count())) break
    await actor.clickDirect(`[data-model-thinking-provider="${providerLabel}"]`, {
      label: `展开供应商 ${providerLabel}`,
    })
  }
  if (!(await hasOption())) {
    throw new Error(
      `model ${model} is not offered in the picker (provider ${providerLabel}) — refusing to guess`,
    )
  }
  await actor.clickDirect(optionSelector, { label: `选择模型 ${model}` })
  note(`model = ${model}`)

  if (thinking) {
    await actor.clickDirect('[data-model-thinking-section="thinking"]', { label: '展开思考等级' })
    const thinkingOption = page.locator(`[data-model-thinking-thinking-option="${thinking}"]`)
    if (await visible(thinkingOption)) {
      await actor.click(`[data-model-thinking-thinking-option="${thinking}"]`, {
        label: `思考等级 ${thinking}`,
      })
    }
  }

  if (!keepOpen) {
    await actor.press('Escape', { label: '关闭菜单' })
    await sleep(250)
  }
}

/** Type a prompt into the composer and send it, then wait for the turn to end. */
export async function askPrompt(ctx, text, { delay = 45, settleMs = 5000, wait = true } = {}) {
  const { actor, page, waitTurn } = ctx
  await actor.type('.composer-input-wrap textarea', text, { label: '输入提示词', delay })
  await sleep(Math.min(settleMs, 1500))
  await actor.click('.core-send-stop-button', { label: '发送' })
  if (wait) await waitTurn(page)
}

/** Queue follow-up text without waiting (for multi-turn beats). */
export async function typePrompt(ctx, text, { delay = 45, send = true } = {}) {
  const { actor } = ctx
  await actor.type('.composer-input-wrap textarea', text, { label: '输入提示词', delay })
  if (send) await actor.click('.core-send-stop-button', { label: '发送' })
}

export async function visible(locator) {
  if (!(await locator.count())) return false
  return locator.first().isVisible().catch(() => false)
}

/** Open the thinking submenu and pick a level (off/light/medium/high/xhigh/max). */
export async function setThinking(ctx, level) {
  const { actor, page, note } = ctx
  await actor.clickDirect('.core-model-thinking-menu__trigger', { label: '打开模型菜单' })
  const section = page.locator('[data-model-thinking-section="thinking"]')
  if (await visible(section)) {
    await actor.clickDirect('[data-model-thinking-section="thinking"]', { label: '展开思考等级' })
  }
  const option = page.locator(`[data-model-thinking-thinking-option="${level}"]`)
  if (await visible(option)) {
    await actor.clickDirect(`[data-model-thinking-thinking-option="${level}"]`, { label: `思考等级 ${level}` })
    note(`thinking = ${level}`)
  } else {
    note(`thinking option ${level} not offered; leaving as is`)
  }
  await actor.press('Escape', { label: '关闭菜单' })
  await sleep(250)
}

/** Map a model id to the display-name fragment shown on the trigger. */
function modelLabelHint(model) {
  // 'command-code-zai-org-glm-5.3' -> 'glm-5.3'; the trigger shows 'GLM-5.3'.
  const tail = String(model).split('/').pop().toLowerCase()
  const parts = tail.split('-')
  return parts.slice(-2).join('-')
}

async function hold0(ms) {
  await sleep(ms)
}
