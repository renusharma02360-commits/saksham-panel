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
BOT_TOKEN = "8807309763:AAEXX_0tVMslGImWCBkeKscBheg4io4gf6g"
API_KEY   = "fam_4c308a3f58df8f752e41770178d877982e4e1a58"
ADMIN_ID  = 7778093775
ADMIN_WP  = "919306606011" # Aapka WhatsApp Number
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
user_msg_history = {} # Tracks old message IDs to delete them

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
    user = users_col.find_one({"_id": str(uid)})
    if user and user["balance"] >= amount:
        users_col.update_one({"_id": str(uid)}, {"$inc": {"balance": -amount}})
        return True
    return False

def credit_atomic(uid, amount, utr):
    if orders_col.find_one({"utr": utr}):
        return False, get_balance(uid)
    orders_col.insert_one({"utr": utr, "uid": str(uid), "amount": amount, "time": time.strftime("%d-%m-%Y %I:%M %p")})
    return True, credit_balance(uid, amount)

def log_order(uid, product, key, price):
    orders_col.insert_one({"uid": str(uid), "product": product, "key": key, "price": price, "time": time.strftime("%d-%m-%Y %I:%M %p")})

# ================== MAIN MENU ==================
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

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    uid, data, name = call.from_user.id, call.data, call.from_user.first_name
    msg_id, chat_id = call.message.message_id, call.message.chat.id
    settings = get_settings()
    
    if settings.get("maintenance", "false") == "true" and str(uid) != str(ADMIN_ID):
        bot.answer_callback_query(call.id, "🚧 Bot is currently under maintenance.", show_alert=True)
        return
    bot.answer_callback_query(call.id)

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
            text = f"{header}\n━━━━━━━━━━━━━━━━━━━━\n👇 Select a product:"
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
            if product.get("description"): text += f"📝 {product['description']}\n"
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
            kb.add(InlineKeyboardButton("🔙 Back", callback_data="menu_shop"))
            
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

            # DIRECT UPI PAYMENT FOR PRODUCT
            if product.get("redirect_to_wp"):
                # WhatsApp Flow
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
                # API Flow with Direct Pay
                if product.get("is_v1"):
                    msg = bot.send_message(chat_id, "📱 <b>Enter your Android ID:</b>", parse_mode="HTML")
                    bot.register_next_step_handler(msg, process_android_id_direct_pay, p_id, duration, final_price)
                else:
                    wait = bot.send_message(chat_id, "⚡ <i>Generating Product UPI QR...</i>", parse_mode="HTML")
                    generate_product_qr(chat_id, wait.message_id, uid, p_id, duration, final_price, None)

        elif data.startswith("copykey_"):
            bot.answer_callback_query(call.id, f"✅ Key: {data.split('_', 1)[1]}\n\n(Tap to copy)", show_alert=True)
            
        elif data.startswith("cancel_qr_"):
            bot.delete_message(chat_id, msg_id)
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
            try: bot.delete_message(chat_id=chat_id, message_id=photo_msg_id)
            except: pass
            bot.send_message(chat_id, f"⌛ <b>Order Expired.</b>", parse_mode="HTML")
            return

# ================== RESELLER QR ==================
def generate_reseller_qr(chat_id, uid, amount, name):
    try: order = fg.create_order(amount=amount, customer_name=f"Reseller_{name}")
    except Exception as e:
        bot.send_message(chat_id, f"❌ <b>API Error:</b> <code>{str(e)}</code>", parse_mode="HTML")
        return
    uid = str(uid)
    caption = f"👑 <b>RESELLER PURCHASE</b>\n━━━━━━━━━━━━━━━━━━━━\n🆔 <b>Order ID:</b> <code>{order.order_id}</code>\n💵 <b>Amount:</b> ₹{float(order.payable_amount):.2f}\n━━━━━━━━━━━━━━━━━━━━\n\n📲 <i>Scan the QR above to pay.</i>\n✅ <b>Auto-verify ON</b>"
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Cancel / Back", callback_data="cancel_qr_back"))
    
    sent_photo = bot.send_photo(chat_id, photo=order.qr_url, caption=caption, parse_mode="HTML", reply_markup=kb)
    sent_wait = bot.send_message(chat_id, f"🔄 <b>Verifying Payment...</b>", parse_mode="HTML")
    threading.Thread(target=poll_reseller_status, args=(order.order_id, uid, chat_id, sent_wait.message_id, sent_photo.message_id), daemon=True).start()

