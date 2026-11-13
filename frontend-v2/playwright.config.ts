import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: true,
  use: { baseURL: 'http://127.0.0.1:4178', channel: 'chrome' },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 1100 } } },
    { name: 'mobile-390', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: 'npm run build && npm run preview -- --port 4178',
    url: 'http://127.0.0.1:4178',
    // Synthetic course ID used only for this browser test build.
    env: { VITE_COURSE_KB_ID: '33333333-3333-4333-8333-333333333333' },
    reuseExistingServer: false,
  },
})
