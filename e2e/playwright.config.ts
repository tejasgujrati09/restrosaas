import { defineConfig } from "@playwright/test";
import { ports } from "./ports";

// In CI the compose stack already serves the API; locally never latch onto an
// unrelated process that happens to hold the port.
const reuseExistingServer = Boolean(process.env.CI);

const apps = (["guest", "staff", "admin"] as const).map((name) => ({
  name,
  port: ports[name],
}));

export default defineConfig({
  testDir: "./tests",
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: { trace: "retain-on-failure" },
  webServer: [
    {
      command: `cd ../apps/api && uv run uvicorn app.main:app --port ${ports.api}`,
      url: `http://localhost:${ports.api}/health`,
      reuseExistingServer,
    },
    ...apps.map(({ name, port }) => ({
      command: `pnpm --filter ${name} exec next dev --port ${port}`,
      url: `http://localhost:${port}`,
      reuseExistingServer,
      timeout: 120_000,
    })),
  ],
});
