
import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto('http://localhost:6174/', { waitUntil: 'networkidle', timeout: 15000 });
  const title = await page.title();
  console.log('Title:', title);
  const html = await page.content();
  console.log('Body preview:', html.substring(0, 3000));
  await page.screenshot({ path: 'E:/e2e for writer/frontend_screenshot.png', fullPage: true });
  console.log('Screenshot saved');
  await browser.close();
})();
