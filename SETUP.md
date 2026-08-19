# Get notifications in ~10 minutes

Do these in order. Step 3 proves your phone works before you touch Instagram.

---

## 1. Set up your iPhone (2 min)

1. Install **ntfy** from the App Store (free, open source).
2. Open it → **allow notifications** when asked.
3. Tap **+** and subscribe to a topic name.

   Make it long and unguessable — a topic on the public server is readable by
   anyone who knows the name:

   ```
   zero2sudo-a7f3c91e4b
   ```

4. In iOS **Settings → Notifications → ntfy**, turn on **Allow Notifications**,
   **Lock Screen**, **Banners**, and **Sounds**. Turn OFF **Scheduled Summary**
   for ntfy — that setting batches notifications and would delay them by hours.

---

## 2. Get an Instagram session cookie (2 min)

You're deleting Instagram from your phone, but the *watcher* still needs to be
signed in, because **stories are invisible to logged-out visitors**.

You don't need a new account and you don't need to store a password:

1. On a desktop, log in to <https://www.instagram.com> in a browser.
2. Open DevTools (**F12**) → **Application** → **Cookies** →
   `https://www.instagram.com`.
3. Copy the value of the **`sessionid`** cookie.

The account you're logged in as must **follow @zero2sudo**.

> Revoke it whenever you like: Instagram → Settings → Accounts Centre →
> Password and security → **Where you're logged in** → log out that session.
>
> Automated polling is against Instagram's terms of service, and the account
> doing it can get restricted. If that worries you, make a throwaway account,
> follow @zero2sudo from it, and take the cookie from that instead.

---

## 3. Install and prove the notification path (3 min)

On whatever machine will run this (laptop, Raspberry Pi, VPS — see step 5):

```bash
git clone https://github.com/DevDesai444/insta-notifications.git
cd insta-notifications
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m insta_notify quickstart
```

`quickstart` writes a `.env` with a generated topic, walks you through the
phone setup, and sends a test push.

Then open `.env` and paste in your cookie from step 2:

```ini
IG_SESSIONID=71234567890%3AAbCdEf...
ANTHROPIC_API_KEY=sk-ant-...        # optional but recommended — see below
```

To re-send the test at any point:

```bash
python -m insta_notify selftest
```

**Your phone should buzz within a second or two.** Tap it — Safari should open
`myworkday.com`. If that works, the hard part is done.

---

## 4. Log in to Instagram and start watching

```bash
python -m insta_notify doctor    # checks config, logs in, lists recent posts
python -m insta_notify run       # starts watching
```

The first poll records what is already posted **without** notifying you, so you
don't get a burst of old content. Everything after that gets pushed.

Leave it running. That's it.

---

## 5. Keep it running 24/7

`run` only notifies while the process is alive. Pick one:

| Where | Command | Real-time? |
|---|---|---|
| **Any always-on box** (Pi, VPS, old laptop) | `docker compose up -d` | Yes — ~60s |
| **Linux / Raspberry Pi**, no Docker | `deploy/insta-notify.service` (systemd) | Yes — ~60s |
| **macOS**, always plugged in | `deploy/com.instanotify.watcher.plist` (launchd) | Yes — ~60s |
| **Fly.io** (~$2/mo, nothing at home) | `fly deploy` — see `fly.toml` | Yes — ~60s |
| **GitHub Actions**, nothing to run at all | see **[RUN_ON_GITHUB.md](RUN_ON_GITHUB.md)** | Yes — ~60s, with a short gap every 5.5h |

A closed laptop sends no notifications. **If you have no machine that stays
on, use [RUN_ON_GITHUB.md](RUN_ON_GITHUB.md)** — your repo is public, so
Actions minutes are free and unlimited, and the watcher runs there in ~5.5h
shifts with no server of your own.

---

## About the `ANTHROPIC_API_KEY`

Skip it and you still get every post and story, with any link that's in the
caption or in a story link sticker.

Add it and the watcher also **reads the image**. That's what catches the
Workday links he posts as screenshots, which were never clickable on Instagram
in the first place — they get pulled out of the picture and turned into a
tappable button. It also names the company and role in the notification title.

Get one at <https://console.anthropic.com/>. Cost is roughly a cent or two per
image analysed; a busy day of ~20 story frames is a few cents.
