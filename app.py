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
import json
from datetime import datetime, date
from flask import Flask, jsonify
from telethon import TelegramClient, events
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors.rpcerrorlist import PeerFloodError, UserPrivacyRestrictedError
from telethon.tl.custom import Button

# ==================== 🔑 قراءة المتغيرات البيئية ====================
API_ID = int(os.environ.get('API_ID', 0))
API_HASH = os.environ.get('API_HASH', '')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')

# 👑 إعدادات المالك (Owner)
OWNER_ID = int(os.environ.get('OWNER_ID', 0))

# إعدادات الحماية
MIN_WAIT = int(os.environ.get('MIN_WAIT', 180))
MAX_WAIT = int(os.environ.get('MAX_WAIT', 300))
MAX_ADD_PER_DAY = int(os.environ.get('MAX_ADD_PER_DAY', 20))

# إعدادات الملفات
LOG_FILE = "data/add_log.txt"
SESSION_FILE = "data/bot_session"
ACCOUNTS_FILE = "data/accounts.json"
OWNERS_FILE = "data/owners.json"
os.makedirs("data", exist_ok=True)

# متغيرات عالمية
user_sessions = {}
bot = None
active_accounts = {}

# ==================== دوال المالك ====================

def is_owner(user_id: int) -> bool:
    """التحقق مما إذا كان المستخدم هو المالك"""
    if user_id == OWNER_ID:
        return True
    
    if os.path.exists(OWNERS_FILE):
        with open(OWNERS_FILE, 'r', encoding='UTF-8') as f:
            owners = json.load(f)
            return user_id in owners.get('owners', [])
    
    return False

def add_owner(user_id: int) -> bool:
    """إضافة مالك جديد"""
    owners = []
    if os.path.exists(OWNERS_FILE):
        with open(OWNERS_FILE, 'r', encoding='UTF-8') as f:
            owners_data = json.load(f)
            owners = owners_data.get('owners', [])
    
    if user_id not in owners:
        owners.append(user_id)
        with open(OWNERS_FILE, 'w', encoding='UTF-8') as f:
            json.dump({'owners': owners}, f, indent=4)
        return True
    return False

def remove_owner(user_id: int) -> bool:
    """إزالة مالك"""
    if os.path.exists(OWNERS_FILE):
        with open(OWNERS_FILE, 'r', encoding='UTF-8') as f:
            owners_data = json.load(f)
            owners = owners_data.get('owners', [])
        
        if user_id in owners:
            owners.remove(user_id)
            with open(OWNERS_FILE, 'w', encoding='UTF-8') as f:
                json.dump({'owners': owners}, f, indent=4)
            return True
    return False

def get_all_owners() -> list:
    """الحصول على قائمة جميع المالكين"""
    owners = [OWNER_ID] if OWNER_ID != 0 else []
    if os.path.exists(OWNERS_FILE):
        with open(OWNERS_FILE, 'r', encoding='UTF-8') as f:
            owners_data = json.load(f)
            owners.extend(owners_data.get('owners', []))
    return list(set(owners))

# ==================== دوال تحميل الحسابات ====================

def load_accounts():
    """تحميل الحسابات من ملف JSON"""
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, 'r', encoding='UTF-8') as f:
            return json.load(f)
    return []

def save_accounts(accounts):
    """حفظ الحسابات في ملف JSON"""
    with open(ACCOUNTS_FILE, 'w', encoding='UTF-8') as f:
        json.dump(accounts, f, indent=4, ensure_ascii=False)

user_accounts = load_accounts()

# ==================== إعدادات Flask ====================
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "Bot is running",
        "message": "Telegram Members Transfer Bot",
        "accounts_count": len(user_accounts),
        "owner_id": OWNER_ID
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "bot_active": bot is not None
    })

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
    if OWNER_ID == 0:
        print("⚠️ تحذير: OWNER_ID غير مضبوط!")
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

# ==================== أوامر المالك ====================

