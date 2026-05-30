"""
Telegram Members Transfer Bot - نسخة Render
بوت لنقل وإدارة أعضاء مجموعات تيليجرام مع دعم Flask server
"""

import asyncio
import csv
import os
import random
import re
import threading
from datetime import datetime, date
from flask import Flask, request, jsonify
from telethon import TelegramClient, events
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors.rpcerrorlist import PeerFloodError, UserPrivacyRestrictedError

# ==================== 🔑 إعدادات البوت ====================
# 🚨 هام: ضع القيم الصحيحة هنا قبل الرفع على Render
API_ID = 12345678                    # ⬅️ ضع API ID الخاص بك
API_HASH = 'ضع_api_hash_هنا'          # ⬅️ ضع API Hash
BOT_TOKEN = 'ضع_توكن_البوت_هنا'        # ⬅️ ضع توكن البوت

# إعدادات الحماية
MIN_WAIT = 180      # أقل وقت بين الإضافات
MAX_WAIT = 300      # أقصى وقت بين الإضافات
MAX_ADD_PER_DAY = 20  # الحد الأقصى للإضافات في اليوم
# =========================================================

# ==================== إعدادات Flask ====================
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "Bot is running", "message": "Telegram Members Transfer Bot"})

@app.route('/health')
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})
# =========================================================

# إعدادات الملفات
LOG_FILE = "data/add_log.txt"
SESSION_FILE = "data/bot_session"
os.makedirs("data", exist_ok=True)

# متغيرات عالمية
user_sessions = {}
bot = None
bot_thread = None

def can_add_today():
    """التحقق من الحد اليومي"""
    today = date.today()
    if not os.path.exists(LOG_FILE):
        return True, MAX_ADD_PER_DAY
    
    with open(LOG_FILE, 'r') as f:
        lines = f.readlines()
        if lines:
            last_date_str, count_str = lines[-1].strip().split(',')
            last_date = datetime.strptime(last_date_str, '%Y-%m-%d').date()
            count = int(count_str)
            if last_date == today:
                remaining = MAX_ADD_PER_DAY - count
                if remaining <= 0:
                    return False, 0
                return True, remaining
    return True, MAX_ADD_PER_DAY

def log_add():
    """تسجيل إضافة جديدة"""
    today = date.today()
    counts = {}
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            for line in f:
                d, c = line.strip().split(',')
                counts[d] = int(c)
    counts[today.isoformat()] = counts.get(today.isoformat(), 0) + 1
    with open(LOG_FILE, 'w') as f:
        for d, c in counts.items():
            f.write(f"{d},{c}\n")

def random_wait():
    return random.randint(MIN_WAIT, MAX_WAIT)

# ========== أوامر البوت ==========
@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.reply("""
🤖 **مرحباً بك في بوت نقل أعضاء تيليجرام!**

📋 **الأوامر المتاحة:**

🔹 `/scrape` - سحب أعضاء من مجموعة وحفظهم
🔹 `/add` - إضافة أعضاء من ملف إلى مجموعة
🔹 `/groups` - عرض قائمة المجموعات
🔹 `/status` - عرض حالة الإضافات اليومية
🔹 `/cancel` - إلغاء العملية الحالية
🔹 `/help` - عرض هذه المساعدة

⚠️ **تحذير:** استخدم البوت بمسؤولية!
    """)

@bot.on(events.NewMessage(pattern='/help'))
async def help_cmd(event):
    await start(event)

@bot.on(events.NewMessage(pattern='/status'))
async def status_cmd(event):
    can_add, remaining = can_add_today()
    if can_add:
        await event.reply(f"📊 **حالة اليوم:**\n✅ يمكنك إضافة {remaining} مستخدم اليوم\n📈 الحد الأقصى: {MAX_ADD_PER_DAY}")
    else:
        await event.reply(f"❌ **تم الوصول للحد اليومي!**\n📊 الحد الأقصى: {MAX_ADD_PER_DAY}\n⏰ انتظر حتى الغد.")

