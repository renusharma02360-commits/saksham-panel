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
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId

# ================== CONFIG ==================
BOT_TOKEN = "8764644526:AAET1x8jqFsp4d-XvdiZbVx-aO2cyKY3ISc"
API_KEY   = "fam_4c308a3f58df8f752e41770178d877982e4e1a58"
ADMIN_ID  = 7778093775
MONGO_URI = os.environ.get("MONGO_URI") 
UPLOAD_FOLDER = "static/uploads"
WEB_URL = "https://saksham-panel-kpsl.onrender.com" 

ADMIN_WP = "918849507563" 
SUPPORT_LINK = "https://wa.me/918849507563" 

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
star_packages_col = db.star_packages # Naya collection packages ke liye

bot = telebot.TeleBot(BOT_TOKEN)
fg  = FamGateway(api_key=API_KEY)

# ---------------- DB HELPERS ----------------
def get_settings():
    s = settings_col.find_one({"_id": "global"})
    if not s:
        default_s = {"_id": "global", "star_enabled": True}
        settings_col.insert_one(default_s)
        return default_s
    return s

def save_settings(updates):
    settings_col.update_one({"_id": "global"}, {"$set": updates}, upsert=True)

def get_user_info(uid):
    u = users_col.find_one({"_id": str(uid)})
    if not u:
        default_u = {"_id": str(uid), "balance": 0.0, "name": "User", "discount": 0, "is_star": False}
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
    text = f"👋 <b>Welcome to SAKSHAM PANEL STORE, {msg.from_user.first_name}!</b>\n\n💳 <b>Your Balance:</b> ₹{get_balance(uid):.2f}\n\n👇 <i>Select an option below:</i>"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🛒 Shop Now", callback_data="bot_shop"))
    kb.add(InlineKeyboardButton("⭐ Paid Push (Star)", web_app=WebAppInfo(url=f"{WEB_URL}/paid_push")))
    kb.add(InlineKeyboardButton("👤 My Profile", callback_data="bot_profile"), InlineKeyboardButton("💻 Web App", web_app=WebAppInfo(url=WEB_URL)))
    kb.add(InlineKeyboardButton("💸 Add Balance", web_app=WebAppInfo(url=f"{WEB_URL}/deposit")))
    if str(uid) == str(ADMIN_ID):
        kb.add(InlineKeyboardButton("⚙️ Admin Panel", web_app=WebAppInfo(url=f"{WEB_URL}/admin")))
    bot.send_message(msg.chat.id, text, parse_mode="HTML", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: True)
