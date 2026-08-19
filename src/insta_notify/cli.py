"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config
from .extract.vision import VisionExtractor
from .models import Item, Notification
from .notify import build_notifier
from .pipeline import Pipeline
from .runner import Runner, parse_duration
from .sources.fake import FakeSource
from .state import StateStore

log = logging.getLogger("insta_notify")

_TARGET_ID_KEY = "target_user_id"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("public_request").setLevel(logging.WARNING)
    logging.getLogger("private_request").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _build_source(cfg: Config, state: StateStore):
    from .sources.instagram import InstagramSource

    source = InstagramSource(
        username=cfg.ig_username,
        password=cfg.ig_password,
        target=cfg.target_username,
        session_file=cfg.session_file,
        totp_seed=cfg.ig_verification_code,
        sessionid=cfg.ig_sessionid,
    )
    cached = state.get_meta(_TARGET_ID_KEY)
    if cached:
        source.set_target_id(cached)
    return source


def _build_pipeline(cfg: Config, state: StateStore, source=None) -> Pipeline:
    vision = VisionExtractor(cfg.anthropic_api_key, cfg.vision_model) if cfg.use_vision else None
    if vision and not vision.available:
        vision = None
    return Pipeline(
        cfg=cfg,
        source=source if source is not None else _build_source(cfg, state),
        notifier=build_notifier(cfg),
        state=state,
        vision=vision,
    )


def _report_config(cfg: Config) -> bool:
    problems = cfg.validate()
    print(f"  watching        : @{cfg.target_username}")
    print(f"  poll interval   : {cfg.poll_interval}s (jitter ±{int(cfg.poll_jitter*100)}%)")
    print(f"  backend         : {cfg.backend}")
    if cfg.backend == "ntfy":
        print(f"  ntfy topic      : {cfg.ntfy_server}/{cfg.ntfy_topic or '(unset)'}")
    auth = (
        "session cookie" if cfg.ig_sessionid
        else f"password (@{cfg.ig_username})" if cfg.ig_username
        else "NOT SET"
    )
    print(f"  instagram auth  : {auth}")
    print(f"  stories / posts : {cfg.check_stories} / {cfg.check_posts}")
    print(f"  image reading   : {'on (' + cfg.vision_model + ')' if cfg.use_vision else 'off'}")
    print(f"  data dir        : {cfg.data_dir.resolve()}")
    print(f"  notify all      : {cfg.notify_all}")
    if problems:
        print("\n  PROBLEMS:")
        for p in problems:
            print(f"    - {p}")
        return False
    print("\n  config looks good.")
    return True


# ------------------------------------------------------------------ commands


def cmd_doctor(cfg: Config, _args) -> int:
    print("\nConfiguration\n" + "-" * 60)
    ok = _report_config(cfg)
    if not ok:
        return 1

    print("\nInstagram login\n" + "-" * 60)
    with StateStore(cfg.state_db) as state:
        try:
            source = _build_source(cfg, state)
            source.connect()
            user_id = source.target_id
            state.set_meta(_TARGET_ID_KEY, user_id)
            print(f"  logged in, @{cfg.target_username} resolves to id {user_id}")
        except Exception as exc:
            print(f"  FAILED: {exc}")
            print("\n  Run `insta-notify login` for the interactive login flow.")
            return 1

        print("\nFetch check\n" + "-" * 60)
        try:
            stories = source.fetch_stories()
            print(f"  stories visible now : {len(stories)}")
        except Exception as exc:
            print(f"  stories FAILED: {exc}")
        try:
            posts = source.fetch_posts(limit=3)
            print(f"  recent posts        : {len(posts)}")
            for p in posts[:3]:
                print(f"    - {p.taken_at:%Y-%m-%d %H:%M} {p.permalink}")
        except Exception as exc:
            print(f"  posts FAILED: {exc}")
    return 0


def cmd_login(cfg: Config, _args) -> int:
    """Interactive first login — handles 2FA prompts on a terminal."""
    problems = [p for p in cfg.validate() if "IG_USERNAME" in p]
    if problems:
        for p in problems:
            print(f"  {p}")
        return 1
    with StateStore(cfg.state_db) as state:
        source = _build_source(cfg, state)
        try:
            source.connect()
        except Exception as exc:
            print(f"login failed: {exc}")
            print(
                "\nIf Instagram asked for a code, set IG_TOTP_SEED in .env "
                "(Settings > Accounts Centre > Password and security > "
                "Two-factor authentication > Authentication app), then retry."
            )
            return 1
        user_id = source.target_id
        state.set_meta(_TARGET_ID_KEY, user_id)
        print(f"logged in. session saved to {cfg.session_file}")
        print(f"@{cfg.target_username} -> {user_id}")
    return 0


