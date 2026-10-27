import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const PW = "FedCardio!2026";
const SHOTS = process.env.E2E_SCREENSHOTS ?? "../docs/screenshots";

async function login(page: Page, email: string, { temporary = false } = {}) {
  await page.goto("/login");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PW);
  await page.getByRole("button", { name: /^Sign in/ }).click();
  // a temporary password opens the required "choose your own password" dialog, which hides the page behind it
  await expect(temporary ? page.getByRole("dialog", { name: "Choose your own password" })
    : page.getByRole("button", { name: "Account menu" })).toBeVisible();
}

// admin-created accounts start with a temporary password and must pick their own at first sign-in
async function choosePassword(page: Page, temporary: string, mine: string) {
  const d = page.getByRole("dialog", { name: "Choose your own password" });
  await expect(d).toBeVisible();
  await d.getByLabel("Temporary password").fill(temporary);
  await d.getByLabel("New password", { exact: true }).fill(mine);
  await d.getByLabel("Repeat new password").fill(mine);
  await d.getByRole("button", { name: "Save password" }).click();
  await expect(page.getByText("Password changed")).toBeVisible();
  await expect(d).toHaveCount(0);
}

async function a11y(page: Page, name: string) {
  // contrast is measured on the final colours, not mid fade-in
  await page.evaluate(() => Promise.all(document.getAnimations()
    .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity) // skip looping spinners and pulses
    .map((a) => a.finished.catch(() => undefined))));
  await page.waitForTimeout(300);
  const r =await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
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
  // demo accounts stay hidden until the demo password is typed with the email left empty
  await expect(page.getByText("Demo accounts")).toHaveCount(0);
  await page.getByLabel("Password", { exact: true }).fill("not-the-demo-password");
  await page.waitForTimeout(800);
  await expect(page.getByText("Demo accounts")).toHaveCount(0);
  await page.getByLabel("Password", { exact: true }).fill(PW);
  await expect(page.getByText("Demo accounts")).toBeVisible();
  await page.getByRole("button", { name: /admin@fedcardio\.dev/ }).click();
  await expect(page.getByLabel("Work email")).toHaveValue("admin@fedcardio.dev");
  await a11y(page, "login");
  await shot(page, "01-login");
  await page.getByLabel("Password", { exact: true }).fill("");
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
  // hand the trained model to the platform admin for review
  await page.getByRole("button", { name: "Register model" }).click();
  await expect(page.getByText("Model registered for review")).toBeVisible();
  await expect(page.getByText("In registry · staging")).toBeVisible();
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