@bot.on(events.NewMessage(pattern='/groups'))
async def list_groups(event):
    await event.reply("🔄 **جاري تحميل قائمة المجموعات...**")
    groups = []
    async for dialog in bot.iter_dialogs():
        if dialog.is_group or dialog.is_channel:
            groups.append(dialog)
    if not groups:
        await event.reply("❌ لا توجد مجموعات في حسابك!")
        return
    message = "📁 **قائمة مجموعاتك:**\n\n"
    for i, group in enumerate(groups[:50]):
        message += f"{i+1}. {group.name}\n"
    await event.reply(message)

@bot.on(events.NewMessage(pattern='/scrape'))
async def scrape_start(event):
    user_id = event.sender_id
    await event.reply("🔄 **بدء عملية سحب الأعضاء...**")
    groups = []
    async for dialog in bot.iter_dialogs():
        if dialog.is_group or dialog.is_channel:
            groups.append(dialog)
    if not groups:
        await event.reply("❌ لا توجد مجموعات في حسابك!")
        return
    user_sessions[user_id] = {'action': 'scrape_select_group', 'groups': groups, 'step': 'waiting_for_group'}
    message = "📁 **اختر رقم المجموعة:**\n\n"
    for i, group in enumerate(groups[:30]):
        message += f"{i+1}. {group.name}\n"
    await event.reply(message)

@bot.on(events.NewMessage(pattern='/add'))
async def add_start(event):
    user_id = event.sender_id
    can_add, remaining = can_add_today()
    if not can_add:
        await event.reply(f"❌ **لا يمكنك الإضافة اليوم!**\nتم الوصول للحد الأقصى ({MAX_ADD_PER_DAY})")
        return
    await event.reply(f"✅ يمكنك إضافة {remaining} مستخدم اليوم\n\n🔄 **بدء عملية الإضافة...**\n\nالرجاء إرسال ملف CSV الذي يحتوي على الأعضاء")
    user_sessions[user_id] = {'action': 'add', 'step': 'waiting_for_file', 'remaining': remaining}

@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_cmd(event):
    user_id = event.sender_id
    if user_id in user_sessions:
        del user_sessions[user_id]
    await event.reply("✅ **تم إلغاء العملية الحالية.**")

@bot.on(events.NewMessage(func=lambda e: e.file and e.file.name and e.file.name.endswith(('.csv', '.txt'))))
async def handle_file(event):
    user_id = event.sender_id
    if user_id not in user_sessions or user_sessions[user_id].get('action') != 'add':
        await event.reply("❌ ليس لديك عملية إضافة نشطة. استخدم /add أولاً")
        return
    file_path = await event.download_media()
    users = []
    try:
        with open(file_path, 'r', encoding='UTF-8') as f:
            content = f.read()
            lines = content.strip().split('\n')
            start_idx = 1 if lines[0].startswith('username') else 0
            for line in lines[start_idx:]:
                parts = line.split(',')
                if parts[0].strip():
                    users.append({'username': parts[0].strip()})
    except Exception as e:
        await event.reply(f"❌ خطأ في قراءة الملف: {str(e)}")
        os.remove(file_path)
        return
    os.remove(file_path)
    if not users:
        await event.reply("❌ لم يتم العثور على مستخدمين في الملف!")
        return
    user_sessions[user_id]['users'] = users
    user_sessions[user_id]['step'] = 'waiting_for_group_add'
    groups = []
    async for dialog in bot.iter_dialogs():
        if dialog.is_group or dialog.is_channel:
            groups.append(dialog)
    user_sessions[user_id]['groups'] = groups
    message = f"📁 **تم تحميل {len(users)} مستخدم من الملف**\n\n📌 **اختر المجموعة الهدف:**\n\n"
    for i, group in enumerate(groups[:30]):
        message += f"{i+1}. {group.name}\n"
    await event.reply(message)

