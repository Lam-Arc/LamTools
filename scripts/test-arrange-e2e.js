const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();

  const WS_ROOT = 'E:\\LamTools\\playwright-test';
  const MSG = '请帮我安排一个任务：每两分钟在这个会话里向我汇报当前时间';

  // --- Step 1: Navigate ---
  console.log('[1] Navigating to core demo...');
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);

  // --- Step 2: Create workspace ---
  console.log('[2] Creating workspace:', WS_ROOT);

  // Click the "+" button
  let clicked = false;
  for (const sel of ['button[aria-label="新建项目"]', 'button.icon-btn']) {
    const btn = page.locator(sel).first();
    try {
      await btn.click({ timeout: 3000 });
      clicked = true;
      break;
    } catch {}
  }
  if (!clicked) {
    console.log('[2] Could not find new-project button, trying page content...');
    const btns = page.locator('button');
    const cnt = await btns.count();
    for (let i = 0; i < cnt; i++) {
      const text = await btns.nth(i).textContent();
      if (text && (text.includes('新建') || text === '+')) {
        await btns.nth(i).click();
        clicked = true;
        break;
      }
    }
  }

  await page.waitForTimeout(1500);

  // Fill path
  const rootInput = page.locator('input[data-project-root]');
  try {
    await rootInput.waitFor({ state: 'visible', timeout: 5000 });
    await rootInput.fill(WS_ROOT);
  } catch (e) {
    console.log('[2] Project dialog not found, may already have a workspace. Trying to proceed...');
  }
  await page.waitForTimeout(500);

  // Submit
  const submitBtn = page.locator('button[data-project-submit]');
  try {
    await submitBtn.click({ timeout: 3000 });
    console.log('[2] Project submit clicked.');
  } catch (e) {
    console.log('[2] Submit button not found, may already have a session.');
  }

  // Wait for dialog to close
  await page.waitForTimeout(3000);

  // Dismiss any remaining overlays
  try {
    const overlay = page.locator('.core-project-overlay, [data-project-backdrop], .modal-backdrop');
    if (await overlay.isVisible({ timeout: 2000 }).catch(() => false)) {
      await overlay.click({ force: true });
      console.log('[2] Dismissed overlay.');
      await page.waitForTimeout(1000);
    }
  } catch {}

  // --- Step 3: Send message ---
  console.log('[3] Sending message:', MSG);

  // Wait for session to be ready - textarea should be enabled
  await page.waitForTimeout(2000);
  const textarea = page.locator('textarea[placeholder*="发送"], textarea[placeholder*="任务"]').first();
  
  try {
    await textarea.waitFor({ state: 'visible', timeout: 10000 });
  } catch (e) {
    console.log('[3] Textarea not visible, checking page state...');
  }

  // Focus and type using keyboard
  await page.keyboard.press('Tab'); // Try to focus the textarea
  await page.waitForTimeout(300);
  
  // Click with force to bypass overlays
  try {
    await textarea.click({ force: true, timeout: 5000 });
  } catch {
    // Try triple-click on the page to ensure focus
    await page.locator('body').click({ position: { x: 400, y: 500 } });
    await page.waitForTimeout(300);
  }
  
  await page.waitForTimeout(500);
  await textarea.fill(MSG);
  await page.waitForTimeout(500);

  // Press Enter to send
  await textarea.press('Enter');
  console.log('[3] Message sent via Enter.');

  // --- Step 4: Wait for arrange tool call ---
  console.log('[4] Waiting for agent response (arrange tool call)...');

  try {
    await page.waitForFunction(() => {
      const text = document.body.innerText;
      return text.includes('arrange') || text.includes('安排');
    }, { timeout: 120000 });
    console.log('[4] Agent started processing (arrange detected).');
  } catch {
    console.log('[4] Timeout waiting for arrange text. Continuing...');
  }

  await page.waitForTimeout(8000);
  
  const bodyText = await page.evaluate(() => document.body.innerText);
  if (bodyText.includes('error') || bodyText.includes('错误') || bodyText.includes('失败')) {
    console.log('[4] WARNING: Possible error detected!');
    console.log('[4] Page text sample:', bodyText.substring(0, 1500));
  } else {
    console.log('[4] No obvious error detected. Arrange job should be created.');
  }

  // --- Step 5: Wait for arrange execution (up to 4 min) ---
  console.log('[5] Waiting up to 4 minutes for arranged time report...');
  const startTime = Date.now();
  const maxWait = 4 * 60 * 1000;
  let found = false;

  while (Date.now() - startTime < maxWait) {
    await page.waitForTimeout(5000);
    const text = await page.evaluate(() => document.body.innerText);
    
    const timePatterns = [
      /当前时间[：:]\s*\d{4}/,
      /\d{1,2}:\d{2}:\d{2}/,
      /汇报.*时间/,
      /现在时间/,
    ];
    
    for (const pattern of timePatterns) {
      if (pattern.test(text)) {
        console.log('[5] Time report detected!');
        found = true;
        break;
      }
    }
    
    if (found) break;
    
    const elapsed = Math.round((Date.now() - startTime) / 1000);
    if (elapsed % 10 === 0) console.log(`[5] Waiting... ${elapsed}s`);
  }

  if (found) {
    console.log('[5] SUCCESS: Arranged time report appeared!');
  } else {
    console.log('[5] Timeout: No time report within 4 minutes.');
    const fullText = await page.evaluate(() => document.body.innerText);
    console.log('[5] Page text (last 2000 chars):\n', fullText.slice(-2000));
  }

  console.log('[DONE] Test complete. Browser stays open.');
})();