def cmd_selftest(cfg: Config, _args) -> int:
    """Send a real notification so the phone setup can be verified."""
    problems = cfg.validate()
    blocking = [p for p in problems if "NTFY" in p or "PUSHOVER" in p or "BACKEND" in p]
    if blocking:
        for p in blocking:
            print(f"  {p}")
        return 1

    notifier = build_notifier(cfg)
    note = Notification(
        title="🔗 Test Corp · New Grad SWE (Workday)",
        body=(
            "This is a test from insta-notify.\n\n"
            "Tap this notification — it should open the link below in your "
            "default browser.\n\n"
            "[Workday] https://www.myworkday.com/\n\n"
            f"— watching @{cfg.target_username}"
        ),
        links=["https://www.myworkday.com/", "https://www.instagram.com/"],
        click_url="https://www.myworkday.com/",
        tags=["rotating_light"],
        priority=cfg.ntfy_priority,
    )
    ok = notifier.send(note)
    if ok:
        print(f"sent via {notifier.describe()} — check your phone.")
        print("Tapping it should open myworkday.com in Safari.")
        return 0
    print("send FAILED — see the error above.")
    return 1


def cmd_demo(cfg: Config, _args) -> int:
    """Run the real pipeline over fabricated content. No Instagram needed."""
    now = datetime.now(timezone.utc)
    items = [
        Item(
            kind="story",
            item_id=f"story:demo-{now.timestamp()}",
            username=cfg.target_username,
            taken_at=now - timedelta(minutes=2),
            permalink=f"https://www.instagram.com/stories/{cfg.target_username}/1/",
            caption="NVIDIA new grad SWE 2026 just opened, apply now",
            sticker_links=[
                "https://l.instagram.com/?u=https%3A%2F%2Fnvidia.wd5.myworkdayjobs.com"
                "%2Fen-US%2FNVIDIAExternalCareerSite%2Fjob%2FUS-CA%2FNew-Grad-SWE_JR1234&e=X"
            ],
        ),
        Item(
            kind="post",
            item_id=f"post:demo-{now.timestamp()}",
            username=cfg.target_username,
            taken_at=now - timedelta(minutes=1),
            permalink="https://www.instagram.com/p/DemoCode/",
            caption=(
                "Big one today — Stripe new grad applications are live.\n"
                "boards.greenhouse.io/stripe/jobs/456 (US + Canada)"
            ),
        ),
    ]

    cfg.seed_on_first_run = False
    with StateStore(cfg.data_dir / "demo-state.db") as state:
        pipeline = _build_pipeline(cfg, state, source=FakeSource(
            posts=[i for i in items if i.kind == "post"],
            stories=[i for i in items if i.kind == "story"],
        ))
        # Vision is pointless here — there are no real images.
        pipeline.vision = None
        sent = pipeline.poll_once()
    print(f"\ndemo complete: {sent} notification(s) sent via {cfg.backend}.")
    return 0 if sent else 1


QUICKSTART_TEMPLATE = """\
# Written by `insta-notify quickstart`. Edit freely.

IG_TARGET_USERNAME={target}

# ── Instagram sign-in ────────────────────────────────────────────────────
# Stories are invisible to logged-out visitors, so this is required.
#
# EASIEST (no new account, no password stored):
#   1. Log in to instagram.com in a desktop browser
#   2. DevTools (F12) > Application > Cookies > https://www.instagram.com
#   3. Copy the value of the `sessionid` cookie and paste it below
# Whatever account you use must FOLLOW @{target}.
IG_SESSIONID=

# Or, if you'd rather use a throwaway account's login:
IG_USERNAME=
IG_PASSWORD=
IG_TOTP_SEED=

# ── Where notifications go ───────────────────────────────────────────────
NOTIFY_BACKEND=ntfy
NTFY_TOPIC={topic}
NTFY_SERVER=https://ntfy.sh
NTFY_PRIORITY=5

# ── Reading links out of screenshots (optional but recommended) ──────────
# Catches Workday links that only exist as pixels in a story image.
ANTHROPIC_API_KEY=
VISION_ENABLED=true
VISION_MODEL=claude-opus-5

# ── Timing ───────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS=60
NOTIFY_ALL=true
DATA_DIR=data
SEED_ON_FIRST_RUN=true
"""


