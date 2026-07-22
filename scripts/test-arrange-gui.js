const { chromium } = require('playwright');

(async () => {
  const BASE = process.env.LAMTOOLS_GUI_URL || 'http://127.0.0.1:5173';
  const SCREENSHOT_DIR = process.env.SCREENSHOT_DIR || process.cwd();

  console.log(`启动浏览器，导航到 ${BASE}`);
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  let passed = 0, failed = 0;

  async function check(desc, fn) {
    process.stdout.write(`  ${desc} ... `);
    try {
      await fn();
      console.log('\x1b[32mPASS\x1b[0m');
      passed++;
    } catch (e) {
      console.log('\x1b[31mFAIL\x1b[0m');
      console.log(`    ${e.message}`);
      await page.screenshot({ path: `${SCREENSHOT_DIR}/playwright-fail-${desc.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '-')}.png` });
      failed++;
    }
  }

  async function screenshot(name) {
    await page.screenshot({ path: `${SCREENSHOT_DIR}/playwright-${name}.png` });
    console.log(`    截图: ${SCREENSHOT_DIR}/playwright-${name}.png`);
  }

  try {
    // ---- Navigate ----
    await page.goto(BASE, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(2000);
    await screenshot('01-initial');

    // ---- B1: Click "长期安排" in sidebar footer ----
    await check('B1 打开安排管理页', async () => {
      const btn = page.locator('.sidebar-action', { hasText: '长期安排' });
      await btn.waitFor({ state: 'visible', timeout: 10000 });
      await btn.click();
      await page.waitForTimeout(1000);
      // Verify the arrange page appears
      await page.waitForSelector('.arrange-page', { timeout: 5000 });
      await screenshot('02-arrange-page');
    });

    // Check if there are any cards
    const cardCount = await page.locator('.arrange-card').count();
    console.log(`  发现 ${cardCount} 张安排卡片`);

    if (cardCount === 0) {
      // ---- B7: Empty state ----
      await check('B7 空状态提示', async () => {
        const empty = page.locator('.arrange-empty');
        await empty.waitFor({ state: 'visible', timeout: 3000 });
        const text = await empty.textContent();
        if (!text || !text.includes('还没有安排')) throw new Error(`unexpected empty text: ${text}`);
      });
    } else {
      // ---- B2: Edit title inline ----
      await check('B2 编辑标题', async () => {
        const title = page.locator('.card-title').first();
        const oldText = await title.textContent();
        await title.click();
        const input = page.locator('.title-edit').first();
        await input.waitFor({ state: 'visible', timeout: 3000 });
        await input.fill('Playwright测试标题');
        await input.press('Enter');
        await page.waitForTimeout(500);
        await screenshot('03-title-edited');
      });

      // ---- B3: Edit instruction inline ----
      await check('B3 编辑指令', async () => {
        const instr = page.locator('.card-instruction').first();
        await instr.click();
        const textarea = page.locator('.instruction-edit').first();
        await textarea.waitFor({ state: 'visible', timeout: 3000 });
        await textarea.fill('Playwright修改后的指令');
        // Ctrl+Enter to confirm
        await page.locator('.edit-hint .mini-btn').first().click();
        await page.waitForTimeout(500);
        await screenshot('04-instruction-edited');
      });

      // ---- B4: Toggle session strategy ----
      await check('B4 切换会话策略', async () => {
        const sessionBtn = page.locator('.meta-item.clickable', { hasText: '会话' }).first();
        const oldText = await sessionBtn.textContent();
        await sessionBtn.click();
        await page.waitForTimeout(500);
        const newText = await sessionBtn.textContent();
        if (oldText === newText) throw new Error('session strategy did not toggle');
        // Toggle back
        await sessionBtn.click();
        await screenshot('05-session-toggled');
      });

      // ---- B5: Expand run history ----
      await check('B5 展开运行历史', async () => {
        const expandBtn = page.locator('.expand-toggle').first();
        if (await expandBtn.count() === 0) {
          console.log('    (无运行历史，跳过)');
          return;
        }
        await expandBtn.click();
        await page.waitForTimeout(500);
        const panel = page.locator('.history-panel').first();
        await panel.waitFor({ state: 'visible', timeout: 3000 });
        await screenshot('06-history-expanded');
      });

      // ---- B6: Pause / Resume / Cancel ----
      await check('B6 暂停操作', async () => {
        const pauseBtn = page.locator('.action-btn', { hasText: '暂停' }).first();
        if (await pauseBtn.count() === 0) {
          console.log('    (无可暂停任务，跳过)');
          return;
        }
        await pauseBtn.click();
        await page.waitForTimeout(500);
        // Verify status label changed
        const statusLabel = page.locator('.status-label').first();
        const text = await statusLabel.textContent();
        if (!text || !text.includes('已暂停')) throw new Error(`unexpected status: ${text}`);
        await screenshot('07-paused');
      });

      // Resume
      await check('B6 恢复操作', async () => {
        const resumeBtn = page.locator('.action-btn', { hasText: '恢复' }).first();
        if (await resumeBtn.count() === 0) {
          console.log('    (无已暂停任务，跳过)');
          return;
        }
        await resumeBtn.click();
        await page.waitForTimeout(500);
        await screenshot('08-resumed');
      });
    }

    // ---- B7: Click "返回" ----
    await check('B7 返回按钮', async () => {
      const backBtn = page.locator('.text-button', { hasText: '返回' }).first();
      await backBtn.click();
      await page.waitForTimeout(500);
      // Verify we're back to main workspace (arrange-page should be gone from DOM or hidden)
      const arrangePage = page.locator('.arrange-page');
      const visible = await arrangePage.isVisible().catch(() => false);
      if (visible) throw new Error('arrange page still visible after back');
    });

  } catch (e) {
    console.log(`\n\x1b[31m测试异常: ${e.message}\x1b[0m`);
    await screenshot('error');
    failed++;
  }

  console.log(`\n=== Results: ${passed} passed, ${failed} failed ===`);
  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
})();