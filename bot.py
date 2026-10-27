import asyncio
import random
import secrets
import aiohttp
import time
import os
import shutil
import logging
from datetime import datetime, timedelta, timezone
import sys
from aiohttp import web

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- FIX FOR ANDROID (PYDROID 3 & TERMUX) DNS ERROR ---
import dns.resolver
dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
dns.resolver.default_resolver.nameservers = ["8.8.8.8", "8.8.4.4", "1.1.1.1"]

try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from pyrogram import Client, utils, filters, StopPropagation, idle
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from pyrogram.errors import UserNotParticipant, FloodWait, PeerIdInvalid
from motor.motor_asyncio import AsyncIOMotorClient

# ==================== PYROGRAM PEER ID BUG MONKEY PATCH ====================
def get_peer_type_new(peer_id: int) -> str:
    peer_id_str = str(peer_id)
    if not peer_id_str.startswith("-"):
        return "user"
    elif peer_id_str.startswith("-100"):
        return "channel"
    else:
        return "chat"

utils.get_peer_type = get_peer_type_new
# ============================================================================

# ==================== CONFIGURATION ====================
API_ID = int(os.environ.get("API_ID", "27479878"))
API_HASH = os.environ.get("API_HASH", "05f8dc8265d4c5df6376dded1d71c0ff")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8898529611:AAFG-W2NG8rOMVfwyTRLcCYGbizDf5nCfDU")

OWNER_ID = int(os.environ.get("OWNER_ID", "6804892450"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1004351084760"))
DB_CHANNEL = int(os.environ.get("DB_CHANNEL", "-1004310513644"))

FSUB_CHANNELS = [-1004418968985, -1004362209221, -1004350772381]
FSUB_LINKS = {
    -1004418968985: "https://t.me/+hmElX1lHOb9iNTJl",
    -1004362209221: "https://t.me/+n-gCTKB9ZuAzNDM1",
    -1004350772381: "https://t.me/+auUb96ZUfh0yZDI1"
}

MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://usaomega1_db_user:Masdt2qYlJfXs20N@cluster0.zpedlcp.mongodb.net/?appName=Cluster0")
DB_NAME = os.environ.get("DB_NAME", "Cluster0")

SHORTENER_API = os.environ.get("SHORTENER_API", "f97c6e815c1d7bcaeca0660b5ae0064f5b6c2973")  
SHORTENER_DOMAIN = "vplink.in"
FALLBACK_SHORT_LINK = "https://vplink.in/WOODZ2"

QR_IMAGE_URL = "https://i.ibb.co/LDyTb5S9/Screenshot-20261027-124013-Nekogram.jpg"  
ADMIN_SUPPORT = "@Prettttyyyyyyyyyy"
PROMO_CHANNEL_URL = "https://t.me/telegram"

FREE_DAILY_LIMIT = 50
AUTO_DELETE_SECONDS = 300  

SPAM_MAX_HITS = 4
SPAM_WINDOW_SEC = 5
SPAM_BLOCK_DURATION = 300  

START_TIME = time.time()

# ==================== BULLETPROOF AUTO DELETE ====================
async def auto_delete_msg(client: Client, chat_id: int, message_id: int, delay: int = AUTO_DELETE_SECONDS):
    await asyncio.sleep(delay)
    try: 
        await client.delete_messages(chat_id=chat_id, message_ids=message_id)
    except Exception: 
        pass
# =================================================================

app = Client("Pookie69Bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client[DB_NAME]
users_col = db["users"]
videos_col = db["videos"]
orders_col = db["orders"]
sudo_col = db["sudoers"]
settings_col = db["settings"]

user_activity = {}
spam_blocked_until = {}
spam_notified = set()
pending_proofs = {}
pending_utr = {}
banned_users = set()  

video_cooldowns = {}
batch_cooldowns = {}
VIDEO_COOLDOWN_SEC = 15

idx_state = {
    "is_active": False,
    "start": 0,
    "end": 0,
    "current": 0,
    "added": 0,
    "skipped": 0
}

PLANS = {
    "1d": {"name": "1 DAY", "price": 9, "days": 1},
    "7d": {"name": "7 DAYS", "price": 24, "days": 7},
    "1m": {"name": "1 MONTH", "price": 60, "days": 30},
    "3m": {"name": "3 MONTHS", "price": 150, "days": 90},
    "6m": {"name": "6 MONTHS", "price": 270, "days": 180},
    "1y": {"name": "1 YEAR", "price": 480, "days": 365},
}

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("GET VIDEO 🍭"), KeyboardButton("BATCH 💋")],
        [KeyboardButton("PLAN STATUS 🏷"), KeyboardButton("BUY PREMIUM")],
        [KeyboardButton("REFER 👥"), KeyboardButton("SUPPORT 👨‍💻")]
    ],
    resize_keyboard=True
)

# ==================== DB HELPERS & SYSTEM INIT ====================
async def init_db():
    async for u in users_col.find({"is_banned": True}):
        banned_users.add(u["_id"])
    
    s = await settings_col.find_one({"_id": "global"})
    if not s:
        await settings_col.insert_one({"_id": "global", "maintenance": False, "premium_only": False})

async def get_user(user_id: int):
    user = await users_col.find_one({"_id": user_id})
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not user:
        user = {
            "_id": user_id, "referrals": 0, "ref_points": 0, "referred_by": None,
            "premium_expiry": None, "daily_count": 0, "last_reset": today_str,
            "verify_token": None, "joined_at": datetime.now(timezone.utc), "video_index": 0,
            "is_banned": False
        }
        await users_col.insert_one(user)
    else:
        updates = {}
        if user.get("last_reset") != today_str:
            updates["daily_count"] = 0
            updates["last_reset"] = today_str
            user["daily_count"] = 0
            user["last_reset"] = today_str
        if "video_index" not in user: updates["video_index"] = 0
        if updates: await users_col.update_one({"_id": user_id}, {"$set": updates})
    return user

async def is_premium(user_id: int) -> bool:
    if user_id == OWNER_ID: return True
    user = await get_user(user_id)
    exp = user.get("premium_expiry")
    if exp and isinstance(exp, datetime):
        if exp.tzinfo is None: exp = exp.replace(tzinfo=timezone.utc)
        return exp > datetime.now(timezone.utc)
    return False

