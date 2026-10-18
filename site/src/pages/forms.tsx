import type { Context } from "hono";
import { html } from "hono/html";
import { EMPLOYER_ID_RE, loadProfile, loadStats } from "../data";
import { readForm } from "../body";
import type { AppEnv } from "../env";
import { t, tj, type Key } from "../i18n";
import { Layout, page } from "../layout";
import { pageSeo, respondFormSeo } from "../seo";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

// Control characters other than tab and line breaks (a null byte included)
// carry no meaning in a statement and are dropped before anything is stored.
const CONTROL_RE = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g;

function field(body: Record<string, unknown>, key: string, max: number): string {
  const v = body[key];
  return (typeof v === "string" ? v : "").replace(CONTROL_RE, "").trim().slice(0, max);
}

// The two form tables live in D1. When it cannot take the row the form is
// shown again with what was typed and a line asking to try again.
const UNAVAILABLE: Key[] = ["error.server_text"];

async function dataAsOf(c: Context<AppEnv>): Promise<string | null> {
  const stats = await loadStats(c.env);
  return stats?.data_as_of ?? null;
}

// Validation messages are dictionary keys, rendered in the reader's language.
export async function respondForm(
  c: Context<AppEnv>, errors: Key[] = [], values: Record<string, string> = {}, status?: number,
): Promise<Response> {
  const lang = c.get("lang");
  const id = c.req.param("id") ?? "";
  const profile = await loadProfile(c.env, id);
  if (!profile) return c.notFound();
  return page(
    c,
    <Layout lang={lang} title={t(lang, "employer.respond")} dataAsOf={await dataAsOf(c)} seo={respondFormSeo(profile, lang)}>
      <h1>{t(lang, "employer.respond")}</h1>
      <p class="muted">
        {tj(lang, "form.respond_intro", { employer: <a href={`/employers/${id}`}>{profile.employer.display_name}</a> })}
      </p>
      {errors.length ? <ul class="errors">{errors.map((e) => <li>{t(lang, e)}</li>)}</ul> : null}
      <form method="post" action={`/employers/${id}/respond`} class="stack">
        <label>{t(lang, "form.name")}<input name="name" type="text" required maxlength={120} value={values.name ?? ""} /></label>
        <label>{t(lang, "form.work_email")}<input name="email" type="email" required maxlength={200} value={values.email ?? ""} /></label>
        <label>{t(lang, "form.statement")}<textarea name="statement" rows={6} required maxlength={5000}>{values.statement ?? ""}</textarea></label>
        <div class="hp"><label>{t(lang, "form.honeypot")}<input name="website" type="text" tabindex={-1} autocomplete="off" /></label></div>
        <button type="submit" class="btn btn-primary">{t(lang, "form.submit_statement")}</button>
      </form>
    </Layout>,
    status ?? (errors.length ? 400 : 200),
  );
}

export async function respondSubmit(c: Context<AppEnv>): Promise<Response> {
  const id = c.req.param("id") ?? "";
  const form = await readForm(c);
  if (!form.ok) return c.text(t(c.get("lang"), "form.rejected"), form.status);
  const body = form.fields;
  if (field(body, "website", 10)) return c.text(t(c.get("lang"), "form.rejected"), 400);
  const name = field(body, "name", 120);
  const email = field(body, "email", 200);
  const statement = field(body, "statement", 5000);
  const errors: Key[] = [];
  if (name.length < 2) errors.push("form.err_name");
  if (!EMAIL_RE.test(email)) errors.push("form.err_email");
  if (statement.length < 20) errors.push("form.err_statement");
  const profile = await loadProfile(c.env, id);
  if (!profile) return c.notFound();
  if (errors.length) return respondForm(c, errors, { name, email, statement });
  try {
    await c.env.DB.prepare(
      "INSERT INTO employer_responses (employer_id, received_at, contact_name, contact_email, statement, verified, published) VALUES (?, ?, ?, ?, ?, 0, 0)",
    ).bind(id, new Date().toISOString(), name, email, statement).run();
  } catch (e) {
    console.error(`response not stored: ${String(e).slice(0, 200)}`);
    return respondForm(c, UNAVAILABLE, { name, email, statement }, 503);
  }
  return thanks(c, "form.thanks_statement", `/employers/${id}`);
}