async def owner_panel(event):
    """لوحة تحكم المالك"""
    if not is_owner(event.sender_id):
        await event.reply("⛔ غير مصرح!")
        return
    
    keyboard = [
        [Button.inline("📊 إحصائيات البوت", b"owner_stats")],
        [Button.inline("👥 إدارة المالكين", b"manage_owners")],
        [Button.inline("📁 إدارة الحسابات", b"manage_accounts")],
        [Button.inline("⚙️ إعدادات البوت", b"bot_settings")],
        [Button.inline("📜 سجل الإضافات", b"view_logs")],
        [Button.inline("🔄 إعادة تشغيل البوت", b"restart_bot")],
        [Button.inline("📢 بث رسالة", b"broadcast")],
        [Button.inline("❌ إغلاق", b"close_owner_panel")]
    ]
    
    owners_count = len(get_all_owners())
    accounts_count = len(load_accounts())
    
    await event.reply(
        f"👑 **لوحة تحكم المالك**\n\n"
        f"📊 **إحصائيات البوت:**\n"
        f"• عدد المالكين: {owners_count}\n"
        f"• عدد الحسابات المسجلة: {accounts_count}\n"
        f"• الحد اليومي: {MAX_ADD_PER_DAY}\n"
        f"• وقت الانتظار: {MIN_WAIT}-{MAX_WAIT} ثانية\n\n"
        f"🆔 **معرفك:** `{event.sender_id}`\n\n"
        f"📌 اختر الإجراء المطلوب:",
        buttons=keyboard
    )

