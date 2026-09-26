/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // LAN=1 scripts/dev.sh: lets a phone on the same Wi-Fi load dev assets.
  allowedDevOrigins: process.env.LAN_HOST ? process.env.LAN_HOST.split(",") : [],
  // Workspace packages ship TypeScript source.
  transpilePackages: ["@restosaas/ui", "api-client"],
};
export default nextConfig;
