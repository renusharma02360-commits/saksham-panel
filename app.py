import os
import time
import threading
import requests
import telebot
import re
import urllib.parse
from functools import wraps
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, ReplyKeyboardRemove, ForceReply
from famgateway import FamGateway
from flask import Flask, request, render_template_string, redirect, url_for
from pymongo import MongoClient
from bson.objectid import ObjectId

# ================== CONFIG ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8765613302:AAE2b0qDyR-o0UkzGs5H7fuSSz0yhLiYSBc") 
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")

ADMIN_ID = 7778093775
WEB_URL = "https://saksham-panel-kpsl.onrender.com"

# 💳 FAMGATEWAY CONFIG
API_KEY = "fam_c8a61c94c53cd1cd51dc5a16d019626ddc7da1c5"

# RESELLER API
RESELLER_API_URL = "https://bantibhaiya.to/api/reseller_v1.php"
RESELLER_API_KEY = "e5990b638beaa7b2335373200b39c93f"
MASTER_KEY = "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"
# ============================================

try:
    client = MongoClient(MONGO_URI)
    db = client.saksham_panel
    users_col = db.users
    products_col = db.products
    categories_col = db.categories
    orders_col = db.orders
    settings_col = db.settings
    key_stock_col = db.key_stock 
    print("✅ Database Connected")
except Exception as e:
    print(f"❌ Database Error: {e}")

bot = telebot.TeleBot(BOT_TOKEN)

try:
    fg = FamGateway(api_key=API_KEY)
    print("✅ FamGateway Connected")
except Exception as e:
    print(f"❌ Gateway Error: {e}")

calc_data = {}

# ---------------- DB HELPERS ----------------
def get_setting(key, default):
    s = settings_col.find_one({"_id": key})
    return s["value"] if s else default

def get_user_info(uid):
    u = users_col.find_one({"_id": str(uid)})
    if not u:
        default_u = {"_id": str(uid), "balance": 0.0, "name": "User", "discount": 0, "joined": time.strftime("%d-%m-%Y"), "custom_prices": {}}
        users_col.insert_one(default_u)
        return default_u
    return u

def get_balance(uid):
    return get_user_info(uid).get("balance", 0.0)

def deduct_balance(uid, amount):
    result = users_col.find_one_and_update(
        {"_id": str(uid), "balance": {"$gte": amount}},
        {"$inc": {"balance": -amount}}
    )
    return result is not None

def credit_atomic(uid, amount, utr):
    if orders_col.find_one({"utr": utr, "type": "deposit"}):
        return True, get_balance(uid)
    orders_col.insert_one({"utr": utr, "uid": str(uid), "amount": amount, "type": "deposit", "time": time.strftime("%d-%m-%Y %I:%M %p")})
    users_col.update_one({"_id": str(uid)}, {"$inc": {"balance": amount}}, upsert=True)
    return True, get_balance(uid)

def log_order(uid, product, key, price):
    orders_col.insert_one({"uid": str(uid), "product": product, "key": key, "price": price, "type": "purchase", "time": time.strftime("%d-%m-%Y %I:%M %p")})

def auto_delete_message(chat_id, message_id, delay=300):
    time.sleep(delay)
    try: bot.delete_message(chat_id, message_id)
    except: pass 

