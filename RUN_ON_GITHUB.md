# Run it 24/7 on GitHub — no computer of your own

Your repo is **public**, so GitHub Actions minutes are free and unlimited.
This is the path if you don't have a machine that stays on.

Total setup: about 5 minutes, all in the browser.

---

## 1. Subscribe on your iPhone

A topic has already been generated and wired in, so there is nothing to
configure. Install **ntfy** from the App Store, open it, allow notifications,
tap **+**, and subscribe to:

```
zero2sudo-f5bf63a219
```

Or just open <https://ntfy.sh/zero2sudo-f5bf63a219> on the phone.

In **iOS Settings → Notifications → ntfy**, turn **off Scheduled Summary**.
Leaving it on batches notifications and would delay them by hours.

> This repo is public, so that topic name is public too — anyone who reads it
> could push to your phone. The content is public Instagram posts either way,
> but if you want it locked down, add a repository secret named `NTFY_TOPIC`
> with a private name of your own. It overrides the built-in default.

---

## 2. Get an Instagram session cookie

Stories are invisible to logged-out visitors, so the watcher needs to be
signed in. You do **not** need a new account and you do **not** need to store
a password:

1. On a desktop, log in to <https://www.instagram.com> in a browser.
2. Open DevTools (**F12**) → **Application** → **Cookies** →
   `https://www.instagram.com`.
3. Find the row named **`sessionid`** and copy its value. It looks like
   `71234567890%3AAbCdEf...%3A17%3AAbCd...`.

The account you're logged in as must **follow @zero2sudo**.

> You can revoke this at any time: Instagram → Settings → Accounts Centre →
> Password and security → **Where you're logged in** → log out that session.
> The cookie dies instantly.

---

## 3. Add one repository secret

[**Click here to add it**](https://github.com/DevDesai444/insta-notifications/settings/secrets/actions/new)
— or go to **Settings → Secrets and variables → Actions → New repository
secret**.

| Name | Value |
|---|---|
| `IG_SESSIONID` | the cookie from step 2 |

Optional extras, same place:

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | enables reading links out of screenshots |
| `NTFY_TOPIC` | a private topic name, overriding the public default |

Secrets are encrypted and never appear in logs, even though the repo is
public.

---

## 4. Nothing — it's already deployed

The watcher is live and has already run. With no credentials it finishes in
about 4 seconds, having skipped everything, and it will keep doing that until
`IG_SESSIONID` exists. Every few hours it pushes a reminder to your phone
with a link straight to the form above.

**If you got a notification saying "Almost there — 1 step left", the whole
delivery chain already works.** The only missing piece is that cookie.

Once the secret is saved, the next firing starts a real 5h30m watch shift.

### If nothing happens within ~15 minutes of saving the secret

GitHub's scheduler takes its time. Measured on this repo: the first scheduled
run arrived **38 minutes** after the workflow was created, and `*/5` firings
then ran 2–3 minutes late. It does work — it just isn't prompt, and it is not
worth sitting and watching. Give it a nudge by hand:

**Actions** tab → **watch instagram** → **Run workflow** → **Run workflow**.

That starts a shift immediately, and also sends you the setup reminder again
so you can confirm the notification path. Pushing any commit to the default
branch does the same thing.

---

## Optional: make it hand over to itself

The crons do work, so this is a refinement rather than a fix. It removes the
few-minute gap at each shift changeover, and the risk of a firing being
dropped under load. If you want each shift to start the next one directly:

1. Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new)
   scoped to **this repository only**, with **Actions: Read and write**.
2. Save it as a repository secret named **`DISPATCH_TOKEN`**.

Each shift then dispatches the next one as it finishes. Without the token the
step prints a line and does nothing, and the crons remain the fallback.

The built-in `GITHUB_TOKEN` cannot do this: GitHub deliberately refuses to
start a workflow from an event raised with it, to stop workflows looping
forever. That is why a separate token is needed.

---

## How it stays running

GitHub caps a single job at 6 hours, so:

- Each run watches for **5h30m**, polling every 60 seconds.
- A cron fires **every 5 minutes**. If a shift is already running, that run
  exits in ~15 seconds. If none is running, it starts the next shift.
- The dedup database and Instagram session ride between shifts in the Actions
  cache, so you never get repeat notifications and it doesn't re-login
  constantly.

Expect a **gap of a few minutes every 5.5 hours** at shift changeover —
measured firings ran 2–3 minutes behind schedule, and GitHub warns they can
be dropped entirely under load, so occasionally it will be longer. If a story goes up during that
window and expires before the next shift starts, it's missed. Everything else
arrives within ~60 seconds.

---

## Things worth knowing

- **Actions caches are readable by anyone who can run workflows on this repo.**
  On a public repo that's you and any collaborators — pull requests from forks
  get their own isolated cache and cannot read yours. Still, the cached
  session file is a live Instagram credential. If that bothers you, make the
  repo private (you get 2,000 free minutes/month, which is *not* enough for
  24/7 — you'd need to fall back to a 5-minute cron) or just revoke the
  session when you're done.
- **ntfy.sh's free tier has a daily message cap per publishing IP** (and
  attachments expire after 3 hours). Each Actions run publishes from a fresh
  runner IP, so this won't bite you — but it's why a self-hosted or paid ntfy
  is the answer if you ever fan this out to many accounts.
- **GitHub asks that Actions be used for work related to the project.** A
  permanently-running watcher is a gray area, and heavy scheduled usage can
  get throttled. If this matters to you, the `docker compose up -d` path on
  any always-on box is the sanctioned option.
- **Scheduled workflows only run from the default branch.** This repo's
  default branch is already the one holding this code, so nothing to do — but
  if you rename or switch branches, move the workflow with it.
- GitHub disables scheduled workflows in repos with **no activity for 60
  days**. A single commit re-enables them.

---

## Turning it off

**Actions → watch instagram → ⋯ → Disable workflow.**

Then revoke the Instagram session (step 2) if you're done for good.
