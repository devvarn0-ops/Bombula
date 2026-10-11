
import telebot
import requests
import os
from telebot import types

# --- CONFIG ---
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ADMIN_CHAT_ID = int(os.environ.get('ADMIN_CHAT_ID', '0'))

# Ye hai tera Firebase Database ka URL (Jo tumhe project settings se milta hai)
# Example: https://my-project-id.firebaseio.com/
FIREBASE_URL = os.environ.get('FIREBASE_URL', 'https://your-project-id.firebaseio.com/')

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    kb = types.InlineKeyboardMarkup()
    btn_join = types.InlineKeyboardButton("Join Channel", url="https://t.me/YourChannel")
    kb.add(btn_join)
    bot.reply_to(message, "👋 Welcome! Use /fetch to get latest SMS.", reply_markup=kb)

@bot.message_handler(commands=['fetch'])
def fetch_sms(message):
    try:
        # Seedha GET request bhejo Firebase ko
        response = requests.get(FIREBASE_URL + ".json")
        
        if response.status_code == 200:
            data = response.json()
            
            # Agar data empty hai
            if not data:
                bot.reply_to(message, "❌ No SMS found in database.")
                return

            # Data format karo taaki Telegram pe dikhe
            output = "📱 <b>Latest SMS Data:</b>\n\n"
            for key, value in data.items():
                output += f"🔹 <b>{key}:</b> <code>{value}</code>\n\n"
            
            bot.reply_to(message, output, parse_mode='HTML')
            
        else:
            bot.reply_to(message, f"❌ Error: {response.status_code}")
            
    except Exception as e:
        bot.reply_to(message, f"Error fetching data: {str(e)}")

print("Bot is running...")
bot.infinity_polling()
