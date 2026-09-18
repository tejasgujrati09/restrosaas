import { defineConfig } from "@playwright/test";
import { ports } from "./ports";

// In CI the compose stack already serves the API; locally never latch onto an
// unrelated process that happens to hold the port.
const reuseExistingServer = Boolean(process.env.CI);

const apiUrl = `http://localhost:${ports.api}`;
const appNames = ["guest", "staff", "admin"] as const;

export default defineConfig({
  testDir: "./tests",
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: { trace: "retain-on-failure" },
  webServer: [
    {
      command: `cd ../apps/api && uv run uvicorn app.main:app --port ${ports.api}`,
      url: `${apiUrl}/health`,
      reuseExistingServer,
      env: {
        // Browsers cannot read the API console, so tests use a fixed code (refused in production).
        OTP_DEV_FIXED_CODE: "123456",
        CORS_ORIGINS: JSON.stringify(appNames.map((n) => `http://localhost:${ports[n]}`)),
        STAFF_BASE_URL: `http://localhost:${ports.staff}`,
        PUBLIC_BASE_URL: `http://localhost:${ports.guest}`,
      },
    },
    ...appNames.map((name) => ({
      command: `pnpm --filter ${name} exec next dev --port ${ports[name]}`,
      url: `http://localhost:${ports[name]}`,
      reuseExistingServer,
      timeout: 120_000,
      env: { NEXT_PUBLIC_API_URL: apiUrl },
    })),
  ],
});
