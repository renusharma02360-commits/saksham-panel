import os
import json
import time
import threading
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from famgateway import FamGateway
from flask import Flask, request, render_template_string, redirect, url_for
from werkzeug.utils import secure_filename

# ================== CONFIG ==================
BOT_TOKEN = "8807309763:AAEXX_0tVMslGImWCBkeKscBheg4io4gf6g"
API_KEY   = "fam_4c308a3f58df8f752e41770178d877982e4e1a58"
ADMIN_ID  = 7778093775
DB_FILE   = "wallet.json"
PRODUCTS_FILE = "products.json"
SETTINGS_FILE = "settings.json"
UPLOAD_FOLDER = "static/uploads"

RESELLER_API_URL = "https://bantibhaiya.to/api/reseller_v1.php"
RESELLER_API_KEY = "e5990b638beaa7b2335373200b39c93f"
MASTER_KEY       = "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"
# ============================================

# Ensure directories and files exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
for file, default in [(DB_FILE, {"users": {}, "utrs": [], "deposits": {}, "orders": []}), 
                      (PRODUCTS_FILE, {}), 
                      (SETTINGS_FILE, {"store_name": "SAKSHAM STORE", "support_username": "YourSupport", "update_link": "https://t.me/", "maintenance": "false"})]:
    if not os.path.exists(file):
        with open(file, "w") as f: json.dump(default, f)

# ================== BOT SETUP ==================
bot = telebot.TeleBot(BOT_TOKEN)
fg  = FamGateway(api_key=API_KEY)
lock = threading.Lock()
calc_data = {}

def safe_edit(chat_id, message_id, text, reply_markup=None):
    try:
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        err = str(e).lower()
        if "message is not modified" in err: pass
        elif "there is no text in the message to edit" in err:
            try: bot.delete_message(chat_id, message_id)
            except: pass
            bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)

def is_maintenance():
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f).get("maintenance", "false") == "true"

def load_db():
    with open(DB_FILE, "r") as f: return json.load(f)

def save_db(db):
    with open(DB_FILE, "w") as f: json.dump(db, f, indent=2)

def get_user_info(uid):
    return load_db()["users"].get(str(uid), {"balance": 0.0, "name": "User", "discount": 0})

def get_balance(uid):
    with lock: return get_user_info(uid).get("balance", 0.0)

def get_discount(uid):
    with lock: return get_user_info(uid).get("discount", 0)

def deduct_balance(uid, amount):
    with lock:
        db = load_db()
        user = db["users"].get(str(uid))
        if user and user["balance"] >= amount:
            user["balance"] = round(user["balance"] - amount, 2)
            save_db(db)
            return True
        return False

def credit_atomic(uid, amount, utr):
    with lock:
        db = load_db()
        if utr in db.get("utrs", []): return False, db["users"].get(str(uid), {}).get("balance", 0.0)
        db.setdefault("utrs", []).append(utr)
        u = db["users"].setdefault(str(uid), {"balance": 0.0, "name": "User", "discount": 0})
        u["balance"] = round(u["balance"] + float(amount), 2)
        save_db(db)
        return True, u["balance"]

def log_order(uid, product, key, price):
    with lock:
        db = load_db()
        db.setdefault("orders", []).append({"uid": str(uid), "product": product, "key": key, "price": price, "time": time.strftime("%d-%m-%Y %I:%M %p")})
        save_db(db)

def load_products():
    with open(PRODUCTS_FILE, "r") as f: return json.load(f)

def get_settings():
    with open(SETTINGS_FILE, "r") as f: return json.load(f)

