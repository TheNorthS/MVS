import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests",
  workers: 1,
  use: {
    baseURL: process.env.MVS_UI_TEST_URL ?? "http://127.0.0.1:8123",
    channel: process.env.MVS_BROWSER_CHANNEL,
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
  },
  reporter: "list",
  timeout: 60000,
});
