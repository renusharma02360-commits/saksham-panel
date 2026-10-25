import os
import time
import threading
import requests
import urllib.parse
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from famgateway import FamGateway
from flask import Flask, request, render_template_string, redirect, url_for
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson.objectid import ObjectId

# ================== CONFIG ==================
# AAPKA NAYA TOKEN
BOT_TOKEN = "8807309763:AAF1-K9pqDHKomEXMbV_0xQI-KdshM6hQl8"
API_KEY   = "fam_4c308a3f58df8f752e41770178d877982e4e1a58"
ADMIN_ID  = 7778093775
ADMIN_WP  = "919306606011" 
MONGO_URI = os.environ.get("MONGO_URI") 
UPLOAD_FOLDER = "static/uploads"

RESELLER_API_URL = "https://bantibhaiya.to/api/reseller_v1.php"
RESELLER_API_KEY = "e5990b638beaa7b2335373200b39c93f"
MASTER_KEY       = "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"
# ============================================

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- MongoDB Setup ---
client = MongoClient(MONGO_URI)
db = client.saksham_panel
users_col = db.users
products_col = db.products
orders_col = db.orders
settings_col = db.settings

bot = telebot.TeleBot(BOT_TOKEN)
fg  = FamGateway(api_key=API_KEY)
calc_data = {}
user_msg_history = {} 

# ---------------- DB HELPERS ----------------
def get_settings():
    s = settings_col.find_one({"_id": "global"})
    if not s:
        default_s = {"_id": "global", "store_name": "SAKSHAM STORE", "support_username": "Saksham_sharma89", "update_link": "https://t.me/", "maintenance": "false", "reseller_price": 149, "reseller_discount": 40}
        settings_col.insert_one(default_s)
        return default_s
    return s

def save_settings(updates):
    settings_col.update_one({"_id": "global"}, {"$set": updates}, upsert=True)

def get_user_info(uid):
    u = users_col.find_one({"_id": str(uid)})
    if not u:
        default_u = {"_id": str(uid), "balance": 0.0, "name": "User", "discount": 0}
        users_col.insert_one(default_u)
        return default_u
    return u

def get_balance(uid):
    return get_user_info(uid).get("balance", 0.0)

def get_discount(uid):
    return get_user_info(uid).get("discount", 0)

def credit_balance(uid, amount):
    users_col.update_one({"_id": str(uid)}, {"$inc": {"balance": amount}}, upsert=True)
    return get_balance(uid)

def deduct_balance(uid, amount):
    result = users_col.find_one_and_update(
        {"_id": str(uid), "balance": {"$gte": amount}},
        {"$inc": {"balance": -amount}}
    )
    return result is not None

def credit_atomic(uid, amount, utr):
    if orders_col.find_one({"utr": utr}):
        return False, get_balance(uid)
    orders_col.insert_one({"utr": utr, "uid": str(uid), "amount": amount, "time": time.strftime("%d-%m-%Y %I:%M %p")})
    return True, credit_balance(uid, amount)

def log_order(uid, product, key, price):
    orders_col.insert_one({"uid": str(uid), "product": product, "key": key, "price": price, "time": time.strftime("%d-%m-%Y %I:%M %p")})

# ---------------- UI HELPERS ----------------
def clean_old_messages(chat_id):
    if chat_id in user_msg_history:
        for msg_id in user_msg_history[chat_id]:
            try: bot.delete_message(chat_id, msg_id)
            except: pass
        user_msg_history[chat_id] = []

def send_menu(chat_id, text, reply_markup):
    clean_old_messages(chat_id)
    msg = bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)
    user_msg_history[chat_id] = [msg.message_id]

def safe_edit(chat_id, message_id, text, reply_markup=None):
    try:
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        if "message is not modified" in str(e).lower(): pass
        else:
            try: bot.delete_message(chat_id, message_id)
            except: pass
            msg = bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)
            if chat_id not in user_msg_history: user_msg_history[chat_id] = []
            user_msg_history[chat_id].append(msg.message_id)

