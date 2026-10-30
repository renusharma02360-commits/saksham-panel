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
    print("✅ Database Connected")
except Exception as e:
    print(f"❌ Database Error: {e}")

bot = telebot.TeleBot(BOT_TOKEN)

try:
    fg = FamGateway(api_key=API_KEY)
    print("✅ FamGateway Connected")
except Exception as e:
    print(f"❌ Gateway Error: {e}")

# Calculator State (Temporary Memory)
calc_data = {}

# ---------------- DB HELPERS ----------------
def get_setting(key, default):
    s = settings_col.find_one({"_id": key})
    return s["value"] if s else default

def get_user_info(uid):
    u = users_col.find_one({"_id": str(uid)})
    if not u:
        default_u = {
            "_id": str(uid), "balance": 0.0, "name": "User", "discount": 0, "joined": time.strftime("%d-%m-%Y"),
            "custom_prices": {} 
        }
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

# ---------------- AUTO DELETE HELPER ----------------
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
    
    btn_shop = get_setting("btn_shop", "➡️ Shop Now 🛍️")
    btn_add = get_setting("btn_add", "➡️ Add Amount 💸")
    btn_profile = get_setting("btn_profile", "➡️ My Profile 👤")
    btn_history = get_setting("btn_history", "➡️ Order History 📄")
    btn_channel = get_setting("btn_channel", "➡️ Main Channel ⚡")
    channel_link = get_setting("channel_link", "https://t.me/YourChannel")
    support_link = get_setting("support_link", "https://wa.me/918849507563")

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton(btn_shop, callback_data="bot_shop", style="danger"))
    kb.add(InlineKeyboardButton(btn_add, callback_data="bot_add_bal", style="danger"), 
           InlineKeyboardButton(btn_profile, callback_data="bot_profile", style="danger"))
    kb.add(InlineKeyboardButton(btn_history, callback_data="bot_history", style="danger"), 
           InlineKeyboardButton(btn_channel, url=channel_link, style="danger"))
    kb.add(InlineKeyboardButton("➡️ Contact Support 📞", url=support_link, style="danger"))
    
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
            if not categories:
                return bot.answer_callback_query(call.id, "❌ No categories added yet.", show_alert=True)
            
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
            if update_link.startswith('http'): kb.add(InlineKeyboardButton("📥 Update File", url=update_link, style="danger"))
            if video_link.startswith('http'): kb.add(InlineKeyboardButton("▶️ Video/Feedback", url=video_link, style="danger"))
            
            for d, pr in p.get('prices', {}).items():
                if not d.strip(): continue
                if d in custom_prices: final_pr = custom_prices[d]
                else: final_pr = float(pr) - (float(pr) * disc / 100) if disc > 0 else float(pr)
                kb.add(InlineKeyboardButton(f"{d.upper()} - ₹{final_pr:.1f}", callback_data=f"buy_{p_id}_{d}", style="danger"))
                
            kb.add(InlineKeyboardButton("⬅️ Back", callback_data=f"cat_{p.get('category_id')}", style="danger"))
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
                bot.edit_message_text("⏳ <i>Processing your order from API...</i>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
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
                    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back to Menu", callback_data="bot_main", style="danger"))
                    bot.edit_message_text(f"✅ <b>PURCHASE SUCCESSFUL!</b>\n\n📦 Product: {p['name']}\n⏱ Duration: {duration}\n🔑 Key:\n<code>{key}</code>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
                else:
                    users_col.update_one({"_id": str(uid)}, {"$inc": {"balance": price}})
                    err_msg = result.get("message", "Out of Stock / API Error")
                    bot.edit_message_text(f"❌ <b>API Error</b>\n\nReason: {err_msg}\n\n₹{price:.2f} Refunded.", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="bot_shop", style="danger")))

        elif call.data == "bot_profile":
            u = get_user_info(uid)
            text = f"👤 <b>YOUR PROFILE</b>\n\n🆔 ID: <code>{uid}</code>\n💰 Balance: ₹{u.get('balance', 0.0):.2f}\n🏷️ Discount: {u.get('discount', 0)}%\n📅 Joined: {u.get('joined')}"
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("💸 Add Balance", callback_data="bot_add_bal", style="danger"), InlineKeyboardButton("🔙 Back", callback_data="bot_main", style="danger"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)
            
        elif call.data == "bot_history":
            orders = list(orders_col.find({"uid": uid}).sort("_id", -1))
            if not orders: return bot.answer_callback_query(call.id, "No orders found.", show_alert=True)
            text = "📜 <b>Your Order History</b>\n\n"
            for o in orders[:5]:
                text += f"📦 {o.get('product', 'Deposit')}\n🔑 <code>{o.get('key', 'N/A')}</code>\n📅 {o.get('time')}\n➖➖➖➖➖➖➖➖\n"
            sent = bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="bot_main", style="danger")))
            threading.Thread(target=auto_delete_message, args=(sent.chat.id, sent.message_id)).start()
            bot.answer_callback_query(call.id)
            
        # ================== CALCULATOR LOGIC ==================
        elif call.data == "bot_add_bal":
            calc_data[uid] = "" # Reset amount
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
                calc_data[uid] = "" # Clear calculator state
                
                # Show Redirecting
                bot.edit_message_text("⏳ <i>Redirecting to Payment Gateway...</i>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
                
                try:
                    order = fg.create_order(amount=amount, customer_name=f"User_{uid}")
                except Exception as e:
                    bot.edit_message_text("❌ Failed to create order via FamGateway. Please try again.", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="bot_main", style="danger")))
                    return
                
                # Show QR and Waiting Status
                caption = f"💳 <b>Pay ₹{amount}</b>\n\nScan the QR code above using any UPI app.\n\n⏳ <i>Waiting for payment confirmation...</i>"
                bot.delete_message(call.message.chat.id, call.message.message_id) # delete redirecting msg
                qr_msg = bot.send_photo(call.message.chat.id, photo=order.qr_url, caption=caption, parse_mode="HTML")
                
                # Start Background Check
                threading.Thread(target=verify_chat_payment_famgateway, args=(call.message.chat.id, uid, order.order_id, amount, qr_msg.message_id)).start()
                
            else:
                # Number pressed (0-9)
                if action == "C":
                    calc_data[uid] = ""
                elif action == "back":
                    calc_data[uid] = current_amount[:-1]
                else:
                    if len(current_amount) < 5: # Max 5 digits
                        calc_data[uid] += action
                
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
    # Numbers
    kb.add(InlineKeyboardButton("1", callback_data="calc_1", style="danger"), InlineKeyboardButton("2", callback_data="calc_2", style="danger"), InlineKeyboardButton("3", callback_data="calc_3", style="danger"))
    kb.add(InlineKeyboardButton("4", callback_data="calc_4", style="danger"), InlineKeyboardButton("5", callback_data="calc_5", style="danger"), InlineKeyboardButton("6", callback_data="calc_6", style="danger"))
    kb.add(InlineKeyboardButton("7", callback_data="calc_7", style="danger"), InlineKeyboardButton("8", callback_data="calc_8", style="danger"), InlineKeyboardButton("9", callback_data="calc_9", style="danger"))
    kb.add(InlineKeyboardButton("C", callback_data="calc_C", style="danger"), InlineKeyboardButton("0", callback_data="calc_0", style="danger"), InlineKeyboardButton("⌫", callback_data="calc_back", style="danger"))
    # Tick and Cross
    kb.add(InlineKeyboardButton("✗ Cancel", callback_data="calc_cross", style="danger"), InlineKeyboardButton("✓ Proceed", callback_data="calc_tick", style="success"))
    
    bot.edit_message_text(text, chat_id, msg_id, parse_mode="HTML", reply_markup=kb)

