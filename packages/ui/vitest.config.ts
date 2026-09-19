import { defineConfig } from "vitest/config";

// Next needs `"jsx": "preserve"` in tsconfig; tests need the JSX transformed.
export default defineConfig({ oxc: { jsx: { runtime: "automatic" } } });
