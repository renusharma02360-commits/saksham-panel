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
        default_s = {"_id": "global", "store_name": "SK PANEL SHOP", "support_username": "YourSupport"}
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

# ================== TELEGRAM BOT ==================
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.from_user.id
    get_user_info(uid)
    text = f"✨ <b>WELCOME, {msg.from_user.first_name}</b>\n💳 <b>Wallet:</b> ₹{get_balance(uid):.2f}\n\n👇 <i>Choose an option:</i>"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🛒 Shop", web_app=WebAppInfo(url=WEB_URL)), InlineKeyboardButton("💻 My Profile", web_app=WebAppInfo(url=f"{WEB_URL}/profile")))
    if str(uid) == str(ADMIN_ID):
        kb.add(InlineKeyboardButton("⚙️ Admin Panel", web_app=WebAppInfo(url=f"{WEB_URL}/admin")))
    bot.send_message(msg.chat.id, text, parse_mode="HTML", reply_markup=kb)

# ================== FLASK WEB APP (HD UI & ADMIN PANEL) ==================
app = Flask(__name__)
app.secret_key = "sk_panel_secret"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# -------- HD CSS --------
BASE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap');
    * { box-sizing: border-box; font-family: 'Poppins', sans-serif; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body { background-color: #05070a; color: #fff; padding-bottom: 90px; background-image: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #05070a 50%); min-height: 100vh; }
    
    /* HD Top Navbar */
    .top-nav { display: flex; justify-content: space-between; align-items: center; padding: 15px 20px; background: rgba(15, 23, 42, 0.9); backdrop-filter: blur(15px); position: sticky; top: 0; z-index: 100; border-bottom: 1px solid rgba(255,255,255,0.1); }
    .store-btn { background: linear-gradient(45deg, #0ea5e9, #3b82f6); padding: 10px 20px; border-radius: 25px; font-weight: 700; display: flex; align-items: center; gap: 8px; font-size: 15px; box-shadow: 0 4px 15px rgba(14, 165, 233, 0.4); color: white; text-decoration: none; }
    .reseller-badge { background: linear-gradient(45deg, #f59e0b, #ef4444); padding: 6px 12px; border-radius: 20px; font-size: 11px; font-weight: 800; color: #fff; text-transform: uppercase; margin-left: 8px; box-shadow: 0 0 10px rgba(245, 158, 11, 0.5); }
    .wallet-box { background: rgba(16, 185, 129, 0.15); border: 1.5px solid #10b981; padding: 8px 16px; border-radius: 25px; font-weight: 800; color: #10b981; font-size: 15px; box-shadow: 0 0 15px rgba(16, 185, 129, 0.2); }
    .top-up-btn { background: linear-gradient(45deg, #6366f1, #a855f7); padding: 10px 18px; border-radius: 25px; font-weight: 800; font-size: 14px; color: white; border: none; box-shadow: 0 4px 15px rgba(168, 85, 247, 0.4); text-decoration: none; }
    
    /* Container */
    .container { padding: 20px; max-width: 600px; margin: 0 auto; }
    
    /* HD Hero Banner */
    .hero-banner { width: 100%; height: 200px; background: linear-gradient(135deg, #1e1b4b, #312e81, #4338ca); border-radius: 20px; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; margin-bottom: 25px; border: 2px solid #6366f1; box-shadow: 0 15px 35px rgba(99, 102, 241, 0.3); }
    .hero-banner h1 { font-size: 28px; font-weight: 800; text-shadow: 0 0 15px rgba(255,255,255,0.6); background: linear-gradient(90deg, #fbbf24, #f59e0b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: 1px; }
    .hero-banner p { font-size: 14px; color: #cbd5e1; margin-top: 8px; font-weight: 500; }

    /* Stats Grid HD */
    .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 25px; }
    .stat-card { background: rgba(30, 41, 59, 0.8); border-radius: 15px; padding: 18px; border: 1.5px solid rgba(255,255,255,0.08); box-shadow: 0 5px 15px rgba(0,0,0,0.3); }
    .stat-title { font-size: 12px; color: #94a3b8; font-weight: 700; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
    .stat-value { font-size: 24px; font-weight: 800; }
    .text-green { color: #10b981; text-shadow: 0 0 10px rgba(16,185,129,0.4); }
    .text-blue { color: #38bdf8; text-shadow: 0 0 10px rgba(56,189,248,0.4); }
    .text-yellow { color: #f59e0b; text-shadow: 0 0 10px rgba(245,158,11,0.4); }

    /* VIP Banner */
    .vip-banner { background: linear-gradient(90deg, rgba(16, 185, 129, 0.25), rgba(16, 185, 129, 0.05)); border: 2px solid #10b981; border-radius: 15px; padding: 20px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; box-shadow: 0 0 20px rgba(16, 185, 129, 0.3); }
    .vip-title { font-size: 16px; font-weight: 800; color: #10b981; }
    .vip-desc { font-size: 12px; color: #cbd5e1; margin-top: 5px; font-weight: 500; }
    .vip-badge { background: #10b981; color: #000; padding: 8px 15px; border-radius: 10px; font-size: 12px; font-weight: 800; box-shadow: 0 0 10px rgba(16,185,129,0.5); }

    /* Products */
    .product-grid { display: grid; grid-template-columns: 1fr; gap: 20px; }
    .product-card { background: linear-gradient(145deg, #111827, #0f172a); border-radius: 18px; padding: 20px; border: 1.5px solid rgba(255,255,255,0.08); box-shadow: 0 8px 25px rgba(0,0,0,0.4); }
    .product-title { font-size: 18px; font-weight: 800; color: #fff; margin-bottom: 15px; letter-spacing: 0.5px; }
    .price-row { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }
    .price-tag { background: rgba(56, 189, 248, 0.15); color: #38bdf8; padding: 8px 12px; border-radius: 8px; font-size: 14px; font-weight: 700; border: 1px solid rgba(56,189,248,0.3); }
    .buy-btn { background: linear-gradient(90deg, #0ea5e9, #3b82f6); color: white; text-align: center; padding: 15px; border-radius: 12px; text-decoration: none; font-weight: 800; font-size: 16px; border: none; box-shadow: 0 5px 15px rgba(14, 165, 233, 0.4); display: block; }

    /* Forms & Inputs (HD) */
    .input-group { margin-bottom: 20px; }
    .input-group label { display: block; font-size: 14px; color: #cbd5e1; margin-bottom: 8px; font-weight: 600; }
    .input-group input, .input-group textarea { width: 100%; padding: 16px; border-radius: 12px; border: 1.5px solid #334155; background: #0f172a; color: #fff; font-size: 16px; outline: none; font-weight: 500; transition: 0.3s; }
    .input-group input:focus { border-color: #38bdf8; box-shadow: 0 0 10px rgba(56, 189, 248, 0.2); }
    .submit-btn { width: 100%; background: linear-gradient(90deg, #10b981, #059669); color: #fff; padding: 16px; border-radius: 12px; border: none; font-weight: 800; font-size: 16px; box-shadow: 0 5px 15px rgba(16, 185, 129, 0.3); display: block; text-align: center; }
    .video-btn { background: linear-gradient(90deg, #ef4444, #dc2626); color: #fff; padding: 12px; border-radius: 10px; border: none; font-weight: 700; font-size: 14px; display: block; width: 100%; margin-bottom: 10px; text-align: center; text-decoration: none; }

    /* Bottom Nav HD */
    .bottom-nav { position: fixed; bottom: 0; left: 0; width: 100%; background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(10px); display: flex; justify-content: space-around; padding: 15px 0; border-top: 1.5px solid rgba(255,255,255,0.08); z-index: 100; padding-bottom: env(safe-area-inset-bottom, 15px); }
    .nav-item { display: flex; flex-direction: column; align-items: center; color: #64748b; text-decoration: none; font-size: 11px; font-weight: 700; gap: 6px; transition: 0.3s; }
    .nav-item.active { color: #38bdf8; }
    .nav-icon { font-size: 22px; }
</style>
"""

def get_bottom_nav(active):
    return f"""
    <div class="bottom-nav">
        <a href="/" class="nav-item {'active' if active == 'store' else ''}"><span class="nav-icon">🛍️</span> Store</a>
        <a href="/keys" class="nav-item {'active' if active == 'keys' else ''}"><span class="nav-icon">🔑</span> My Keys</a>
        <a href="/deposit" class="nav-item {'active' if active == 'deposit' else ''}"><span class="nav-icon">💰</span> Deposit</a>
        <a href="/history" class="nav-item {'active' if active == 'history' else ''}"><span class="nav-icon">📜</span> History</a>
        <a href="/profile" class="nav-item {'active' if active == 'profile' else ''}"><span class="nav-icon">👤</span> Profile</a>
    </div>
    """

@app.route('/')
def web_home():
    try:
        if 'uid' not in session:
            return render_template_string(BASE_CSS + """
            <div class="container" style="margin-top: 80px;">
                <div class="hero-banner">
                    <h1>SK PANEL SHOP</h1>
                    <p>Premium Panel Store</p>
                </div>
                <div style="background: rgba(30, 41, 59, 0.9); padding: 30px; border-radius: 20px; border: 1.5px solid rgba(255,255,255,0.1);">
                    <h2 style="font-size: 22px; margin-bottom: 20px; text-align: center; color: #38bdf8;">Login to Continue</h2>
                    <form method="POST" action="/login">
                        <div class="input-group">
                            <label>Enter Telegram ID</label>
                            <input type="text" name="uid" placeholder="e.g. 7778093775" required>
                        </div>
                        <button type="submit" class="submit-btn">Login Securely</button>
                    </form>
                </div>
            </div>
            """)
        
        uid = session['uid']
        u = get_user_info(uid)
        bal = u.get('balance', 0.0)
        discount = u.get('discount', 0)
        
        live_orders = list(orders_col.find({}).sort("_id", -1).limit(5))
        live_html = ""
        for o in live_orders:
            live_html += f"""
            <div class="live-card" style="min-width: 200px; background: rgba(30, 41, 59, 0.9); padding: 15px; border-radius: 12px; border: 1.5px solid rgba(255,255,255,0.05); flex-shrink: 0;">
                <div style="font-size: 11px; color: #94a3b8; font-weight: 600;">👤 User***{str(o.get('uid', 'XXX'))[-3:]}</div>
                <div style="font-size: 14px; font-weight: 700; color: #fff; margin: 5px 0;">📦 {o.get('product', 'Unknown')}</div>
                <div style="font-size: 11px; color: #38bdf8; font-family: monospace;">🔑 {str(o.get('key', 'XXX'))[:10]}***</div>
            </div>
            """
        
        # Reseller Logic
        vip_html = ""
        reseller_badge = ""
        if discount > 0:
            reseller_badge = f'<span class="reseller-badge">RESELLER</span>'
            vip_html = f"""
            <div class="vip-banner">
                <div>
                    <div class="vip-title">👑 RESELLER VIP ACTIVE</div>
                    <div class="vip-desc">You get {discount}% OFF on all products.</div>
                </div>
                <div class="vip-badge">VIP</div>
            </div>
            """

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
            <div style="display:flex; align-items:center;">
                <a href="/" class="store-btn">📦 Store</a>
                {reseller_badge}
            </div>
            <div style="display:flex; align-items:center; gap:10px;">
                <div class="wallet-box">₹{bal:.2f}</div>
                <a href="/deposit" class="top-up-btn">⚡ TOP UP</a>
            </div>
        </div>

        <div class="container">
            <div class="hero-banner">
                <h1>SK PANEL SHOP</h1>
                <p>Premium Panel Store</p>
            </div>

            <div class="stats-grid">
                <div class="stat-card"><div class="stat-title">💳 Wallet Balance</div><div class="stat-value text-green">₹{bal:.2f}</div></div>
                <div class="stat-card"><div class="stat-title">🔑 Keys Purchased</div><div class="stat-value text-blue">{len(user_orders)}</div></div>
                <div class="stat-card"><div class="stat-title">⚡ Today's Spend</div><div class="stat-value text-yellow">₹0.00</div></div>
                <div class="stat-card"><div class="stat-title">🛍️ Total Spent</div><div class="stat-value text-yellow">₹{total_spent:.2f}</div></div>
            </div>

            {vip_html}

            <div style="display:flex; align-items:center; gap:10px; font-size:15px; font-weight:800; margin-bottom:15px;">
                <span style="color:#ef4444; font-size:20px;">●</span> Live Purchases <span style="background:#ef4444; color:#fff; padding:3px 10px; border-radius:20px; font-size:11px;">1000+ LIVE</span>
            </div>
            <div style="display:flex; gap:15px; overflow-x:auto; padding-bottom:15px; margin-bottom:15px; scrollbar-width:none;">
                {live_html}
            </div>

            <div style="font-size: 18px; font-weight: 800; margin-bottom: 15px; margin-top: 25px; color: #fff;">🔥 Browse Products</div>
            <div style="font-size: 13px; color: #38bdf8; margin-bottom: 15px; font-weight:600;">>> MARKETPLACE / WHOLESALE STOCK</div>
            <div class="product-grid">
                {prod_html}
            </div>
        </div>
        {get_bottom_nav('store')}
        """)
    except Exception as e:
        return f"<h1>System Error</h1><p>{str(e)}</p>"

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
    
    uid = session['uid']
    u = get_user_info(uid)
    discount = u.get('discount', 0)
    
    price_tags = ""
    for d, pr in p.get('prices', {}).items():
        final_price = float(pr) - (float(pr) * discount / 100) if discount > 0 else float(pr)
        price_tags += f"""
        <form action="/buy_web" method="POST" style="margin-bottom:10px;">
            <input type="hidden" name="p_id" value="{p_id}">
            <input type="hidden" name="duration" value="{d}">
            <button type="submit" class="submit-btn" style="display:flex; justify-content:space-between; background:linear-gradient(90deg, #0ea5e9, #3b82f6);">
                <span>⏱ {d}</span>
                <span>₹{final_price:.2f}</span>
            </button>
        </form>
        """

    # Video Buttons
    video_html = ""
    if p.get("video"):
        video_html += f'<a href="{p["video"]}" target="_blank" class="video-btn" style="background:linear-gradient(90deg, #3b82f6, #2563eb);">📺 Watch Setup Video</a>'
    if p.get("hack"):
        video_html += f'<a href="{p["hack"]}" target="_blank" class="video-btn">🛠️ Watch Hack Video</a>'

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <a href="/" class="store-btn">🔙 Back</a>
        <div class="wallet-box">₹{get_balance(uid):.2f}</div>
    </div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card">
            <div class="product-title" style="font-size:22px;">📦 {p.get('name', 'Unknown')}</div>
            <p style="color:#94a3b8; font-size:14px; margin-bottom:20px; line-height:1.5;">{p.get('description', 'Instant delivery key.')}</p>
            
            <div style="margin-bottom: 20px;">
                {video_html}
            </div>

            <div style="font-size:16px; font-weight:700; margin-bottom:15px; color:#38bdf8;">Select Duration to Buy:</div>
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
    u = get_user_info(uid)
    discount = u.get('discount', 0)
    
    original_price = float(product.get("prices", {}).get(duration, 0))
    price = original_price - (original_price * discount / 100) if discount > 0 else original_price
    
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
                    <h2 style="color:#10b981; margin-bottom:15px; font-size:24px;">✅ Purchase Successful!</h2>
                    <p style="color:#cbd5e1; font-size:15px;">Your Key:</p>
                    <div style="background:#0f172a; padding:20px; border-radius:12px; border:2px solid #38bdf8; font-family:monospace; font-size:20px; margin:20px 0; font-weight:700;">{key}</div>
                    <a href="/keys" class="submit-btn" style="text-decoration:none;">Go to My Keys</a>
                </div>
            </div>
            {get_bottom_nav('store')}
            """)
        else:
            credit_balance(uid, price)
            return render_template_string(BASE_CSS + f"""
            <div class="container" style="margin-top:50px;">
                <div class="product-card" style="text-align:center;">
                    <h2 style="color:#ef4444; margin-bottom:15px; font-size:24px;">❌ Out of Stock</h2>
                    <p style="color:#cbd5e1;">API Error: {result.get('message', 'Unknown')}</p>
                    <p style="color:#10b981; margin-top:15px; font-weight:700;">₹{price:.2f} Refunded to Wallet.</p>
                    <br><a href="/" class="submit-btn" style="text-decoration:none;">Back to Store</a>
                </div>
            </div>
            {get_bottom_nav('store')}
            """)
    return redirect(url_for('web_home'))

# ---------------- ADMIN PANEL (FULL CONTROLLER) ----------------
@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    if 'uid' not in session or str(session['uid']) != str(ADMIN_ID):
        return "Access Denied. Login with Admin ID first."
    
    msg = ""
    if request.method == 'POST':
        try:
            name = request.form['name']
            pid = request.form['pid']
            desc = request.form['description']
            video = request.form['video']
            hack = request.form['hack']
            is_maintenance = request.form.get('is_maintenance') == 'true'
            
            # Parse Durations & Prices
            durs = request.form.getlist('duration[]')
            prices = request.form.getlist('price[]')
            price_dict = {d.strip(): float(p.strip()) for d, p in zip(durs, prices) if d.strip() and p.strip()}
            
            products_col.insert_one({
                "name": name, "pid": pid, "description": desc,
                "video": video, "hack": hack, 
                "is_maintenance": is_maintenance, "prices": price_dict
            })
            msg = "<div style='background:#10b981; color:#fff; padding:15px; border-radius:10px; margin-bottom:20px;'>✅ Product Added Successfully!</div>"
        except Exception as e:
            msg = f"<div style='background:#ef4444; color:#fff; padding:15px; border-radius:10px; margin-bottom:20px;'>❌ Error: {e}</div>"

    products = list(products_col.find({}))
    prod_html = ""
    for p in products:
        prod_html += f"""
        <div style="background:#1e293b; padding:15px; border-radius:10px; margin-bottom:10px; border:1px solid #334155;">
            <div style="font-weight:700; font-size:16px; color:#38bdf8;">{p.get('name', '')} (PID: {p.get('pid', '')})</div>
            <div style="font-size:12px; color:#94a3b8;">Setup Video: {p.get('video', 'None')} | Hack Video: {p.get('hack', 'None')}</div>
            <div style="margin-top:10px;">
                <form action="/delete_product/{p['_id']}" method="POST" style="display:inline;">
                    <button type="submit" style="background:#ef4444; color:#fff; border:none; padding:5px 10px; border-radius:5px; font-size:12px; cursor:pointer;">Delete</button>
                </form>
            </div>
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:800; font-size:18px;">⚙️ Admin Controller</div>
        <a href="/" class="store-btn" style="background:#ef4444;">Exit</a>
    </div>
    <div class="container" style="margin-top:20px;">
        {msg}
        <div style="background:rgba(30,41,59,0.9); padding:20px; border-radius:15px; margin-bottom:30px;">
            <h3 style="margin-bottom:15px; color:#38bdf8;">➕ Add New Product</h3>
            <form method="POST">
                <div class="input-group"><label>Product Name</label><input type="text" name="name" required></div>
                <div class="input-group"><label>PID</label><input type="text" name="pid" required></div>
                <div class="input-group"><label>Description</label><input type="text" name="description"></div>
                <div class="input-group"><label>Setup Video Link (URL)</label><input type="url" name="video" placeholder="https://youtu.be/..."></div>
                <div class="input-group"><label>Hack Video Link (URL)</label><input type="url" name="hack" placeholder="https://youtu.be/..."></div>
                <div class="input-group">
                    <label>Status</label>
                    <select name="is_maintenance" style="width:100%; padding:15px; border-radius:10px; background:#0f172a; color:#fff; border:1px solid #334155;">
                        <option value="false">🟢 Active</option>
                        <option value="true">🔴 Maintenance</option>
                    </select>
                </div>
                
                <label style="font-weight:700; color:#38bdf8; margin-top:10px; display:block;">Durations & Prices</label>
                <div id="price-container">
                    <div style="display:flex; gap:10px; margin-bottom:10px;">
                        <input type="text" name="duration[]" placeholder="e.g. 1 Day" style="flex:1; padding:12px; border-radius:8px; background:#0f172a; border:1px solid #334155; color:#fff;">
                        <input type="number" name="price[]" placeholder="₹ Price" style="flex:1; padding:12px; border-radius:8px; background:#0f172a; border:1px solid #334155; color:#fff;">
                    </div>
                </div>
                <button type="button" onclick="addPrice()" style="background:#f59e0b; color:#000; padding:10px; border:none; border-radius:8px; margin-bottom:15px; font-weight:700;">+ Add More Duration</button>
                
                <button type="submit" class="submit-btn">Save Product</button>
            </form>
        </div>

        <h3 style="margin-bottom:15px; color:#38bdf8;">📦 All Products ({len(products)})</h3>
        {prod_html}
    </div>
    <script>
        function addPrice() {{
            const c = document.getElementById('price-container');
            const d = document.createElement('div');
            d.style.display = 'flex'; d.style.gap = '10px'; d.style.marginBottom = '10px';
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1; padding:12px; border-radius:8px; background:#0f172a; border:1px solid #334155; color:#fff;"><input type="number" name="price[]" placeholder="Price" style="flex:1; padding:12px; border-radius:8px; background:#0f172a; border:1px solid #334155; color:#fff;">`;
            c.appendChild(d);
        }}
    </script>
    """)

@app.route('/delete_product/<p_id>', methods=['POST'])
def delete_product(p_id):
    if 'uid' not in session or str(session['uid']) != str(ADMIN_ID):
        return "Access Denied", 403
    products_col.delete_one({"_id": ObjectId(p_id)})
    return redirect(url_for('admin_panel'))

# ---------------- OTHER ROUTES ----------------
@app.route('/keys')
def web_keys():
    if 'uid' not in session: return redirect(url_for('web_home'))
    uid = session['uid']
    orders = list(orders_col.find({"uid": str(uid)}).sort("_id", -1))
    keys_html = "".join([f"""
        <div class="product-card" style="margin-bottom:15px;">
            <div style="font-size:12px; color:#94a3b8;">{o.get('time', '')}</div>
            <div style="font-weight:800; font-size:16px; margin:8px 0; color:#38bdf8;">📦 {o.get('product', 'Unknown')}</div>
            <div style="background:#0f172a; padding:15px; border-radius:10px; font-family:monospace; font-size:16px; color:#fff; border:1.5px solid #10b981;">{o.get('key', 'N/A')}</div>
        </div>
        """ for o in orders])
    if not orders: keys_html = "<p style='color:#94a3b8; text-align:center; font-size:16px;'>No keys purchased yet.</p>"
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><div style="font-weight:800; font-size:18px;">🔑 My Keys</div><div class="wallet-box">₹{get_balance(uid):.2f}</div></div>
    <div class="container" style="margin-top:20px;">{keys_html}</div>
    {get_bottom_nav('keys')}
    """)

@app.route('/deposit')
def web_deposit():
    if 'uid' not in session: return redirect(url_for('web_home'))
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><div style="font-weight:800; font-size:18px;">💰 Deposit</div><div class="wallet-box">₹{get_balance(session['uid']):.2f}</div></div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card">
            <h3 style="margin-bottom:20px; font-size:20px; color:#38bdf8;">Add Balance to Wallet</h3>
            <form action="/gen_qr_web" method="POST">
                <div class="input-group"><label>Enter Amount (₹)</label><input type="number" name="amount" min="10" required placeholder="e.g. 100"></div>
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
        <div class="container" style="margin-top:30px; text-align:center;">
            <div class="product-card">
                <h2 style="color:#10b981; font-size:24px;">Pay ₹{amount}</h2>
                <p style="color:#94a3b8; margin:10px 0;">Order ID: {order.order_id}</p>
                <img src="{order.qr_url}" style="width:100%; max-width:280px; border-radius:15px; border:2px solid #38bdf8; margin:20px 0;">
                <p style="color:#f59e0b; font-size:13px;">Scan and pay. Balance will be added automatically.</p>
                <a href="/" class="submit-btn" style="text-decoration:none; margin-top:20px;">I have paid (Check Status)</a>
            </div>
        </div>
        {get_bottom_nav('deposit')}
        """)
    except Exception as e:
        return f"API Error: {e}"

@app.route('/profile')
def web_profile():
    if 'uid' not in session: return redirect(url_for('web_home'))
    uid = session['uid']
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><div style="font-weight:800; font-size:18px;">👤 Profile</div><a href="/logout" class="store-btn" style="background:#ef4444;">Logout</a></div>
    <div class="container" style="margin-top:20px;">
        <div class="product-card" style="text-align:center;">
            <div style="font-size:60px; margin-bottom:15px;">👤</div>
            <h2 style="color:#38bdf8; font-size:22px;">{get_user_info(uid).get('name', 'User')}</h2>
            <p style="color:#94a3b8; margin-bottom:20px; font-size:15px;">ID: {uid}</p>
            <div class="wallet-box" style="display:inline-flex; font-size:20px; padding:10px 25px;">₹{get_balance(uid):.2f}</div>
        </div>
    </div>
    {get_bottom_nav('profile')}
    """)

@app.route('/history')
def web_history():
    if 'uid' not in session: return redirect(url_for('web_home'))
    uid = session['uid']
    orders = list(orders_col.find({"uid": str(uid)}).sort("_id", -1))
    html = "".join([f"""
        <div class="product-card" style="margin-bottom:15px;">
            <div style="display:flex; justify-content:space-between; font-size:12px; color:#94a3b8; margin-bottom:8px;">
                <span>{o.get('time', '')}</span><span style="color:#ef4444; font-weight:700;">-₹{o.get('price', 0)}</span>
            </div>
            <div style="font-weight:800; font-size:16px;">{o.get('product', 'Unknown')}</div>
        </div>
        """ for o in orders])
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><div style="font-weight:800; font-size:18px;">📜 History</div><div class="wallet-box">₹{get_balance(uid):.2f}</div></div>
    <div class="container" style="margin-top:20px;">{html if html else '<p style="text-align:center; color:#94a3b8;">No transactions yet.</p>'}</div>
    {get_bottom_nav('history')}
    """)

@app.route('/logout')
def logout():
    session.pop('uid', None)
    return redirect(url_for('web_home'))

# ================== RUNNING ==================
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def run_bot():
    try: bot.delete_webhook(drop_pending_updates=True) 
    except: pass
    bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_flask()
