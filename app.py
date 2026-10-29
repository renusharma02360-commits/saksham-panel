import os
import time
import threading
import requests
import telebot
from functools import wraps
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from famgateway import FamGateway
from flask import Flask, request, render_template_string, redirect, url_for
from pymongo import MongoClient
from bson.objectid import ObjectId

# ================== CONFIG ==================
# 🚨 APNA NAYA TOKEN YAHAN DAALEIN 🚨
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8765613302:AAE2b0qDyR-o0UkzGs5H7fuSSz0yhLiYSBc") 
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")

ADMIN_ID = 7778093775
WEB_URL = "https://saksham-panel-kpsl.onrender.com"

API_KEY = "fam_4c308a3f58df8f752e41770178d877982e4e1a58"
RESELLER_API_URL = "https://bantibhaiya.to/api/reseller_v1.php"
RESELLER_API_KEY = "e5990b638beaa7b2335373200b39c93f"
MASTER_KEY = "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"
SUPPORT_LINK = "https://wa.me/918849507563"
CHANNEL_LINK = "https://t.me/YourChannel"
# ============================================

try:
    client = MongoClient(MONGO_URI)
    db = client.saksham_panel
    users_col = db.users
    products_col = db.products
    categories_col = db.categories
    orders_col = db.orders
    print("✅ Database Connected")
except Exception as e:
    print(f"❌ Database Error: {e}")

bot = telebot.TeleBot(BOT_TOKEN)
try:
    fg = FamGateway(api_key=API_KEY)
    print("✅ Gateway Connected")
except Exception as e:
    print(f"❌ Gateway Error: {e}")

# ---------------- DB HELPERS ----------------
def get_user_info(uid):
    u = users_col.find_one({"_id": str(uid)})
    if not u:
        default_u = {"_id": str(uid), "balance": 0.0, "name": "User", "discount": 0, "joined": time.strftime("%d-%m-%Y")}
        users_col.insert_one(default_u)
        return default_u
    # Agar purane user ka joined N/A hai, toh aaj ki date set kar do
    if "joined" not in u or u["joined"] == "N/A":
        users_col.update_one({"_id": str(uid)}, {"$set": {"joined": time.strftime("%d-%m-%Y")}})
        u["joined"] = time.strftime("%d-%m-%Y")
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

# ================== TELEGRAM BOT ==================
def get_main_menu(uid):
    text = (
        "(●) <b>WELCOME TO SAKSHAM PANEL SHOP\n- PRODUCT STATUS</b> [Shop]\n\n"
        "➡️ Buy Now : All Key Purchase & Instant Delivery ✅\n"
        "➡️ Add Balance : Secure Auto Payment System ✅\n"
        "➡️ My Profile + All History : Check Your All History ✅\n"
        "➡️ Support : Bot Problem Fixed For Support Admin ✅\n\n"
        "⬇️ <b>SELECT AN OPTION FROM THE MENU BELOW 🛒</b>"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("➡️ Shop Now 🛍️", callback_data="bot_shop"))
    kb.add(InlineKeyboardButton("➡️ Add Amount 💸", callback_data="bot_add_bal"), 
           InlineKeyboardButton("➡️ My Profile 👤", callback_data="bot_profile"))
    kb.add(InlineKeyboardButton("➡️ Order History 📄", callback_data="bot_history"), 
           InlineKeyboardButton("➡️ Main Channel ⚡", url=CHANNEL_LINK))
    kb.add(InlineKeyboardButton("➡️ Contact Support 📞", url=SUPPORT_LINK))
    
    if str(uid) == str(ADMIN_ID):
        kb.add(InlineKeyboardButton("⚙️ Admin Panel", web_app=WebAppInfo(url=f"{WEB_URL}/admin")))
        
    return text, kb

@bot.message_handler(commands=["start"])
def start(msg):
    uid = str(msg.from_user.id)
    get_user_info(uid)
    text, kb = get_main_menu(uid)
    bot.send_message(msg.chat.id, text, parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: True)