def poll_reseller_status(order_id, uid, chat_id, wait_msg_id, photo_msg_id):
    start_ts = time.time()
    settings = get_settings()
    discount = settings.get("reseller_discount", 40)
    while time.time() - start_ts < 360:
        time.sleep(2)
        try: status = fg.get_status(order_id)
        except: continue
        if status.is_paid:
            users_col.update_one({"_id": str(uid)}, {"$set": {"discount": discount}})
            try: bot.delete_message(chat_id=chat_id, message_id=wait_msg_id)
            except: pass
            try: bot.delete_message(chat_id=chat_id, message_id=photo_msg_id)
            except: pass
            text, kb = get_main_menu(uid, "User")
            send_menu(chat_id, f"🎉 <b>CONGRATULATIONS!</b>\nYou are now an official <b>RESELLER</b>!\n🏷️ You get <b>{discount}% OFF</b> on all products.", kb)
            return
        if status.is_expired:
            try: bot.delete_message(chat_id=chat_id, message_id=wait_msg_id)
            except: pass
            try: bot.delete_message(chat_id=chat_id, message_id=photo_msg_id)
            except: pass
            bot.send_message(chat_id, f"⌛ <b>Order Expired.</b>", parse_mode="HTML")
            return

# ================== DIRECT PRODUCT PAYMENT & API ==================
def process_android_id_direct_pay(msg, p_id, duration, price):
    android_id = msg.text.strip()
    if len(android_id) < 10: return bot.reply_to(msg, "❌ <b>Invalid Android ID!</b>", parse_mode="HTML")
    wait = bot.reply_to(msg, "⚡ <i>Generating Product UPI QR...</i>", parse_mode="HTML")
    generate_product_qr(msg.chat.id, wait.message_id, msg.from_user.id, p_id, duration, price, android_id)

def generate_product_qr(chat_id, wait_msg_id, uid, p_id, duration, price, android_id):
    try: 
        order = fg.create_order(amount=price, customer_name=f"Product_{p_id}")
    except Exception as e:
        try: bot.delete_message(chat_id, wait_msg_id)
        except: pass
        bot.send_message(chat_id, f"❌ <b>API Error:</b> <code>{str(e)}</code>", parse_mode="HTML")
        return
        
    caption = (
        f"🛒 <b>PRODUCT CHECKOUT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Amount to Pay:</b> ₹{float(order.payable_amount):.2f}\n"
        f"⏱ <b>Duration:</b> {duration}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📲 <i>Scan the QR above to pay for this product.</i>\n"
        f"✅ <b>Key will be generated instantly after payment.</b>"
    )
    
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Cancel Payment", callback_data="cancel_qr_back"))
    
    try: bot.delete_message(chat_id, wait_msg_id)
    except: pass
    
    sent_photo = bot.send_photo(chat_id, photo=order.qr_url, caption=caption, parse_mode="HTML", reply_markup=kb)
    sent_wait = bot.send_message(chat_id, f"🔄 <b>Waiting for Payment...</b>", parse_mode="HTML")
    
    threading.Thread(target=poll_product_status, args=(order.order_id, str(uid), chat_id, sent_wait.message_id, sent_photo.message_id, p_id, duration, price, android_id), daemon=True).start()