def cmd_quickstart(cfg: Config, args) -> int:
    """Write a .env with a generated topic and prove the phone works."""
    env_path = Path(args.env_file or ".env")

    if env_path.exists() and not args.force:
        print(f"{env_path} already exists — leaving it alone.")
        print("Re-run with --force to overwrite it.\n")
        topic = cfg.ntfy_topic
    else:
        topic = cfg.ntfy_topic or f"{cfg.target_username}-{secrets.token_hex(5)}"
        env_path.write_text(
            QUICKSTART_TEMPLATE.format(target=cfg.target_username, topic=topic)
        )
        print(f"wrote {env_path}\n")

    if not topic:
        print("No NTFY_TOPIC set. Add one to .env and re-run.")
        return 1

    print("=" * 66)
    print("  STEP 1 — on your iPhone")
    print("=" * 66)
    print("  1. Install 'ntfy' from the App Store (free)")
    print("  2. Open it, allow notifications, tap + and subscribe to:\n")
    print(f"        {topic}\n")
    print("  3. iOS Settings > Notifications > ntfy:")
    print("     turn OFF 'Scheduled Summary' (it would delay alerts by hours)")
    print()
    print(f"  Or just open this link on the phone:  https://ntfy.sh/{topic}")
    print()

    if args.no_test:
        print("skipping the test push (--no-test)")
    else:
        try:
            input("  Press Enter once you've subscribed, to send a test push… ")
        except (EOFError, KeyboardInterrupt):
            print()
        cfg.ntfy_topic = topic
        cfg.backend = "ntfy"
        if cmd_selftest(cfg, args) != 0:
            return 1
        print()

    print("=" * 66)
    print("  STEP 2 — let it read Instagram")
    print("=" * 66)
    print(f"  Open {env_path} and set IG_SESSIONID (instructions are in the file).")
    print("  Then:")
    print("      insta-notify doctor      # verifies the login works")
    print("      insta-notify run         # starts watching")
    print()
    print("  No machine that stays on? This repo ships a GitHub Actions")
    print("  watcher that runs it 24/7 for free — see RUN_ON_GITHUB.md")
    print()
    return 0


SECRETS_URL = (
    "https://github.com/DevDesai444/insta-notifications/settings/secrets/actions/new"
)
GUIDE_URL = (
    "https://github.com/DevDesai444/insta-notifications/blob/"
    "claude/instagram-newgrad-notifications-1nxoju/RUN_ON_GITHUB.md"
)


def _alert_auth_failure(cfg: Config, exc: Exception) -> None:
    """Tell the phone when Instagram stops accepting our sign-in.

    Session cookies expire, and passwords get challenged. Without this the
    watcher just goes quiet and the first you'd know is noticing you haven't
    heard about a role in a month.
    """
    how_to_fix = (
        "Grab a fresh `sessionid` cookie:\n"
        "1. Log in to instagram.com on a desktop\n"
        "2. F12 → Application → Cookies → instagram.com\n"
        "3. Copy `sessionid`\n"
        "4. Tap below and update the IG_SESSIONID secret"
        if cfg.ig_sessionid
        else "Check the IG_USERNAME / IG_PASSWORD secrets, and whether "
        "Instagram is asking that account for a security check."
    )
    note = Notification(
        title="🔴 Instagram sign-in stopped working",
        body=(
            f"The @{cfg.target_username} watcher can no longer sign in, so it "
            f"is not seeing new posts.\n\n{how_to_fix}\n\n"
            f"Details: {str(exc)[:200]}"
        ),
        links=[SECRETS_URL, GUIDE_URL],
        link_labels=["Update the secret", "Instructions"],
        click_url=SECRETS_URL,
        tags=["rotating_light"],
        priority=5,
    )
    try:
        build_notifier(cfg).send(note)
    except Exception:  # a broken notifier must not mask the original error
        log.exception("could not send the sign-in failure alert")


