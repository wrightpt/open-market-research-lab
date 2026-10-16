// Optional rendered checks: use an existing, trusted Playwright installation.
// All browser traffic is confined to the newly spawned loopback demo.
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdirSync} = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  mkdirSync('artifacts/browser', {recursive: true});
  const server = spawn('python3', ['-m', 'developer_portal.demo', '--port', '0']);
  let browser, passed = 0;
  const check = async (name, fn) => { await fn(); passed++; console.log(`ok ${passed} - ${name}`); };
  try {
    const [output] = await once(server.stdout, 'data');
    const origin = String(output).match(/http:\/\/127\.0\.0\.1:\d+/)?.[0];
    assert.ok(origin, 'demo prints its loopback origin');
    browser = await chromium.launch({headless: false, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, reducedMotion: 'reduce'});
    await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const textIs = (selector, text) => page.waitForFunction(([s, t]) => document.querySelector(s)?.textContent.includes(t), [selector, text]);
    const scenario = async value => { await page.selectOption('#demo-scenario', value); await textIs('#connection', 'Connected to loopback'); };
    await page.goto(`${origin}/portal/`);
    await textIs('#connection', 'Connected to loopback');
    await check('landing is explicitly synthetic and mock', async () => {
      assert.match(await page.locator('.scope-strip').innerText(), /SYNTHETIC/);
      assert.equal(await page.locator('#demo-banner').isVisible(), true);
      await page.screenshot({path: 'artifacts/browser/desktop.png', fullPage: true});
    });
    await check('catalog has ten fields and immutable split identities', async () => {
      await page.locator('nav a[href="#datasets"]').click();
      await page.locator('#dataset-fields tbody tr').first().waitFor();
      assert.equal(await page.locator('#dataset-fields tbody tr').count(), 10);
      assert.equal(await page.locator('#dataset-coverage tbody tr').count(), 2);
      await page.fill('#dataset-search', 'no such dataset');
      await textIs('#catalog-status', 'No synthetic fixtures');
      assert.equal(await page.locator('#dataset-list button').count(), 0);
    });
    await check('loading and failed catalog never report success', async () => {
      await page.fill('#dataset-search', '');
      await scenario('loading'); await textIs('#catalog-status', 'Loading');
      await textIs('#catalog-status', '1 synthetic dataset');
      await scenario('failure'); await textIs('#catalog-status', 'could not be completed');
      assert.equal(await page.locator('#dataset-detail').isVisible(), false);
    });
    await page.locator('nav a[href="#account"]').click();
    await check('pending and denied hide privileged controls', async () => {
      for (const value of ['pending', 'denied']) {
        await scenario(value); await textIs('#account-status', `Access request ${value}`);
        assert.equal(await page.locator('#key-form').isVisible(), false);
      }
    });
    await check('access request becomes pending without granting access', async () => {
      await scenario('unrequested'); await page.locator('#purpose').waitFor();
      await page.fill('#purpose', 'Review causal feature timing on synthetic observations.');
      await page.locator('#request-form button').click();
      await textIs('#account-status', 'Access request pending');
    });
    await check('key creation renders text safely and clears once-only secret', async () => {
      await scenario('approved'); await textIs('#key-status', 'No keys yet');
      await page.fill('#key-name', '<img src=x onerror=alert(1)>');
      await page.locator('#key-form button').click();
      await page.locator('#secret-dialog').waitFor();
      assert.match(await page.locator('#secret-value').innerText(), /^DEMO_NOT_A_CREDENTIAL_/);
      await page.click('#dismiss-secret');
      assert.equal(await page.locator('#secret-value').textContent(), '');
      assert.equal(await page.locator('#key-list img').count(), 0);
      await textIs('#key-list', '<img src=x onerror=alert(1)>');
      assert.deepEqual(await page.evaluate(() => [localStorage.length, sessionStorage.length]), [0, 0]);
    });
    await check('rotation revokes predecessor and navigation clears replacement', async () => {
      await page.getByRole('button', {name: 'Rotate', exact: true}).click();
      await page.click('#confirm-accept'); await page.locator('#secret-dialog').waitFor();
      await page.evaluate(() => { location.hash = '#api'; });
      await page.locator('#secret-dialog').waitFor({state: 'hidden'});
      assert.equal(await page.locator('#secret-value').textContent(), '');
      await page.locator('nav a[href="#account"]').click();
      await textIs('#key-list', 'REVOKED');
      await page.getByRole('button', {name: 'Revoke', exact: true}).click();
      await page.click('#confirm-accept');
      await page.waitForFunction(() => document.querySelectorAll('#key-list .revoked').length === 2);
    });
    await check('logout returns anonymous and no browser errors occur', async () => {
      await page.click('#logout'); await page.locator('#github-login').waitFor();
      assert.equal(await page.locator('#demo-scenario').inputValue(), 'anonymous');
      assert.deepEqual(errors, []);
    });
    await check('mobile and tablet pages fit and controls have labels', async () => {
      for (const width of [375, 768]) {
        await page.setViewportSize({width, height: 900});
        for (const view of ['overview', 'datasets', 'api', 'account', 'challenge']) {
          await page.locator(`nav a[href="#${view}"]`).click();
          await page.locator(`#${view}`).waitFor({state: 'visible'});
          assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${view} fits ${width}px`);
        }
      }
      await page.setViewportSize({width: 375, height: 900});
      await page.locator('nav a[href="#overview"]').click();
      await page.locator('#overview').waitFor({state: 'visible'});
      await page.screenshot({path: 'artifacts/browser/mobile.png', fullPage: true});
      assert.equal(await page.locator('input:not([id]), textarea:not([id]), select:not([id])').count(), 0);
    });
    console.log(`${passed} browser checks passed`);
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM'); await once(server, 'exit');
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
