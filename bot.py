import os
import asyncio
import yaml
import hashlib
import re
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from openai import AsyncOpenAI
from utils import init_db, add_subscriber, remove_subscriber, list_subscribers, seen_article, is_seen, parse_rss_feed, classify_by_keywords, deduplicate_items

BASE_DIR = os.path.dirname(__file__)
CONFIG = yaml.safe_load(open(os.path.join(BASE_DIR, "config.yaml")))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN in environment")
if not DEEPSEEK_API_KEY:
    raise RuntimeError("Set DEEPSEEK_API_KEY in environment")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

KEYWORDS = CONFIG.get("keywords", [])

# Настройка клиента DeepSeek
ai_client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1"
)

# Создание клавиатуры
main_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
main_keyboard.add(KeyboardButton("/feed"))
main_keyboard.add(KeyboardButton("/announcements"))
main_keyboard.add(KeyboardButton("/companies"))
main_keyboard.add(KeyboardButton("/subscribe"))
main_keyboard.add(KeyboardButton("/unsubscribe"))

async def query_deepseek(prompt):
    """Запрос к DeepSeek API для генерации или суммирования новостей"""
    try:
        response = await ai_client.chat.completions.create(
            model="deepseek-r1:free",  # Бесплатная модель
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=500
        )
        content = response.choices[0].message.content.strip()
        # Парсинг ответа в формат {title, summary, url}
        items = []
        for block in content.split("\n\n"):
            lines = block.split("\n")
            if len(lines) >= 3:
                items.append({
                    "title": lines[0].replace("**", "").strip(),
                    "summary": lines[1].strip(),
                    "url": lines[2].strip() if len(lines) > 2 and lines[2].startswith("http") else ""
                })
        print(f"DeepSeek query: {prompt}, results: {len(items)}")
        return items
    except Exception as e:
        print(f"Error querying DeepSeek: {e}")
        return []

async def format_and_send_list(chat_id, items, limit=5):
    if not items:
        await bot.send_message(chat_id, "No items found.")
        return
    for it in items[:limit]:
        title = it.get("title") or "No title"
        url = it.get("url") or it.get("link") or ""
        summary = it.get("summary") or ""
        title = re.sub(r'<sub>', 'H2', title)
        title = re.sub(r'</sub>', '', title)
        summary = re.sub(r'<sub>', 'H2', summary)
        summary = re.sub(r'</sub>', '', summary)
        title = re.sub(r'<(?!b|i|a|code|pre|s|u|tg-spoiler|tg-emoji)[^>]+>', '', title)
        summary = re.sub(r'<(?!b|i|a|code|pre|s|u|tg-spoiler|tg-emoji)[^>]+>', '', summary)
        topics = classify_by_keywords(title + " " + summary, KEYWORDS)
        text = f"📰 <b>{title}</b>\n{', '.join(topics)}\n{summary}\n{url}"
        try:
            await bot.send_message(chat_id, text, parse_mode='HTML')
        except Exception as e:
            print(f"Error sending message to {chat_id}: {e}")
            text = f"📰 {title}\n{', '.join(topics)}\n{summary}\n{url}"
            await bot.send_message(chat_id, text)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Hello! I am H2 Hydrogen Bot.\n\n"
        "Commands:\n"
        "/feed - latest hydrogen news\n"
        "/announcements - latest press releases from RSS\n"
        "/company <name> - news about a company\n"
        "/companies - news from configured companies\n"
        "/topic <keyword> - news about a topic\n"
        "/subscribe - daily digest\n"
        "/unsubscribe - stop digest\n",
        reply_markup=main_keyboard
    )

@dp.message(Command("feed"))
async def cmd_feed(message: types.Message):
    await message.answer("Fetching latest news...")
    prompt = "Summarize the latest hydrogen news (H2, ammonia, electrolyzer, fuel cell). Provide 6 items, each with a title, summary, and source URL."
    items = await query_deepseek(prompt)
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
        except Exception as e:
            print(f"Error parsing RSS feed {f}: {e}")
    items = deduplicate_items(all_items)
    print(f"RSS feeds results: {len(items)}")
    await format_and_send_list(message.chat.id, items, limit=6)

@dp.message(Command("company"))
async def cmd_company(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /company Linde")
        return
    company = args[1]
    await message.answer(f"Searching news for {company}...")
    prompt = f"Summarize the latest hydrogen-related news for {company}. Provide 6 items, each with a title, summary, and source URL."
    items = await query_deepseek(prompt)
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
        await asyncio.sleep(1)
        try:
            prompt = f"Summarize the latest hydrogen-related news for {company}. Provide 3 items, each with a title, summary, and source URL."
            items = await query_deepseek(prompt)
            for item in items:
                item["company"] = company
            all_items += items
        except Exception as e:
            print(f"Error processing {company}: {e}")
            continue
    all_items = deduplicate_items(all_items)
    if not all_items:
        await message.answer("No recent company news found.")
        return
    for it in all_items[:15]:
        title = it.get("title") or "No title"
        url = it.get("url") or ""
        summary = it.get("summary") or ""
        company = it.get("company", "")
        text = f"🏭 <b>{company}</b>\n{title}\n{summary}\n{url}"
        await format_and_send_list(message.chat.id, [it], limit=1)

@dp.message(Command("topic"))
async def cmd_topic(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /topic Electrolyzer")
        return
    topic = args[1]
    await message.answer(f"Searching news for {topic}...")
    prompt = f"Summarize the latest hydrogen-related news on {topic}. Provide 6 items, each with a title, summary, and source URL."
    items = await query_deepseek(prompt)
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
    prompt = "Summarize today's hydrogen news (H2, ammonia, electrolyzer, fuel cell, investment). Provide 5 items, each with a title, summary, and source URL."
    items = await query_deepseek(prompt)
    items = deduplicate_items(items)
    for s in subs:
        try:
            await format_and_send_list(s, items, limit=5)
        except Exception as e:
            print(f"Error sending digest to {s}: {e}")

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
