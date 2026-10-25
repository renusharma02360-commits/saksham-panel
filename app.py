import os
import time
import threading
import requests
import urllib.parse
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from famgateway import FamGateway
from flask import Flask, request
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson.objectid import ObjectId

# ================== CONFIG ==================
BOT_TOKEN = "8807309763:AAEXX_0tVMslGImWCBkeKscBheg4io4gf6g"
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
if not MONGO_URI:
    print("WARNING: MONGO_URI is not set in Environment Variables!")

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
        default_s = {"_id": "global", "store_name": "SAKSHAM STORE", "support_username": "YourSupport", "update_link": "https://t.me/", "maintenance": "false", "reseller_price": 149, "reseller_discount": 40}
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
        bot.reply_to(msg, "🚧 <b>Bot is currently under maintenance.</b>\n\n<i>Please try again later.</i>", parse_mode="HTML")
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
        bot.send_message(chat_id, "🚧 <b>Bot is currently under maintenance.</b>", parse_mode="HTML")
        return

    try:
        if data == "menu_back":
            text, kb = get_main_menu(uid, name)
            safe_edit(chat_id, msg_id, text, kb)
            
        elif data == "menu_balance":
            bal, discount = get_balance(uid), get_discount(uid)
            user_orders = list(orders_col.find({"uid": str(uid)}).sort("_id", -1).limit(5))
            reseller_tag = "👑 <b>RESELLER ACCOUNT</b>\n" if discount > 0 else ""
            text = f"👤 <b>MY PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━\n{reseller_tag}🆔 <b>ID:</b> <code>{uid}</code>\n💵 <b>Balance:</b> ₹{bal:.2f}\n"
            if discount > 0: text += f"🏷️ <b>Discount:</b> {discount}% OFF\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n"
            
            kb = InlineKeyboardMarkup(row_width=1)
            if user_orders:
                text += "📜 <b>Recent Purchases:</b>\n\n"
                for i, o in enumerate(user_orders, 1):
                    text += f"{i}. <b>{o['product']}</b>\n   🔑 <code>{o['key']}</code>\n\n"
                    if o['key'] != "WhatsApp Manual":
                        kb.add(InlineKeyboardButton(f"📋 Copy Key {i}", callback_data=f"copykey_{o['key']}"))
            else: 
                text += "📭 <i>No purchases yet.</i>\n"
            kb.add(InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back"))
            safe_edit(chat_id, msg_id, text, kb)
            
        elif data == "menu_addfund":
            text = f"💸 <b>ADD BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━\nSelect amount or enter custom:"
            kb = InlineKeyboardMarkup(row_width=3).add(InlineKeyboardButton("₹10", callback_data="amt_10"), InlineKeyboardButton("₹50", callback_data="amt_50"), InlineKeyboardButton("₹100", callback_data="amt_100")).add(InlineKeyboardButton("🧮 Custom Amount", callback_data="amt_custom")).add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
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
                generate_wallet_qr(chat_id, uid, float(current), name)
                if uid in calc_data: del calc_data[uid]
                return
            else:
                if len(current) < 5: current += action
            calc_data[uid] = current
            show_calc(chat_id, msg_id, uid)
            
        elif data.startswith("amt_"):
            amount = float(data.split("_")[1])
            safe_edit(chat_id, msg_id, f"⚡ <i>Generating Secure UPI QR for ₹{amount}...</i>")
            generate_wallet_qr(chat_id, uid, amount, name)
            
        elif data == "buy_reseller":
            price = settings.get("reseller_price", 149)
            text = f"👑 <b>BUY RESELLER ACCESS</b>\n━━━━━━━━━━━━━━━━━━━━\n💰 <b>Price:</b> ₹{price}\n🏷️ <b>Benefits:</b> Get {settings.get('reseller_discount', 40)}% OFF on all products!\n\nClick below to pay:"
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton(f"💳 Pay ₹{price} Now", callback_data="pay_reseller")).add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
            safe_edit(chat_id, msg_id, text, kb)
            
        elif data == "pay_reseller":
            price = settings.get("reseller_price", 149)
            safe_edit(chat_id, msg_id, f"⚡ <i>Generating Secure UPI QR for ₹{price}...</i>")
            generate_reseller_qr(chat_id, uid, price, name)
            
        elif data == "menu_shop":
            products = list(products_col.find({}))
            if not products:
                safe_edit(chat_id, msg_id, "🛒 <b>Store is empty!</b>", InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="menu_back")))
                return
            discount = get_discount(uid)
            header = "👑 <b>RESELLER STORE</b>" if discount > 0 else "🛒 <b>STORE</b>"
            text = f"{header}\n━━━━━━━━━━━━━━━━━━━━\n👇 Select a product to view:"
            kb = InlineKeyboardMarkup(row_width=1)
            for p in products:
                maint = " 🔴 [MAINTENANCE]" if p.get("is_maintenance") else ""
                kb.add(InlineKeyboardButton(f"📦 {p['name']}{maint}", callback_data=f"view_{str(p['_id'])}"))
            kb.add(InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back"))
            safe_edit(chat_id, msg_id, text, kb)
            
        elif data.startswith("view_"):
            p_id = data.split("_")[1]
            product = products_col.find_one({"_id": ObjectId(p_id)})
            
            if product.get("is_maintenance"):
                bot.answer_callback_query(call.id, "🚧 This product is currently under maintenance. Please try later.", show_alert=True)
                return

            discount = get_discount(uid)
            text = f"📦 <b>{product['name']}</b>\n"
            if product.get("description"): text += f"📝 <i>{product['description']}</i>\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n"
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
            kb.add(InlineKeyboardButton("🔙 Back to Shop", callback_data="menu_shop"))
            
            try: bot.delete_message(chat_id, msg_id)
            except: pass
            
            if product.get("image") and os.path.exists(product["image"]):
                with open(product["image"], "rb") as photo: 
                    msg = bot.send_photo(chat_id, photo=photo, caption=text, parse_mode="HTML", reply_markup=kb)
                    user_msg_history[chat_id] = [msg.message_id]
            else: 
                msg = bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
                user_msg_history[chat_id] = [msg.message_id]
                
        elif data.startswith("buy_"):
            parts = data.split("_", 2)
            p_id, duration = parts[1], parts[2]
            product = products_col.find_one({"_id": ObjectId(p_id)})
            
            if product.get("is_maintenance"):
                bot.answer_callback_query(call.id, "🚧 This product is currently under maintenance.", show_alert=True)
                return

            original_price = float(product["prices"].get(duration, 0))
            discount = get_discount(uid)
            final_price = original_price - (original_price * discount / 100) if discount > 0 else original_price
            
            try: bot.delete_message(chat_id, msg_id)
            except: pass

            if product.get("redirect_to_wp"):
                if deduct_balance(uid, final_price):
                    log_order(uid, product['name'], "WhatsApp Manual", final_price)
                    wa_text = f"Hello Admin, I want to purchase {duration} {product['name']}. Please provide the key."
                    wa_link = f"https://wa.me/{ADMIN_WP}?text={urllib.parse.quote(wa_text)}"
                    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("💬 Contact Admin on WhatsApp", url=wa_link)).add(InlineKeyboardButton("🔙 Menu", callback_data="menu_back"))
                    
                    success_text = (
                        f"✅ <b>PAYMENT SUCCESSFUL</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"📦 <b>Product:</b> {product['name']}\n"
                        f"⏱ <b>Duration:</b> {duration}\n"
                        f"💵 <b>Price:</b> ₹{final_price:.2f}\n"
                        f"💼 <b>New Balance:</b> ₹{get_balance(uid):.2f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"👇 <i>Click the button below to get your key.</i>"
                    )
                    send_menu(chat_id, success_text, kb)
                else:
                    bot.send_message(chat_id, "❌ <b>Low Balance! Please add funds first.</b>", parse_mode="HTML")
                return
            else:
                if product.get("is_v1"):
                    msg = bot.send_message(chat_id, "📱 <b>Enter your Android ID:</b>", parse_mode="HTML")
                    bot.register_next_step_handler(msg, process_android_id_direct_pay, p_id, duration, final_price)
                else:
                    wait = bot.send_message(chat_id, "⚡ <i>Generating Product UPI QR...</i>", parse_mode="HTML")
                    generate_product_qr(chat_id, wait.message_id, uid, p_id, duration, final_price, None)

        elif data.startswith("copykey_"):
            bot.answer_callback_query(call.id, f"✅ Key: {data.split('_', 1)[1]}\n\n(Tap to copy)", show_alert=True)
            
        elif data.startswith("cancel_qr_"):
            try: bot.delete_message(chat_id, msg_id)
            except: pass
            text, kb = get_main_menu(uid, name)
            send_menu(chat_id, "❌ <b>Payment Cancelled.</b>", kb)
            
    except Exception as e: print(f"Callback Error: {e}")