# --- FAMGATEWAY PAYMENT VERIFICATION ---
def verify_chat_payment_famgateway(chat_id, uid, order_id, amount, msg_id):
    for i in range(240): # 20 mins
        time.sleep(5)
        try:
            status = fg.get_status(order_id)
            if status.is_paid:
                ok, new_bal = credit_atomic(uid, amount, status.utr)
                # Edit the QR caption to show success!
                success_caption = (
                    f"✅ <b>Payment Successful!</b>\n\n"
                    f"💰 Amount: ₹{amount}\n"
                    f"💵 New Balance: ₹{new_bal:.2f}\n\n"
                    f"<i>Thank you for your purchase!</i>"
                )
                bot.edit_message_caption(chat_id=chat_id, message_id=msg_id, caption=success_caption, parse_mode="HTML")
                return
        except Exception as e: 
            pass 

# ================== FLASK WEB APP (ADMIN PANEL) ==================
app = Flask(__name__)
app.secret_key = "sk_panel_secret"
# [Admin Panel code yahan same rahega jo pichle message mein tha, maine ise short rakha hai]
# (Aap pichle code se /admin routes copy kar sakte hain, unme koi change nahi karna hai)

@app.route('/')
def home(): return "Bot is running with Calculator UI!"

# ================== RUNNING ==================
if __name__ == "__main__":
    threading.Thread(target=lambda: bot.infinity_polling(timeout=30, long_polling_timeout=30), daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
