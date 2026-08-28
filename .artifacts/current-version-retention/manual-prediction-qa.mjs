import { chromium } from "file:///C:/Users/monster/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";
import { writeFileSync } from "node:fs";

const outputDir = "D:/work/football-ai/.artifacts/current-version-retention";
const apiBase = "http://127.0.0.1:8001";
const webBase = "http://127.0.0.1:3002";
const source = await fetch(`${apiBase}/api/fixtures/sportsdb-2506175`).then((response) => response.json());
const browser = await chromium.launch({
  headless: true,
  executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
});
const results = {};

{
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  await page.goto(`${webBase}/matches/sportsdb-2506175`, { waitUntil: "domcontentloaded" });
  await page.getByText("比赛已结束，不能重新预测").waitFor({ state: "visible" });
  results.finished = {
    blockedMessageVisible: await page.getByText("比赛已结束，不能重新预测").isVisible(),
    manualButtonCount: await page.getByRole("button", { name: /手动生成预测|重新生成/ }).count(),
    horizontalOverflow: await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1),
    consoleErrors: errors,
  };
  await page.screenshot({ path: `${outputDir}/screenshots/manual-prediction-finished.png`, fullPage: true });
  await page.close();
}

{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  const scheduled = structuredClone(source);
  scheduled.fixture = {
    ...scheduled.fixture,
    id: "test-scheduled",
    status: "scheduled",
    provider_status: "NS",
    score: null,
  };
  scheduled.prediction = null;
  scheduled.predictions = { deepseek: null, chatgpt: null };
  scheduled.bet = null;
  scheduled.bets = { deepseek: null, chatgpt: null };
  await page.route(`${apiBase}/api/fixtures/test-scheduled`, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(scheduled),
  }));
  await page.route(`${webBase}/api/admin/predict`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ detail: "测试：赛前证据不足" }),
    });
  });
  await page.goto(`${webBase}/matches/test-scheduled`, { waitUntil: "domcontentloaded" });
  const button = page.getByRole("button", { name: "手动生成预测" });
  await button.waitFor({ state: "visible" });
  const clickPromise = button.click();
  await page.getByRole("button", { name: "计算中" }).waitFor({ state: "visible" });
  const loadingDisabled = await page.getByRole("button", { name: "计算中" }).isDisabled();
  await clickPromise;
  await page.getByText("测试：赛前证据不足").waitFor({ state: "visible" });
  results.scheduled = {
    initialButtonVisible: true,
    loadingDisabled,
    errorText: await page.getByText("测试：赛前证据不足").innerText(),
    horizontalOverflow: await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1),
    consoleErrors: errors,
  };
  await page.screenshot({ path: `${outputDir}/screenshots/manual-prediction-scheduled-mobile.png`, fullPage: true });
  await context.close();
}

await browser.close();
writeFileSync(`${outputDir}/manual-prediction-qa-result.json`, JSON.stringify(results, null, 2));
process.stdout.write(`${JSON.stringify(results)}\n`);
