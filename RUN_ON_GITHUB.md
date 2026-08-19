# Run it 24/7 on GitHub — no computer of your own

Your repo is **public**, so GitHub Actions minutes are free and unlimited.
This is the path if you don't have a machine that stays on.

Total setup: about 5 minutes, all in the browser.

---

## 1. Pick your ntfy topic

Install **ntfy** from the App Store, open it, allow notifications, tap **+**,
and subscribe to a long unguessable name:

```
zero2sudo-a7f3c91e4b
```

In **iOS Settings → Notifications → ntfy**, turn **off Scheduled Summary**.
Leaving it on batches notifications and would delay them by hours.

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

## 3. Add three repository secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**
in this repo, and add:

| Name | Value |
|---|---|
| `NTFY_TOPIC` | the topic from step 1 |
| `IG_SESSIONID` | the cookie from step 2 |
| `ANTHROPIC_API_KEY` | *optional* — enables reading links out of screenshots |

Secrets are encrypted and are never shown in logs, even though the repo is
public.

---

## 4. Turn it on

**Actions** tab → **watch instagram** → **Run workflow** → **Run workflow**.

That's it. You should start getting notifications within a minute or two of
@zero2sudo posting.

To confirm it's alive, open the running job — it logs a line per poll at
debug level and a line whenever it notifies.

---

## How it stays running

GitHub caps a single job at 6 hours, so:

- Each run watches for **5h30m**, polling every 60 seconds.
- A cron fires **every 5 minutes**. If a shift is already running, that run
  exits in ~15 seconds. If none is running, it starts the next shift.
- The dedup database and Instagram session ride between shifts in the Actions
  cache, so you never get repeat notifications and it doesn't re-login
  constantly.

Expect a **gap of up to ~5–15 minutes every 5.5 hours** at shift changeover,
because GitHub's scheduler is not punctual. If a story goes up during that
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
