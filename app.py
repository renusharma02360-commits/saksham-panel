import os
import time
import threading
import requests
import telebot
import uuid
from functools import wraps
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from famgateway import FamGateway
from flask import Flask, request, render_template_string, redirect, url_for, session, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId

# ================== CONFIG ==================
# 🚨 APNA NAYA TOKEN YAHAN DAALEIN 🚨
BOT_TOKEN = "8765613302:AAE2b0qDyR-o0UkzGs5H7fuSSz0yhLiYSBc" 

API_KEY   = "fam_4c308a3f58df8f752e41770178d877982e4e1a58"
ADMIN_ID  = 7778093775
MONGO_URI = os.environ.get("MONGO_URI") 
UPLOAD_FOLDER = "static/uploads"
WEB_URL = "https://saksham-panel-kpsl.onrender.com" 

# Agar MongoDB URI nahi hai toh default (Render pe env variable set karein)
if not MONGO_URI:
    MONGO_URI = "mongodb://localhost:27017/"

RESELLER_API_URL = "https://bantibhaiya.to/api/reseller_v1.php"
RESELLER_API_KEY = "e5990b638beaa7b2335373200b39c93f"
MASTER_KEY       = "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"
# ============================================

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

client = MongoClient(MONGO_URI)
db = client.saksham_panel
users_col = db.users
products_col = db.products
categories_col = db.categories 
orders_col = db.orders
settings_col = db.settings

bot = telebot.TeleBot(BOT_TOKEN)
fg  = FamGateway(api_key=API_KEY)

# ---------------- DB & SETTINGS HELPERS ----------------
def get_setting(key, default):
    s = settings_col.find_one({"_id": key})
    if not s:
        settings_col.insert_one({"_id": key, "value": default})
        return default
    return s['value']

def get_user_info(uid):
    u = users_col.find_one({"_id": str(uid)})
    if not u:
        default_u = {"_id": str(uid), "balance": 0.0, "name": "User", "discount": 0, "joined": time.strftime("%d-%m-%Y")}
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