def bot_callbacks(call):
    uid = str(call.from_user.id)
    bot.answer_callback_query(call.id)
    
    try:
        if call.data == "bot_main":
            text, kb = get_main_menu(uid)
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            
        elif call.data == "bot_shop":
            categories = list(categories_col.find({}))
            if not categories:
                return bot.answer_callback_query(call.id, "❌ No categories added yet.", show_alert=True)
            
            text = "📁 <b>CHOOSE A CATEGORY</b>\n\n🔥 Premium Mods, Panels & Bypasses\n\n👇 <i>Tap a category below:</i>"
            kb = InlineKeyboardMarkup(row_width=1)
            for cat in categories:
                kb.add(InlineKeyboardButton(f"➡️ {cat.get('name').upper()}", callback_data=f"bot_cat|{cat['_id']}"))
            kb.add(InlineKeyboardButton("⬅️ BACK", callback_data="bot_main"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)

        elif call.data.startswith("bot_cat|"):
            cat_id = call.data.split("|")[1]
            cat = categories_col.find_one({"_id": ObjectId(cat_id)})
            
            # STRICT CHECK: Sirf usi category ke products fetch karo
            products = list(products_col.find({"category_id": str(cat_id)}))
            
            if not products:
                # Agar product nahi hai, toh alert dikhao
                return bot.answer_callback_query(call.id, f"❌ Koi product nahi mila {cat.get('name')} mein. (Please Admin panel se product edit karke is category me daalein)", show_alert=True)
            
            text = f"📁 <b>{cat.get('name', 'Category').upper()}</b>\n\n➡️ Choose a product 🕊️❤️"
            kb = InlineKeyboardMarkup(row_width=1)
            for p in products:
                icon = p.get('icon', '🔹')
                kb.add(InlineKeyboardButton(f"{icon} {p.get('name')}", callback_data=f"bot_view|{p['_id']}"))
            kb.add(InlineKeyboardButton("⬅️ BACK", callback_data="bot_shop"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)

        elif call.data.startswith("bot_view|"):
            p_id = call.data.split("|")[1]
            p = products_col.find_one({"_id": ObjectId(p_id)})
            u = get_user_info(uid)
            disc = u.get('discount', 0)
            
            features_text = p.get('features', '').replace('\n', '\n⚡ ') if p.get('features') else ''
            text = f"📁 <b>{p['name']}</b>\n\n⚡ {features_text}\n\n"
            
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📥 Update File", url=p.get('setup_video', '#')), 
                   InlineKeyboardButton("▶️ Video/Feedback", url=p.get('hack_video', '#')))
            
            for d, pr in p.get('prices', {}).items():
                final_pr = float(pr) - (float(pr) * disc / 100) if disc > 0 else float(pr)
                kb.add(InlineKeyboardButton(f"⏱ {d} - ₹{final_pr:.2f}", callback_data=f"bot_buy|{p_id}|{d}"))
                
            kb.add(InlineKeyboardButton("🔙 Back", callback_data=f"bot_cat|{p.get('category_id')}"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)

        elif call.data.startswith("bot_buy|"):
            parts = call.data.split("|")
            p_id, duration = parts[1], parts[2]
            p = products_col.find_one({"_id": ObjectId(p_id)})
            u = get_user_info(uid)
            disc = u.get('discount', 0)
            
            price = float(p['prices'][duration]) - (float(p['prices'][duration]) * disc / 100) if disc > 0 else float(p['prices'][duration])
            
            if get_balance(uid) < price:
                return bot.answer_callback_query(call.id, "❌ Low Balance! Please add funds.", show_alert=True)
                
            if deduct_balance(uid, price):
                bot.edit_message_text("⏳ <i>Processing...</i>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
                try:
                    data = {'api_key': RESELLER_API_KEY, 'action': 'buy', 'product_id': str(p.get("pid", "")).strip(), 'duration': str(duration).strip(), 'quantity': 1}
                    res = requests.post(RESELLER_API_URL, data=data, headers={'x-master-key': MASTER_KEY}, timeout=20)
                    result = res.json()
                except Exception as e: result = {"status": "error"}
                    
                if result.get("status") == "success" or "keys" in result:
                    key = result.get("keys", ["Key not found"])[0]
                    log_order(uid, p['name'], key, price)
                    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back to Menu", callback_data="bot_main"))
                    bot.edit_message_text(f"✅ <b>PURCHASE SUCCESSFUL!</b>\n\n📦 Product: {p['name']}\n⏱ Duration: {duration}\n🔑 Key:\n<code>{key}</code>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
                else:
                    users_col.update_one({"_id": str(uid)}, {"$inc": {"balance": price}})
                    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="bot_shop"))
                    bot.edit_message_text(f"❌ <b>API Error (Out of Stock)</b>\n\n₹{price:.2f} Refunded.", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
                    
        elif call.data == "bot_profile":
            u = get_user_info(uid)
            text = f"👤 <b>YOUR PROFILE</b>\n\n🆔 ID: <code>{uid}</code>\n💰 Balance: ₹{u.get('balance', 0.0):.2f}\n🏷️ Discount: {u.get('discount', 0)}%\n📅 Joined: {u.get('joined', time.strftime('%d-%m-%Y'))}"
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("💸 Add Balance", callback_data="bot_add_bal"), InlineKeyboardButton("🔙 Back", callback_data="bot_main"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            
        elif call.data == "bot_history":
            orders = list(orders_col.find({"uid": uid}).sort("_id", -1))
            if not orders:
                return bot.answer_callback_query(call.id, "No orders found.", show_alert=True)
            
            text = "📜 <b>Your Order History</b>\n\n"
            for o in orders[:5]:
                text += f"📦 {o.get('product')}\n🔑 <code>{o.get('key')}</code>\n📅 {o.get('time')}\n➖➖➖➖➖➖➖➖\n"
            
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="bot_main"))
            bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=kb)
            
        elif call.data == "bot_add_bal":
            web_app = WebAppInfo(url=f"{WEB_URL}/deposit?uid={uid}")
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("💸 Open Calculator", web_app=web_app))
            bot.send_message(call.message.chat.id, "👇 Click below to add balance:", reply_markup=kb)
            
    except Exception as e:
        # ERROR HANDLER: Agar code fat-ta hai, toh admin ko message jayega
        error_msg = f"⚠️ <b>Bot Error Detected!</b>\n\nUser ID: <code>{uid}</code>\nButton: {call.data}\nError: <code>{str(e)}</code>"
        try:
            bot.send_message(ADMIN_ID, error_msg, parse_mode="HTML")
        except:
            pass
        print(f"Callback Error: {e}")

# ================== FLASK WEB APP (Admin & Calculator) ==================
# ... (FlaSK code same rahega jo pichli baar diya tha) ...
# Maine yahan short kar diya hai taaki message lamba na ho. 
# Aap apne pichle code ka Flask waala hissa (BASE_CSS, /admin, /add_product, /deposit wagera) yahan waise hi rakho.
# Bas bot_callbacks waala hissa upar wale se replace kar do.