def cmd_preflight(cfg: Config, args) -> int:
    """Check readiness, and push what's still missing to the phone.

    The watcher can be fully deployed while still lacking the one thing only
    a human can supply: an Instagram session. Rather than dying in a log
    nobody reads, this puts the remaining step on the lock screen.

    Exit codes: 0 ready, 2 waiting on the user, 1 misconfigured.
    """
    problems = cfg.validate()
    blocking_notify = [
        p for p in problems if "NTFY" in p or "PUSHOVER" in p or "BACKEND" in p
    ]
    if blocking_notify:
        for p in blocking_notify:
            log.error("config: %s", p)
        return 1

    if cfg.has_instagram_auth:
        log.info("preflight OK — Instagram auth present, notifications configured")
        return 0

    log.warning("no Instagram credentials; notifying the phone and standing by")

    if args.quiet:
        return 2

    notifier = build_notifier(cfg)
    note = Notification(
        title="⚙️ Almost there — 1 step left",
        body=(
            "Your @{target} watcher is deployed and running on GitHub.\n\n"
            "It just needs to be signed in to Instagram (stories are invisible "
            "to logged-out visitors).\n\n"
            "On a desktop:\n"
            "1. Log in to instagram.com\n"
            "2. F12 → Application → Cookies → instagram.com\n"
            "3. Copy the value of the `sessionid` cookie\n"
            "4. Tap below, name the secret IG_SESSIONID, paste, save\n\n"
            "Notifications start within ~5 minutes of saving it."
        ).format(target=cfg.target_username),
        links=[SECRETS_URL, GUIDE_URL],
        link_labels=["Add the secret", "Instructions"],
        click_url=SECRETS_URL,
        tags=["gear"],
        priority=4,
    )
    notifier.send(note)
    return 2


def cmd_once(cfg: Config, args) -> int:
    if args.no_seed:
        cfg.seed_on_first_run = False
    with StateStore(cfg.state_db) as state:
        pipeline = _build_pipeline(cfg, state)
        try:
            pipeline.source.connect()
            state.set_meta(_TARGET_ID_KEY, pipeline.source.target_id)
        except Exception as exc:
            log.error("could not connect to Instagram: %s", exc)
            _alert_auth_failure(cfg, exc)
            return 1
        sent = pipeline.poll_once()
        state.prune()
    log.info("poll complete, %d notification(s) sent", sent)
    return 0


def cmd_run(cfg: Config, args) -> int:
    problems = cfg.validate()
    if problems:
        for p in problems:
            log.error("config: %s", p)
        return 1
    if args.no_seed:
        cfg.seed_on_first_run = False
    if args.interval:
        cfg.poll_interval = args.interval
    try:
        duration = parse_duration(getattr(args, "duration", None))
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    with StateStore(cfg.state_db) as state:
        pipeline = _build_pipeline(cfg, state)
        try:
            pipeline.source.connect()
            state.set_meta(_TARGET_ID_KEY, pipeline.source.target_id)
        except Exception as exc:
            log.error("could not connect to Instagram: %s", exc)
            log.error("try `insta-notify login` first")
            _alert_auth_failure(cfg, exc)
            return 1

        state.prune()
        runner = Runner(pipeline, cfg.poll_interval, cfg.poll_jitter, duration=duration)
        runner.install_signal_handlers()
        runner.run_forever()
    return 0


# --------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="insta-notify",
        description=(
            "Real-time iPhone push notifications for a watched Instagram "
            "account's posts and stories, with tap-to-open job links."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--env-file", default=".env", help="path to the .env file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="watch continuously (the daemon)")
    p_run.add_argument("--interval", type=int, help="override POLL_INTERVAL_SECONDS")
    p_run.add_argument(
        "--no-seed",
        action="store_true",
        help="notify about currently-visible content instead of silently recording it",
    )
    p_run.add_argument(
        "--duration",
        help="stop cleanly after this long, e.g. 5h30m (default: run forever)",
    )
    p_run.set_defaults(func=cmd_run)

    p_quick = sub.add_parser(
        "quickstart", help="set everything up and verify your phone (start here)"
    )
    p_quick.add_argument("--force", action="store_true", help="overwrite an existing .env")
    p_quick.add_argument("--no-test", action="store_true", help="skip the test push")
    p_quick.set_defaults(func=cmd_quickstart)

    p_pre = sub.add_parser(
        "preflight",
        help="check readiness; push the remaining setup step to your phone",
    )
    p_pre.add_argument(
        "--quiet", action="store_true", help="don't send the reminder notification"
    )
    p_pre.set_defaults(func=cmd_preflight)

    p_once = sub.add_parser("once", help="run a single poll and exit (for cron)")
    p_once.add_argument("--no-seed", action="store_true")
    p_once.set_defaults(func=cmd_once)

    sub.add_parser("doctor", help="check config, login, and fetching").set_defaults(
        func=cmd_doctor
    )
    sub.add_parser("login", help="log in to Instagram and save the session").set_defaults(
        func=cmd_login
    )
    sub.add_parser(
        "selftest", help="send a test push notification to your phone"
    ).set_defaults(func=cmd_selftest)
    sub.add_parser(
        "demo", help="push two fake notifications to check formatting end to end"
    ).set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    cfg = Config.from_env(args.env_file)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    try:
        return args.func(cfg, args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