def credit_balance(uid, amount):
    users_col.update_one({"_id": str(uid)}, {"$inc": {"balance": amount}}, upsert=True)
    return get_balance(uid)

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
    text = get_setting("welcome_text", 
        "(●) <b>WELCOME TO SAKSHAM PANEL SHOP - PRODUCT STATUS</b> [Shop]\n\n"
        "➡️ Buy Now : All Key Purchase & Instant Delivery ✅\n"
        "➡️ Add Balance : Secure Auto Payment System ✅\n"
        "➡️ My Profile + All History : Check Your All History ✅\n"
        "➡️ Support : Bot Problem Fixed For Support Admin ✅\n\n"
        "⬇️ <b>SELECT AN OPTION FROM THE MENU BELOW 🛒</b>"
    )
    channel_link = get_setting("channel_link", "https://t.me/YourChannel")
    support_link = get_setting("support_link", "https://wa.me/918849507563")

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("➡️ Shop Now 🛍️", callback_data="bot_shop"))
    kb.add(InlineKeyboardButton("➡️ Add Amount 💸", callback_data="bot_add_bal"), 
           InlineKeyboardButton("➡️ My Profile 👤", callback_data="bot_profile"))
    kb.add(InlineKeyboardButton("➡️ Order History 📄", callback_data="bot_history"), 
           InlineKeyboardButton("➡️ Main Channel ⚡", url=channel_link))
    kb.add(InlineKeyboardButton("➡️ Contact Support 📞", url=support_link))
    
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
            
            text = "📁 <b>CHOOSE A CATEGORY</b>\n\n🔥 Premium Mods, Panels & Bypasses — all in one place!\n⚡ Instant delivery • 🔒 Verified sellers\n\n👇 <i>Tap a category below to get started:</i>"
            kb = InlineKeyboardMarkup(row_width=1)
            for cat in categories:
                kb.add(InlineKeyboardButton(f"➡️ {cat.get('name').upper()}", callback_data=f"bot_cat|{cat['_id']}"))
            kb.add(InlineKeyboardButton("⬅️ BACK", callback_data="bot_main"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)

        elif call.data.startswith("bot_cat|"):
            cat_id = call.data.split("|")[1]
            cat = categories_col.find_one({"_id": ObjectId(cat_id)})
            
            # Sirf usi category ke products fetch honge
            products = list(products_col.find({"category_id": str(cat_id), "status": {"$ne": "out_of_stock"}}))
            
            if not products:
                return bot.answer_callback_query(call.id, "❌ No products in this category right now.", show_alert=True)
            
            text = f"📁 <b>SAKSHAM PANEL SHOP — {cat.get('name', 'Category').upper()}</b>\n\n➡️ Choose a product 🕊️❤️"
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
                bot.edit_message_text("⏳ <i>Processing your order...</i>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
                try:
                    data = {'api_key': RESELLER_API_KEY, 'action': 'buy', 'product_id': str(p.get("pid", "")).strip(), 'duration': str(duration).strip(), 'quantity': 1}
                    res = requests.post(RESELLER_API_URL, data=data, headers={'x-master-key': MASTER_KEY}, timeout=20)
                    result = res.json()
                except Exception as e: result = {"status": "error", "message": str(e)}
                    
                if result.get("status") == "success" or "keys" in result:
                    key = result.get("keys", ["Key not found"])[0]
                    log_order(uid, p['name'], key, price)
                    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back to Menu", callback_data="bot_main"))
                    bot.edit_message_text(f"✅ <b>PURCHASE SUCCESSFUL!</b>\n\n📦 Product: {p['name']}\n⏱ Duration: {duration}\n🔑 Key:\n<code>{key}</code>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
                else:
                    credit_balance(uid, price)
                    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="bot_shop"))
                    bot.edit_message_text(f"❌ <b>API Error (Out of Stock)</b>\n\n₹{price:.2f} has been refunded to your wallet.", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
                    
        elif call.data == "bot_profile":
            u = get_user_info(uid)
            text = (
                f"👤 <b>YOUR PROFILE</b>\n\n"
                f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
                f"💰 <b>Balance:</b> ₹{u.get('balance', 0.0):.2f}\n"
                f"🏷️ <b>Discount:</b> {u.get('discount', 0)}%\n"
                f"📅 <b>Joined:</b> {u.get('joined', 'N/A')}\n"
            )
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("💸 Add Balance", callback_data="bot_add_bal"), InlineKeyboardButton("🔙 Back", callback_data="bot_main"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            
        elif call.data == "bot_history":
            orders = list(orders_col.find({"uid": uid}).sort("_id", -1))
            if not orders:
                return bot.answer_callback_query(call.id, "No orders found.", show_alert=True)
            
            text = "📜 <b>Your Order History</b>\n\n"
            for o in orders[:5]: # Show last 5 orders
                text += f"📦 {o.get('product')}\n🔑 <code>{o.get('key')}</code>\n📅 {o.get('time')}\n➖➖➖➖➖➖➖➖\n"
            
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="bot_main"))
            bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=kb)
            
        elif call.data == "bot_add_bal":
            # WebApp open hoga yahan
            web_app = WebAppInfo(url=f"{WEB_URL}/deposit?uid={uid}")
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("💸 Add Balance", web_app=web_app))
            bot.send_message(call.message.chat.id, "👇 Click the button below to open the secure payment calculator:", reply_markup=kb)
            
    except Exception as e:
        print(f"Callback Error: {e}")
        bot.send_message(call.message.chat.id, "⚠️ An error occurred. Please try again later.")

# ================== FLASK WEB APP ==================
app = Flask(__name__)
app.secret_key = "sk_panel_secret"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