def get_main_menu(uid, name):
    bal = get_balance(uid)
    discount = get_discount(uid)
    settings = get_settings()
    support_user = settings.get('support_username', 'YourSupport').replace('@', '')
    reseller_tag = " 👑 <b>[RESELLER]</b>" if discount > 0 else ""
    
    text = (f"<b>✨ WELCOME TO {settings['store_name']} ✨</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 <b>Hello, {name}</b>{reseller_tag}\n💳 <b>Wallet:</b> ₹{bal:.2f}\n━━━━━━━━━━━━━━━━━━━━\n⚡ <i>100% Trusted & Instant Delivery</i>\n\n🛒 <b>Buy Now:</b> Premium Keys\n💰 <b>Add Balance:</b> UPI Auto-Verify\n⚙️ <b>My Profile:</b> History & Keys\n━━━━━━━━━━━━━━━━━━━━\n👇 <i>Select an option below:</i>")
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🛒 Buy Now", callback_data="menu_shop"), InlineKeyboardButton("📢 Updates", url=settings.get('update_link', 'https://t.me/')))
    kb.add(InlineKeyboardButton("💸 Add Balance", callback_data="menu_addfund"), InlineKeyboardButton("👤 My Profile", callback_data="menu_balance"))
    kb.add(InlineKeyboardButton("🛟 Support", url=f"https://t.me/{support_user}"))
    return text, kb

