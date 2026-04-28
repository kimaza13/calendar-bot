# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Telegram bot that automates calendar management across Google Calendar, Apple Calendar (iCloud CalDAV), and Notion. Features: create events from natural language, sync calendars, send reminders, parse schedules from Telegram messages and email.

## Stack

- **Language:** Python 3.11+
- **Telegram bot:** `python-telegram-bot`
- **Google Calendar:** `google-api-python-client` + `google-auth-oauthlib`
- **Apple Calendar (iCloud):** `caldav`
- **Notion:** `notion-client`
- **NLP parsing:** `dateparser` for extracting dates/times from text
- **Scheduler:** `APScheduler` for reminders
- **Config:** `python-dotenv` + `.env`

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python main.py

# Run a single test
pytest tests/test_<module>.py -v

# Run all tests
pytest

# Lint
ruff check .
```

## Architecture

```
calendar-bot/
├── main.py              # Entry point — starts Telegram bot
├── bot/
│   ├── handlers.py      # Telegram command and message handlers
│   └── keyboards.py     # Inline keyboard layouts
├── integrations/
│   ├── google_cal.py    # Google Calendar API client
│   ├── apple_cal.py     # iCloud CalDAV client
│   └── notion_cal.py    # Notion database client
├── services/
│   ├── parser.py        # NLP: extract event details from text
│   ├── sync.py          # Two-way sync logic across all three calendars
│   └── reminders.py     # APScheduler-based reminder jobs
├── config.py            # Loads and validates env vars
├── .env                 # Secrets (never commit)
└── tests/
```

### Key flows

**Create event from message:** User sends text → `parser.py` extracts title, date, time, duration → `services/sync.py` writes to all enabled calendars.

**Sync:** `sync.py` pulls events from all three sources, deduplicates by title+time, pushes missing events to the others. Run on schedule via APScheduler.

**Reminders:** On event creation, APScheduler schedules a job to send a Telegram message N minutes before the event.

## Environment Variables

```
TELEGRAM_BOT_TOKEN=
GOOGLE_CREDENTIALS_JSON=   # Path to OAuth2 credentials file
ICLOUD_USERNAME=
ICLOUD_PASSWORD=           # App-specific password from appleid.apple.com
NOTION_TOKEN=
NOTION_DATABASE_ID=
REMINDER_MINUTES=15        # Default reminder lead time
```

## Auth Notes

- **Google Calendar:** OAuth2 flow — first run opens a browser to authorize. Token saved to `token.json`.
- **Apple iCloud:** Requires an app-specific password (not your main Apple ID password). Generate at appleid.apple.com → Security → App-Specific Passwords.
- **Notion:** Internal integration token from notion.so/my-integrations. The target database must have the integration added manually.
