import os
import time
import threading
import requests
import telebot
import uuid
from functools import wraps
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from famgateway import FamGateway
from flask import Flask, request, render_template_string, redirect, url_for, session, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId

# ================== CONFIG ==================
BOT_TOKEN = "8765613302:AAE2b0qDyR-o0UkzGs5H7fuSSz0yhLiYSBc" 
API_KEY   = "fam_4c308a3f58df8f752e41770178d877982e4e1a58"
ADMIN_ID  = 7778093775
MONGO_URI = os.environ.get("MONGO_URI") 
UPLOAD_FOLDER = "static/uploads"
WEB_URL = "https://saksham-panel-kpsl.onrender.com" 

ADMIN_WP = "918849507563" 
SUPPORT_LINK = "https://wa.me/918849507563" 
CHANNEL_LINK = "https://t.me/YourChannelLink" # Apna channel link yahan daalein

RESELLER_API_URL = "https://bantibhaiya.to/api/reseller_v1.php"
RESELLER_API_KEY = "e5990b638beaa7b2335373200b39c93f"
MASTER_KEY       = "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"
# ============================================

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

client = MongoClient(MONGO_URI)
db = client.saksham_panel
users_col = db.users
web_users_col = db.web_users 
products_col = db.products
categories_col = db.categories 
orders_col = db.orders

bot = telebot.TeleBot(BOT_TOKEN)
fg  = FamGateway(api_key=API_KEY)

# ---------------- DB HELPERS ----------------
def get_user_info(uid):
    u = users_col.find_one({"_id": str(uid)})
    if not u:
        default_u = {"_id": str(uid), "balance": 0.0, "name": "User", "discount": 0, "verified": False}
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

def log_order(uid, product, key, price):
    orders_col.insert_one({"uid": str(uid), "product": product, "key": key, "price": price, "type": "purchase", "time": time.strftime("%d-%m-%Y %I:%M %p")})

# ================== TELEGRAM BOT ==================
def get_main_menu(uid):
    text = (
        "(●) <b>WELCOME TO SAKSHAM PANEL SHOP - PRODUCT STATUS</b> [Shop]\n\n"
        "➡️ Buy Now : All Key Purchase & Instant Delivery ✅\n"
        "➡️ Check Update : Check Setup And Update Apk ✅\n"
        "➡️ Add Balance : Secure Auto Payment System ✅\n"
        "➡️ My Profile + All History : Check Your All History ✅\n"
        "➡️ How To Use Bot : View Tutorial And Work This Bot ✅\n"
        "➡️ Support : Bot Problem Fixed For Support Admin ✅\n\n"
        "⬇️ <b>SELECT AN OPTION FROM THE MENU BELOW 🛒</b>"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("➡️ Shop Now 🛍️", callback_data="bot_shop"))
    kb.add(InlineKeyboardButton("➡️ Add Amount 💸", callback_data="bot_add_bal"), InlineKeyboardButton("➡️ My Profile 👤", callback_data="bot_profile"))
    kb.add(InlineKeyboardButton("➡️ Order History 📄", callback_data="bot_history"), InlineKeyboardButton("➡️ Main Channel ⚡", url=CHANNEL_LINK))
    kb.add(InlineKeyboardButton("➡️ All Hack Update 📁", url=CHANNEL_LINK), InlineKeyboardButton("➡️ How To Buy Panel 🚀", url=SUPPORT_LINK))
    kb.add(InlineKeyboardButton("➡️ Become A Reseller 🤝", web_app=WebAppInfo(url=f"{WEB_URL}/buy_reseller")))
    kb.add(InlineKeyboardButton("➡️ Contact Support 📞", url=SUPPORT_LINK))
    
    if str(uid) == str(ADMIN_ID):
        kb.add(InlineKeyboardButton("⚙️ Admin Panel", web_app=WebAppInfo(url=f"{WEB_URL}/admin")))
        
    return text, kb

@bot.message_handler(commands=["start"])
def start(msg):
    uid = str(msg.from_user.id)
    user = get_user_info(uid)
    
    if not user.get("verified"):
        markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(KeyboardButton("📱 Share Contact (For Verification)", request_contact=True))
        bot.send_message(msg.chat.id, "🛡️ <b>Verification Required</b>\n\nPlease verify your phone number to continue.", parse_mode="HTML", reply_markup=markup)
        return
        
    text, kb = get_main_menu(uid)
    bot.send_message(msg.chat.id, text, parse_mode="HTML", reply_markup=kb)