# ================== TELEGRAM BOT ==================
def get_main_menu(uid):
    welcome_text = (
        "🛍️ <b>SAKSHAM PANEL SHOP</b>\n"
        "─────────────────\n\n"
        "🔥 Premium Mods, Panels & Bypasses — all in one place!\n"
        "⚡ Instant delivery • 🔒 Verified sellers • 💯 Trusted by 1000+ buyers\n\n"
        "👇 <i>Tap a category below to get started:</i>"
    )
    
    # A to Z dynamic texts
    channel_link = get_setting("channel_link", "https://t.me/YourChannel")
    support_link = get_setting("support_link", "https://wa.me/918849507563")
    hack_update_link = get_setting("hack_update_link", "https://t.me/YourChannel")

    # Stylish UPPERCASE button names
    btn_shop = get_setting("btn_shop", "➡️ SHOP NOW 🛍️")
    btn_add = get_setting("btn_add", "➡️ ADD AMOUNT 💸")
    btn_profile = get_setting("btn_profile", "➡️ MY PROFILE 👤")
    btn_history = get_setting("btn_history", "➡️ ORDER HISTORY 📄")
    btn_reseller = get_setting("btn_reseller", "➡️ MAKE RESELLER 99 👑")
    btn_hack = get_setting("btn_hack", "➡️ ALL HACK UPDATE 📁")
    btn_channel = get_setting("btn_channel", "➡️ MAIN CHANNEL ⚡")
    btn_support = get_setting("btn_support", "➡️ CONTACT SUPPORT 📞")

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton(btn_shop, callback_data="bot_shop", style="danger"))
    
    kb.add(InlineKeyboardButton(btn_add, callback_data="bot_add_bal", style="danger"), 
           InlineKeyboardButton(btn_profile, callback_data="bot_profile", style="danger"))
           
    kb.add(InlineKeyboardButton(btn_history, callback_data="bot_history", style="danger"), 
           InlineKeyboardButton(btn_hack, url=hack_update_link, style="danger"))
           
    kb.add(InlineKeyboardButton(btn_reseller, callback_data="bot_make_reseller", style="danger"),
           InlineKeyboardButton(btn_channel, url=channel_link, style="danger"))
           
    kb.add(InlineKeyboardButton(btn_support, url=support_link, style="danger"))
    
    return welcome_text, kb

@bot.message_handler(commands=["start"])
def start(msg):
    uid = str(msg.from_user.id)
    get_user_info(uid)
    text, kb = get_main_menu(uid)
    sent_msg = bot.send_message(msg.chat.id, text, parse_mode="HTML", reply_markup=kb)
    threading.Thread(target=auto_delete_message, args=(msg.chat.id, sent_msg.message_id)).start()