async def add_premium(user_id: int, days: int):
    user = await get_user(user_id)
    now = datetime.now(timezone.utc)
    current_exp = user.get("premium_expiry")
    if current_exp and isinstance(current_exp, datetime):
        if current_exp.tzinfo is None: current_exp = current_exp.replace(tzinfo=timezone.utc)
        if current_exp > now: new_exp = current_exp + timedelta(days=days)
        else: new_exp = now + timedelta(days=days)
    else:
        new_exp = now + timedelta(days=days)
    await users_col.update_one({"_id": user_id}, {"$set": {"premium_expiry": new_exp}})
    return new_exp

# ==================== SUDO & ADMIN SYSTEM ====================
async def check_admin(uid: int, required_perm: str = None):
    if uid == OWNER_ID: return True
    sudo = await sudo_col.find_one({"_id": uid})
    if not sudo: return False
    if sudo.get("full"): return True
    if required_perm and not sudo.get(required_perm): return False
    return True

def build_sudo_kb(uid, perms):
    def b(val): return "✅" if val else "❌"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Read {b(perms.get('read'))}", callback_data=f"sperm_{uid}_read"),
         InlineKeyboardButton(f"Write {b(perms.get('write'))}", callback_data=f"sperm_{uid}_write")],
        [InlineKeyboardButton(f"Edit {b(perms.get('edit'))}", callback_data=f"sperm_{uid}_edit"),
         InlineKeyboardButton(f"Full {b(perms.get('full'))}", callback_data=f"sperm_{uid}_full")],
        [InlineKeyboardButton("🗑 Remove Sudo", callback_data=f"sperm_{uid}_remove")]
    ])

@app.on_message(filters.command("add_sudo") & filters.user(OWNER_ID))
async def add_sudo_cmd(client: Client, message: Message):
    if len(message.command) < 2: return await message.reply("Usage: `/add_sudo <user_id>`")
    try: uid = int(message.command[1])
    except: return await message.reply("❌ Invalid User ID")
    
    perms = {"_id": uid, "read": True, "write": False, "edit": False, "full": False}
    await sudo_col.update_one({"_id": uid}, {"$setOnInsert": perms}, upsert=True)
    current = await sudo_col.find_one({"_id": uid})
    
    await message.reply(f"👑 **Sudo Permissions for** `{uid}`", reply_markup=build_sudo_kb(uid, current))

@app.on_message(filters.command("remove_sudo") & filters.user(OWNER_ID))
async def remove_sudo_cmd(client: Client, message: Message):
    if len(message.command) < 2: return await message.reply("Usage: `/remove_sudo <user_id>`")
    try: uid = int(message.command[1])
    except: return await message.reply("❌ Invalid User ID")
    await sudo_col.delete_one({"_id": uid})
    await message.reply(f"✅ Removed `{uid}` from Sudoers.")

@app.on_callback_query(filters.regex("^sperm_"))
async def sudo_perm_cb(client: Client, query: CallbackQuery):
    if query.from_user.id != OWNER_ID: return await query.answer("Access Denied", show_alert=True)
    _, uid_str, action = query.data.split("_")
    uid = int(uid_str)
    
    if action == "remove":
        await sudo_col.delete_one({"_id": uid})
        return await query.edit_message_text(f"✅ Sudo removed for `{uid}`.")
        
    current = await sudo_col.find_one({"_id": uid})
    if not current: return await query.answer("User not in sudo list.", show_alert=True)
    
    new_val = not current.get(action, False)
    await sudo_col.update_one({"_id": uid}, {"$set": {action: new_val}})
    updated = await sudo_col.find_one({"_id": uid})
    
    await query.edit_message_reply_markup(reply_markup=build_sudo_kb(uid, updated))

# ==================== GLOBAL ACCESS GATES ====================
@app.on_message(filters.private, group=-2)
async def global_message_gate(client: Client, message: Message):
    if not message.from_user: return
    uid = message.from_user.id
    
    if uid in banned_users: raise StopPropagation
        
    if uid != OWNER_ID:
        now = time.time()
        if uid in spam_blocked_until:
            if now < spam_blocked_until[uid]: raise StopPropagation
            else:
                del spam_blocked_until[uid]
                spam_notified.discard(uid)
        hits = user_activity.get(uid, [])
        hits = [t for t in hits if now - t <= SPAM_WINDOW_SEC]
        hits.append(now)
        user_activity[uid] = hits
        if len(hits) > SPAM_MAX_HITS:
            spam_blocked_until[uid] = now + SPAM_BLOCK_DURATION
            user_activity[uid] = []
            spam_notified.add(uid)
            await message.reply(f"🚫 {message.from_user.mention}, **SPAM DETECTED!**\nYou are blocked for 5 minutes.")
            raise StopPropagation

    is_adm = await check_admin(uid)
    if not is_adm:
        settings = await settings_col.find_one({"_id": "global"}) or {}
        
        if settings.get("maintenance"):
            await message.reply("⚙️ **BOT IS UNDER MAINTENANCE**\n\nWe are currently updating the system. Please try again later!")
            raise StopPropagation
            
        if settings.get("premium_only"):
            if not await is_premium(uid):
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium (Instant)", callback_data="force_buy_menu")]])
                await message.reply("⚠️ **PREMIUM ONLY MODE ENABLED**\n\nThe bot is currently restricted to Premium members only due to high server load.", reply_markup=kb)
                raise StopPropagation

@app.on_callback_query(group=-2)
async def global_callback_gate(client: Client, query: CallbackQuery):
    if not query.from_user: return
    uid = query.from_user.id
    if uid in banned_users: raise StopPropagation
    
    if uid != OWNER_ID:
        now = time.time()
        if uid in spam_blocked_until and now < spam_blocked_until[uid]:
            await query.answer("🚫 SPAM DETECTED! Please wait.", show_alert=True)
            raise StopPropagation

    is_adm = await check_admin(uid)
    if not is_adm:
        settings = await settings_col.find_one({"_id": "global"}) or {}
        if settings.get("maintenance") or (settings.get("premium_only") and not await is_premium(uid)):
            await query.answer("Bot is restricted right now. See chat.", show_alert=True)
            raise StopPropagation

