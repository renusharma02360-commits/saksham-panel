import os
import time
import threading
import requests
import telebot
from functools import wraps
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, ReplyKeyboardRemove, ForceReply
from famgateway import FamGateway
from flask import Flask, request, render_template_string, redirect, url_for
from pymongo import MongoClient
from bson.objectid import ObjectId

# ================== CONFIG ==================
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
    
    try:
        if call.data == "bot_main":
            text, kb = get_main_menu(uid)
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)
            
        elif call.data == "bot_shop":
            categories = list(categories_col.find({}))
            if not categories:
                return bot.answer_callback_query(call.id, "❌ No categories added yet.", show_alert=True)
            
            text = "📁 <b>CHOOSE A CATEGORY</b>\n\n🔥 Premium Mods, Panels & Bypasses\n\n👇 <i>Tap a category below:</i>"
            kb = InlineKeyboardMarkup(row_width=1)
            for cat in categories:
                kb.add(InlineKeyboardButton(f"➡️ {cat.get('name').upper()}", callback_data=f"cat_{cat['_id']}"))
            kb.add(InlineKeyboardButton("⬅️ BACK", callback_data="bot_main"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif call.data.startswith("cat_"):
            cat_id = call.data.split("_")[1]
            cat = categories_col.find_one({"_id": ObjectId(cat_id)})
            
            products = list(products_col.find({"category_id": str(cat_id)}))
            
            if not products:
                return bot.answer_callback_query(call.id, f"❌ No products found in {cat.get('name')}.", show_alert=True)
            
            text = f"📁 <b>{cat.get('name', 'Category').upper()}</b>\n\n➡️ Choose a product 🕊️❤️"
            kb = InlineKeyboardMarkup(row_width=1)
            for p in products:
                icon = p.get('icon', '🔹')
                kb.add(InlineKeyboardButton(f"{icon} {p.get('name')}", callback_data=f"view_{p['_id']}"))
            kb.add(InlineKeyboardButton("⬅️ BACK", callback_data="bot_shop"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif call.data.startswith("view_"):
            p_id = call.data.split("_")[1]
            p = products_col.find_one({"_id": ObjectId(p_id)})
            u = get_user_info(uid)
            disc = u.get('discount', 0)
            
            features_text = p.get('features', '').replace('\n', '\n⚡ ') if p.get('features') else ''
            text = f"📁 <b>{p['name']}</b>\n\n⚡ {features_text}\n\n"
            
            kb = InlineKeyboardMarkup(row_width=2)
            
            update_link = str(p.get('setup_video', '')).strip()
            video_link = str(p.get('hack_video', '')).strip()
            
            if update_link.startswith('http'):
                kb.add(InlineKeyboardButton("📥 Update File", url=update_link))
                
            if video_link.startswith('http'):
                kb.add(InlineKeyboardButton("▶️ Video/Feedback", url=video_link))
            
            for d, pr in p.get('prices', {}).items():
                if not d.strip(): continue
                final_pr = float(pr) - (float(pr) * disc / 100) if disc > 0 else float(pr)
                kb.add(InlineKeyboardButton(f"⏱ {d} - ₹{final_pr:.2f}", callback_data=f"buy_{p_id}_{d}"))
                
            kb.add(InlineKeyboardButton("🔙 Back", callback_data=f"cat_{p.get('category_id')}"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)

        elif call.data.startswith("buy_"):
            parts = call.data.split("_")
            p_id = parts[1]
            duration = "_".join(parts[2:])
            
            p = products_col.find_one({"_id": ObjectId(p_id)})
            if not p:
                return bot.answer_callback_query(call.id, "❌ Product not found.", show_alert=True)
                
            u = get_user_info(uid)
            disc = u.get('discount', 0)
            
            if duration not in p.get('prices', {}):
                return bot.answer_callback_query(call.id, "❌ Invalid duration.", show_alert=True)
                
            base_price = float(p['prices'][duration])
            price = base_price - (base_price * disc / 100) if disc > 0 else base_price
            
            user_bal = get_balance(uid)
            
            if user_bal < price:
                return bot.answer_callback_query(call.id, f"❌ Low Balance!\n\nYour Balance: ₹{user_bal:.2f}\nRequired: ₹{price:.2f}\n\nPlease add funds using 'Add Amount'.", show_alert=True)
                
            bot.answer_callback_query(call.id)
            
            if deduct_balance(uid, price):
                bot.edit_message_text("⏳ <i>Processing your order from API...</i>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
                try:
                    data = {'api_key': RESELLER_API_KEY, 'action': 'buy', 'product_id': str(p.get("pid", "")).strip(), 'duration': str(duration).strip(), 'quantity': 1}
                    res = requests.post(RESELLER_API_URL, data=data, headers={'x-master-key': MASTER_KEY}, timeout=20)
                    result = res.json()
                except Exception as e: 
                    result = {"status": "error", "message": str(e)}
                    
                if result.get("status") == "success" or "keys" in result:
                    key = result.get("keys", ["Key not found"])[0]
                    log_order(uid, p['name'], key, price)
                    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back to Menu", callback_data="bot_main"))
                    bot.edit_message_text(f"✅ <b>PURCHASE SUCCESSFUL!</b>\n\n📦 Product: {p['name']}\n⏱ Duration: {duration}\n🔑 Key:\n<code>{key}</code>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
                else:
                    users_col.update_one({"_id": str(uid)}, {"$inc": {"balance": price}})
                    err_msg = result.get("message", "Out of Stock / API Error")
                    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="bot_shop"))
                    bot.edit_message_text(f"❌ <b>API Error</b>\n\nReason: {err_msg}\n\n₹{price:.2f} Refunded to your wallet.", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)

        elif call.data == "bot_profile":
            u = get_user_info(uid)
            text = f"👤 <b>YOUR PROFILE</b>\n\n🆔 ID: <code>{uid}</code>\n💰 Balance: ₹{u.get('balance', 0.0):.2f}\n🏷️ Discount: {u.get('discount', 0)}%\n📅 Joined: {u.get('joined', time.strftime('%d-%m-%Y'))}"
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("💸 Add Balance", callback_data="bot_add_bal"), InlineKeyboardButton("🔙 Back", callback_data="bot_main"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)
            
        elif call.data == "bot_history":
            orders = list(orders_col.find({"uid": uid}).sort("_id", -1))
            if not orders:
                return bot.answer_callback_query(call.id, "No orders found.", show_alert=True)
            
            text = "📜 <b>Your Order History</b>\n\n"
            for o in orders[:5]:
                text += f"📦 {o.get('product', 'Deposit')}\n🔑 <code>{o.get('key', 'N/A')}</code>\n📅 {o.get('time')}\n➖➖➖➖➖➖➖➖\n"
            
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back", callback_data="bot_main"))
            bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(call.id)
            
        elif call.data == "bot_add_bal":
            msg = bot.send_message(call.message.chat.id, "💸 <b>Enter Amount</b>\n\nPlease type the amount (in ₹) you want to add to your wallet (e.g., 50, 100):", parse_mode="HTML", reply_markup=ForceReply(selective=True))
            bot.register_next_step_handler(msg, process_deposit_amount)
            bot.answer_callback_query(call.id)

        # FIXED: Parsing using Pipe '|' instead of Underscore '_'
        elif call.data.startswith("check_dep|"):
            parts = call.data.split("|")
            order_id = parts[1]
            amount = float(parts[2])
            target_uid = parts[3]
            
            bot.answer_callback_query(call.id, "⏳ Checking status with gateway...")
            verify_payment_manually(call.message.chat.id, target_uid, order_id, amount)

    except Exception as e:
        error_msg = f"⚠️ <b>Bot Error Detected!</b>\n\nUser ID: <code>{uid}</code>\nButton: {call.data}\nError: <code>{str(e)}</code>"
        try: bot.send_message(ADMIN_ID, error_msg, parse_mode="HTML")
        except: pass

def process_deposit_amount(message):
    uid = str(message.from_user.id)
    try:
        amount = float(message.text)
        
        if amount <= 0:
            msg = bot.reply_to(message, "❌ Amount must be greater than 0. Please enter again:")
            bot.register_next_step_handler(msg, process_deposit_amount)
            return
        
        bot.send_message(message.chat.id, "⏳ <i>Generating QR Code...</i>", parse_mode="HTML")
        order = fg.create_order(amount=amount, customer_name=f"User_{uid}")
        
        caption = f"💳 <b>Pay ₹{amount}</b>\n\nScan the QR code above using any UPI app.\n\n<i>Bot is checking for payment in the background. Please wait...</i>"
        
        # FIXED: Using Pipe '|' here too
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 Check Payment Status", callback_data=f"check_dep|{order.order_id}|{amount}|{uid}"))
        bot.send_photo(message.chat.id, photo=order.qr_url, caption=caption, parse_mode="HTML", reply_markup=kb)
        
        threading.Thread(target=verify_chat_payment, args=(message.chat.id, uid, order.order_id, amount)).start()
        
    except ValueError:
        msg = bot.reply_to(message, "❌ Invalid amount. Please type numbers only (e.g., 50):")
        bot.register_next_step_handler(msg, process_deposit_amount)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error creating order. Please try again later.")
        try: bot.send_message(ADMIN_ID, f"Deposit Error: {str(e)}", parse_mode="HTML")
        except: pass

def verify_chat_payment(chat_id, uid, order_id, amount):
    for _ in range(200): 
        time.sleep(3)
        try:
            status = fg.get_status(order_id)
            if status.is_paid:
                ok, new_bal = credit_atomic(uid, amount, status.utr)
                bot.send_message(chat_id, f"✅ <b>Payment Successful!</b>\n\n₹{amount} has been added to your wallet.\n💰 New Balance: ₹{new_bal:.2f}", parse_mode="HTML")
                return
        except Exception as e: 
            print(f"API Check Error: {e}")
    
    bot.send_message(chat_id, "⚠️ Auto-check session expired. If you paid, please click 'Check Payment Status' button or contact support.")

def verify_payment_manually(chat_id, uid, order_id, amount):
    try:
        status = fg.get_status(order_id)
        if status.is_paid:
            ok, new_bal = credit_atomic(uid, amount, status.utr)
            bot.send_message(chat_id, f"✅ <b>Payment Verified Manually!</b>\n\n₹{amount} has been added to your wallet.\n💰 New Balance: ₹{new_bal:.2f}", parse_mode="HTML")
        else:
            bot.send_message(chat_id, f"❌ Payment not received yet for Order ID: <code>{order_id}</code>.\n\nIf you just paid, please wait 1-2 minutes and try again.", parse_mode="HTML")
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Gateway Error: Could not fetch status. Please try again later.")
        try: bot.send_message(ADMIN_ID, f"Manual Check Error:\nOrder: {order_id}\nError: {str(e)}", parse_mode="HTML")
        except: pass


# ================== FLASK WEB APP (Admin Only) ==================
app = Flask(__name__)
app.secret_key = "sk_panel_secret"

BASE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800;900&display=swap');
    * { box-sizing: border-box; font-family: 'Poppins', sans-serif; margin: 0; padding: 0; }
    body { background-color: #050810; color: #fff; padding-bottom: 50px; }
    .container { padding: 20px; max-width: 800px; margin: 0 auto; }
    .top-nav { display: flex; justify-content: space-between; align-items: center; padding: 20px; background: #0f172a; border-bottom: 1px solid #334155; }
    .store-btn { background: #2563eb; padding: 12px 20px; border-radius: 15px; font-weight: 800; color: white; text-decoration: none; font-size: 14px; }
    .card { background: #0f172a; border-radius: 20px; padding: 25px; border: 1px solid #334155; margin-bottom: 20px; }
    input, textarea, select { width: 100%; padding: 15px; border-radius: 12px; border: 2px solid #334155; background: #050810; color: #fff; font-size: 16px; outline: none; margin-bottom: 15px; }
    label { display: block; font-size: 14px; color: #94a3b8; margin-bottom: 8px; font-weight: 600; }
    .btn { display: block; width: 100%; padding: 18px; border-radius: 12px; text-align: center; font-weight: 900; font-size: 16px; border: none; cursor: pointer; text-decoration: none; color: white; }
    .btn-primary { background: #2563eb; }
    .btn-success { background: #10b981; }
    .btn-danger { background: #ef4444; }
    .btn-warning { background: #f59e0b; color: black; }
    .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px; }
    .stat-card { background: #0f172a; border-radius: 15px; padding: 20px; border: 1px solid #334155; text-align: center; }
    .stat-title { font-size: 12px; color: #94a3b8; }
    .stat-value { font-size: 24px; font-weight: 900; color: #38bdf8; }
</style>
"""

@app.route('/admin')
def admin_panel():
    total_users = users_col.count_documents({})
    total_products = products_col.count_documents({})
    
    products = list(products_col.find({}))
    prod_html = ""
    for p in products:
        cat = categories_col.find_one({"_id": ObjectId(p.get('category_id'))}) if p.get('category_id') else None
        cat_name = cat.get('name') if cat else "No Category"
        prod_html += f"""
        <div class="card" style="display:flex; justify-content:space-between; align-items:center; padding:15px;">
            <div>
                <div style="font-size:18px; font-weight:900; color:#38bdf8;">{p.get('icon', '🔹')} {p.get('name', '')}</div>
                <div style="font-size:12px; color:#f59e0b;">Category: {cat_name}</div>
            </div>
            <div style="display:flex; gap:5px;">
                <a href="/edit_product/{p['_id']}" class="btn btn-warning" style="padding:8px 12px; font-size:12px; width:auto;">Edit</a>
                <form action="/delete_product/{p['_id']}" method="POST">
                    <button type="submit" class="btn btn-danger" style="padding:8px 12px; font-size:12px; width:auto;">Del</button>
                </form>
            </div>
        </div>
        """

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:20px;">⚙️ Admin Panel</div>
        <div style="display:flex; gap:10px;">
            <a href="/admin_deposits" class="store-btn" style="background:#8b5cf6;">💰 Deposits</a>
            <a href="/admin_users" class="store-btn" style="background:#f59e0b; color:#000;">👥 Users</a>
            <a href="/admin_categories" class="store-btn" style="background:#10b981;">📁 Categories</a>
        </div>
    </div>
    <div class="container" style="margin-top:20px;">
        <div class="stats-grid">
            <div class="stat-card"><div class="stat-title">Total Users</div><div class="stat-value">{total_users}</div></div>
            <div class="stat-card"><div class="stat-title">Total Products</div><div class="stat-value">{total_products}</div></div>
        </div>

        <div class="card" style="border-color:#38bdf8;">
            <h3 style="margin-bottom:15px; color:#38bdf8;">➕ Add Product</h3>
            <form method="POST" action="/add_product">
                <label>Name</label><input type="text" name="name" required>
                <label>Icon (Emoji)</label><input type="text" name="icon" placeholder="🔹" required>
                <label>PID</label><input type="text" name="pid" required>
                <label>Category</label>
                <select name="category_id" required>
                    <option value="">-- Select --</option>
                    {''.join([f'<option value="{c["_id"]}">{c["name"]}</option>' for c in categories_col.find({})])}
                </select>
                <label>Features</label><textarea name="features" rows="2"></textarea>
                <label>Update Link (Full URL)</label><input type="text" name="setup_video" placeholder="https://...">
                <label>Video Link (Full URL)</label><input type="text" name="hack_video" placeholder="https://...">
                
                <label style="margin-top:15px; color:#38bdf8;">Durations & Price</label>
                <div id="price-container">
                    <div style="display:flex; gap:10px; margin-bottom:10px;">
                        <input type="text" name="duration[]" placeholder="e.g. 1 Day" style="flex:1;">
                        <input type="number" name="price[]" placeholder="Price (₹)" style="flex:1;">
                    </div>
                </div>
                <button type="button" onclick="addPrice()" class="btn btn-success" style="margin-bottom:15px;">+ Add More</button>
                <button type="submit" class="btn btn-primary">Save Product</button>
            </form>
        </div>

        <h3 style="margin-bottom:15px;">📦 All Products</h3>
        {prod_html}
    </div>
    <script>
        function addPrice() {{
            const c = document.getElementById('price-container');
            const d = document.createElement('div');
            d.style.display = 'flex'; d.style.gap = '10px'; d.style.marginBottom = '10px';
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1;"><input type="number" name="price[]" placeholder="Price (₹)" style="flex:1;">`;
            c.appendChild(d);
        }}
    </script>
    """)

@app.route('/admin_deposits')
def admin_deposits():
    deposits = list(orders_col.find({"type": "deposit"}).sort("_id", -1))
    dep_html = ""
    for d in deposits:
        user = users_col.find_one({"_id": d['uid']})
        uname = user.get('name', 'User') if user else d['uid']
        
        dep_html += f"""
        <div class="card" style="padding:15px; border-left: 4px solid #10b981;">
            <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
                <span style="font-weight:bold; color:#38bdf8;">{uname}</span>
                <span style="color:#10b981; font-weight:900;">+₹{d.get('amount')}</span>
            </div>
            <div style="font-size:12px; color:#94a3b8;">ID: <code>{d.get('uid')}</code></div>
            <div style="font-size:12px; color:#94a3b8;">UTR: {d.get('utr', 'N/A')}</div>
            <div style="font-size:12px; color:#f59e0b;">Time: {d.get('time')}</div>
        </div>
        """
        
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav">
        <div style="font-weight:900; font-size:20px; color:#8b5cf6;">💰 All Deposits</div>
        <a href="/admin" class="store-btn">🔙 Back</a>
    </div>
    <div class="container" style="margin-top:20px;">
        {dep_html if dep_html else '<h3 style="text-align:center; color:#94a3b8;">No deposits found yet.</h3>'}
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
    cat_html = "".join([f"""
        <div class="card" style="display:flex; justify-content:space-between; align-items:center; padding:15px;">
            <div style="font-size:18px; font-weight:900; color:#10b981;">📁 {c['name']}</div>
            <form action="/delete_category/{c['_id']}" method="POST">
                <button type="submit" class="btn btn-danger" style="padding:8px 12px; font-size:12px; width:auto;">Del</button>
            </form>
        </div>
    """ for c in categories])

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><div style="font-weight:900; font-size:20px; color:#10b981;">📁 Categories</div><a href="/admin" class="store-btn">🔙 Back</a></div>
    <div class="container" style="margin-top:20px;">
        <div class="card" style="border-color:#10b981;">
            <form method="POST">
                <label>Category Name</label>
                <input type="text" name="cat_name" placeholder="e.g. Android Root" required>
                <button type="submit" class="btn btn-success">Add Category</button>
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
        cat_id = str(request.form.get('category_id'))
        durs = request.form.getlist('duration[]')
        prices = request.form.getlist('price[]')
        price_dict = {d.strip(): float(p.strip()) for d, p in zip(durs, prices) if d.strip() and p.strip()}
        
        products_col.insert_one({
            "name": request.form['name'], 
            "icon": request.form.get('icon', '🔹'),
            "pid": request.form['pid'], 
            "category_id": cat_id,
            "features": request.form.get('features', ''), 
            "setup_video": request.form.get('setup_video', '').strip(), 
            "hack_video": request.form.get('hack_video', '').strip(), 
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
                "setup_video": request.form.get('setup_video', '').strip(), 
                "hack_video": request.form.get('hack_video', '').strip(), 
                "prices": price_dict
            }})
            return redirect(url_for('admin_panel'))
        except Exception as e: 
            return f"Error: {e}"

    price_fields = "".join([f"""
        <div style="display:flex; gap:10px; margin-bottom:10px;">
            <input type="text" name="duration[]" value="{d}" style="flex:1;">
            <input type="number" name="price[]" value="{pr}" style="flex:1;">
        </div>
    """ for d, pr in p.get('prices', {}).items()])
        
    categories = list(categories_col.find({}))
    cat_options = "".join([f'<option value="{c["_id"]}" {"selected" if str(c["_id"]) == p.get("category_id") else ""}>{c["name"]}</option>' for c in categories])

    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><a href="/admin" class="store-btn">🔙 Back</a></div>
    <div class="container" style="margin-top:20px;">
        <div class="card">
            <h3 style="margin-bottom:15px; color:#f59e0b;">✏️ Edit Product</h3>
            <form method="POST">
                <label>Name</label><input type="text" name="name" value="{p.get('name', '')}" required>
                <label>Icon</label><input type="text" name="icon" value="{p.get('icon', '🔹')}" required>
                <label>PID</label><input type="text" name="pid" value="{p.get('pid', '')}" required>
                <label>Category</label><select name="category_id">{cat_options}</select>
                <label>Features</label><textarea name="features" rows="2">{p.get('features', '')}</textarea>
                <label>Update Link</label><input type="text" name="setup_video" value="{p.get('setup_video', '')}">
                <label>Video Link</label><input type="text" name="hack_video" value="{p.get('hack_video', '')}">
                <label style="margin-top:15px; color:#38bdf8;">Durations & Price</label>
                <div id="price-container">{price_fields}</div>
                <button type="button" onclick="addPrice()" class="btn btn-success" style="margin-bottom:15px;">+ Add More</button>
                <button type="submit" class="btn btn-warning">Update</button>
            </form>
        </div>
    </div>
    <script>
        function addPrice() {{
            const c = document.getElementById('price-container');
            const d = document.createElement('div');
            d.style.display = 'flex'; d.style.gap = '10px'; d.style.marginBottom = '10px';
            d.innerHTML = `<input type="text" name="duration[]" placeholder="Duration" style="flex:1;"><input type="number" name="price[]" placeholder="Price (₹)" style="flex:1;">`;
            c.appendChild(d);
        }}
    </script>
    """)

@app.route('/delete_product/<p_id>', methods=['POST'])
def delete_product(p_id):
    products_col.delete_one({"_id": ObjectId(p_id)})
    return redirect(url_for('admin_panel'))

@app.route('/admin_users')
def admin_users():
    users = list(users_col.find({}))
    user_html = "".join([f"""
        <div class="card" style="display:flex; justify-content:space-between; align-items:center; padding:15px;">
            <div>
                <div style="font-size:16px; font-weight:900; color:#38bdf8;">{u.get('name', 'User')}</div>
                <div style="font-size:12px; color:#94a3b8;"><code>{u['_id']}</code></div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:18px; font-weight:900; color:#10b981;">₹{u.get('balance', 0):.2f}</div>
                <a href="/admin_edit_user/{u['_id']}" class="btn btn-warning" style="padding:6px 10px; font-size:10px; width:auto; margin-top:5px;">Edit</a>
            </div>
        </div>
    """ for u in users])
    return render_template_string(BASE_CSS + f"""
    <div class="top-nav"><div style="font-weight:900; font-size:20px; color:#f59e0b;">👥 Users</div><a href="/admin" class="store-btn">🔙 Back</a></div>
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
    <div class="top-nav"><div style="font-weight:900; font-size:20px; color:#f59e0b;">Edit User</div><a href="/admin_users" class="store-btn">🔙 Back</a></div>
    <div class="container" style="margin-top:20px;">
        <div class="card">
            <form method="POST">
                <label>Balance (₹)</label><input type="number" step="0.01" name="balance" value="{u.get('balance', 0)}" required>
                <label>Discount (%)</label><input type="number" name="discount" value="{u.get('discount', 0)}" required>
                <button type="submit" class="btn btn-warning">Update</button>
            </form>
        </div>
    </div>
    """)

@app.route('/')
def home(): return redirect(url_for('admin_panel'))

# ================== RUNNING ==================
if __name__ == "__main__":
    threading.Thread(target=lambda: bot.infinity_polling(timeout=30, long_polling_timeout=30), daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
