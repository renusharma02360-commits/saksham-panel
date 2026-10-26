import os
import time
import threading
import requests
import urllib.parse
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from famgateway import FamGateway
from flask import Flask, request, render_template_string, redirect, url_for, session
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson.objectid import ObjectId

# ================== CONFIG ==================
BOT_TOKEN = "8764644526:AAET1x8jqFsp4d-XvdiZbVx-aO2cyKY3ISc"
API_KEY   = "fam_4c308a3f58df8f752e41770178d877982e4e1a58"
ADMIN_ID  = 7778093775
MONGO_URI = os.environ.get("MONGO_URI") 
UPLOAD_FOLDER = "static/uploads"
WEB_URL = "https://saksham-panel-kpsl.onrender.com" 

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

# ---------------- DB HELPERS ----------------
def get_settings():
    s = settings_col.find_one({"_id": "global"})
    if not s:
        default_s = {"_id": "global", "store_name": "TM PANEL SHOP", "support_username": "YourSupport"}
        settings_col.insert_one(default_s)
        return default_s
    return s

def get_user_info(uid):
    u = users_col.find_one({"_id": str(uid)})
    if not u:
        default_u = {"_id": str(uid), "balance": 0.0, "name": "User", "discount": 0}
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
    orders_col.insert_one({"uid": str(uid), "product": product, "key": key, "price": price, "time": time.strftime("%d-%m-%Y %I:%M %p")})

# ================== TELEGRAM BOT LOGIC ==================
def get_main_menu(uid, name):
    bal = get_balance(uid)
    text = f"✨ <b>WELCOME, {name}</b>\n💳 <b>Wallet:</b> ₹{bal:.2f}\n\n👇 <i>Choose an option:</i>"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🛒 Shop", callback_data="menu_shop"), InlineKeyboardButton("💸 Add Balance", callback_data="menu_addfund"))
    kb.add(InlineKeyboardButton("👤 My Profile", callback_data="menu_balance"))
    if str(uid) == str(ADMIN_ID):
        kb.add(InlineKeyboardButton("💻 Admin Web Panel", web_app=WebAppInfo(url=f"{WEB_URL}/admin")))
    return text, kb