@bot.message_handler(commands=["start"])
def start(msg):
    if is_maintenance() and str(msg.from_user.id) != str(ADMIN_ID):
        bot.reply_to(msg, "🚧 <b>Bot is currently under maintenance.</b>\n\n<i>Please try again later.</i>", parse_mode="HTML")
        return
    with lock:
        db = load_db()
        if str(msg.from_user.id) not in db["users"]:
            db["users"][str(msg.from_user.id)] = {"balance": 0.0, "name": msg.from_user.first_name, "discount": 0}
            save_db(db)
    text, kb = get_main_menu(msg.from_user.id, msg.from_user.first_name)
    bot.send_message(msg.chat.id, text, parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    uid, data, name = call.from_user.id, call.data, call.from_user.first_name
    msg_id, chat_id = call.message.message_id, call.message.chat.id
    if is_maintenance() and str(uid) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "🚧 Bot is currently under maintenance.", show_alert=True)
        return
    bot.answer_callback_query(call.id)

    try:
        if data == "menu_back":
            text, kb = get_main_menu(uid, name)
            safe_edit(chat_id, msg_id, text, kb)
        elif data == "menu_balance":
            bal, discount = get_balance(uid), get_discount(uid)
            db = load_db()
            user_orders = [o for o in db.get("orders", []) if o["uid"] == str(uid)][-5:]
            reseller_tag = "👑 <b>RESELLER ACCOUNT</b> (Prices are discounted!)\n" if discount > 0 else ""
            text = f"👤 <b>MY PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━\n{reseller_tag}🆔 <b>ID:</b> <code>{uid}</code>\n💵 <b>Balance:</b> ₹{bal:.2f}\n"
            if discount > 0: text += f"🏷️ <b>Your Discount:</b> {discount}% OFF\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n"
            kb = InlineKeyboardMarkup(row_width=1)
            if user_orders:
                text += "📜 <b>Recent Purchases:</b>\n\n"
                for i, o in enumerate(user_orders[::-1], 1):
                    text += f"{i}. <b>{o['product']}</b>\n   🔑 <code>{o['key']}</code>\n\n"
                    kb.add(InlineKeyboardButton(f"📋 Copy Key {i}", callback_data=f"copykey_{o['key']}"))
            else: text += "📭 <i>Aapne abhi tak kuch nahi kharida.</i>\n"
            kb.add(InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back"))
            safe_edit(chat_id, msg_id, text, kb)
        elif data == "menu_addfund":
            text = f"💸 <b>ADD BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━\nSelect amount or enter custom:"
            kb = InlineKeyboardMarkup(row_width=3).add(InlineKeyboardButton("₹10", callback_data="amt_10"), InlineKeyboardButton("₹50", callback_data="amt_50"), InlineKeyboardButton("₹100", callback_data="amt_100")).add(InlineKeyboardButton("🧮 Custom Amount", callback_data="amt_custom"), InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
            safe_edit(chat_id, msg_id, text, kb)
        elif data == "amt_custom":
            calc_data[uid] = ""
            show_calc(chat_id, msg_id, uid)
        elif data.startswith("calc_"):
            action = data.split("_")[1]
            current = calc_data.get(uid, "")
            if action == "cut": current = current[:-1]
            elif action == "ac": current = ""
            elif action == "done":
                if not current or float(current) < 5:
                    bot.answer_callback_query(call.id, "❌ Minimum amount ₹5 hai!", show_alert=True)
                    return
                safe_edit(chat_id, msg_id, f"⚡ <i>Generating Secure UPI QR for ₹{current}...</i>")
                generate_qr(chat_id, uid, float(current), name)
                if uid in calc_data: del calc_data[uid]
                return
            else:
                if len(current) < 5: current += action
            calc_data[uid] = current
            show_calc(chat_id, msg_id, uid)
        elif data.startswith("amt_"):
            amount = float(data.split("_")[1])
            safe_edit(chat_id, msg_id, f"⚡ <i>Generating Secure UPI QR for ₹{amount}...</i>")
            generate_qr(chat_id, uid, amount, name)
        elif data == "menu_shop":
            products = load_products()
            if not products:
                safe_edit(chat_id, msg_id, "🛒 <b>Store is empty!</b>", InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="menu_back")))
                return
            kb = InlineKeyboardMarkup(row_width=1)
            for p_id, p_info in products.items():
                kb.add(InlineKeyboardButton(f"📦 {p_info['name']}", callback_data=f"view_{p_id}"))
            kb.add(InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back"))
            safe_edit(chat_id, msg_id, "🛒 <b>STORE PRODUCTS</b>\n━━━━━━━━━━━━━━━━━━━━\nSelect a product to view:", kb)
        elif data.startswith("view_"):
            p_id = data.split("_")[1]
            product = load_products().get(p_id)
            discount = get_discount(uid)
            text = f"📦 <b>{product['name']}</b>\n━━━━━━━━━━━━━━━━━━━━\n👇 <i>Select Duration:</i>\n"
            if discount > 0: text += f"🏷️ <b>RESELLER PRICES ({discount}% OFF)</b>\n"
            kb = InlineKeyboardMarkup(row_width=2)
            row = []
            if product.get("video"): row.append(InlineKeyboardButton("📺 Video", url=product["video"]))
            if product.get("setup"): row.append(InlineKeyboardButton("⚙️ Setup Link", url=product["setup"]))
            if product.get("hack"): row.append(InlineKeyboardButton("🛠️ Hack Link", url=product["hack"]))
            if row: kb.add(*row)
            for dur, price in product["prices"].items():
                final_price = price - (price * discount / 100) if discount > 0 else price
                btn_text = f"⏱ {dur} - ₹{final_price:.2f}" + (" 👑" if discount > 0 else "")
                kb.add(InlineKeyboardButton(btn_text, callback_data=f"buy_{p_id}_{dur}"))
            kb.add(InlineKeyboardButton("🔙 Back to Shop", callback_data="menu_shop"))
            try: bot.delete_message(chat_id, msg_id)
            except: pass
            if product.get("image") and os.path.exists(product["image"]):
                with open(product["image"], "rb") as photo: bot.send_photo(chat_id, photo=photo, caption=text, parse_mode="HTML", reply_markup=kb)
            else: bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
        elif data.startswith("buy_"):
            parts = data.split("_", 2)
            p_id, duration = parts[1], parts[2]
            product = load_products().get(p_id)
            original_price = float(product["prices"].get(duration, 0))
            discount = get_discount(uid)
            final_price = original_price - (original_price * discount / 100) if discount > 0 else original_price
            bal = get_balance(uid)
            try: bot.delete_message(chat_id, msg_id)
            except: pass
            if bal < final_price:
                text = f"❌ <b>INSUFFICIENT BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━\nAapke paas sirf <b>₹{bal:.2f}</b> hain.\nIs product ke liye <b>₹{final_price:.2f}</b> chahiye."
                kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("💸 Add Balance", callback_data="menu_addfund"), InlineKeyboardButton("🔙 Back to Shop", callback_data="menu_shop"))
                bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
                return
            if product.get("is_v1"):
                msg = bot.send_message(chat_id, "📱 <b>Kripya apna Android ID bhejein:</b>", parse_mode="HTML")
                bot.register_next_step_handler(msg, process_android_id, p_id, duration, final_price)
            else:
                wait = bot.send_message(chat_id, "⚡ <i>Checking Stock & Generating Key...</i>", parse_mode="HTML")
                execute_api_buy(chat_id, wait.message_id, uid, p_id, duration, final_price, android_id=None)
        elif data.startswith("copykey_"):
            bot.answer_callback_query(call.id, f"✅ Key: {data.split('_', 1)[1]}\n\n(Touch to copy)", show_alert=True)
    except Exception as e: print(f"Callback Error: {e}")

