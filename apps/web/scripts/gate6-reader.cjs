// Gate 6 补充：Reader 工具栏三模式验收
const { chromium } = require('@playwright/test');
const fs = require('fs');
const OUT = 'test-results/gate6';
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
  await page.getByText('文章 alpha').first().click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/04-reader-after-select.png` });

  const toolbar = {
    hasOriginal: await page.getByRole('button', { name: '原文', exact: true }).count(),
    hasBilingual: await page.getByRole('button', { name: '双语', exact: true }).count(),
    hasTranslated: await page.getByRole('button', { name: '仅译文', exact: true }).count(),
    oldInBodyToggle: await page.getByRole('group', { name: '文章语言视图' }).count(),
    aaPresent: await page.getByRole('button', { name: /阅读样式|Aa/ }).count(),
  };
  fs.writeFileSync(`${OUT}/reader-toolbar.json`, JSON.stringify(toolbar, null, 2));

  // 切双语：未配置 AI 时应看到诚实状态行（不遮原文）；截图
  await page.getByRole('button', { name: '双语', exact: true }).first().click();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${OUT}/05-reader-bilingual.png` });
  const bilingualState = {
    statusBarText: (await page.locator('[role="status"]').filter({ hasText: /翻译|已译|失败/ }).allTextContents()).slice(0, 2),
  };
  // 切仅译文
  await page.getByRole('button', { name: '仅译文', exact: true }).first().click();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/05b-reader-translated.png` });
  fs.writeFileSync(`${OUT}/reader-bilingual.json`, JSON.stringify(bilingualState, null, 2));

  // 移动端工具栏（390px：应为紧凑菜单形态）
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
  await mobile.getByText('文章 alpha').first().click();
  await mobile.waitForTimeout(1500);
  await mobile.screenshot({ path: `${OUT}/09-mobile-reader.png` });
  const mobileToolbar = {
    desktopSegmented: await mobile.getByRole('button', { name: '双语', exact: true }).count(),
    menuTrigger: await mobile.getByRole('button', { name: /语言视图/ }).count(),
  };
  fs.writeFileSync(`${OUT}/mobile-toolbar.json`, JSON.stringify(mobileToolbar, null, 2));

  console.log('reader toolbar:', JSON.stringify(toolbar));
  console.log('mobile:', JSON.stringify(mobileToolbar));
  await browser.close();
})();