BASE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800;900&display=swap');
    * { box-sizing: border-box; font-family: 'Poppins', sans-serif; margin: 0; padding: 0; }
    body { background-color: #050810; color: #fff; padding-bottom: 50px; }
    .container { padding: 20px; max-width: 1000px; margin: 0 auto; }
    .top-nav { display: flex; justify-content: space-between; align-items: center; padding: 20px 25px; background: rgba(15, 23, 42, 0.85); position: sticky; top: 0; z-index: 100; border-bottom: 1px solid rgba(255,255,255,0.1); }
    .store-btn { background: linear-gradient(135deg, #0ea5e9, #2563eb); padding: 15px 25px; border-radius: 25px; font-weight: 800; color: white; text-decoration: none; }
    .product-card { background: linear-gradient(145deg, #0f172a, #050810); border-radius: 25px; padding: 30px; border: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; }
    .input-group { margin-bottom: 20px; }
    .input-group label { display: block; font-size: 16px; color: #cbd5e1; margin-bottom: 10px; font-weight: 700; }
    .input-group input, .input-group textarea, select { width: 100%; padding: 20px; border-radius: 15px; border: 2px solid #334155; background: #0f172a; color: #fff; font-size: 18px; outline: none; }
    .action-btn { display: block; width: 100%; padding: 20px; border-radius: 15px; text-align: center; font-weight: 900; font-size: 18px; text-decoration: none; border: none; cursor: pointer; text-transform: uppercase; }
    .btn-primary { background: linear-gradient(135deg, #0ea5e9, #3b82f6); color: white; }
    .btn-success { background: linear-gradient(135deg, #10b981, #059669); color: white; }
    .btn-danger { background: linear-gradient(135deg, #ef4444, #b91c1c); color: white; }
    .btn-warning { background: linear-gradient(135deg, #f59e0b, #d97706); color: black; }
    .stats-grid { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 20px; margin-bottom: 30px; }
    .stat-card { background: linear-gradient(145deg, #0f172a, #1e293b); border-radius: 20px; padding: 25px; border: 1px solid rgba(255,255,255,0.08); }
    .stat-title { font-size: 15px; color: #94a3b8; font-weight: 700; }
    .stat-value { font-size: 32px; font-weight: 900; }

    /* Calculator CSS */
    .calc-display { background: #000; padding: 20px; border-radius: 15px; font-size: 40px; font-weight: 900; color: #00f0ff; text-align: right; margin-bottom: 20px; border: 2px solid #00f0ff; box-shadow: 0 0 20px rgba(0,240,255,0.2); letter-spacing: 2px; }
    .calc-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
    .calc-btn { background: #1e293b; color: white; border: none; padding: 20px; font-size: 24px; font-weight: 700; border-radius: 15px; cursor: pointer; transition: 0.2s; }
    .calc-btn:active { transform: scale(0.95); background: #334155; }
    .calc-btn.clear { background: #ef4444; color: white; }
    .calc-btn.back { background: #f59e0b; color: black; }
    .calc-btn.proceed { background: #10b981; color: white; grid-column: span 3; font-size: 20px; margin-top: 10px; text-transform: uppercase; }
</style>
"""

# ================== ADMIN PANEL ==================
@app.route('/admin', methods=['GET'])
def admin_panel():
    total_users = users_col.count_documents({})
    total_sales = orders_col.count_documents({"type": "purchase"})
    total_revenue = sum([o.get('price', 0) for o in orders_col.find({"type": "purchase"})])
    total_products = products_col.count_documents({})
    
    products = list(products_col.find({}))

    prod_html = ""
    for p in products:
        cat = categories_col.find_one({"_id": ObjectId(p.get('category_id'))}) if p.get('category_id') else None
        cat_name = cat.get('name') if cat else "No Category"
        icon = p.get('icon', '🔹')
        
        prod_html += f"""
        <div class="product-card" style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <div style="font-size:22px; font-weight:900; color:#38bdf8;">{icon} {p.get('name', '')}</div>
                <div style="font-size:14px; color:#f59e0b;">Category: {cat_name}</div>
            </div>
            <div style="display:flex; gap:10px;">
                <a href="/edit_product/{p['_id']}" class="action-btn btn-warning" style="padding:10px; font-size:14px; width:auto;">Edit</a>
                <form action="/delete_product/{p['_id']}" method="POST">
                    <button type="submit" class="action-btn btn-danger" style="padding:10px; font-size:14px; width:auto;">Del</button>
                </form>
            </div>
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:24px; color:#38bdf8;">⚙️ Admin Panel</div>
        <div style="display:flex; gap:10px;">
            <a href="/admin_users" class="store-btn" style="background:#f59e0b;">👥 Users</a>
            <a href="/admin_settings" class="store-btn" style="background:#8b5cf6;">⚙️ Settings</a>
            <a href="/admin_categories" class="store-btn" style="background:#10b981;">📁 Categories</a>
        </div>
    </div>
    <div class="container" style="margin-top:20px;">
        <div class="stats-grid">
            <div class="stat-card"><div class="stat-title">Users</div><div class="stat-value text-blue">{total_users}</div></div>
            <div class="stat-card"><div class="stat-title">Sales</div><div class="stat-value text-yellow">{total_sales}</div></div>
            <div class="stat-card"><div class="stat-title">Revenue</div><div class="stat-value text-green">₹{total_revenue}</div></div>
            <div class="stat-card"><div class="stat-title">Products</div><div class="stat-value">{total_products}</div></div>
        </div>

        <div class="product-card" style="border-color:#0ea5e9;">
            <h3 style="margin-bottom:25px; color:#38bdf8; font-size:26px;">➕ Add New Product</h3>
            <form method="POST" action="/add_product">
                <div class="input-group"><label>Product Name</label><input type="text" name="name" required></div>
                <div class="input-group"><label>Product Icon (Emoji)</label><input type="text" name="icon" placeholder="🔹" required></div>
                <div class="input-group"><label>PID (API Product ID)</label><input type="text" name="pid" required></div>
                
                <div class="input-group">
                    <label>Select Category</label>
                    <select name="category_id" required>
                        <option value="">-- Select Category --</option>
                        {''.join([f'<option value="{c["_id"]}">{c["name"]}</option>' for c in categories_col.find({})])}
                    </select>
                </div>
                
                <div class="input-group"><label>Features (One per line)</label><textarea name="features" rows="4"></textarea></div>
                <div class="input-group"><label>Update File Link</label><input type="url" name="setup_video" placeholder="https://..."></div>
                <div class="input-group"><label>Video / Feedback Link</label><input type="url" name="hack_video" placeholder="https://..."></div>

                <label style="font-weight:900; color:#38bdf8; margin:20px 0 10px 0; display:block; font-size:20px;">Durations & Selling Price (₹)</label>
                <div id="price-container">
                    <div style="display:flex; gap:10px; margin-bottom:10px;">
                        <input type="text" name="duration[]" placeholder="e.g. 1 Day" style="flex:1; padding:15px;">
                        <input type="number" name="price[]" placeholder="Sell (₹)" style="flex:1; padding:15px;">
                    </div>
                </div>
                <button type="button" onclick="addPrice()" class="action-btn btn-success" style="margin-bottom:25px; background:#f59e0b; color:#000;">+ Add More</button>
                <button type="submit" class="action-btn btn-primary">Save Product</button>
            </form>
        </div>

        <h3 style="margin-bottom:20px; color:#38bdf8; font-size:24px;">📦 All Products</h3>
        {prod_html}
    </div>
    <script>
        function addPrice() {{
            const c = document.getElementById('price-container');
            const d = document.createElement('div');
            d.style.display = 'flex'; d.style.gap = '10px'; d.style.marginBottom = '10px';
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1; padding:15px;"><input type="number" name="price[]" placeholder="Sell (₹)" style="flex:1; padding:15px;">`;
            c.appendChild(d);
        }}
    </script>
    """)

@app.route('/admin_settings', methods=['GET', 'POST'])
def admin_settings():
    if request.method == 'POST':
        settings_col.update_one({"_id": "welcome_text"}, {"$set": {"value": request.form['welcome_text']}}, upsert=True)
        settings_col.update_one({"_id": "channel_link"}, {"$set": {"value": request.form['channel_link']}}, upsert=True)
        settings_col.update_one({"_id": "support_link"}, {"$set": {"value": request.form['support_link']}}, upsert=True)
        return redirect(url_for('admin_settings'))

    welcome = get_setting("welcome_text", "(●) <b>WELCOME...</b>")
    channel = get_setting("channel_link", "https://t.me/YourChannel")
    support = get_setting("support_link", "https://wa.me/918849507563")

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:24px; color:#8b5cf6;">⚙️ Bot Settings</div>
        <a href="/admin" class="store-btn">🔙 Back</a>
    </div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card" style="border-color:#8b5cf6;">
            <h3 style="margin-bottom:20px; color:#8b5cf6;">Edit Bot Messages & Links</h3>
            <form method="POST">
                <div class="input-group">
                    <label>Welcome Message (Main Menu Text)</label>
                    <textarea name="welcome_text" rows="8" required>{welcome}</textarea>
                </div>
                <div class="input-group">
                    <label>Main Channel Link</label>
                    <input type="url" name="channel_link" value="{channel}" required>
                </div>
                <div class="input-group">
                    <label>Support Link (WhatsApp/Telegram)</label>
                    <input type="url" name="support_link" value="{support}" required>
                </div>
                <button type="submit" class="action-btn btn-primary">Save Settings</button>
            </form>
        </div>
    </div>
    """)

@app.route('/admin_users')
def admin_users():
    users = list(users_col.find({}))
    user_html = ""
    for u in users:
        reseller = "Yes" if u.get('discount', 0) > 0 else "No"
        user_html += f"""
        <div class="product-card" style="display:flex; justify-content:space-between; align-items:center; padding:15px;">
            <div>
                <div style="font-size:18px; font-weight:900; color:#38bdf8;">{u.get('name', 'User')}</div>
                <div style="font-size:14px; color:#94a3b8;">ID: <code>{u['_id']}</code></div>
                <div style="font-size:12px; color:#f59e0b;">Reseller: {reseller}</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:20px; font-weight:900; color:#10b981;">₹{u.get('balance', 0):.2f}</div>
                <a href="/admin_edit_user/{u['_id']}" class="action-btn btn-warning" style="padding:8px 15px; font-size:12px; width:auto; margin-top:5px;">Edit User</a>
            </div>
        </div>
        """
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><div style="font-weight:900; font-size:24px; color:#f59e0b;">👥 Users ({len(users)})</div><a href="/admin" class="store-btn">🔙 Back</a></div>
    <div class="container" style="margin-top:20px;">{user_html}</div>
    """)

@app.route('/admin_edit_user/<uid>', methods=['GET', 'POST'])
def admin_edit_user(uid):
    u = get_user_info(uid)
    if request.method == 'POST':
        bal = float(request.form['balance'])
        disc = int(request.form['discount'])
        users_col.update_one({"_id": str(uid)}, {"$set": {"balance": bal, "discount": disc}})
        return redirect(url_for('admin_users'))
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><div style="font-weight:900; font-size:24px; color:#f59e0b;">✏️ Edit User: {u.get('name')}</div><a href="/admin_users" class="store-btn">🔙 Back</a></div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card" style="border-color:#f59e0b;">
            <form method="POST">
                <div class="input-group"><label>Balance (₹)</label><input type="number" step="0.01" name="balance" value="{u.get('balance', 0)}" required></div>
                <div class="input-group"><label>Discount (%) - (0 for none, 56 for reseller)</label><input type="number" name="discount" value="{u.get('discount', 0)}" required></div>
                <button type="submit" class="action-btn btn-warning">Update User</button>
            </form>
        </div>
    </div>
    """)

@app.route('/admin_categories', methods=['GET', 'POST'])
def admin_categories():
    if request.method == 'POST':
        cat_name = request.form.get('cat_name')
        if cat_name:
            categories_col.insert_one({"name": cat_name})
            return redirect(url_for('admin_categories'))
            
    categories = list(categories_col.find({}))
    cat_html = ""
    for c in categories:
        cat_html += f"""
        <div class="product-card" style="display:flex; justify-content:space-between; align-items:center;">
            <div style="font-size:20px; font-weight:900; color:#10b981;">📁 {c['name']}</div>
            <form action="/delete_category/{c['_id']}" method="POST">
                <button type="submit" class="action-btn btn-danger" style="padding:10px; font-size:14px; width:auto;">Del</button>
            </form>
        </div>
        """
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><div style="font-weight:900; font-size:24px; color:#10b981;">📁 Categories</div><a href="/admin" class="store-btn">🔙 Back</a></div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card" style="border-color:#10b981;">
            <h3 style="margin-bottom:20px; color:#10b981;">➕ Add New Category</h3>
            <form method="POST">
                <div class="input-group"><input type="text" name="cat_name" placeholder="e.g. Android Root" required></div>
                <button type="submit" class="action-btn btn-success">Save</button>
            </form>
        </div>
        {cat_html}
    </div>
    """)

@app.route('/delete_category/<c_id>', methods=['POST'])
def delete_category(c_id):
    categories_col.delete_one({"_id": ObjectId(c_id)})
    return redirect(url_for('admin_categories'))

@app.route('/add_product', methods=['POST'])
def add_product():
    try:
        cat_id = str(request.form.get('category_id')) # String mein convert karna zaroori hai
        durs = request.form.getlist('duration[]')
        prices = request.form.getlist('price[]')
        price_dict = {d.strip(): float(p.strip()) for d, p in zip(durs, prices) if d.strip() and p.strip()}
        
        products_col.insert_one({
            "name": request.form['name'], 
            "icon": request.form.get('icon', '🔹'),
            "pid": request.form['pid'], 
            "category_id": cat_id,
            "features": request.form.get('features', ''), 
            "setup_video": request.form.get('setup_video', '#'), 
            "hack_video": request.form.get('hack_video', '#'), 
            "prices": price_dict, 
            "status": "active"
        })
        return redirect(url_for('admin_panel'))
    except Exception as e: 
        return f"Error: {e}"

@app.route('/edit_product/<p_id>', methods=['GET', 'POST'])
def edit_product(p_id):
    p = products_col.find_one({"_id": ObjectId(p_id)})
    if not p: return "Not found"

    if request.method == 'POST':
        try:
            cat_id = str(request.form.get('category_id'))
            durs = request.form.getlist('duration[]')
            prices = request.form.getlist('price[]')
            price_dict = {d.strip(): float(p.strip()) for d, p in zip(durs, prices) if d.strip() and p.strip()}
            
            products_col.update_one({"_id": ObjectId(p_id)}, {"$set": {
                "name": request.form['name'], 
                "icon": request.form.get('icon', '🔹'),
                "pid": request.form['pid'], 
                "category_id": cat_id,
                "features": request.form.get('features', ''), 
                "setup_video": request.form.get('setup_video', '#'), 
                "hack_video": request.form.get('hack_video', '#'), 
                "prices": price_dict
            }})
            return redirect(url_for('admin_panel'))
        except Exception as e: 
            return f"Error: {e}"

    price_fields = ""
    for d, pr in p.get('prices', {}).items():
        price_fields += f"""
        <div style="display:flex; gap:10px; margin-bottom:10px;">
            <input type="text" name="duration[]" value="{d}" style="flex:1; padding:15px;">
            <input type="number" name="price[]" value="{pr}" style="flex:1; padding:15px;">
        </div>
        """
        
    categories = list(categories_col.find({}))
    cat_options = "".join([f'<option value="{c["_id"]}" {"selected" if str(c["_id"]) == p.get("category_id") else ""}>{c["name"]}</option>' for c in categories])

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/admin" class="store-btn">🔙 Back</a></div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card">
            <h3 style="margin-bottom:20px; color:#f59e0b;">✏️ Edit Product</h3>
            <form method="POST">
                <div class="input-group"><label>Product Name</label><input type="text" name="name" value="{p.get('name', '')}" required></div>
                <div class="input-group"><label>Product Icon (Emoji)</label><input type="text" name="icon" value="{p.get('icon', '🔹')}" required></div>
                <div class="input-group"><label>PID</label><input type="text" name="pid" value="{p.get('pid', '')}" required></div>
                <div class="input-group">
                    <label>Category</label>
                    <select name="category_id">{cat_options}</select>
                </div>
                <div class="input-group"><label>Features</label><textarea name="features" rows="4">{p.get('features', '')}</textarea></div>
                <div class="input-group"><label>Update Link</label><input type="url" name="setup_video" value="{p.get('setup_video', '#')}"></div>
                <div class="input-group"><label>Video Link</label><input type="url" name="hack_video" value="{p.get('hack_video', '#')}"></div>
                <label style="font-weight:900; color:#38bdf8; margin:15px 0 10px 0; display:block;">Durations & Price</label>
                <div id="price-container">{price_fields}</div>
                <button type="button" onclick="addPrice()" class="action-btn btn-success" style="margin-bottom:20px; background:#f59e0b; color:#000;">+ Add More</button>
                <button type="submit" class="action-btn btn-warning">Update</button>
            </form>
        </div>
    </div>
    <script>
        function addPrice() {{
            const c = document.getElementById('price-container');
            const d = document.createElement('div');
            d.style.display = 'flex'; d.style.gap = '10px'; d.style.marginBottom = '10px';
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1; padding:15px;"><input type="number" name="price[]" placeholder="Sell (₹)" style="flex:1; padding:15px;">`;
            c.appendChild(d);
        }}
    </script>
    """)

@app.route('/delete_product/<p_id>', methods=['POST'])
def delete_product(p_id):
    products_col.delete_one({"_id": ObjectId(p_id)})
    return redirect(url_for('admin_panel'))

# ================== USER WEB APP (DEPOSIT) ==================
@app.route('/deposit', methods=['GET', 'POST'])
def web_deposit():
    uid = request.args.get('uid')
    if not uid:
        return "User ID not found. Please try again from bot."

    if request.method == 'POST':
        amount = float(request.form['amount'])
        
        if amount < 10:
            return "<h3 style='color:red; text-align:center;'>Minimum amount is ₹10</h3>"

        try:
            order = fg.create_order(amount=amount, customer_name=f"User_{uid}")
            
            QR_HTML = BASE_CSS + f"""
            <div class="container fade-in" style="margin-top:30px; text-align:center;">
                <div class="product-card" style="padding: 40px 20px;">
                    <h2 style="color:#10b981; font-size:36px; font-weight:900; margin-bottom:10px;">Pay ₹{amount}</h2>
                    <p style="color:#94a3b8; font-size:16px; margin-bottom:25px;">Scan the QR Code below to pay</p>
                    
                    <div id="qr-section">
                        <div style="background:#fff; padding:15px; border-radius:20px; display:inline-block; box-shadow: 0 0 30px rgba(56, 189, 248, 0.6);">
                            <img src="{order.qr_url}" style="width:100%; max-width:250px; display:block; border-radius:10px;">
                        </div>
                        
                        <div id="loading-section" style="margin-top:30px;">
                            <div style="display:inline-block; width:45px; height:45px; border:4px solid rgba(255,255,255,0.1); border-top:4px solid #38bdf8; border-radius:50%; animation: spin 1s linear infinite;"></div>
                            <h3 style="color:#38bdf8; margin-top:15px; font-weight:800; font-size:20px;">Waiting for Payment...</h3>
                            <button onclick="checkPaymentStatus()" class="action-btn btn-warning" style="margin-top:20px; padding:15px; font-size:16px; border-radius:10px;">🔄 Check Status Manually</button>
                        </div>
                    </div>

                    <div id="success-section" style="display:none; margin-top:30px;">
                        <div style="font-size:70px; margin-bottom:20px;">✅</div>
                        <h2 style="color:#10b981; font-size:32px; font-weight:900;">Payment Successful!</h2>
                        <p style="color:#cbd5e1; font-size:20px; margin-top:15px;">New Balance: <b id="new-balance" style="color:#38bdf8;">₹0.00</b></p>
                    </div>
                </div>
            </div>
            <script>
                let checkCount = 0;
                const maxChecks = 40; 
                
                function checkPaymentStatus() {{
                    fetch('/check_payment/{order.order_id}/{amount}?uid={uid}')
                    .then(response => response.json())
                    .then(data => {{
                        if (data.status === 'success') {{
                            document.getElementById('qr-section').style.display = 'none';
                            document.getElementById('success-section').style.display = 'block';
                            document.getElementById('new-balance').innerText = '₹' + data.new_balance.toFixed(2);
                        }} else if (data.status === 'expired') {{
                            document.getElementById('loading-section').innerHTML = '<h3 style="color:#ef4444;">QR Expired! Please try again.</h3>';
                            clearInterval(pollInterval);
                        }}
                    }});
                    checkCount++;
                    if(checkCount >= maxChecks) {{ clearInterval(pollInterval); }}
                }}
                const pollInterval = setInterval(checkPaymentStatus, 3000);
            </script>
            """
            return render_template_string(QR_HTML)
        except Exception as e: 
            return f"<h2 style='color:red; text-align:center; margin-top:50px;'>API Error: {e}</h2>"

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:20px; color:#38bdf8;">💸 Add Balance</div>
    </div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card" style="border-color:#0ea5e9;">
            <form method="POST" id="depositForm">
                <div class="input-group">
                    <label style="text-align:center; font-size:18px; color:#94a3b8;">Enter Amount (₹)</label>
                    <input type="number" id="amountInput" name="amount" required readonly style="font-size:32px; text-align:right; background:#000; color:#00f0ff; border:2px solid #00f0ff; border-radius:15px; padding:20px; font-weight:900;">
                </div>

                <div class="calc-grid">
                    <button type="button" class="calc-btn" onclick="addDigit('1')">1</button>
                    <button type="button" class="calc-btn" onclick="addDigit('2')">2</button>
                    <button type="button" class="calc-btn" onclick="addDigit('3')">3</button>
                    <button type="button" class="calc-btn" onclick="addDigit('4')">4</button>
                    <button type="button" class="calc-btn" onclick="addDigit('5')">5</button>
                    <button type="button" class="calc-btn" onclick="addDigit('6')">6</button>
                    <button type="button" class="calc-btn" onclick="addDigit('7')">7</button>
                    <button type="button" class="calc-btn" onclick="addDigit('8')">8</button>
                    <button type="button" class="calc-btn" onclick="addDigit('9')">9</button>
                    <button type="button" class="calc-btn clear" onclick="clearDisplay()">C</button>
                    <button type="button" class="calc-btn" onclick="addDigit('0')">0</button>
                    <button type="button" class="calc-btn back" onclick="backspace()">⌫</button>
                    <button type="submit" class="calc-btn proceed">Proceed to Pay</button>
                </div>
            </form>
        </div>
    </div>
    <script>
        const input = document.getElementById('amountInput');
        
        function addDigit(digit) {{
            if (input.value === '0') input.value = digit;
            else input.value += digit;
        }}
        
        function clearDisplay() {{
            input.value = '';
        }}
        
        function backspace() {{
            input.value = input.value.slice(0, -1);
        }}
    </script>
    """)

@app.route('/check_payment/<order_id>/<float:amount>')
def check_payment(order_id, amount):
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"status": "error", "message": "UID missing"})
        
    try:
        status = fg.get_status(order_id)
        if status.is_paid:
            ok, new_bal = credit_atomic(uid, amount, status.utr)
            return jsonify({"status": "success", "new_balance": new_bal})
        elif status.is_expired:
            return jsonify({"status": "expired"})
        else:
            return jsonify({"status": "pending"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/')
def home():
    return redirect(url_for('admin_panel'))

# ================== RUNNING ==================
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def run_bot():
    print("Starting Bot...")
    try: 
        bot.delete_webhook(drop_pending_updates=True) 
    except Exception as e: 
        print(f"Webhook error: {e}")
    print("Bot Polling Started!")
    bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_flask()
