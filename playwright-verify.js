const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();

  console.log('导航到 http://127.0.0.1:5173');
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });

  // 等待页面主要元素出现
  await page.waitForTimeout(2000);

  // 截图 1：页面初始状态
  await page.screenshot({ path: 'E:\\LamTools\\playwright-verify-01-initial.png' });
  console.log('截图已保存: playwright-verify-01-initial.png');

  // 找到 composer textarea（placeholder 包含"发送任务"）
  const textarea = await page.$('textarea[placeholder*="发送任务"]');
  if (!textarea) {
    console.error('未找到 composer textarea');
    await browser.close();
    process.exit(1);
  }

  // 点击 textarea
  await textarea.click();
  console.log('已点击输入框');

  // 输入指令
  const testMessage = '你好，Core Agent！这是一个 Playwright 交互验证。';
  await textarea.fill(testMessage);
  console.log('已输入测试消息:', testMessage);

  // 截图 2：输入后状态
  await page.screenshot({ path: 'E:\\LamTools\\playwright-verify-02-input.png' });
  console.log('截图已保存: playwright-verify-02-input.png');

  // 尝试触发发送（Enter）
  await textarea.press('Enter');
  console.log('已按 Enter 键');

  await page.waitForTimeout(1500);

  // 截图 3：发送后状态
  await page.screenshot({ path: 'E:\\LamTools\\playwright-verify-03-sent.png' });
  console.log('截图已保存: playwright-verify-03-sent.png');

  console.log('交互验证完成。');
  await browser.close();
})().catch(err => {
  console.error('验证失败:', err);
  process.exit(1);
});