def show_calc(chat_id, msg_id, uid):
    current = calc_data.get(uid, "")
    display = f"₹{current}" if current else "₹0"
    text = f"🧮 <b>SECURE CALCULATOR</b>\n━━━━━━━━━━━━━━━━━━━━\n💰 <b>Amount:</b> <code>{display}</code>\n⚠️ <b>Min Amount:</b> ₹5\n━━━━━━━━━━━━━━━━━━━━\n👇 <i>Neeche se amount type karein:</i>"
    kb = InlineKeyboardMarkup(row_width=3).add(InlineKeyboardButton("1", callback_data="calc_1"), InlineKeyboardButton("2", callback_data="calc_2"), InlineKeyboardButton("3", callback_data="calc_3"), InlineKeyboardButton("4", callback_data="calc_4"), InlineKeyboardButton("5", callback_data="calc_5"), InlineKeyboardButton("6", callback_data="calc_6"), InlineKeyboardButton("7", callback_data="calc_7"), InlineKeyboardButton("8", callback_data="calc_8"), InlineKeyboardButton("9", callback_data="calc_9"), InlineKeyboardButton("🧹 AC", callback_data="calc_ac"), InlineKeyboardButton("0", callback_data="calc_0"), InlineKeyboardButton("❌ X", callback_data="calc_cut")).add(InlineKeyboardButton("✅ Done / Pay", callback_data="calc_done")).add(InlineKeyboardButton("🔙 Back", callback_data="menu_addfund"))
    safe_edit(chat_id, msg_id, text, kb)

def generate_qr(chat_id, uid, amount, name, wait_msg=None):
    try: order = fg.create_order(amount=amount, customer_name=name or "User")
    except Exception as e:
        if wait_msg: bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
        bot.send_message(chat_id, f"❌ <b>API Error:</b> <code>{str(e)}</code>", parse_mode="HTML")
        return
    uid = str(uid)
    with lock:
        db = load_db()
        db.setdefault("deposits", {}).setdefault(uid, []).append({"order_id": order.order_id, "amount": amount, "status": "pending"})
        save_db(db)
    caption = f"💳 <b>PAYMENT REQUEST</b>\n━━━━━━━━━━━━━━━━━━━━\n🆔 <b>Order ID:</b> <code>{order.order_id}</code>\n💵 <b>Amount:</b> ₹{float(order.payable_amount):.2f}\n━━━━━━━━━━━━━━━━━━━━\n\n📲 <i>Scan the QR above to pay.</i>\n✅ <b>Auto-verify ON</b>"
    if wait_msg: bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
    sent_photo = bot.send_photo(chat_id, photo=order.qr_url, caption=caption, parse_mode="HTML")
    sent_wait = bot.send_message(chat_id, f"🔄 <b>Redirecting...</b>\n━━━━━━━━━━━━━━━━━━━━\n<i>Please wait, payment confirm ho rahi hai...</i>", parse_mode="HTML")
    threading.Thread(target=poll_status, args=(order.order_id, uid, chat_id, sent_wait.message_id, sent_photo.message_id, amount), daemon=True).start()