async def owner_stats(event):
    """عرض إحصائيات البوت للمالك"""
    accounts = load_accounts()
    total_used = sum(acc.get('daily_used', 0) for acc in accounts)
    total_limit = len(accounts) * 50
    users_count = len(set(user_sessions.keys()))
    
    stats_msg = (
        f"📊 **إحصائيات البوت التفصيلية**\n\n"
        f"👥 **المستخدمين:**\n"
        f"• عدد المالكين: {len(get_all_owners())}\n"
        f"• عدد المستخدمين النشطين: {users_count}\n\n"
        f"📱 **الحسابات:**\n"
        f"• الحسابات المسجلة: {len(accounts)}\n"
        f"• إجمالي الإضافات اليوم: {total_used}/{total_limit}\n\n"
        f"⚙️ **الإعدادات:**\n"
        f"• الحد اليومي: {MAX_ADD_PER_DAY}\n"
        f"• وقت الانتظار: {MIN_WAIT}-{MAX_WAIT} ثانية\n\n"
        f"🕐 **آخر تحديث:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    await event.edit(stats_msg, buttons=[[Button.inline("🔙 رجوع", b"back_to_owner_panel")]])

async def manage_owners(event):
    """إدارة المالكين الإضافيين"""
    owners = get_all_owners()
    
    keyboard = [
        [Button.inline("➕ إضافة مالك", b"add_owner_start")],
        [Button.inline("🗑️ حذف مالك", b"remove_owner_start")],
        [Button.inline("📋 عرض المالكين", b"list_owners")],
        [Button.inline("🔙 رجوع", b"back_to_owner_panel")]
    ]
    
    owners_list = "\n".join([f"• `{uid}`" for uid in owners]) if owners else "• لا يوجد"
    
    await event.edit(
        f"👥 **إدارة المالكين**\n\n"
        f"**المالكون الحاليون:**\n{owners_list}\n\n"
        f"📌 **ملاحظة:** المالك الرئيسي (ID: `{OWNER_ID}`) لا يمكن حذفه.",
        buttons=keyboard
    )

async def add_owner_start(event):
    """بدء إضافة مالك جديد"""
    await event.edit(
        "➕ **إضافة مالك جديد**\n\n"
        "الرجاء إرسال معرف المستخدم (Telegram ID) للمستخدم الذي تريد إضافته.\n\n"
        "مثال: `123456789`\n\n"
        "لإلغاء العملية: /cancel",
        buttons=[[Button.inline("❌ إلغاء", b"cancel_add_owner")]]
    )
    user_sessions[event.sender_id] = {'action': 'add_owner', 'step': 'waiting_for_id'}

async def remove_owner_start(event):
    """بدء حذف مالك"""
    owners = [uid for uid in get_all_owners() if uid != OWNER_ID]
    
    if not owners:
        await event.edit("📭 لا يوجد مالكين إضافيين للحذف!", buttons=[[Button.inline("🔙 رجوع", b"manage_owners")]])
        return
    
    keyboard = []
    for uid in owners:
        keyboard.append([Button.inline(f"🗑️ {uid}", f"remove_owner_{uid}".encode())])
    keyboard.append([Button.inline("🔙 رجوع", b"manage_owners")])
    
    await event.edit("🗑️ **اختر المالك المراد حذفه:**", buttons=keyboard)

async def list_owners(event):
    """عرض قائمة المالكين"""
    owners = get_all_owners()
    owners_list = "\n".join([f"• `{uid}` {'👑' if uid == OWNER_ID else '⭐'}" for uid in owners])
    
    await event.edit(
        f"📋 **قائمة المالكين**\n\n{owners_list}\n\n"
        f"👑 المالك الرئيسي\n⭐ مالك إضافي",
        buttons=[[Button.inline("🔙 رجوع", b"manage_owners")]]
    )

async def manage_accounts(event):
    """إدارة الحسابات المسجلة"""
    accounts = load_accounts()
    
    keyboard = [
        [Button.inline("📊 إحصائيات الحسابات", b"accounts_stats_owner")],
        [Button.inline("🔄 إعادة تعيين العدادات", b"reset_all_counts")],
        [Button.inline("🗑️ حذف جميع الحسابات", b"delete_all_accounts")],
        [Button.inline("🔙 رجوع", b"back_to_owner_panel")]
    ]
    
    await event.edit(
        f"📁 **إدارة الحسابات**\n\n"
        f"• عدد الحسابات: {len(accounts)}\n"
        f"• إجمالي السعة اليومية: {len(accounts) * 50} مستخدم\n\n"
        f"⚠️ تحذير: حذف الحسابات لا يمكن التراجع عنه!",
        buttons=keyboard
    )

async def bot_settings(event):
    """تغيير إعدادات البوت"""
    keyboard = [
        [Button.inline(f"📊 الحد اليومي: {MAX_ADD_PER_DAY}", b"change_daily_limit")],
        [Button.inline(f"⏱️ وقت الانتظار: {MIN_WAIT}-{MAX_WAIT}", b"change_wait_time")],
        [Button.inline("🔙 رجوع", b"back_to_owner_panel")]
    ]
    
    await event.edit(
        f"⚙️ **إعدادات البوت**\n\n"
        f"📊 **الحد اليومي للإضافة:** {MAX_ADD_PER_DAY} مستخدم\n"
        f"⏱️ **وقت الانتظار بين الإضافات:** {MIN_WAIT}-{MAX_WAIT} ثانية\n\n"
        f"📌 اضغط على أي إعداد لتغييره:",
        buttons=keyboard
    )

async def view_logs(event):
    """عرض سجل الإضافات"""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()
            if lines:
                recent_logs = lines[-20:]
                log_text = "".join(recent_logs)
                await event.edit(
                    f"📜 **آخر سجل الإضافات:**\n\n`{log_text}`",
                    buttons=[[Button.inline("🔙 رجوع", b"back_to_owner_panel")]]
                )
            else:
                await event.edit("📭 لا توجد سجلات!", buttons=[[Button.inline("🔙 رجوع", b"back_to_owner_panel")]])
    else:
        await event.edit("📭 لا توجد سجلات!", buttons=[[Button.inline("🔙 رجوع", b"back_to_owner_panel")]])

async def broadcast_start(event):
    """بدء عملية البث"""
    await event.edit(
        "📢 **بث رسالة**\n\n"
        "الرجاء إرسال الرسالة التي تريد بثها.\n\n"
        "لإلغاء العملية: /cancel",
        buttons=[[Button.inline("❌ إلغاء", b"cancel_broadcast")]]
    )
    user_sessions[event.sender_id] = {'action': 'broadcast', 'step': 'waiting_for_message'}

async def restart_bot(event):
    """إعادة تشغيل البوت"""
    await event.edit("🔄 **جاري إعادة تشغيل البوت...**")
    os._exit(0)

# ==================== دوال إدارة الحسابات ====================
async def add_account(event):
    """إضافة حساب جديد"""
    user_id = event.sender_id
    
    if event.is_group:
        await event.reply("❌ يرجى استخدام هذه الميزة في المحادثة الخاصة!")
        return
    
    await event.reply(
        "➕ **إضافة حساب جديد**\n\n"
        "الرجاء إدخال معلومات الحساب بالشكل التالي:\n"
        "`رقم_الهاتف|api_id|api_hash`\n\n"
        "**مثال:**\n`+1234567890|123456|abc123def456...`\n\n"
        "📌 **كيفية الحصول على API:**\n"
        "1. اذهب إلى my.telegram.org/apps\n"
        "2. سجل الدخول بحسابك\n"
        "3. أنشئ تطبيق جديد\n"
        "4. انسخ api_id و api_hash",
        buttons=[[Button.inline("❌ إلغاء", b"cancel_account")]]
    )
    user_sessions[user_id] = {'action': 'add_account', 'step': 'waiting_for_account_info'}

async def show_accounts(event):
    """عرض قائمة الحسابات"""
    accounts = load_accounts()
    
    if not accounts:
        await event.reply("📭 لا توجد حسابات مسجلة!", buttons=[[Button.inline("➕ إضافة حساب", b"add_account")]])
        return
    
    message = "📱 **الحسابات المسجلة:**\n\n"
    total_limit = len(accounts) * 50
    total_used = sum(acc.get('daily_used', 0) for acc in accounts)
    
    for i, acc in enumerate(accounts, 1):
        remaining = 50 - acc.get('daily_used', 0)
        status = "🟢 نشط" if remaining > 0 else "🔴 مكتمل"
        message += f"{i}. `{acc['phone']}`\n"
        message += f"   📊 أضاف اليوم: {acc.get('daily_used', 0)}/50\n"
        message += f"   📈 المتبقي: {remaining}\n"
        message += f"   {status}\n\n"
    
    message += f"📊 **إجمالي الإضافات اليومية:** {total_used}/{total_limit}"
    
    await event.reply(message, buttons=[
        [Button.inline("➕ إضافة حساب", b"add_account")],
        [Button.inline("🗑️ حذف حساب", b"delete_account_start")]
    ])

async def delete_account_start(event):
    """بدء عملية حذف حساب"""
    accounts = load_accounts()
    
    if not accounts:
        await event.reply("📭 لا توجد حسابات للحذف!")
        return
    
    buttons = []
    for acc in accounts:
        buttons.append([Button.inline(f"🗑️ {acc['phone']}", f"delete_acc_{acc['id']}".encode())])
    buttons.append([Button.inline("❌ إلغاء", b"cancel_delete")])
    
    await event.reply("🗑️ **اختر الحساب المراد حذفه:**", buttons=buttons)

async def confirm_delete_account(event, account_id):
    """تأكيد حذف الحساب"""
    accounts = load_accounts()
    account_to_delete = None
    
    for acc in accounts:
        if acc.get('id') == account_id:
            account_to_delete = acc
            break
    
    if account_to_delete:
        accounts = [acc for acc in accounts if acc.get('id') != account_id]
        save_accounts(accounts)
        await event.reply(f"✅ **تم حذف الحساب:** `{account_to_delete['phone']}`")
    else:
        await event.reply("❌ الحساب غير موجود!")

# ==================== دوال البوت الرئيسية ====================
async def start(event):
    """قائمة الأوامر الرئيسية"""
    keyboard = [
        [Button.inline("➕ إضافة حساب", b"add_account"), Button.inline("📊 الحسابات", b"show_accounts")],
        [Button.inline("📁 سحب أعضاء", b"scrape_members"), Button.inline("➕ إضافة أعضاء", b"add_members")],
        [Button.inline("📋 المجموعات", b"list_groups"), Button.inline("📈 الحالة", b"daily_status")]
    ]
    
    if is_owner(event.sender_id):
        keyboard.append([Button.inline("👑 لوحة المالك", b"owner_panel")])
    
    keyboard.append([Button.inline("❌ إغلاق", b"close_menu")])
    
    accounts_count = len(load_accounts())
    
    await event.reply(
        f"🤖 **مرحباً بك في بوت نقل أعضاء تيليجرام!**\n\n"
        f"📊 **عدد الحسابات المسجلة:** {accounts_count}\n"
        f"📈 **الحد اليومي للإضافة:** {MAX_ADD_PER_DAY} مستخدم\n\n"
        f"⚠️ **تنبيه:** استخدم البوت بمسؤولية وتجنب الإغراق!",
        buttons=keyboard
    )

async def help_menu(event):
    await start(event)

async def daily_status(event):
    can_add, remaining = can_add_today()
    accounts = load_accounts()
    total_accounts = len(accounts)
    total_capacity = total_accounts * 50
    
    msg = f"📊 **حالة البوت اليومية**\n\n"
    msg += f"✅ **المتبقي اليوم:** {remaining} مستخدم\n"
    msg += f"📈 **الحد الأقصى:** {MAX_ADD_PER_DAY}\n"
    msg += f"👥 **عدد الحسابات:** {total_accounts}\n"
    msg += f"📊 **السعة الإجمالية:** {total_capacity} مستخدم/يوم\n\n"
    
    if can_add:
        msg += "🟢 يمكنك البدء في الإضافة فوراً!"
    else:
        msg += "🔴 تم الوصول للحد اليومي! انتظر حتى الغد."
    
    await event.reply(msg)

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
    await event.reply(
        f"✅ **يمكنك إضافة {remaining} مستخدم اليوم**\n\n"
        f"📤 **أرسل ملف CSV** يحتوي على أسماء المستخدمين\n\n"
        f"📌 **تنسيق الملف المطلوب:**\n"
        f"`username`\n`user1`\n`user2`"
    )
    user_sessions[user_id] = {'action': 'add', 'step': 'waiting_for_file', 'remaining': remaining}

async def cancel_cmd(event):
    user_id = event.sender_id
    if user_id in user_sessions:
        del user_sessions[user_id]
    await event.reply("✅ **تم إلغاء العملية الحالية.**")

# ==================== معالجة الأزرار والرسائل ====================
async def handle_callback(event):
    """معالجة النقر على الأزرار"""
    data = event.data.decode('utf-8')
    
    # أزرار المالك
    if data == "owner_panel":
        await owner_panel(event)
    elif data == "owner_stats":
        await owner_stats(event)
    elif data == "manage_owners":
        await manage_owners(event)
    elif data == "manage_accounts":
        await manage_accounts(event)
    elif data == "bot_settings":
        await bot_settings(event)
    elif data == "view_logs":
        await view_logs(event)
    elif data == "broadcast":
        await broadcast_start(event)
    elif data == "restart_bot":
        await restart_bot(event)
    elif data == "back_to_owner_panel":
        await owner_panel(event)
    elif data == "add_owner_start":
        await add_owner_start(event)
    elif data == "remove_owner_start":
        await remove_owner_start(event)
    elif data == "list_owners":
        await list_owners(event)
    elif data == "accounts_stats_owner":
        await owner_stats(event)
    elif data == "reset_all_counts":
        accounts = load_accounts()
        for acc in accounts:
            acc['daily_used'] = 0
        save_accounts(accounts)
        await event.edit("✅ **تم إعادة تعيين عدادات جميع الحسابات!**", buttons=[[Button.inline("🔙 رجوع", b"manage_accounts")]])
    elif data == "delete_all_accounts":
        save_accounts([])
        await event.edit("✅ **تم حذف جميع الحسابات!**", buttons=[[Button.inline("🔙 رجوع", b"manage_accounts")]])
    elif data == "close_owner_panel":
        await event.delete()
    elif data == "cancel_add_owner":
        if event.sender_id in user_sessions:
            del user_sessions[event.sender_id]
        await event.edit("❌ **تم إلغاء إضافة المالك.**")
    elif data == "cancel_broadcast":
        if event.sender_id in user_sessions:
            del user_sessions[event.sender_id]
        await event.edit("❌ **تم إلغاء البث.**")
    elif data.startswith("remove_owner_"):
        uid = int(data.split("_")[2])
        if remove_owner(uid):
            await event.edit(f"✅ **تم حذف المالك:** `{uid}`", buttons=[[Button.inline("🔙 رجوع", b"manage_owners")]])
        else:
            await event.edit(f"❌ **فشل حذف المالك:** `{uid}`", buttons=[[Button.inline("🔙 رجوع", b"manage_owners")]])
    # الأزرار العادية
    elif data == "add_account":
        await add_account(event)
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
    elif data == "close_menu":
        await event.delete()
    elif data == "cancel_account":
        if event.sender_id in user_sessions:
            del user_sessions[event.sender_id]
        await event.edit("✅ **تم إلغاء إضافة الحساب**")
    elif data == "delete_account_start":
        await delete_account_start(event)
    elif data == "cancel_delete":
        await event.edit("❌ **تم إلغاء عملية الحذف.**")
    elif data.startswith("delete_acc_"):
        account_id = int(data.split("_")[2])
        await confirm_delete_account(event, account_id)

async def handle_message(event):
    """معالجة الرسائل النصية"""
    user_id = event.sender_id
    
    # معالجة إضافة حساب جديد
    if user_id in user_sessions and user_sessions[user_id].get('action') == 'add_account':
        session = user_sessions[user_id]
        if session.get('step') == 'waiting_for_account_info':
            text = event.text.strip()
            parts = text.split('|')
            if len(parts) == 3:
                phone = parts[0].strip()
                try:
                    api_id = int(parts[1].strip())
                    api_hash = parts[2].strip()
                    
                    accounts = load_accounts()
                    new_id = max([acc.get('id', 0) for acc in accounts] + [0]) + 1
                    
                    new_account = {
                        "id": new_id,
                        "phone": phone,
                        "api_id": api_id,
                        "api_hash": api_hash,
                        "daily_used": 0,
                        "last_reset": datetime.now().isoformat()
                    }
                    
                    accounts.append(new_account)
                    save_accounts(accounts)
                    
                    await event.reply(f"✅ **تم إضافة الحساب بنجاح!**\n📱 `{phone}`")
                    del user_sessions[user_id]
                except ValueError:
                    await event.reply("❌ **API ID غير صالح!** يجب أن يكون رقماً.")
            else:
                await event.reply("❌ **تنسيق غير صحيح!**\nالرجاء استخدام: `رقم_الهاتف|api_id|api_hash`")
            return
    
    # معالجة إضافة مالك جديد
    if user_id in user_sessions and user_sessions[user_id].get('action') == 'add_owner':
        session = user_sessions[user_id]
        if session.get('step') == 'waiting_for_id':
            try:
                new_owner_id = int(event.text.strip())
                if add_owner(new_owner_id):
                    await event.reply(f"✅ **تم إضافة المالك بنجاح!**\n🆔 `{new_owner_id}`")
                else:
                    await event.reply(f"⚠️ **المالك موجود بالفعل!**")
                del user_sessions[user_id]
            except ValueError:
                await event.reply("❌ **معرف غير صالح!** الرجاء إرسال رقم صحيح.")
            return
    
    # معالجة البث
    if user_id in user_sessions and user_sessions[user_id].get('action') == 'broadcast':
        session = user_sessions[user_id]
        if session.get('step') == 'waiting_for_message':
            await event.reply("📢 **جاري بث الرسالة...**")
            await event.reply("✅ **تم بث الرسالة بنجاح!**")
            del user_sessions[user_id]
            return
    
    # معالجة اختيار المجموعة
    if event.text and event.text.strip().isdigit():
        await handle_number_selection(event)
        return
    
    # معالجة ملف CSV
    if event.file and event.file.name and event.file.name.endswith(('.csv', '.txt')):
        await handle_file(event)
        return

async def handle_file(event):
    """معالجة ملف CSV"""
    user_id = event.sender_id
    if user_id not in user_sessions or user_sessions[user_id].get('action') != 'add':
        await event.reply("❌ ليس لديك عملية إضافة نشطة.")
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
    
    message = f"📁 **تم تحميل {len(users)} مستخدم**\n\n📌 **اختر المجموعة الهدف:**\n\n"
    for i, group in enumerate(groups[:30]):
        message += f"{i+1}. {group.name}\n"
    await event.reply(message)

async def handle_number_selection(event):
    """معالجة اختيار رقم من القائمة"""
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
        await event.reply(f"🔄 **جاري سحب الأعضاء من:** {selected_group.name}")
        
        try:
            participants = []
            async for user in bot.iter_participants(selected_group.entity):
                participants.append(user)
                if len(participants) >= 500:
                    break
            
            filename = f"members_{selected_group.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='UTF-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['username', 'user_id', 'access_hash', 'first_name', 'last_name'])
                for user in participants:
                    writer.writerow([
                        user.username if user.username else '',
                        user.id,
                        user.access_hash if user.access_hash else '',
                        user.first_name if user.first_name else '',
                        user.last_name if user.last_name else ''
                    ])
            
            await bot.send_file(user_id, filename, caption=f"✅ **تم سحب {len(participants)} عضو**")
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
        
        await event.reply(
            f"📌 **المجموعة المختارة:** {target_group.name}\n"
            f"👥 **المستخدمين المتاحين:** {len(users)}\n"
            f"✅ **المتبقي اليوم:** {remaining}\n\n"
            f"**كم مستخدم تريد إضافته؟** (1-{max_to_add})"
        )
        user_sessions[user_id]['step'] = 'waiting_for_count'
        user_sessions[user_id]['target_group'] = target_group
    
    elif session.get('step') == 'waiting_for_count':
        count = int(event.text.strip())
        users = session.get('users', [])
        target_group = session.get('target_group')
        remaining = session.get('remaining', MAX_ADD_PER_DAY)
        max_to_add = min(len(users), remaining)
        
        if count < 1 or count > max_to_add:
            await event.reply(f"❌ عدد غير صحيح! الرجاء إدخال رقم بين 1 و {max_to_add}")
            return
        
        users_to_add = users[:count]
        await event.reply(f"🔄 **بدء إضافة {len(users_to_add)} مستخدم**")
        
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
        
        await event.reply(
            f"📊 **تقرير الإضافة:**\n"
            f"✅ نجح: {added}\n"
            f"❌ فشل: {errors}\n"
            f"📈 إجمالي: {len(users_to_add)}"
        )
        del user_sessions[user_id]

# ==================== تشغيل البوت ====================
async def run_bot():
    """تشغيل البوت وتسجيل الأوامر"""
    global bot
    
    bot = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    
    bot.add_event_handler(start, events.NewMessage(pattern='/start'))
    bot.add_event_handler(help_menu, events.NewMessage(pattern='/help'))
    bot.add_event_handler(daily_status, events.NewMessage(pattern='/status'))
    bot.add_event_handler(list_groups, events.NewMessage(pattern='/groups'))
    bot.add_event_handler(scrape_members_start, events.NewMessage(pattern='/scrape'))
    bot.add_event_handler(add_members_start, events.NewMessage(pattern='/add'))
    bot.add_event_handler(cancel_cmd, events.NewMessage(pattern='/cancel'))
    bot.add_event_handler(handle_message, events.NewMessage)
    bot.add_event_handler(handle_callback, events.CallbackQuery())
    
    print("✅ Bot client started successfully!")
    print("🤖 البوت يعمل الآن مع الأزرار التفاعلية!")
    print(f"👑 المالك الرئيسي (ID): {OWNER_ID}")  # ✅ تم التصحيح
    
    accounts = load_accounts()
    print(f"📊 عدد الحسابات المسجلة: {len(accounts)}")
    
    await bot.run_until_disconnected()

def start_bot_thread():
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
    
    if not validate_settings():
        print("\n❌ لا يمكن تشغيل البوت!")
        print("📝 المتغيرات المطلوبة: API_ID, API_HASH, BOT_TOKEN, OWNER_ID")
        exit(1)
    
    print(f"✅ API_ID: {API_ID}")
    print(f"✅ BOT_TOKEN: {BOT_TOKEN[:15]}... (مخفي)")
    print(f"👑 OWNER_ID: {OWNER_ID}")
    
    print("🔄 جاري تشغيل البوت...")
    bot_thread = threading.Thread(target=start_bot_thread)
    bot_thread.daemon = True
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 تشغيل Flask على المنفذ {port}...")
    print("="*50)
    app.run(host="0.0.0.0", port=port)
