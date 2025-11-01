import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import sqlite3
from datetime import datetime, timedelta
import os

TOKEN = os.environ.get("BOT_TOKEN")

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize database
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()

    # Table for tracking current streak and high score
    c.execute('''
        CREATE TABLE IF NOT EXISTS hidden_events
        (chat_id INTEGER PRIMARY KEY, last_hidden_time TIMESTAMP, high_score INTEGER DEFAULT 0)
    ''')

    # New table for tracking daily hide counts
    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_hides
        (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, hide_date DATE, hide_count INTEGER DEFAULT 1,
         UNIQUE(chat_id, hide_date))
    ''')

    # Table for tracking the maximum daily hides record
    c.execute('''
        CREATE TABLE IF NOT EXISTS max_daily_hides
        (chat_id INTEGER PRIMARY KEY, max_daily_count INTEGER DEFAULT 0, record_date DATE)
    ''')

    conn.commit()
    conn.close()

# Get days since last hidden event and high score
def get_days_and_highscore(chat_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('SELECT last_hidden_time, high_score FROM hidden_events WHERE chat_id = ?', (chat_id,))
    result = c.fetchone()
    conn.close()

    if result and result[0]:
        hidden_time = datetime.fromisoformat(result[0])
        current_time = datetime.now()
        days_passed = (current_time - hidden_time).days
        high_score = result[1] if result[1] else 0
        return days_passed, high_score
    return None, 0

# Get maximum daily hides count
def get_max_daily_hides(chat_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute('SELECT max_daily_count, record_date FROM max_daily_hides WHERE chat_id = ?', (chat_id,))
    result = c.fetchone()
    conn.close()

    if result:
        return result[0], result[1]
    return 0, None

# Update daily hide count and check for new record
def update_daily_hides(chat_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    today = datetime.now().date()

    # Get current daily count for today
    c.execute('''
        INSERT INTO daily_hides (chat_id, hide_date, hide_count)
        VALUES (?, ?, 1)
        ON CONFLICT(chat_id, hide_date) DO UPDATE SET
        hide_count = hide_count + 1
        RETURNING hide_count
    ''', (chat_id, today))

    result = c.fetchone()
    current_daily_count = result[0] if result else 1

    # Check if this is a new record
    current_max, record_date = get_max_daily_hides(chat_id)

    if current_daily_count > current_max:
        # Update the record
        c.execute('''
            INSERT OR REPLACE INTO max_daily_hides (chat_id, max_daily_count, record_date)
            VALUES (?, ?, ?)
        ''', (chat_id, current_daily_count, today))
        conn.commit()
        conn.close()
        return current_daily_count, True  # New record set

    conn.commit()
    conn.close()
    return current_daily_count, False  # No new record

# Save hidden event timestamp and update high score
def save_hidden_event(chat_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    current_time = datetime.now().isoformat()

    # First, get current days count before reset to check for new high score
    c.execute('SELECT last_hidden_time, high_score FROM hidden_events WHERE chat_id = ?', (chat_id,))
    result = c.fetchone()

    current_high_score = 0
    if result and result[1]:
        current_high_score = result[1]

    # Calculate days since last hidden event (this will be our candidate for new high score)
    new_candidate_score = 0
    if result and result[0]:
        last_hidden_time = datetime.fromisoformat(result[0])
        current_time_dt = datetime.now()
        new_candidate_score = (current_time_dt - last_hidden_time).days

    # Update high score if current streak is higher
    new_high_score = max(current_high_score, new_candidate_score)

    # Save the new hidden event with updated high score
    c.execute('''
        INSERT OR REPLACE INTO hidden_events (chat_id, last_hidden_time, high_score)
        VALUES (?, ?, ?)
    ''', (chat_id, current_time, new_high_score))
    conn.commit()
    conn.close()
    return current_time

# Get today's hide count
def get_todays_hides(chat_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    today = datetime.now().date()

    c.execute('SELECT hide_count FROM daily_hides WHERE chat_id = ? AND hide_date = ?', (chat_id, today))
    result = c.fetchone()
    conn.close()

    return result[0] if result else 0

# Start command handler
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "i count how long it has been since someone in the chat accidentally hid the general topic.\n"
        "type /dayssince to check the current count and high score\n"
        "type /records to see all records\n"
        "i only work in groupchats!"
    )

# Days since command handler
async def days_since_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    days, high_score = get_days_and_highscore(chat_id)
    max_daily_hides, record_date = get_max_daily_hides(chat_id)

    if days is None:
        await update.message.reply_text("either general hasnt been hidden since i started tracking, or im not in a groupchat.")
    else:
        message = f"days since general got hidden: {days}\nhighscore: {high_score}"
        if max_daily_hides > 0:
            if record_date:
                record_date_str = record_date if isinstance(record_date, str) else record_date.strftime('%Y/%m/%d')
                message += f"\nmost hides in a day: {max_daily_hides} (on {record_date_str})"
            else:
                message += f"\nmost hides in a day: {max_daily_hides}"
        await update.message.reply_text(message)

# Records command handler
async def records_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    days, high_score = get_days_and_highscore(chat_id)
    max_daily_hides, record_date = get_max_daily_hides(chat_id)
    todays_hides = get_todays_hides(chat_id)

    message = "RECORDS\n"

    if high_score > 0:
        message += f"longest streak: {high_score} days\n"
    else:
        message += "longest streak: 0\n"

    if max_daily_hides > 0:
        if record_date:
            record_date_str = record_date if isinstance(record_date, str) else record_date.strftime('%Y/%m/%d')
            message += f"most hides in a day: {max_daily_hides} (on {record_date_str})\n"
        else:
            message += f"most hides in a day: {max_daily_hides}\n"
    else:
        message += "most hides in a day: 0\n"

    message += f"hides today: {todays_hides}"

    await update.message.reply_text(message)

# Handle GeneralForumTopicHidden service messages
async def handle_general_topic_hidden(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message

        # Check if this is a GeneralForumTopicHidden service message
        if hasattr(message, 'general_forum_topic_hidden') and message.general_forum_topic_hidden:
            chat_id = message.chat_id

            # Get current days count before reset to check for new high score
            days_before_reset, current_high_score = get_days_and_highscore(chat_id)

            # Save the event with current timestamp (this updates high score if needed)
            save_hidden_event(chat_id)

            # Update daily hide count and check for record
            current_daily_count, new_daily_record = update_daily_hides(chat_id)

            # Get updated high score
            _, new_high_score = get_days_and_highscore(chat_id)

            # Get the message thread ID (topic ID) to reply in the correct topic
            message_thread_id = getattr(message, 'message_thread_id', None)

            # Build response message
            if days_before_reset and days_before_reset > current_high_score:
                reply_text = f"days since general got hidden: 0 🎉\nNEW HIGH SCORE! {days_before_reset} days! 🏆"
            else:
                reply_text = f"days since general got hidden: 0 🎉\nhighscore: {new_high_score}"

            # Add daily hide info
            if new_daily_record:
                reply_text += f"\nNEW DAILY RECORD! {current_daily_count} hides today!"
            else:
                reply_text += f"\nhides today: {current_daily_count}"

            if message_thread_id:
                # Reply in the specific topic
                await context.bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    text=reply_text
                )
            else:
                # Fallback: reply to the message
                await message.reply_text(reply_text)

            logger.info(f"general topic hidden event recorded for chat {chat_id}. high score: {new_high_score}, daily hides: {current_daily_count}")

    except Exception as e:
        logger.error(f"error handling GeneralForumTopicHidden: {e}")

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"exception while handling an update: {context.error}")

def main():
    # Initialize database
    init_db()

    # Create application
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("dayssince", days_since_command))
    application.add_handler(CommandHandler("records", records_command))

    # Handle GeneralForumTopicHidden service messages
    application.add_handler(MessageHandler(
        filters.StatusUpdate.GENERAL_FORUM_TOPIC_HIDDEN,
        handle_general_topic_hidden
    ))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start the bot
    print("bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    main()