@bot.message_handler(commands=["start"])
def start(msg):
    get_user_info(msg.from_user.id)
    text, kb = get_main_menu(msg.from_user.id, msg.from_user.first_name)
    bot.send_message(msg.chat.id, text, parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    uid, data, name = call.from_user.id, call.data, call.from_user.first_name
    msg_id, chat_id = call.message.message_id, call.message.chat.id
    bot.answer_callback_query(call.id)
    
    if data == "menu_back":
        text, kb = get_main_menu(uid, name)
        bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=kb)
    elif data == "menu_balance":
        bal = get_balance(uid)
        text = f"👤 <b>MY PROFILE</b>\n🆔 <b>ID:</b> <code>{uid}</code>\n💵 <b>Balance:</b> ₹{bal:.2f}"
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
        bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=kb)
    elif data == "menu_shop":
        products = list(products_col.find({}))
        if not products:
            return bot.answer_callback_query(call.id, "Store is empty!", show_alert=True)
        kb = InlineKeyboardMarkup(row_width=1)
        for p in products:
            kb.add(InlineKeyboardButton(f"📦 {p.get('name', 'Unknown')}", callback_data=f"view|{str(p['_id'])}"))
        kb.add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
        bot.edit_message_text("🛒 <b>STORE PRODUCTS</b>", chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=kb)
    elif data.startswith("view|"):
        p_id = data.split("|")[1]
        product = products_col.find_one({"_id": ObjectId(p_id)})
        if not product: return
        text = f"📦 <b>{product.get('name', 'Unknown')}</b>\n"
        kb = InlineKeyboardMarkup(row_width=2)
        for dur, price in product.get("prices", {}).items():
            kb.add(InlineKeyboardButton(f"⏱ {dur} - ₹{price}", callback_data=f"buy|{p_id}|{dur}"))
        kb.add(InlineKeyboardButton("🔙 Back", callback_data="menu_shop"))
        bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=kb)
    elif data.startswith("buy|"):
        parts = data.split("|")
        p_id, duration = parts[1], parts[2]
        product = products_col.find_one({"_id": ObjectId(p_id)})
        if not product: return
        price = float(product.get("prices", {}).get(duration, 0))
        
        if deduct_balance(uid, price):
            bot.edit_message_text("⚡ <i>Processing API...</i>", chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
            try:
                data_req = {'api_key': RESELLER_API_KEY, 'action': 'buy', 'product_id': str(product.get("pid", "")).strip(), 'duration': str(duration).strip(), 'quantity': 1}
                res = requests.post(RESELLER_API_URL, data=data_req, headers={'x-master-key': MASTER_KEY}, timeout=20)
                result = res.json()
            except Exception as e: result = {"status": "error", "message": str(e)}
            
            if result.get("status") == "success" or "keys" in result:
                key = result.get("keys", ["Key not found"])[0]
                log_order(uid, product.get('name', 'Unknown'), key, price)
                bot.edit_message_text(f"✅ <b>PURCHASE SUCCESSFUL</b>\n🔑 Key: <code>{key}</code>", chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
            else:
                credit_balance(uid, price) # Refund
                bot.edit_message_text(f"❌ <b>Failed (Out of Stock)</b>\nRefunded ₹{price} to wallet.", chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
        else:
            bot.answer_callback_query(call.id, "❌ Low Balance! Please add funds on website.", show_alert=True)
    elif data == "menu_addfund":
        bot.edit_message_text("💸 Please visit the website to add balance instantly!", chat_id=chat_id, message_id=msg_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("💻 Open Website", web_app=WebAppInfo(url=WEB_URL))))


# ================== FLASK WEB APP (TM PANEL UI) ==================
app = Flask(__name__)
app.secret_key = "saksham_secret_key"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# -------- GLOBAL CSS (NEON DARK THEME) --------
BASE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;800&display=swap');
    * { box-sizing: border-box; font-family: 'Poppins', sans-serif; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body { background-color: #090a0f; color: #fff; padding-bottom: 80px; background-image: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #090a0f 60%); }
    
    /* Top Navbar */
    .top-nav { display: flex; justify-content: space-between; align-items: center; padding: 15px 20px; background: rgba(15, 23, 42, 0.8); backdrop-filter: blur(10px); position: sticky; top: 0; z-index: 100; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .store-btn { background: linear-gradient(45deg, #0ea5e9, #3b82f6); padding: 8px 15px; border-radius: 20px; font-weight: 600; display: flex; align-items: center; gap: 5px; font-size: 14px; box-shadow: 0 0 10px rgba(14, 165, 233, 0.5); color: white; text-decoration: none; }
    .reseller-badge { background: linear-gradient(45deg, #f59e0b, #ef4444); padding: 5px 10px; border-radius: 15px; font-size: 10px; font-weight: 800; color: #fff; text-transform: uppercase; margin-left: 5px; }
    .wallet-box { background: rgba(16, 185, 129, 0.1); border: 1px solid #10b981; padding: 5px 12px; border-radius: 20px; display: flex; align-items: center; gap: 8px; font-weight: 700; color: #10b981; font-size: 14px; }
    .top-up-btn { background: linear-gradient(45deg, #6366f1, #a855f7); padding: 8px 15px; border-radius: 20px; font-weight: 600; font-size: 14px; color: white; border: none; cursor: pointer; box-shadow: 0 0 15px rgba(168, 85, 247, 0.4); text-decoration: none; }
    
    /* Container */
    .container { padding: 20px; max-width: 800px; margin: 0 auto; }
    
    /* Hero Banner */
    .hero-banner { width: 100%; height: 180px; background: linear-gradient(135deg, #1e1b4b, #312e81, #4338ca); border-radius: 20px; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; margin-bottom: 20px; border: 1px solid #6366f1; box-shadow: 0 10px 30px rgba(99, 102, 241, 0.2); position: relative; overflow: hidden; }
    .hero-banner h1 { font-size: 24px; font-weight: 800; text-shadow: 0 0 10px rgba(255,255,255,0.5); background: linear-gradient(90deg, #fbbf24, #f59e0b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .hero-banner p { font-size: 12px; color: #cbd5e1; margin-top: 5px; }
    .tg-btn { background: #0ea5e9; color: white; padding: 8px 20px; border-radius: 20px; text-decoration: none; font-size: 12px; font-weight: 600; margin-top: 10px; display: inline-block; }

    /* Stats Grid */
    .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px; }
    .stat-card { background: rgba(30, 41, 59, 0.6); border-radius: 12px; padding: 15px; border: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; justify-content: center; }
    .stat-title { font-size: 11px; color: #94a3b8; font-weight: 600; margin-bottom: 5px; display: flex; align-items: center; gap: 5px; text-transform: uppercase; }
    .stat-value { font-size: 20px; font-weight: 800; }
    .text-green { color: #10b981; }
    .text-blue { color: #38bdf8; }
    .text-yellow { color: #f59e0b; }

    /* Reseller VIP Banner */
    .vip-banner { background: linear-gradient(90deg, rgba(16, 185, 129, 0.2), rgba(16, 185, 129, 0.05)); border: 1px solid #10b981; border-radius: 12px; padding: 15px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; box-shadow: 0 0 15px rgba(16, 185, 129, 0.2); }
    .vip-title { font-size: 14px; font-weight: 700; color: #10b981; }
    .vip-desc { font-size: 11px; color: #94a3b8; margin-top: 3px; }
    .vip-badge { background: #10b981; color: #000; padding: 5px 10px; border-radius: 8px; font-size: 10px; font-weight: 800; }

    /* Live Purchases */
    .live-title { display: flex; align-items: center; gap: 10px; font-size: 14px; font-weight: 700; margin-bottom: 10px; }
    .live-dot { width: 8px; height: 8px; background: #ef4444; border-radius: 50%; box-shadow: 0 0 10px #ef4444; animation: pulse 1s infinite; }
    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
    .live-scroll { display: flex; gap: 10px; overflow-x: auto; padding-bottom: 10px; scrollbar-width: none; }
    .live-scroll::-webkit-scrollbar { display: none; }
    .live-card { min-width: 180px; background: rgba(30, 41, 59, 0.8); padding: 10px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.05); flex-shrink: 0; }
    .live-card .user { font-size: 10px; color: #94a3b8; }
    .live-card .prod { font-size: 12px; font-weight: 700; color: #fff; margin: 5px 0; }
    .live-card .key { font-size: 10px; color: #38bdf8; font-family: monospace; }

    /* Products Section */
    .section-title { font-size: 16px; font-weight: 700; margin-bottom: 15px; margin-top: 20px; display: flex; align-items: center; gap: 8px; color: #fff; }
    .product-grid { display: grid; grid-template-columns: 1fr; gap: 15px; }
    .product-card { background: linear-gradient(145deg, #1e293b, #0f172a); border-radius: 15px; padding: 15px; border: 1px solid rgba(255,255,255,0.05); display: flex; flex-direction: column; }
    .product-title { font-size: 16px; font-weight: 700; color: #fff; margin-bottom: 10px; }
    .price-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px; }
    .price-tag { background: rgba(56, 189, 248, 0.1); color: #38bdf8; padding: 4px 8px; border-radius: 6px; font-size: 12px; font-weight: 600; }
    .buy-btn { background: linear-gradient(90deg, #0ea5e9, #3b82f6); color: white; text-align: center; padding: 12px; border-radius: 10px; text-decoration: none; font-weight: 600; font-size: 14px; border: none; cursor: pointer; }

    /* Bottom Nav */
    .bottom-nav { position: fixed; bottom: 0; left: 0; width: 100%; background: #0f172a; display: flex; justify-content: space-around; padding: 10px 0; border-top: 1px solid rgba(255,255,255,0.05); z-index: 100; padding-bottom: env(safe-area-inset-bottom, 15px); }
    .nav-item { display: flex; flex-direction: column; align-items: center; color: #64748b; text-decoration: none; font-size: 10px; font-weight: 600; gap: 5px; }
    .nav-item.active { color: #0ea5e9; }
    .nav-icon { font-size: 20px; }

    /* Forms & Inputs */
    .input-group { margin-bottom: 15px; }
    .input-group label { display: block; font-size: 12px; color: #94a3b8; margin-bottom: 5px; }
    .input-group input { width: 100%; padding: 12px; border-radius: 10px; border: 1px solid #334155; background: #0f172a; color: #fff; font-size: 14px; outline: none; }
    .input-group input:focus { border-color: #38bdf8; }
    .submit-btn { width: 100%; background: linear-gradient(90deg, #10b981, #059669); color: #fff; padding: 14px; border-radius: 10px; border: none; font-weight: 700; font-size: 14px; cursor: pointer; }
</style>
"""

def get_bottom_nav(active):
    return f"""
    <div class="bottom-nav">
        <a href="/" class="nav-item {'active' if active == 'store' else ''}">
            <span class="nav-icon">🛍️</span> Store
        </a>
        <a href="/keys" class="nav-item {'active' if active == 'keys' else ''}">
            <span class="nav-icon">🔑</span> My Keys
        </a>
        <a href="/deposit" class="nav-item {'active' if active == 'deposit' else ''}">
            <span class="nav-icon">💰</span> Deposit
        </a>
        <a href="/history" class="nav-item {'active' if active == 'history' else ''}">
            <span class="nav-icon">📜</span> History
        </a>
        <a href="/profile" class="nav-item {'active' if active == 'profile' else ''}">
            <span class="nav-icon">👤</span> Profile
        </a>
    </div>
    """

@app.route('/')
def web_home():
    try:
        if 'uid' not in session:
            return render_template_string(BASE_CSS + """
            <div class="container" style="margin-top: 50px;">
                <div class="hero-banner">
                    <h1>TM PANEL SHOP</h1>
                    <p>Premium Panel Store</p>
                </div>
                <div style="background: rgba(30, 41, 59, 0.8); padding: 20px; border-radius: 15px;">
                    <h2 style="font-size: 18px; margin-bottom: 15px;">Login to Continue</h2>
                    <form method="POST" action="/login">
                        <div class="input-group">
                            <label>Telegram ID</label>
                            <input type="text" name="uid" placeholder="e.g. 7778093775" required>
                        </div>
                        <button type="submit" class="submit-btn">Login</button>
                    </form>
                </div>
            </div>
            """)
        
        uid = session['uid']
        u = get_user_info(uid)
        bal = u.get('balance', 0.0)
        
        # Fetch Live Orders (Latest 5)
        live_orders = list(orders_col.find({}).sort("_id", -1).limit(5))
        live_html = ""
        for o in live_orders:
            live_html += f"""
            <div class="live-card">
                <div class="user">👤 User***{str(o.get('uid', 'XXX'))[-3:]}</div>
                <div class="prod">📦 {o.get('product', 'Unknown')}</div>
                <div class="key">🔑 {str(o.get('key', 'XXX'))[:10]}***</div>
            </div>
            """
        if not live_orders:
            live_html = "<div style='color:#64748b; font-size:12px;'>No live purchases yet.</div>"

        # Fetch Products
        products = list(products_col.find({}))
        prod_html = ""
        for p in products:
            prices = p.get('prices', {})
            price_tags = "".join([f"<span class='price-tag'>{d} - ₹{pr}</span>" for d, pr in prices.items()])
            prod_html += f"""
            <div class="product-card">
                <div class="product-title">📦 {p.get('name', 'Unknown')}</div>
                <div class="price-row">{price_tags}</div>
                <a href="/product/{str(p['_id'])}" class="buy-btn">View & Buy</a>
            </div>
            """

        user_orders = list(orders_col.find({'uid': str(uid)}))
        total_spent = sum([float(o.get('price', 0)) for o in user_orders])

        return render_template_string(BASE_CSS + f"""
        <div class="top-nav">
            <div style="display:flex; align-items:center; gap:10px;">
                <a href="/" class="store-btn">📦 Store</a>
                <span class="reseller-badge">Reseller</span>
            </div>
            <div style="display:flex; align-items:center; gap:10px;">
                <div class="wallet-box">💳 ₹{bal:.2f}</div>
                <a href="/deposit" class="top-up-btn">⚡ TOP UP</a>
            </div>
        </div>

        <div class="container">
            <div class="hero-banner">
                <h1>TM PANEL SHOP</h1>
                <p>Premium Panel Store</p>
                <a href="https://t.me/SakshamPannelBot" class="tg-btn">JOIN TELEGRAM BOT</a>
            </div>

            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-title">💳 Wallet Balance</div>
                    <div class="stat-value text-green">₹{bal:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">🔑 Keys Purchased</div>
                    <div class="stat-value text-blue">{len(user_orders)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">⚡ Today's Spend</div>
                    <div class="stat-value text-yellow">₹0.00</div>
                </div>
                <div class="stat-card">
                    <div class="stat-title">🛍️ Total Spent</div>
                    <div class="stat-value text-yellow">₹{total_spent:.2f}</div>
                </div>
            </div>

            <div class="vip-banner">
                <div>
                    <div class="vip-title">👑 RESELLER VIP PANEL ACTIVE</div>
                    <div class="vip-desc">Main website wholesale reseller discount rates applied.</div>
                </div>
                <div class="vip-badge">RESELLER</div>
            </div>

            <div class="live-title">
                <div class="live-dot"></div> Live Purchases <span style="background:#ef4444; color:#fff; padding:2px 8px; border-radius:10px; font-size:10px;">1000+ LIVE</span>
            </div>
            <div class="live-scroll">
                {live_html}
            </div>

            <div class="section-title">🔥 Browse Products</div>
            <div style="font-size: 12px; color: #38bdf8; margin-bottom: 10px;">>> MARKETPLACE / RESELLER WHOLESALE STOCK</div>
            <div class="product-grid">
                {prod_html}
            </div>
        </div>
        {get_bottom_nav('store')}
        """)
    except Exception as e:
        return f"System Error: {str(e)}" # Returns error to screen instead of 500 crash

@app.route('/login', methods=['POST'])
def web_login():
    uid = request.form['uid'].strip()
    session['uid'] = uid
    get_user_info(uid) 
    return redirect(url_for('web_home'))

@app.route('/product/<p_id>')
def web_product(p_id):
    if 'uid' not in session: return redirect(url_for('web_home'))
    p = products_col.find_one({"_id": ObjectId(p_id)})
    if not p: return "Product not found", 404
    
    price_tags = "".join([f"""
        <form action="/buy_web" method="POST" style="margin-bottom:10px;">
            <input type="hidden" name="p_id" value="{p_id}">
            <input type="hidden" name="duration" value="{d}">
            <button type="submit" class="submit-btn" style="display:flex; justify-content:space-between; background:linear-gradient(90deg, #0ea5e9, #3b82f6);">
                <span>⏱ {d}</span>
                <span>₹{pr}</span>
            </button>
        </form>
    """ for d, pr in p.get('prices', {}).items()])

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <a href="/" class="store-btn">🔙 Back</a>
        <div class="wallet-box">💳 ₹{get_balance(session['uid']):.2f}</div>
    </div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card">
            <div class="product-title" style="font-size:20px;">📦 {p.get('name', 'Unknown')}</div>
            <p style="color:#94a3b8; font-size:12px; margin-bottom:20px;">{p.get('description', 'Instant delivery key.')}</p>
            <div class="section-title" style="margin-top:0;">Select Duration:</div>
            {price_tags}
        </div>
    </div>
    {get_bottom_nav('store')}
    """)

@app.route('/buy_web', methods=['POST'])
def buy_web():
    if 'uid' not in session: return redirect(url_for('web_home'))
    uid = session['uid']
    p_id = request.form['p_id']
    duration = request.form['duration']
    
    product = products_col.find_one({"_id": ObjectId(p_id)})
    price = float(product.get("prices", {}).get(duration, 0))
    
    if deduct_balance(uid, price):
        try:
            data = {'api_key': RESELLER_API_KEY, 'action': 'buy', 'product_id': str(product.get("pid", "")).strip(), 'duration': str(duration).strip(), 'quantity': 1}
            res = requests.post(RESELLER_API_URL, data=data, headers={'x-master-key': MASTER_KEY}, timeout=20)
            result = res.json()
        except Exception as e: result = {"status": "error", "message": str(e)}
            
        if result.get("status") == "success" or "keys" in result:
            key = result.get("keys", ["Key not found"])[0]
            log_order(uid, product.get('name', 'Unknown'), key, price)
            return render_template_string(BASE_CSS + f"""
            <div class="container" style="margin-top:50px;">
                <div class="product-card" style="text-align:center;">
                    <h2 style="color:#10b981; margin-bottom:15px;">✅ Purchase Successful!</h2>
                    <p style="color:#94a3b8;">Your Key:</p>
                    <div style="background:#0f172a; padding:15px; border-radius:10px; border:1px solid #38bdf8; font-family:monospace; font-size:18px; margin:15px 0;">{key}</div>
                    <a href="/keys" class="submit-btn" style="display:block; text-decoration:none;">Go to My Keys</a>
                </div>
            </div>
            {get_bottom_nav('store')}
            """)
        else:
            credit_balance(uid, price)
            return render_template_string(BASE_CSS + f"""
            <div class="container" style="margin-top:50px;">
                <div class="product-card" style="text-align:center;">
                    <h2 style="color:#ef4444; margin-bottom:15px;">❌ Out of Stock</h2>
                    <p style="color:#94a3b8;">API Error: {result.get('message', 'Unknown')}</p>
                    <p style="color:#10b981; margin-top:10px;">₹{price} Refunded to Wallet.</p>
                    <br><a href="/" class="submit-btn" style="display:block; text-decoration:none;">Back to Store</a>
                </div>
            </div>
            {get_bottom_nav('store')}
            """)
    return redirect(url_for('web_home'))

@app.route('/keys')
def web_keys():
    if 'uid' not in session: return redirect(url_for('web_home'))
    uid = session['uid']
    orders = list(orders_col.find({"uid": str(uid)}).sort("_id", -1))
    
    keys_html = ""
    for o in orders:
        keys_html += f"""
        <div class="product-card" style="margin-bottom:10px;">
            <div style="font-size:12px; color:#94a3b8;">{o.get('time', '')}</div>
            <div style="font-weight:700; margin:5px 0;">📦 {o.get('product', 'Unknown')}</div>
            <div style="background:#0f172a; padding:10px; border-radius:8px; font-family:monospace; font-size:14px; color:#38bdf8; border:1px solid rgba(56,189,248,0.3);">{o.get('key', 'N/A')}</div>
        </div>
        """
    if not orders: keys_html = "<p style='color:#94a3b8; text-align:center;'>No keys purchased yet.</p>"

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:700;">🔑 My Keys</div>
        <div class="wallet-box">💳 ₹{get_balance(uid):.2f}</div>
    </div>
    <div class="container" style="margin-top:20px;">
        {keys_html}
    </div>
    {get_bottom_nav('keys')}
    """)

@app.route('/deposit')
def web_deposit():
    if 'uid' not in session: return redirect(url_for('web_home'))
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:700;">💰 Deposit</div>
        <div class="wallet-box">💳 ₹{get_balance(session['uid']):.2f}</div>
    </div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card">
            <h3 style="margin-bottom:15px;">Add Balance to Wallet</h3>
            <form action="/gen_qr_web" method="POST">
                <div class="input-group">
                    <label>Enter Amount (₹)</label>
                    <input type="number" name="amount" min="10" required placeholder="e.g. 100">
                </div>
                <button type="submit" class="submit-btn">Generate Payment QR</button>
            </form>
        </div>
    </div>
    {get_bottom_nav('deposit')}
    """)

@app.route('/gen_qr_web', methods=['POST'])
def gen_qr_web():
    if 'uid' not in session: return redirect(url_for('web_home'))
    amount = float(request.form['amount'])
    try:
        order = fg.create_order(amount=amount, customer_name=session['uid'])
        return render_template_string(BASE_CSS + f"""
        <div class="top-nav"><a href="/deposit" class="store-btn">🔙 Back</a></div>
        <div class="container" style="margin-top:20px; text-align:center;">
            <div class="product-card">
                <h2 style="color:#10b981;">Pay ₹{amount}</h2>
                <p style="color:#94a3b8; margin:10px 0;">Order ID: {order.order_id}</p>
                <img src="{order.qr_url}" style="width:100%; max-width:250px; border-radius:15px; border:2px solid #38bdf8; margin:15px 0;">
                <p style="color:#f59e0b; font-size:12px;">Scan and pay. Balance will be added automatically.</p>
                <a href="/" class="submit-btn" style="display:block; text-decoration:none; margin-top:15px;">I have paid (Check Status)</a>
            </div>
        </div>
        {get_bottom_nav('deposit')}
        """)
    except Exception as e:
        return f"API Error: {e}"

@app.route('/history')
def web_history():
    if 'uid' not in session: return redirect(url_for('web_home'))
    uid = session['uid']
    orders = list(orders_col.find({"uid": str(uid)}).sort("_id", -1))
    
    html = ""
    for o in orders:
        html += f"""
        <div class="product-card" style="margin-bottom:10px;">
            <div style="display:flex; justify-content:space-between; font-size:12px; color:#94a3b8; margin-bottom:5px;">
                <span>{o.get('time', '')}</span>
                <span style="color:#ef4444;">-₹{o.get('price', 0)}</span>
            </div>
            <div style="font-weight:700;">{o.get('product', 'Unknown')}</div>
        </div>
        """
    
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:700;">📜 History</div>
        <div class="wallet-box">💳 ₹{get_balance(uid):.2f}</div>
    </div>
    <div class="container" style="margin-top:20px;">
        {html if html else '<p style="text-align:center; color:#94a3b8;">No transactions yet.</p>'}
    </div>
    {get_bottom_nav('history')}
    """)

@app.route('/profile')
def web_profile():
    if 'uid' not in session: return redirect(url_for('web_home'))
    uid = session['uid']
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:700;">👤 Profile</div>
        <a href="/logout" class="store-btn" style="background:#ef4444;">Logout</a>
    </div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card" style="text-align:center;">
            <div style="font-size:50px; margin-bottom:10px;">👤</div>
            <h2 style="color:#38bdf8;">{get_user_info(uid).get('name', 'User')}</h2>
            <p style="color:#94a3b8; margin-bottom:15px;">ID: {uid}</p>
            <div class="wallet-box" style="display:inline-flex; font-size:16px;">💳 ₹{get_balance(uid):.2f}</div>
        </div>
    </div>
    {get_bottom_nav('profile')}
    """)

@app.route('/logout')
def logout():
    session.pop('uid', None)
    return redirect(url_for('web_home'))

@app.route('/admin')
def admin_panel():
    if 'uid' not in session or str(session['uid']) != str(ADMIN_ID):
        return "Access Denied. Login with Admin ID first."
    
    products = list(products_col.find({}))
    prod_html = "".join([f"<div style='padding:10px; border-bottom:1px solid #333;'><b>{p.get('name', 'Unknown')}</b> (PID: {p.get('pid', '')})</div>" for p in products])
    
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><div style="font-weight:700;">💻 Admin Panel</div></div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card">
            <h3>All Products</h3>
            <div style="margin-top:15px;">{prod_html}</div>
        </div>
    </div>
    """)

# ================== RUNNING APP ==================
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def run_bot():
    print("Starting Telegram Bot...")
    try: bot.delete_webhook(drop_pending_updates=True) 
    except: pass
    bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_flask()
