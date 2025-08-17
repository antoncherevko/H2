import os, asyncio, yaml, hashlib
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import aiohttp
from bs4 import BeautifulSoup
from utils import init_db, add_subscriber, remove_subscriber, list_subscribers, seen_article, is_seen, fetch_newsapi, parse_rss_feed, classify_by_keywords, deduplicate_items

BASE_DIR = os.path.dirname(__file__)
CONFIG = yaml.safe_load(open(os.path.join(BASE_DIR, "config.yaml")))
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")  # Добавьте в .env
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")  # Добавьте в .env

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

async def scrape_linkedin_posts(company):
    """Парсинг публичных постов с LinkedIn (простой пример, настройте селекторы)"""
    url = f"https://www.linkedin.com/company/{company.lower()}/posts/?feedView=all"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return []
            html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")
            results = []
            for post in soup.find_all("div", class_="feed-shared-update-v2"):  # Пример селектора, может измениться
                title = post.find("span", class_="feed-shared-actor__name") or "No title"
                title = title.text.strip() if title else "No title"
                summary = post.find("p", class_="feed-shared-text") or ""
                summary = summary.text.strip() if summary else ""
                link = post.find("a", class_="app-aware-link") or ""
                link = link.get("href") if link else ""
                if "hydrogen" in summary.lower() or "h2" in summary.lower():
                    results.append({"title": title, "summary": summary, "url": link})
            return results[:5]

@dp.message(Command("linkedin"))
async def cmd_linkedin(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /linkedin Linde")
        return
    company = args[1].lower()
    await message.answer(f"Searching LinkedIn for {company} hydrogen news...")
    items = await scrape_linkedin_posts(company)
    await format_and_send_list(message.chat.id, items, limit=5)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hello! I am H2 Hydrogen Bot.\n\n"
        "Commands:\n"
        "/feed - latest hydrogen news\n"
        "/announcements - latest press releases from tracked RSS\n"
        "/company <name> - news about a company\n"
        "/companies - latest news from configured companies\n"
        "/topic <keyword> - news about a topic\n"
        "/linkedin <company> - posts from LinkedIn\n"
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
    google_items = await google_search(f'{company} hydrogen', num=5)
    items += google_items
    items = deduplicate_items(items)
    await format_and_send_list(message.chat.id, items, limit=6)

@dp.message(Command("companies"))
async def cmd_companies(message: types.Message):
    companies = CONFIG.get("companies", [])
    if not companies:
        await message.answer("No companies configured.")
        return

    await message.answer("📡 Fetching latest company news...")
    all_items = []
    for company in companies:
        await asyncio.sleep(1)  # Задержка 1 секунда между компаниями
        try:
            # Поиск в NewsAPI
            articles = await fetch_newsapi(f'hydrogen AND "{company}"', page_size=3)
            news_items = [
                {"title": a.get("title"),
                 "summary": a.get("description"),
                 "url": a.get("url"),
                 "publishedAt": a.get("publishedAt"),
                 "company": company}
                for a in articles
            ]
            all_items += news_items

            # Поиск в Google
            google_items = await google_search(f'{company} hydrogen', num=2)
            for g in google_items:
                g["company"] = company
            all_items += google_items

            # Поиск в LinkedIn
            linkedin_items = await scrape_linkedin_posts(company)
            for l in linkedin_items:
                l["company"] = company
            all_items += linkedin_items
        except Exception as e:
            print(f"Error processing {company}: {e}")
            continue

    # Убираем дубликаты
    all_items = deduplicate_items(all_items)

    if not all_items:
        await message.answer("No recent company news found.")
        return

    # Формируем и отправляем
    for it in all_items[:15]:
        title = it.get("title") or "No title"
        url = it.get("url") or ""
        summary = it.get("summary") or ""
        company = it.get("company", "")
        text = f"🏭 <b>{company}</b>\n{title}\n{summary}\n{url}"
        await message.answer(text, parse_mode='HTML')

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
