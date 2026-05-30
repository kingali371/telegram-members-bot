"""
Telegram Members Transfer Bot - نسخة Render مع متغيرات بيئية وأزرار تفاعلية
بوت لنقل وإدارة أعضاء مجموعات تيليجرام
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
from telethon.tl.types import KeyboardButtonCallback, KeyboardButtonUrl
from telethon.tl.custom import Button

# ==================== 🔑 قراءة المتغيرات البيئية ====================
API_ID = int(os.environ.get('API_ID', 0))
API_HASH = os.environ.get('API_HASH', '')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')

# إعدادات الحماية
MIN_WAIT = int(os.environ.get('MIN_WAIT', 180))
MAX_WAIT = int(os.environ.get('MAX_WAIT', 300))
MAX_ADD_PER_DAY = int(os.environ.get('MAX_ADD_PER_DAY', 20))

# إعدادات الملفات
LOG_FILE = "data/add_log.txt"
SESSION_FILE = "data/bot_session"
ACCOUNTS_FILE = "data/accounts.json"
os.makedirs("data", exist_ok=True)

# متغيرات عالمية
user_sessions = {}
bot = None
active_accounts = {}  # لتخزين الحسابات المتعددة

# ==================== إعدادات Flask ====================
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "Bot is running",
        "message": "Telegram Members Transfer Bot"
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "bot_active": bot is not None
    })
# =========================================================

# ==================== دوال مساعدة ====================
def validate_settings():
    """التحقق من صحة المتغيرات"""
    if API_ID == 0:
        print("❌ API_ID غير موجود!")
        return False
    if not API_HASH:
        print("❌ API_HASH غير موجود!")
        return False
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN غير موجود!")
        return False
    print("✅ جميع الإعدادات صحيحة!")
    return True

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

# ==================== دوال إدارة الحسابات ====================
async def add_account(event):
    """إضافة حساب جديد للبوت"""
    user_id = event.sender_id
    await event.reply(""+
        "➕ **إضافة حساب جديد**\n\n"+
        "الرجاء إدخال معلومات الحساب بالشكل التالي:\n"+
        "`رقم_الهاتف|api_id|api_hash`\n\n"+
        "مثال:\n`+1234567890|123456|abc123def456...`\n\n"+
        "⚠️ سيتم حفظ الحساب بشكل آمن واستخدامه في نقل الأعضاء",
        buttons=[
            [Button.inline("❌ إلغاء", b"cancel_account")],
            [Button.url("📖 كيفية الحصول على API", "https://my.telegram.org/apps")]
        ]
    )
    user_sessions[user_id] = {'action': 'add_account', 'step': 'waiting_for_account_info'}

async def transfer_members_start(event):
    """بدء عملية نقل الأعضاء بين الحسابات"""
    user_id = event.sender_id
    if not active_accounts:
        await event.reply(""+
            "❌ **لا توجد حسابات نشطة!**\n\n"+
            "الرجاء إضافة حساب أولاً باستخدام زر ➕ إضافة حساب",
            buttons=[[Button.inline("➕ إضافة حساب", b"add_account")]]
        )
        return
    
    # عرض قائمة الحسابات المتاحة
    accounts_list = list(active_accounts.keys())
    message = "🔄 **نقل الأعضاء بين الحسابات**\n\n"
    message += "**اختر الحساب المصدر (المنقول منه):**\n\n"
    
    buttons = []
    for i, acc in enumerate(accounts_list[:10]):
        buttons.append([Button.inline(f"📱 {acc[:20]}...", f"source_acc_{i}".encode())])
    
    await event.reply(message, buttons=buttons)
    user_sessions[user_id] = {'action': 'transfer_members', 'step': 'waiting_for_source_account', 'accounts': accounts_list}

async def show_accounts(event):
    """عرض قائمة الحسابات النشطة"""
    if not active_accounts:
        await event.reply(""+
            "📭 **لا توجد حسابات نشطة**\n\n"+
            "استخدم زر ➕ إضافة حساب لإضافة حساب جديد",
            buttons=[[Button.inline("➕ إضافة حساب", b"add_account")]]
        )
        return
    
    message = "📱 **الحسابات النشطة:**\n\n"
    for i, (phone, acc_info) in enumerate(active_accounts.items(), 1):
        status = "✅ نشط" if acc_info.get('connected') else "❌ غير متصل"
        message += f"{i}. `{phone}`\n   {status}\n\n"
    
    message += f"\n📊 **عدد الحسابات:** {len(active_accounts)}"
    
    await event.reply(message, buttons=[
        [Button.inline("➕ إضافة حساب", b"add_account")],
        [Button.inline("❌ حذف حساب", b"remove_account")]
    ])

# ==================== دوال البوت الرئيسية ====================
async def start(event):
    keyboard = [
        [
            Button.inline("➕ إضافة حساب", b"add_account"),
            Button.inline("🔄 نقل أعضاء", b"transfer_members")
        ],
        [
            Button.inline("📊 حالة الحسابات", b"show_accounts"),
            Button.inline("📁 سحب أعضاء", b"scrape_members")
        ],
        [
            Button.inline("➕ إضافة أعضاء", b"add_members"),
            Button.inline("📋 المجموعات", b"list_groups")
        ],
        [
            Button.inline("📈 الحالة اليومية", b"daily_status"),
            Button.inline("❓ المساعدة", b"help_menu")
        ]
    ]
    
    await event.reply("""
