# insta-notifications

Watches one Instagram account and pushes every new **post and story** to your
iPhone within about a minute — with the job link pulled out and made tappable,
so tapping the notification opens the Workday/Greenhouse/Lever page directly in
Safari.

Built so you can **delete Instagram from your phone** and still not miss a
posting.

**→ [SETUP.md](SETUP.md) gets you notifications in about 10 minutes.**

---

## What a notification looks like

```
┌──────────────────────────────────────────────┐
│  🔗 Nvidia · New Grad SWE (Workday)          │
│                                              │
│  Screenshot of the NVIDIA careers page —     │
│  2026 University Recruiting, US locations,   │
│  applications open now.                      │
│                                              │
│  [Workday] https://nvidia.wd5.myworkdayjobs… │
│                                              │
│  — Story by @zero2sudo                       │
│                                              │
│  [ Nvidia (Workday) ]  [ Open Simplify ]     │
└──────────────────────────────────────────────┘
```

Tapping the body opens the Workday link in your default browser. Each extra
link becomes its own button (up to three, ntfy's limit).

---

## The part that took the work: links that aren't links

He posts job links three different ways, and only one of them is a real link.

| How it appears | How it's found |
|---|---|
| URL typed in the caption | Regex over the caption text |
| Story **link sticker** | Read from the story, then unwrapped — Instagram wraps these in `l.instagram.com/?u=…`, so the redirect is stripped to reveal the real Workday URL |
| **A screenshot of a Workday page** — never clickable, not even on Instagram | The image is sent to Claude, which transcribes the URL out of the pixels |

That third row is the whole reason this project needs an image step. A
screenshot of a job posting has the URL rendered as *pixels*; there is no link
to extract. Classic OCR is unreliable on exactly the characters that matter in
a URL (`l`/`1`/`I`, `0`/`O`, `rn`/`m`), so the image goes to `claude-opus-5`
with a structured-output schema instead. The same call also names the company
and role for the notification title, and says whether the post is job-related
at all.

If there's no API key, no SDK, or the call fails, it silently falls back to
caption-and-sticker links. You still get the notification.

Instagram **stories carry no caption field at all** (verified against
instagrapi's model — see `tests/test_instagram_source.py`), so for stories the
image is the *only* source of text. That makes the vision step much more than
a nice-to-have if most of what you care about arrives as stories.

---

## How it works

```
  every ~60s
      │
      ▼
  ┌─────────────┐   posts + stories   ┌──────────────┐
  │ instagrapi  │────────────────────▶│  dedup       │  SQLite: already sent?
  │ (burner     │                     │  (state.db)  │
  │  session)   │                     └──────┬───────┘
  └─────────────┘                            │ new only
                                             ▼
                          ┌──────────────────────────────┐
                          │ extract links                │
                          │  • caption regex             │
                          │  • sticker → unwrap redirect │
                          │  • image → Claude vision     │
                          └──────────────┬───────────────┘
                                         ▼
                          ┌──────────────────────────────┐
                          │ ntfy  → APNs → your iPhone   │
                          │  click = the job link        │
                          └──────────────────────────────┘
```

### Why polling, and what "real time" means here

Instagram has no public API and no webhook for someone else's account, so
"real time" is a tight poll, not a push. Default is **60 seconds** with ±20%
jitter (a perfectly regular request pattern is what gets accounts flagged).
Delivery from there is instant — ntfy pushes over APNs.

You can drop `POLL_INTERVAL_SECONDS` to 30, but not below: two API calls per
poll at 30s is already ~240 requests/hour, which is where Instagram starts
pushing back. The runner backs off exponentially when Instagram errors, up to
15 minutes, and resets on the first success.

### Why ntfy

It's the only free option that does the thing you actually asked for: its
`click` field makes **tapping the notification open a URL in your default
browser**, and `actions` adds up to three labelled link buttons. No account
needed, and the iOS app delivers over APNs so it's instant.

Pushover works too (`NOTIFY_BACKEND=pushover`, ~$5 one-off) — it carries one
tappable link instead of three, with the rest listed in the body.

---

## Commands

```bash
python -m insta_notify selftest   # send a test push — verify your phone first
python -m insta_notify doctor     # check config, log in, list recent posts
python -m insta_notify login      # log in to Instagram, save the session
python -m insta_notify demo       # two fake notifications, no Instagram needed
python -m insta_notify run        # watch continuously  ← the daemon
python -m insta_notify once       # single poll, then exit (for cron)
```

Add `-v` for debug logging.

---

## Configuration

Everything is environment variables; see [`.env.example`](.env.example) for the
annotated list. The ones that matter most:

| Variable | Default | What it does |
|---|---|---|
| `IG_TARGET_USERNAME` | `zero2sudo` | Account to watch |
| `IG_USERNAME` / `IG_PASSWORD` | — | **Throwaway** account that follows the target |
| `NTFY_TOPIC` | — | Your private ntfy topic. Make it unguessable |
| `ANTHROPIC_API_KEY` | — | Enables reading links out of images |
| `POLL_INTERVAL_SECONDS` | `60` | How often to check |
| `NOTIFY_ALL` | `true` | `false` = only posts with a link or a keyword hit |
| `DATA_DIR` | `data` | Session + dedup DB. **Must persist**, or you'll get repeats |
| `SEED_ON_FIRST_RUN` | `true` | First poll records existing content silently |

`NOTIFY_ALL=true` is the default on purpose. The chat-screenshot posts about
new grad roles often have an empty or unrelated caption, so keyword filtering
would drop exactly the ones worth seeing.

---

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # 85 tests
python -m insta_notify demo  # end-to-end with the console backend
```

Tests cover URL extraction and Instagram redirect unwrapping, dedup and
persistence across restarts, first-run seeding, retry-on-send-failure, the
vision merge path, the ntfy payload against the documented JSON schema, and
the instagrapi field mappings (those last ones skip if instagrapi isn't
installed).

---

## Honest limitations

- **This is against Instagram's terms of service.** Automated reading of
  another account's content can get the account doing it restricted or
  disabled. Use a throwaway account; don't use your real one.
- **Not truly push.** Median delay is about half your poll interval, so ~30s
  by default. A story posted and deleted inside a minute can be missed.
- **Video stories** are analysed from their cover frame only. A link that
  appears mid-video won't be read.
- **Vision transcription isn't perfect.** A URL read out of a low-resolution
  screenshot can come back wrong. The image is attached to the notification so
  you can always read it yourself, and the summary text is included.
- **ntfy.sh is a free public service** with per-IP daily message limits and
  attachments that expire after 3 hours. Fine for a handful of posts a day. If
  you self-host ntfy, you must set `upstream-base-url: https://ntfy.sh` in its
  config or **iOS notifications will not arrive instantly** — self-hosted
  servers have no APNs connection of their own.
- **Anyone who knows your ntfy topic can read your notifications.** Use a long
  random topic name, or set `NTFY_TOKEN` with an access-controlled topic.