# ==================== HELP & ADMIN TOGGLES ====================
@app.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
    uid = message.from_user.id
    text = (
        "🤖 **BOT COMMANDS**\n\n"
        "🔹 `/start` - Start the bot & verify\n"
        "🔹 `PLAN STATUS 🏷` - Check premium status\n"
        "🔹 `GET VIDEO 🍭` - Fetch a new video\n"
        "🔹 `/find <id>` - Get specific video by Index ID\n"
        "🔹 `BATCH 💋` - Get 4 videos at once (Premium)\n"
        "🔹 `REFER 👥` - Get your referral link\n"
        "🔹 `BUY PREMIUM` - Purchase a plan\n\n"
    )
    
    if await check_admin(uid):
        text += (
            "👑 **ADMIN COMMANDS**\n\n"
            "🔸 `/add <uid> <days>` - Give premium\n"
            "🔸 `/remove <uid>` - Remove premium\n"
            "🔸 `/ban` / `/unban <uid>` - Ban controls\n"
            "🔸 `/unblock <uid>` - Remove spam block\n"
            "🔸 `/admin` or `/stats` - View bot stats\n"
            "🔸 `/ping` - View CPU/RAM/Storage\n"
            "🔸 `/broadcast` - (Reply) Send to all\n"
            "🔸 `/index <start> <end>` - Index DB\n"
            "🔸 `/delete <id>` - Delete video by Index ID\n"
            "🔸 `/maintenance` - Toggle Maintenance Mode\n"
            "🔸 `/premium` - Toggle Premium-Only Mode\n"
            "🔸 `/logs` - Download bot log file\n"
        )
        if uid == OWNER_ID:
            text += (
                "\n🗝 **OWNER COMMANDS**\n"
                "🔸 `/add_sudo <uid>` - Manage sudo perms\n"
                "🔸 `/remove_sudo <uid>` - Delete sudo\n"
            )
    await message.reply(text)

@app.on_message(filters.command("maintenance"))
async def maintenance_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "edit"): return
    settings = await settings_col.find_one({"_id": "global"})
    new_state = not settings.get("maintenance", False)
    await settings_col.update_one({"_id": "global"}, {"$set": {"maintenance": new_state}})
    state_str = "ON 🔴" if new_state else "OFF 🟢"
    await message.reply(f"⚙️ **Maintenance Mode is now {state_str}**\n*(When ON, normal users cannot use the bot)*")

@app.on_message(filters.command("premium"))
async def premium_mode_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "edit"): return
    settings = await settings_col.find_one({"_id": "global"})
    new_state = not settings.get("premium_only", False)
    await settings_col.update_one({"_id": "global"}, {"$set": {"premium_only": new_state}})
    state_str = "ON 🔴" if new_state else "OFF 🟢"
    await message.reply(f"💎 **Premium-Only Mode is now {state_str}**\n*(When ON, free users cannot use the bot)*")

@app.on_message(filters.command("logs"))
async def logs_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "read"): return
    if os.path.exists("bot.log"):
        await message.reply_document("bot.log", caption="📄 **Here are the recent bot logs.**")
    else:
        await message.reply("No log file found yet.")

# ==================== FIND & DELETE (VIDEO DB) ====================
@app.on_message(filters.command("find") & filters.private)
async def find_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if len(message.command) < 2: 
        return await message.reply("Usage: `/find <video_id>`\n*(Example: `/find 152`)*")
    
    try: 
        msg_id = int(message.command[1])
    except ValueError: 
        return await message.reply("❌ Invalid ID. Must be a number.")

    # 1. Check Cooldown
    now = time.time()
    if user_id != OWNER_ID and user_id in video_cooldowns:
        passed = now - video_cooldowns[user_id]
        if passed < VIDEO_COOLDOWN_SEC:
            rem = int(VIDEO_COOLDOWN_SEC - passed)
            temp_msg = await message.reply(f"⏳ **Cool down!** Wait `{rem}s` before searching again.")
            asyncio.create_task(auto_delete_msg(client, message.chat.id, temp_msg.id, 5))
            return

    # 2. Check Force Sub
    joined, btns = await check_fsub(client, user_id)
    if not joined:
        return await message.reply("⚠️ **Please join all our channels first!**", reply_markup=InlineKeyboardMarkup(btns))

    user = await get_user(user_id)
    prem = await is_premium(user_id)

    # 3. Check Limits (Strict Free Limit Block)
    if not prem and user.get("daily_count", 0) >= FREE_DAILY_LIMIT:
        bot_me = await client.get_me()
        verify_short_url = await get_verify_link(client, user_id)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Watch Ads (1 Day)", url=verify_short_url)],
            [InlineKeyboardButton("🎁 Refer & Earn (1 Day)", url=f"https://t.me/share/url?url=https://t.me/{bot_me.username}?start=ref_{user_id}")],
            [InlineKeyboardButton("💎 Buy Premium (Instant)", callback_data="force_buy_menu")]
        ])
        text = f"⚠️ **Yᴏᴜ'ᴠᴇ ʀᴇᴀᴄʜᴇᴅ ʏᴏᴜʀ ᴅᴀɪʟʏ ғʀᴇᴇ ʟɪᴍɪᴛ ({FREE_DAILY_LIMIT}/{FREE_DAILY_LIMIT})...!**\n\n⏳ *Come back tomorrow for 50 new videos, or unlock unlimited access right now!*"
        return await message.reply(text, reply_markup=kb)

    # 4. Fetch from DB
    vid = await videos_col.find_one({"msg_id": msg_id})
    if not vid: return await message.reply("❌ Video not found in the database.")
    
    # 5. Update State
    if not prem:
        await users_col.update_one({"_id": user_id}, {"$inc": {"daily_count": 1}})
    video_cooldowns[user_id] = time.time()

    # 6. Send and set for Auto-Delete
    try:
        caption_text = f"🍿 **Video ID:** `{msg_id}`\n⏳ **This video will expire in 5 minutes! Save it ASAP!**"
        sent = await client.copy_message(chat_id=message.chat.id, from_chat_id=DB_CHANNEL, message_id=msg_id, caption=caption_text, protect_content=True)
        asyncio.create_task(auto_delete_msg(client, message.chat.id, sent.id, AUTO_DELETE_SECONDS))
    except Exception as e:
        await message.reply(f"⚠️ Error sending video: {e}")

@app.on_message(filters.command(["del", "delete"]))
async def delete_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "edit"): return
    if len(message.command) < 2: return await message.reply("Usage: `/delete <index_id>`")
    try: msg_id = int(message.command[1])
    except ValueError: return await message.reply("❌ Invalid ID. Must be a number.")
    
    res = await videos_col.delete_one({"msg_id": msg_id})
    if res.deleted_count > 0:
        await message.reply(f"✅ Video with Index ID `{msg_id}` deleted from database.")
    else:
        await message.reply("❌ Video not found in the database.")