@bot.message_handler(content_types=['contact'])
def handle_contact(msg):
    uid = str(msg.from_user.id)
    if msg.contact.user_id == msg.from_user.id:
        users_col.update_one({"_id": uid}, {"$set": {"phone": msg.contact.phone_number, "verified": True}})
        bot.send_message(msg.chat.id, "✅ <b>Verification Successful!</b>", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
        text, kb = get_main_menu(uid)
        bot.send_message(msg.chat.id, text, parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: True)
def bot_callbacks(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    
    if call.data == "bot_main":
        text, kb = get_main_menu(uid)
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
        
    elif call.data == "bot_shop":
        categories = list(categories_col.find({}))
        if not categories:
            return bot.answer_callback_query(call.id, "❌ No categories added yet.", show_alert=True)
        
        text = "📁 <b>CHOOSE A CATEGORY</b>\n\nChoose a product category below:"
        kb = InlineKeyboardMarkup(row_width=1)
        for cat in categories:
            kb.add(InlineKeyboardButton(f"➡️ {cat.get('name').upper()}", callback_data=f"bot_cat|{cat['_id']}"))
        kb.add(InlineKeyboardButton("⬅️ BACK", callback_data="bot_main"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)

    elif call.data.startswith("bot_cat|"):
        cat_id = call.data.split("|")[1]
        cat = categories_col.find_one({"_id": ObjectId(cat_id)})
        
        products = list(products_col.find({"category_id": cat_id, "status": {"$ne": "out_of_stock"}}))
        if not products:
            return bot.answer_callback_query(call.id, "❌ No products in this category right now.", show_alert=True)
        
        text = f"📁 <b>SAKSHAM PANEL SHOP — {cat.get('name', 'Category').upper()}</b>\n\n➡️ Choose a product 🕊️❤️"
        kb = InlineKeyboardMarkup(row_width=1)
        for p in products:
            # Yahan hum product icon (emoji) use kar rahe hain
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
        bot.answer_callback_query(call.id, f"👤 Name: {u.get('name')}\n📱 Phone: {u.get('phone', 'N/A')}\n💰 Balance: ₹{u.get('balance'):.2f}\n🏷️ Discount: {u.get('discount')}%", show_alert=True)
        
    elif call.data == "bot_history":
        orders = list(orders_col.find({"uid": str(uid)}).sort("_id", -1))
        if not orders:
            return bot.answer_callback_query(call.id, "No orders found.", show_alert=True)
        text = "📜 <b>Your Order History</b>\n\n"
        for o in orders[:5]: # Last 5 orders
            text += f"📦 {o.get('product')}\n🔑 <code>{o.get('key')}</code>\n➖➖➖➖➖➖➖➖\n"
        bot.send_message(call.message.chat.id, text, parse_mode="HTML")
        
    elif call.data == "bot_add_bal":
        bot.send_message(call.message.chat.id, "👇 Click here to add balance:", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("💸 Add Balance", web_app=WebAppInfo(url=f"{WEB_URL}/deposit"))))
    else:
        bot.answer_callback_query(call.id, "🚧 This feature is coming soon!", show_alert=True)


# ================== FLASK WEB APP (ADMIN PANEL) ==================
app = Flask(__name__)
app.secret_key = "sk_panel_secret"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

BASE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800;900&display=swap');
    * { box-sizing: border-box; font-family: 'Poppins', sans-serif; margin: 0; padding: 0; }
    body { background-color: #050810; color: #fff; padding-bottom: 100px; }
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
</style>
"""

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
            <a href="/admin_categories" class="store-btn" style="background:#10b981;">📁 Categories</a>
            <a href="/" class="store-btn" style="background:#ef4444;">Exit</a>
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
                <div class="input-group"><label>Product Icon (Emoji) - e.g. 💀 or ⚡</label><input type="text" name="icon" placeholder="🔹" required></div>
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
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1; padding:15px; border-radius:15px; background:#0f172a; color:#fff; border:2px solid #334155;"><input type="number" name="price[]" placeholder="Sell (₹)" style="flex:1; padding:15px; border-radius:15px; background:#0f172a; color:#fff; border:2px solid #334155;">`;
            c.appendChild(d);
        }}
    </script>
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
    <div class="top-nav">
        <div style="font-weight:900; font-size:24px; color:#10b981;">📁 Categories</div>
        <a href="/admin" class="store-btn">🔙 Back</a>
    </div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card" style="border-color:#10b981;">
            <h3 style="margin-bottom:20px; color:#10b981;">➕ Add New Category</h3>
            <form method="POST">
                <div class="input-group">
                    <input type="text" name="cat_name" placeholder="e.g. Android Root" required>
                </div>
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
        cat_id = request.form.get('category_id')
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
            cat_id = request.form.get('category_id')
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

# User Web routes (Deposit/Login) required for FamGateway to work
@app.route('/deposit', methods=['GET', 'POST'])
def web_deposit():
    # (Aapka purana deposit code yahan aayega, maine short rakha hai)
    return "<h2 style='color:white;text-align:center;'>Deposit Page Working (Implement your FamGateway here)</h2>"

@app.route('/buy_reseller', methods=['GET', 'POST'])
def buy_reseller():
    return "<h2 style='color:white;text-align:center;'>Reseller Page Working</h2>"

@app.route('/')
def home():
    return redirect(url_for('admin_panel'))

# ================== RUNNING ==================
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def run_bot():
    try: 
        bot.delete_webhook(drop_pending_updates=True) 
    except Exception as e: 
        print(f"Webhook error: {e}")
    bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_flask()