@bot.on(events.NewMessage(func=lambda e: e.text and e.text.strip().isdigit()))
async def handle_number_selection(event):
    user_id = event.sender_id
    if user_id not in user_sessions:
        return
    session = user_sessions[user_id]
    choice = int(event.text.strip()) - 1
    if session.get('action') == 'scrape_select_group':
        if choice < 0 or choice >= len(session.get('groups', [])):
            await event.reply("❌ اختيار غير صحيح!")
            return
        selected_group = session['groups'][choice]
        await event.reply(f"🔄 **جاري سحب الأعضاء من:** {selected_group.name}\n⏳ قد يستغرق هذا دقائق...")
        try:
            participants = []
            async for user in bot.iter_participants(selected_group.entity):
                participants.append(user)
            filename = f"members_{selected_group.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='UTF-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['username', 'user_id', 'access_hash', 'first_name', 'last_name'])
                for user in participants:
                    writer.writerow([user.username if user.username else '', user.id, user.access_hash if user.access_hash else '', user.first_name if user.first_name else '', user.last_name if user.last_name else ''])
            await bot.send_file(user_id, filename, caption=f"✅ **تم سحب {len(participants)} عضو من {selected_group.name}**")
            os.remove(filename)
        except Exception as e:
            await event.reply(f"❌ خطأ: {str(e)}")
        del user_sessions[user_id]
    elif session.get('step') == 'waiting_for_group_add':
        if choice < 0 or choice >= len(session.get('groups', [])):
            await event.reply("❌ اختيار غير صحيح!")
            return
        target_group = session['groups'][choice]
        users = session.get('users', [])
        remaining = session.get('remaining', MAX_ADD_PER_DAY)
        max_to_add = min(len(users), remaining)
        await event.reply(f"📌 **المجموعة المختارة:** {target_group.name}\n👥 **المستخدمين المتاحين:** {len(users)}\n✅ **المتبقي اليوم:** {remaining}\n\nكم مستخدم تريد إضافته؟ (1-{max_to_add})")
        user_sessions[user_id]['step'] = 'waiting_for_count'
        user_sessions[user_id]['target_group'] = target_group

@bot.on(events.NewMessage(func=lambda e: e.text and e.text.strip().isdigit()))
async def handle_add_count(event):
    user_id = event.sender_id
    if user_id not in user_sessions or user_sessions[user_id].get('step') != 'waiting_for_count':
        return
    session = user_sessions[user_id]
    count = int(event.text.strip())
    users = session.get('users', [])
    target_group = session.get('target_group')
    remaining = session.get('remaining', MAX_ADD_PER_DAY)
    if count < 1 or count > min(len(users), remaining):
        await event.reply(f"❌ عدد غير صحيح!")
        return
    users_to_add = users[:count]
    await event.reply(f"🔄 **بدء إضافة {len(users_to_add)} مستخدم**\n⏳ سيتم الانتظار بين كل إضافة...")
    added = 0
    errors = 0
    for i, user in enumerate(users_to_add):
        try:
            if user['username']:
                try:
                    entity = await bot.get_input_entity(user['username'])
                    await bot(InviteToChannelRequest(target_group.entity, [entity]))
                    added += 1
                    log_add()
                    await event.reply(f"✅ {i+1}/{len(users_to_add)}: تمت إضافة {user['username']}")
                except Exception as e:
                    await event.reply(f"⚠️ {i+1}/{len(users_to_add)}: فشل {user['username']}")
                    errors += 1
            else:
                errors += 1
            if i < len(users_to_add) - 1:
                wait_time = random_wait()
                minutes = wait_time // 60
                seconds = wait_time % 60
                await event.reply(f"⏳ انتظار {minutes} دقيقة و {seconds} ثانية...")
                await asyncio.sleep(wait_time)
        except PeerFloodError:
            await event.reply("❌ **خطأ Flood! تم حظرك مؤقتاً.**")
            break
        except Exception as e:
            errors += 1
            continue
    await event.reply(f"📊 **تقرير الإضافة:**\n✅ نجح: {added}\n❌ فشل: {errors}\n📈 إجمالي: {len(users_to_add)}")
    del user_sessions[user_id]

async def run_bot():
    """تشغيل البوت"""
    global bot
    bot = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    print("✅ Bot client started successfully!")
    await bot.run_until_disconnected()

def start_bot_thread():
    """تشغيل البوت في thread منفصل"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════╗
    ║   🤖 Telegram Members Transfer Bot    ║
    ║   بوت نقل أعضاء تيليجرام              ║
    ╚═══════════════════════════════════════╝
    """)
    print("🔄 جاري تشغيل البوت...")
    
    # تشغيل البوت في thread منفصل
    bot_thread = threading.Thread(target=start_bot_thread)
    bot_thread.daemon = True
    bot_thread.start()
    
    # تشغيل Flask server
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port)