# ==================== OTHER ADMIN COMMANDS ====================
@app.on_message(filters.command("remove"))
async def remove_premium_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "edit"): return
    if len(message.command) < 2: return await message.reply("Usage: `/remove <user_id>`")
    try: uid = int(message.command[1])
    except ValueError: return await message.reply("❌ Invalid User ID.")
    await users_col.update_one({"_id": uid}, {"$set": {"premium_expiry": None}})
    await message.reply(f"✅ Premium access removed for user `{uid}`.")

@app.on_message(filters.command(["ban", "bang"]))
async def ban_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "edit"): return
    if len(message.command) < 2: return await message.reply("Usage: `/ban <user_id>`")
    try: uid = int(message.command[1])
    except ValueError: return await message.reply("❌ Invalid User ID.")
    await users_col.update_one({"_id": uid}, {"$set": {"is_banned": True}}, upsert=True)
    banned_users.add(uid)
    await message.reply(f"🚫 User `{uid}` has been permanently **BANNED**.")

@app.on_message(filters.command("unban"))
async def unban_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "edit"): return
    if len(message.command) < 2: return await message.reply("Usage: `/unban <user_id>`")
    try: uid = int(message.command[1])
    except ValueError: return await message.reply("❌ Invalid User ID.")
    await users_col.update_one({"_id": uid}, {"$set": {"is_banned": False}})
    banned_users.discard(uid)
    await message.reply(f"✅ User `{uid}` has been **UNBANNED**.")

@app.on_message(filters.command("broadcast"))
async def broadcast_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "full"): return
    if not message.reply_to_message: return await message.reply("⚠️ Reply to a message to broadcast.")
    m = await message.reply("⏳ **Broadcasting message...**")
    all_users = await users_col.find({}).to_list(length=None)
    success, failed = 0, 0
    for u in all_users:
        try:
            await message.reply_to_message.copy(chat_id=u["_id"])
            success += 1
            await asyncio.sleep(0.1)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            await message.reply_to_message.copy(chat_id=u["_id"])
            success += 1
        except Exception: failed += 1
    await m.edit_text(f"✅ **Broadcast Complete!**\n\n🟢 **Success:** `{success}`\n🔴 **Failed:** `{failed}`")

@app.on_message(filters.command("add"))
async def add_premium_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "edit"): return
    if len(message.command) < 3: return await message.reply("Usage: `/add <user_id> <days>`")
    try:
        uid = int(message.command[1])
        days = int(message.command[2])
    except ValueError: return await message.reply("❌ Invalid format.")
    new_exp = await add_premium(uid, days)
    await message.reply(f"✅ Added **{days} Days** Premium to `{uid}`.\n📅 Expires on: `{new_exp.strftime('%d %b %Y, %I:%M %p')} UTC`")
    try: await client.send_message(uid, f"🎉 **Admin added {days} Days Premium to your account!**\n📅 **Expires on:** `{new_exp.strftime('%d %b %Y, %I:%M %p')} UTC`")
    except Exception: pass

@app.on_message(filters.command("ping"))
async def ping_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "read"): return
    uptime_sec = int(time.time() - START_TIME)
    uptime_str = str(timedelta(seconds=uptime_sec))
    start_t = time.time()
    m = await message.reply("`Pinging system...`")
    end_t = time.time()
    latency = int((end_t - start_t) * 1000)

    total, used, free = shutil.disk_usage("/")
    storage_total, storage_used = total // (2**30), used // (2**30)
    
    ram_total, ram_used = "N/A", "N/A"
    try:
        with open('/proc/meminfo', 'r') as f: lines = f.readlines()
        mem_total = int(lines[0].split()[1]) / 1024
        mem_avail = int(lines[2].split()[1]) / 1024
        ram_total = f"{mem_total/1024:.2f} GB"
        ram_used = f"{(mem_total - mem_avail)/1024:.2f} GB"
    except Exception: pass

    try:
        cpu_load = [x / os.cpu_count() * 100 for x in os.getloadavg()]
        cpu_usage = f"{cpu_load[0]:.1f}%"
    except Exception: cpu_usage = "N/A"

    text = (f"🏓 **Pong!**\n⚡ **Latency:** `{latency}ms`\n⏳ **Uptime:** `{uptime_str}`\n\n"
            f"💻 **System Info:**\n├ ⚙️ **CPU:** `{cpu_usage}`\n├ 💾 **RAM:** `{ram_used} / {ram_total}`\n└ 💿 **Storage:** `{storage_used}GB / {storage_total}GB`")
    await m.edit_text(text)

@app.on_message(filters.command(["admin", "stats", "users"]))
async def admin_panel_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "read"): return
    total_users = await users_col.count_documents({})
    prem_users = await users_col.count_documents({"premium_expiry": {"$gt": datetime.now(timezone.utc)}})
    total_videos = await videos_col.count_documents({})
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    active_users = await users_col.count_documents({"last_reset": today_str})
    dead_users = max(0, total_users - active_users)
    now = time.time()
    active_blocked = sum(1 for exp in spam_blocked_until.values() if exp > now)
    
    text = (f"👑 **ADMIN CONTROL PANEL**\n━━━━━━━━━━━━━━━━━━\n"
            f"👥 **Total Users:** `{total_users}`\n🟢 **Active Today:** `{active_users}`\n"
            f"💀 **Dead Users:** `{dead_users}`\n💎 **Premium Users:** `{prem_users}`\n"
            f"🎬 **Total Videos:** `{total_videos}`\n🚫 **Spam Blocked:** `{active_blocked}`\n"
            f"⛔ **Banned Users:** `{len(banned_users)}`\n━━━━━━━━━━━━━━━━━━")
    await message.reply(text)

@app.on_message(filters.command("unblock"))
async def unblock_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "edit"): return
    if len(message.command) < 2: return await message.reply("Usage: `/unblock <user_id>`")
    try: uid = int(message.command[1])
    except ValueError: return await message.reply("❌ Invalid User ID.")
    spam_blocked_until.pop(uid, None)
    spam_notified.discard(uid)
    await message.reply(f"✅ User `{uid}` unblocked from spam cooldown!")

@app.on_message(filters.command("progress"))
async def progress_cmd(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "read"): return
    if not idx_state["is_active"]: return await message.reply("💤 No indexing is currently running.")
    total = idx_state["end"] - idx_state["start"] + 1
    checked = idx_state["current"] - idx_state["start"]
    percent = (checked / total) * 100 if total > 0 else 0
    text = (f"🔄 **INDEXING IN PROGRESS...**\n━━━━━━━━━━━━━━━━━━\n"
            f"📊 **Checked:** `{checked} / {total}` ({percent:.1f}%)\n"
            f"🆕 **Added:** `{idx_state['added']}`\n⏭️ **Skipped:** `{idx_state['skipped']}`\n"
            f"📍 **Current ID Scan:** `{idx_state['current']}`\n━━━━━━━━━━━━━━━━━━")
    await message.reply(text)

