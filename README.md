# Бот «Массаж будущего» — Михаил Новосёлов (Сочи)

Telegram-бот с воронкой продаж, лид-магнитом, записью и распознаванием голоса.

## Возможности

- **Воронка продаж**: приветствие → лид-магнит → услуги → запись
- **Лид-магнит**: бесплатный гайд «5 признаков, что телу нужна помощь»
- **Услуги**: Первая встреча (5000 ₽), Массаж будущего (10000 ₽), Курс 4 сеанса (30000 ₽)
- **Свободные слоты** с учётом длительности
- **Ссылки** на Dikidi и сайт
- **Обо мне** + контакты
- Заявки в SQLite + уведомление админу

## Ссылки в боте

- Сайт: https://massage-future-sochi.ru/
- Dikidi: https://dikidi.ru/1237678
- Прямая запись на первую встречу: https://dkd.su/1237678/s/22603980
- Адрес: ул. Несебрская, 4, центр Сочи

## Запуск

```bash

cd telegram_booking_bot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Впишите BOT_TOKEN и ADMIN_ID

python bot.py
```

## Меню бота

- 📅 Записаться
- 🎁 Бесплатный гайд (лид-магнит)
- 👤 Обо мне
- 💅 Услуги и цены
- 📋 Мои записи
- ℹ️ Контакты

Готово к использованию.

## Railway deployment

Проект использует Dockerfile и Python 3.12 (Debian Bookworm). Railway должен собирать Dockerfile напрямую; runtime.txt не используется.

Required variables in Railway:
- BOT_TOKEN
- ADMIN_ID

Start command is already defined in Dockerfile: `python -u bot.py`.