def poll_status(order_id, uid, chat_id, wait_msg_id, photo_msg_id, amount):
    start_ts = time.time()
    frames = ["🎲 <b>Connecting...</b>", "🔄 <b>Checking Bank...</b>", "⏳ <b>Verifying...</b>", "⚡ <b>Almost Done...</b>"]
    idx = 0
    while time.time() - start_ts < 360:
        time.sleep(2)
        try:
            idx = (idx + 1) % len(frames)
            bot.edit_message_text(f"{frames[idx]}\n━━━━━━━━━━━━━━━━━━━━\n<i>Please wait...</i>", chat_id=chat_id, message_id=wait_msg_id, parse_mode="HTML")
        except: pass
        try: status = fg.get_status(order_id)
        except: continue
        if status.is_paid:
            ok, new_bal = credit_atomic(uid, amount, status.utr)
            try: bot.delete_message(chat_id=chat_id, message_id=wait_msg_id)
            except: pass
            try: bot.delete_message(chat_id=chat_id, message_id=photo_msg_id)
            except: pass
            bot.send_message(chat_id, f"✅ <b>PAYMENT SUCCESSFUL</b>\n💵 <b>Added:</b> ₹{amount:.2f}\n🏦 <b>UTR:</b> <code>{status.utr}</code>\n💼 <b>New Balance:</b> ₹{new_bal:.2f}", parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Menu", callback_data="menu_back")))
            return
        if status.is_expired:
            try: bot.delete_message(chat_id=chat_id, message_id=wait_msg_id)
            except: pass
            try: bot.delete_message(chat_id=chat_id, message_id=photo_msg_id)
            except: pass
            bot.send_message(chat_id, f"⌛ <b>Order Expired.</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Menu", callback_data="menu_back")))
            return

def process_android_id(msg, p_id, duration, price):
    android_id = msg.text.strip()
    if len(android_id) < 10: return bot.reply_to(msg, "❌ <b>Invalid Android ID!</b>", parse_mode="HTML")
    wait = bot.reply_to(msg, "⏳ <i>Checking Stock & Generating Key...</i>", parse_mode="HTML")
    execute_api_buy(msg.chat.id, wait.message_id, msg.from_user.id, p_id, duration, price, android_id=android_id)

def execute_api_buy(chat_id, msg_id, uid, p_id, duration, price, android_id=None):
    product = load_products()[p_id]
    data = {'api_key': RESELLER_API_KEY, 'action': 'buy', 'product_id': product["pid"], 'duration': duration, 'quantity': 1}
    if android_id: data['android_id'] = android_id
    headers = {'Content-Type': 'application/x-www-form-urlencoded', 'x-master-key': MASTER_KEY}
    try: result = requests.post(RESELLER_API_URL, data=data, headers=headers, timeout=20).json()
    except: result = {"status": "error", "message": "Network Error"}
    if result.get("status") == "success" or "keys" in result:
        if deduct_balance(uid, price):
            keys = result.get("keys", ["Key not found"])
            new_bal = get_balance(uid)
            log_order(uid, product['name'], keys[0], price)
            kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("📋 Copy Key", callback_data=f"copykey_{keys[0]}"), InlineKeyboardButton("🔙 Menu", callback_data="menu_back"))
            safe_edit(chat_id, msg_id, f"✅ <b>PURCHASE SUCCESSFUL</b>\n📦 <b>Product:</b> {product['name']}\n⏱ <b>Duration:</b> {duration}\n💵 <b>Price:</b> ₹{price:.2f}\n🔑 <b>Key:</b>\n<code>{keys[0]}</code>\n💼 <b>New Balance:</b> ₹{new_bal:.2f}", kb)
        else: safe_edit(chat_id, msg_id, "❌ <b>Balance deduct error.</b>")
    else: safe_edit(chat_id, msg_id, f"❌ <b>PURCHASE FAILED</b>\n\n<b>Reason:</b> {result.get('message', 'Out of Stock')}")