🤖 **مرحباً بك في بوت نقل أعضاء تيليجرام!**

📌 **الأزرار المتاحة:**

➕ **إضافة حساب** - إضافة حساب جديد للبوت
🔄 **نقل أعضاء** - نقل أعضاء بين الحسابات
📁 **سحب أعضاء** - سحب أعضاء من مجموعة
➕ **إضافة أعضاء** - إضافة أعضاء إلى مجموعة
📋 **المجموعات** - عرض قائمة المجموعات
📈 **الحالة اليومية** - عرض حالة الإضافات
❓ **المساعدة** - عرض الأوامر المتاحة

⚠️ **تنبيه:** استخدم البوت بمسؤولية وتجنب الإغراق!
    """, buttons=keyboard)

async def help_menu(event):
    await start(event)

async def daily_status(event):
    can_add, remaining = can_add_today()
    if can_add:
        await event.reply(f"📊 **حالة اليوم:**\n✅ يمكنك إضافة {remaining} مستخدم اليوم\n📈 الحد الأقصى: {MAX_ADD_PER_DAY}")
    else:
        await event.reply(f"❌ **تم الوصول للحد اليومي!**\n📊 الحد الأقصى: {MAX_ADD_PER_DAY}\n⏰ انتظر حتى الغد.")

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

async def scrape_members_start(event):
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

async def add_members_start(event):
    user_id = event.sender_id
    can_add, remaining = can_add_today()
    if not can_add:
        await event.reply(f"❌ **لا يمكنك الإضافة اليوم!**\nتم الوصول للحد الأقصى ({MAX_ADD_PER_DAY})")
        return
    await event.reply(f"✅ يمكنك إضافة {remaining} مستخدم اليوم\n\n🔄 **بدء عملية الإضافة...**\n\nالرجاء إرسال ملف CSV الذي يحتوي على الأعضاء")
    user_sessions[user_id] = {'action': 'add', 'step': 'waiting_for_file', 'remaining': remaining}

async def cancel_cmd(event):
    user_id = event.sender_id
    if user_id in user_sessions:
        del user_sessions[user_id]
    await event.reply("✅ **تم إلغاء العملية الحالية.**")

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

# ==================== معالجة الأزرار ====================
async def handle_callback(event):
    """معالجة النقر على الأزرار"""
    data = event.data.decode('utf-8')
    
    if data == "add_account":
        await add_account(event)
    elif data == "transfer_members":
        await transfer_members_start(event)
    elif data == "show_accounts":
        await show_accounts(event)
    elif data == "scrape_members":
        await scrape_members_start(event)
    elif data == "add_members":
        await add_members_start(event)
    elif data == "list_groups":
        await list_groups(event)
    elif data == "daily_status":
        await daily_status(event)
    elif data == "help_menu":
        await help_menu(event)
    elif data == "cancel_account":
        if event.sender_id in user_sessions:
            del user_sessions[event.sender_id]
        await event.edit("✅ **تم إلغاء إضافة الحساب**")
    elif data.startswith("source_acc_"):
        # معالجة اختيار الحساب المصدر
        await handle_source_account_selection(event)
    elif data.startswith("target_acc_"):
        # معالجة اختيار الحساب الهدف
        await handle_target_account_selection(event)

async def handle_source_account_selection(event):
    """معالجة اختيار الحساب المصدر لنقل الأعضاء"""
    user_id = event.sender_id
    if user_id not in user_sessions or user_sessions[user_id].get('action') != 'transfer_members':
        return
    
    data = event.data.decode('utf-8')
    index = int(data.split('_')[2])
    accounts = user_sessions[user_id]['accounts']
    source_account = accounts[index]
    
    user_sessions[user_id]['source_account'] = source_account
    user_sessions[user_id]['step'] = 'waiting_for_target_account'
    
    # عرض الحسابات الهدف
    accounts_list = list(active_accounts.keys())
    message = f"✅ **تم اختيار الحساب المصدر:** {source_account[:20]}...\n\n"
    message += "**اختر الحساب الهدف (المنقول إليه):**\n\n"
    
    buttons = []
    for i, acc in enumerate(accounts_list):
        if acc != source_account:
            buttons.append([Button.inline(f"📱 {acc[:20]}...", f"target_acc_{i}".encode())])
    
    if not buttons:
        await event.edit("❌ **لا توجد حسابات هدف متاحة!**")
        return
    
    await event.edit(message, buttons=buttons)

async def handle_target_account_selection(event):
    """معالجة اختيار الحساب الهدف لنقل الأعضاء"""
    user_id = event.sender_id
    if user_id not in user_sessions or user_sessions[user_id].get('action') != 'transfer_members':
        return
    
    data = event.data.decode('utf-8')
    index = int(data.split('_')[2])
    accounts = user_sessions[user_id]['accounts']
    target_account = accounts[index]
    source_account = user_sessions[user_id]['source_account']
    
    await event.edit(f"""
