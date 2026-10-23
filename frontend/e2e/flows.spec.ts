import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const PW = "FedCardio!2026";
const SHOTS = process.env.E2E_SCREENSHOTS ?? "../docs/screenshots";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PW);
  await page.getByRole("button", { name: /^Sign in/ }).click();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
}

async function a11y(page: Page, name: string) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const serious = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const describe = (v: (typeof serious)[number]) =>
    `${name}: ${v.id} -> ` + v.nodes.map((n) => `${n.target.join(" ")} [${n.failureSummary?.split("\n")[1]?.trim() ?? ""}]`).join(" | ");
  expect(serious.map(describe)).toEqual([]);
}

async function shot(page: Page, name: string) {
  await page.waitForTimeout(900); // let entrance animations settle
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });
}

test("login page is accessible and rejects bad credentials", async ({ page }) => {
  await page.goto("/login");
  await a11y(page, "login");
  await shot(page, "01-login");
  await page.getByLabel("Work email").fill("dr.cleveland@fedcardio.dev");
  await page.getByLabel("Password", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: /^Sign in/ }).click();
  await expect(page.getByText("invalid email or password")).toBeVisible();
});

test("clinician assesses a patient's risk with explanation and gives feedback", async ({ page }) => {
  await login(page, "dr.cleveland@fedcardio.dev");
  await expect(page).toHaveURL(/\/risk/);
  await page.getByRole("option").first().click();
  await expect(page.getByRole("tab", { name: "Record" })).toBeVisible();
  await page.getByRole("button", { name: "Assess risk" }).first().click();
  await expect(page.getByText("calibrated probability", { exact: true })).toBeVisible();
  await expect(page.getByRole("list", { name: "Factors contributing to the estimate" })).toBeVisible();
  await a11y(page, "risk");
  await shot(page, "02-risk-assessment");
  await page.getByRole("button", { name: "Helpful", exact: true }).click();
  await expect(page.getByText("Thanks — feedback recorded")).toBeVisible();
  // manual entry
  await page.getByRole("button", { name: /Manual entry/ }).click();
  await page.getByRole("button", { name: "Assess risk" }).click();
  await expect(page.getByText("calibrated probability", { exact: true })).toBeVisible();
});

test("cross-hospital sharing: request, consent, approve, view, revoke", async ({ browser, baseURL }) => {
  const newPage = async () => (await browser.newContext({ baseURL })).newPage();
  // Hungarian clinician finds a patient without consent and reads the pseudonym
  const hu = await newPage();
  await login(hu, "dr.hungarian@fedcardio.dev");
  const target = hu.getByRole("option").nth(1);
  const pseudo = (await target.locator(".font-mono").innerText()).trim();
  await target.click();
  // the patient's ID card carries the details another hospital needs
  await hu.getByRole("button", { name: "ID card" }).click();
  const card = hu.getByRole("dialog");
  await expect(card.getByText(pseudo)).toBeVisible();
  const name = (await card.getByTestId("id-name").innerText()).trim();
  const born = (await card.getByText("Born").locator("xpath=following-sibling::div").innerText()).trim();
  const sex = (await card.getByText("Sex", { exact: true }).locator("xpath=following-sibling::div").innerText()).trim().toLowerCase();
  await a11y(hu, "id card");
  await hu.keyboard.press("Escape");

  // Cleveland clinician requests it
  const cl = await newPage();
  await login(cl, "dr.cleveland@fedcardio.dev");
  await cl.getByRole("link", { name: "Record sharing" }).click();
  await cl.getByRole("button", { name: "New request" }).first().click();
  await cl.getByLabel("Full name").fill(name);
  await cl.getByLabel("Birth year").fill(born);
  await cl.getByLabel("Sex").selectOption(sex);
  await cl.getByRole("button", { name: "Find patient" }).click();
  await expect(cl.getByText(/Record held by/)).toBeVisible();
  await expect(cl.getByRole("dialog").getByText(pseudo)).toBeVisible();
  await cl.getByLabel("Clinical justification").fill("Transferred to our cardiology ward for angiography");
  await cl.getByRole("button", { name: "Send request" }).click();
  await expect(cl.getByText("Request sent")).toBeVisible();
  await a11y(cl, "sharing");

  // Hungarian clinician records consent
  await hu.getByRole("tab", { name: /Consent/ }).click();
  await hu.getByRole("button", { name: "Record consent" }).click();
  await hu.getByRole("dialog").getByRole("button", { name: "Record consent" }).click();
  await expect(hu.getByText("Consent recorded")).toBeVisible();

  // Hungarian admin approves
  const adm = await newPage();
  await login(adm, "admin.hungarian@fedcardio.dev");
  await adm.goto("/sharing");
  await adm.getByRole("tab", { name: /Requests for our patients/ }).click();
  await adm.getByRole("row", { name: new RegExp(pseudo) }).getByRole("button", { name: "Review" }).click();
  await expect(adm.getByText("An active patient consent covers this purpose")).toBeVisible();
  await shot(adm, "03-share-review");
  await adm.getByRole("button", { name: "Approve" }).click();
  await expect(adm.getByText("Access granted")).toBeVisible();

  // Cleveland opens the decrypted record
  await cl.reload();
  await cl.getByRole("row", { name: new RegExp(pseudo) }).getByRole("button", { name: "Open record" }).click();
  await expect(cl.getByText("Decrypted for your hospital only")).toBeVisible();
  await shot(cl, "04-shared-record");
  await cl.keyboard.press("Escape");

  // admin revokes; recipient loses access
  await adm.reload();
  await adm.getByRole("tab", { name: /Requests for our patients/ }).click();
  await adm.getByRole("row", { name: new RegExp(pseudo) }).getByRole("button", { name: "Revoke" }).click();
  await expect(adm.getByText("Access revoked")).toBeVisible();
  await cl.reload();
  await expect(cl.getByRole("row", { name: new RegExp(pseudo) }).getByText("Revoked")).toBeVisible();
});

