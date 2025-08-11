import os
import logging
import json
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import pytz
from telegram import Bot
from telegram.error import TelegramError

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
bot = Bot(token=BOT_TOKEN)
tz = pytz.timezone(TZ)

# Load timetable file (same folder)
base_dir = os.path.dirname(__file__)
with open(os.path.join(base_dir, "timetable.json"), "r", encoding="utf-8") as f:
    TIMETABLE = json.load(f)

scheduler = BackgroundScheduler(timezone=tz)

def send_message(text):
    try:
        bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
        logging.info("Sent message: %s", text)
    except TelegramError as e:
        logging.error("TelegramError: %s", e)

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

if __name__ == "__main__":
    logging.info("Starting Timetable Bot")
    scheduler.start()
    startup_schedule()
    try:
        while True:
            time.sleep(30)
    except (KeyboardInterrupt, SystemExit):
        logging.info("Shutting down scheduler...")
        scheduler.shutdown()