✅ **تم تحديد الحسابات:**
📤 **المصدر:** {source_account[:20]}...
📥 **الهدف:** {target_account[:20]}...

🔄 **جاري بدء عملية نقل الأعضاء...**
    """)
    
    # هنا يمكن إضافة منطق نقل الأعضاء الفعلي بين الحسابات
    await event.reply("🚧 **هذه الميزة قيد التطوير...**\nسيتم إضافة منطق نقل الأعضاء قريباً!")
    
    del user_sessions[user_id]

# ==================== تشغيل البوت ====================
async def run_bot():
    """تشغيل البوت وتسجيل الأوامر"""
    global bot
    
    # تهيئة البوت
    bot = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    
    # تسجيل الأوامر والأحداث
    bot.add_event_handler(start, events.NewMessage(pattern='/start'))
    bot.add_event_handler(help_menu, events.NewMessage(pattern='/help'))
    bot.add_event_handler(daily_status, events.NewMessage(pattern='/status'))
    bot.add_event_handler(list_groups, events.NewMessage(pattern='/groups'))
    bot.add_event_handler(scrape_members_start, events.NewMessage(pattern='/scrape'))
    bot.add_event_handler(add_members_start, events.NewMessage(pattern='/add'))
    bot.add_event_handler(cancel_cmd, events.NewMessage(pattern='/cancel'))
    bot.add_event_handler(handle_file, events.NewMessage(func=lambda e: e.file and e.file.name and e.file.name.endswith(('.csv', '.txt'))))
    bot.add_event_handler(handle_number_selection, events.NewMessage(func=lambda e: e.text and e.text.strip().isdigit()))
    bot.add_event_handler(handle_add_count, events.NewMessage(func=lambda e: e.text and e.text.strip().isdigit()))
    bot.add_event_handler(handle_callback, events.CallbackQuery())
    
    print("✅ Bot client started successfully!")
    print("🤖 البوت يعمل الآن مع الأزرار التفاعلية...")
    
    await bot.run_until_disconnected()

def start_bot_thread():
    """تشغيل البوت في thread منفصل"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())

# ==================== التشغيل الرئيسي ====================
if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════╗
    ║   🤖 Telegram Members Transfer Bot    ║
    ║   بوت نقل أعضاء تيليجرام مع أزرار    ║
    ╚═══════════════════════════════════════╝
    """)
    
    # التحقق من صحة المتغيرات
    if not validate_settings():
        print("\n❌ لا يمكن تشغيل البوت بسبب أخطاء في المتغيرات!")
        print("📝 يرجى إضافة المتغيرات التالية في لوحة تحكم Render:")
        print("   - API_ID")
        print("   - API_HASH")
        print("   - BOT_TOKEN")
        exit(1)
    
    print("🔄 جاري تشغيل البوت...")
    
    # تشغيل البوت في thread منفصل
    bot_thread = threading.Thread(target=start_bot_thread)
    bot_thread.daemon = True
    bot_thread.start()
    
    # تشغيل Flask server
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 تشغيل Flask server على المنفذ {port}...")
    print("="*50)
    app.run(host="0.0.0.0", port=port)
