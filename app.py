import os
import time
import threading
import requests
import urllib.parse
import telebot
import uuid
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
web_users_col = db.web_users 
products_col = db.products
orders_col = db.orders
settings_col = db.settings

# Create Admin Web User automatically if not exists
if not web_users_col.find_one({"username": "admin"}):
    web_users_col.insert_one({"uid": str(ADMIN_ID), "username": "admin", "password": "admin123"})
    users_col.insert_one({"_id": str(ADMIN_ID), "balance": 0.0, "name": "Admin", "discount": 0})

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

# ================== FLASK WEB APP ==================
app = Flask(__name__)
app.secret_key = "sk_panel_secret"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# -------- HD CSS (Bada aur Clean) --------
BASE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800;900&display=swap');
    * { box-sizing: border-box; font-family: 'Poppins', sans-serif; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body { background-color: #050810; color: #fff; padding-bottom: 100px; background-image: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #050810 70%); background-attachment: fixed; min-height: 100vh; animation: bodyFadeIn 0.8s ease-out; }
    @keyframes bodyFadeIn { from { opacity: 0; } to { opacity: 1; } }
    
    /* Bada Container */
    .container { padding: 25px; max-width: 950px; margin: 0 auto; animation: slideUp 0.5s ease-out; }
    @keyframes slideUp { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
    
    /* Top Navbar */
    .top-nav { display: flex; justify-content: space-between; align-items: center; padding: 20px 25px; background: rgba(15, 23, 42, 0.9); backdrop-filter: blur(15px); position: sticky; top: 0; z-index: 100; border-bottom: 1px solid rgba(255,255,255,0.1); }
    .store-btn { background: linear-gradient(135deg, #0ea5e9, #2563eb); padding: 15px 30px; border-radius: 25px; font-weight: 800; font-size: 18px; color: white; text-decoration: none; box-shadow: 0 4px 15px rgba(14, 165, 233, 0.4); }
    .wallet-box { background: rgba(16, 185, 129, 0.15); border: 2px solid #10b981; padding: 12px 25px; border-radius: 25px; font-weight: 900; color: #10b981; font-size: 20px; }
    
    /* Hero Banner */
    .hero-banner { width: 100%; padding: 50px 20px; background: linear-gradient(145deg, #1e1b4b, #0f172a); border-radius: 25px; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; margin-bottom: 35px; border: 2px solid #6366f1; box-shadow: inset 0 0 30px rgba(99, 102, 241, 0.2), 0 10px 40px rgba(0, 0, 0, 0.6); }
    .logo-text { font-size: 50px; font-weight: 900; background: linear-gradient(to right, #fbbf24, #f59e0b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; text-shadow: 0 0 30px rgba(245, 158, 11, 0.5); }
    
    /* Stats Grid */
    .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px; }
    .stat-card { background: linear-gradient(145deg, #0f172a, #1e293b); border-radius: 20px; padding: 30px; border: 1px solid rgba(255,255,255,0.08); }
    .stat-title { font-size: 16px; color: #94a3b8; font-weight: 700; margin-bottom: 10px; text-transform: uppercase; }
    .stat-value { font-size: 36px; font-weight: 900; }

    /* Products */
    .product-grid { display: grid; grid-template-columns: 1fr; gap: 25px; }
    .product-card { background: linear-gradient(145deg, #0f172a, #050810); border-radius: 25px; padding: 35px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 15px 35px rgba(0,0,0,0.5); }
    .product-title { font-size: 30px; font-weight: 900; color: #fff; margin-bottom: 20px; }
    .price-row { display: flex; flex-wrap: wrap; gap: 15px; margin-bottom: 30px; }
    .price-tag { background: rgba(56, 189, 248, 0.15); color: #38bdf8; padding: 15px 25px; border-radius: 12px; font-size: 20px; font-weight: 800; border: 1px solid rgba(56,189,248,0.4); }

    /* Buttons & Inputs (Bade) */
    .action-btn { display: block; width: 100%; padding: 25px; border-radius: 20px; text-align: center; font-weight: 900; font-size: 22px; text-decoration: none; border: none; cursor: pointer; text-transform: uppercase; letter-spacing: 1px; }
    .btn-primary { background: linear-gradient(135deg, #0ea5e9, #3b82f6); color: white; box-shadow: 0 8px 25px rgba(14, 165, 233, 0.4); }
    .btn-success { background: linear-gradient(135deg, #10b981, #059669); color: white; box-shadow: 0 8px 25px rgba(16, 185, 129, 0.4); }
    .btn-danger { background: linear-gradient(135deg, #ef4444, #b91c1c); color: white; box-shadow: 0 8px 25px rgba(239, 68, 68, 0.4); }
    .btn-warning { background: linear-gradient(135deg, #f59e0b, #d97706); color: black; box-shadow: 0 8px 25px rgba(245, 158, 11, 0.4); }

    .input-group { margin-bottom: 25px; }
    .input-group label { display: block; font-size: 20px; color: #cbd5e1; margin-bottom: 12px; font-weight: 700; }
    .input-group input, .input-group textarea { width: 100%; padding: 25px; border-radius: 20px; border: 2px solid #334155; background: #0f172a; color: #fff; font-size: 20px; outline: none; font-weight: 600; }
    .input-group input:focus { border-color: #38bdf8; box-shadow: 0 0 20px rgba(56, 189, 248, 0.3); }
    
    /* Video Player */
    .gameplay-container { margin-bottom: 20px; border-radius: 15px; overflow: hidden; border: 2px solid #0ea5e9; box-shadow: 0 5px 20px rgba(14, 165, 233, 0.3); }
    .gameplay-container video { width: 100%; display: block; background: #000; }
</style>
"""

# ================== AUTH ROUTES ==================
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
                    <h2 style="color:#ef4444; margin-bottom:20px; font-size:30px;">❌ Invalid Login</h2>
                    <a href="/login" class="action-btn btn-primary">Try Again</a>
                </div>
            </div>
            """)
    
    if 'uid' in session: return redirect(url_for('web_home'))
    return render_template_string(BASE_CSS + """
    <div class="container fade-in" style="margin-top: 60px;">
        <div class="hero-banner"><div class="logo-text">SK PANEL</div></div>
        <div class="product-card">
            <h2 style="font-size: 32px; margin-bottom: 30px; text-align: center; color: #38bdf8; font-weight: 900;">Login</h2>
            <form method="POST" action="/login">
                <div class="input-group"><label>Username</label><input type="text" name="username" required></div>
                <div class="input-group"><label>Password</label><input type="password" name="password" required></div>
                <button type="submit" class="action-btn btn-success">Login</button>
            </form>
            <div style="text-align: center; margin-top: 25px;">
                <a href="/register" style="color: #38bdf8; text-decoration: none; font-weight: 700; font-size:18px;">Don't have an account? Register</a>
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
            return render_template_string(BASE_CSS + "<h2 style='text-align:center; color:red; margin-top:50px; font-size:30px;'>Username already exists! <a href='/register'>Try again</a></h2>")
        
        uid = "web_" + str(uuid.uuid4())[:8]
        get_user_info(uid) 
        web_users_col.insert_one({"uid": uid, "username": user, "password": pw})
        session['uid'] = uid
        session['username'] = user
        return redirect(url_for('web_home'))
        
    return render_template_string(BASE_CSS + """
    <div class="container fade-in" style="margin-top: 60px;">
        <div class="hero-banner"><div class="logo-text">SK PANEL</div></div>
        <div class="product-card">
            <h2 style="font-size: 32px; margin-bottom: 30px; text-align: center; color: #38bdf8; font-weight: 900;">Register</h2>
            <form method="POST" action="/register">
                <div class="input-group"><label>Username</label><input type="text" name="username" required></div>
                <div class="input-group"><label>Password</label><input type="password" name="password" required></div>
                <button type="submit" class="action-btn btn-primary">Register</button>
            </form>
            <div style="text-align: center; margin-top: 25px;">
                <a href="/login" style="color: #38bdf8; text-decoration: none; font-weight: 700; font-size:18px;">Already have an account? Login</a>
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
    discount = u.get('discount', 0)
    
    products = list(products_col.find({}))
    prod_html = ""
    for p in products:
        prices = p.get('prices', {})
        price_tags = "".join([f"<span class='price-tag'>{d} - ₹{pr}</span>" for d, pr in prices.items()])
        
        gameplay_html = ""
        if p.get("gameplay_video"):
            gameplay_html = f'<div class="gameplay-container"><video src="/{p["gameplay_video"]}" controls autoplay muted loop></video></div>'
            
        prod_html += f"""
        <div class="product-card fade-in">
            <div class="product-title">📦 {p.get('name', 'Unknown')}</div>
            {gameplay_html}
            <div class="price-row">{price_tags}</div>
            <a href="/product/{str(p['_id'])}" class="action-btn btn-primary">View & Buy</a>
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <a href="/" class="store-btn">📦 Store</a>
        <div style="display:flex; align-items:center; gap:20px;">
            <div class="wallet-box">₹{bal:.2f}</div>
            <a href="/logout" class="store-btn" style="background:#ef4444;">Logout</a>
        </div>
    </div>
    <div class="container">
        <div class="hero-banner"><div class="logo-text">SK PANEL</div></div>
        <div class="stats-grid">
            <div class="stat-card"><div class="stat-title">💳 Wallet</div><div class="stat-value text-green">₹{bal:.2f}</div></div>
            <div class="stat-card"><div class="stat-title">🔑 Keys</div><div class="stat-value text-blue">{len(list(orders_col.find({'uid': str(uid)})))}</div></div>
        </div>
        <a href="/deposit" class="action-btn btn-warning" style="margin-bottom:40px;">⚡ Add Balance</a>
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
    
    price_tags = ""
    for d, pr in p.get('prices', {}).items():
        final_price = float(pr) - (float(pr) * discount / 100) if discount > 0 else float(pr)
        price_tags += f"""
        <form action="/buy_web" method="POST" style="margin-bottom:20px;">
            <input type="hidden" name="p_id" value="{p_id}">
            <input type="hidden" name="duration" value="{d}">
            <button type="submit" class="action-btn btn-primary" style="display:flex; justify-content:space-between;">
                <span>⏱ {d}</span><span>₹{final_price:.2f}</span>
            </button>
        </form>
        """

    video_html = ""
    if p.get("gameplay_video"): video_html += f'<div class="gameplay-container"><video src="/{p["gameplay_video"]}" controls></video></div>'
    if p.get("setup_video"): video_html += f'<div class="gameplay-container" style="border-color:#38bdf8;"><video src="/{p["setup_video"]}" controls></video></div>'
    if p.get("hack_video"): video_html += f'<div class="gameplay-container" style="border-color:#ef4444;"><video src="/{p["hack_video"]}" controls></video></div>'

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a><div class="wallet-box">₹{get_balance(uid):.2f}</div></div>
    <div class="container fade-in" style="margin-top:30px;">
        <div class="product-card">
            <div class="product-title" style="font-size:36px; color:#38bdf8;">📦 {p.get('name', 'Unknown')}</div>
            <p style="color:#cbd5e1; font-size:18px; margin-bottom:30px;">{p.get('description', '')}</p>
            {video_html}
            <div style="font-size:24px; font-weight:900; margin:40px 0 25px 0;">Select Duration:</div>
            {price_tags}
        </div>
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
            <div class="container fade-in" style="margin-top:60px;">
                <div class="product-card" style="text-align:center;">
                    <h2 style="color:#10b981; font-size:36px;">✅ Successful!</h2>
                    <div style="background:#050810; padding:30px; border-radius:20px; border:2px solid #38bdf8; font-family:monospace; font-size:28px; margin:30px 0; font-weight:900; color:#38bdf8;">{key}</div>
                    <a href="/" class="action-btn btn-primary">Back</a>
                </div>
            </div>
            """)
        else:
            credit_balance(uid, price)
            return render_template_string(BASE_CSS + f"""
            <div class="container fade-in" style="margin-top:60px;">
                <div class="product-card" style="text-align:center;">
                    <h2 style="color:#ef4444; font-size:36px;">❌ Out of Stock</h2>
                    <p style="color:#10b981; margin-top:25px; font-weight:900; font-size:22px;">₹{price:.2f} Refunded to Wallet.</p>
                    <br><a href="/" class="action-btn btn-warning">Back</a>
                </div>
            </div>
            """)
    return redirect(url_for('web_home'))

@app.route('/deposit', methods=['GET', 'POST'])
def web_deposit():
    if 'uid' not in session: return redirect(url_for('login'))
    
    if request.method == 'POST':
        amount = float(request.form['amount'])
        try:
            order = fg.create_order(amount=amount, customer_name=session['uid'])
            return render_template_string(BASE_CSS + f"""
            <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a></div>
            <div class="container fade-in" style="margin-top:40px; text-align:center;">
                <div class="product-card">
                    <h2 style="color:#10b981; font-size:32px;">Pay ₹{amount}</h2>
                    <img src="{order.qr_url}" style="width:100%; max-width:350px; border-radius:20px; border:2px solid #38bdf8; margin:30px 0;">
                    <a href="/" class="action-btn btn-primary">I have paid</a>
                </div>
            </div>
            """)
        except Exception as e: return f"Error: {e}"

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a></div>
    <div class="container fade-in" style="margin-top:30px;">
        <div class="product-card">
            <h2 style="font-size:32px; margin-bottom:30px; color:#38bdf8; text-align:center;">Add Balance</h2>
            <form method="POST" action="/deposit">
                <div class="input-group"><label>Enter Amount (₹)</label><input type="number" name="amount" min="10" required placeholder="100"></div>
                <button type="submit" class="action-btn btn-success">Generate QR</button>
            </form>
        </div>
    </div>
    """)

# ================== ADMIN PANEL (Dedicated Login & Edit Feature) ==================
@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    # If not logged in as Admin, show clean login page without 'Access Denied'
    if 'uid' not in session or str(session['uid']) != str(ADMIN_ID):
        if request.method == 'POST':
            user = request.form['username']
            pw = request.form['password']
            if user == "admin" and pw == "admin123":
                session['uid'] = str(ADMIN_ID)
                session['username'] = 'admin'
                return redirect(url_for('admin_panel'))
            else:
                return "<h2 style='text-align:center; color:red; margin-top:50px; font-size:30px;'>❌ Invalid Admin Credentials</h2>"
                
        return render_template_string(BASE_CSS + """
        <div class="container fade-in" style="margin-top: 60px;">
            <div class="hero-banner"><div class="logo-text">CONTROLLER</div></div>
            <div class="product-card">
                <h2 style="font-size: 32px; margin-bottom: 30px; text-align: center; color: #38bdf8; font-weight: 900;">Admin Login</h2>
                <form method="POST" action="/admin">
                    <div class="input-group"><label>Username</label><input type="text" name="username" required></div>
                    <div class="input-group"><label>Password</label><input type="password" name="password" required></div>
                    <button type="submit" class="action-btn btn-primary">Login to Panel</button>
                </form>
            </div>
        </div>
        """)
    
    products = list(products_col.find({}))
    prod_html = ""
    for p in products:
        prod_html += f"""
        <div class="product-card" style="margin-bottom:25px; display:flex; justify-content:space-between; align-items:center; padding:25px;">
            <div>
                <div style="font-size:24px; font-weight:900; color:#38bdf8;">{p.get('name', '')}</div>
                <div style="font-size:16px; color:#94a3b8;">PID: {p.get('pid', '')}</div>
            </div>
            <div style="display:flex; gap:15px;">
                <a href="/edit_product/{p['_id']}" class="action-btn btn-warning" style="padding:15px 25px; font-size:16px; width:auto;">✏️ Edit</a>
                <form action="/delete_product/{p['_id']}" method="POST">
                    <button type="submit" class="action-btn btn-danger" style="padding:15px 25px; font-size:16px; width:auto;">🗑️ Del</button>
                </form>
            </div>
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:26px; color:#38bdf8;">⚙️ Controller</div>
        <a href="/" class="store-btn" style="background:#ef4444;">Exit</a>
    </div>
    <div class="container fade-in" style="margin-top:30px;">
        <div class="product-card" style="margin-bottom:40px; border-color:#0ea5e9;">
            <h3 style="margin-bottom:30px; color:#38bdf8; font-size:28px;">➕ Add New Product</h3>
            <form method="POST" action="/add_product" enctype="multipart/form-data">
                <div class="input-group"><label>Product Name</label><input type="text" name="name" required></div>
                <div class="input-group"><label>PID</label><input type="text" name="pid" required></div>
                
                <div class="input-group"><label>🎮 Gameplay Video</label><input type="file" name="gameplay_video_file" accept="video/*" style="padding:25px; background:#050810; border:2px solid #334155; border-radius:20px;"></div>
                <div class="input-group"><label>Setup Video</label><input type="file" name="setup_video_file" accept="video/*" style="padding:25px; background:#050810; border:2px solid #334155; border-radius:20px;"></div>
                <div class="input-group"><label>Hack Video</label><input type="file" name="hack_video_file" accept="video/*" style="padding:25px; background:#050810; border:2px solid #334155; border-radius:20px;"></div>

                <label style="font-weight:900; color:#38bdf8; margin:25px 0 15px 0; display:block; font-size:20px;">Durations & Prices</label>
                <div id="price-container">
                    <div style="display:flex; gap:15px; margin-bottom:15px;">
                        <input type="text" name="duration[]" placeholder="1 Day" style="flex:1; padding:25px; border-radius:20px; background:#050810; border:2px solid #334155; color:#fff; font-size:20px;">
                        <input type="number" name="price[]" placeholder="Price" style="flex:1; padding:25px; border-radius:20px; background:#050810; border:2px solid #334155; color:#fff; font-size:20px;">
                    </div>
                </div>
                <button type="button" onclick="addPrice()" class="action-btn btn-success" style="margin-bottom:30px; background:#f59e0b; color:#000;">+ Add More</button>
                <button type="submit" class="action-btn btn-primary">Save Product</button>
            </form>
        </div>
        <h3 style="margin-bottom:25px; color:#38bdf8; font-size:28px;">📦 All Products</h3>
        {prod_html}
    </div>
    <script>
        function addPrice() {{
            const c = document.getElementById('price-container');
            const d = document.createElement('div');
            d.style.display = 'flex'; d.style.gap = '15px'; d.style.marginBottom = '15px';
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1; padding:25px; border-radius:20px; background:#050810; border:2px solid #334155; color:#fff; font-size:20px;"><input type="number" name="price[]" placeholder="Price" style="flex:1; padding:25px; border-radius:20px; background:#050810; border:2px solid #334155; color:#fff; font-size:20px;">`;
            c.appendChild(d);
        }}
    </script>
    """)

@app.route('/add_product', methods=['POST'])
def add_product():
    if 'uid' not in session or str(session['uid']) != str(ADMIN_ID): return "Access Denied", 403
    try:
        gameplay_video_path = None
        setup_video_path = None
        hack_video_path = None
        
        if 'gameplay_video_file' in request.files:
            f = request.files['gameplay_video_file']
            if f.filename:
                fname = secure_filename(f.filename)
                f.save(os.path.join(UPLOAD_FOLDER, fname))
                gameplay_video_path = f"static/uploads/{fname}"

        if 'setup_video_file' in request.files:
            f = request.files['setup_video_file']
            if f.filename:
                fname = secure_filename(f.filename)
                f.save(os.path.join(UPLOAD_FOLDER, fname))
                setup_video_path = f"static/uploads/{fname}"
                
        if 'hack_video_file' in request.files:
            f = request.files['hack_video_file']
            if f.filename:
                fname = secure_filename(f.filename)
                f.save(os.path.join(UPLOAD_FOLDER, fname))
                hack_video_path = f"static/uploads/{fname}"
        
        durs = request.form.getlist('duration[]')
        prices = request.form.getlist('price[]')
        price_dict = {d.strip(): float(p.strip()) for d, p in zip(durs, prices) if d.strip() and p.strip()}
        
        products_col.insert_one({
            "name": request.form['name'], "pid": request.form['pid'], "features": request.form.get('features', ''),
            "gameplay_video": gameplay_video_path,
            "setup_video": setup_video_path, "hack_video": hack_video_path, "prices": price_dict
        })
        return redirect(url_for('admin_panel'))
    except Exception as e: return f"Error: {e}"

@app.route('/edit_product/<p_id>', methods=['GET', 'POST'])
def edit_product(p_id):
    if 'uid' not in session or str(session['uid']) != str(ADMIN_ID): return "Access Denied", 403
    
    p = products_col.find_one({"_id": ObjectId(p_id)})
    if not p: return "Product not found"

    if request.method == 'POST':
        try:
            gameplay_video_path = p.get('gameplay_video')
            setup_video_path = p.get('setup_video')
            hack_video_path = p.get('hack_video')
            
            if 'gameplay_video_file' in request.files:
                f = request.files['gameplay_video_file']
                if f.filename:
                    fname = secure_filename(f.filename)
                    f.save(os.path.join(UPLOAD_FOLDER, fname))
                    gameplay_video_path = f"static/uploads/{fname}"

            if 'setup_video_file' in request.files:
                f = request.files['setup_video_file']
                if f.filename:
                    fname = secure_filename(f.filename)
                    f.save(os.path.join(UPLOAD_FOLDER, fname))
                    setup_video_path = f"static/uploads/{fname}"
                    
            if 'hack_video_file' in request.files:
                f = request.files['hack_video_file']
                if f.filename:
                    fname = secure_filename(f.filename)
                    f.save(os.path.join(UPLOAD_FOLDER, fname))
                    hack_video_path = f"static/uploads/{fname}"
            
            durs = request.form.getlist('duration[]')
            prices = request.form.getlist('price[]')
            price_dict = {d.strip(): float(p.strip()) for d, p in zip(durs, prices) if d.strip() and p.strip()}
            
            products_col.update_one({"_id": ObjectId(p_id)}, {"$set": {
                "name": request.form['name'], "pid": request.form['pid'], "features": request.form.get('features', ''),
                "gameplay_video": gameplay_video_path,
                "setup_video": setup_video_path, "hack_video": hack_video_path, "prices": price_dict
            }})
            return redirect(url_for('admin_panel'))
        except Exception as e: return f"Error: {e}"

    price_fields = ""
    for d, pr in p.get('prices', {}).items():
        price_fields += f"""
        <div style="display:flex; gap:15px; margin-bottom:15px;">
            <input type="text" name="duration[]" value="{d}" style="flex:1; padding:25px; border-radius:20px; background:#050810; border:2px solid #334155; color:#fff; font-size:20px;">
            <input type="number" name="price[]" value="{pr}" style="flex:1; padding:25px; border-radius:20px; background:#050810; border:2px solid #334155; color:#fff; font-size:20px;">
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <a href="/admin" class="store-btn">🔙 Back to Admin</a>
    </div>
    <div class="container fade-in" style="margin-top:30px;">
        <div class="product-card" style="border-color:#f59e0b;">
            <h3 style="margin-bottom:30px; color:#f59e0b; font-size:28px;">✏️ Edit Product</h3>
            <form method="POST" enctype="multipart/form-data">
                <div class="input-group"><label>Product Name</label><input type="text" name="name" value="{p.get('name', '')}" required></div>
                <div class="input-group"><label>PID</label><input type="text" name="pid" value="{p.get('pid', '')}" required></div>
                
                <div class="input-group">
                    <label>🎮 Gameplay Video (Leave empty to keep old)</label>
                    <input type="file" name="gameplay_video_file" accept="video/*" style="padding:25px; background:#050810; border:2px solid #334155; border-radius:20px;">
                </div>
                <div class="input-group">
                    <label>Setup Video (Leave empty to keep old)</label>
                    <input type="file" name="setup_video_file" accept="video/*" style="padding:25px; background:#050810; border:2px solid #334155; border-radius:20px;">
                </div>
                <div class="input-group">
                    <label>Hack Video (Leave empty to keep old)</label>
                    <input type="file" name="hack_video_file" accept="video/*" style="padding:25px; background:#050810; border:2px solid #334155; border-radius:20px;">
                </div>

                <label style="font-weight:900; color:#38bdf8; margin:25px 0 15px 0; display:block; font-size:20px;">Durations & Prices</label>
                <div id="price-container">
                    {price_fields}
                </div>
                <button type="button" onclick="addPrice()" class="action-btn btn-success" style="margin-bottom:30px; background:#f59e0b; color:#000;">+ Add More</button>
                <button type="submit" class="action-btn btn-warning">Update Product</button>
            </form>
        </div>
    </div>
    <script>
        function addPrice() {{
            const c = document.getElementById('price-container');
            const d = document.createElement('div');
            d.style.display = 'flex'; d.style.gap = '15px'; d.style.marginBottom = '15px';
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1; padding:25px; border-radius:20px; background:#050810; border:2px solid #334155; color:#fff; font-size:20px;"><input type="number" name="price[]" placeholder="Price" style="flex:1; padding:25px; border-radius:20px; background:#050810; border:2px solid #334155; color:#fff; font-size:20px;">`;
            c.appendChild(d);
        }}
    </script>
    """)

@app.route('/delete_product/<p_id>', methods=['POST'])
def delete_product(p_id):
    if 'uid' not in session or str(session['uid']) != str(ADMIN_ID): return "Access Denied", 403
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