def poll_product_status(order_id, uid, chat_id, wait_msg_id, photo_msg_id, p_id, duration, price, android_id):
    start_ts = time.time()
    while time.time() - start_ts < 360:
        time.sleep(2)
        try: status = fg.get_status(order_id)
        except: continue
        
        if status.is_paid:
            try: bot.delete_message(chat_id=chat_id, message_id=wait_msg_id)
            except: pass
            try: bot.delete_message(chat_id=chat_id, message_id=photo_msg_id)
            except: pass
            
            # CALL BANTI API
            product = products_col.find_one({"_id": ObjectId(p_id)})
            clean_pid = str(product["pid"]).strip()
            clean_dur = str(duration).strip()
            data = {'api_key': RESELLER_API_KEY, 'action': 'buy', 'product_id': clean_pid, 'duration': clean_dur, 'quantity': 1}
            if android_id: data['android_id'] = android_id
            headers = {'Content-Type': 'application/x-www-form-urlencoded', 'x-master-key': MASTER_KEY, 'User-Agent': 'Mozilla/5.0'}
            
            res = requests.post(RESELLER_API_URL, data=data, headers=headers, timeout=20)
            try: result = res.json()
            except: result = {"status": "error", "message": f"Invalid Response: {res.text[:100]}"}
            
            if result.get("status") == "success" or "keys" in result:
                keys = result.get("keys", ["Key not found"])
                log_order(uid, product['name'], keys[0], price)
                kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("📋 Copy Key", callback_data=f"copykey_{keys[0]}"), InlineKeyboardButton("🔙 Menu", callback_data="menu_back"))
                success_text = f"✅ <b>PURCHASE SUCCESSFUL</b>\n📦 <b>Product:</b> {product['name']}\n⏱ <b>Duration:</b> {duration}\n💵 <b>Paid:</b> ₹{price:.2f}\n🔑 <b>Key:</b>\n<code>{keys[0]}</code>"
                send_menu(chat_id, success_text, kb)
            else: 
                # 🔥 AUTO REFUND IF STOCK OUT / API FAILS
                new_bal = credit_balance(uid, price)
                err_msg = result.get("message", str(result))
                refund_text = (
                    f"❌ <b>PURCHASE FAILED (STOCK OUT)</b>\n\n"
                    f"<b>API Error:</b> <code>{err_msg}</code>\n\n"
                    f"💵 <b>₹{price:.2f} Refunded to your Wallet.</b>\n"
                    f"💼 <b>New Balance:</b> ₹{new_bal:.2f}\n\n"
                    f"<i>You can try buying later or contact support.</i>"
                )
                kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Menu", callback_data="menu_back"))
                send_menu(chat_id, refund_text, kb)
            return
            
        if status.is_expired:
            try: bot.delete_message(chat_id=chat_id, message_id=wait_msg_id)
            except: pass
            try: bot.delete_message(chat_id=chat_id, message_id=photo_msg_id)
            except: pass
            bot.send_message(chat_id, f"⌛ <b>Order Expired.</b>", parse_mode="HTML")
            return

@bot.callback_query_handler(func=lambda call: call.data == "cancel_qr_back")
def cb_cancel_qr(call):
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
    text, kb = get_main_menu(call.from_user.id, call.from_user.first_name)
    send_menu(call.message.chat.id, text, kb)

