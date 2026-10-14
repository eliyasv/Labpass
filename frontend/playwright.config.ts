import { defineConfig, devices } from "@playwright/test";

if (!process.env.LABPASS_E2E_URL || !process.env.LABPASS_TEST_API_CONTAINER) {
  throw new Error(
    "Set LABPASS_E2E_URL and LABPASS_TEST_API_CONTAINER for an isolated Compose test project. See README.",
  );
}
const url = new URL(process.env.LABPASS_E2E_URL);
if (url.hostname !== "127.0.0.1" || url.protocol !== "http:") {
  throw new Error("Browser tests are restricted to local loopback HTTP.");
}

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45000,
  expect: { timeout: 10000 },
  reporter: "list",
  use: { baseURL: url.origin, trace: "off", screenshot: "off", video: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
