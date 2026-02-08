# -*- coding: utf-8 -*-
"""
Discord bot: Slash commands /help, /scan, /check. Gõ / để hiện lệnh sẵn.
"""
import discord
from discord import app_commands
import re
import os
import asyncio
import aiohttp
import requests
from bs4 import BeautifulSoup

# ================= CONFIG =================
# Token: đặt biến môi trường DISCORD_BOT_TOKEN hoặc sửa dòng dưới. Nếu bị 401 Unauthorized thì token hết hạn/reset — vào Discord Developer Portal → Application → Bot → Reset Token, copy token mới.
TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "TOKEN")
CHANNEL_SCAN_ID = 1444536423435735060   # Channel chứa link snote
CHANNEL_OUTPUT_ID = 1470017876986433556   # Channel nhận toàn bộ phản hồi / kết quả
CHANNEL_CHECK_RESULT_ID = 1451529761569636464  # Channel nhận kết quả /check (embed)
WEBHOOK_URL = "https://discord.com/api/webhooks/1451531409368813601/W3Rt5AVpyzjUKwRXq8no31Rwj0Xyzc7aUfDMimjZoQaTeUI2GaEXCh6jN9puHWRDUicA"

DELETE_AFTER_SECONDS = 30   # Tự xoá tin nhắn (user + bot) sau số giây; hoặc xoá khi có lệnh mới
CHECK_PAUSE_ON_ERROR_SEC = 600  # Khi check gặp 400 hoặc rate limit: dừng 10 phút rồi chạy lại link đó
CHECK_RETRY_MAX = 5  # Số lần thử lại tối đa cho 1 link khi 400/429

INVALID_TEXT = "Bạn không có quyền để xem / sửa ghi chú này"

SNOTE_LINKS_FILE = "snote_links.txt"
VALID_LINKS_FILE = "valid_links.txt"
MAX_CONCURRENT = 30
TIMEOUT = 15
# =========================================

PATTERN_SNOTE = re.compile(r"https:\/\/snote\.vip\/notes\/\w+")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Tin nhắn bot ở channel output để xoá khi lệnh mới chạy hoặc sau DELETE_AFTER_SECONDS
last_output_messages = []


# ============ HELP ============
def get_help_embed():
    return (
        "**📋 DANH SÁCH LỆNH** (dùng **/** hoặc **!**)\n\n"
        "**/scan** hoặc **!scan** — Quét link trong channel. Lấy toàn bộ link snote từ lịch sử kênh, quét từng link. "
        "Link nào không hiện thông báo \"không có quyền xem\" thì coi là hợp lệ. "
        "Lọc ra link hợp lệ, gửi lên kênh kèm file `.txt`.\n\n"
        "**/check** hoặc **!check** — Kiểm tra link. Đọc file link hợp lệ (sau khi đã scan), mở từng link, "
        "lấy link trong khung nội dung note, gửi vào channel kết quả. Gặp 400/rate limit sẽ dừng 10 phút rồi thử lại."
    )


# ============ WEBHOOK ============
def send_webhook_content(text):
    requests.post(WEBHOOK_URL, json={"content": text})


def send_webhook_embed(title, description, color=0x5865F2):
    """Gửi webhook với embed (khung nhỏ) chứa description."""
    payload = {
        "embeds": [{
            "title": title,
            "description": description[:2048] if description else "Không có link.",
            "color": color,
        }]
    }
    requests.post(WEBHOOK_URL, json=payload)


async def delete_old_output_messages():
    """Xoá toàn bộ tin nhắn bot đã lưu ở channel output."""
    global last_output_messages
    out = list(last_output_messages)
    last_output_messages.clear()
    ch = await client.fetch_channel(CHANNEL_OUTPUT_ID)
    for m in out:
        try:
            await m.delete()
        except Exception:
            pass


async def schedule_delete_after(seconds, messages):
    """Sau vài giây sẽ xoá các tin nhắn (chỉ id, cần fetch lại nếu cần)."""
    await asyncio.sleep(seconds)
    for m in messages:
        try:
            await m.delete()
        except Exception:
            pass


# ============ !scan: Lấy link snote + quét hợp lệ + gửi file ============
async def fetch_snote_links_from_channel(channel):
    links = set()
    async for msg in channel.history(limit=None, oldest_first=True):
        found = PATTERN_SNOTE.findall(msg.content or "")
        links.update(found)
    return sorted(links)


