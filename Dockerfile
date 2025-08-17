FROM python:3.12-slim

# Установка инструментов для компиляции sgmllib3k
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip
# Устанавливаем зависимости, но для feedparser убираем --only-binary
RUN pip install --no-cache-dir -r requirements.txt
# Отдельно устанавливаем sgmllib3k, если нужно
RUN pip install --no-cache-dir sgmllib3k

COPY . .

CMD ["python", "bot.py"]
