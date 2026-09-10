// Probe the built-in Translator API surface in the current browser binary.
// Research-only diagnostic. Usage: node translator-probe.mjs <url-or-blank>
import { chromium } from "@playwright/test";

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
await page.goto("about:blank");

const probe = await page.evaluate(async () => {
  const w = window;
  const out = {
    userAgent: navigator.userAgent,
    hasWindowTranslator: typeof w.Translator !== "undefined",
    hasWindowLanguageDetector: typeof w.LanguageDetector !== "undefined",
    hasNavigatorAi: typeof w.ai !== "undefined" && w.ai !== null,
    hasNavigatorModelManager: typeof w.modelManager !== "undefined",
    navigatorKeysAi: Object.keys(w.navigator ?? {}).filter((k) =>
      /ai|translat|detect|language/i.test(k),
    ),
  };
  if (out.hasWindowTranslator) {
    try {
      out.availabilityEnZh = await w.Translator.availability({
        sourceLanguage: "en",
        targetLanguage: "zh-CN",
      });
      out.availabilityEnJa = await w.Translator.availability({
        sourceLanguage: "en",
        targetLanguage: "ja",
      });
      out.availabilityZhEn = await w.Translator.availability({
        sourceLanguage: "zh-CN",
        targetLanguage: "en",
      });
    } catch (e) {
      out.availabilityError = String(e);
    }
    try {
      const t = await w.Translator.create({
        sourceLanguage: "en",
        targetLanguage: "zh-CN",
      });
      out.createOk = true;
      out.sample = await t.translate("The model was trained on a large corpus.");
    } catch (e) {
      out.createError = `${e.name}: ${e.message}`;
    }
  }
  return out;
});
console.log(JSON.stringify(probe, null, 2));
await browser.close();
