# Используем Python 3.12, так как он более стабилен для scikit-learn
FROM python:3.12-slim

# Устанавливаем системные зависимости для компиляции scikit-learn (если потребуется)
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libopenblas-dev \
    liblapack-dev \
    gfortran \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Обновляем pip и устанавливаем зависимости
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Указываем команду для запуска бота
CMD ["python", "bot.py"]