test("platform admin replaces a hospital: add, upload data, deactivate, delete", async ({ browser, baseURL }) => {
  test.setTimeout(180_000); // four accounts, two password changes, an upload and a delete
  const newPage = async () => (await browser.newContext({ baseURL })).newPage();
  const code = `e2e_${Date.now() % 100000}`;
  const name = `Pune General ${code.slice(4)}`;
  const adminEmail = `admin@${code.replace("_", "-")}.fedcardio.dev`;
  const drEmail = `dr@${code.replace("_", "-")}.fedcardio.dev`;
  const pa = await newPage();
  await login(pa, "admin@fedcardio.dev");
  await pa.getByRole("link", { name: "Administration" }).click();
  await pa.getByRole("button", { name: "Add hospital" }).first().click();
  const hd = pa.getByRole("dialog");
  await hd.getByLabel("Hospital name").fill(name);
  await hd.getByLabel("Tenant code").fill(code);
  await hd.getByLabel("City").fill("Pune");
  await hd.getByLabel("Admin's full name").fill("Pune Admin");
  await hd.getByLabel("Admin's email").fill(adminEmail);
  await hd.getByLabel("Temporary password").fill(PW);
  await hd.getByRole("button", { name: "Add", exact: true }).click();
  await expect(pa.getByText("Hospital added", { exact: true })).toBeVisible();
  // the platform admin cannot appoint doctors: that is the hospital admin's job
  await pa.getByRole("button", { name: "Add user" }).click();
  await expect(pa.getByRole("dialog").getByLabel("Role").locator("option")).toHaveText(["Hospital admin", "Data scientist", "Auditor"]);
  await pa.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();

  // the new hospital's admin adds a doctor, then uploads its training data
  const ha = await newPage();
  await login(ha, adminEmail, { temporary: true });
  await choosePassword(ha, PW, "Apollo!Admin2026");
  await ha.getByRole("link", { name: "Administration" }).click();
  await ha.getByRole("button", { name: "Add user" }).click();
  const ud = ha.getByRole("dialog");
  await ud.getByLabel("Full name").fill("Dr. Pune");
  await ud.getByLabel("Email").fill(drEmail);
  await ud.getByLabel("Role").selectOption("clinician");
  await ud.getByLabel("Temporary password").fill(PW);
  await ud.getByRole("button", { name: "Create user" }).click();
  await expect(ha.getByText("User created")).toBeVisible();
  await ha.getByRole("tab", { name: "Training data" }).click();
  await expect(ha.getByText("No training data yet")).toBeVisible();
  await ha.getByLabel("Choose CSV file").setInputFiles({ name: "bad.csv", mimeType: "text/csv", buffer: Buffer.from("age,sex\n50,1\n") });
  await expect(ha.getByText("missing columns: cp, trestbps")).toBeVisible();
  const rows = Array.from({ length: 40 }, (_, i) => `${40 + i},${i % 2},${1 + (i % 4)},${120 + i},${200 + i},0,0,${150 - i},${i % 2},1.0,${i % 3 === 0 ? 1 : 0}`);
  const csv = "age,sex,cp,trestbps,chol,fbs,restecg,thalach,exang,oldpeak,target\n" + rows.join("\n");
  await ha.getByLabel("Choose CSV file").setInputFiles({ name: "pune.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await expect(ha.getByText("Training data uploaded")).toBeVisible();
  await expect(ha.getByText("pune.csv")).toBeVisible();
  await a11y(ha, "training-data");
  await shot(ha, "15-training-data");

  // the doctor starts with no patients and registers one
  const dr = await newPage();
  await login(dr, drEmail, { temporary: true });
  await choosePassword(dr, PW, "Apollo!Doctor2026");
  await expect(dr.getByText("No patients yet")).toBeVisible();
  await dr.getByRole("button", { name: "Add patient" }).first().click();
  const pd = dr.getByRole("dialog");
  await pd.getByLabel("Full name").fill("Meera Joshi");
  await pd.getByLabel("Hospital record number").fill("PGH-0001");
  await pd.getByLabel("Birth year").fill("1968");
  await pd.getByLabel("Serum cholesterol (mg/dL)").fill("245");
  await pd.getByLabel("Confirmed diagnosis (coronary artery disease)").selectOption("1");
  await a11y(dr, "add-patient");
  await shot(dr, "17-add-patient");
  await pd.getByRole("button", { name: "Register patient" }).click();
  await expect(dr.getByText("Patient registered")).toBeVisible();
  await expect(dr.getByRole("option", { name: /Meera Joshi/ })).toBeVisible();
  await dr.getByRole("button", { name: "Assess risk" }).first().click();
  await expect(dr.getByText("calibrated probability", { exact: true })).toBeVisible();

  // platform admin sees the counts, deactivates, then deletes
  await pa.reload();
  await pa.getByRole("tab", { name: "Hospitals" }).click();
  const card = pa.getByText(`tenant: ${code}`).locator("..");
  await expect(card.getByText("40")).toBeVisible();
  await a11y(pa, "hospitals");
  await shot(pa, "16-hospitals");
  await card.getByRole("button", { name: "Deactivate" }).click();
  await pa.getByRole("dialog").getByRole("button", { name: "Deactivate" }).click();
  await expect(pa.getByText(`${name} deactivated`)).toBeVisible();
  await ha.reload();
  await expect(ha).toHaveURL(/\/login/);
  await card.getByRole("button", { name: "Delete" }).click();
  const del = pa.getByRole("dialog");
  await expect(del.getByRole("button", { name: "Delete forever" })).toBeDisabled();
  await del.getByLabel(`Type ${code} to confirm`).fill(code);
  await del.getByRole("button", { name: "Delete forever" }).click();
  await expect(pa.getByText(`${name} permanently deleted`)).toBeVisible();
  await expect(pa.getByText(`tenant: ${code}`)).toHaveCount(0);
});