# ================== MAIN MENU ==================
def get_main_menu(uid, name):
    bal = get_balance(uid)
    discount = get_discount(uid)
    settings = get_settings()
    support_user = settings.get('support_username', 'YourSupport').replace('@', '')
    
    if discount > 0:
        header = f"👑 <b>WELCOME, {name}</b>\n━━━━━━━━━━━━━━━━━━━━\n⚡ <b>RESELLER ACCOUNT</b> | 🏷️ {discount}% OFF\n💳 <b>Wallet:</b> ₹{bal:.2f}\n━━━━━━━━━━━━━━━━━━━━"
    else:
        header = f"✨ <b>WELCOME, {name}</b>\n━━━━━━━━━━━━━━━━━━━━\n💳 <b>Wallet:</b> ₹{bal:.2f}\n━━━━━━━━━━━━━━━━━━━━"
    
    text = f"{header}\n\n🛒 <b>Buy Now:</b> Premium Keys\n💰 <b>Add Balance:</b> UPI Auto-Verify\n⚙️ <b>My Profile:</b> History & Keys\n🛟 <b>Support:</b> 24/7 Help\n━━━━━━━━━━━━━━━━━━━━\n👇 <i>Choose an option below:</i>"
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🛒 Shop", callback_data="menu_shop"), InlineKeyboardButton("📢 Updates", url=settings.get('update_link', 'https://t.me/')))
    kb.add(InlineKeyboardButton("💰 Wallet", callback_data="menu_addfund"), InlineKeyboardButton("👤 Profile", callback_data="menu_balance"))
    
    if discount == 0:
        reseller_price = settings.get("reseller_price", 149)
        kb.add(InlineKeyboardButton(f"👑 Buy Reseller (₹{reseller_price})", callback_data="buy_reseller"))
        
    kb.add(InlineKeyboardButton("🛟 Support", url=f"https://t.me/{support_user}"))
    return text, kb

