FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt --only-binary :all:

COPY . .

CMD ["python", "bot.py"]
