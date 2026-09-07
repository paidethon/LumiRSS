// Gate 6 浏览器视觉验收（对 dev 栈 5173；截图落 gitignored test-results/）
const { chromium } = require('@playwright/test');

const BASE = 'http://127.0.0.1:5173';
const OUT = 'test-results/gate6';
const fs = require('fs');
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch();
  const results = [];
  const shot = async (page, name) => {
    const path = `${OUT}/${name}.png`;
    await page.screenshot({ path, fullPage: false });
    results.push({ name, path });
  };

  // ---- 桌面 1440 ----
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await shot(page, '01-desktop-home');

  // 打开设置（侧栏或顶栏的设置按钮）
  const settingsButton = page.getByRole('button', { name: '设置' }).first();
  await settingsButton.click();
  await page.waitForTimeout(600);
  await shot(page, '02-settings-general');

  // 遍历分类检查重复“开关”文字
  const categories = ['通用', '外观', '阅读', '翻译', 'AI', 'RSSHub', '数据控制'];
  const findings = {};
  for (const cat of categories) {
    const btn = page.getByRole('button', { name: cat }).first();
    try {
      await btn.click({ timeout: 5000 });
      await page.waitForTimeout(500);
      // 收集所有含“开关”后缀的可见文本
      const dupText = await page.evaluate(() => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const hits = [];
        while (walker.nextNode()) {
          const t = walker.currentNode.textContent.trim();
          if (t.endsWith('开关')) hits.push(t);
        }
        return hits;
      });
      findings[cat] = dupText;
      await shot(page, `03-settings-${cat}`);
    } catch (e) {
      findings[cat] = ['<category not clickable: ' + e.message.split('\n')[0] + '>'];
    }
  }
  fs.writeFileSync(`${OUT}/switch-duplicate-text.json`, JSON.stringify(findings, null, 2));

  // Reader：返回首页选一篇文章
  await page.keyboard.press('Escape');
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const entry = page.locator('[data-entry-ref], article, .entry-row, li').filter({ hasText: /.+/ }).first();
  await page.waitForTimeout(500);
  // 点击第一条文章行（结构未知，取条目列表第一个可点击元素）
  const firstEntry = page.getByRole('button').nth(0);
  try {
    const listItems = page.locator('main li, [class*=entry] li, [class*=list] > *');
    await listItems.first().click({ timeout: 4000 });
  } catch (e) {
    await firstEntry.click().catch(() => {});
  }
  await page.waitForTimeout(1200);
  await shot(page, '04-reader-after-select');
  const toolbar = {
    hasOriginal: await page.getByRole('button', { name: '原文', exact: true }).count(),
    hasBilingual: await page.getByRole('button', { name: '双语', exact: true }).count(),
    hasTranslated: await page.getByRole('button', { name: /仅译文|译文/ }).count(),
    oldInBodyToggle: await page.getByRole('group', { name: '文章语言视图' }).count(),
  };
  fs.writeFileSync(`${OUT}/reader-toolbar.json`, JSON.stringify(toolbar, null, 2));
  // 切双语看行为（若可点）
  const bilingual = page.getByRole('button', { name: '双语', exact: true }).first();
  if (await bilingual.count()) {
    await bilingual.click();
    await page.waitForTimeout(2000);
    await shot(page, '05-reader-bilingual');
  }

  await page.close();

  // ---- 桌面深色 ----
  const dark = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark' });
  await dark.goto(BASE, { waitUntil: 'networkidle' });
  await shot(dark, '06-desktop-dark');
  await dark.close();

  // ---- 移动 390 ----
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto(BASE, { waitUntil: 'networkidle' });
  await shot(mobile, '07-mobile-home');
  const mSettings = mobile.getByRole('button', { name: '设置' }).first();
  if (await mSettings.count()) {
    await mSettings.click();
    await mobile.waitForTimeout(600);
    await shot(mobile, '08-mobile-settings');
  }
  await mobile.close();

  fs.writeFileSync(`${OUT}/summary.json`, JSON.stringify(results, null, 2));
  console.log('DONE', results.length, 'screenshots');
  await browser.close();
})();