# ================== FLASK SETUP (WEB PANEL) ==================
app = Flask(__name__)
app.secret_key = "saksham_secret"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Saksham Panel Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;800&display=swap');
        * { box-sizing: border-box; font-family: 'Poppins', sans-serif; margin: 0; padding: 0; }
        body { background: #0b0f19; color: #e2e8f0; min-height: 100vh; background-image: radial-gradient(circle at 50% -20%, #1e1b4b, #0b0f19 50%); padding-bottom: 50px; }
        .container { max-width: 1100px; margin: 0 auto; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; padding: 20px 0; border-bottom: 1px solid rgba(255,255,255,0.1); }
        .header h1 { font-size: 28px; font-weight: 800; background: linear-gradient(90deg, #38bdf8, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .tabs { display: flex; gap: 10px; margin-bottom: 30px; flex-wrap: wrap; }
        .tab-btn { background: rgba(30, 41, 59, 0.8); color: #94a3b8; padding: 12px 20px; border-radius: 10px; text-decoration: none; font-weight: 600; font-size: 14px; transition: 0.3s; border: 1px solid transparent; }
        .tab-btn:hover { background: rgba(56, 189, 248, 0.1); color: #38bdf8; }
        .tab-btn.active { background: #0ea5e9; color: white; box-shadow: 0 4px 15px rgba(14, 165, 233, 0.4); }
        .card { background: rgba(30, 41, 59, 0.6); backdrop-filter: blur(10px); padding: 30px; border-radius: 16px; margin-bottom: 25px; border: 1px solid rgba(255,255,255,0.05); box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
        .card h3 { color: #38bdf8; margin-bottom: 20px; font-weight: 600; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 8px; font-size: 14px; color: #94a3b8; }
        input, select, textarea { width: 100%; padding: 12px 15px; border-radius: 8px; border: 1px solid #334155; background: rgba(15, 23, 42, 0.8); color: white; outline: none; transition: 0.3s; }
        input:focus, select:focus, textarea:focus { border-color: #38bdf8; box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2); }
        button { padding: 14px 20px; background: linear-gradient(90deg, #0ea5e9, #3b82f6); color: white; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; width: 100%; transition: 0.3s; font-size: 15px; }
        button:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(14, 165, 233, 0.3); }
        .btn-danger { background: linear-gradient(90deg, #ef4444, #dc2626); padding: 8px 15px; width: auto; margin: 0; font-size: 12px; }
        .btn-warning { background: linear-gradient(90deg, #f59e0b, #d97706); padding: 8px 15px; width: auto; margin: 0; font-size: 12px; color: #000; }
        .btn-success { background: linear-gradient(90deg, #10b981, #059669); padding: 8px 15px; width: auto; margin: 0; font-size: 12px; }
        .row { display: flex; gap: 15px; flex-wrap: wrap; }
        .row .form-group { flex: 1; min-width: 200px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 15px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.05); }
        th { color: #38bdf8; font-weight: 600; font-size: 14px; }
        td { font-size: 14px; color: #cbd5e1; }
        .badge { background: #f59e0b; color: #000; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 800; display: inline-block; margin-top: 5px; }
        .badge-red { background: #ef4444; color: white; }
        .badge-green { background: #10b981; color: white; }
        .badge-blue { background: #38bdf8; color: #000; }
        .alert-success { background: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; color: #10b981; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-weight: 600; }
        .alert-danger { background: rgba(239, 68, 68, 0.2); border: 1px solid #ef4444; color: #ef4444; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-weight: 600; }
        .product-item { display: flex; justify-content: space-between; align-items: center; padding: 15px; background: rgba(15, 23, 42, 0.5); border-radius: 10px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.05); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>👑 Saksham Panel Admin</h1>
            <a href="/" style="color:#94a3b8; text-decoration:none; font-size:14px;">Refresh</a>
        </div>
        <div class="tabs">
            <a href="/" class="tab-btn {% if tab == 'products' %}active{% endif %}">📦 Products</a>
            <a href="/users" class="tab-btn {% if tab == 'users' %}active{% endif %}">👥 Users & Resellers</a>
            <a href="/orders" class="tab-btn {% if tab == 'orders' %}active{% endif %}">📜 All History</a>
            <a href="/broadcast" class="tab-btn {% if tab == 'broadcast' %}active{% endif %}">📢 Broadcast</a>
            <a href="/settings" class="tab-btn {% if tab == 'settings' %}active{% endif %}">⚙️ Settings</a>
        </div>
        {% if msg_success %}<div class="alert-success">{{ msg_success }}</div>{% endif %}
        {% if msg_error %}<div class="alert-danger">{{ msg_error }}</div>{% endif %}

        {% if tab == 'products' %}
        <div class="card">
            <h3>➕ Add New Product</h3>
            <form action="/add_product" method="POST" enctype="multipart/form-data">
                <div class="row">
                    <div class="form-group"><label>Product Name</label><input type="text" name="name" required></div>
                    <div class="form-group"><label>PID</label><input type="text" name="pid" required></div>
                </div>
                <div class="form-group"><label>Description / Hack Features (Optional)</label><input type="text" name="description" placeholder="e.g. Aimbot, ESP, No Recoil"></div>
                <div class="form-group"><label>Product Image</label><input type="file" name="image_file" accept="image/*"></div>
                <div class="row">
                    <div class="form-group"><label>Setup Video Link</label><input type="url" name="video" placeholder="https://youtube.com/..."></div>
                    <div class="form-group"><label>Hack Video Link</label><input type="url" name="hack" placeholder="https://youtube.com/..."></div>
                </div>
                <div class="row">
                    <div class="form-group">
                        <label>Device Type</label>
                        <select name="is_v1"><option value="false">V2 (Direct Key)</option><option value="true">V1 (Requires Android ID)</option></select>
                    </div>
                    <div class="form-group">
                        <label>Key Delivery Method</label>
                        <select name="redirect_to_wp"><option value="false">🤖 Bot Auto-Delivery (API)</option><option value="true">💬 Manual WhatsApp Delivery</option></select>
                    </div>
                    <div class="form-group">
                        <label>Maintenance Mode</label>
                        <select name="is_maintenance"><option value="false">🟢 Active (ON)</option><option value="true">🔴 Disable (OFF)</option></select>
                    </div>
                </div>
                
                <label style="margin-top: 10px; display:block;">Durations & Prices</label>
                <div id="price-container">
                    <div class="row">
                        <div class="form-group">
                            <select name="duration[]" required style="margin-bottom: 5px;">
                                <option value="">-- Select Duration --</option>
                                <option value="1 Hours">1 Hours</option>
                                <option value="3 Hours">3 Hours</option>
                                <option value="6 Hours">6 Hours</option>
                                <option value="12 Hours">12 Hours</option>
                                <option value="1 DaYs">1 DaYs</option>
                                <option value="3 DaYs">3 DaYs</option>
                                <option value="7 DaYs">7 DaYs</option>
                                <option value="15 DaYs">15 DaYs</option>
                                <option value="30 DaYs">30 DaYs</option>
                                <option value="CUSTOM">✍️ Custom (Type below)</option>
                            </select>
                            <input type="text" name="duration[]" placeholder="Or type custom duration (e.g. 1 DaYs)" style="font-size: 12px;" required>
                        </div>
                        <div class="form-group"><input type="number" name="price[]" required placeholder="Price"></div>
                    </div>
                </div>
                <button type="button" class="btn-success" onclick="addPriceRow()" style="margin-bottom:10px; width:auto;">➕ More</button>
                <button type="submit">💾 Save Product</button>
            </form>
        </div>
        <div class="card">
            <h3>📦 All Products ({{ products|length }})</h3>
            {% for p in products %}
            <div class="product-item">
                <div>
                    <strong style="color:#fff; font-size:16px;">{{ p.name }}</strong> 
                    <span style="color:#64748b; font-size:12px;">(PID: {{ p.pid }})</span><br>
                    {% if p.get('is_maintenance') %}<span class="badge badge-red">MAINTENANCE</span>{% else %}<span class="badge badge-green">ACTIVE</span>{% endif %}
                    {% if p.get('redirect_to_wp') %}<span class="badge badge-blue">MANUAL (WA)</span>{% else %}<span class="badge">AUTO (API)</span>{% endif %}
                    <br>
                    <small style="color:#94a3b8;">{% for d, pr in p.prices.items() %}{{d}}: ₹{{pr}} | {% endfor %}</small>
                </div>
                <div style="display:flex; gap:10px; flex-wrap: wrap;">
                    <a href="/toggle_maintenance/{{ p._id }}"><button class="btn-warning" style="padding:8px 15px;">{% if p.get('is_maintenance') %}Enable{% else %}Disable{% endif %}</button></a>
                    <a href="/edit_product/{{ p._id }}"><button class="btn-warning" style="padding:8px 15px;">✏️ Edit</button></a>
                    <a href="/delete_product/{{ p._id }}"><button class="btn-danger" style="padding:8px 15px;">🗑️ Delete</button></a>
                </div>
            </div>
            {% endfor %}
        </div>

        {% elif tab == 'edit_product' %}
        <div class="card">
            <h3>✏️ Edit Product: {{ product.name }}</h3>
            <form action="/update_product/{{ product._id }}" method="POST" enctype="multipart/form-data">
                <div class="row">
                    <div class="form-group"><label>Name</label><input type="text" name="name" value="{{ product.name }}" required></div>
                    <div class="form-group"><label>PID</label><input type="text" name="pid" value="{{ product.pid }}" required></div>
                </div>
                <div class="form-group"><label>Description / Hack Features</label><input type="text" name="description" value="{{ product.get('description', '') }}"></div>
                <div class="form-group"><label>Image (Leave blank to keep old)</label><input type="file" name="image_file" accept="image/*"></div>
                <div class="row">
                    <div class="form-group"><label>Setup Video</label><input type="url" name="video" value="{{ product.video or '' }}"></div>
                    <div class="form-group"><label>Hack Video</label><input type="url" name="hack" value="{{ product.hack or '' }}"></div>
                </div>
                <div class="row">
                    <div class="form-group">
                        <label>Device Type</label>
                        <select name="is_v1"><option value="false" {% if not product.is_v1 %}selected{% endif %}>V2</option><option value="true" {% if product.is_v1 %}selected{% endif %}>V1</option></select>
                    </div>
                    <div class="form-group">
                        <label>Key Delivery Method</label>
                        <select name="redirect_to_wp">
                            <option value="false" {% if not product.get('redirect_to_wp') %}selected{% endif %}>🤖 Bot Auto-Delivery (API)</option>
                            <option value="true" {% if product.get('redirect_to_wp') %}selected{% endif %}>💬 Manual WhatsApp Delivery</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Maintenance Mode</label>
                        <select name="is_maintenance"><option value="false" {% if not product.get('is_maintenance') %}selected{% endif %}>🟢 Active (ON)</option><option value="true" {% if product.get('is_maintenance') %}selected{% endif %}>🔴 Disable (OFF)</option></select>
                    </div>
                </div>
                <label>Durations & Prices</label>
                <div id="price-container">
                    {% for dur, pr in product.prices.items() %}
                    <div class="row">
                        <div class="form-group">
                            <select name="duration_select[]" style="margin-bottom: 5px;">
                                <option value="">-- Select --</option>
                                <option value="1 Hours" {% if dur=='1 Hours' %}selected{% endif %}>1 Hours</option>
                                <option value="3 Hours" {% if dur=='3 Hours' %}selected{% endif %}>3 Hours</option>
                                <option value="6 Hours" {% if dur=='6 Hours' %}selected{% endif %}>6 Hours</option>
                                <option value="12 Hours" {% if dur=='12 Hours' %}selected{% endif %}>12 Hours</option>
                                <option value="1 DaYs" {% if dur=='1 DaYs' %}selected{% endif %}>1 DaYs</option>
                                <option value="3 DaYs" {% if dur=='3 DaYs' %}selected{% endif %}>3 DaYs</option>
                                <option value="7 DaYs" {% if dur=='7 DaYs' %}selected{% endif %}>7 DaYs</option>
                                <option value="15 DaYs" {% if dur=='15 DaYs' %}selected{% endif %}>15 DaYs</option>
                                <option value="30 DaYs" {% if dur=='30 DaYs' %}selected{% endif %}>30 DaYs</option>
                                <option value="CUSTOM" {% if dur not in ['1 Hours','3 Hours','6 Hours','12 Hours','1 DaYs','3 DaYs','7 DaYs','15 DaYs','30 DaYs'] %}selected{% endif %}>✍️ Custom</option>
                            </select>
                            <input type="text" name="duration[]" value="{{ dur }}" placeholder="Custom Duration" style="font-size: 12px;">
                        </div>
                        <div class="form-group"><input type="number" name="price[]" value="{{ pr }}" required></div>
                    </div>
                    {% endfor %}
                </div>
                <button type="button" class="btn-success" onclick="addPriceRow()" style="margin-bottom:10px; width:auto;">➕ More</button>
                <button type="submit" style="background:linear-gradient(90deg, #f59e0b, #d97706); color:#000;">💾 Update</button>
                <a href="/" style="display:block; text-align:center; margin-top:15px; color:#94a3b8; text-decoration:none;">Cancel</a>
            </form>
        </div>

        {% elif tab == 'users' %}
        <div class="card">
            <h3>👥 Users & Resellers</h3>
            <table>
                <tr><th>User ID</th><th>Name</th><th>Balance</th><th>Update</th></tr>
                {% for u in users %}
                <tr>
                    <td><code>{{ u._id }}</code></td>
                    <td>{{ u.name }} {% if u.get('discount',0)>0 %}<br><span class="badge">RESELLER ({{ u.get('discount') }}%)</span>{% endif %}</td>
                    <td style="color:#10b981; font-weight:600;">₹{{ u.balance }}</td>
                    <td>
                        <form action="/update_user" method="POST" style="display:flex; gap:10px;">
                            <input type="hidden" name="uid" value="{{ u._id }}">
                            <input type="number" name="amount" placeholder="+/- ₹" style="width:70px; padding:8px; margin:0;">
                            <input type="number" name="discount" value="{{ u.get('discount', 0) }}" placeholder="Disc%" style="width:70px; padding:8px; margin:0;">
                            <button type="submit" class="btn-success" style="padding:8px 15px;">Save</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </table>
        </div>

        {% elif tab == 'orders' %}
        <div class="card">
            <h3>📜 All Purchase History</h3>
            <table>
                <tr><th>Date/Time</th><th>User ID</th><th>Product</th><th>Price</th><th>Key</th></tr>
                {% for o in orders %}
                <tr><td><small>{{ o.time }}</small></td><td><code>{{ o.uid }}</code></td><td>{{ o.product }}</td><td style="color:#10b981;">₹{{ o.price }}</td><td><code>{{ o.key }}</code></td></tr>
                {% endfor %}
            </table>
        </div>

        {% elif tab == 'broadcast' %}
        <div class="card">
            <h3>📢 Send Message to All Users</h3>
            <form action="/send_broadcast" method="POST"><textarea name="message" rows="5" required></textarea><button type="submit" style="background:linear-gradient(90deg, #10b981, #059669);">🚀 Send</button></form>
        </div>

        {% elif tab == 'settings' %}
        <div class="card">
            <h3>⚙️ Bot Settings</h3>
            <form action="/settings" method="POST">
                <div class="row">
                    <div class="form-group"><label>Store Name</label><input type="text" name="store_name" value="{{ settings.get('store_name', '') }}"></div>
                    <div class="form-group"><label>Support Username</label><input type="text" name="support_username" value="{{ settings.get('support_username', '') }}"></div>
                </div>
                <div class="form-group"><label>Update Link</label><input type="url" name="update_link" value="{{ settings.get('update_link', '') }}"></div>
                <div class="row">
                    <div class="form-group"><label>Reseller Price (₹)</label><input type="number" name="reseller_price" value="{{ settings.get('reseller_price', 149) }}"></div>
                    <div class="form-group"><label>Reseller Discount (%)</label><input type="number" name="reseller_discount" value="{{ settings.get('reseller_discount', 40) }}"></div>
                </div>
                <div class="form-group">
                    <label>Global Bot Maintenance</label>
                    <select name="maintenance"><option value="false" {% if settings.get('maintenance')=='false' %}selected{% endif %}>🟢 ON (Working)</option><option value="true" {% if settings.get('maintenance')=='true' %}selected{% endif %}>🔴 OFF (Maintenance)</option></select>
                </div>
                <button type="submit">💾 Save Settings</button>
            </form>
        </div>
        {% endif %}
    </div>
    <script>
        function addPriceRow() { 
            const c = document.getElementById('price-container'); 
            const d = document.createElement('div'); 
            d.className='row'; 
            d.innerHTML=`<div class="form-group">
                            <select name="duration_select[]" style="margin-bottom: 5px;">
                                <option value="">-- Select --</option>
                                <option value="1 Hours">1 Hours</option>
                                <option value="3 Hours">3 Hours</option>
                                <option value="6 Hours">6 Hours</option>
                                <option value="12 Hours">12 Hours</option>
                                <option value="1 DaYs">1 DaYs</option>
                                <option value="3 DaYs">3 DaYs</option>
                                <option value="7 DaYs">7 DaYs</option>
                                <option value="15 DaYs">15 DaYs</option>
                                <option value="30 DaYs">30 DaYs</option>
                                <option value="CUSTOM">✍️ Custom</option>
                            </select>
                            <input type="text" name="duration[]" placeholder="Custom Duration" style="font-size: 12px;">
                        </div>
                        <div class="form-group"><input type="number" name="price[]" placeholder="Price" required></div>`; 
            c.appendChild(d); 
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE, tab='products', products=list(products_col.find({})))
@app.route('/add_product', methods=['POST'])
def add_product():
    try:
        prices = {}
        dur_list = request.form.getlist('duration[]')
        for d, p in zip(dur_list, request.form.getlist('price[]')):
            if d.strip() and p.strip(): prices[d.strip()] = float(p.strip())
        
        img = None
        if 'image_file' in request.files:
            f = request.files['image_file']
            if f.filename: img = os.path.join(UPLOAD_FOLDER, secure_filename(f.filename)); f.save(img)
        
        products_col.insert_one({
            "name": request.form['name'], "pid": request.form['pid'], 
            "description": request.form.get('description'),
            "image": img, "video": request.form.get('video'), "hack": request.form.get('hack'), 
            "is_v1": request.form.get('is_v1')=='true', 
            "is_maintenance": request.form.get('is_maintenance')=='true',
            "redirect_to_wp": request.form.get('redirect_to_wp')=='true',
            "prices": prices
        })
        return render_template_string(HTML_TEMPLATE, tab='products', products=list(products_col.find({})), msg_success="✅ Product Added!")
    except Exception as e: return render_template_string(HTML_TEMPLATE, tab='products', products=list(products_col.find({})), msg_error=f"❌ Error: {str(e)}")

@app.route('/edit_product/<p_id>')
def edit_product(p_id): return render_template_string(HTML_TEMPLATE, tab='edit_product', product=products_col.find_one({"_id": ObjectId(p_id)}))
@app.route('/update_product/<p_id>', methods=['POST'])
def update_product(p_id):
    try:
        prices = {}
        dur_list = request.form.getlist('duration[]')
        for d, p in zip(dur_list, request.form.getlist('price[]')):
            if d.strip() and p.strip(): prices[d.strip()] = float(p.strip())
        
        current_prod = products_col.find_one({"_id": ObjectId(p_id)})
        img = current_prod.get("image") 
        if 'image_file' in request.files:
            f = request.files['image_file']
            if f.filename: img = os.path.join(UPLOAD_FOLDER, secure_filename(f.filename)); f.save(img)
        
        products_col.update_one({"_id": ObjectId(p_id)}, {"$set": {
            "name": request.form['name'], "pid": request.form['pid'], 
            "description": request.form.get('description'),
            "image": img, "video": request.form.get('video'), "hack": request.form.get('hack'), 
            "is_v1": request.form.get('is_v1')=='true', 
            "is_maintenance": request.form.get('is_maintenance')=='true',
            "redirect_to_wp": request.form.get('redirect_to_wp')=='true',
            "prices": prices
        }})
        return render_template_string(HTML_TEMPLATE, tab='products', products=list(products_col.find({})), msg_success="✅ Product Updated!")
    except Exception as e: return render_template_string(HTML_TEMPLATE, tab='products', products=list(products_col.find({})), msg_error=f"❌ Error: {str(e)}")

@app.route('/toggle_maintenance/<p_id>')
def toggle_maintenance(p_id):
    prod = products_col.find_one({"_id": ObjectId(p_id)})
    new_status = not prod.get("is_maintenance", False)
    products_col.update_one({"_id": ObjectId(p_id)}, {"$set": {"is_maintenance": new_status}})
    return redirect(url_for('index'))

@app.route('/delete_product/<p_id>')
def delete_product(p_id):
    products_col.delete_one({"_id": ObjectId(p_id)})
    return redirect(url_for('index'))

@app.route('/users')
def users(): return render_template_string(HTML_TEMPLATE, tab='users', users=list(users_col.find({})))
@app.route('/update_user', methods=['POST'])
def update_user():
    uid = request.form['uid']
    amt = float(request.form['amount']) if request.form['amount'] else 0
    discount = int(request.form['discount']) if request.form['discount'] else 0
    users_col.update_one({"_id": uid}, {"$inc": {"balance": amt}, "$set": {"discount": discount}})
    return redirect(url_for('users'))

@app.route('/orders')
def orders(): return render_template_string(HTML_TEMPLATE, tab='orders', orders=list(orders_col.find({}).sort("_id", -1).limit(100)))
@app.route('/broadcast')
def broadcast(): return render_template_string(HTML_TEMPLATE, tab='broadcast')
@app.route('/send_broadcast', methods=['POST'])
def send_broadcast():
    c = 0
    for u in users_col.find({}):
        try:
            if requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": u["_id"], "text": request.form['message'], "parse_mode": "HTML"}).status_code == 200: c += 1
        except: pass
    return render_template_string(HTML_TEMPLATE, tab='broadcast', msg_success=f"✅ Sent to {c} users!")

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        save_settings({
            "store_name": request.form['store_name'], "support_username": request.form['support_username'], "update_link": request.form['update_link'],
            "maintenance": request.form['maintenance'], "reseller_price": int(request.form.get('reseller_price', 149)), "reseller_discount": int(request.form.get('reseller_discount', 40))
        })
        return render_template_string(HTML_TEMPLATE, tab='settings', settings=get_settings(), msg_success="✅ Settings Saved!")
    return render_template_string(HTML_TEMPLATE, tab='settings', settings=get_settings())

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.infinity_polling(timeout=30, long_polling_timeout=30)
