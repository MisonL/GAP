// @ts-check
import { chromium } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const STORAGE_PATH = path.resolve(process.cwd(), 'playwright/.auth/user.json');
const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:5173';

/**
 * Global setup for Playwright tests.
 *
 * It ensures that `playwright/.auth/user.json` exists before any test runs,
 * so that `use.storageState` can always load it.
 *
 * If `GAP_E2E_PASSWORD` is provided, it will attempt a basic UI login
 * on the `/login` page and store the resulting authenticated state.
 * If login fails or the env var is not set, it will still write an
 * (anonymous) storage state file so tests at least start.
 *
 * @type {import('@playwright/test').GlobalSetup}
 */
export default async function globalSetup() {
  // Ensure auth directory exists
  fs.mkdirSync(path.dirname(STORAGE_PATH), { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();

  const password = process.env.GAP_E2E_PASSWORD;

  if (password) {
    try {
      await page.goto(`${BASE_URL}/login`);

      // Try common selectors for password-only login; failures are non-fatal.
      try {
        await page.fill('input[type="password"]', password);
      } catch {
        // ignore
      }

      // Try a few common login button texts; ignore failures and continue.
      const candidateButtons = ['button:has-text("登录")', 'button:has-text("Login")'];
      for (const selector of candidateButtons) {
        try {
          if (await page.locator(selector).first().isVisible()) {
            await page.click(selector);
            break;
          }
        } catch {
          // ignore and try next selector
        }
      }

      // Give the app a moment to process login / redirects.
      await page.waitForTimeout(2000);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('[global-setup] Login attempt failed, continuing with anonymous storage state:', e);
    }
  }

  await context.storageState({ path: STORAGE_PATH });
  await browser.close();
}
