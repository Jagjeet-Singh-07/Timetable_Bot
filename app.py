
import os
import logging
import json
import time
import asyncio
from datetime import datetime, timedelta
from threading import Thread
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import pytz
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError
from flask import Flask

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Config from environment or config file
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TZ = os.getenv("TZ", "Asia/Kolkata")

if not BOT_TOKEN or not CHAT_ID:
    logging.error("BOT_TOKEN and CHAT_ID must be set as environment variables.")
    raise SystemExit("Missing BOT_TOKEN or CHAT_ID")

CHAT_ID = int(CHAT_ID)
tz = pytz.timezone(TZ)

# Load timetable file (same folder)
base_dir = os.path.dirname(__file__)
with open(os.path.join(base_dir, "timetable.json"), "r", encoding="utf-8") as f:
    TIMETABLE = json.load(f)

scheduler = BackgroundScheduler(timezone=tz)

# Flask webserver for keeping bot alive
app = Flask('')

@app.route('/')
def home():
    return "🤖 Timetable Bot is alive! ✅"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# Global application instance
application = None

async def send_message_async(text):
    """Send message using async bot"""
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
        logging.info("Sent message: %s", text)
    except TelegramError as e:
        logging.error("TelegramError: %s", e)
    except Exception as e:
        logging.error("Unexpected error: %s", e)

def send_message(text):
    """Sync wrapper for sending messages"""
    asyncio.create_task(send_message_async(text))

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    current_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    today_name = datetime.now(tz).strftime("%A")
    classes_today = len(TIMETABLE.get(today_name, []))
    
    status_text = f"🤖 *Bot Status*\n\n✅ Bot is alive and running!\n⏰ Current time: {current_time}\n📅 Today: {today_name}\n📚 Classes today: {classes_today}"
    
    await update.message.reply_text(status_text, parse_mode="Markdown")
    logging.info("Status command executed by user %s", update.effective_user.id)

async def alive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alive command"""
    await update.message.reply_text("🟢 *Bot is alive!* ✅", parse_mode="Markdown")
    logging.info("Alive command executed by user %s", update.effective_user.id)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """
🤖 *Timetable Bot Commands*

/status - Check bot status and current info
/alive - Quick alive check
/help - Show this help message

The bot automatically sends notifications for your classes:
⏳ 10 minutes before class starts
🎯 When class starts
🕑 5 minutes before class ends
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")
    logging.info("Help command executed by user %s", update.effective_user.id)

async def start_telegram_bot():
    """Start the Telegram bot with proper async handling"""
    global application
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("alive", alive_command))
    application.add_handler(CommandHandler("help", help_command))
    
    logging.info("Telegram command handlers set up")
    
    # Initialize and start the application
    await application.initialize()
    await application.start()
    
    # Start polling
    logging.info("Starting Telegram bot polling...")
    await application.updater.start_polling(drop_pending_updates=True)
    
    # Keep the bot running
    while True:
        await asyncio.sleep(1)

def run_telegram_bot():
    """Run the Telegram bot in a separate thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_telegram_bot())
    except Exception as e:
        logging.error("Telegram bot error: %s", e)
    finally:
        loop.close()

def schedule_all_for_today():
    today_name = datetime.now(tz).strftime("%A")
    classes = TIMETABLE.get(today_name, [])
    now = datetime.now(tz)
    logging.info("Scheduling for %s — %d classes", today_name, len(classes))

    for idx, cls in enumerate(classes):
        subject = cls["subject"]
        start_time = datetime.strptime(cls["start"], "%H:%M").time()
        end_time = datetime.strptime(cls["end"], "%H:%M").time()

        start_dt = tz.localize(datetime.combine(now.date(), start_time))
        end_dt = tz.localize(datetime.combine(now.date(), end_time))

        # compute times
        t_before_10 = start_dt - timedelta(minutes=10)
        t_start = start_dt
        t_before_end_5 = end_dt - timedelta(minutes=5)

        # next class info
        if idx + 1 < len(classes):
            next_cls = classes[idx + 1]
            next_text = f"Next: *{next_cls['subject']}* at {next_cls['start']}"
        else:
            next_text = "No more classes today 🎉"

        # create unique job ids
        jid1 = f"{today_name}-{subject}-10min"
        jid2 = f"{today_name}-{subject}-start"
        jid3 = f"{today_name}-{subject}-5end"

        # only schedule if in future (today)
        if t_before_10 > now:
            scheduler.add_job(send_message, trigger=DateTrigger(run_date=t_before_10),
                              args=[f"⏳ *Next in 10 min*: *{subject}* ({cls['start']} – {cls['end']})"],
                              id=jid1, replace_existing=True)
            logging.info("Scheduled 10min before for %s at %s", subject, t_before_10.isoformat())

        if t_start > now:
            scheduler.add_job(send_message, trigger=DateTrigger(run_date=t_start),
                              args=[f"🎯 *Now starting*: *{subject}* ({cls['start']} – {cls['end']})"],
                              id=jid2, replace_existing=True)
            logging.info("Scheduled start for %s at %s", subject, t_start.isoformat())

        if t_before_end_5 > now:
            scheduler.add_job(send_message, trigger=DateTrigger(run_date=t_before_end_5),
                              args=[f"🕑 *5 min left*: *{subject}* (ends at {cls['end']}).\n{next_text}"],
                              id=jid3, replace_existing=True)
            logging.info("Scheduled 5min-before-end for %s at %s", subject, t_before_end_5.isoformat())

def schedule_midnight_job():
    tomorrow = (datetime.now(tz) + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
    scheduler.add_job(schedule_all_for_today, trigger=DateTrigger(run_date=tomorrow),
                      id="schedule_tomorrow", replace_existing=True)
    logging.info("Scheduled next-day scheduler at %s", tomorrow.isoformat())

def startup_schedule():
    schedule_all_for_today()
    schedule_midnight_job()

async def send_test_message():
    """Send a test message to verify the bot is working"""
    test_text = "🤖 *Test Message*\n\nTimetable Bot is working correctly! ✅\n\nTry these commands:\n/alive - Check if bot is alive\n/status - Get detailed status\n/help - Show help"
    await send_message_async(test_text)

def main():
    logging.info("Starting Timetable Bot")
    
    # Start Flask webserver in background
    keep_alive()
    logging.info("Webserver started on port 8080")
    
    # Start scheduler
    scheduler.start()
    logging.info("Scheduler started")
    
    # Send test message
    asyncio.run(send_test_message())
    
    # Schedule today's classes
    startup_schedule()
    
    # Start Telegram bot in a separate thread
    bot_thread = Thread(target=run_telegram_bot)
    bot_thread.daemon = True
    bot_thread.start()
    logging.info("Telegram bot thread started")
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(30)
    except (KeyboardInterrupt, SystemExit):
        logging.info("Shutting down...")
        if application:
            asyncio.run(application.stop())
            asyncio.run(application.shutdown())
        scheduler.shutdown()

if __name__ == "__main__":
    main()
