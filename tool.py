# ================= AUTO INSTALL =================
import subprocess, sys
def pip_install(package):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    except: pass

required = {"aiohttp": "aiohttp>=3.9.0"}
for m, p in required.items():
    try: __import__(m)
    except ImportError: pip_install(p)
# =================================================

import asyncio
import aiohttp
import random
import string
import os

# ========== CONFIG ==========
BASE_URL = "https://snote.vip/notes/"
CONCURRENT = 10
CODE_LENGTH = 6
CHARSET = string.ascii_uppercase + string.digits

PAUSE_MINUTES = 20
PAUSE_SECONDS = PAUSE_MINUTES * 60

DISCORD_WEBHOOK_URL = "https://canary.discord.com/api/webhooks/1444536629623656543/zNHlASTocFTzq0EmhPYbY1JHIUdf1NjoeFcfLZlD0kp6HtGOWYOUKMxuCsbzCYKt6yJZ"

CHECKED_FILE = "checked_urls.txt"
LOG_DIR = "logs"
VALID_FILE = os.path.join(LOG_DIR, "all_valid_links.txt")

checked_urls = set()
file_lock = asyncio.Lock()
stats = {"scan": 0, "found": 0}


# ========== Helper ==========
def gen_code():
    return "".join(random.choices(CHARSET, k=CODE_LENGTH))

def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)

async def append_line(fp, text):
    folder = os.path.dirname(fp)
    if folder: os.makedirs(folder, exist_ok=True)
    async with file_lock:
        with open(fp, "a", encoding="utf-8") as f:
            f.write(text + "\n")

async def notify(url):
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(DISCORD_WEBHOOK_URL, json={"content": url})
    except:
        pass


# ========== Scanner ==========
async def scan_one(session):
    code = gen_code()
    url = BASE_URL + code

    if url in checked_urls:
        return False
    checked_urls.add(url)
    await append_line(CHECKED_FILE, url)

    await asyncio.sleep(random.uniform(0.8, 1.8))

    try:
        async with session.get(url, timeout=10) as res:
            stats["scan"] += 1

            # Rate-limit: báo trên tool, không gửi Discord
            if res.status in (429, 403):
                print(f"⛔ RATE-LIMIT — Tạm dừng {PAUSE_MINUTES} phút")
                return True

            # URL hợp lệ
            if res.status == 200:
                stats["found"] += 1
                print(f"✔ [{stats['found']}] Hợp lệ: {url}")
                await append_line(VALID_FILE, url)
                await notify(url)

            # Console refresh theo nhịp
            if stats["scan"] % 50 == 0:
                print(f"🔄 Đã quét: {stats['scan']} — Hợp lệ: {stats['found']}")

    except Exception as e:
        print("Lỗi:", e)

    return False


# ========== Main Loop ==========
async def main():
    ensure_log_dir()
    print("🚀 Scanner START!")

    async with aiohttp.ClientSession() as session:
        while True:
            results = await asyncio.gather(*(scan_one(session) for _ in range(CONCURRENT)))

            # nếu bất kỳ request nào bị chặn → Pause
            if any(results):
                await asyncio.sleep(PAUSE_SECONDS)
                print("▶️ Resume sau tránh limit!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 STOP bởi user")