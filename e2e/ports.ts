const port = (name: string, fallback: number) => Number(process.env[name] ?? fallback);

export const ports = {
  api: port("E2E_API_PORT", 8000),
  guest: port("E2E_GUEST_PORT", 3000),
  staff: port("E2E_STAFF_PORT", 3001),
  admin: port("E2E_ADMIN_PORT", 3002),
};
