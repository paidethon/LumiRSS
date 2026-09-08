// Gate 6 移动端 + 深色 快速验收
const { chromium } = require('@playwright/test');
const fs = require('fs');
const OUT = 'test-results/gate6';

(async () => {
  const browser = await chromium.launch();

  // 移动端 Reader 工具栏（紧凑菜单形态）
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
  await mobile.getByText('文章 alpha').filter({ visible: true }).first().click();
  await mobile.waitForTimeout(1500);
  await mobile.screenshot({ path: `${OUT}/09-mobile-reader.png` });
  const mt = {
    desktopSegmentedVisible: await mobile.getByRole('button', { name: '双语', exact: true }).isVisible().catch(() => false),
    menuTrigger: await mobile.getByRole('button', { name: /语言视图/ }).count(),
    horizontalOverflow: await mobile.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth),
  };
  fs.writeFileSync(`${OUT}/mobile-toolbar.json`, JSON.stringify(mt, null, 2));
  // 打开语言菜单
  const trigger = mobile.getByRole('button', { name: /语言视图/ }).first();
  if (await trigger.count()) {
    await trigger.click();
    await mobile.waitForTimeout(500);
    await mobile.screenshot({ path: `${OUT}/10-mobile-language-menu.png` });
  }
  await mobile.close();

  // 深色：设置阅读页 + Reader 双语
  const dark = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark' });
  await dark.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
  await dark.getByText('文章 alpha').filter({ visible: true }).first().click();
  await dark.waitForTimeout(1200);
  await dark.screenshot({ path: `${OUT}/11-dark-reader.png` });
  await dark.close();

  console.log('mobile:', JSON.stringify(mt));
  await browser.close();
})();