@app.on_message(filters.command("index"))
async def manual_index(client: Client, message: Message):
    if not await check_admin(message.from_user.id, "edit"): return
    if idx_state["is_active"]: return await message.reply("⚠️ **Indexing is already running!** Use `/progress`.")
    if len(message.command) == 2:
        start_id = 1
        try: end_id = int(message.command[1])
        except ValueError: return await message.reply("❌ **Error:** Must provide a NUMBER.")
    elif len(message.command) == 3:
        try:
            start_id, end_id = int(message.command[1]), int(message.command[2])
        except ValueError: return await message.reply("❌ **Error:** Must provide NUMBERS.")
    else: return await message.reply("**Usage:**\n`/index <last_msg_id>`\n`/index <start_id> <end_id>`")
    
    if start_id > end_id: return await message.reply("❌ Start ID must be less than End ID.")
    
    idx_state.update({"is_active": True, "start": start_id, "end": end_id, "current": start_id, "added": 0, "skipped": 0})
    await message.reply(f"⏳ **Indexing started from {start_id} to {end_id}...**\n*(Checking safely to avoid API limits. Use `/progress`)*")
    
    for i in range(start_id, end_id + 1, 20):
        if not idx_state["is_active"]: break 
        ids = list(range(i, min(i + 20, end_id + 1)))
        idx_state["current"] = i
        try:
            msgs = await client.get_messages(DB_CHANNEL, ids)
            for m in msgs:
                if m and not m.empty and (m.video or m.document):
                    result = await videos_col.update_one({"msg_id": m.id}, {"$setOnInsert": {"msg_id": m.id, "date": datetime.now(timezone.utc)}}, upsert=True)
                    if result.upserted_id: idx_state["added"] += 1
                    else: idx_state["skipped"] += 1
            await asyncio.sleep(2)
        except FloodWait as e: await asyncio.sleep(e.value)
        except PeerIdInvalid: 
            idx_state["is_active"] = False
            return await message.reply("❌ **Peer ID Invalid!**\nBot is blind. Send a text message in DB channel, then try again.")
        except Exception: pass
    idx_state["is_active"] = False
    await message.reply(f"✅ **Indexing Complete!**\n\n🆕 **New Videos Added:** `{idx_state['added']}`\n⏭️ **Duplicates Skipped:** `{idx_state['skipped']}`")

# ==================== MAIN USER COMMANDS ====================
async def get_verify_link(client: Client, user_id: int) -> str:
    token = secrets.token_urlsafe(8)
    await users_col.update_one({"_id": user_id}, {"$set": {"verify_token": token}})
    bot_me = await client.get_me()
    dest_url = f"https://t.me/{bot_me.username}?start=verify_{token}"
    if not SHORTENER_API: return FALLBACK_SHORT_LINK
    api_url = f"https://{SHORTENER_DOMAIN}/api?api={SHORTENER_API}&url={dest_url}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=8) as resp:
                data = await resp.json()
                if data.get("status") == "success": return data.get("shortenedUrl")
    except Exception: pass
    return FALLBACK_SHORT_LINK

async def check_fsub(client: Client, user_id: int):
    if user_id == OWNER_ID: return True, []
    is_missing = False
    async with aiohttp.ClientSession() as session:
        for idx, ch_id in enumerate(FSUB_CHANNELS, start=1):
            is_member = False
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember?chat_id={ch_id}&user_id={user_id}"
            try:
                async with session.get(url, timeout=5) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        status = data["result"]["status"]
                        if status in ["member", "administrator", "creator"]:
                            is_member = True
            except Exception: pass
            if not is_member:
                is_missing = True
                break
    if is_missing:
        all_buttons = []
        for idx, ch_id in enumerate(FSUB_CHANNELS, start=1):
            link = FSUB_LINKS.get(ch_id, "https://t.me/telegram")
            all_buttons.append([InlineKeyboardButton(f"📢 JOIN CHANNEL {idx}", url=link)])
        all_buttons.append([InlineKeyboardButton("🔄 TRY AGAIN", callback_data="check_fsub")])
        return False, all_buttons
    return True, []

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    existed = await users_col.find_one({"_id": user_id})
    user = await get_user(user_id)

    if len(message.command) > 1 and message.command[1].startswith("verify_"):
        token = message.command[1].replace("verify_", "")
        if user.get("verify_token") == token or token == "free1day":
            await users_col.update_one({"_id": user_id}, {"$set": {"verify_token": None}})
            new_exp = await add_premium(user_id, 1)
            try: await client.send_message(LOG_CHANNEL, f"🎁 #SHORTLINK_VERIFIED\n👤 **User:** {message.from_user.mention} (`{user_id}`)\n🎁 **Reward:** 1 Day Premium")
            except: pass
            return await message.reply("✅ **Verification Successful!**\n\n🎉 You received **1 DAY FREE PREMIUM**!\n" + f"📅 **Expires on:** `{new_exp.strftime('%d %b %Y, %I:%M %p')} UTC`", reply_markup=MAIN_KEYBOARD)
        else: return await message.reply("⚠️ **Invalid or Expired Verification Link!**")

    if not existed:
        if len(message.command) > 1 and message.command[1].startswith("ref_"):
            try:
                ref_id = int(message.command[1].split("_")[1])
                if ref_id != user_id:
                    referrer = await get_user(ref_id)
                    new_pts = referrer.get("ref_points", 0) + 1
                    await users_col.update_one({"_id": user_id}, {"$set": {"referred_by": ref_id}})
                    if new_pts >= 5:
                        await users_col.update_one({"_id": ref_id}, {"$inc": {"referrals": 1}, "$set": {"ref_points": 0}})
                        new_exp = await add_premium(ref_id, 1)
                        try: await client.send_message(ref_id, f"🎉 **5 Referral Points Completed!**\n💎 You unlocked **1 DAY FREE PREMIUM**!")
                        except: pass
                    else:
                        await users_col.update_one({"_id": ref_id}, {"$inc": {"referrals": 1}, "$set": {"ref_points": new_pts}})
                        try: await client.send_message(ref_id, f"👥 **New Referral Joined!** (+1 Point)\n🎯 **Points:** `{new_pts}/5`")
                        except: pass
            except: pass
        try: await client.send_message(LOG_CHANNEL, f"👤 #NEW_USER\n👤 **User:** {message.from_user.mention}\n🆔 **ID:** `{user_id}`")
        except: pass

    joined, btns = await check_fsub(client, user_id)
    if not joined:
        return await message.reply("⚠️ **Please join all our updates channels below to use this bot!**", reply_markup=InlineKeyboardMarkup(btns))
    await message.reply(f"👋 **Welcome {message.from_user.first_name}!**\n\nUse the buttons below to get videos or manage your plan.", reply_markup=MAIN_KEYBOARD)