test("data scientist launches an encrypted federated job and watches it converge", async ({ page }) => {
  await login(page, "ds@fedcardio.dev");
  await expect(page).toHaveURL(/\/federated/);
  await page.getByLabel("Rounds", { exact: true }).fill("12");
  await page.getByRole("switch", { name: /Homomorphic encryption/ }).click();
  await page.getByRole("button", { name: "Launch training" }).click();
  await expect(page.getByText("Training launched")).toBeVisible();
  await expect(page.getByText("completed").first()).toBeVisible({ timeout: 60_000 });
  await a11y(page, "federated");
  await shot(page, "05-federated-console");
});

test("results explorer shows script-generated evidence and the paper comparison", async ({ page }) => {
  await login(page, "ds@fedcardio.dev");
  await page.getByRole("link", { name: "Experiments" }).click();
  await expect(page.getByText("Honest summary")).toBeVisible();
  await shot(page, "06-results-overview");
  await page.getByRole("tab", { name: "Methods" }).click();
  await expect(page.getByText("UCI Heart — 4 real hospitals")).toBeVisible();
  await a11y(page, "results-methods");
  await shot(page, "07-results-methods");
  await page.getByRole("tab", { name: "Privacy–utility" }).click();
  await shot(page, "08-results-privacy");
  await page.getByRole("tab", { name: "Non-IID & scale" }).click();
  await shot(page, "09-results-noniid");
  await page.getByRole("tab", { name: "vs. base paper" }).click();
  await expect(page.getByText("Different dataset — not directly comparable.")).toBeVisible();
  await shot(page, "10-results-paper");
});

test("platform admin sees model card and governance; auditor verifies the chain", async ({ page }) => {
  await login(page, "admin@fedcardio.dev");
  await page.getByRole("link", { name: "Model registry" }).click();
  await expect(page.getByRole("heading", { name: "Intended use" }).first()).toBeVisible();
  await a11y(page, "models");
  await shot(page, "11-model-registry");
  await page.getByRole("link", { name: "Administration" }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await a11y(page, "admin");
  await shot(page, "12-admin");
  // platform admin must not reach patient data
  await expect(page.getByRole("link", { name: "Risk assessment" })).toHaveCount(0);
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: /Sign out/ }).click();
  await expect(page).toHaveURL(/\/login/);

  await login(page, "auditor@fedcardio.dev");
  await expect(page).toHaveURL(/\/audit/);
  await expect(page.getByText("Chain intact")).toBeVisible();
  await a11y(page, "audit");
  await shot(page, "13-audit-log");
});

test("dark mode and mobile layout render", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, "dr.cleveland@fedcardio.dev");
  await page.getByRole("button", { name: "Change theme" }).click();
  await page.getByRole("menuitem", { name: "Dark" }).click();
  await page.getByRole("option").first().click();
  await page.getByRole("button", { name: "Assess risk" }).first().click();
  await expect(page.getByText("calibrated probability", { exact: true })).toBeVisible();
  await a11y(page, "risk-dark-mobile");
  await shot(page, "14-mobile-dark");
});