def show_calc(chat_id, msg_id, uid):
    current = calc_data.get(uid, "")
    display = f"₹{current}" if current else "₹0"
    text = f"🧮 <b>CALCULATOR</b>\n━━━━━━━━━━━━━━━━━━━━\n💰 <b>Amount:</b> <code>{display}</code>\n⚠️ Min: ₹5"
    kb = InlineKeyboardMarkup(row_width=3).add(InlineKeyboardButton("1", callback_data="calc_1"), InlineKeyboardButton("2", callback_data="calc_2"), InlineKeyboardButton("3", callback_data="calc_3"), InlineKeyboardButton("4", callback_data="calc_4"), InlineKeyboardButton("5", callback_data="calc_5"), InlineKeyboardButton("6", callback_data="calc_6"), InlineKeyboardButton("7", callback_data="calc_7"), InlineKeyboardButton("8", callback_data="calc_8"), InlineKeyboardButton("9", callback_data="calc_9"), InlineKeyboardButton("🧹 AC", callback_data="calc_ac"), InlineKeyboardButton("0", callback_data="calc_0"), InlineKeyboardButton("❌ X", callback_data="calc_cut")).add(InlineKeyboardButton("✅ Done / Pay", callback_data="calc_done")).add(InlineKeyboardButton("🔙 Back", callback_data="menu_addfund"))
    safe_edit(chat_id, msg_id, text, kb)

