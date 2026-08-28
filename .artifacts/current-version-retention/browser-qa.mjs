import { chromium } from "file:///C:/Users/monster/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
import { writeFileSync } from "node:fs";

const outputPath = "D:/work/football-ai/.artifacts/current-version-retention/browser-qa-result.json";
const browser = await chromium.launch({
  headless: true,
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
});
const target = "http://127.0.0.1:3002/matches/sportsdb-2506175";
const cases = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 },
];
const results = [];

for (const item of cases) {
  const context = await browser.newContext({ viewport: { width: item.width, height: item.height } });
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  const failedResponses = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push({ message: message.text(), location: message.location() });
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 400) failedResponses.push(`${response.status()} ${response.url()}`);
  });
  await page.goto(target, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(5000);
  const state = await page.evaluate(() => {
    const text = document.body.innerText;
    const forbidden = [
      "历史模型概率已保留",
      "历史提示词",
      "历史版本持仓",
      "早期预测已经执行",
      "历史持仓",
    ];
    return {
      title: document.title,
      emptyStateVisible: text.includes("暂无当前版本预测"),
      scoreVisible: text.includes("4") && text.includes("1"),
      simulatedPositionVisible: text.includes("本次模拟仓位"),
      forbiddenMatches: forbidden.filter((value) => text.includes(value)),
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    };
  });
  await page.screenshot({
    path: `D:/work/football-ai/.artifacts/current-version-retention/screenshots/real-madrid-${item.name}.png`,
    fullPage: true,
  });
  results.push({
    viewport: item,
    ...state,
    horizontalOverflow: state.scrollWidth > state.clientWidth + 1,
    consoleErrors,
    pageErrors,
    failedResponses,
  });
  await context.close();
}

await browser.close();
writeFileSync(outputPath, JSON.stringify(results, null, 2));
process.stdout.write(`${JSON.stringify(results)}\n`);