@app.on_callback_query(filters.regex("^check_fsub$"))
async def fsub_callback(client: Client, query: CallbackQuery):
    joined, btns = await check_fsub(client, query.from_user.id)
    if not joined: return await query.answer("❌ You haven't joined all channels yet! Please check them one by one.", show_alert=True)
    await query.message.delete()
    await query.message.reply("✅ **Thank you for joining!** Use the menu below:", reply_markup=MAIN_KEYBOARD)

async def send_plan_menu(message: Message, user_id: int, force_buy=False, is_cb=False):
    user = await get_user(user_id)
    prem = await is_premium(user_id)
    
    if prem and not force_buy:
        exp = user.get("premium_expiry")
        if exp and isinstance(exp, datetime):
            if exp.tzinfo is None: exp = exp.replace(tzinfo=timezone.utc)
            exp_str = exp.strftime("%d %b %Y, %I:%M %p UTC")
        else: exp_str = "Unknown"
        text = (f"💎 **ACTIVE PREMIUM STATUS**\n━━━━━━━━━━━━━━━━━━\n\n✅ **Status:** `Premium Active`\n"
                f"📅 **Expires On:** `{exp_str}`\n\n✦ BATCH Command Unlocked 🔓\n✦ Unlimited Video Access 🍿\n"
                f"✦ Forward & Download Disabled 🔒\n━━━━━━━━━━━━━━━━━━")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Extend Premium", callback_data="force_buy_menu")],
            [InlineKeyboardButton("👨‍💻 Contact Support", url=f"https://t.me/{ADMIN_SUPPORT.replace('@', '')}")]
        ])
        if is_cb:
            try: return await message.edit_text(text, reply_markup=kb)
            except: pass
        return await message.reply(text, reply_markup=kb)
        
    limit_disp = "♾️ UNLIMITED (Premium)" if prem else f"{user.get('daily_count', 0)} / {FREE_DAILY_LIMIT}"
    text = (f"💳 **CHOOSE A PLAN**\n━━━━━━━━━━━━━━━━━━\n\n📊 **Limit:** `{limit_disp}`\n🏦 PAYTM • UPI • PHONEPE • GPAY\n\n"
            f"✦ Pʀᴇᴍɪᴜᴍ ᴀᴄᴛɪᴠᴀᴛᴇs ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʏ ᴀғᴛᴇʀ ᴘᴀʏᴍᴇɴᴛ\n✦ Vɪᴅᴇᴏ Fᴏʀᴡᴀʀᴅɪɴɢ ɪs Disabled 🔒\n━━━━━━━━━━━━━━━━━━\n👇 **Sᴇʟᴇᴄᴛ ʏᴏᴜʀ ᴘʟᴀɴ:**")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1 DAY · ₹9", callback_data="buy_1d"), InlineKeyboardButton("7 DAYS · ₹24", callback_data="buy_7d")],
        [InlineKeyboardButton("1 MONTH · ₹60", callback_data="buy_1m"), InlineKeyboardButton("3 MONTHS · ₹150", callback_data="buy_3m")],
        [InlineKeyboardButton("6 MONTHS · ₹270", callback_data="buy_6m"), InlineKeyboardButton("1 YEAR · ₹480", callback_data="buy_1y")]
    ])
    if is_cb:
        try: return await message.edit_text(text, reply_markup=kb)
        except: pass
    await message.reply(text, reply_markup=kb)

@app.on_message(filters.regex("^(PLAN STATUS 🏷|BUY PREMIUM)$") & filters.private)
async def plan_status_handler(client: Client, message: Message): 
    await send_plan_menu(message, message.from_user.id, force_buy=(message.text == "BUY PREMIUM"))

@app.on_callback_query(filters.regex("^(open_premium|force_buy_menu)$"))
async def open_premium_cb(client: Client, query: CallbackQuery):
    await query.answer()
    await send_plan_menu(query.message, query.from_user.id, force_buy=(query.data == "force_buy_menu"), is_cb=True)

@app.on_message(filters.regex("^SUPPORT 👨‍💻$") & filters.private)
async def support_handler(client: Client, message: Message):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("👨‍💻 Message Admin", url=f"https://t.me/{ADMIN_SUPPORT.replace('@', '')}")]])
    await message.reply("💬 **Need Help?**\n\nIf you have issues, tap below.", reply_markup=kb)

async def send_refer_stats(client: Client, user_id: int, message: Message):
    user = await get_user(user_id)
    bot_me = await client.get_me()
    ref_link = f"https://t.me/{bot_me.username}?start=ref_{user_id}"
    exp = user.get("premium_expiry")
    if exp and isinstance(exp, datetime):
        if exp.tzinfo is None: exp = exp.replace(tzinfo=timezone.utc)
        exp_str = exp.strftime("%d %b %Y") if exp > datetime.now(timezone.utc) else "ɴᴏᴛ ᴀᴄᴛɪᴠᴇ"
    else: exp_str = "ɴᴏᴛ ᴀᴄᴛɪᴠᴇ"
    pts, total_refs = user.get("ref_points", 0), user.get("referrals", 0)
    text = f"🎯 **ʀᴇғᴇʀ sᴛᴀᴛs:**\n\n• **ʀᴇғᴇʀʀᴀʟs:** {total_refs} ({pts}/5 ᴘᴏɪɴᴛs)\n• **ʀᴇғᴇʀ ʀᴇᴡᴀʀᴅ:** 5 ᴘᴏɪɴᴛs = 1 ᴅᴀʏ ᴘʀᴇᴍɪᴜᴍ\n• **ᴘʀᴇᴍɪᴜᴍ ᴇxᴘɪʀʏ:** {exp_str}\n\n• **ʏᴏᴜʀ ʀᴇғᴇʀ ʟɪɴᴋ:**\n{ref_link}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("• SHARE YOUR LINK •", url=f"https://t.me/share/url?url={ref_link}&text=Join%20this%20amazing%20bot!")]])
    await message.reply(text, reply_markup=kb, disable_web_page_preview=True)

