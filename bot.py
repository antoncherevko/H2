import os, asyncio, yaml, hashlib
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import aiohttp
from utils import init_db, add_subscriber, remove_subscriber, list_subscribers, seen_article, is_seen, fetch_newsapi, parse_rss_feed, classify_by_keywords, deduplicate_items

BASE_DIR = os.path.dirname(__file__)
CONFIG = yaml.safe_load(open(os.path.join(BASE_DIR, "config.yaml")))
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN in environment")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

KEYWORDS = CONFIG.get("keywords", [])

async def format_and_send_list(chat_id, items, limit=5):
    if not items:
        await bot.send_message(chat_id, "No items found.")
        return
    for it in items[:limit]:
        title = it.get("title") or "No title"
        url = it.get("url") or it.get("link") or ""
        summary = it.get("summary") or ""
        topics = classify_by_keywords(title + " " + summary, KEYWORDS)
        text = f"📰 <b>{title}</b>\n{', '.join(topics)}\n{summary}\n{url}"
        await bot.send_message(chat_id, text, parse_mode='HTML')

async def google_search(query, num=5):
    """Поиск в Google через Custom Search API"""
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        return []
    url = f"https://www.googleapis.com/customsearch/v1?q={query}&key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}&num={num}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            results = []
            for item in data.get("items", []):
                results.append({
                    "title": item["title"],
                    "summary": item.get("snippet"),
                    "url": item["link"]
                })
            return results

@dp.message(Command("search"))
async def cmd_search(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /search hydrogen storage")
        return
    query = args[1]
    await message.answer(f"🔎 Searching the web: {query}")
    items = await google_search(query, num=6)
    await format_and_send_list(message.chat.id, items, limit=6)

async def scrape_press_releases(url):
    """Пример простого парсинга страницы"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")
            results = []
            for a in soup.select("a"):  # Настроить под конкретный сайт
                title = a.get_text().strip()
                link = a.get("href")
                if title and link:
                    results.append({"title": title, "url": link})
            return results[:10]

@dp.message(Command("press"))
async def cmd_press(message: types.Message):
    await message.answer("Fetching press releases...")
    url = "https://www.linde.com/news"  # пример
    items = await scrape_press_releases(url)
    await format_and_send_list(message.chat.id, items, limit=6)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hello! I am H2 Hydrogen Bot.\n\n"
        "Commands:\n"
        "/feed - latest hydrogen news\n"
        "/announcements - latest press releases from tracked RSS\n"
        "/company <name> - news about a company\n"
        "/topic <keyword> - news about a topic\n"
        "/subscribe - daily digest\n"
        "/unsubscribe - stop digest\n"
    )

@dp.message(Command("feed"))
async def cmd_feed(message: types.Message):
    await message.answer("Fetching latest news...")
    q = "hydrogen OR H2 OR ammonia OR electrolyzer OR fuel cell"
    articles = await fetch_newsapi(q, page_size=10)
    items = []
    for a in articles:
        items.append({"title": a.get("title"), "summary": a.get("description"), "url": a.get("url"), "publishedAt": a.get("publishedAt")})
    items = deduplicate_items(items)
    await format_and_send_list(message.chat.id, items, limit=6)

@dp.message(Command("announcements"))
async def cmd_announcements(message: types.Message):
    await message.answer("Fetching RSS announcements...")
    feeds = CONFIG.get("rss_feeds", [])
    all_items = []
    for f in feeds:
        try:
            items = parse_rss_feed(f, max_items=8)
            for it in items:
                it["source"] = f
            all_items += items
        except Exception:
            pass
    items = deduplicate_items(all_items)
    await format_and_send_list(message.chat.id, items, limit=6)

@dp.message(Command("company"))
async def cmd_company(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /company Linde")
        return
    company = args[1]
    await message.answer(f"Searching news for {company}...")
    articles = await fetch_newsapi(f'hydrogen AND "{company}"', page_size=10)
    items = [{"title": a.get("title"), "summary": a.get("description"), "url": a.get("url"), "publishedAt": a.get("publishedAt")} for a in articles]
    items = deduplicate_items(items)
    await format_and_send_list(message.chat.id, items, limit=6)

@dp.message(Command("topic"))
async def cmd_topic(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /topic Electrolyzer")
        return
    topic = args[1]
    articles = await fetch_newsapi(f'hydrogen AND {topic}', page_size=10)
    items = [{"title": a.get("title"), "summary": a.get("description"), "url": a.get("url"), "publishedAt": a.get("publishedAt")} for a in articles]
    items = deduplicate_items(items)
    await format_and_send_list(message.chat.id, items, limit=6)

@dp.message(Command("subscribe"))
async def cmd_subscribe(message: types.Message):
    add_subscriber(message.from_user.id)
    await message.answer("✅ Subscribed to daily digest.")

@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: types.Message):
    remove_subscriber(message.from_user.id)
    await message.answer("❌ Unsubscribed.")

async def daily_digest():
    subs = list_subscribers()
    if not subs:
        return
    q = "hydrogen OR electrolyzer OR fuel cell OR HRS OR ammonia OR FID OR investment OR financing"
    articles = await fetch_newsapi(q, page_size=5)
    items = [{"title": a.get("title"), "summary": a.get("description"), "url": a.get("url"), "publishedAt": a.get("publishedAt")} for a in articles]
    items = deduplicate_items(items)
    for s in subs:
        try:
            await format_and_send_list(s, items, limit=5)
        except Exception:
            pass

def run_scheduler():
    scheduler.add_job(daily_digest, "interval", hours=24, id="daily_digest")
    scheduler.start()

async def main():
    init_db()
    run_scheduler()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