export async function correctionsForm(
  c: Context<AppEnv>, errors: Key[] = [], values: Record<string, string> = {}, status?: number,
): Promise<Response> {
  const lang = c.get("lang");
  const employer = (c.req.query("employer") ?? values.employer ?? "").slice(0, 40);
  return page(
    c,
    <Layout lang={lang} title={t(lang, "employer.correct")} dataAsOf={await dataAsOf(c)} seo={pageSeo("corrections", lang)}>
      <h1>{t(lang, "employer.correct")}</h1>
      <p class="muted">{t(lang, "form.correct_intro")}</p>
      {errors.length ? <ul class="errors">{errors.map((e) => <li>{t(lang, e)}</li>)}</ul> : null}
      <form method="post" action="/corrections" class="stack">
        <label>
          {t(lang, "form.record_ref")}
          <input name="record_ref" type="text" required maxlength={200} placeholder={t(lang, "form.record_placeholder")} value={values.record_ref ?? ""} />
        </label>
        <input type="hidden" name="employer" value={employer} />
        <label>{t(lang, "form.what_wrong")}<textarea name="request" rows={6} required maxlength={5000}>{values.request ?? ""}</textarea></label>
        <label>{t(lang, "form.reply_email")}<input name="email" type="email" maxlength={200} value={values.email ?? ""} /></label>
        <div class="hp"><label>{t(lang, "form.honeypot")}<input name="website" type="text" tabindex={-1} autocomplete="off" /></label></div>
        <button type="submit" class="btn btn-primary">{t(lang, "form.send_correction")}</button>
      </form>
    </Layout>,
    status ?? (errors.length ? 400 : 200),
  );
}

export async function correctionsSubmit(c: Context<AppEnv>): Promise<Response> {
  const form = await readForm(c);
  if (!form.ok) return c.text(t(c.get("lang"), "form.rejected"), form.status);
  const body = form.fields;
  if (field(body, "website", 10)) return c.text(t(c.get("lang"), "form.rejected"), 400);
  const recordRef = field(body, "record_ref", 200);
  const request = field(body, "request", 5000);
  const email = field(body, "email", 200);
  const employerRaw = field(body, "employer", 40);
  const errors: Key[] = [];
  if (recordRef.length < 3) errors.push("form.err_record");
  if (request.length < 10) errors.push("form.err_request");
  if (email && !EMAIL_RE.test(email)) errors.push("form.err_reply_email");
  if (errors.length) return correctionsForm(c, errors, { record_ref: recordRef, request, email, employer: employerRaw });
  let employerId: string | null = null;
  const candidate = employerRaw || (EMPLOYER_ID_RE.test(recordRef) ? recordRef : "");
  if (candidate && (await loadProfile(c.env, candidate))) employerId = candidate;
  try {
    await c.env.DB.prepare(
      "INSERT INTO corrections (employer_id, record_ref, received_at, request, contact_email, published) VALUES (?, ?, ?, ?, ?, 0)",
    ).bind(employerId, recordRef, new Date().toISOString(), request, email || null).run();
  } catch (e) {
    console.error(`correction not stored: ${String(e).slice(0, 200)}`);
    return correctionsForm(c, UNAVAILABLE, { record_ref: recordRef, request, email, employer: employerRaw }, 503);
  }
  return thanks(c, "form.thanks_correction", employerId ? `/employers/${employerId}` : "/");
}

async function thanks(c: Context<AppEnv>, message: Key, back: string): Promise<Response> {
  const lang = c.get("lang");
  c.header("Cache-Control", "no-store");
  return c.html(
    html`<!doctype html>${(
      <Layout lang={lang} title={t(lang, "form.thanks")} dataAsOf={await dataAsOf(c)}>
        <h1>{t(lang, "form.thanks")}</h1>
        <p>{t(lang, message)}</p>
        <p>
          <a href={back}>{t(lang, "common.back")}</a>
        </p>
      </Layout>
    ) as any}`,
  );
}