# ================== WALLET ADD FUND ==================
def generate_wallet_qr(chat_id, uid, amount, name):
    try: order = fg.create_order(amount=amount, customer_name=name or "User")
    except Exception as e:
        bot.send_message(chat_id, f"❌ <b>API Error:</b> <code>{str(e)}</code>", parse_mode="HTML")
        return
    uid = str(uid)
    caption = f"💳 <b>ADD BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━\n🆔 <b>Order ID:</b> <code>{order.order_id}</code>\n💵 <b>Amount:</b> ₹{float(order.payable_amount):.2f}\n━━━━━━━━━━━━━━━━━━━━\n\n📲 <i>Scan the QR above to pay.</i>\n✅ <b>Auto-verify ON</b>"
    
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Cancel / Back", callback_data="cancel_qr_back"))
    
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

# Dummy placeholders for missing functions from original snippet
def process_android_id_direct_pay(msg, p_id, duration, final_price):
    pass

def generate_product_qr(chat_id, msg_id, uid, p_id, duration, final_price, context):
    pass

def generate_reseller_qr(chat_id, uid, price, name):
    pass

# ================== FLASK WEB SERVER (Render Fix) ==================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!", 200

def run_bot():
    print("Starting Telegram Bot...")
    bot.polling(none_stop=True)

if __name__ == "__main__":
    # Start the Telegram Bot in a separate thread
    threading.Thread(target=run_bot, daemon=True).start()
    
    # Start the Flask Web Server for Render
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