def bot_callbacks(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    
    if call.data == "bot_shop":
        products = list(products_col.find({"status": {"$ne": "out_of_stock"}}))
        if not products:
            return bot.send_message(call.message.chat.id, "❌ Store is currently empty.")
        kb = InlineKeyboardMarkup(row_width=1)
        for p in products:
            kb.add(InlineKeyboardButton(f"📦 {p.get('name')}", callback_data=f"bot_view|{p['_id']}"))
        kb.add(InlineKeyboardButton("🔙 Back to Menu", callback_data="bot_main"))
        bot.edit_message_text("🛒 <b>STORE PRODUCTS</b>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
                              
    elif call.data == "bot_profile":
        uid = str(uid)
        u = get_user_info(uid)
        star_badge = "⭐ <b>VERIFIED STAR</b>\n" if u.get('is_star') else ""
        text = f"👤 <b>MY PROFILE</b>\n\n{star_badge}🆔 ID: <code>{uid}</code>\n💵 Balance: <b>₹{u.get('balance', 0):.2f}</b>\n🏷️ Reseller: {u.get('discount', 0)}% OFF"
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="bot_main"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
        
    elif call.data == "bot_main":
        text = f"👋 <b>Welcome to SAKSHAM PANEL STORE!</b>\n\n💳 <b>Your Balance:</b> ₹{get_balance(uid):.2f}"
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(InlineKeyboardButton("🛒 Shop Now", callback_data="bot_shop"))
        kb.add(InlineKeyboardButton("⭐ Paid Push (Star)", web_app=WebAppInfo(url=f"{WEB_URL}/paid_push")))
        kb.add(InlineKeyboardButton("👤 My Profile", callback_data="bot_profile"), InlineKeyboardButton("💻 Web App", web_app=WebAppInfo(url=WEB_URL)))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)

    elif call.data.startswith("bot_view|"):
        p_id = call.data.split("|")[1]
        p = products_col.find_one({"_id": ObjectId(p_id)})
        u = get_user_info(uid)
        disc = u.get('discount', 0)
        
        text = f"📦 <b>{p['name']}</b>\n\n{p.get('features', '')}"
        kb = InlineKeyboardMarkup(row_width=2)
        for d, pr in p.get('prices', {}).items():
            final_pr = float(pr) - (float(pr) * disc / 100) if disc > 0 else float(pr)
            kb.add(InlineKeyboardButton(f"⏱ {d} - ₹{final_pr:.2f}", callback_data=f"bot_buy|{p_id}|{d}"))
        kb.add(InlineKeyboardButton("🔙 Back to Shop", callback_data="bot_shop"))
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
                kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back to Shop", callback_data="bot_shop"))
                bot.edit_message_text(f"❌ <b>API Error (Out of Stock)</b>\n\n₹{price:.2f} has been refunded to your wallet.", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)

# ================== FLASK WEB APP ==================
app = Flask(__name__)
app.secret_key = "sk_panel_secret"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

BASE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800;900&display=swap');
    * { box-sizing: border-box; font-family: 'Poppins', sans-serif; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body { background-color: #050810; color: #fff; padding-bottom: 100px; background-image: radial-gradient(circle at 15% 50%, rgba(56, 189, 248, 0.1), transparent 30%), radial-gradient(circle at 85% 30%, rgba(168, 85, 247, 0.1), transparent 30%); background-attachment: fixed; min-height: 100vh; animation: bodyFadeIn 0.8s ease-out; }
    @keyframes bodyFadeIn { from { opacity: 0; } to { opacity: 1; } }
    .container { padding: 20px; max-width: 1000px; margin: 0 auto; animation: slideUp 0.5s ease-out; }
    @keyframes slideUp { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
    
    .top-nav { display: flex; justify-content: space-between; align-items: center; padding: 20px 25px; background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(20px); position: sticky; top: 0; z-index: 100; border-bottom: 1px solid rgba(255,255,255,0.1); box-shadow: 0 5px 20px rgba(0,0,0,0.5); }
    .store-btn { background: linear-gradient(135deg, #0ea5e9, #2563eb); padding: 15px 25px; border-radius: 25px; font-weight: 800; font-size: 16px; color: white; text-decoration: none; box-shadow: 0 4px 15px rgba(14, 165, 233, 0.4); transition: 0.3s; }
    .store-btn:active { transform: scale(0.92); }
    .wallet-box { background: rgba(16, 185, 129, 0.15); border: 2px solid #10b981; padding: 12px 20px; border-radius: 25px; font-weight: 900; color: #10b981; font-size: 20px; box-shadow: 0 0 20px rgba(16, 185, 129, 0.2); }
    
    .hero-banner { width: 100%; padding: 40px 20px; background: linear-gradient(145deg, #1e1b4b, #0f172a); border-radius: 25px; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; margin-bottom: 30px; border: 2px solid #6366f1; box-shadow: inset 0 0 30px rgba(99, 102, 241, 0.2), 0 10px 40px rgba(0, 0, 0, 0.6); position: relative; overflow: hidden; }
    .logo-text { font-size: 38px; font-weight: 900; background: linear-gradient(to right, #fbbf24, #f59e0b); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 5px; text-shadow: 0 0 30px rgba(245, 158, 11, 0.5); text-transform: uppercase; letter-spacing: 1px; }
    .tagline { font-size: 13px; color: #38bdf8; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; margin-top: 5px; text-shadow: 0 0 10px rgba(56, 189, 248, 0.5); }
    
    .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px; }
    .stat-card { background: linear-gradient(145deg, #0f172a, #1e293b); border-radius: 20px; padding: 25px; border: 1px solid rgba(255,255,255,0.08); box-shadow: 0 10px 25px rgba(0,0,0,0.3); transition: 0.3s; }
    .stat-card:hover { transform: translateY(-5px); border-color: #38bdf8; box-shadow: 0 10px 30px rgba(56,189,248,0.2); }
    .stat-title { font-size: 15px; color: #94a3b8; font-weight: 700; margin-bottom: 10px; text-transform: uppercase; }
    .stat-value { font-size: 32px; font-weight: 900; }

    .search-box { display: flex; background: #0f172a; border: 2px solid #334155; border-radius: 15px; padding: 10px; margin-bottom: 30px; transition: 0.3s; }
    .search-box:focus-within { border-color: #38bdf8; box-shadow: 0 0 20px rgba(56,189,248,0.3); }
    .search-box input { flex: 1; background: transparent; border: none; color: #fff; font-size: 16px; padding: 10px; outline: none; }
    .search-box button { background: #38bdf8; color: #000; border: none; padding: 10px 20px; border-radius: 10px; font-weight: 800; cursor: pointer; }

    .reseller-banner { background: linear-gradient(135deg, #f59e0b, #d97706, #fbbf24); background-size: 200% 200%; animation: gradientShift 3s ease infinite; border-radius: 20px; padding: 25px; margin-bottom: 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 10px 30px rgba(245, 158, 11, 0.4); border: 2px solid #fbbf24; position: relative; overflow: hidden; }
    @keyframes gradientShift { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
    .reseller-text { color: #000; position: relative; z-index: 1; }
    .reseller-text h2 { font-size: 22px; font-weight: 900; margin-bottom: 5px; }
    .reseller-text p { font-size: 14px; font-weight: 700; }
    .reseller-btn { background: #000; color: #fbbf24; padding: 12px 25px; border-radius: 15px; font-weight: 900; font-size: 16px; text-decoration: none; position: relative; z-index: 1; box-shadow: 0 5px 15px rgba(0,0,0,0.5); transition: 0.3s; border: 2px solid #fbbf24; }
    .reseller-btn:hover { background: #fbbf24; color: #000; transform: scale(1.05); }

    .product-grid { display: grid; grid-template-columns: 1fr; gap: 20px; }
    .product-card { background: linear-gradient(145deg, #0f172a, #050810); border-radius: 25px; padding: 30px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 15px 35px rgba(0,0,0,0.5); transition: 0.3s; }
    .product-card:hover { transform: translateY(-3px); box-shadow: 0 15px 40px rgba(56,189,248,0.1); border-color: rgba(56,189,248,0.3); }
    .product-title { font-size: 24px; font-weight: 900; color: #fff; margin-bottom: 15px; }

    .action-btn { display: block; width: 100%; padding: 20px; border-radius: 15px; text-align: center; font-weight: 900; font-size: 18px; text-decoration: none; border: none; cursor: pointer; text-transform: uppercase; letter-spacing: 1px; transition: 0.3s; }
    .action-btn:hover { transform: translateY(-2px); filter: brightness(1.2); }
    .action-btn:active { transform: scale(0.95); }
    .btn-primary { background: linear-gradient(135deg, #0ea5e9, #3b82f6); color: white; box-shadow: 0 8px 25px rgba(14, 165, 233, 0.4); }
    .btn-success { background: linear-gradient(135deg, #10b981, #059669); color: white; box-shadow: 0 8px 25px rgba(16, 185, 129, 0.4); }
    .btn-danger { background: linear-gradient(135deg, #ef4444, #b91c1c); color: white; box-shadow: 0 8px 25px rgba(239, 68, 68, 0.4); }
    .btn-warning { background: linear-gradient(135deg, #f59e0b, #d97706); color: black; box-shadow: 0 8px 25px rgba(245, 158, 11, 0.4); }

    .input-group { margin-bottom: 20px; }
    .input-group label { display: block; font-size: 16px; color: #cbd5e1; margin-bottom: 10px; font-weight: 700; }
    .input-group input, .input-group textarea { width: 100%; padding: 20px; border-radius: 15px; border: 2px solid #334155; background: #0f172a; color: #fff; font-size: 18px; outline: none; font-weight: 600; transition: 0.3s; }
    .input-group input:focus, .input-group textarea:focus { border-color: #38bdf8; box-shadow: 0 0 20px rgba(56,189,248,0.3); }
    
    .gameplay-banner-container { width: 100%; aspect-ratio: 1 / 1; border-radius: 15px; overflow: hidden; border: 2px solid #00f0ff; box-shadow: 0 0 25px rgba(0, 240, 255, 0.4), inset 0 0 20px rgba(0,0,0,0.8); margin-bottom: 20px; position: relative; background: #000; }
    .gameplay-banner { width: 100%; height: 100%; object-fit: contain; object-position: center; transition: transform 0.5s ease; }
    .gameplay-banner-container:hover .gameplay-banner { transform: scale(1.05); }
    
    .product-page-title { text-align: center; font-size: 28px; font-weight: 900; color: white; text-shadow: 0 0 15px rgba(255,255,255,0.4); margin-bottom: 20px; letter-spacing: 1px; }
    .feature-item { background: linear-gradient(90deg, #0a101f, #111827); border: 1px solid #1e293b; border-radius: 12px; padding: 18px; margin-bottom: 12px; display: flex; align-items: center; gap: 15px; font-weight: 700; color: #e2e8f0; font-size: 16px; transition: 0.3s; }
    .feature-item:hover { transform: translateX(5px); border-color: #10b981; }
    .feature-item::before { content: '✅'; font-size: 20px; filter: drop-shadow(0 0 5px #10b981); }
    
    .check-btns { display: flex; gap: 12px; margin-top: 20px; margin-bottom: 30px; }
    .btn-cyan { flex: 1; background: linear-gradient(135deg, #0ea5e9, #2563eb); border: none; color: white; padding: 15px 10px; border-radius: 12px; font-weight: 800; font-size: 14px; text-align: center; text-decoration: none; text-transform: uppercase; display: flex; align-items: center; justify-content: center; gap: 8px; box-shadow: 0 5px 15px rgba(14,165,233,0.4); transition: 0.3s; }
    .btn-cyan:hover { transform: translateY(-3px); box-shadow: 0 8px 25px rgba(14,165,233,0.6); }
    .btn-red { flex: 1; background: linear-gradient(135deg, #ef4444, #b91c1c); border: none; color: white; padding: 15px 10px; border-radius: 12px; font-weight: 800; font-size: 14px; text-align: center; text-decoration: none; text-transform: uppercase; display: flex; align-items: center; justify-content: center; gap: 8px; box-shadow: 0 5px 15px rgba(239,68,68,0.4); transition: 0.3s; }
    .btn-red:hover { transform: translateY(-3px); box-shadow: 0 8px 25px rgba(239,68,68,0.6); }
    
    .purchase-header { background: linear-gradient(90deg, #8b5cf6, #6366f1); color: white; padding: 15px; border-radius: 12px; text-align: center; font-weight: 900; font-size: 20px; text-transform: uppercase; margin-bottom: 20px; letter-spacing: 1px; box-shadow: 0 5px 20px rgba(139, 92, 246, 0.4); }
    
    .price-row-ui { display: flex; align-items: center; justify-content: space-between; background: linear-gradient(145deg, #0a101f, #050810); border: 1px solid rgba(56, 189, 248, 0.2); border-radius: 15px; padding: 18px 25px; margin-bottom: 15px; transition: 0.3s; box-shadow: 0 5px 15px rgba(0,0,0,0.4); }
    .price-row-ui:hover { border-color: #00f0ff; transform: translateY(-2px); box-shadow: 0 8px 25px rgba(0,240,255,0.15); }
    .price-dur { font-weight: 800; font-size: 18px; color: #00f0ff; margin-bottom: 5px; text-shadow: 0 0 10px rgba(0,240,255,0.5); }
    .price-amt { font-weight: 900; font-size: 22px; color: white; }
    
    .buy-btn-ui { background: linear-gradient(45deg, #ff00cc, #ff3366, #ff00cc); background-size: 200% auto; color: white; padding: 15px 30px; border-radius: 10px; font-weight: 900; font-size: 18px; border: none; cursor: pointer; box-shadow: 0 5px 15px rgba(255, 0, 204, 0.4), 0 0 20px rgba(255, 0, 204, 0.2); text-transform: uppercase; transition: 0.3s; animation: shine 3s linear infinite; }
    .buy-btn-ui:hover { transform: translateY(-3px) scale(1.05); box-shadow: 0 8px 25px rgba(255, 0, 204, 0.6), 0 0 30px rgba(255, 0, 204, 0.4); }
    .buy-btn-ui:active { transform: translateY(1px) scale(0.95); }
    
    @keyframes shine { to { background-position: 200% center; } }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

    .floating-support { position: fixed; bottom: 30px; right: 30px; background: linear-gradient(135deg, #10b981, #059669); width: 60px; height: 60px; border-radius: 50%; display: flex; justify-content: center; align-items: center; font-size: 30px; color: white; text-decoration: none; box-shadow: 0 5px 20px rgba(16,185,129,0.5); z-index: 1000; animation: float 3s ease-in-out infinite; }
    @keyframes float { 0% { transform: translateY(0px); } 50% { transform: translateY(-10px); } 100% { transform: translateY(0px); } }

    #toast { visibility: hidden; min-width: 250px; background-color: #10b981; color: #fff; text-align: center; border-radius: 12px; padding: 16px; position: fixed; z-index: 10000; left: 50%; bottom: 30px; transform: translateX(-50%); font-size: 16px; font-weight: bold; box-shadow: 0 5px 20px rgba(16,185,129,0.5); opacity: 0; transition: opacity 0.3s, bottom 0.3s; }
    #toast.show { visibility: visible; opacity: 1; bottom: 50px; }
</style>
<div id="toast">✅ Key Copied!</div>
<script>
    function copyKey(text) {
        navigator.clipboard.writeText(text);
        var x = document.getElementById("toast");
        x.className = "show";
        setTimeout(function(){ x.className = x.className.replace("show", ""); }, 3000);
    }
</script>
"""

# ================== USER AUTH ROUTES ==================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form['username']
        pw = request.form['password']
        existing_user = web_users_col.find_one({"username": user})
        
        if existing_user:
            stored_password = existing_user['password']
            if stored_password.startswith(('pbkdf2:', 'scrypt:', 'argon2:')):
                if check_password_hash(stored_password, pw):
                    session['uid'] = existing_user['uid']
                    session['username'] = user
                    return redirect(url_for('web_home'))
            else:
                if stored_password == pw:
                    new_hashed = generate_password_hash(pw)
                    web_users_col.update_one({"_id": existing_user["_id"]}, {"$set": {"password": new_hashed}})
                    session['uid'] = existing_user['uid']
                    session['username'] = user
                    return redirect(url_for('web_home'))
            
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
        <div class="hero-banner">
            <div class="logo-text">SAKSHAM PANEL</div>
            <div class="tagline">100% Trusted • Instant Delivery</div>
        </div>
        <div class="product-card">
            <h2 style="font-size: 28px; margin-bottom: 25px; text-align: center; color: #38bdf8; font-weight: 900;">User Login</h2>
            <form method="POST" action="/login">
                <div class="input-group"><label>Username</label><input type="text" name="username" required></div>
                <div class="input-group"><label>Password</label><input type="password" name="password" required></div>
                <button type="submit" class="action-btn btn-success">Login</button>
            </form>
            <div style="text-align: center; margin-top: 20px;">
                <a href="/register" style="color: #38bdf8; text-decoration: none; font-weight: 700; font-size:16px;">Don't have an account? Register</a>
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
        web_users_col.insert_one({"uid": uid, "username": user, "password": generate_password_hash(pw)})
        session['uid'] = uid
        session['username'] = user
        return redirect(url_for('web_home'))
        
    return render_template_string(BASE_CSS + """
    <div class="container fade-in" style="margin-top: 50px;">
        <div class="hero-banner">
            <div class="logo-text">SAKSHAM PANEL</div>
            <div class="tagline">100% Trusted • Instant Delivery</div>
        </div>
        <div class="product-card">
            <h2 style="font-size: 28px; margin-bottom: 25px; text-align: center; color: #38bdf8; font-weight: 900;">Register</h2>
            <form method="POST" action="/register">
                <div class="input-group"><label>Username</label><input type="text" name="username" required></div>
                <div class="input-group"><label>Password</label><input type="password" name="password" required></div>
                <button type="submit" class="action-btn btn-primary">Register</button>
            </form>
            <div style="text-align: center; margin-top: 20px;">
                <a href="/login" style="color: #38bdf8; text-decoration: none; font-weight: 700; font-size:16px;">Already have an account? Login</a>
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
    disc = u.get('discount', 0)
    is_star = u.get('is_star', False)
    
    search_q = request.args.get('q', '')
    if search_q:
        products = list(products_col.find({"name": {"$regex": search_q, "$options": "i"}}))
    else:
        products = list(products_col.find({}))
        
    prod_html = ""
    for p in products:
        status_badge = '<span style="background:#ef4444; color:#fff; padding:5px 10px; border-radius:5px; font-size:12px; margin-left:10px;">Out of Stock</span>' if p.get('status') == 'out_of_stock' else ''
        prod_html += f"""
        <div class="product-card fade-in" style="display: flex; justify-content: space-between; align-items: center;">
            <div class="product-title" style="margin-bottom: 0; font-size: 22px;">📦 {p.get('name', 'Unknown')} {status_badge}</div>
            <a href="/product/{str(p['_id'])}" class="action-btn btn-primary" style="width: auto; padding: 15px 30px; font-size: 16px;">View</a>
        </div>
        """

    reseller_html = ""
    if disc == 0:
        reseller_html = f"""
        <div class="reseller-banner fade-in">
            <div class="reseller-text">
                <h2>👑 Upgrade to Reseller</h2>
                <p>Get Flat 40% OFF on all products!</p>
            </div>
            <a href="/buy_reseller" class="reseller-btn">Buy Now @ ₹150</a>
        </div>
        """

    star_badge = "⭐ " if is_star else ""

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="display:flex; gap:10px;">
            <a href="/" class="store-btn">📦 Store</a>
            <a href="/paid_push" class="store-btn" style="background:#f59e0b; color:black;">⭐ Paid Push</a>
            <a href="/history" class="store-btn" style="background:#8b5cf6;">📜 History</a>
        </div>
        <div style="display:flex; align-items:center; gap:10px;">
            <div class="wallet-box">{star_badge}₹{bal:.2f}</div>
            <a href="/logout" class="store-btn" style="background:#ef4444; padding:12px 20px;">Logout</a>
        </div>
    </div>
    <div class="container">
        <div class="hero-banner">
            <div class="logo-text">SAKSHAM PANEL STORE</div>
            <div class="tagline">100% Trusted • Instant Delivery • 24/7 Support</div>
        </div>
        
        {reseller_html}

        <form class="search-box" method="GET" action="/">
            <input type="text" name="q" placeholder="Search products..." value="{search_q}">
            <button type="submit">🔍 Search</button>
        </form>

        <div class="stats-grid">
            <div class="stat-card"><div class="stat-title">💳 Wallet Balance</div><div class="stat-value text-green">₹{bal:.2f}</div></div>
            <div class="stat-card"><div class="stat-title">🔑 Purchased Keys</div><div class="stat-value text-blue">{len(list(orders_col.find({'uid': str(uid), 'type': 'purchase'})))}</div></div>
        </div>
        <a href="/deposit" class="action-btn btn-warning" style="margin-bottom:30px;">⚡ Add Balance</a>
        <div class="product-grid">{prod_html}</div>
    </div>
    
    <a href="{SUPPORT_LINK}" target="_blank" class="floating-support">🎧</a>
    """)

# ================== PAID PUSH / STAR SYSTEM ==================
@app.route('/paid_push', methods=['GET'])
def paid_push():
    if 'uid' not in session: return redirect(url_for('login'))
    uid = session['uid']
    u = get_user_info(uid)
    settings = get_settings()
    is_enabled = settings.get('star_enabled', True)
    
    if not is_enabled:
        return render_template_string(BASE_CSS + "<h2 style='text-align:center; color:#ef4444; margin-top:50px;'>Paid Push service is currently disabled.</h2>")
        
    if u.get('is_star'):
        return render_template_string(BASE_CSS + f"""
        <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a></div>
        <div class="container fade-in" style="margin-top:50px; text-align:center;">
            <div class="product-card" style="border-color:#fbbf24;">
                <h1 style="font-size:60px;">⭐</h1>
                <h2 style="color:#fbbf24; font-size:32px; font-weight:900;">You are already Star Verified!</h2>
                <p style="color:#fff; font-size:18px; margin-top:15px;">Enjoy your premium benefits.</p>
                <a href="/" class="action-btn btn-warning" style="margin-top:20px;">Back to Store</a>
            </div>
        </div>
        """)

    # Fetch all available star packages
    packages = list(star_packages_col.find({}))
    
    packages_html = ""
    for p in packages:
        packages_html += f"""
        <div class="product-card fade-in" style="margin-bottom:15px; display:flex; justify-content:space-between; align-items:center; border-color:#fbbf24;">
            <div>
                <div style="font-size:24px; font-weight:900; color:#fbbf24;">⭐ {p.get('name')}</div>
                <div style="font-size:20px; font-weight:800; color:#fff;">₹{p.get('price')}</div>
            </div>
            <a href="/buy_star_package/{str(p['_id'])}" class="action-btn btn-warning" style="width:auto; padding:12px 25px; font-size:16px; background:#fbbf24; color:#000;">Buy Now</a>
        </div>
        """
        
    if not packages:
        packages_html = "<h3 style='text-align:center; color:#94a3b8;'>No Star packages available right now.</h3>"

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a></div>
    <div class="container fade-in" style="margin-top:30px;">
        <div class="hero-banner" style="border-color:#fbbf24;">
            <h1 style="font-size:60px; margin-bottom:10px;">⭐</h1>
            <h2 style="color:#fbbf24; font-size:36px; font-weight:900;">Premium Paid Push</h2>
            <h3 style="color:#fff; font-size:24px; margin-top:5px;">FREE FIRE (FF)</h3>
        </div>

        <div style="background:rgba(251,191,36,0.1); border:2px solid #fbbf24; padding:20px; border-radius:15px; margin-bottom:30px;">
            <p style="color:#fff; font-size:18px; margin-bottom:10px;">✅ Instant Device Push</p>
            <p style="color:#fff; font-size:18px; margin-bottom:10px;">✅ VIP Verified Star Badge</p>
            <p style="color:#fff; font-size:18px;">✅ Priority Updates & 24/7 Support</p>
        </div>

        <h3 style="color:#fbbf24; font-size:24px; margin-bottom:20px;">Select a Package:</h3>
        {packages_html}
    </div>
    """)

@app.route('/buy_star_package/<p_id>', methods=['GET', 'POST'])
def buy_star_package(p_id):
    if 'uid' not in session: return redirect(url_for('login'))
    uid = session['uid']
    package = star_packages_col.find_one({"_id": ObjectId(p_id)})
    
    if not package:
        return "Package not found", 404
        
    amount = package['price']

    if request.method == 'POST':
        try:
            order = fg.create_order(amount=amount, customer_name=f"StarPush_{uid}")
            
            QR_HTML = BASE_CSS + f"""
            <div class="top-nav"><a href="/paid_push" class="store-btn">🔙 Back</a></div>
            <div class="container fade-in" style="margin-top:30px; text-align:center;">
                <div class="product-card" style="padding: 40px 20px; border-color:#fbbf24; box-shadow: 0 0 30px rgba(251,191,36,0.2);">
                    <h1 style="font-size:50px; margin-bottom:10px;">⭐</h1>
                    <h2 style="color:#fbbf24; font-size:32px; font-weight:900; margin-bottom:10px;">{package['name']}</h2>
                    <p style="color:#fff; font-size:18px; margin-bottom:25px;">Pay ₹{amount} to activate</p>
                    
                    <div id="qr-section">
                        <div style="background:#fff; padding:15px; border-radius:20px; display:inline-block; box-shadow: 0 0 30px rgba(251, 191, 36, 0.6);">
                            <img src="{order.qr_url}" style="width:100%; max-width:250px; display:block; border-radius:10px;">
                        </div>
                        
                        <div id="loading-section" style="margin-top:30px;">
                            <div style="display:inline-block; width:45px; height:45px; border:4px solid rgba(255,255,255,0.1); border-top:4px solid #fbbf24; border-radius:50%; animation: spin 1s linear infinite;"></div>
                            <h3 style="color:#fbbf24; margin-top:15px; font-weight:800; font-size:20px;">Waiting for Payment...</h3>
                            <button onclick="checkStarPayment()" class="action-btn btn-warning" style="margin-top:20px; padding:15px; font-size:16px; border-radius:10px; background:#fbbf24; color:#000;">🔄 Check Status Manually</button>
                        </div>
                    </div>

                    <div id="success-section" style="display:none; margin-top:30px;">
                        <div style="font-size:70px; margin-bottom:20px;">⭐</div>
                        <h2 style="color:#fbbf24; font-size:32px; font-weight:900;">PAYMENT SUCCESSFUL!</h2>
                        <p style="color:#fff; font-size:18px; margin-top:15px;">Please provide your details to complete the order.</p>
                    </div>
                </div>
            </div>
            <script>
                function checkStarPayment() {{
                    fetch('/check_star_payment/{order.order_id}/{amount}/{urllib.parse.quote(package["name"])}')
                    .then(response => response.json())
                    .then(data => {{
                        if (data.status === 'success') {{
                            window.location.href = '/star_form?amount={amount}&pkg={urllib.parse.quote(package["name"])}';
                        }} else if (data.status === 'expired') {{
                            alert('QR Expired! Please try again.');
                            window.location.reload();
                        }}
                    }});
                }}
                const pollInterval = setInterval(checkStarPayment, 3000);
            </script>
            """
            return render_template_string(QR_HTML)
        except Exception as e: 
            return f"<h2 style='color:red; text-align:center; margin-top:50px;'>API Error: {e}</h2>"

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/paid_push" class="store-btn">🔙 Back</a></div>
    <div class="container fade-in" style="margin-top:50px;">
        <div class="product-card" style="text-align:center; border-color:#fbbf24; box-shadow: 0 0 40px rgba(251,191,36,0.2);">
            <h1 style="font-size:60px; margin-bottom:10px;">⭐</h1>
            <h2 style="color:#fbbf24; font-size:32px; font-weight:900;">{package['name']}</h2>
            <h3 style="color:#fff; font-size:24px; margin-top:5px;">FREE FIRE (FF)</h3>
            
            <div style="background:#000; border:2px solid #fbbf24; padding:20px; border-radius:15px; margin:25px 0;">
                <h3 style="color:#fff; font-size:24px;">Price: <span style="color:#fbbf24;">₹{amount}</span></h3>
            </div>

            <form method="POST">
                <button type="submit" class="action-btn btn-warning" style="background:linear-gradient(135deg, #f59e0b, #fbbf24); color:#000; font-size:20px;">Generate QR to Pay ₹{amount}</button>
            </form>
        </div>
    </div>
    """)

@app.route('/check_star_payment/<order_id>/<float:amount>/<path:pkg_name>')
def check_star_payment(order_id, amount, pkg_name):
    if 'uid' not in session: return jsonify({"status": "unauthorized"})
    try:
        status = fg.get_status(order_id)
        if status.is_paid:
            uid = session['uid']
            users_col.update_one({"_id": str(uid)}, {"$set": {"is_star": True}})
            utr = status.utr if hasattr(status, 'utr') else f"STAR_{pkg_name}"
            if not orders_col.find_one({"utr": utr, "type": "purchase"}):
                orders_col.insert_one({"utr": utr, "uid": str(uid), "product": f"Paid Push ({pkg_name})", "key": "STAR-ACTIVATED", "price": amount, "type": "purchase", "time": time.strftime("%d-%m-%Y %I:%M %p")})
            return jsonify({"status": "success"})
        elif status.is_expired:
            return jsonify({"status": "expired"})
        else:
            return jsonify({"status": "pending"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/star_form', methods=['GET', 'POST'])
def star_form():
    if 'uid' not in session: return redirect(url_for('login'))
    amount = request.args.get('amount', 100)
    pkg_name = request.args.get('pkg', '1 Star')
    
    if request.method == 'POST':
        game_name = request.form['game_name']
        game_uid = request.form['game_uid']
        
        message = f"Hello Admin, I have paid ₹{amount} for Paid Push ({pkg_name}).\n\n🎮 Game Name: {game_name}\n🆔 Game UID: {game_uid}\n\nPlease push the stars to my ID."
        wa_link = f"https://wa.me/{ADMIN_WP}?text={urllib.parse.quote(message)}"
        
        return redirect(wa_link)
        
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a></div>
    <div class="container fade-in" style="margin-top:50px;">
        <div class="product-card" style="text-align:center; border-color:#fbbf24; box-shadow: 0 0 40px rgba(251,191,36,0.2);">
            <h1 style="font-size:60px; margin-bottom:10px;">⭐</h1>
            <h2 style="color:#fbbf24; font-size:32px; font-weight:900;">Payment Received!</h2>
            <p style="color:#fff; font-size:18px; margin:15px 0;">Package: <b>{pkg_name}</b> (₹{amount})</p>
            <p style="color:#94a3b8; font-size:14px; margin-bottom:20px;">Please enter your Free Fire details.</p>
            
            <form method="POST">
                <div class="input-group" style="text-align:left;">
                    <label>Free Fire Name</label>
                    <input type="text" name="game_name" placeholder="Enter your FF Name" required>
                </div>
                <div class="input-group" style="text-align:left;">
                    <label>Free Fire UID</label>
                    <input type="text" name="game_uid" placeholder="Enter your FF UID" required>
                </div>
                <button type="submit" class="action-btn btn-success" style="background:linear-gradient(135deg, #10b981, #059669); font-size:20px;">Submit Details</button>
            </form>
        </div>
    </div>
    """)

# ================== RESELLER & PRODUCT ROUTES ==================
@app.route('/buy_reseller', methods=['GET', 'POST'])
def buy_reseller():
    if 'uid' not in session: return redirect(url_for('login'))
    uid = session['uid']
    u = get_user_info(uid)
    reseller_price = 150
    
    if u.get('discount', 0) > 0:
        return "You are already a reseller!"

    if request.method == 'POST':
        try:
            order = fg.create_order(amount=reseller_price, customer_name=f"Reseller_{session['uid']}")
            
            QR_HTML = BASE_CSS + f"""
            <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a></div>
            <div class="container fade-in" style="margin-top:30px; text-align:center;">
                <div class="product-card" style="padding: 40px 20px; border-color:#fbbf24; box-shadow: 0 0 30px rgba(251,191,36,0.2);">
                    <h1 style="font-size:60px; margin-bottom:10px;">👑</h1>
                    <h2 style="color:#fbbf24; font-size:32px; font-weight:900; margin-bottom:10px;">Buy Reseller VIP</h2>
                    <p style="color:#fff; font-size:18px; margin-bottom:25px;">Pay ₹150 to unlock 40% OFF</p>
                    
                    <div id="qr-section">
                        <div style="background:#fff; padding:15px; border-radius:20px; display:inline-block; box-shadow: 0 0 30px rgba(251, 191, 36, 0.6);">
                            <img src="{order.qr_url}" style="width:100%; max-width:250px; display:block; border-radius:10px;">
                        </div>
                        
                        <div id="loading-section" style="margin-top:30px;">
                            <div style="display:inline-block; width:45px; height:45px; border:4px solid rgba(255,255,255,0.1); border-top:4px solid #fbbf24; border-radius:50%; animation: spin 1s linear infinite;"></div>
                            <h3 style="color:#fbbf24; margin-top:15px; font-weight:800; font-size:20px;">Waiting for Payment...</h3>
                            
                            <button onclick="checkResellerPayment()" class="action-btn btn-warning" style="margin-top:20px; padding:15px; font-size:16px; border-radius:10px; background:#fbbf24; color:#000;">🔄 Check Status Manually</button>
                        </div>
                    </div>

                    <div id="success-section" style="display:none; margin-top:30px;">
                        <div style="font-size:70px; margin-bottom:20px;">✅</div>
                        <h2 style="color:#fbbf24; font-size:32px; font-weight:900;">VIP ACTIVATED!</h2>
                        <p style="color:#fff; font-size:18px; margin-top:15px;">You are now a Reseller. You will get 40% OFF.</p>
                    </div>
                </div>
            </div>
            <script>
                function checkResellerPayment() {{
                    fetch('/check_reseller_payment/{order.order_id}')
                    .then(response => response.json())
                    .then(data => {{
                        if (data.status === 'success') {{
                            document.getElementById('qr-section').style.display = 'none';
                            document.getElementById('success-section').style.display = 'block';
                            setTimeout(() => {{ window.location.href = '/'; }}, 3000);
                        }} else if (data.status === 'expired') {{
                            alert('QR Expired! Please try again.');
                            window.location.reload();
                        }}
                    }});
                }}
                const pollInterval = setInterval(checkResellerPayment, 3000);
            </script>
            """
            return render_template_string(QR_HTML)
        except Exception as e: 
            return f"<h2 style='color:red; text-align:center; margin-top:50px;'>API Error: {e}</h2>"

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a></div>
    <div class="container fade-in" style="margin-top:50px;">
        <div class="product-card" style="text-align:center; border-color:#fbbf24; box-shadow: 0 0 40px rgba(251,191,36,0.2);">
            <h1 style="font-size:50px; margin-bottom:10px;">👑</h1>
            <h2 style="color:#fbbf24; font-size:32px; font-weight:900;">Reseller VIP Package</h2>
            <p style="color:#94a3b8; font-size:18px; margin:20px 0;">Unlock 40% Discount on all products instantly.</p>
            
            <div style="background:rgba(251,191,36,0.1); border:2px solid #fbbf24; padding:20px; border-radius:15px; margin-bottom:30px;">
                <h3 style="color:#fff; font-size:24px;">Price: <span style="color:#fbbf24;">₹150</span></h3>
            </div>

            <form method="POST">
                <button type="submit" class="action-btn btn-warning" style="background:linear-gradient(135deg, #f59e0b, #fbbf24); color:#000; font-size:20px;">Generate QR to Pay ₹150</button>
            </form>
        </div>
    </div>
    """)

@app.route('/check_reseller_payment/<order_id>')
def check_reseller_payment(order_id):
    if 'uid' not in session: return jsonify({"status": "unauthorized"})
    try:
        status = fg.get_status(order_id)
        if status.is_paid:
            uid = session['uid']
            users_col.update_one({"_id": str(uid)}, {"$set": {"discount": 40}})
            utr = status.utr if hasattr(status, 'utr') else "RESELLER_PAYMENT"
            if not orders_col.find_one({"utr": utr, "type": "purchase"}):
                orders_col.insert_one({"utr": utr, "uid": str(uid), "product": "Reseller VIP Package", "key": "VIP-ACTIVATED", "price": 150, "type": "purchase", "time": time.strftime("%d-%m-%Y %I:%M %p")})
            return jsonify({"status": "success"})
        elif status.is_expired:
            return jsonify({"status": "expired"})
        else:
            return jsonify({"status": "pending"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/product/<p_id>')
def web_product(p_id):
    if 'uid' not in session: return redirect(url_for('login'))
    p = products_col.find_one({"_id": ObjectId(p_id)})
    if not p: return "Product not found", 404
    
    uid = session['uid']
    u = get_user_info(uid)
    discount = u.get('discount', 0)
    
    features_html = ""
    if p.get("features"):
        for f in p["features"].split('\n'):
            if f.strip():
                features_html += f'<div class="feature-item">{f.strip()}</div>'

    price_rows = ""
    if p.get('status') == 'out_of_stock':
         price_rows = f"""
         <div style="background:rgba(239,68,68,0.1); border:2px solid #ef4444; border-radius:15px; padding:30px; text-align:center; margin-top:20px;">
            <h3 style="color:#ef4444; font-size:24px; margin-bottom:10px;">Out of Stock</h3>
            <p style="color:#cbd5e1;">This product is currently unavailable. Please check back later.</p>
         </div>
         """
    else:
        for d, pr in p.get('prices', {}).items():
            final_price = float(pr) - (float(pr) * discount / 100) if discount > 0 else float(pr)
            orig_price_html = f"<span style='text-decoration:line-through; color:#ef4444; font-size:14px; margin-left:10px;'>₹{pr}</span>" if discount > 0 else ""
            price_rows += f"""
            <div class="price-row-ui">
                <div>
                    <div class="price-dur">{d}</div>
                    <div class="price-amt">₹{final_price:.2f} {orig_price_html}</div>
                </div>
                <form action="/buy_web" method="POST" style="margin: 0;">
                    <input type="hidden" name="p_id" value="{p_id}">
                    <input type="hidden" name="duration" value="{d}">
                    <button type="submit" class="buy-btn-ui">BUY</button>
                </form>
            </div>
            """

    banner_html = ""
    if p.get("image") and os.path.exists(p["image"]):
        banner_html = f"""
        <div class="gameplay-banner-container">
            <img src="/{p["image"]}" class="gameplay-banner">
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a><div class="wallet-box">₹{get_balance(uid):.2f}</div></div>
    <div class="container fade-in" style="margin-top:20px;">
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
    
    <a href="{SUPPORT_LINK}" target="_blank" class="floating-support">🎧</a>
    """)

@app.route('/buy_web', methods=['POST'])
def buy_web():
    if 'uid' not in session: return redirect(url_for('login'))
    uid = session['uid']
    p_id = request.form['p_id']
    duration = request.form['duration']
    
    product = products_col.find_one({"_id": ObjectId(p_id)})
    
    if product.get('status') == 'out_of_stock':
         return redirect(url_for('web_home'))

    u = get_user_info(uid)
    discount = u.get('discount', 0)
    bal = u.get('balance', 0.0)
    
    original_price = float(product.get("prices", {}).get(duration, 0))
    price = original_price - (original_price * discount / 100) if discount > 0 else original_price
    
    if bal < price:
        return render_template_string(BASE_CSS + f"""
        <div class="container fade-in" style="margin-top:50px;">
            <div class="product-card" style="text-align:center; border-color:#ef4444;">
                <h2 style="color:#ef4444; font-size:32px;">❌ Low Balance!</h2>
                <p style="color:#cbd5e1; margin-top:15px; font-size:20px;">You need ₹{price:.2f} to buy this key.</p>
                <p style="color:#38bdf8; margin-top:5px; font-size:18px;">Your Balance: ₹{bal:.2f}</p>
                <br>
                <a href="/deposit" class="action-btn btn-success">Add Balance Now</a>
                <a href="/" class="action-btn btn-primary" style="margin-top:15px;">Back to Store</a>
            </div>
        </div>
        """)
    
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
                    <h2 style="color:#10b981; font-size:36px;">✅ Purchase Successful!</h2>
                    <p style="color:#cbd5e1; margin-top:10px; font-size:18px;">Click below to copy your key</p>
                    <div style="background:#050810; padding:25px; border-radius:15px; border:2px solid #38bdf8; font-family:monospace; font-size:24px; margin:25px 0; font-weight:900; color:#38bdf8; word-break:break-all; box-shadow: inset 0 0 20px rgba(56,189,248,0.2);">{key}</div>
                    
                    <button onclick="copyKey('{key}')" class="action-btn btn-success" style="box-shadow: 0 0 20px rgba(16,185,129,0.5);">📋 Copy Key</button>
                    <a href="/" class="action-btn btn-primary" style="margin-top:15px;">Back to Store</a>
                </div>
            </div>
            """)
        else:
            credit_balance(uid, price)
            return render_template_string(BASE_CSS + f"""
            <div class="container fade-in" style="margin-top:50px;">
                <div class="product-card" style="text-align:center;">
                    <h2 style="color:#ef4444; font-size:32px;">❌ Out of Stock</h2>
                    <p style="color:#10b981; margin-top:20px; font-weight:900; font-size:20px;">₹{price:.2f} Refunded to Wallet.</p>
                    <br><a href="/" class="action-btn btn-warning">Back to Store</a>
                </div>
            </div>
            """)
    return redirect(url_for('web_home'))

@app.route('/history')
def web_history():
    if 'uid' not in session: return redirect(url_for('login'))
    uid = session['uid']
    orders = list(orders_col.find({"uid": str(uid)}).sort("_id", -1))
    
    history_html = ""
    for o in orders:
        o_type = o.get("type")
        if o_type == "purchase":
            color = "#fbbf24" if "Reseller" in o.get('product', '') or "Star" in o.get('product', '') else "#ef4444"
            history_html += f"""
            <div class="product-card" style="margin-bottom:20px; border-left: 5px solid {color};">
                <div style="display:flex; justify-content:space-between; font-size:14px; color:#94a3b8; margin-bottom:10px;">
                    <span>{o.get('time', '')}</span>
                    <span style="color:{color}; font-weight:900; font-size:18px;">-₹{o.get('price', 0)}</span>
                </div>
                <div style="font-weight:900; font-size:20px; color:#fff; margin-bottom:15px;">📦 {o.get('product', 'Unknown')}</div>
                <button onclick="copyKey('{o.get('key', '')}')" class="action-btn btn-primary" style="padding:12px; font-size:14px;">📋 Copy Key</button>
            </div>
            """
        elif o_type == "deposit":
            history_html += f"""
            <div class="product-card" style="margin-bottom:20px; border-left: 5px solid #10b981;">
                <div style="display:flex; justify-content:space-between; font-size:14px; color:#94a3b8; margin-bottom:10px;">
                    <span>{o.get('time', '')}</span>
                    <span style="color:#10b981; font-weight:900; font-size:18px;">+₹{o.get('amount', 0)}</span>
                </div>
                <div style="font-weight:900; font-size:18px; color:#e2e8f0;">💰 Wallet Top-Up</div>
                <div style="font-size:12px; color:#64748b; margin-top:5px;">UTR: {o.get('utr', 'N/A')}</div>
            </div>
            """
    
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a><div class="wallet-box">₹{get_balance(uid):.2f}</div></div>
    <div class="container fade-in" style="margin-top:20px;">
        <h2 style="text-align:center; color:#8b5cf6; font-weight:900; margin-bottom:30px; font-size:32px; text-shadow: 0 0 15px rgba(139, 92, 246, 0.5);">📜 Transaction History</h2>
        {history_html if history_html else '<p style="text-align:center; color:#94a3b8; font-size:20px;">No transactions yet.</p>'}
    </div>
    <a href="{SUPPORT_LINK}" target="_blank" class="floating-support">🎧</a>
    """)

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
                            <p style="color:#ef4444; font-size:14px; margin-top:10px; font-weight:bold;" id="error-msg"></p>
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
    <div class="top-nav"><a href="/" class="store-btn">🔙 Back</a></div>
    <div class="container fade-in" style="margin-top:20px;">
        <div class="product-card">
            <h2 style="font-size:32px; margin-bottom:30px; color:#38bdf8; text-align:center; font-weight:900;">Add Balance</h2>
            <form method="POST" action="/deposit">
                <div class="input-group"><label>Enter Amount (₹)</label><input type="number" name="amount" min="10" required placeholder="100"></div>
                <button type="submit" class="action-btn btn-success">Generate QR</button>
            </form>
        </div>
    </div>
    <a href="{SUPPORT_LINK}" target="_blank" class="floating-support">🎧</a>
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

# ================== ADMIN PANEL (NO LOGIN) ==================
@app.route('/admin', methods=['GET'])
def admin_panel():
    total_users = users_col.count_documents({})
    total_sales = orders_col.count_documents({"type": "purchase"})
    total_revenue = sum([o.get('price', 0) for o in orders_col.find({"type": "purchase"})])
    total_products = products_col.count_documents({})
    
    search_q = request.args.get('q', '')
    if search_q:
        products = list(products_col.find({"name": {"$regex": search_q, "$options": "i"}}))
    else:
        products = list(products_col.find({}))

    prod_html = ""
    for p in products:
        status_btn = f'<a href="/toggle_stock/{p["_id"]}" class="action-btn btn-warning" style="padding:12px 20px; font-size:14px; width:auto; background:#10b981; color:white;">🟢 Mark In Stock</a>' if p.get('status') == 'out_of_stock' else f'<a href="/toggle_stock/{p["_id"]}" class="action-btn btn-warning" style="padding:12px 20px; font-size:14px; width:auto; background:#ef4444; color:white;">🔴 Mark Out of Stock</a>'
        
        prod_html += f"""
        <div class="product-card" style="margin-bottom:15px; display:flex; justify-content:space-between; align-items:center; padding:20px;">
            <div>
                <div style="font-size:22px; font-weight:900; color:#38bdf8;">{p.get('name', '')}</div>
                <div style="font-size:14px; color:#94a3b8;">PID: {p.get('pid', '')}</div>
            </div>
            <div style="display:flex; gap:10px; flex-wrap:wrap;">
                {status_btn}
                <a href="/edit_product/{p['_id']}" class="action-btn btn-warning" style="padding:12px 20px; font-size:14px; width:auto;">✏️ Edit</a>
                <form action="/delete_product/{p['_id']}" method="POST">
                    <button type="submit" class="action-btn btn-danger" style="padding:12px 20px; font-size:14px; width:auto;">🗑️ Del</button>
                </form>
            </div>
        </div>
        """

    star_enabled = get_settings().get('star_enabled', True)
    
    # Star Packages List
    star_packages = list(star_packages_col.find({}))
    star_pkg_html = ""
    for sp in star_packages:
        star_pkg_html += f"""
        <div style="background:#0a101f; padding:15px; border-radius:12px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center; border:1px solid #334155;">
            <div>
                <div style="font-weight:800; color:#fbbf24; font-size:18px;">⭐ {sp.get('name')}</div>
                <div style="color:#fff; font-weight:600;">₹{sp.get('price')}</div>
            </div>
            <form action="/delete_star_package/{sp['_id']}" method="POST">
                <button type="submit" class="action-btn btn-danger" style="padding:8px 15px; font-size:14px; width:auto;">🗑️ Delete</button>
            </form>
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:24px; color:#38bdf8;">⚙️ Controller</div>
        <div style="display:flex; gap:10px;">
            <a href="/admin_history" class="store-btn" style="background:#8b5cf6; color:#fff;">📜 All History</a>
            <a href="/admin_users" class="store-btn" style="background:#f59e0b; color:#000;">👥 Users</a>
            <a href="/" class="store-btn" style="background:#ef4444;">Exit</a>
        </div>
    </div>
    <div class="container fade-in" style="margin-top:20px;">
        
        <div class="stats-grid" style="grid-template-columns: 1fr 1fr 1fr 1fr;">
            <div class="stat-card"><div class="stat-title">👥 Users</div><div class="stat-value text-blue" style="font-size:24px;">{total_users}</div></div>
            <div class="stat-card"><div class="stat-title">🛍️ Sales</div><div class="stat-value text-yellow" style="font-size:24px;">{total_sales}</div></div>
            <div class="stat-card"><div class="stat-title">💰 Revenue</div><div class="stat-value text-green" style="font-size:24px;">₹{total_revenue}</div></div>
            <div class="stat-card"><div class="stat-title">📦 Products</div><div class="stat-value" style="font-size:24px;">{total_products}</div></div>
        </div>

        <!-- PAID PUSH PACKAGE MANAGER -->
        <div class="product-card" style="margin-bottom:30px; border-color:#fbbf24;">
            <h3 style="margin-bottom:25px; color:#fbbf24; font-size:26px;">⭐ Paid Push Packages Manager</h3>
            
            <form method="POST" action="/update_star_settings" style="margin-bottom:20px;">
                <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
                    <select name="star_enabled" style="flex:1; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff; font-size:16px;">
                        <option value="true" {'selected' if star_enabled else ''}>🟢 Star Service ON</option>
                        <option value="false" {'selected' if not star_enabled else ''}>🔴 Star Service OFF</option>
                    </select>
                    <button type="submit" class="action-btn btn-warning" style="width:auto; padding:15px 25px; font-size:16px;">Update Status</button>
                </div>
            </form>

            <hr style="border-color:#334155; margin-bottom:20px;">

            <h4 style="color:#fff; margin-bottom:15px;">➕ Add New Package</h4>
            <form method="POST" action="/add_star_package" style="margin-bottom:20px;">
                <div style="display:flex; gap:10px; flex-wrap:wrap;">
                    <input type="text" name="pkg_name" placeholder="Package Name (e.g. 1 Star, 4 Stars)" style="flex:2; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff; font-size:16px;" required>
                    <input type="number" name="pkg_price" placeholder="Price (₹)" style="flex:1; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff; font-size:16px;" required>
                    <button type="submit" class="action-btn btn-success" style="width:auto; padding:15px 25px; font-size:16px;">Add Package</button>
                </div>
            </form>

            <h4 style="color:#fff; margin-bottom:15px;">📦 Available Packages</h4>
            {star_pkg_html if star_pkg_html else '<p style="color:#94a3b8;">No packages created yet.</p>'}
        </div>
        <!-- END PAID PUSH PACKAGE MANAGER -->

        <div class="product-card" style="margin-bottom:30px; border-color:#0ea5e9;">
            <h3 style="margin-bottom:25px; color:#38bdf8; font-size:26px;">➕ Add New Product</h3>
            <form method="POST" action="/add_product" enctype="multipart/form-data">
                <div class="input-group"><label>Product Name</label><input type="text" name="name" required></div>
                <div class="input-group"><label>PID</label><input type="text" name="pid" required></div>
                
                <div class="input-group">
                    <label>Banner Image (Square size recommended)</label>
                    <input type="file" name="image_file" accept="image/*" style="padding:15px; background:#050810; border:2px solid #334155; border-radius:15px;">
                </div>
                
                <div class="input-group"><label>Features (One per line)</label><textarea name="features" rows="4" placeholder="AIMBOT ADD&#10;AUTO REVIVE"></textarea></div>
                <div class="input-group"><label>Update File Link</label><input type="url" name="setup_video" placeholder="https://..."></div>
                <div class="input-group"><label>Video / Feedback Link</label><input type="url" name="hack_video" placeholder="https://..."></div>

                <label style="font-weight:900; color:#38bdf8; margin:20px 0 10px 0; display:block; font-size:20px;">Durations & Prices</label>
                <div id="price-container">
                    <div style="display:flex; gap:10px; margin-bottom:10px;">
                        <input type="text" name="duration[]" placeholder="1 Hours" style="flex:1; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">
                        <input type="number" name="price[]" placeholder="Price" style="flex:1; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">
                    </div>
                </div>
                <button type="button" onclick="addPrice()" class="action-btn btn-success" style="margin-bottom:25px; background:#f59e0b; color:#000;">+ Add More</button>
                <button type="submit" class="action-btn btn-primary">Save Product</button>
            </form>
        </div>

        <form class="search-box" method="GET" action="/admin">
            <input type="text" name="q" placeholder="Search products..." value="{search_q}">
            <button type="submit">🔍 Search</button>
        </form>

        <h3 style="margin-bottom:20px; color:#38bdf8; font-size:24px;">📦 All Products</h3>
        {prod_html}
    </div>
    <script>
        function addPrice() {{
            const c = document.getElementById('price-container');
            const d = document.createElement('div');
            d.style.display = 'flex'; d.style.gap = '10px'; d.style.marginBottom = '10px';
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;"><input type="number" name="price[]" placeholder="Price" style="flex:1; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">`;
            c.appendChild(d);
        }}
    </script>
    """)

@app.route('/update_star_settings', methods=['POST'])
def update_star_settings():
    enabled = request.form.get('star_enabled') == 'true'
    save_settings({"star_enabled": enabled})
    return redirect(url_for('admin_panel'))

@app.route('/add_star_package', methods=['POST'])
def add_star_package():
    name = request.form.get('pkg_name')
    price = int(request.form.get('pkg_price', 100))
    star_packages_col.insert_one({"name": name, "price": price})
    return redirect(url_for('admin_panel'))

@app.route('/delete_star_package/<p_id>', methods=['POST'])
def delete_star_package(p_id):
    star_packages_col.delete_one({"_id": ObjectId(p_id)})
    return redirect(url_for('admin_panel'))

@app.route('/toggle_stock/<p_id>')
def toggle_stock(p_id):
    p = products_col.find_one({"_id": ObjectId(p_id)})
    new_status = 'active' if p.get('status') == 'out_of_stock' else 'out_of_stock'
    products_col.update_one({"_id": ObjectId(p_id)}, {"$set": {"status": new_status}})
    return redirect(url_for('admin_panel'))

@app.route('/admin_history')
def admin_history():
    orders = list(orders_col.find({}).sort("_id", -1))
    history_html = ""
    for o in orders:
        web_u = web_users_col.find_one({"uid": o['uid']})
        uname = f"@{web_u['username']}" if web_u else o['uid']
        
        if o.get('type') == 'purchase':
            color = "#fbbf24" if "Reseller" in o.get('product', '') or "Star" in o.get('product', '') else "#ef4444"
            history_html += f"""
            <div class="product-card" style="margin-bottom:15px; border-left: 5px solid {color}; padding:20px;">
                <div style="display:flex; justify-content:space-between; font-size:14px; color:#94a3b8; margin-bottom:10px;">
                    <span>👤 {uname}</span>
                    <span>{o.get('time', '')}</span>
                </div>
                <div style="font-weight:900; font-size:18px; color:#fff; margin-bottom:5px;">📦 {o.get('product', 'Unknown')}</div>
                <div style="color:#38bdf8; font-weight:900; font-size:16px;">🔑 {o.get('key', 'N/A')}</div>
                <div style="color:{color}; font-weight:900; margin-top:5px;">Amount Deducted: ₹{o.get('price', 0)}</div>
            </div>
            """
        elif o.get('type') == 'deposit':
            history_html += f"""
            <div class="product-card" style="margin-bottom:15px; border-left: 5px solid #10b981; padding:20px;">
                <div style="display:flex; justify-content:space-between; font-size:14px; color:#94a3b8; margin-bottom:10px;">
                    <span>👤 {uname}</span>
                    <span>{o.get('time', '')}</span>
                </div>
                <div style="font-weight:900; font-size:18px; color:#e2e8f0; margin-bottom:5px;">💰 Added Balance</div>
                <div style="color:#10b981; font-weight:900; font-size:18px;">+₹{o.get('amount', 0)}</div>
                <div style="font-size:12px; color:#64748b; margin-top:5px;">UTR: {o.get('utr', 'N/A')}</div>
            </div>
            """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:24px; color:#38bdf8;">📜 All Transactions</div>
        <a href="/admin" class="store-btn">🔙 Back to Admin</a>
    </div>
    <div class="container fade-in" style="margin-top:20px;">
        {history_html if history_html else '<h3 style="text-align:center; color:#94a3b8;">No transactions found.</h3>'}
    </div>
    """)

@app.route('/admin_users', methods=['GET'])
def admin_users():
    search_query = request.args.get('q', '')
    if search_query:
        users = list(users_col.find({"_id": {"$regex": search_query, "$options": "i"}}).sort("balance", -1))
    else:
        users = list(users_col.find({}).sort("balance", -1)) 

    users_html = ""
    for u in users:
        web_username = web_users_col.find_one({"uid": u['_id']})
        display_name = f"@{web_username['username']}" if web_username else f"{u.get('name', 'User')} (Bot)"
        star_badge = "⭐ " if u.get('is_star') else ""

        users_html += f"""
        <div class="product-card" style="margin-bottom:15px; padding:20px; border-left: 5px solid {'#fbbf24' if u.get('is_star') else ('#f59e0b' if u.get('discount',0) > 0 else '#38bdf8')};">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <div style="font-weight:900; color:#fff; font-size:20px;">{star_badge}👤 {display_name}</div>
                    <div style="font-size:14px; color:#94a3b8; margin-top:5px;">ID: <code>{u['_id']}</code></div>
                </div>
                <div style="text-align:right;">
                    <div style="font-weight:900; color:#10b981; font-size:24px;">₹{u.get('balance', 0):.2f}</div>
                    <div style="font-size:12px; color:#f59e0b; font-weight:bold;">Reseller: {u.get('discount', 0)}% OFF</div>
                </div>
            </div>
            <a href="/admin_user_detail/{u['_id']}" class="action-btn btn-primary" style="margin-top:15px; padding:12px; font-size:14px;">👁️ View Full Details & History</a>
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:24px; color:#38bdf8;">👥 Users List</div>
        <a href="/admin" class="store-btn">🔙 Back to Admin</a>
    </div>
    <div class="container fade-in" style="margin-top:20px;">
        
        <form method="GET" action="/admin_users" style="display:flex; gap:10px; margin-bottom:25px;">
            <input type="text" name="q" value="{search_query}" placeholder="Search by User ID..." style="flex:1; padding:15px; border-radius:15px; border:2px solid #334155; background:#050810; color:#fff; font-size:16px;">
            <button type="submit" class="action-btn btn-primary" style="width:auto; padding:15px 25px;">Search</button>
        </form>

        <div style="display:flex; justify-content:space-between; margin-bottom:15px; color:#94a3b8; font-weight:bold;">
            <span>Total Users: {len(users)}</span>
            <span>Sorted by Balance (High to Low)</span>
        </div>

        {users_html if users_html else '<h3 style="text-align:center; color:#94a3b8;">No users found.</h3>'}
    </div>
    """)

@app.route('/admin_user_detail/<uid>', methods=['GET', 'POST'])
def admin_user_detail(uid):
    msg = ""
    if request.method == 'POST':
        amt = float(request.form.get('amount', 0))
        disc = int(request.form.get('discount', 0))
        
        users_col.update_one({"_id": str(uid)}, {"$inc": {"balance": amt}, "$set": {"discount": disc}})
        msg = f"""
        <div style="background:rgba(16,185,129,0.2); border:2px solid #10b981; border-radius:15px; padding:20px; margin-bottom:20px; text-align:center;">
            <h3 style="color:#10b981; font-weight:900;">✅ User Updated Successfully!</h3>
            <p style="color:#fff;">Balance Changed by: ₹{amt} | Discount Set: {disc}%</p>
        </div>
        """

    u = get_user_info(uid)
    web_username = web_users_col.find_one({"uid": uid})
    display_name = f"@{web_username['username']}" if web_username else u.get('name', 'User')
    
    orders = list(orders_col.find({"uid": str(uid)}).sort("_id", -1))
    
    history_html = ""
    for o in orders:
        o_type = o.get("type")
        if o_type == "purchase":
            color = "#fbbf24" if "Reseller" in o.get('product', '') or "Star" in o.get('product', '') else "#ef4444"
            history_html += f"""
            <div class="product-card" style="margin-bottom:15px; border-left: 5px solid {color}; padding:15px;">
                <div style="display:flex; justify-content:space-between; font-size:13px; color:#94a3b8; margin-bottom:5px;">
                    <span>{o.get('time', '')}</span>
                    <span style="color:{color}; font-weight:900;">-₹{o.get('price', 0)}</span>
                </div>
                <div style="font-weight:900; font-size:16px; color:#fff;">📦 {o.get('product', 'Unknown')}</div>
                <div style="color:#38bdf8; font-weight:900; font-size:14px; margin-top:5px;">🔑 {o.get('key', 'N/A')}</div>
            </div>
            """
        elif o_type == "deposit":
            history_html += f"""
            <div class="product-card" style="margin-bottom:15px; border-left: 5px solid #10b981; padding:15px;">
                <div style="display:flex; justify-content:space-between; font-size:13px; color:#94a3b8; margin-bottom:5px;">
                    <span>{o.get('time', '')}</span>
                    <span style="color:#10b981; font-weight:900;">+₹{o.get('amount', 0)}</span>
                </div>
                <div style="font-weight:900; font-size:16px; color:#e2e8f0;">💰 Added Balance</div>
                <div style="font-size:12px; color:#64748b; margin-top:5px;">UTR: {o.get('utr', 'N/A')}</div>
            </div>
            """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:24px; color:#38bdf8;">👤 User Details</div>
        <a href="/admin_users" class="store-btn">🔙 Back to Users</a>
    </div>
    <div class="container fade-in" style="margin-top:20px;">
        
        {msg}

        <div class="product-card" style="border-color:#38bdf8; margin-bottom:30px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <h2 style="font-size:26px; font-weight:900; color:#fff;">{display_name}</h2>
                    <p style="font-size:14px; color:#94a3b8; margin-top:5px;">ID: <code>{uid}</code></p>
                </div>
                <div style="text-align:right;">
                    <h2 style="color:#10b981; font-size:30px; font-weight:900;">₹{u.get('balance', 0):.2f}</h2>
                    <p style="font-size:13px; color:#f59e0b; font-weight:bold;">Reseller: {u.get('discount', 0)}% OFF</p>
                </div>
            </div>
            
            <form action="/admin_user_detail/{uid}" method="POST" style="display:flex; gap:10px; flex-wrap:wrap; margin-top:20px; padding-top:20px; border-top:1px solid #334155;">
                <input type="number" name="amount" placeholder="+/- Balance (e.g. 100 or -50)" style="flex:1; min-width:150px; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff; font-size:16px;">
                <input type="number" name="discount" value="{u.get('discount', 0)}" placeholder="Disc%" style="width:120px; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff; font-size:16px;">
                <button type="submit" class="action-btn btn-success" style="padding:15px 25px; font-size:16px; width:auto;">Update User</button>
            </form>
        </div>

        <h3 style="color:#38bdf8; font-size:22px; margin-bottom:15px;">📜 Transaction History ({len(orders)})</h3>
        {history_html if history_html else '<p style="color:#94a3b8; text-align:center;">No transactions for this user yet.</p>'}
        
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
            "prices": price_dict, "status": "active"
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
            <input type="text" name="duration[]" value="{d}" style="flex:1; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">
            <input type="number" name="price[]" value="{pr}" style="flex:1; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <a href="/admin" class="store-btn">🔙 Back</a>
    </div>
    <div class="container fade-in" style="margin-top:20px;">
        <div class="product-card" style="border-color:#f59e0b;">
            <h3 style="margin-bottom:20px; color:#f59e0b; font-size:26px;">✏️ Edit Product</h3>
            <form method="POST" enctype="multipart/form-data">
                <div class="input-group"><label>Product Name</label><input type="text" name="name" value="{p.get('name', '')}" required></div>
                <div class="input-group"><label>PID</label><input type="text" name="pid" value="{p.get('pid', '')}" required></div>
                
                <div class="input-group"><label>Banner Image (Leave empty to keep old)</label><input type="file" name="image_file" accept="image/*" style="padding:15px; background:#050810; border:2px solid #334155; border-radius:12px;"></div>
                
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
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;"><input type="number" name="price[]" placeholder="Price" style="flex:1; padding:15px; border-radius:12px; background:#050810; border:2px solid #334155; color:#fff;">`;
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
