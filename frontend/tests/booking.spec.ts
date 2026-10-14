import { test, expect, origin, registerAndSignIn, signIn } from "./fixtures";

test("register, reserve, restore session, cancel, rebook and sign out", async ({
  page,
  workshop,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await registerAndSignIn(page);
  const card = page.getByRole("article", { name: workshop.title, exact: true });
  await card.getByRole("button", { name: "Reserve a seat" }).click();
  await expect(
    card.getByRole("button", { name: "Seat reserved" }),
  ).toBeDisabled();
  await expect(card).toContainText("0 of 1 seats available");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "My bookings", exact: true }).click();
  const history = page.getByRole("article", {
    name: `Booking for ${workshop.title}`,
    exact: true,
  });
  await history
    .getByRole("button", { name: "Cancel booking", exact: true })
    .click();
  await history
    .getByRole("button", { name: "Keep my seat", exact: true })
    .click();
  await expect(history.getByText("Reserved", { exact: true })).toBeVisible();
  await history
    .getByRole("button", { name: "Cancel booking", exact: true })
    .click();
  await history
    .getByRole("button", { name: "Confirm cancellation", exact: true })
    .click();
  await expect(history.getByText("Cancelled", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Workshops", exact: true }).click();
  await expect(card).toContainText("1 of 1 seats available");
  await card.getByRole("button", { name: "Reserve a seat" }).click();
  await expect(
    card.getByRole("button", { name: "Seat reserved" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Sign in →", exact: true }),
  ).toBeEnabled();
  const response = await page.context().request.get(`${origin}/api/auth/me`);
  expect(response.status()).toBe(401);
  expect(errors).toEqual([]);
});

test("lost committed booking response retries the same key across reload", async ({
  page,
  workshop,
}) => {
  await registerAndSignIn(page);
  const keys: string[] = [];
  await page.route("**/api/bookings", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    keys.push(route.request().headers()["idempotency-key"]);
    const response = await route.fetch(); // Actual PostgreSQL commit happens first.
    expect(response.status()).toBe(200);
    await route.abort("failed"); // Simulate loss of the committed response.
  });
  await page
    .getByRole("article", { name: workshop.title })
    .getByRole("button", { name: "Reserve a seat" })
    .click();
  await expect(page.getByRole("alert")).toContainText("could not confirm");
  await page.unroute("**/api/bookings");
  await page.reload();
  // Session storage retains the pending key. History detects the successful booking.
  await expect(
    page
      .getByRole("article", { name: workshop.title })
      .getByRole("button", { name: "Seat reserved" }),
  ).toBeDisabled();
  const pending = await page.evaluate(() =>
    Object.entries(sessionStorage).filter(([key]) =>
      key.startsWith("labpass:booking:"),
    ),
  );
  expect(pending).toHaveLength(1);
  expect(pending[0][1]).toBe(keys[0]);
  const me = await (
    await page.context().request.get(`${origin}/api/auth/me`)
  ).json();
  const retry = await page.context().request.post(`${origin}/api/bookings`, {
    headers: {
      Origin: origin,
      "X-CSRF-Token": me.csrf_token,
      "Idempotency-Key": pending[0][1],
    },
    data: { workshop_id: workshop.id },
  });
  expect(retry.status()).toBe(200);
  const history = await (
    await page.context().request.get(`${origin}/api/bookings`)
  ).json();
  expect(
    history.filter(
      (row: { workshop_id: string }) => row.workshop_id === workshop.id,
    ),
  ).toHaveLength(1);
  const current = await (
    await page.context().request.get(`${origin}/api/workshops/${workshop.id}`)
  ).json();
  expect(current.reserved).toBe(1);
  // Cancellation must retire the pending key even when the initial response was lost.
  await page.getByRole("button", { name: "My bookings", exact: true }).click();
  const row = page.getByRole("article", {
    name: `Booking for ${workshop.title}`,
  });
  await row
    .getByRole("button", { name: "Cancel booking", exact: true })
    .click();
  await row
    .getByRole("button", { name: "Confirm cancellation", exact: true })
    .click();
  await expect(row.getByText("Cancelled", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Workshops", exact: true }).click();
  const nextRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith("/api/bookings"),
  );
  await page
    .getByRole("article", { name: workshop.title })
    .getByRole("button", { name: "Reserve a seat" })
    .click();
  expect((await nextRequest).headers()["idempotency-key"]).not.toBe(keys[0]);
  await expect(
    page
      .getByRole("article", { name: workshop.title })
      .getByRole("button", { name: "Seat reserved" }),
  ).toBeDisabled();
});

test("manual UI retry after a lost response keeps the original key", async ({
  page,
  workshop,
}) => {
  await registerAndSignIn(page);
  const keys: string[] = [];
  await page.route("**/api/bookings", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    keys.push(route.request().headers()["idempotency-key"]);
    const response = await route.fetch();
    if (keys.length === 1) await route.abort("failed");
    else await route.fulfill({ response });
  });
  const card = page.getByRole("article", { name: workshop.title });
  await card.getByRole("button", { name: "Reserve a seat" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await card.getByRole("button", { name: "Retry reservation" }).click();
  await expect(
    card.getByRole("button", { name: "Seat reserved" }),
  ).toBeDisabled();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  expect(
    await page.evaluate(() =>
      Object.keys(sessionStorage).filter((key) =>
        key.startsWith("labpass:booking:"),
      ),
    ),
  ).toHaveLength(0);
});

test("pending retry remains available when a full workshop is absent from the visible history page", async ({
  page,
  workshop,
}) => {
  await registerAndSignIn(page);
  let key = "";
  await page.route("**/api/bookings", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    key = route.request().headers()["idempotency-key"];
    const committed = await route.fetch();
    expect(committed.status()).toBe(200);
    await route.abort("failed");
  });
  await page
    .getByRole("article", { name: workshop.title })
    .getByRole("button", { name: "Reserve a seat" })
    .click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.unroute("**/api/bookings");
  // Fault injection affects only the displayed history page; the real booking stays committed.
  await page.route("**/api/bookings?*", async (route) => {
    const response = await route.fetch();
    const rows = await response.json();
    await route.fulfill({
      response,
      json: rows.filter(
        (row: { workshop_id: string }) => row.workshop_id !== workshop.id,
      ),
    });
  });
  await page.reload();
  const card = page.getByRole("article", { name: workshop.title });
  await expect(card).toContainText("0 of 1 seats available");
  await expect(
    card.getByRole("button", { name: "Retry reservation" }),
  ).toBeEnabled();
  const retried = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith("/api/bookings"),
  );
  await page.unroute("**/api/bookings?*");
  await card.getByRole("button", { name: "Retry reservation" }).click();
  expect((await retried).headers()["idempotency-key"]).toBe(key);
  await expect(
    card.getByRole("button", { name: "Seat reserved" }),
  ).toBeDisabled();
});

test("admin creation and capacity changes, with server enforcement below reservations", async ({
  page,
  admin,
  workshop,
}) => {
  await registerAndSignIn(page);
  await expect(
    page.getByRole("button", { name: "Manage workshops" }),
  ).toHaveCount(0);
  await page
    .getByRole("article", { name: workshop.title })
    .getByRole("button", { name: "Reserve a seat" })
    .click();
  await expect(
    page
      .getByRole("article", { name: workshop.title })
      .getByRole("button", { name: "Seat reserved" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await signIn(page, admin);
  await page
    .getByRole("button", { name: "Manage workshops", exact: true })
    .click();
  const form = page.getByRole("form", {
    name: `Capacity for ${workshop.title}`,
  });
  await form.getByRole("spinbutton").fill("0");
  await form.getByRole("button", { name: "Save capacity" }).click();
  await expect(page.getByRole("alert")).toContainText("cannot be lower");
  await form.getByRole("spinbutton").fill("3");
  await form.getByRole("button", { name: "Save capacity" }).click();
  await expect(form).toContainText("1 reserved · 2 available");
  await page
    .getByLabel("Workshop title", { exact: true })
    .fill("A new browser-created workshop");
  await page.getByLabel("Capacity", { exact: true }).fill("5");
  await page
    .getByRole("button", { name: "Create workshop", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Workshop created.");
});

test("real browser cookies, CSRF, Origin, and regular-user authorization", async ({
  page,
  workshop,
}) => {
  await registerAndSignIn(page);
  const client = page.context().request;
  const me = await (await client.get(`${origin}/api/auth/me`)).json();
  const cookies = await page.context().cookies();
  const session = cookies.find((cookie) => cookie.name === "labpass_session");
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Lax");
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    "labpass_session",
  );
  expect(await page.evaluate(() => JSON.stringify(localStorage))).toBe("{}");
  const blocked = await client.post(`${origin}/api/bookings`, {
    headers: { Origin: origin, "Idempotency-Key": crypto.randomUUID() },
    data: { workshop_id: workshop.id },
  });
  expect(blocked.status()).toBe(403);
  const foreign = await client.post(`${origin}/api/bookings`, {
    headers: {
      Origin: "http://evil.example",
      "X-CSRF-Token": me.csrf_token,
      "Idempotency-Key": crypto.randomUUID(),
    },
    data: { workshop_id: workshop.id },
  });
  expect(foreign.status()).toBe(403);
  const admin = await client.post(`${origin}/api/admin/workshops`, {
    headers: { Origin: origin, "X-CSRF-Token": me.csrf_token },
    data: { title: "Should be denied", capacity: 1 },
  });
  expect(admin.status()).toBe(403);
});

test("mobile layout and workshop search", async ({ page, workshop }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("article", { name: workshop.title }),
  ).toBeVisible();
  await page.getByRole("searchbox").fill("no-such-workshop-unique");
  await expect(page.getByText("No matches on this page")).toBeVisible();
  await page.getByRole("searchbox").fill(workshop.title);
  await expect(
    page.getByRole("article", { name: workshop.title }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("untrusted workshop titles render as text", async ({ page, admin }) => {
  const client = page.context().request;
  const signedIn = await client.post(`${origin}/api/auth/login`, {
    headers: { Origin: origin },
    data: admin,
  });
  const me = await signedIn.json();
  const title = "<img src=x onerror=alert(1)> Cloud workshop";
  const response = await client.post(`${origin}/api/admin/workshops`, {
    headers: { Origin: origin, "X-CSRF-Token": me.csrf_token },
    data: { title, capacity: 0 },
  });
  expect(response.status()).toBe(201);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible();
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});