@bot.callback_query_handler(func=lambda call: True)
def bot_callbacks(call):
    uid = str(call.from_user.id)
    try:
        if call.data == "bot_main":
            text, kb = get_main_menu(uid)
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)
            
        elif call.data == "bot_shop":
            categories = list(categories_col.find({}))
            if not categories: return bot.answer_callback_query(call.id, "❌ No categories added yet.", show_alert=True)
            
            text = "📁 <b>CHOOSE A CATEGORY</b>\n─────────────────\n\n🔥 Premium Mods, Panels & Bypasses\n\n👇 <i>Tap a category below:</i>"
            kb = InlineKeyboardMarkup(row_width=1)
            for cat in categories:
                kb.add(InlineKeyboardButton(f"➡️ {cat.get('name').upper()} PANEL", callback_data=f"cat_{cat['_id']}", style="danger"))
            kb.add(InlineKeyboardButton("⬅️ BACK", callback_data="bot_main", style="danger"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif call.data.startswith("cat_"):
            cat_id = call.data.split("_")[1]
            cat = categories_col.find_one({"_id": ObjectId(cat_id)})
            products = list(products_col.find({"category_id": str(cat_id)}))
            if not products: return bot.answer_callback_query(call.id, f"❌ No products found.", show_alert=True)
            
            text = f"📁 <b>{cat.get('name', 'Category').upper()}</b>\n\n➡️ Choose a product 🕊️❤️"
            kb = InlineKeyboardMarkup(row_width=1)
            for p in products:
                kb.add(InlineKeyboardButton(f"{p.get('icon', '🔹')} {p.get('name')}", callback_data=f"view_{p['_id']}", style="danger"))
            kb.add(InlineKeyboardButton("⬅️ BACK", callback_data="bot_shop", style="danger"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif call.data.startswith("view_"):
            p_id = call.data.split("_")[1]
            p = products_col.find_one({"_id": ObjectId(p_id)})
            u = get_user_info(uid)
            disc = u.get('discount', 0)
            custom_prices = u.get('custom_prices', {}).get(str(p_id), {})
            
            features_text = p.get('features', '').replace('\n', '\n⚡ ') if p.get('features') else ''
            text = f"📁 <b>{p['name']}</b>\n\n⚡ {features_text}\n\n"
            
            kb = InlineKeyboardMarkup(row_width=2)
            update_link = str(p.get('setup_video', '')).strip()
            video_link = str(p.get('hack_video', '')).strip()
            if update_link.startswith('http'): kb.add(InlineKeyboardButton("📥 UPDATE FILE", url=update_link, style="danger"))
            if video_link.startswith('http'): kb.add(InlineKeyboardButton("▶️ VIDEO/FEEDBACK", url=video_link, style="danger"))
            
            for d, pr in p.get('prices', {}).items():
                if not d.strip(): continue
                if d in custom_prices: final_pr = custom_prices[d]
                else: final_pr = float(pr) - (float(pr) * disc / 100) if disc > 0 else float(pr)
                kb.add(InlineKeyboardButton(f"{d.upper()} - ₹{final_pr:.1f}", callback_data=f"buy_{p_id}_{d}", style="danger"))
                
            kb.add(InlineKeyboardButton("⬅️ BACK", callback_data=f"cat_{p.get('category_id')}", style="danger"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif call.data.startswith("buy_"):
            parts = call.data.split("_")
            p_id = parts[1]
            duration = "_".join(parts[2:])
            
            p = products_col.find_one({"_id": ObjectId(p_id)})
            u = get_user_info(uid)
            disc = u.get('discount', 0)
            custom_prices = u.get('custom_prices', {}).get(str(p_id), {})
            
            base_price = float(p['prices'][duration])
            if duration in custom_prices: price = float(custom_prices[duration])
            else: price = base_price - (base_price * disc / 100) if disc > 0 else base_price
            
            user_bal = get_balance(uid)
            if user_bal < price:
                return bot.answer_callback_query(call.id, f"❌ Low Balance!\n\nBalance: ₹{user_bal:.2f}\nRequired: ₹{price:.2f}", show_alert=True)
                
            bot.answer_callback_query(call.id)
            
            if deduct_balance(uid, price):
                bot.edit_message_text("⏳ <i>Processing your order...</i>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
                
                manual_key = key_stock_col.find_one_and_delete({"product_id": str(p_id)})
                
                if manual_key:
                    key = manual_key['key']
                    log_order(uid, p['name'], key, price)
                    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 BACK TO MENU", callback_data="bot_main", style="danger"))
                    bot.edit_message_text(f"✅ <b>PURCHASE SUCCESSFUL!</b>\n\n📦 Product: {p['name']}\n⏱ Duration: {duration}\n🔑 Key:\n<code>{key}</code>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
                else:
                    try:
                        data = {'api_key': RESELLER_API_KEY, 'action': 'buy', 'product_id': str(p.get("pid", "")).strip(), 'duration': str(duration).strip(), 'quantity': 1}
                        res = requests.post(RESELLER_API_URL, data=data, headers={'x-master-key': MASTER_KEY}, timeout=20)
                        if not res.text.strip(): raise Exception("API returned empty text.")
                        result = res.json()
                    except Exception as e: 
                        result = {"status": "error", "message": str(e)}
                        
                    if result.get("status") == "success" or "keys" in result:
                        key = result.get("keys", ["Key not found"])[0]
                        log_order(uid, p['name'], key, price)
                        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 BACK TO MENU", callback_data="bot_main", style="danger"))
                        bot.edit_message_text(f"✅ <b>PURCHASE SUCCESSFUL!</b>\n\n📦 Product: {p['name']}\n⏱ Duration: {duration}\n🔑 Key:\n<code>{key}</code>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
                    else:
                        users_col.update_one({"_id": str(uid)}, {"$inc": {"balance": price}})
                        err_msg = result.get("message", "Out of Stock / API Error")
                        bot.edit_message_text(f"❌ <b>API Error</b>\n\nReason: {err_msg}\n\n₹{price:.2f} Refunded.", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 BACK", callback_data="bot_shop", style="danger")))

        elif call.data == "bot_make_reseller":
            # Reseller Info Message
            text = (
                "👑 <b>BECOME A RESELLER</b>\n"
                "─────────────────\n\n"
                "Get special discounted rates on all products and start your own business!\n\n"
                "💰 <b>Price:</b> ₹99 (Lifetime)\n"
                "🏷️ <b>Discount:</b> 50% OFF on all items\n\n"
                "👇 <i>Click below to buy reseller access or contact support.</i>"
            )
            kb = InlineKeyboardMarkup(row_width=1)
            # Yahan aap future me direct auto-buy ka logic laga sakte hain. Abhi ke liye contact support bhej rahe hain.
            kb.add(InlineKeyboardButton("🛒 BUY NOW (₹99)", callback_data="buy_reseller_logic", style="success"))
            kb.add(InlineKeyboardButton("📞 CONTACT SUPPORT", url=get_setting("support_link", "https://wa.me/918849507563"), style="danger"))
            kb.add(InlineKeyboardButton("⬅️ BACK", callback_data="bot_main", style="danger"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif call.data == "buy_reseller_logic":
            # Yeh dummy handler hai abhi ke liye. Aap yahan balance deduct karke user ko reseller bana sakte hain.
            bot.answer_callback_query(call.id, "Please contact support to activate reseller manually (Auto-buy coming soon!).", show_alert=True)

        elif call.data == "bot_profile":
            u = get_user_info(uid)
            text = f"👤 <b>YOUR PROFILE</b>\n\n🆔 ID: <code>{uid}</code>\n💰 Balance: ₹{u.get('balance', 0.0):.2f}\n🏷️ Discount: {u.get('discount', 0)}%\n📅 Joined: {u.get('joined')}"
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("💸 ADD BALANCE", callback_data="bot_add_bal", style="danger"), InlineKeyboardButton("🔙 BACK", callback_data="bot_main", style="danger"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)
            
        elif call.data == "bot_history":
            orders = list(orders_col.find({"uid": uid}).sort("_id", -1))
            if not orders: return bot.answer_callback_query(call.id, "No orders found.", show_alert=True)
            text = "📜 <b>Your Order History</b>\n\n"
            for o in orders[:5]:
                text += f"📦 {o.get('product', 'Deposit')}\n🔑 <code>{o.get('key', 'N/A')}</code>\n📅 {o.get('time')}\n➖➖➖➖➖➖➖➖\n"
            sent = bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 BACK", callback_data="bot_main", style="danger")))
            threading.Thread(target=auto_delete_message, args=(sent.chat.id, sent.message_id)).start()
            bot.answer_callback_query(call.id)
            
        elif call.data == "bot_add_bal":
            calc_data[uid] = "" 
            show_calculator(call.message.chat.id, call.message.message_id, uid)
            bot.answer_callback_query(call.id)

        elif call.data.startswith("calc_"):
            action = call.data.split("_")[1]
            current_amount = calc_data.get(uid, "")

            if action == "cross":
                calc_data[uid] = ""
                text, kb = get_main_menu(uid)
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
                bot.answer_callback_query(call.id, "Cancelled")
            
            elif action == "tick":
                if not current_amount or float(current_amount) <= 0:
                    return bot.answer_callback_query(call.id, "❌ Please enter a valid amount first!", show_alert=True)
                
                amount = float(current_amount)
                calc_data[uid] = "" 
                
                bot.edit_message_text("⏳ <i>Redirecting to Payment Gateway...</i>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
                
                try:
                    order = fg.create_order(amount=amount, customer_name=f"User_{uid}")
                except Exception as e:
                    bot.edit_message_text("❌ Failed to create order via FamGateway. Please try again.", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 BACK", callback_data="bot_main", style="danger")))
                    return
                
                caption = f"💳 <b>Pay ₹{amount}</b>\n\nScan the QR code above using any UPI app.\n\n⏳ <i>Waiting for payment confirmation...</i>"
                bot.delete_message(call.message.chat.id, call.message.message_id) 
                qr_msg = bot.send_photo(call.message.chat.id, photo=order.qr_url, caption=caption, parse_mode="HTML")
                
                threading.Thread(target=verify_chat_payment_famgateway, args=(call.message.chat.id, uid, order.order_id, amount, qr_msg.message_id)).start()
                
            else:
                if action == "C": calc_data[uid] = ""
                elif action == "back": calc_data[uid] = current_amount[:-1]
                else:
                    if len(current_amount) < 5: calc_data[uid] += action
                show_calculator(call.message.chat.id, call.message.message_id, uid)
                bot.answer_callback_query(call.id)

    except Exception as e:
        try: bot.send_message(ADMIN_ID, f"⚠️ <b>Bot Error:</b>\n<code>{str(e)}</code>", parse_mode="HTML")
        except: pass

def show_calculator(chat_id, msg_id, uid):
    current = calc_data.get(uid, "")
    display = current if current else "0"
    text = f"💸 <b>Enter Amount</b>\n\n<code>₹ {display}</code>\n\n<i>Type amount using the calculator below:</i>"
    
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(InlineKeyboardButton("1", callback_data="calc_1", style="danger"), InlineKeyboardButton("2", callback_data="calc_2", style="danger"), InlineKeyboardButton("3", callback_data="calc_3", style="danger"))
    kb.add(InlineKeyboardButton("4", callback_data="calc_4", style="danger"), InlineKeyboardButton("5", callback_data="calc_5", style="danger"), InlineKeyboardButton("6", callback_data="calc_6", style="danger"))
    kb.add(InlineKeyboardButton("7", callback_data="calc_7", style="danger"), InlineKeyboardButton("8", callback_data="calc_8", style="danger"), InlineKeyboardButton("9", callback_data="calc_9", style="danger"))
    kb.add(InlineKeyboardButton("C", callback_data="calc_C", style="danger"), InlineKeyboardButton("0", callback_data="calc_0", style="danger"), InlineKeyboardButton("⌫", callback_data="calc_back", style="danger"))
    kb.add(InlineKeyboardButton("✗ CANCEL", callback_data="calc_cross", style="danger"), InlineKeyboardButton("✓ PROCEED", callback_data="calc_tick", style="success"))
    
    bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=kb)

def verify_chat_payment_famgateway(chat_id, uid, order_id, amount, msg_id):
    for i in range(240): 
        time.sleep(5)
        try:
            status = fg.get_status(order_id)
            if status.is_paid:
                ok, new_bal = credit_atomic(uid, amount, status.utr)
                success_caption = f"✅ <b>Payment Successful!</b>\n\n💰 Amount: ₹{amount}\n💵 New Balance: ₹{new_bal:.2f}\n\n<i>Thank you for your purchase!</i>"
                bot.edit_message_caption(chat_id=chat_id, message_id=msg_id, caption=success_caption, parse_mode="HTML")
                return
        except Exception as e: pass 

# ================== FLASK WEB APP (ADMIN PANEL) ==================
app = Flask(__name__)
app.secret_key = "sk_panel_secret"

BASE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap');
    * { box-sizing: border-box; font-family: 'Poppins', sans-serif; margin: 0; padding: 0; }
    body { background-color: #0d1117; color: #c9d1d9; padding-bottom: 50px; }
    .top-nav { display: flex; justify-content: space-between; align-items: center; padding: 15px 30px; background: #161b22; border-bottom: 1px solid #30363d; }
    .nav-links a { color: #8b949e; text-decoration: none; margin-right: 15px; font-weight: 600; transition: 0.2s; padding: 8px 12px; border-radius: 6px; }
    .nav-links a:hover, .nav-links a.active { color: #fff; background: #21262d; }
    .container { padding: 30px; max-width: 1000px; margin: 0 auto; }
    .card { background: #161b22; border-radius: 12px; padding: 25px; border: 1px solid #30363d; margin-bottom: 25px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
    .stat-card { background: linear-gradient(145deg, #161b22, #0d1117); border-radius: 12px; padding: 20px; border: 1px solid #30363d; text-align: center; }
    .stat-title { font-size: 13px; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
    .stat-value { font-size: 28px; font-weight: 800; color: #58a6ff; margin-top: 5px; }
    input, textarea, select { width: 100%; padding: 12px; border-radius: 8px; border: 1px solid #30363d; background: #0d1117; color: #c9d1d9; font-size: 15px; outline: none; margin-bottom: 15px; transition: 0.2s; }
    input:focus, textarea:focus, select:focus { border-color: #58a6ff; box-shadow: 0 0 0 3px rgba(88,166,255,0.2); }
    label { display: block; font-size: 14px; color: #8b949e; margin-bottom: 8px; font-weight: 600; }
    .btn { display: inline-block; padding: 12px 24px; border-radius: 8px; font-weight: 700; font-size: 15px; border: none; cursor: pointer; text-decoration: none; color: #fff; transition: 0.2s; text-align: center; }
    .btn-primary { background: #238636; }
    .btn-primary:hover { background: #2ea043; }
    .btn-danger { background: #da3633; }
    .btn-warning { background: #d29922; color: #000; }
    .btn-warning:hover { background: #e3b341; }
    .btn-blue { background: #1f6feb; }
    .btn-blue:hover { background: #388bfd; }
</style>
"""

@app.route('/')
def home(): return redirect(url_for('admin_dashboard'))

@app.route('/admin')
def admin_dashboard():
    total_users = users_col.count_documents({})
    total_products = products_col.count_documents({})
    total_keys = key_stock_col.count_documents({})
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-size:20px; font-weight:800; color:#fff;">⚙️ Controller</div>
        <div class="nav-links">
            <a href="/admin" class="active">Dashboard</a><a href="/admin_users">Users</a><a href="/admin_products">Products</a><a href="/admin_keys">Keys</a><a href="/admin_categories">Categories</a><a href="/admin_settings">Bot Settings</a>
        </div>
    </div>
    <div class="container">
        <div class="stats-grid">
            <div class="stat-card"><div class="stat-title">Total Users</div><div class="stat-value">{total_users}</div></div>
            <div class="stat-card"><div class="stat-title">Total Products</div><div class="stat-value">{total_products}</div></div>
            <div class="stat-card"><div class="stat-title">Manual Keys Stock</div><div class="stat-value">{total_keys}</div></div>
        </div>
        <div class="card" style="border-color:#58a6ff; text-align:center;">
            <h2 style="color:#58a6ff; margin-bottom:10px;">Welcome to Saksham Panel</h2>
            <p style="color:#8b949e;">All systems operational. You can manage Manual Keys and Custom Prices for specific users.</p>
        </div>
    </div>
    """)

# ... (Baaki saare admin routes same rahenge, sirf settings route me naye buttons add honge) ...

@app.route('/admin_settings', methods=['GET', 'POST'])
def admin_settings():
    if request.method == 'POST':
        for key in request.form: settings_col.update_one({"_id": key}, {"$set": {"value": request.form[key]}}, upsert=True)
        return redirect(url_for('admin_settings'))
        
    settings = {
        "welcome_text": get_setting("welcome_text", "🛍️ <b>SAKSHAM PANEL SHOP</b>\n─────────────────\n\n🔥 Premium Mods, Panels & Bypasses — all in one place!\n⚡ Instant delivery • 🔒 Verified sellers • 💯 Trusted by 1000+ buyers\n\n👇 <i>Tap a category below to get started:</i>"),
        "btn_shop": get_setting("btn_shop", "➡️ SHOP NOW 🛍️"), 
        "btn_add": get_setting("btn_add", "➡️ ADD AMOUNT 💸"),
        "btn_profile": get_setting("btn_profile", "➡️ MY PROFILE 👤"), 
        "btn_history": get_setting("btn_history", "➡️ ORDER HISTORY 📄"),
        "btn_reseller": get_setting("btn_reseller", "➡️ MAKE RESELLER 99 👑"),
        "btn_hack": get_setting("btn_hack", "➡️ ALL HACK UPDATE 📁"),
        "btn_channel": get_setting("btn_channel", "➡️ MAIN CHANNEL ⚡"), 
        "btn_support": get_setting("btn_support", "➡️ CONTACT SUPPORT 📞"),
        "channel_link": get_setting("channel_link", "https://t.me/YourChannel"),
        "hack_update_link": get_setting("hack_update_link", "https://t.me/YourChannel"),
        "support_link": get_setting("support_link", "https://wa.me/918849507563")
    }

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><div style="font-size:20px; font-weight:800; color:#fff;">⚙️ Controller</div><div class="nav-links"><a href="/admin">Dashboard</a><a href="/admin_users">Users</a><a href="/admin_products">Products</a><a href="/admin_keys">Keys</a><a href="/admin_categories">Categories</a><a href="/admin_settings" class="active">Bot Settings</a></div></div>
    <div class="container">
        <div class="card">
            <h3 style="margin-bottom:20px; color:#fff;">Edit Bot Text & Links</h3>
            <form method="POST">
                <label>Welcome Message</label><textarea name="welcome_text" rows="5">{settings['welcome_text']}</textarea>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:15px;">
                    <div><label>Shop Button</label><input type="text" name="btn_shop" value="{settings['btn_shop']}"></div>
                    <div><label>Add Amount Button</label><input type="text" name="btn_add" value="{settings['btn_add']}"></div>
                    <div><label>Profile Button</label><input type="text" name="btn_profile" value="{settings['btn_profile']}"></div>
                    <div><label>History Button</label><input type="text" name="btn_history" value="{settings['btn_history']}"></div>
                    <div><label>Reseller Button</label><input type="text" name="btn_reseller" value="{settings['btn_reseller']}"></div>
                    <div><label>Hack Update Button</label><input type="text" name="btn_hack" value="{settings['btn_hack']}"></div>
                    <div><label>Channel Button</label><input type="text" name="btn_channel" value="{settings['btn_channel']}"></div>
                    <div><label>Support Button</label><input type="text" name="btn_support" value="{settings['btn_support']}"></div>
                    <div><label>Channel Link</label><input type="text" name="channel_link" value="{settings['channel_link']}"></div>
                    <div><label>Hack Update Link</label><input type="text" name="hack_update_link" value="{settings['hack_update_link']}"></div>
                    <div><label>Support Link</label><input type="text" name="support_link" value="{settings['support_link']}"></div>
                </div>
                <button type="submit" class="btn btn-blue" style="width:100%; margin-top:20px;">Save Settings</button>
            </form>
        </div>
    </div>
    """)

# ... (Baki routes jaise /admin_users, /admin_products, /admin_keys, /admin_categories, etc. pichle code se same rahenge) ...

# ================== RUNNING ==================
if __name__ == "__main__":
    threading.Thread(target=lambda: bot.infinity_polling(timeout=30, long_polling_timeout=30), daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
