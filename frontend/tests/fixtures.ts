import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { test as base, expect, type Page } from "@playwright/test";
import type { Auth, Workshop } from "../src/api";

export const origin = new URL(process.env.LABPASS_E2E_URL!).origin;
export const credentials = () => ({
  email: `browser-${randomUUID()}@example.test`,
  password: randomUUID(),
});

type Fixtures = { workshop: Workshop; admin: ReturnType<typeof credentials> };
export const test = base.extend<Fixtures>({
  admin: async ({}, use) => {
    const account = credentials();
    const container = process.env.LABPASS_TEST_API_CONTAINER!;
    const project = execFileSync(
      "docker",
      [
        "inspect",
        "--format",
        '{{ index .Config.Labels "com.docker.compose.project" }}',
        container,
      ],
      { encoding: "utf8" },
    ).trim();
    if (!project.startsWith("labpass-m3-verification")) {
      throw new Error(
        "Admin fixtures must use a Compose project named labpass-m3-verification (optional suffix allowed).",
      );
    }
    // Password is passed only through stdin, never command arguments or environment.
    execFileSync(
      "docker",
      [
        "exec",
        "-i",
        container,
        "python",
        "-c",
        [
          "import json, sys",
          "from labpass.config import Settings",
          "from labpass.db import make_engine, make_sessions",
          "from labpass.auth import hash_password",
          "from labpass.create_admin import provision_admin",
          "body = json.load(sys.stdin)",
          "engine = make_engine(Settings.from_env().database_url)",
          "sessions = make_sessions(engine)",
          "with sessions.begin() as session:",
          '    provision_admin(session, body["email"], hash_password(body["password"]))',
          "engine.dispose()",
        ].join("\n"),
      ],
      { input: JSON.stringify(account), stdio: ["pipe", "pipe", "pipe"] },
    );
    await use(account);
  },
  workshop: async ({ playwright, admin }, use) => {
    const client = await playwright.request.newContext({
      baseURL: origin,
      extraHTTPHeaders: { Origin: origin },
    });
    const login = await client.post("/api/auth/login", { data: admin });
    expect(login.ok()).toBeTruthy();
    const auth: Auth = await login.json();
    const result = await client.post("/api/admin/workshops", {
      headers: { "X-CSRF-Token": auth.csrf_token },
      data: {
        title: `Browser workshop ${randomUUID().slice(0, 8)}`,
        capacity: 1,
      },
    });
    expect(result.status()).toBe(201);
    const row: Workshop = await result.json();
    await client.post("/api/auth/logout", {
      headers: { "X-CSRF-Token": auth.csrf_token },
    });
    await client.dispose();
    await use(row);
  },
});

export async function signIn(
  page: Page,
  account: ReturnType<typeof credentials>,
) {
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByLabel("Email address", { exact: true }).fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in →", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toBeEnabled();
}

export async function registerAndSignIn(page: Page) {
  const account = credentials();
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await page.getByLabel("Email address", { exact: true }).fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page
    .getByRole("button", { name: "Create account →", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Account created.");
  await signIn(page, account);
  return account;
}

export { expect };