async def check_one_link(session, url, sem):
    async with sem:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
                text = await r.text()
                if INVALID_TEXT not in text:
                    return url
        except Exception:
            pass
    return None


async def get_output_channel():
    return await client.fetch_channel(CHANNEL_OUTPUT_ID)


async def run_scan(out_channel):
    sent = []
    m = await out_channel.send("⏳ Đang lấy toàn bộ link snote từ kênh...")
    sent.append(m)
    channel = await client.fetch_channel(CHANNEL_SCAN_ID)
    all_links = await fetch_snote_links_from_channel(channel)

    if not all_links:
        m = await out_channel.send("❌ Không tìm thấy link snote nào trong kênh.")
        sent.append(m)
        return sent

    with open(SNOTE_LINKS_FILE, "w", encoding="utf-8") as f:
        for u in all_links:
            f.write(u + "\n")

    m = await out_channel.send(f"📂 Đã lưu {len(all_links)} link vào `{SNOTE_LINKS_FILE}`. Đang quét điều kiện hợp lệ...")
    sent.append(m)

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [check_one_link(session, u, sem) for u in all_links]
        results = await asyncio.gather(*tasks)

    valid_list = [r for r in results if r]

    with open(VALID_LINKS_FILE, "w", encoding="utf-8") as f:
        for v in valid_list:
            f.write(v + "\n")

    m = await out_channel.send(
        f"✅ Scan xong. Hợp lệ: **{len(valid_list)}** / {len(all_links)}",
        file=discord.File(VALID_LINKS_FILE)
    )
    sent.append(m)
    return sent


# ============ Lấy link trong div.form-control.read.content-fit ============
def extract_links_from_content_div(html: str):
    soup = BeautifulSoup(html, "html.parser")
    div = soup.select_one("div.form-control.read.content-fit")
    if not div:
        return []
    links = []
    for a in div.find_all("a", href=True):
        href = a["href"].strip()
        if href and (href.startswith("http://") or href.startswith("https://")):
            links.append(href)
    return links


# ============ !check: Mở từng link hợp lệ, lấy link trong div, gửi vào channel check result ============
async def run_check(out_channel):
    sent = []
    if not os.path.exists(VALID_LINKS_FILE):
        m = await out_channel.send(f"❌ Chưa có file `{VALID_LINKS_FILE}`. Chạy **/scan** hoặc **!scan** trước.")
        sent.append(m)
        return sent

    with open(VALID_LINKS_FILE, "r", encoding="utf-8") as f:
        urls = [x.strip() for x in f if x.strip()]

    if not urls:
        m = await out_channel.send("❌ File link hợp lệ trống.")
        sent.append(m)
        return sent

    total = len(urls)
    m = await out_channel.send(f"🚀 Bắt đầu mở {total} link hợp lệ. Kết quả gửi vào channel kết quả.")
    sent.append(m)

    check_channel = await client.fetch_channel(CHANNEL_CHECK_RESULT_ID)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    async with aiohttp.ClientSession(headers=headers) as session:
        i = 0
        while i < len(urls):
            url = urls[i]
            idx = i + 1
            retries = 0
            success = False

            while not success and retries <= CHECK_RETRY_MAX:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
                        if r.status == 400 or r.status == 429:
                            try:
                                await r.read()
                            except Exception:
                                pass
                            retries += 1
                            if retries <= CHECK_RETRY_MAX:
                                m = await out_channel.send(
                                    f"⏸ Link số {idx}/{total} gặp lỗi {r.status} (rate limit/400). "
                                    f"Dừng {CHECK_PAUSE_ON_ERROR_SEC // 60} phút rồi thử lại (lần {retries}/{CHECK_RETRY_MAX})."
                                )
                                sent.append(m)
                                await asyncio.sleep(CHECK_PAUSE_ON_ERROR_SEC)
                            else:
                                emb = discord.Embed(
                                    title=f"❌ Link số {idx}/{total}",
                                    description=f"{url}\nLỗi HTTP {r.status} sau {CHECK_RETRY_MAX} lần thử.",
                                    color=0xED4245,
                                )
                                await check_channel.send(embed=emb)
                                success = True
                            continue

                        html = await r.text()
                        success = True

                        inside_links = extract_links_from_content_div(html)
                        link_count = len(inside_links)
                        body = "\n".join(inside_links) if inside_links else "Không có link trong khung nội dung."

                        title = f"📋 Link số {idx}/{total}"
                        desc = f"**URL snote:** {url}\n**Số link trong note:** {link_count}\n\n```\n{body}\n```"
                        if len(desc) > 2048:
                            desc = desc[:2040] + "\n```"
                        emb = discord.Embed(title=title, description=desc, color=0x5865F2)
                        await check_channel.send(embed=emb)

                except asyncio.TimeoutError:
                    emb = discord.Embed(title=f"❌ Link số {idx}/{total}", description=f"{url}\nLỗi: Timeout", color=0xED4245)
                    await check_channel.send(embed=emb)
                    success = True
                except Exception as e:
                    emb = discord.Embed(title=f"❌ Link số {idx}/{total}", description=f"{url}\nLỗi: {e}", color=0xED4245)
                    await check_channel.send(embed=emb)
                    success = True

            i += 1
            await asyncio.sleep(1)

    m = await out_channel.send("🎉 Đã xử lý xong tất cả link, đã gửi vào channel kết quả.")
    sent.append(m)
    return sent


