"""
Marathon AI Coach — Telegram Bot
Pulls training data from Supabase, sends it as context to Claude,
and replies to your messages as a personal running coach.
"""

import os
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from anthropic import Anthropic
from supabase import create_client, Client
from dotenv import load_dotenv
import threading
import time
import base64

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s")
log = logging.getLogger(__name__)

# ── Clients ──────────────────────────────────────────────────────────────────

anthropic = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
supabase: Client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# Per-user conversation history (in-memory; swap for Redis in production)
conversation_history: dict[int, list] = {}

RACE_DATE = os.getenv("RACE_DATE", "2026-08-30")  # Sydney Marathon date

# ── Supabase data fetching ────────────────────────────────────────────────────

def fetch_recent_activities(days: int = 14) -> list[dict]:
    """Fetch workouts from the last N days."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    resp = (
        supabase.table("activities")
        .select("*")
        .gte("start_date", since)
        .order("start_date", desc=True)
        .limit(50)
        .execute()
    )
    return resp.data or []


def fetch_sleep_scores(days: int = 7) -> list[dict]:
    """Fetch Oura sleep/HRV scores from the last N days."""
    since = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    resp = (
        supabase.table("sleep_scores")
        .select("date, score, hrv_avg, rhr, readiness_score, deep_sleep_minutes, total_sleep_minutes")
        .gte("date", since)
        .order("date", desc=True)
        .execute()
    )
    return resp.data or []


def fetch_planned_workouts(days_ahead: int = 7) -> list[dict]:
    """Fetch upcoming planned workouts from Final Surge."""
    today = datetime.utcnow().date().isoformat()
    future = (datetime.utcnow() + timedelta(days=days_ahead)).date().isoformat()
    resp = (
        supabase.table("planned_workouts")
        .select("*")
        .gte("planned_date", today)
        .lte("planned_date", future)
        .order("planned_date")
        .execute()
    )
    return resp.data or []


def fetch_weekly_summary() -> dict:
    """Compute rolling 7-day training load summary."""
    since = (datetime.utcnow() - timedelta(days=7)).isoformat()
    resp = (
        supabase.table("activities")
        .select("distance_km, duration_seconds, sport_type, average_heartrate, suffer_score")
        .gte("start_date", since)
        .execute()
    )
    acts = resp.data or []
    total_km = sum(a.get("distance_km", 0) for a in acts)
    total_mins = sum(a.get("duration_seconds", 0) for a in acts) / 60
    total_load = sum(a.get("suffer_score", 0) for a in acts)
    runs = [a for a in acts if a.get("sport_type") == "Run"]
    return {
        "total_activities": len(acts),
        "total_km": round(total_km, 1),
        "total_minutes": round(total_mins),
        "training_load": round(total_load),
        "run_count": len(runs),
    }


# ── System prompt builder ────────────────────────────────────────────────────

def build_system_prompt() -> str:
    """Assemble a rich coaching context from live Supabase data."""
    activities = fetch_recent_activities(30)
    sleep = fetch_sleep_scores(30)
    planned = fetch_planned_workouts(60)
    weekly = fetch_weekly_summary()

    days_to_race = (datetime.strptime(RACE_DATE, "%Y-%m-%d") - datetime.utcnow()).days
    today_str = datetime.utcnow().strftime("%B %d, %Y")

    acts_text = "\n".join(
        f"  • {a.get('start_date','')[:10]} | {a.get('sport_type','')} | "
        f"{a.get('distance_km', 0):.1f}km | {int(a.get('duration_seconds',0)//60)}min | "
        f"HR avg {a.get('average_heartrate','—')} | Load {a.get('suffer_score','—')}"
        for a in activities
    ) or "  No activities recorded."

    sleep_text = "\n".join(
        f"  • {s.get('date','')} | Sleep score {s.get('score','—')} | "
        f"HRV {s.get('hrv_avg','—')}ms | RHR {s.get('rhr','—')}bpm | "
        f"Readiness {s.get('readiness_score','—')} | "
        f"Deep {s.get('deep_sleep_minutes','—')}min / {s.get('total_sleep_minutes','—')}min total"
        for s in sleep
    ) or "  No sleep data."

    planned_text = "\n".join(
        f"  • {p.get('planned_date','')} | {p.get('workout_type','')} | "
        f"{p.get('description','')}"
        for p in planned
    ) or "  No planned workouts this week."

    return f"""You are an elite marathon running coach specialising in personalised training for the Sydney Marathon.
You have direct access to the athlete's live training data pulled from Strava, Garmin, Oura, and Final Surge.

ATHLETE PROFILE
───────────────
CRITICAL DATE INFORMATION — DO NOT GUESS OR CALCULATE:
Today is exactly: {today_str} ({datetime.utcnow().strftime("%A")})
Current year: {datetime.utcnow().year}
Race: Sydney Marathon ({RACE_DATE})
Days to race: {days_to_race}

RULES:
- NEVER guess what day of the week a date falls on — calculate it from the date itself
- ALWAYS use {today_str} as today's date, not your training data
- If unsure of the day of week, say the date only (e.g. "April 25") not the day name

LAST 7 DAYS — TRAINING SUMMARY
───────────────────────────────
Activities: {weekly['total_activities']} | Total km: {weekly['total_km']} | Total time: {weekly['total_minutes']} min
Training load: {weekly['training_load']} | Runs: {weekly['run_count']}

