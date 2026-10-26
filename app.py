import os
import time
import threading
import requests
import urllib.parse
import telebot
import uuid
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from famgateway import FamGateway
from flask import Flask, request, render_template_string, redirect, url_for, session, jsonify
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
web_users_col = db.web_users 
products_col = db.products
orders_col = db.orders
settings_col = db.settings

bot = telebot.TeleBot(BOT_TOKEN)
fg  = FamGateway(api_key=API_KEY)

# ---------------- DB HELPERS ----------------
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

def credit_atomic(uid, amount, utr):
    if orders_col.find_one({"utr": utr, "type": "deposit"}):
        return True, get_balance(uid)
    
    orders_col.insert_one({"utr": utr, "uid": str(uid), "amount": amount, "type": "deposit", "time": time.strftime("%d-%m-%Y %I:%M %p")})
    users_col.update_one({"_id": str(uid)}, {"$inc": {"balance": amount}}, upsert=True)
    return True, get_balance(uid)

def log_order(uid, product, key, price):
    orders_col.insert_one({"uid": str(uid), "product": product, "key": key, "price": price, "type": "purchase", "time": time.strftime("%d-%m-%Y %I:%M %p")})

# ================== TELEGRAM BOT ==================
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.from_user.id
    get_user_info(uid)
    text = f"✨ <b>WELCOME, {msg.from_user.first_name}</b>\n💳 <b>Wallet:</b> ₹{get_balance(uid):.2f}\n\n👇 <i>Choose an option:</i>"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🛒 Shop", web_app=WebAppInfo(url=WEB_URL)), InlineKeyboardButton("💻 My Profile", web_app=WebAppInfo(url=f"{WEB_URL}/keys")))
    if str(uid) == str(ADMIN_ID):
        kb.add(InlineKeyboardButton("⚙️ Admin Panel", web_app=WebAppInfo(url=f"{WEB_URL}/admin")))
    bot.send_message(msg.chat.id, text, parse_mode="HTML", reply_markup=kb)

# ================== FLASK WEB APP ==================
app = Flask(__name__)
app.secret_key = "sk_panel_secret"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

