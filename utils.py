import os, hashlib, json, time, sqlite3
from datetime import datetime, timezone
import aiohttp, feedparser
from bs4 import BeautifulSoup
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DB_PATH = os.path.join(os.path.dirname(__file__), "bot_data.sqlite3")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS subscribers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS seen_articles (
        id TEXT PRIMARY KEY,
        url TEXT,
        title TEXT,
        published_at TIMESTAMP
    )""")
    conn.commit()
    conn.close()

def add_subscriber(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO subscribers(chat_id) VALUES(?)", (chat_id,))
    conn.commit()
    conn.close()

def remove_subscriber(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM subscribers WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()

def list_subscribers():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT chat_id FROM subscribers")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows

def seen_article(id, url, title, published_at):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO seen_articles(id,url,title,published_at) VALUES(?,?,?,?)",
                (id, url, title, published_at))
    conn.commit()
    conn.close()

def is_seen(id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM seen_articles WHERE id=?", (id,))
    found = cur.fetchone() is not None
    conn.close()
    return found

# --- NewsAPI fetch ---
NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

async def fetch_newsapi(query, page_size=10):
    if not NEWSAPI_KEY:
        return []
    params = {"q": query, "pageSize": page_size, "language": "en", "sortBy": "publishedAt", "apiKey": NEWSAPI_KEY}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(NEWSAPI_URL, params=params, timeout=20) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("articles", [])
        except Exception:
            return []

# --- RSS fetch ---
def safe_text(s):
    if not s:
        return ""
    return " ".join(s.split())

def parse_rss_feed(url, max_items=10):
    try:
        d = feedparser.parse(url)
        items = []
        for e in d.entries[:max_items]:
            link = e.get("link","")
            title = safe_text(e.get("title",""))
            summary = safe_text(e.get("summary","") or e.get("description",""))
            summary = BeautifulSoup(summary, "html.parser").get_text()
            published = None
            if e.get("published_parsed"):
                from time import mktime
                published = datetime.fromtimestamp(mktime(e.published_parsed), timezone.utc).isoformat()
            items.append({"url": link, "title": title, "summary": summary, "publishedAt": published})
        return items
    except Exception:
        return []

# --- Simple classification by keywords ---
def classify_by_keywords(text, keywords):
    found = []
    lower = (text or "").lower()
    for k in keywords:
        if k.lower() in lower:
            found.append(k)
    # unique
    return list(dict.fromkeys(found))

# --- Deduplication using TF-IDF cosine similarity ---
def deduplicate_items(items, threshold=0.82):
    if not items:
        return items
    texts = [(i.get("title","") + " " + (i.get("summary") or "")) for i in items]
    try:
        vec = TfidfVectorizer(stop_words="english", max_features=5000).fit_transform(texts)
        sim = cosine_similarity(vec)
        keep = []
        seen = set()
        for i in range(len(items)):
            if i in seen: continue
            group = [j for j in range(len(items)) if sim[i][j] > threshold]
            # choose latest by publishedAt if available else first
            chosen = group[0]
            best_time = 0
            for j in group:
                pub = items[j].get("publishedAt")
                try:
                    ts = datetime.fromisoformat(pub).timestamp() if pub else 0
                except Exception:
                    ts = 0
                if ts > best_time:
                    best_time = ts
                    chosen = j
            keep.append(items[chosen])
            seen.update(group)
        return keep
    except Exception:
        seen_urls = set()
        out = []
        for it in items:
            u = it.get("url") or ""
            if u in seen_urls: continue
            seen_urls.add(u)
            out.append(it)
        return out
