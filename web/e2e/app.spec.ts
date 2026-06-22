import { expect, test } from '@playwright/test'

test('opens the local story dashboard', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('NovelLoom', { exact: true })).toBeVisible()
  await expect(page.getByText('本地模式 · SQLite')).toBeVisible()
})