# ================== FLASK SETUP ==================
app = Flask(__name__)
app.secret_key = "saksham_secret"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Saksham Panel</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; font-family: 'Poppins', sans-serif; }
        body { background: #0f172a; color: #e2e8f0; margin: 0; padding: 20px; }
        .container { max-width: 1000px; margin: auto; }
        .header { text-align: center; margin-bottom: 20px; color: #38bdf8; }
        .tabs { display: flex; gap: 5px; margin-bottom: 20px; flex-wrap: wrap; justify-content: center; }
        .tab-btn { background: #1e293b; color: white; padding: 10px 15px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 14px; }
        .tab-btn.active { background: #0ea5e9; }
        .card { background: #1e293b; padding: 25px; border-radius: 12px; margin-bottom: 20px; overflow-x: auto; }
        input, select, textarea { width: 100%; padding: 12px; margin: 5px 0 15px 0; border-radius: 8px; border: 1px solid #334155; background: #0f172a; color: white; }
        button { padding: 14px; background: #0ea5e9; color: white; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; width: 100%; margin-top: 10px; }
        .btn-danger { background: #ef4444; padding: 8px 15px; width: auto; margin: 0; font-size: 13px; }
        .btn-warning { background: #f59e0b; padding: 8px 15px; width: auto; margin: 0; font-size: 13px; }
        .btn-success { background: #10b981; padding: 8px 15px; width: auto; margin: 0; font-size: 13px; }
        .row { display: flex; gap: 10px; }
        .row .form-group { flex: 1; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; min-width: 600px; }
        th, td { padding: 10px; border-bottom: 1px solid #334155; text-align: left; }
        th { color: #38bdf8; }
        .badge { background: #f59e0b; color: #000; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; }
        .alert-success { background: #10b981; padding: 10px; border-radius: 8px; margin-bottom: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <h1 class="header">👑 Saksham Panel Admin</h1>
        <div class="tabs">
            <a href="/" class="tab-btn {% if tab == 'products' %}active{% endif %}">📦 Products</a>
            <a href="/users" class="tab-btn {% if tab == 'users' %}active{% endif %}">👥 Users & Resellers</a>
            <a href="/broadcast" class="tab-btn {% if tab == 'broadcast' %}active{% endif %}">📢 Broadcast</a>
            <a href="/settings" class="tab-btn {% if tab == 'settings' %}active{% endif %}">⚙️ Settings</a>
        </div>
        {% if msg_success %}<div class="alert-success">{{ msg_success }}</div>{% endif %}

        {% if tab == 'products' %}
        <div class="card">
            <h3>Add Product</h3>
            <form action="/add_product" method="POST" enctype="multipart/form-data">
                <div class="row">
                    <div class="form-group"><input type="text" name="name" placeholder="Name" required></div>
                    <div class="form-group"><input type="text" name="pid" placeholder="PID" required></div>
                </div>
                <input type="file" name="image_file" accept="image/*">
                <input type="url" name="video" placeholder="Video URL">
                <input type="url" name="setup" placeholder="Setup URL">
                <input type="url" name="hack" placeholder="Hack URL">
                <select name="is_v1"><option value="false">V2</option><option value="true">V1</option></select>
                <div id="price-container"><div class="row"><div class="form-group"><input type="text" name="duration[]" placeholder="1 Day" required></div><div class="form-group"><input type="number" name="price[]" placeholder="Price" required></div></div></div>
                <button type="button" class="btn-success" onclick="addPriceRow()">➕ More</button>
                <button type="submit">Save</button>
            </form>
        </div>
        <div class="card">
            <h3>All Products</h3>
            {% for id, p in products.items() %}
            <div style="display:flex; justify-content:space-between; border-bottom:1px solid #334155; padding:10px 0;">
                <div><strong>{{ p.name }}</strong> (PID: {{ p.pid }})<br><small>{% for d, pr in p.prices.items() %}{{d}}: ₹{{pr}} {% endfor %}</small></div>
                <div><a href="/edit_product/{{ id }}"><button class="btn-warning">Edit</button></a> <a href="/delete_product/{{ id }}"><button class="btn-danger">Delete</button></a></div>
            </div>
            {% endfor %}
        </div>

        {% elif tab == 'edit_product' %}
        <div class="card">
            <h3>Edit: {{ product.name }}</h3>
            <form action="/update_product/{{ p_id }}" method="POST" enctype="multipart/form-data">
                <div class="row"><div class="form-group"><input type="text" name="name" value="{{ product.name }}" required></div><div class="form-group"><input type="text" name="pid" value="{{ product.pid }}" required></div></div>
                <input type="file" name="image_file" accept="image/*">
                <input type="url" name="video" value="{{ product.video or '' }}">
                <input type="url" name="setup" value="{{ product.setup or '' }}">
                <input type="url" name="hack" value="{{ product.hack or '' }}">
                <select name="is_v1"><option value="false" {% if not product.is_v1 %}selected{% endif %}>V2</option><option value="true" {% if product.is_v1 %}selected{% endif %}>V1</option></select>
                <div id="price-container">{% for dur, pr in product.prices.items() %}<div class="row"><div class="form-group"><input type="text" name="duration[]" value="{{ dur }}" required></div><div class="form-group"><input type="number" name="price[]" value="{{ pr }}" required></div></div>{% endfor %}</div>
                <button type="button" class="btn-success" onclick="addPriceRow()">➕ More</button>
                <button type="submit" style="background:#f59e0b;">Update</button>
            </form>
        </div>

        {% elif tab == 'users' %}
        <div class="card">
            <h3>Users & Resellers</h3>
            <table>
                <tr><th>User ID</th><th>Name</th><th>Balance</th><th>Amt(+/-) & Disc%</th></tr>
                {% for uid, u in users.items() %}
                <tr>
                    <td>{{ uid }}</td>
                    <td>{{ u.name }} {% if u.get('discount',0)>0 %}<br><span class="badge">RESELLER</span>{% endif %}</td>
                    <td>₹{{ u.balance }}</td>
                    <td>
                        <form action="/update_user" method="POST" style="display:flex; gap:5px;">
                            <input type="hidden" name="uid" value="{{ uid }}">
                            <input type="number" name="amount" placeholder="+/- ₹" style="width:70px; padding:8px; margin:0;">
                            <input type="number" name="discount" value="{{ u.get('discount', 0) }}" placeholder="Disc%" style="width:70px; padding:8px; margin:0;">
                            <button type="submit" class="btn-success">Save</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </table>
        </div>

        {% elif tab == 'broadcast' %}
        <div class="card">
            <h3>Send Message</h3>
            <form action="/send_broadcast" method="POST"><textarea name="message" rows="5" required></textarea><button type="submit">🚀 Send</button></form>
        </div>

        {% elif tab == 'settings' %}
        <div class="card">
            <h3>Settings</h3>
            <form action="/settings" method="POST">
                <label>Store Name</label><input type="text" name="store_name" value="{{ settings.get('store_name', '') }}">
                <label>Support Username</label><input type="text" name="support_username" value="{{ settings.get('support_username', '') }}">
                <label>Update Link</label><input type="url" name="update_link" value="{{ settings.get('update_link', '') }}">
                <label>Maintenance</label><select name="maintenance"><option value="false" {% if settings.get('maintenance')=='false' %}selected{% endif %}>ON</option><option value="true" {% if settings.get('maintenance')=='true' %}selected{% endif %}>OFF</option></select>
                <button type="submit">Save</button>
            </form>
        </div>
        {% endif %}
    </div>
    <script>function addPriceRow() { const c = document.getElementById('price-container'); const d = document.createElement('div'); d.className='row'; d.innerHTML=`<div class="form-group"><input type="text" name="duration[]" placeholder="Duration" required></div><div class="form-group"><input type="number" name="price[]" placeholder="Price" required></div>`; c.appendChild(d); }</script>
</body>
</html>
"""

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE, tab='products', products=load_products())
@app.route('/add_product', methods=['POST'])
def add_product():
    prices = {}
    for d, p in zip(request.form.getlist('duration[]'), request.form.getlist('price[]')):
        if d.strip() and p.strip(): prices[d.strip()] = float(p.strip())
    img = None
    if 'image_file' in request.files:
        f = request.files['image_file']
        if f.filename: img = os.path.join(UPLOAD_FOLDER, secure_filename(f.filename)); f.save(img)
    prods = load_products(); prods[str(int(time.time()))] = {"name": request.form['name'], "pid": request.form['pid'], "image": img, "video": request.form.get('video'), "setup": request.form.get('setup'), "hack": request.form.get('hack'), "is_v1": request.form.get('is_v1')=='true', "prices": prices}
    with open(PRODUCTS_FILE, "w") as f: json.dump(prods, f)
    return render_template_string(HTML_TEMPLATE, tab='products', products=prods, msg_success="Added!")
@app.route('/edit_product/<p_id>')
def edit_product(p_id): return render_template_string(HTML_TEMPLATE, tab='edit_product', product=load_products().get(p_id), p_id=p_id)
@app.route('/update_product/<p_id>', methods=['POST'])
def update_product(p_id):
    prods = load_products(); prices = {}
    for d, p in zip(request.form.getlist('duration[]'), request.form.getlist('price[]')):
        if d.strip() and p.strip(): prices[d.strip()] = float(p.strip())
    img = prods[p_id].get("image")
    if 'image_file' in request.files:
        f = request.files['image_file']
        if f.filename: img = os.path.join(UPLOAD_FOLDER, secure_filename(f.filename)); f.save(img)
    prods[p_id].update({"name": request.form['name'], "pid": request.form['pid'], "image": img, "video": request.form.get('video'), "setup": request.form.get('setup'), "hack": request.form.get('hack'), "is_v1": request.form.get('is_v1')=='true', "prices": prices})
    with open(PRODUCTS_FILE, "w") as f: json.dump(prods, f)
    return render_template_string(HTML_TEMPLATE, tab='products', products=prods, msg_success="Updated!")
@app.route('/delete_product/<p_id>')
def delete_product(p_id):
    prods = load_products()
    if p_id in prods: del prods[p_id]; 
    with open(PRODUCTS_FILE, "w") as f: json.dump(prods, f)
    return redirect(url_for('index'))
@app.route('/users')
def users(): return render_template_string(HTML_TEMPLATE, tab='users', users=load_db().get("users", {}))
@app.route('/update_user', methods=['POST'])
def update_user():
    db = load_db(); uid = request.form['uid']
    if uid in db["users"]:
        amt = float(request.form['amount']) if request.form['amount'] else 0
        db["users"][uid]["balance"] = max(0, round(db["users"][uid]["balance"] + amt, 2))
        db["users"][uid]["discount"] = int(request.form['discount']) if request.form['discount'] else 0
        save_db(db)
    return redirect(url_for('users'))
@app.route('/broadcast')
def broadcast(): return render_template_string(HTML_TEMPLATE, tab='broadcast')
@app.route('/send_broadcast', methods=['POST'])
def send_broadcast():
    db = load_db(); c = 0
    for uid in db.get("users", {}).keys():
        try:
            if requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": uid, "text": request.form['message'], "parse_mode": "HTML"}).status_code == 200: c += 1
        except: pass
    return render_template_string(HTML_TEMPLATE, tab='broadcast', msg_success=f"Sent to {c} users!")
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"store_name": request.form['store_name'], "support_username": request.form['support_username'], "update_link": request.form['update_link'], "maintenance": request.form['maintenance']}, f)
        return render_template_string(HTML_TEMPLATE, tab='settings', settings=get_settings(), msg_success="Saved!")
    return render_template_string(HTML_TEMPLATE, tab='settings', settings=get_settings())

# ================== RUNNER ==================
def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("🚀 Bot and Web Panel started together!")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)
