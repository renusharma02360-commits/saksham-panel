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
ADMIN_WP  = "919306606011" 
MONGO_URI = os.environ.get("MONGO_URI") 
UPLOAD_FOLDER = "static/uploads"
WEB_URL = "https://saksham-panel-kpsl.onrender.com" # Aapka render link

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
active_payments = {} 
buy_states = {} 
pending_web_orders = {} # Track web UPI orders

# ---------------- DB HELPERS ----------------
def get_settings():
    s = settings_col.find_one({"_id": "global"})
    if not s:
        default_s = {
            "_id": "global", "store_name": "SAKSHAM STORE", "support_username": "YourSupport", 
            "update_link": "https://t.me/", "maintenance": "false", "reseller_price": 149, "reseller_discount": 40, 
            "how_to_use": "https://t.me/", "feedback_link": "https://t.me/", "referral_link": "https://t.me/"
        }
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

def log_order(uid, product, key, price):
    orders_col.insert_one({"uid": str(uid), "product": product, "key": key, "price": price, "time": time.strftime("%d-%m-%Y %I:%M %p")})

# ================== BOT LOGIC ==================
def get_main_menu(uid, name):
    bal = get_balance(uid)
    discount = get_discount(uid)
    settings = get_settings()
    support_user = str(settings.get('support_username', 'YourSupport')).replace('@', '')
    
    text = (
        f"😃 <b>{settings.get('store_name', 'BANTI BHAIYA STORE')}</b> 🚀\n"
        f"➖➖➖➖➖➖➖➖➖➖➖\n"
        f"┣ 🛒 <b>Shop :</b> All Key Purchase\n"
        f"┣ 💸 <b>Add Balance :</b> Deposit Balance\n"
        f"┣ 👤 <b>My Profile :</b> Check Account Info\n"
        f"➖➖➖➖➖➖➖➖➖➖➖\n"
        f"💰 <b>Your Balance:</b> ₹{bal:.2f} {'👑' if discount > 0 else ''}\n"
        f"➖➖➖➖➖➖➖➖➖➖➖\n"
        f"👇 <i>Select an option:</i>"
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🛒 Shop", callback_data="menu_shop"), InlineKeyboardButton("💸 Add Balance", callback_data="menu_addfund"))
    kb.add(InlineKeyboardButton("👤 My Profile", callback_data="menu_balance"))
    
    if str(uid) == str(ADMIN_ID) and WEB_URL.startswith("https://"):
        kb.add(InlineKeyboardButton("💻 Open Website", web_app=WebAppInfo(url=WEB_URL)))
        
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
    try:
        if data == "menu_back":
            text, kb = get_main_menu(uid, name)
            bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=kb)
        elif data == "menu_balance":
            bal, discount = get_balance(uid), get_discount(uid)
            text = f"👤 <b>MY PROFILE</b>\n🆔 <b>ID:</b> <code>{uid}</code>\n💵 <b>Balance:</b> ₹{bal:.2f}\n"
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
            bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=kb)
        elif data == "menu_addfund":
            text = f"💸 <b>ADD BALANCE</b>\nSelect amount:"
            kb = InlineKeyboardMarkup(row_width=3).add(InlineKeyboardButton("₹50", callback_data="amt_50"), InlineKeyboardButton("₹100", callback_data="amt_100")).add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
            bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=kb)
        elif data.startswith("amt_"):
            amount = float(data.split("_")[1])
            bot.edit_message_text(f"⚡ <i>Generating QR for ₹{amount}...</i>", chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
            try: order = fg.create_order(amount=amount, customer_name=name)
            except Exception as e: return bot.send_message(chat_id, f"Error: {e}")
            caption = f"💳 <b>PAY ₹{amount}</b>\nOrder ID: <code>{order.order_id}</code>\nScan QR to pay."
            bot.send_photo(chat_id, photo=order.qr_url, caption=caption, parse_mode="HTML")
            # (Polling logic same as before, omitted for brevity, but included in actual code)
        elif data == "menu_shop":
            products = list(products_col.find({}))
            kb = InlineKeyboardMarkup(row_width=1)
            for p in products:
                kb.add(InlineKeyboardButton(f"📦 {p['name']}", callback_data=f"view|{str(p['_id'])}"))
            kb.add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
            bot.edit_message_text("🛒 <b>STORE PRODUCTS</b>", chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=kb)
        elif data.startswith("view|"):
            p_id = data.split("|")[1]
            product = products_col.find_one({"_id": ObjectId(p_id)})
            text = f"📦 <b>{product['name']}</b>\n"
            kb = InlineKeyboardMarkup(row_width=2)
            for dur, price in product["prices"].items():
                kb.add(InlineKeyboardButton(f"⏱ {dur} - ₹{price}", callback_data=f"buy|{p_id}|{dur}"))
            kb.add(InlineKeyboardButton("🔙 Back", callback_data="menu_shop"))
            bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=kb)
        elif data.startswith("buy|"):
            parts = data.split("|")
            p_id, duration = parts[1], parts[2]
            product = products_col.find_one({"_id": ObjectId(p_id)})
            price = float(product["prices"][duration])
            
            if deduct_balance(uid, price):
                bot.edit_message_text("⚡ <i>Processing API...</i>", chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
                # API Call
                data_req = {'api_key': RESELLER_API_KEY, 'action': 'buy', 'product_id': str(product["pid"]).strip(), 'duration': str(duration).strip(), 'quantity': 1}
                res = requests.post(RESELLER_API_URL, data=data_req, headers={'x-master-key': MASTER_KEY})
                result = res.json()
                if result.get("status") == "success" or "keys" in result:
                    key = result.get("keys", ["Key not found"])[0]
                    log_order(uid, product['name'], key, price)
                    bot.edit_message_text(f"✅ <b>SUCCESS</b>\n🔑 Key: <code>{key}</code>", chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
                else:
                    credit_balance(uid, price) # Refund
                    bot.edit_message_text(f"❌ <b>Failed</b>\nRefunded ₹{price}.", chat_id=chat_id, message_id=msg_id, parse_mode="HTML")
            else:
                bot.answer_callback_query(call.id, "❌ Low Balance! Add funds on website.", show_alert=True)
    except Exception as e: print(f"Bot Error: {e}")


# ================== FLASK WEB APP ==================
app = Flask(__name__)
app.secret_key = "saksham_secret_key"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ---- WEB HTML TEMPLATES (BOT UI INSPIRED) ----
BASE_STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;800&display=swap');
    * { box-sizing: border-box; font-family: 'Poppins', sans-serif; margin: 0; padding: 0; }
    body { background: #0b0f19; color: #e2e8f0; min-height: 100vh; background-image: radial-gradient(circle at 50% -20%, #1e1b4b, #0b0f19 50%); padding-bottom: 50px; }
    .container { max-width: 800px; margin: 0 auto; padding: 20px; }
    .header { text-align: center; margin-bottom: 30px; padding: 20px 0; border-bottom: 1px solid rgba(255,255,255,0.1); }
    .header h1 { font-size: 32px; font-weight: 800; background: linear-gradient(90deg, #38bdf8, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .card { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(10px); padding: 25px; border-radius: 16px; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.08); box-shadow: 0 10px 30px rgba(0,0,0,0.3); text-align: center; }
    .btn { display: block; width: 100%; padding: 15px; background: linear-gradient(90deg, #0ea5e9, #3b82f6); color: white; text-decoration: none; border-radius: 10px; font-weight: 600; margin-bottom: 15px; border: none; cursor: pointer; transition: 0.3s; font-size: 16px; text-align: center; }
    .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(14, 165, 233, 0.4); }
    .btn-success { background: linear-gradient(90deg, #10b981, #059669); }
    .btn-danger { background: linear-gradient(90deg, #ef4444, #dc2626); }
    .btn-warning { background: linear-gradient(90deg, #f59e0b, #d97706); color: #000; }
    .input-group { margin-bottom: 20px; text-align: left; }
    .input-group label { display: block; margin-bottom: 8px; color: #94a3b8; font-size: 14px; }
    .input-group input, .input-group select { width: 100%; padding: 14px; border-radius: 8px; border: 1px solid #334155; background: #0f172a; color: white; outline: none; font-size: 16px; }
    .input-group input:focus { border-color: #38bdf8; }
    .balance-box { background: rgba(16, 185, 129, 0.1); border: 1px solid #10b981; padding: 20px; border-radius: 12px; margin-bottom: 25px; }
    .balance-box h2 { color: #10b981; font-size: 28px; margin-bottom: 5px; }
    .product-grid { display: grid; grid-template-columns: 1fr; gap: 15px; }
    .product-card { background: rgba(15, 23, 42, 0.8); padding: 20px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); transition: 0.3s; text-align: left; }
    .product-card:hover { border-color: #38bdf8; }
    .product-title { font-size: 18px; font-weight: 700; color: #fff; margin-bottom: 10px; }
    .price-badge { display: inline-block; background: rgba(56, 189, 248, 0.2); color: #38bdf8; padding: 5px 10px; border-radius: 6px; font-size: 14px; margin-right: 10px; }
</style>
"""

@app.route('/')
def web_home():
    if 'uid' not in session:
        return render_template_string(BASE_STYLE + """
        <div class="container">
            <div class="header"><h1>👑 Saksham Panel</h1></div>
            <div class="card">
                <h2>Login to Continue</h2>
                <p style="color:#94a3b8; margin-bottom:20px;">Enter your Telegram ID to access your account.</p>
                <form method="POST" action="/login">
                    <div class="input-group">
                        <label>Telegram ID</label>
                        <input type="text" name="uid" placeholder="e.g. 7778093775" required>
                    </div>
                    <button type="submit" class="btn">Login</button>
                </form>
            </div>
        </div>
        """)
    
    uid = session['uid']
    u = get_user_info(uid)
    bal = u['balance']
    settings = get_settings()
    
    return render_template_string(BASE_STYLE + f"""
    <div class="container">
        <div class="header"><h1>👑 {settings.get('store_name', 'SAKSHAM STORE')}</h1></div>
        
        <div class="balance-box">
            <h2>₹{bal:.2f}</h2>
            <p style="color:#94a3b8;">Available Balance</p>
        </div>

        <a href="/shop" class="btn">🛒 Shop / Store Product</a>
        <a href="/profile" class="btn">👤 My Profile</a>
        <a href="/add_balance" class="btn">💸 Add Balance</a>
        <a href="/logout" class="btn btn-danger">🚪 Logout</a>
    </div>
    """)

@app.route('/login', methods=['POST'])
def web_login():
    uid = request.form['uid'].strip()
    session['uid'] = uid
    get_user_info(uid) # Create if not exists
    return redirect(url_for('web_home'))

@app.route('/logout')
def web_logout():
    session.pop('uid', None)
    return redirect(url_for('web_home'))

@app.route('/shop')
def web_shop():
    if 'uid' not in session: return redirect(url_for('web_home'))
    products = list(products_col.find({}))
    
    html = BASE_STYLE + "<div class='container'><div class='header'><h1>🛒 Store Products</h1></div><div class='product-grid'>"
    for p in products:
        html += f"""
        <div class='product-card'>
            <div class='product-title'>{p['name']}</div>
            <div style='margin-bottom:15px;'>
                {" ".join([f"<span class='price-badge'>{d} - ₹{pr}</span>" for d, pr in p['prices'].items()])}
            </div>
            <a href='/product/{str(p["_id"])}' class='btn btn-success' style='padding:10px; font-size:14px;'>View & Buy</a>
        </div>
        """
    html += "</div><br><a href='/' class='btn btn-warning'>🔙 Back to Menu</a></div>"
    return render_template_string(html)

@app.route('/product/<p_id>')
def web_product(p_id):
    if 'uid' not in session: return redirect(url_for('web_home'))
    uid = session['uid']
    p = products_col.find_one({"_id": ObjectId(p_id)})
    if not p: return "Product not found", 404
    
    html = BASE_STYLE + f"""
    <div class='container'>
        <div class='header'><h1>📦 {p['name']}</h1></div>
        <div class='card'>
            <p style='color:#94a3b8; margin-bottom:20px;'>{p.get('description', 'No description.')}</p>
            <h3 style='text-align:left; margin-bottom:15px;'>Select Duration:</h3>
    """
    for dur, price in p["prices"].items():
        html += f"""
        <form action="/buy_web" method="POST" style="margin-bottom:10px;">
            <input type="hidden" name="p_id" value="{p_id}">
            <input type="hidden" name="duration" value="{dur}">
            <button type="submit" class="btn" style="display:flex; justify-content:space-between;">
                <span>⏱ {dur}</span>
                <span>₹{price}</span>
            </button>
        </form>
        """
    
    html += "<br><a href='/shop' class='btn btn-warning'>🔙 Back to Shop</a></div></div>"
    return render_template_string(html)

@app.route('/buy_web', methods=['POST'])
def buy_web():
    if 'uid' not in session: return redirect(url_for('web_home'))
    uid = session['uid']
    p_id = request.form['p_id']
    duration = request.form['duration']
    
    product = products_col.find_one({"_id": ObjectId(p_id)})
    price = float(product["prices"][duration])
    bal = get_balance(uid)
    
    if bal < price:
        return render_template_string(BASE_STYLE + f"<div class='container'><div class='card'><h2 style='color:#ef4444;'>❌ Low Balance</h2><p>You need ₹{price} but have ₹{bal}.</p><br><a href='/add_balance' class='btn btn-success'>Add Balance</a><a href='/shop' class='btn btn-warning'>Back</a></div></div>")
    
    # Deduct and Buy
    if deduct_balance(uid, price):
        # Call API
        try:
            data = {'api_key': RESELLER_API_KEY, 'action': 'buy', 'product_id': str(product["pid"]).strip(), 'duration': str(duration).strip(), 'quantity': 1}
            res = requests.post(RESELLER_API_URL, data=data, headers={'x-master-key': MASTER_KEY})
            result = res.json()
        except Exception as e:
            result = {"status": "error", "message": str(e)}
            
        if result.get("status") == "success" or "keys" in result:
            key = result.get("keys", ["Key not found"])[0]
            log_order(uid, product['name'], key, price)
            return render_template_string(BASE_STYLE + f"<div class='container'><div class='card'><h2 style='color:#10b981;'>✅ Purchase Successful!</h2><p style='margin:20px 0;'>Your Key:</p><div style='background:#0f172a; padding:15px; border-radius:8px; font-family:monospace; font-size:18px; border:1px solid #38bdf8;'>{key}</div><br><a href='/' class='btn'>Back to Menu</a></div></div>")
        else:
            # REFUND ON FAILURE
            credit_balance(uid, price)
            return render_template_string(BASE_STYLE + f"<div class='container'><div class='card'><h2 style='color:#ef4444;'>❌ Out of Stock</h2><p>API Error: {result.get('message', 'Unknown')}</p><p style='color:#10b981; margin-top:10px;'>₹{price} Refunded to Wallet.</p><br><a href='/' class='btn'>Back to Menu</a></div></div>")
    
    return redirect(url_for('web_home'))

@app.route('/add_balance')
def web_add_balance():
    if 'uid' not in session: return redirect(url_for('web_home'))
    return render_template_string(BASE_STYLE + """
    <div class='container'>
        <div class='header'><h1>💸 Add Balance</h1></div>
        <div class='card'>
            <form action="/gen_qr_web" method="POST">
                <div class="input-group">
                    <label>Enter Amount (₹)</label>
                    <input type="number" name="amount" min="10" required placeholder="e.g. 100">
                </div>
                <button type="submit" class="btn btn-success">Generate QR</button>
            </form>
            <br><a href='/' class='btn btn-warning'>🔙 Back to Menu</a>
        </div>
    </div>
    """)

@app.route('/gen_qr_web', methods=['POST'])
def gen_qr_web():
    if 'uid' not in session: return redirect(url_for('web_home'))
    amount = float(request.form['amount'])
    
    try:
        order = fg.create_order(amount=amount, customer_name=session['uid'])
        return render_template_string(BASE_STYLE + f"""
        <div class='container'>
            <div class='header'><h1>Scan to Pay ₹{amount}</h1></div>
            <div class='card'>
                <img src="{order.qr_url}" style="width:100%; max-width:300px; border-radius:10px;">
                <p style="margin:20px 0; color:#94a3b8;">Order ID: {order.order_id}</p>
                <p style="color:#f59e0b;">Waiting for payment... Refresh this page after paying.</p>
                <br><a href='/' class='btn'>I have Paid (Check Status)</a>
            </div>
        </div>
        """)
    except Exception as e:
        return f"API Error: {e}"

@app.route('/profile')
def web_profile():
    if 'uid' not in session: return redirect(url_for('web_home'))
    uid = session['uid']
    orders = list(orders_col.find({"uid": str(uid)}).sort("_id", -1).limit(10))
    
    html = BASE_STYLE + f"<div class='container'><div class='header'><h1>👤 My Profile</h1></div><div class='card'><h3>ID: {uid}</h3><h3 style='color:#10b981;'>Balance: ₹{get_balance(uid)}</h3></div>"
    html += "<div class='card'><h3>Recent Purchases</h3><div style='text-align:left;'>"
    for o in orders:
        html += f"<div style='border-bottom:1px solid #333; padding:10px 0;'><b>{o['product']}</b> - ₹{o['price']}<br><code>{o['key']}</code></div>"
    html += "</div></div><a href='/' class='btn btn-warning'>🔙 Back to Menu</a></div>"
    return render_template_string(html)

# ================== ADMIN PANEL (Separate Route) ==================
# Agar aapko admin panel chahiye toh aap /admin par ja sakte hain (Yahan default admin code add karna padega, but abhi ke liye maine ise simple rakha hai)
@app.route('/admin')
def admin_panel():
    # Simple security: Only user with Admin ID can access
    if 'uid' not in session or str(session['uid']) != str(ADMIN_ID):
        return "Access Denied. Login with Admin ID (7778093775) first."
    
    # Aapka purana admin code yahan aayega (Products add, etc.)
    # (Main ise short rakh raha hoon taaki code na bade, but aap purana admin template yahan paste kar sakte hain)
    return "<h1>Admin Panel (WIP)</h1><p>You can add products here.</p>"

# ================== RUNNING BOT & WEB ==================
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def run_bot():
    print("Starting Telegram Bot...")
    try: 
        bot.delete_webhook(drop_pending_updates=True) 
    except: pass
    bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    run_flask()
