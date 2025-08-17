H2 Hydrogen Telegram Bot - Extended version
==========================================

What is included
-----------------
- bot.py : main Telegram bot (aiogram) with NewsAPI + RSS + keyword classification + deduplication
- utils.py : helper functions (DB for subscribers, NewsAPI fetch, RSS parse, dedup, classify)
- config.yaml : list of companies, RSS feeds, keywords
- requirements.txt : Python dependencies

How to run
----------
1. Unzip the project and change to the bot directory:
   ```bash
   cd bot
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate     # Windows: .venv\\Scripts\\activate
   pip install -r requirements.txt
   ```

3. Create a `.env` file (or export env variables) with:
   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token_from_BotFather
   NEWSAPI_KEY=your_newsapi_key_from_newsapi.org
   ```

4. (Optional) Edit `config.yaml` to add/remove RSS feeds, companies, and keywords.

5. Run the bot:
   ```bash
   python bot.py
   ```

Commands in Telegram
-------------------
- `/start` - welcome and help
- `/feed` - latest hydrogen news (NewsAPI)
- `/announcements` - recent press releases (RSS feeds)
- `/company <name>` - news filtered by company name
- `/topic <keyword>` - news filtered by a keyword/topic
- `/subscribe` - subscribe to daily digest
- `/unsubscribe` - stop digest

Notes and next steps
--------------------
- The bot stores subscribers and seen articles in `bot_data.sqlite3` in the bot folder so subscriptions survive restarts.
- You can expand `config.yaml` with more RSS feeds and keywords relevant to hydrogen projects.
- For LinkedIn/Facebook integration you will need official API access and extra code (not included here).
- Consider deploying the bot on a server (DigitalOcean, AWS, Heroku) with a scheduler for continuous operation.
