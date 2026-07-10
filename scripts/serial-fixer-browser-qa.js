const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROME });
  const context = await browser.newContext({
    storageState: '.mcp-auth/storage-state.json',
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  const results = {};

  async function load(path) {
    const response = await page.goto('https://sprinklers.savagepace.com' + path, { waitUntil: 'domcontentloaded', timeout: 30000 });
    if (!response || response.status() !== 200) throw new Error(path + ' returned ' + (response && response.status()));
  }

  await load('/audit');
  await page.locator('#t tbody tr').first().waitFor({ timeout: 10000 });
  results.audit = {
    overflow: await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
    rows: await page.locator('#t tbody tr').count(),
    disabled: await page.locator('.status.disabled').count(),
  };

  await page.route('**/api/cam/regression/list?flag=1', route => route.fulfill({ status: 500, body: 'failure' }));
  await load('/cam/regression');
  await page.locator('[role=alert]').waitFor({ timeout: 10000 });
  results.regressionError = await page.locator('[role=alert]').textContent();
  await page.unroute('**/api/cam/regression/list?flag=1');

  await page.route('**/api/cam/quality', route => route.fulfill({ status: 500, body: 'failure' }));
  await load('/cam/quality');
  await page.locator('#banner[role=alert]').waitFor({ timeout: 10000 });
  results.qualityError = await page.locator('#banner[role=alert]').textContent();
  await page.unroute('**/api/cam/quality');

  await load('/cam/test-audit');
  await page.locator('#controls').waitFor({ state: 'visible', timeout: 35000 });
  results.testAudit = {
    main: await page.locator('main').count(),
    status: await page.locator('#sub[aria-live]').count(),
    emptyAlt: await page.locator('img[src*="/api/cam/training/img/"][alt=""]').count(),
    images: await page.locator('img[src*="/api/cam/training/img/"]').count(),
    unnamedActions: await page.locator('#grid button:not([aria-label])').count(),
  };

  await load('/cam/cnn-report');
  results.cnn = {
    overflow: await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
    main: await page.locator('main').count(),
    blankHeaders: await page.locator('th:empty').count(),
  };

  await page.route('**/api/cam/latest?**', route => route.fulfill({ status: 502, body: 'failure' }));
  await load('/cam/focus');
  results.focus = {
    baselineDisabled: await page.locator('#baselineBtn').isDisabled(),
    refreshDisabled: await page.locator('#refreshBtn').isDisabled(),
  };

  console.log(JSON.stringify(results, null, 2));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
