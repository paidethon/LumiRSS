// Gate 11 补充：1920 视口截图 + 全程 console error 采集
const { chromium } = require('@playwright/test');
const fs = require('fs');
const OUT = 'test-results/gate6';
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch();
  const consoleErrors = [];
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 2000));
  });
  page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${String(err).slice(0, 2000)}`));

  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
  await page.screenshot({ path: `${OUT}/12-desktop-1920-home.png` });

  // Reader
  await page.getByText('文章 alpha').filter({ visible: true }).first().click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/13-desktop-1920-reader.png` });

  // 设置各分类（1920）
  await page.getByRole('button', { name: '打开设置' }).first().click();
  await page.waitForTimeout(500);
  for (const cat of ['通用', '外观', '阅读', '翻译', 'AI', 'RSSHub', '数据控制']) {
    const btn = page.getByRole('button', { name: cat }).filter({ visible: true }).first();
    try {
      await btn.click({ timeout: 4000 });
      await page.waitForTimeout(450);
      await page.screenshot({ path: `${OUT}/14-1920-${cat}.png` });
    } catch (e) {
      consoleErrors.push(`category ${cat}: ${e.message.split('\n')[0]}`);
    }
  }
  await page.keyboard.press('Escape');

  // 双语切换一次（1920 Reader，AI 未配置的诚实态）
  await page.getByRole('button', { name: '双语', exact: true }).first().click();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${OUT}/15-desktop-1920-bilingual.png` });

  fs.writeFileSync(`${OUT}/console-errors-1920.json`, JSON.stringify(consoleErrors, null, 2));
  console.log('console errors:', JSON.stringify(consoleErrors));
  await browser.close();
})();
