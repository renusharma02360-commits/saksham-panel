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
DEFAULT_RESELLER_DISCOUNT = 40

RESELLER_API_URL = "https://bantibhaiya.to/api/reseller_v1.php"
RESELLER_API_KEY = "e5990b638beaa7b2335373200b39c93f"
MASTER_KEY       = "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"
# ============================================

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

# ================= RESELLER COMMANDS =================
@bot.message_handler(commands=["makereseller"])
def make_reseller(msg):
    if msg.from_user.id != ADMIN_ID: return
    try:
        args = msg.text.split()
        if len(args) < 2:
            return bot.reply_to(msg, "⚠️ Usage: `/makereseller <user_id> [discount%]`\nExample: `/makereseller 7778093775 40`", parse_mode="Markdown")
        target_uid = args[1].strip()
        discount = int(args[2]) if len(args) > 2 else DEFAULT_RESELLER_DISCOUNT
        
        db = load_db()
        if target_uid not in db["users"]:
            return bot.reply_to(msg, f"❌ User `{target_uid}` not found. Ensure they've used /start first.", parse_mode="Markdown")
        
        db["users"][target_uid]["discount"] = discount
        save_db(db)
        bot.reply_to(msg, f"✅ <b>Reseller Created!</b>\n\n👤 User: `{target_uid}`\n🏷️ Discount: <b>{discount}%</b>\n\nThey now see discounted prices automatically.", parse_mode="Markdown")
        
        try:
            bot.send_message(int(target_uid), f"🎉 <b>CONGRATULATIONS!</b>\n\nYou have been upgraded to <b>RESELLER</b> status!\n\n🏷️ You now get <b>{discount}% OFF</b> on every product.\n\nCheck the shop to see new prices!", parse_mode="HTML")
        except: pass
    except Exception as e:
        bot.reply_to(msg, f"❌ Error: {e}")

@bot.message_handler(commands=["removereseller"])
def remove_reseller(msg):
    if msg.from_user.id != ADMIN_ID: return
    try:
        args = msg.text.split()
        if len(args) < 2:
            return bot.reply_to(msg, "⚠️ Usage: `/removereseller <user_id>`", parse_mode="Markdown")
        target_uid = args[1].strip()
        db = load_db()
        if target_uid in db["users"]:
            db["users"][target_uid]["discount"] = 0
            save_db(db)
            bot.reply_to(msg, f"✅ Reseller status removed for `{target_uid}`", parse_mode="Markdown")
        else:
            bot.reply_to(msg, f"❌ User not found")
    except Exception as e:
        bot.reply_to(msg, f"❌ Error: {e}")

@bot.message_handler(commands=["resellerlist"])
def reseller_list(msg):
    if msg.from_user.id != ADMIN_ID: return
    db = load_db()
    resellers = [f"`{uid}` - {u.get('name','?')} ({u.get('discount',0)}%)" for uid, u in db.get("users", {}).items() if u.get("discount", 0) > 0]
    if not resellers:
        return bot.reply_to(msg, "📭 No resellers yet.")
    text = "👑 <b>ALL RESELLERS</b>\n━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(resellers)
    bot.reply_to(msg, text, parse_mode="Markdown")

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
            reseller_tag = "👑 <b>RESELLER ACCOUNT</b>\n" if discount > 0 else ""
            text = f"👤 <b>MY PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━\n{reseller_tag}🆔 <b>ID:</b> <code>{uid}</code>\n💵 <b>Balance:</b> ₹{bal:.2f}\n"
            if discount > 0: text += f"🏷️ <b>Discount:</b> {discount}% OFF\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n"
            kb = InlineKeyboardMarkup(row_width=1)
            if user_orders:
                text += "📜 <b>Recent Purchases:</b>\n\n"
                for i, o in enumerate(user_orders[::-1], 1):
                    text += f"{i}. <b>{o['product']}</b>\n   🔑 <code>{o['key']}</code>\n\n"
                    kb.add(InlineKeyboardButton(f"📋 Copy Key {i}", callback_data=f"copykey_{o['key']}"))
            else: text += "📭 <i>No purchases yet.</i>\n"
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
            discount = get_discount(uid)
            header = "👑 <b>RESELLER STORE</b>" if discount > 0 else "🛒 <b>STORE</b>"
            text = f"{header}\n━━━━━━━━━━━━━━━━━━━━\n👇 Select a product:"
            kb = InlineKeyboardMarkup(row_width=1)
            for p_id, p_info in products.items():
                kb.add(InlineKeyboardButton(f"📦 {p_info['name']}", callback_data=f"view_{p_id}"))
            kb.add(InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back"))
            safe_edit(chat_id, msg_id, text, kb)
        elif data.startswith("view_"):
            p_id = data.split("_")[1]
            product = load_products().get(p_id)
            discount = get_discount(uid)
            text = f"📦 <b>{product['name']}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            if discount > 0: text += f"👑 <b>RESELLER PRICES ({discount}% OFF)</b>\n"
            text += "👇 <i>Select Duration:</i>\n"
            kb = InlineKeyboardMarkup(row_width=2)
            row = []
            if product.get("video"): row.append(InlineKeyboardButton("📺 Setup Video", url=product["video"]))
            if product.get("hack"): row.append(InlineKeyboardButton("🛠️ Hack Video", url=product["hack"]))
            if row: kb.add(*row)
            for dur, price in product["prices"].items():
                final_price = price - (price * discount / 100) if discount > 0 else price
                btn_text = f"⏱ {dur} - ₹{final_price:.2f}" + (" 👑" if discount > 0 else "")
                kb.add(InlineKeyboardButton(btn_text, callback_data=f"buy_{p_id}_{dur}"))
            kb.add(InlineKeyboardButton("🔙 Back", callback_data="menu_shop"))
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
                text = f"❌ <b>LOW BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━\n💵 You have: <b>₹{bal:.2f}</b>\n💸 Required: <b>₹{final_price:.2f}</b>"
                kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("💸 Add Balance", callback_data="menu_addfund"), InlineKeyboardButton("🔙 Back", callback_data="menu_shop"))
                bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
                return
            if product.get("is_v1"):
                msg = bot.send_message(chat_id, "📱 <b>Enter your Android ID:</b>", parse_mode="HTML")
                bot.register_next_step_handler(msg, process_android_id, p_id, duration, final_price)
            else:
                wait = bot.send_message(chat_id, "⚡ <i>Generating Key...</i>", parse_mode="HTML")
                execute_api_buy(chat_id, wait.message_id, uid, p_id, duration, final_price, android_id=None)
        elif data.startswith("copykey_"):
            bot.answer_callback_query(call.id, f"✅ Key: {data.split('_', 1)[1]}\n\n(Tap to copy)", show_alert=True)
    except Exception as e: print(f"Callback Error: {e}")

def show_calc(chat_id, msg_id, uid):
    current = calc_data.get(uid, "")
    display = f"₹{current}" if current else "₹0"
    text = f"🧮 <b>CALCULATOR</b>\n━━━━━━━━━━━━━━━━━━━━\n💰 <b>Amount:</b> <code>{display}</code>\n⚠️ Min: ₹5"
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
    execute_api_buy(msg.chat.id, wait.message_id, msg.from_user.id, p_
                