@app.on_message(filters.regex("^REFER 👥$") & filters.private)
async def refer_handler(client: Client, message: Message): await send_refer_stats(client, message.from_user.id, message)

@app.on_message(filters.regex("^BATCH 💋$") & filters.private)
async def batch_handler(client: Client, message: Message):
    user_id = message.from_user.id
    joined, btns = await check_fsub(client, user_id)
    if not joined:
        return await message.reply("⚠️ **Please join all our channels first!**", reply_markup=InlineKeyboardMarkup(btns))
    prem = await is_premium(user_id)
    if not prem:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium", callback_data="force_buy_menu")]])
        return await message.reply("⚠️ **PREMIUM EXCLUSIVE FEATURE!**\nUpgrade your plan to get 4 videos at once without limits!", reply_markup=kb)
    
    now = time.time()
    if user_id != OWNER_ID and user_id in batch_cooldowns:
        passed = now - batch_cooldowns[user_id]
        if passed < 60:
            rem = int(60 - passed)
            temp_msg = await message.reply(f"⏳ **Batch Cooldown!** Wait `{rem}s`.")
            asyncio.create_task(auto_delete_msg(client, message.chat.id, temp_msg.id, 5))
            return
            
    all_vids = await videos_col.find().to_list(length=500)
    if not all_vids: return await message.reply("⚠️ No videos indexed.")
    batch_cooldowns[user_id] = time.time()
    
    for v in random.sample(all_vids, min(4, len(all_vids))):
        try:
            caption_text = f"🍿 **Video ID:** `{v['msg_id']}`\n⏳ **This video will expire in 5 minutes! Save it ASAP!**"
            sent = await client.copy_message(chat_id=user_id, from_chat_id=DB_CHANNEL, message_id=v["msg_id"], caption=caption_text, protect_content=True)
            asyncio.create_task(auto_delete_msg(client, user_id, sent.id, AUTO_DELETE_SECONDS))
        except: pass

async def send_video_item(client: Client, user_id: int, chat_id: int, query: CallbackQuery = None, direction="next"):
    now = time.time()
    if user_id != OWNER_ID and user_id in video_cooldowns:
        passed = now - video_cooldowns[user_id]
        if passed < VIDEO_COOLDOWN_SEC:
            rem = int(VIDEO_COOLDOWN_SEC - passed)
            if query: return await query.answer(f"⏳ Cool down! Wait {rem}s.", show_alert=True)
            else:
                temp_msg = await client.send_message(chat_id, f"⏳ **Cool down!** Wait `{rem}s`.")
                asyncio.create_task(auto_delete_msg(client, chat_id, temp_msg.id, 5))
                return

    joined, btns = await check_fsub(client, user_id)
    if not joined:
        return await client.send_message(chat_id=chat_id, text="⚠️ **Please join all our updates channels first!**", reply_markup=InlineKeyboardMarkup(btns))

    user = await get_user(user_id)
    prem = await is_premium(user_id)

    if not prem and user.get("daily_count", 0) >= FREE_DAILY_LIMIT:
        bot_me = await client.get_me()
        verify_short_url = await get_verify_link(client, user_id)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Watch Ads (1 Day)", url=verify_short_url)],
            [InlineKeyboardButton("🎁 Refer & Earn (1 Day)", url=f"https://t.me/share/url?url=https://t.me/{bot_me.username}?start=ref_{user_id}")],
            [InlineKeyboardButton("💎 Buy Premium (Instant)", callback_data="force_buy_menu")]
        ])
        text = f"⚠️ **Yᴏᴜ'ᴠᴇ ʀᴇᴀᴄʜᴇᴅ ʏᴏᴜʀ ᴅᴀɪʟʏ ғʀᴇᴇ ʟɪᴍɪᴛ ({FREE_DAILY_LIMIT}/{FREE_DAILY_LIMIT})...!**\n\n⏳ *Come back tomorrow for 50 new videos, or unlock unlimited access right now!*"
        return await client.send_message(chat_id, text, reply_markup=kb)

    all_vids = await videos_col.find().sort("msg_id", 1).to_list(length=10000)
    if not all_vids: return await client.send_message(chat_id, "⚠️ **No videos found!**")

    current_idx = user.get("video_index", 0)
    if direction == "prev":
        current_idx -= 2  
        if current_idx < 0: current_idx = len(all_vids) - 1
    if current_idx >= len(all_vids): current_idx = 0 
        
    chosen = all_vids[current_idx]
    await users_col.update_one({"_id": user_id}, {"$inc": {"daily_count": 1}, "$set": {"video_index": current_idx + 1}})

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏮ PREVIOUS", callback_data="nav_video_prev"), InlineKeyboardButton("▶ NEXT", callback_data="nav_video_next")],
        [InlineKeyboardButton("🔞 VIRAL VIDEOS STUFF 👑", url=PROMO_CHANNEL_URL)]
    ])

    try:
        if query and query.message:
            try: await query.message.delete()
            except: pass
            
        caption_text = f"🍿 **Video ID:** `{chosen['msg_id']}`\n⏳ **This video will expire in 5 minutes! Save it ASAP!**"
        sent = await client.copy_message(chat_id=chat_id, from_chat_id=DB_CHANNEL, message_id=chosen["msg_id"], caption=caption_text, reply_markup=kb, protect_content=True)
        video_cooldowns[user_id] = time.time()
        asyncio.create_task(auto_delete_msg(client, chat_id, sent.id, AUTO_DELETE_SECONDS))
    except PeerIdInvalid: await client.send_message(chat_id, "⚠️ Bot is blind to Database Channel. Send a text message inside DB.")
    except Exception as e: await client.send_message(chat_id, f"⚠️ Error fetching video: `{e}`")

@app.on_message(filters.regex("^GET VIDEO 🍭$") & filters.private)
async def get_video_handler(client: Client, message: Message): await send_video_item(client, message.from_user.id, message.chat.id, direction="next")

@app.on_callback_query(filters.regex("^nav_video_(.+)$"))
async def nav_video_cb(client: Client, query: CallbackQuery):
    await send_video_item(client, query.from_user.id, query.message.chat.id, query=query, direction=query.data.split("_")[2])

