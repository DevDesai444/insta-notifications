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

## 2. Make a throwaway Instagram account (3 min)

You are deleting Instagram from your phone, but the *server* still needs an
Instagram login, because **stories are invisible to logged-out visitors**.

1. Create a new Instagram account (any browser). Do **not** use your main one.
2. **Follow @zero2sudo** from it.
3. Open the account a few times over a day or two if you can — brand-new
   accounts that immediately start polling get flagged fastest.

> Use a throwaway account. Automated polling is against Instagram's terms of
> service, and the account doing it can get restricted or disabled.

---

## 3. Install and prove the notification path (3 min)

On whatever machine will run this (laptop, Raspberry Pi, VPS — see step 5):

```bash
git clone https://github.com/DevDesai444/insta-notifications.git
cd insta-notifications
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Edit `.env` and set, at minimum:

```ini
NTFY_TOPIC=zero2sudo-a7f3c91e4b     # the exact topic from step 1
IG_USERNAME=your_burner_account
IG_PASSWORD=your_burner_password
ANTHROPIC_API_KEY=sk-ant-...        # optional but recommended — see below
```

Now send yourself a test:

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
| **GitHub Actions**, nothing to run | enable `.github/workflows/poll.yml` | **No** — 5–15 min late |

A closed laptop sends no notifications. If you don't have a machine that stays
on, Fly.io is the cheap option and GitHub Actions is the free one — but the
free one is not real-time, and stories can expire before it looks.

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
