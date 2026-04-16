# Marathon AI Coach — Telegram Bot

A personal AI running coach that pulls live data from Strava, Oura, Garmin, and Final Surge into Supabase, then lets you chat with Claude about your training via Telegram.

## Architecture

```
Strava ──┐
Garmin ──┤── sync scripts ──► Supabase ──► Claude (Anthropic API)
Oura ────┤                                        │
Final Surge ─┘                              Telegram Bot ◄──► You
```

## Quick Start

### 1. Create your Telegram bot

1. Open Telegram, search for `@BotFather`
2. Send `/newbot` and follow the prompts
3. Copy your bot token into `.env`

### 2. Set up Supabase

1. Create a free project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** and paste + run `supabase/schema.sql`
3. Copy your project URL and anon key into `.env`

### 3. Get your API credentials

**Strava:**
1. Go to [strava.com/settings/api](https://www.strava.com/settings/api) and create an app
2. Run the OAuth flow once to get your refresh token:
   ```
   https://www.strava.com/oauth/authorize?client_id=YOUR_ID&redirect_uri=http://localhost&response_type=code&scope=activity:read_all
   ```
3. Exchange the `code` for a refresh token via POST to `https://www.strava.com/oauth/token`

**Oura:**
1. Go to [cloud.ouraring.com/personal-access-tokens](https://cloud.ouraring.com/personal-access-tokens)
2. Create a personal access token (no OAuth needed)

**Anthropic:**
1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key

### 4. Install and run

```bash
# Clone / download this project
cd marathon-bot

# Copy env file and fill in your values
cp .env.example .env
nano .env

# Install dependencies
pip install -r requirements.txt

# Run initial data sync
python src/sync_strava.py
python src/sync_oura.py

# Start the bot
python src/bot.py
```

### 5. Set up sync cron jobs

```bash
# Strava — every hour
0 * * * * cd /path/to/marathon-bot && python src/sync_strava.py

# Oura — every morning at 8:30am
30 8 * * * cd /path/to/marathon-bot && python src/sync_oura.py
```

## Bot Commands

| Command | What it does |
|---|---|
| `/start` | Welcome message + command list |
| `/summary` | Weekly training load overview |
| `/readiness` | Today's recovery status based on HRV + sleep |
| `/plan` | Upcoming workouts this week |
| `/clear` | Reset conversation history |
| Any message | Free-form coaching chat with Claude |

## Example conversations

> **You:** How did my long run on Sunday compare to last week?

> **Coach:** Your Sunday long run was 28km at 5:42/km avg, HR 148bpm — a solid effort. Last Sunday was 24km at 5:38/km, HR 144bpm. You covered 4km more at a slightly higher effort level, which is appropriate progression at this stage. Your suffer score was 187 vs 142 last week — make sure Monday stays genuinely easy.

---

> **You:** My HRV is low today, should I do my tempo?

> **Coach:** Your HRV dropped to 38ms today (your 7-day avg is 54ms) and your readiness score is 62. I'd recommend shifting today's 8km tempo to an easy 45-min recovery run at Zone 2. You have a key long run on Sunday — better to absorb last week's load than push through a hard session on a compromised day.

## Deploying to production

For always-on hosting, deploy to:
- **Railway** — easiest, connect GitHub repo, add env vars, done
- **Render** — free tier available, similar to Railway
- **Fly.io** — more control, still simple

The bot uses long-polling (`run_polling()`), so no webhook setup needed.

## Adding Garmin and Final Surge

See `src/sync_strava.py` as a template. Both platforms have REST APIs:
- **Garmin Health API** — requires developer registration at [developer.garmin.com](https://developer.garmin.com)
- **Final Surge** — contact their team for API access or export CSV files and import manually