LAST 14 DAYS — ACTIVITY LOG
────────────────────────────
{acts_text}

LAST 7 DAYS — SLEEP & RECOVERY (Oura)
──────────────────────────────────────
{sleep_text}

UPCOMING PLANNED WORKOUTS (Final Surge)
───────────────────────────────────────
{planned_text}

COACHING GUIDELINES
───────────────────
- Be direct, specific, and data-driven. Reference actual numbers from the athlete's data.
- Flag red flags: poor sleep before a hard session, HRV drop, overreaching.
- Adapt planned workouts based on readiness scores if relevant.
- Keep responses concise. Use bullet points for multi-part answers.
- Always consider the days-to-race figure when giving advice.
- If data is missing, say so and ask the athlete directly.
"""


# ── Claude chat ───────────────────────────────────────────────────────────────

def chat_with_claude(user_id: int, user_message: str) -> str:
    """Send message + history + live data context to Claude, return response."""
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    history = conversation_history[user_id]
    history.append({"role": "user", "content": user_message})

    # Keep last 20 turns to avoid token bloat
    if len(history) > 20:
        history = history[-20:]
        conversation_history[user_id] = history

    system_prompt = build_system_prompt()

    response = anthropic.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=system_prompt,
        messages=history,
    )

    reply = response.content[0].text
    history.append({"role": "assistant", "content": reply})
    return reply


# ── Telegram handlers ─────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👟 *Marathon Coach online!*\n\n"
        "I have access to your Strava, Garmin, Oura and Final Surge data.\n"
        "Ask me anything about your training — pacing, recovery, upcoming sessions.\n\n"
        "Commands:\n"
        "/summary — Weekly training snapshot\n"
        "/readiness — Today's recovery status\n"
        "/plan — This week's upcoming workouts\n"
        "/sync — Manually refresh all data\n"
        "/clear — Reset our conversation",
        parse_mode="Markdown",
    )

async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Syncing your data now... ⏳")
    try:
        from sync_strava import main as strava_sync
        strava_sync()
        await update.message.reply_text("✅ Strava synced!")
    except Exception as e:
        await update.message.reply_text(f"❌ Strava error: {e}")
    try:
        from sync_oura import main as oura_sync
        oura_sync()
        await update.message.reply_text("✅ Oura synced!")
    except Exception as e:
        await update.message.reply_text(f"❌ Oura error: {e}")

async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pulling your weekly data…")
    reply = chat_with_claude(
        update.effective_user.id,
        "Give me a concise summary of my training load and key metrics from the last 7 days. "
        "Flag anything I should pay attention to.",
    )
    await update.message.reply_text(reply)


async def cmd_readiness(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Checking your recovery status…")
    reply = chat_with_claude(
        update.effective_user.id,
        "Based on my sleep, HRV, and recent training load, how recovered am I today? "
        "Should I go ahead with today's planned session as-is, modify it, or rest?",
    )
    await update.message.reply_text(reply)


async def cmd_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Loading your upcoming workouts…")
    reply = chat_with_claude(
        update.effective_user.id,
        "What workouts do I have planned this week? Give me a brief overview and any coaching notes.",
    )
    await update.message.reply_text(reply)


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conversation_history.pop(update.effective_user.id, None)
    await update.message.reply_text("Conversation cleared. Fresh start! 🔄")


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    log.info(f"Message from {user_id}: {text[:80]}")

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        reply = chat_with_claude(user_id, text)
        await update.message.reply_text(reply)
    except Exception as e:
        log.error(f"Error: {e}")
        await update.message.reply_text("Something went wrong fetching your data. Try again in a moment.")

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Get highest resolution photo
    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    
    # Download photo as bytes
    import io
    photo_bytes = await file.download_as_bytearray()
    image_data = base64.standard_b64encode(bytes(photo_bytes)).decode("utf-8")

    # Get caption as the user's message, or use a default
    caption = update.message.caption or "What do you see in this image? Give me coaching feedback if relevant."

    # Add to conversation history with image
    if user_id not in conversation_history:
        conversation_history[user_id] = []
    
    history = conversation_history[user_id]
    history.append({
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_data,
                }
            },
            {
                "type": "text",
                "text": caption
            }
        ]
    })

    system_prompt = build_system_prompt()

    response = anthropic.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=system_prompt,
        messages=history,
    )

    reply = response.content[0].text
    history.append({"role": "assistant", "content": reply})

    await update.message.reply_text(reply)

# ── Entry point ───────────────────────────────────────────────────────────────

def sync_loop():
    """Run Strava and Oura sync on startup and every hour."""
    while True:
        try:
            from sync_strava import main as strava_sync
            strava_sync()
            log.info("Strava sync complete")
        except Exception as e:
            log.error(f"Strava sync error: {e}")
        try:
            from sync_oura import main as oura_sync
            oura_sync()
            log.info("Oura sync complete")
        except Exception as e:
            log.error(f"Oura sync error: {e}")
        time.sleep(3600)



def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("readiness", cmd_readiness))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    

    sync_thread = threading.Thread(target=sync_loop, daemon=True)
    sync_thread.start()
    log.info("Marathon Coach bot is running…")
    app.run_polling()


if __name__ == "__main__":
    main()