@bot.message_handler(commands=["start"])
def start(msg):
    settings = get_settings()
    if settings.get("maintenance", "false") == "true" and str(msg.from_user.id) != str(ADMIN_ID):
        bot.reply_to(msg, "🚧 <b>Bot is currently under maintenance.</b>", parse_mode="HTML")
        return
    
    get_user_info(msg.from_user.id)
    text, kb = get_main_menu(msg.from_user.id, msg.from_user.first_name)
    send_menu(msg.chat.id, text, kb)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    uid, data, name = call.from_user.id, call.data, call.from_user.first_name
    msg_id, chat_id = call.message.message_id, call.message.chat.id
    settings = get_settings()
    bot.answer_callback_query(call.id)
    
    if settings.get("maintenance", "false") == "true" and str(uid) != str(ADMIN_ID):
        return

    try:
        if data == "menu_back":
            text, kb = get_main_menu(uid, name)
            safe_edit(chat_id, msg_id, text, kb)
            
        elif data == "menu_balance":
            bal, discount = get_balance(uid), get_discount(uid)
            user_orders = list(orders_col.find({"uid": str(uid)}).sort("_id", -1).limit(5))
            text = f"👤 <b>MY PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━\n🆔 <b>ID:</b> <code>{uid}</code>\n💵 <b>Balance:</b> ₹{bal:.2f}\n"
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back"))
            safe_edit(chat_id, msg_id, text, kb)
            
        elif data == "menu_addfund":
            text = f"💸 <b>ADD BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━\nSelect amount:"
            kb = InlineKeyboardMarkup(row_width=3).add(InlineKeyboardButton("₹10", callback_data="amt_10"), InlineKeyboardButton("₹50", callback_data="amt_50"), InlineKeyboardButton("₹100", callback_data="amt_100")).add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
            safe_edit(chat_id, msg_id, text, kb)
            
        elif data.startswith("amt_"):
            amount = float(data.split("_")[1])
            safe_edit(chat_id, msg_id, f"⚡ <i>Generating UPI for ₹{amount}...</i>")
            generate_wallet_qr(chat_id, uid, amount, name)
            
        elif data == "menu_shop":
            products = list(products_col.find({}))
            if not products:
                safe_edit(chat_id, msg_id, "🛒 <b>Store is empty!</b>", InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="menu_back")))
                return
            text = f"🛒 <b>STORE</b>\n━━━━━━━━━━━━━━━━━━━━\n👇 Select a product:"
            kb = InlineKeyboardMarkup(row_width=1)
            for p in products:
                kb.add(InlineKeyboardButton(f"📦 {p['name']}", callback_data=f"view_{str(p['_id'])}"))
            kb.add(InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back"))
            safe_edit(chat_id, msg_id, text, kb)
            
    except Exception as e: print(f"Callback Error: {e}")

# ================== WALLET ADD FUND ==================
def generate_wallet_qr(chat_id, uid, amount, name):
    try: order = fg.create_order(amount=amount, customer_name=name or "User")
    except Exception as e:
        bot.send_message(chat_id, f"❌ <b>API Error:</b> <code>{str(e)}</code>", parse_mode="HTML")
        return
    uid = str(uid)
    caption = f"💳 <b>ADD BALANCE</b>\n🆔 <b>Order ID:</b> <code>{order.order_id}</code>\n💵 <b>Amount:</b> ₹{float(order.payable_amount):.2f}\n\n📲 <i>Scan to pay.</i>"
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Cancel", callback_data="cancel_qr_back"))
    sent_photo = bot.send_photo(chat_id, photo=order.qr_url, caption=caption, parse_mode="HTML", reply_markup=kb)
    sent_wait = bot.send_message(chat_id, f"🔄 <b>Waiting for Payment...</b>", parse_mode="HTML")
    threading.Thread(target=poll_wallet_status, args=(order.order_id, uid, chat_id, sent_wait.message_id, sent_photo.message_id, amount), daemon=True).start()

def poll_wallet_status(order_id, uid, chat_id, wait_msg_id, photo_msg_id, amount):
    start_ts = time.time()
    while time.time() - start_ts < 360:
        time.sleep(2)
        try: status = fg.get_status(order_id)
        except: continue
        if status.is_paid:
            ok, new_bal = credit_atomic(uid, amount, status.utr)
            try: bot.delete_message(chat_id=chat_id, message_id=wait_msg_id)
            except: pass
            try: bot.delete_message(chat_id=chat_id, message_id=photo_msg_id)
            except: pass
            text, kb = get_main_menu(uid, "User")
            send_menu(chat_id, f"✅ <b>PAYMENT SUCCESSFUL</b>\n💵 <b>Added:</b> ₹{amount:.2f}\n💼 <b>New Balance:</b> ₹{new_bal:.2f}", kb)
            return
        if status.is_expired:
            try: bot.delete_message(chat_id=chat_id, message_id=wait_msg_id)
            except: pass
            return

# ================== FLASK WEB SERVER (WEB PANEL) ==================
app = Flask(__name__)

# Aapka Admin Panel HTML (Design wahi rakha hai jo aapke screenshot mein tha)
ADMIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Saksham Panel Admin</title>
    <style>
        body { font-family: Arial, sans-serif; background-color: #0f172a; color: white; padding: 20px; }
        h1 { color: #38bdf8; text-align: center; }
        .container { max-width: 600px; margin: auto; }
        .btn-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px; }
        .btn { background: #1e293b; color: #38bdf8; padding: 15px; text-align: center; border-radius: 8px; text-decoration: none; display: block; border: 1px solid #334155; }
        .btn:hover { background: #334155; }
        .card { background: #1e293b; padding: 20px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #334155; }
        input { width: 100%; padding: 10px; margin: 5px 0 15px 0; background: #0f172a; border: 1px solid #334155; color: white; border-radius: 5px; box-sizing: border-box;}
        button { background: #0284c7; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; width: 100%;}
    </style>
</head>
<body>
    <div class="container">
        <h1>👑 Saksham Panel Admin</h1>
        <div class="btn-grid">
            <a href="/" class="btn">📦 Products</a>
            <a href="/" class="btn">👥 Users</a>
            <a href="/" class="btn">📜 History</a>
            <a href="/" class="btn">📢 Broadcast</a>
        </div>

        <div class="card">
            <h2>⚙️ Bot Settings</h2>
            <form method="POST" action="/settings">
                <label>Store Name</label>
                <input type="text" name="store_name" value="{{ settings.get('store_name', 'SAKSHAM STORE') }}">
                
                <label>Support Username</label>
                <input type="text" name="support_username" value="{{ settings.get('support_username', '') }}">
                
                <label>Update Link</label>
                <input type="text" name="update_link" value="{{ settings.get('update_link', '') }}">
                
                <label>Reseller Price (₹)</label>
                <input type="number" name="reseller_price" value="{{ settings.get('reseller_price', 149) }}">
                
                <button type="submit">Save Settings</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    settings = get_settings()
    return render_template_string(ADMIN_HTML, settings=settings)

@app.route('/settings', methods=['POST'])
def update_settings():
    updates = {
        "store_name": request.form.get("store_name"),
        "support_username": request.form.get("support_username"),
        "update_link": request.form.get("update_link"),
        "reseller_price": int(request.form.get("reseller_price", 149))
    }
    save_settings(updates)
    return redirect(url_for('home'))

def run_bot():
    print("Starting Telegram Bot...")
    try: bot.delete_webhook()
    except: pass
    bot.polling(none_stop=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