BASE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800;900&display=swap');
    * { box-sizing: border-box; font-family: 'Poppins', sans-serif; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body { background-color: #050810; color: #fff; padding-bottom: 100px; background-image: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #050810 70%); background-attachment: fixed; min-height: 100vh; animation: bodyFadeIn 0.8s ease-out; }
    @keyframes bodyFadeIn { from { opacity: 0; } to { opacity: 1; } }
    
    .container { padding: 15px; max-width: 900px; margin: 0 auto; animation: slideUp 0.5s ease-out; }
    @keyframes slideUp { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
    
    .top-nav { display: flex; justify-content: space-between; align-items: center; padding: 15px 20px; background: rgba(15, 23, 42, 0.9); backdrop-filter: blur(15px); position: sticky; top: 0; z-index: 100; border-bottom: 1px solid rgba(255,255,255,0.1); }
    .store-btn { background: linear-gradient(135deg, #0ea5e9, #2563eb); padding: 10px 20px; border-radius: 25px; font-weight: 800; font-size: 14px; color: white; text-decoration: none; box-shadow: 0 4px 15px rgba(14, 165, 233, 0.4); }
    .wallet-box { background: rgba(16, 185, 129, 0.15); border: 2px solid #10b981; padding: 8px 15px; border-radius: 25px; font-weight: 900; color: #10b981; font-size: 16px; }
    
    .hero-banner { width: 100%; padding: 30px 20px; background: linear-gradient(145deg, #1e1b4b, #0f172a); border-radius: 20px; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; margin-bottom: 20px; border: 2px solid #6366f1; box-shadow: inset 0 0 30px rgba(99, 102, 241, 0.2), 0 10px 40px rgba(0, 0, 0, 0.6); }
    .logo-text { font-size: 40px; font-weight: 900; background: linear-gradient(to right, #fbbf24, #f59e0b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 5px; text-shadow: 0 0 30px rgba(245, 158, 11, 0.5); }
    
    .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px; }
    .stat-card { background: linear-gradient(145deg, #0f172a, #1e293b); border-radius: 15px; padding: 20px; border: 1px solid rgba(255,255,255,0.08); }
    .stat-title { font-size: 13px; color: #94a3b8; font-weight: 700; margin-bottom: 8px; text-transform: uppercase; }
    .stat-value { font-size: 26px; font-weight: 900; }

    .product-grid { display: grid; grid-template-columns: 1fr; gap: 15px; }
    .product-card { background: linear-gradient(145deg, #0f172a, #050810); border-radius: 20px; padding: 20px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 15px 35px rgba(0,0,0,0.5); }
    .product-title { font-size: 20px; font-weight: 900; color: #fff; margin-bottom: 10px; }
    .price-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px; }
    .price-tag { background: rgba(56, 189, 248, 0.15); color: #38bdf8; padding: 8px 12px; border-radius: 8px; font-size: 14px; font-weight: 800; border: 1px solid rgba(56,189,248,0.4); }

    .action-btn { display: block; width: 100%; padding: 15px; border-radius: 12px; text-align: center; font-weight: 900; font-size: 16px; text-decoration: none; border: none; cursor: pointer; text-transform: uppercase; letter-spacing: 1px; }
    .btn-primary { background: linear-gradient(135deg, #0ea5e9, #3b82f6); color: white; box-shadow: 0 8px 25px rgba(14, 165, 233, 0.4); }
    .btn-success { background: linear-gradient(135deg, #10b981, #059669); color: white; box-shadow: 0 8px 25px rgba(16, 185, 129, 0.4); }
    .btn-danger { background: linear-gradient(135deg, #ef4444, #b91c1c); color: white; box-shadow: 0 8px 25px rgba(239, 68, 68, 0.4); }
    .btn-warning { background: linear-gradient(135deg, #f59e0b, #d97706); color: black; box-shadow: 0 8px 25px rgba(245, 158, 11, 0.4); }

    .input-group { margin-bottom: 15px; }
    .input-group label { display: block; font-size: 14px; color: #cbd5e1; margin-bottom: 8px; font-weight: 700; }
    .input-group input, .input-group textarea { width: 100%; padding: 15px; border-radius: 12px; border: 2px solid #334155; background: #0f172a; color: #fff; font-size: 15px; outline: none; font-weight: 600; }
    
    /* Screenshot Style Product Page (Compact) */
    .gameplay-banner { width: 100%; height: 180px; object-fit: cover; border-radius: 12px; border: 2px solid #00f0ff; box-shadow: 0 0 20px rgba(0, 240, 255, 0.3); margin-bottom: 15px; }
    .product-page-title { text-align: center; font-size: 20px; font-weight: 900; color: white; text-shadow: 0 0 10px rgba(255,255,255,0.3); margin-bottom: 15px; }
    .feature-item { background: #0a101f; border: 1px solid #1e293b; border-radius: 8px; padding: 12px; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; font-weight: 700; color: #e2e8f0; font-size: 14px; }
    .feature-item::before { content: '✅'; font-size: 16px; filter: drop-shadow(0 0 5px #10b981); }
    .check-btns { display: flex; gap: 8px; margin-top: 15px; margin-bottom: 20px; }
    .btn-cyan { flex: 1; background: transparent; border: 1.5px solid #00f0ff; color: #00f0ff; padding: 12px 5px; border-radius: 8px; font-weight: 800; font-size: 12px; text-align: center; text-decoration: none; text-transform: uppercase; display: flex; align-items: center; justify-content: center; gap: 5px; box-shadow: 0 0 10px rgba(0,240,255,0.2); }
    .btn-red { flex: 1; background: transparent; border: 1.5px solid #ef4444; color: #ef4444; padding: 12px 5px; border-radius: 8px; font-weight: 800; font-size: 12px; text-align: center; text-decoration: none; text-transform: uppercase; display: flex; align-items: center; justify-content: center; gap: 5px; box-shadow: 0 0 10px rgba(239,68,68,0.2); }
    
    .purchase-header { background: linear-gradient(90deg, #8b5cf6, #6366f1); color: white; padding: 12px; border-radius: 10px; text-align: center; font-weight: 900; font-size: 16px; text-transform: uppercase; margin-bottom: 15px; letter-spacing: 1px; box-shadow: 0 5px 15px rgba(139, 92, 246, 0.3); }
    
    .price-row-ui { display: flex; align-items: center; justify-content: space-between; background: #0a101f; border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 12px 15px; margin-bottom: 10px; }
    .price-dur { font-weight: 800; font-size: 15px; color: #00f0ff; margin-bottom: 2px; }
    .price-amt { font-weight: 900; font-size: 18px; color: white; }
    .buy-btn-ui { background: linear-gradient(90deg, #ff00cc, #ff3366); color: white; padding: 10px 20px; border-radius: 6px; font-weight: 900; font-size: 14px; border: none; cursor: pointer; box-shadow: 0 0 12px rgba(255, 0, 204, 0.4); text-transform: uppercase; }

    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
</style>
"""

# ================== USER AUTH ROUTES ==================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form['username']
        pw = request.form['password']
        existing_user = web_users_col.find_one({"username": user, "password": pw})
        if existing_user:
            session['uid'] = existing_user['uid']
            session['username'] = user
            return redirect(url_for('web_home'))
        else:
            return render_template_string(BASE_CSS + """
            <div class="container" style="margin-top: 50px;">
                <div class="product-card text-center">
                    <h2 style="color:#ef4444; margin-bottom:20px; font-size:28px;">❌ Invalid Login</h2>
                    <a href="/login" class="action-btn btn-primary">Try Again</a>
                </div>
            </div>
            """)
    
    if 'uid' in session: return redirect(url_for('web_home'))
    return render_template_string(BASE_CSS + """
    <div class="container fade-in" style="margin-top: 50px;">
        <div class="hero-banner"><div class="logo-text">SK PANEL</div></div>
        <div class="product-card">
            <h2 style="font-size: 24px; margin-bottom: 20px; text-align: center; color: #38bdf8; font-weight: 900;">User Login</h2>
            <form method="POST" action="/login">
                <div class="input-group"><label>Username</label><input type="text" name="username" required></div>
                <div class="input-group"><label>Password</label><input type="password" name="password" required></div>
                <button type="submit" class="action-btn btn-success">Login</button>
            </form>
            <div style="text-align: center; margin-top: 20px;">
                <a href="/register" style="color: #38bdf8; text-decoration: none; font-weight: 700; font-size:14px;">Don't have an account? Register</a>
            </div>
        </div>
    </div>
    """)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user = request.form['username'].strip()
        pw = request.form['password'].strip()
        
        if web_users_col.find_one({"username": user}):
            return render_template_string(BASE_CSS + "<h2 style='text-align:center; color:red; margin-top:50px; font-size:24px;'>Username already exists! <a href='/register'>Try again</a></h2>")
        
        uid = "web_" + str(uuid.uuid4())[:8]
        get_user_info(uid) 
        web_users_col.insert_one({"uid": uid, "username": user, "password": pw})
        session['uid'] = uid
        session['username'] = user
        return redirect(url_for('web_home'))
        
    return render_template_string(BASE_CSS + """
    <div class="container fade-in" style="margin-top: 50px;">
        <div class="hero-banner"><div class="logo-text">SK PANEL</div></div>
        <div class="product-card">
            <h2 style="font-size: 24px; margin-bottom: 20px; text-align: center; color: #38bdf8; font-weight: 900;">Register</h2>
            <form method="POST" action="/register">
                <div class="input-group"><label>Username</label><input type="text" name="username" required></div>
                <div class="input-group"><label>Password</label><input type="password" name="password" required></div>
                <button type="submit" class="action-btn btn-primary">Register</button>
            </form>
            <div style="text-align: center; margin-top: 20px;">
                <a href="/login" style="color: #38bdf8; text-decoration: none; font-weight: 700; font-size:14px;">Already have an account? Login</a>
            </div>
        </div>
    </div>
    """)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ================== USER ROUTES ==================
@app.route('/')
def web_home():
    if 'uid' not in session: return redirect(url_for('login'))
    
    uid = session['uid']
    u = get_user_info(uid)
    bal = u.get('balance', 0.0)
    
    products = list(products_col.find({}))
    prod_html = ""
    for p in products:
        prices = p.get('prices', {})
        price_tags = "".join([f"<span class='price-tag'>{d} - ₹{pr}</span>" for d, pr in prices.items()])
            
        prod_html += f"""
        <div class="product-card fade-in">
            <div class="product-title">📦 {p.get('name', 'Unknown')}</div>
            <div class="price-row">{price_tags}</div>
            <a href="/product/{str(p['_id'])}" class="action-btn btn-primary">View & Buy</a>
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <a href="/" class="store-btn">📦 Store</a>
        <div style="display:flex; align-items:center; gap:10px;">
            <div class="wallet-box">₹{bal:.2f}</div>
            <a href="/logout" class="store-btn" style="background:#ef4444;">Logout</a>
        </div>
    </div>
    <div class="container">
        <div class="hero-banner"><div class="logo-text">SK PANEL</div></div>
        <div class="stats-grid">
            <div class="stat-card"><div class="stat-title">💳 Wallet Balance</div><div class="stat-value text-green">₹{bal:.2f}</div></div>
            <div class="stat-card"><div class="stat-title">🔑 Purchased Keys</div><div class="stat-value text-blue">{len(list(orders_col.find({'uid': str(uid), 'type': 'purchase'})))}</div></div>
        </div>
        <a href="/deposit" class="action-btn btn-warning" style="margin-bottom:20px;">⚡ Add Balance</a>
        <div class="product-grid">{prod_html}</div>
    </div>
    """)

@app.route('/product/<p_id>')
def web_product(p_id):
    if 'uid' not in session: return redirect(url_for('login'))
    p = products_col.find_one({"_id": ObjectId(p_id)})
    if not p: return "Product not found", 404
    
    uid = session['uid']
    u = get_user_info(uid)
    discount = u.get('discount', 0)
    
    # Features List
    features_html = ""
    if p.get("features"):
        for f in p["features"].split('\n'):
            if f.strip():
                features_html += f'<div class="feature-item">{f.strip()}</div>'

    # Prices UI
    price_rows = ""
    for d, pr in p.get('prices', {}).items():
        final_price = float(pr) - (float(pr) * discount / 100) if discount > 0 else float(pr)
        price_rows += f"""
        <div class="price-row-ui">
            <div>
                <div class="price-dur">{d}</div>
                <div class="price-amt">₹{final_price:.2f}</div>
            </div>
            <form action="/buy_web" method="POST" style="margin: 0;">
                <input type="hidden" name="p_id" value="{p_id}">
                <input type="hidden" name="duration" value="{d}">
                <button type="submit" class="buy-btn-ui">BUY</button>
            </form>
        </div>
        """

    # Banner Image (Fixed Height)
    banner_html = ""
    if p.get("image") and os.path.exists(p["image"]):
        banner_html = f'<img src="/{p["image"]}" class="gameplay-banner">'

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a><div class="wallet-box">₹{get_balance(uid):.2f}</div></div>
    <div class="container fade-in" style="margin-top:15px;">
        {banner_html}
        <div class="product-page-title">{p.get('name', 'Unknown')}</div>
        
        {features_html}
        
        <div class="check-btns">
            <a href="{p.get('setup_video', '#')}" target="_blank" class="btn-cyan">📥 UPDATE FILE</a>
            <a href="{p.get('hack_video', '#')}" target="_blank" class="btn-red">▶️ VIDEO / FEEDBACK</a>
        </div>

        <div class="purchase-header">PURCHASE KEY</div>
        {price_rows}
    </div>
    """)

@app.route('/buy_web', methods=['POST'])
def buy_web():
    if 'uid' not in session: return redirect(url_for('login'))
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
            <div class="container fade-in" style="margin-top:50px;">
                <div class="product-card" style="text-align:center;">
                    <h2 style="color:#10b981; font-size:28px;">✅ Successful!</h2>
                    <div style="background:#050810; padding:20px; border-radius:15px; border:2px solid #38bdf8; font-family:monospace; font-size:20px; margin:20px 0; font-weight:900; color:#38bdf8;">{key}</div>
                    <a href="/" class="action-btn btn-primary">Back to Store</a>
                </div>
            </div>
            """)
        else:
            credit_balance(uid, price)
            return render_template_string(BASE_CSS + f"""
            <div class="container fade-in" style="margin-top:50px;">
                <div class="product-card" style="text-align:center;">
                    <h2 style="color:#ef4444; font-size:28px;">❌ Out of Stock</h2>
                    <p style="color:#10b981; margin-top:20px; font-weight:900; font-size:18px;">₹{price:.2f} Refunded to Wallet.</p>
                    <br><a href="/" class="action-btn btn-warning">Back to Store</a>
                </div>
            </div>
            """)
    return redirect(url_for('web_home'))

@app.route('/keys')
def web_keys():
    if 'uid' not in session: return redirect(url_for('login'))
    uid = session['uid']
    orders = list(orders_col.find({"uid": str(uid), "type": "purchase"}).sort("_id", -1))
    
    keys_html = ""
    for o in orders:
        keys_html += f"""
        <div class="product-card" style="margin-bottom:15px;">
            <div style="font-size:12px; color:#94a3b8;">{o.get('time', '')}</div>
            <div style="font-weight:900; font-size:16px; margin:5px 0; color:#38bdf8;">📦 {o.get('product', 'Unknown')}</div>
            <div style="background:#050810; padding:12px; border-radius:10px; font-family:monospace; font-size:15px; color:#fff; border:1.5px solid #10b981;">{o.get('key', 'N/A')}</div>
        </div>
        """
    
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/" class="store-btn">🔙 Store</a><div class="wallet-box">₹{get_balance(uid):.2f}</div></div>
    <div class="container fade-in" style="margin-top:20px;">
        <h2 style="text-align:center; color:#38bdf8; font-weight:900; margin-bottom:20px;">🔑 My Keys</h2>
        {keys_html if keys_html else '<p style="text-align:center; color:#94a3b8;">No keys purchased yet.</p>'}
    </div>
    """)

# ================== AUTO-VERIFY DEPOSIT ==================
@app.route('/deposit', methods=['GET', 'POST'])
def web_deposit():
    if 'uid' not in session: return redirect(url_for('login'))
    
    if request.method == 'POST':
        amount = float(request.form['amount'])
        try:
            order = fg.create_order(amount=amount, customer_name=session['uid'])
            
            QR_HTML = BASE_CSS + f"""
            <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a></div>
            <div class="container fade-in" style="margin-top:30px; text-align:center;">
                <div class="product-card" style="padding: 30px 20px;">
                    <h2 style="color:#10b981; font-size:28px; font-weight:900; margin-bottom:10px;">Pay ₹{amount}</h2>
                    <p style="color:#94a3b8; font-size:14px; margin-bottom:20px;">Scan the QR Code below to pay</p>
                    
                    <div id="qr-section">
                        <div style="background:#fff; padding:15px; border-radius:20px; display:inline-block; box-shadow: 0 0 30px rgba(56, 189, 248, 0.4);">
                            <img src="{order.qr_url}" style="width:100%; max-width:220px; display:block;">
                        </div>
                        
                        <div id="loading-section" style="margin-top:25px;">
                            <div style="display:inline-block; width:35px; height:35px; border:4px solid rgba(255,255,255,0.1); border-top:4px solid #38bdf8; border-radius:50%; animation: spin 1s linear infinite;"></div>
                            <h3 style="color:#38bdf8; margin-top:15px; font-weight:700; font-size:16px;">Waiting for Payment...</h3>
                            <p style="color:#94a3b8; font-size:12px;">Auto-verifying. Do not close this page.</p>
                        </div>
                    </div>

                    <div id="success-section" style="display:none; margin-top:25px;">
                        <div style="font-size:50px; margin-bottom:15px;">✅</div>
                        <h2 style="color:#10b981; font-size:24px; font-weight:900;">Payment Successful!</h2>
                        <p style="color:#cbd5e1; font-size:16px; margin-top:10px;">New Balance: <b id="new-balance" style="color:#38bdf8;">₹0.00</b></p>
                        <p style="color:#94a3b8; font-size:12px; margin-top:10px;">Redirecting to store...</p>
                    </div>
                </div>
            </div>
            <script>
                let checkCount = 0;
                const maxChecks = 100; 
                
                function checkPaymentStatus() {{
                    fetch('/check_payment/{order.order_id}/{amount}')
                    .then(response => response.json())
                    .then(data => {{
                        if (data.status === 'success') {{
                            document.getElementById('qr-section').style.display = 'none';
                            document.getElementById('success-section').style.display = 'block';
                            document.getElementById('new-balance').innerText = '₹' + data.new_balance.toFixed(2);
                            setTimeout(() => {{ window.location.href = '/'; }}, 3000);
                        }} else if (data.status === 'expired') {{
                            document.getElementById('loading-section').innerHTML = '<h3 style="color:#ef4444;">QR Expired! Please try again.</h3>';
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
    <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a></div>
    <div class="container fade-in" style="margin-top:20px;">
        <div class="product-card">
            <h2 style="font-size:24px; margin-bottom:20px; color:#38bdf8; text-align:center;">Add Balance</h2>
            <form method="POST" action="/deposit">
                <div class="input-group"><label>Enter Amount (₹)</label><input type="number" name="amount" min="10" required placeholder="100"></div>
                <button type="submit" class="action-btn btn-success">Generate QR</button>
            </form>
        </div>
    </div>
    """)

@app.route('/check_payment/<order_id>/<float:amount>')
def check_payment(order_id, amount):
    if 'uid' not in session: return jsonify({"status": "unauthorized"})
    
    try:
        status = fg.get_status(order_id)
        if status.is_paid:
            uid = session['uid']
            ok, new_bal = credit_atomic(uid, amount, status.utr)
            return jsonify({"status": "success", "new_balance": new_bal})
        elif status.is_expired:
            return jsonify({"status": "expired"})
        else:
            return jsonify({"status": "pending"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ================== ADMIN PANEL (NO LOGIN REQUIRED) ==================
@app.route('/admin', methods=['GET'])
def admin_panel():
    products = list(products_col.find({}))
    prod_html = ""
    for p in products:
        prod_html += f"""
        <div class="product-card" style="margin-bottom:15px; display:flex; justify-content:space-between; align-items:center; padding:15px;">
            <div>
                <div style="font-size:18px; font-weight:900; color:#38bdf8;">{p.get('name', '')}</div>
                <div style="font-size:13px; color:#94a3b8;">PID: {p.get('pid', '')}</div>
            </div>
            <div style="display:flex; gap:10px;">
                <a href="/edit_product/{p['_id']}" class="action-btn btn-warning" style="padding:10px 15px; font-size:13px; width:auto;">✏️ Edit</a>
                <form action="/delete_product/{p['_id']}" method="POST">
                    <button type="submit" class="action-btn btn-danger" style="padding:10px 15px; font-size:13px; width:auto;">🗑️ Del</button>
                </form>
            </div>
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:20px; color:#38bdf8;">⚙️ Controller</div>
        <div style="display:flex; gap:10px;">
            <a href="/admin_users" class="store-btn" style="background:#f59e0b; color:#000;">👥 Users</a>
            <a href="/" class="store-btn" style="background:#ef4444;">Exit</a>
        </div>
    </div>
    <div class="container fade-in" style="margin-top:20px;">
        <div class="product-card" style="margin-bottom:25px; border-color:#0ea5e9;">
            <h3 style="margin-bottom:20px; color:#38bdf8; font-size:20px;">➕ Add New Product</h3>
            <form method="POST" action="/add_product" enctype="multipart/form-data">
                <div class="input-group"><label>Product Name</label><input type="text" name="name" required></div>
                <div class="input-group"><label>PID</label><input type="text" name="pid" required></div>
                
                <div class="input-group"><label>Banner Image (Square/Width size)</label><input type="file" name="image_file" accept="image/*" style="padding:12px; background:#050810; border:2px solid #334155; border-radius:12px;"></div>
                
                <div class="input-group"><label>Features (One per line)</label><textarea name="features" rows="4" placeholder="AIMBOT ADD&#10;AUTO REVIVE"></textarea></div>

                <div class="input-group"><label>Check Update File Link</label><input type="url" name="setup_video" placeholder="https://..."></div>
                <div class="input-group"><label>Check Video/Feedback Link</label><input type="url" name="hack_video" placeholder="https://..."></div>

                <label style="font-weight:900; color:#38bdf8; margin:15px 0 10px 0; display:block;">Durations & Prices</label>
                <div id="price-container">
                    <div style="display:flex; gap:10px; margin-bottom:10px;">
                        <input type="text" name="duration[]" placeholder="1 Hours" style="flex:1; padding:12px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">
                        <input type="number" name="price[]" placeholder="Price" style="flex:1; padding:12px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">
                    </div>
                </div>
                <button type="button" onclick="addPrice()" class="action-btn btn-success" style="margin-bottom:20px; background:#f59e0b; color:#000;">+ Add More</button>
                <button type="submit" class="action-btn btn-primary">Save Product</button>
            </form>
        </div>
        <h3 style="margin-bottom:15px; color:#38bdf8; font-size:20px;">📦 All Products</h3>
        {prod_html}
    </div>
    <script>
        function addPrice() {{
            const c = document.getElementById('price-container');
            const d = document.createElement('div');
            d.style.display = 'flex'; d.style.gap = '10px'; d.style.marginBottom = '10px';
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1; padding:12px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;"><input type="number" name="price[]" placeholder="Price" style="flex:1; padding:12px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">`;
            c.appendChild(d);
        }}
    </script>
    """)

@app.route('/admin_users', methods=['GET', 'POST'])
def admin_users():
    if request.method == 'POST':
        uid = request.form['uid']
        amt = float(request.form.get('amount', 0))
        disc = int(request.form.get('discount', 0))
        users_col.update_one({"_id": uid}, {"$inc": {"balance": amt}, "$set": {"discount": disc}})
        return redirect(url_for('admin_users'))
        
    users = list(users_col.find({}))
    users_html = ""
    for u in users:
        users_html += f"""
        <div class="product-card" style="margin-bottom:15px; padding:15px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                <div>
                    <div style="font-weight:900; color:#38bdf8; font-size:16px;">{u.get('name', 'User')}</div>
                    <div style="font-size:12px; color:#94a3b8;">ID: <code>{u['_id']}</code></div>
                </div>
                <div style="text-align:right;">
                    <div style="font-weight:900; color:#10b981; font-size:16px;">₹{u.get('balance', 0):.2f}</div>
                    <div style="font-size:12px; color:#f59e0b;">Reseller: {u.get('discount', 0)}% OFF</div>
                </div>
            </div>
            <form action="/admin_users" method="POST" style="display:flex; gap:8px;">
                <input type="hidden" name="uid" value="{u['_id']}">
                <input type="number" name="amount" placeholder="+/- Bal" style="flex:1; padding:10px; border-radius:10px; background:#050810; border:1px solid #334155; color:#fff; font-size:13px;">
                <input type="number" name="discount" value="{u.get('discount', 0)}" placeholder="Disc%" style="width:70px; padding:10px; border-radius:10px; background:#050810; border:1px solid #334155; color:#fff; font-size:13px;">
                <button type="submit" class="action-btn btn-success" style="padding:10px 15px; font-size:13px; width:auto;">Update</button>
            </form>
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:20px; color:#38bdf8;">👥 Users</div>
        <a href="/admin" class="store-btn">🔙 Back</a>
    </div>
    <div class="container fade-in" style="margin-top:20px;">
        {users_html}
    </div>
    """)

@app.route('/add_product', methods=['POST'])
def add_product():
    try:
        img_path = None
        if 'image_file' in request.files:
            f = request.files['image_file']
            if f.filename:
                fname = secure_filename(f.filename)
                f.save(os.path.join(UPLOAD_FOLDER, fname))
                img_path = f"static/uploads/{fname}"
        
        durs = request.form.getlist('duration[]')
        prices = request.form.getlist('price[]')
        price_dict = {d.strip(): float(p.strip()) for d, p in zip(durs, prices) if d.strip() and p.strip()}
        
        products_col.insert_one({
            "name": request.form['name'], "pid": request.form['pid'], 
            "features": request.form.get('features', ''),
            "image": img_path,
            "setup_video": request.form.get('setup_video', '#'), 
            "hack_video": request.form.get('hack_video', '#'), 
            "prices": price_dict
        })
        return redirect(url_for('admin_panel'))
    except Exception as e: return f"Error: {e}"

@app.route('/edit_product/<p_id>', methods=['GET', 'POST'])
def edit_product(p_id):
    p = products_col.find_one({"_id": ObjectId(p_id)})
    if not p: return "Product not found"

    if request.method == 'POST':
        try:
            img_path = p.get('image')
            if 'image_file' in request.files:
                f = request.files['image_file']
                if f.filename:
                    fname = secure_filename(f.filename)
                    f.save(os.path.join(UPLOAD_FOLDER, fname))
                    img_path = f"static/uploads/{fname}"
            
            durs = request.form.getlist('duration[]')
            prices = request.form.getlist('price[]')
            price_dict = {d.strip(): float(p.strip()) for d, p in zip(durs, prices) if d.strip() and p.strip()}
            
            products_col.update_one({"_id": ObjectId(p_id)}, {"$set": {
                "name": request.form['name'], "pid": request.form['pid'], 
                "features": request.form.get('features', ''),
                "image": img_path,
                "setup_video": request.form.get('setup_video', '#'), 
                "hack_video": request.form.get('hack_video', '#'), 
                "prices": price_dict
            }})
            return redirect(url_for('admin_panel'))
        except Exception as e: return f"Error: {e}"

    price_fields = ""
    for d, pr in p.get('prices', {}).items():
        price_fields += f"""
        <div style="display:flex; gap:10px; margin-bottom:10px;">
            <input type="text" name="duration[]" value="{d}" style="flex:1; padding:12px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">
            <input type="number" name="price[]" value="{pr}" style="flex:1; padding:12px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <a href="/admin" class="store-btn">🔙 Back</a>
    </div>
    <div class="container fade-in" style="margin-top:20px;">
        <div class="product-card" style="border-color:#f59e0b;">
            <h3 style="margin-bottom:20px; color:#f59e0b; font-size:20px;">✏️ Edit Product</h3>
            <form method="POST" enctype="multipart/form-data">
                <div class="input-group"><label>Product Name</label><input type="text" name="name" value="{p.get('name', '')}" required></div>
                <div class="input-group"><label>PID</label><input type="text" name="pid" value="{p.get('pid', '')}" required></div>
                
                <div class="input-group"><label>Banner Image (Leave empty to keep old)</label><input type="file" name="image_file" accept="image/*" style="padding:12px; background:#050810; border:2px solid #334155; border-radius:12px;"></div>
                
                <div class="input-group"><label>Features</label><textarea name="features" rows="4">{p.get('features', '')}</textarea></div>
                <div class="input-group"><label>Update Link</label><input type="url" name="setup_video" value="{p.get('setup_video', '#')}"></div>
                <div class="input-group"><label>Video/Feedback Link</label><input type="url" name="hack_video" value="{p.get('hack_video', '#')}"></div>

                <label style="font-weight:900; color:#38bdf8; margin:15px 0 10px 0; display:block;">Durations & Prices</label>
                <div id="price-container">
                    {price_fields}
                </div>
                <button type="button" onclick="addPrice()" class="action-btn btn-success" style="margin-bottom:20px; background:#f59e0b; color:#000;">+ Add More</button>
                <button type="submit" class="action-btn btn-warning">Update Product</button>
            </form>
        </div>
    </div>
    <script>
        function addPrice() {{
            const c = document.getElementById('price-container');
            const d = document.createElement('div');
            d.style.display = 'flex'; d.style.gap = '10px'; d.style.marginBottom = '10px';
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1; padding:12px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;"><input type="number" name="price[]" placeholder="Price" style="flex:1; padding:12px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">`;
            c.appendChild(d);
        }}
    </script>
    """)

@app.route('/delete_product/<p_id>', methods=['POST'])
def delete_product(p_id):
    products_col.delete_one({"_id": ObjectId(p_id)})
    return redirect(url_for('admin_panel'))

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
