"""
مثال لملف الإعدادات
انسخ هذا الملف إلى config.py وقم بتعديل القيم
"""

# إعدادات API تيليجرام (من my.telegram.org)
API_ID = 123456  # ضع الـ API ID الخاص بك
API_HASH = 'your_api_hash_here'  # ضع الـ API Hash

# توكن البوت (من @BotFather)
BOT_TOKEN = 'your_bot_token_here'

# إعدادات الحماية
MIN_WAIT = 180      # أقل وقت بين الإضافات (ثواني)
MAX_WAIT = 300      # أقصى وقت بين الإضافات (ثواني)
MAX_ADD_PER_DAY = 20  # الحد الأقصى للإضافات في اليوم