# ==================== PAYMENT SYSTEM ====================
@app.on_callback_query(filters.regex("^buy_(.+)$"))
async def create_order_cb(client: Client, query: CallbackQuery):
    plan_key = query.data.split("_")[1]
    plan = PLANS.get(plan_key)
    if not plan: return await query.answer("Invalid plan!", show_alert=True)
    await query.answer()
    user_id = query.from_user.id
    order_id = f"PREM-{int(datetime.now(timezone.utc).timestamp())}{user_id}"

    await orders_col.insert_one({"order_id": order_id, "user_id": user_id, "plan_key": plan_key, "amount": plan["price"], "days": plan["days"], "status": "pending", "created_at": datetime.now(timezone.utc)})
    caption = f"✦ Please complete the following payment:\n━━━━━━━━━━━━━━━━━━\n\n❒ **AMOUNT :** ₹{plan['price']}\n≡ **PLAN :** {plan['name']}\n❒ **ORDER ID :**\n`{order_id}`\n━━━━━━━━━━━━━━━━━━\n≡ ⏳ **Follow the Instruction:-**\n1️⃣ Scan the QR and pay the amount.\n2️⃣ After Payment, Click on ✅ **Payment Done** Button."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ PAYMENT DONE", callback_data=f"verify_pay_{order_id}")]])

    try: await client.send_photo(chat_id=user_id, photo=QR_IMAGE_URL, caption=caption, reply_markup=kb)
    except: await client.send_message(chat_id=user_id, text=caption, reply_markup=kb)

@app.on_callback_query(filters.regex("^verify_pay_(.+)$"))
async def verify_payment_cb(client: Client, query: CallbackQuery):
    order_id = query.data.replace("verify_pay_", "")
    user_id = query.from_user.id
    pending_proofs[user_id] = order_id
    pending_utr.pop(user_id, None) 
    try: await query.message.delete()
    except: pass
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("👨‍💻 Contact Support", url=f"https://t.me/{ADMIN_SUPPORT.replace('@', '')}")]])
    await client.send_message(user_id, "📸 **Please upload your Payment Screenshot NOW.**", reply_markup=kb)

@app.on_message(filters.photo & filters.private, group=1)
async def handle_payment_proof(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in pending_proofs:
        order_id = pending_proofs.pop(user_id)
        pending_utr[user_id] = {"order_id": order_id, "photo_id": message.photo.file_id}
        await message.reply("📸 **Screenshot Received!**\n\nNow, type your **12-digit UTR / Transaction ID** and send it as a message.")

@app.on_message(filters.text & filters.private, group=2)
async def handle_utr_input(client: Client, message: Message):
    if message.text.startswith("/"): return 
    user_id = message.from_user.id
    if user_id in pending_utr:
        data = pending_utr.pop(user_id)
        order = await orders_col.find_one({"order_id": data["order_id"]})
        if not order: return await message.reply("❌ Order not found or expired.")
        
        caption = f"🧾 **#PAYMENT_PROOF**\n\n👤 **User:** {message.from_user.mention} (`{user_id}`)\n📦 **Plan:** {order.get('days')} Days (₹{order.get('amount')})\n🆔 **Order ID:** `{data['order_id']}`\n🔖 **UTR/Txn ID:** `{message.text}`"
        admin_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_{data['order_id']}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_{data['order_id']}")]
        ])
        
        try:
            await client.send_photo(LOG_CHANNEL, photo=data["photo_id"], caption=caption, reply_markup=admin_kb)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("👨‍💻 Contact Support", url=f"https://t.me/{ADMIN_SUPPORT.replace('@', '')}")]])
            await message.reply("✅ **Screenshot & UTR Submitted Successfully!**\nPlease wait while our admin verifies your payment.", reply_markup=kb)
        except Exception: await message.reply(f"⚠️ Error sending proof to log. Please contact {ADMIN_SUPPORT}")

@app.on_callback_query(filters.regex("^adm_app_(.+)$"))
async def admin_approve_cb(client: Client, query: CallbackQuery):
    if not await check_admin(query.from_user.id, "edit"): return await query.answer("Access Denied", show_alert=True)
    order_id = query.data.replace("adm_app_", "")
    order = await orders_col.find_one({"order_id": order_id})
    if not order: return await query.answer("Order not found!", show_alert=True)
    if order.get("status") == "paid": return await query.answer("Already approved!", show_alert=True)
    
    await orders_col.update_one({"order_id": order_id}, {"$set": {"status": "paid"}})
    new_exp = await add_premium(order["user_id"], order["days"])
    
    try: await query.edit_message_caption(f"{query.message.caption}\n\n✅ **APPROVED BY ADMIN**")
    except: pass
    try: await client.send_message(order["user_id"], f"✅ **Payment Verified!**\n\n💎 **Plan Activated:** `{order['days']} Days`\n📅 **Expires on:** `{new_exp.strftime('%d %b %Y, %I:%M %p')} UTC`")
    except: pass

@app.on_callback_query(filters.regex("^adm_rej_(.+)$"))
async def admin_reject_cb(client: Client, query: CallbackQuery):
    if not await check_admin(query.from_user.id, "edit"): return await query.answer("Access Denied", show_alert=True)
    order_id = query.data.replace("adm_rej_", "")
    order = await orders_col.find_one({"order_id": order_id})
    if not order: return await query.answer("Order not found!", show_alert=True)
    
    await orders_col.update_one({"order_id": order_id}, {"$set": {"status": "rejected"}})
    try: await query.edit_message_caption(f"{query.message.caption}\n\n❌ **REJECTED BY ADMIN**")
    except: pass
    try: 
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("👨‍💻 Contact Support", url=f"https://t.me/{ADMIN_SUPPORT.replace('@', '')}")]])
        await client.send_message(order["user_id"], f"❌ **Payment Rejected!**\n\nYour payment for `{order_id}` could not be verified.", reply_markup=kb)
    except: pass

# ==================== WEB SERVER (KOYEB/RENDER) ====================
async def web_handler(request):
    return web.Response(text="Bot is running smoothly 24/7!")

async def start_web_server():
    webapp = web.Application()
    webapp.router.add_get("/", web_handler)
    runner = web.AppRunner(webapp)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Web server listening on port {port}")

async def main():
    try:
        await db.command("ping")
        print("✅ MongoDB Connection Successful!")
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: MongoDB connection failed!\n{e}\n")
        sys.exit(1)
        
    await init_db()
    await start_web_server()
    print("Bot is starting...")
    await app.start()
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop.run_until_complete(main())