# ============ SLASH COMMANDS ============
async def _run_command(interaction, command_fn):
    """Chung: defer, xoá tin cũ, chạy lệnh, gửi vào output channel, lên lịch xoá."""
    global last_output_messages
    await interaction.response.defer()
    out_channel = await get_output_channel()
    await delete_old_output_messages()
    sent = await command_fn(out_channel)
    last_output_messages = sent
    if sent:
        asyncio.create_task(schedule_delete_after(DELETE_AFTER_SECONDS, list(sent)))


@tree.command(name="help", description="Xem danh sách lệnh và cách dùng")
async def cmd_help(interaction: discord.Interaction):
    global last_output_messages
    await interaction.response.defer(ephemeral=False)
    await delete_old_output_messages()
    out_channel = await get_output_channel()
    m = await out_channel.send(get_help_embed())
    last_output_messages = [m]
    asyncio.create_task(schedule_delete_after(DELETE_AFTER_SECONDS, [m]))


@tree.command(name="scan", description="Quét Link Trong Channel")
async def cmd_scan(interaction: discord.Interaction):
    await _run_command(interaction, run_scan)


@tree.command(name="check", description="Kiểm Tra Link")
async def cmd_check(interaction: discord.Interaction):
    await _run_command(interaction, run_check)


# ============ LỆNH TIỀN TỐ ! (giữ song song với /) ============
@client.event
async def on_message(message):
    global last_output_messages
    if message.author.bot:
        return

    content = message.content.strip()
    if content not in ("!", "!scan", "!check"):
        return

    out_channel = await get_output_channel()

    try:
        await message.delete()
    except Exception:
        pass

    await delete_old_output_messages()

    sent = []
    if content == "!":
        m = await out_channel.send(get_help_embed())
        sent = [m]
    elif content == "!scan":
        sent = await run_scan(out_channel)
    elif content == "!check":
        sent = await run_check(out_channel)

    last_output_messages = sent
    if sent:
        asyncio.create_task(schedule_delete_after(DELETE_AFTER_SECONDS, list(sent)))


@client.event
async def on_ready():
    await tree.sync()
    print(f"Bot ready: {client.user}")


if __name__ == "__main__":
    if not (TOKEN and TOKEN.strip()):
        print("Chưa có token. Đặt biến môi trường DISCORD_BOT_TOKEN hoặc sửa TOKEN trong discord_bot.py")
        print("Lấy token: https://discord.com/developers/applications → chọn app → Bot → Reset Token → Copy")
        raise SystemExit(1)
    try:
        client.run(TOKEN)
    except discord.LoginFailure:
        print("Token không hợp lệ (401 Unauthorized). Token có thể đã bị reset hoặc hết hạn.")
        print("Vào https://discord.com/developers/applications → Application của bạn → Bot → Reset Token")
        print("Copy token mới và: đặt DISCORD_BOT_TOKEN trong môi trường, hoặc dán vào TOKEN trong discord_bot.py")
        raise SystemExit(1)
