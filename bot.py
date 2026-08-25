"""
Telegram-бот «Массаж будущего» — Михаил Новосёлов, Сочи
Python + aiogram 3 + SQLite

Воронка:
1. Приветствие + лид-магнит
2. Ценность / обо мне
3. Услуги + мягкий оффер
4. Запись (свободные слоты) или переход в Dikidi
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from certificate import generate_certificate
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv

# ==================== НАСТРОЙКИ ====================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")  # Ваш Telegram ID

if not BOT_TOKEN:
    raise ValueError("Укажите BOT_TOKEN в файле .env")

# ===== Реальные услуги =====
SERVICES = {
    "Первая встреча": {"price": 5000, "duration_min": 40},
    "Массаж будущего": {"price": 10000, "duration_min": 75},
    "Курс 4 сеанса": {"price": 30000, "duration_min": 75},
}

# Ссылки и контакты
WEBSITE = "https://massage-future-sochi.ru/"
DIKIDI = "https://dikidi.ru/1237678"
DIKIDI_FIRST = "https://dikidi.ru/1237678"  # Онлайн-запись (полная ссылка)
ADDRESS = "ул. Несебрская, 4, центр Сочи"
PHONE = "+7 (999) 656-12-34"
REVIEW_2GIS = "https://2gis.ru/sochi/geo/70000001094480075"
REVIEW_YANDEX = "https://yandex.ru/maps/org/massazh_budushchego/148188812126"
TG_CONTACT = "https://t.me/massage_futures"

# Рабочие часы
WORK_START_HOUR = 10
WORK_END_HOUR = 20
SLOT_STEP_MINUTES = 30

DB_PATH = Path(__file__).parent / "bookings.db"

# ==================== ЛОГИРОВАНИЕ ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ==================== FSM ====================

class BookingStates(StatesGroup):
    choosing_service = State()
    entering_date = State()
    choosing_time = State()
    entering_name = State()
    entering_phone = State()
    confirmation = State()


class CertStates(StatesGroup):
    recipient = State()
    massage_type = State()
    quantity = State()
    valid_until = State()
    send_to = State()


# ==================== БАЗА ДАННЫХ ====================

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                service TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                duration_min INTEGER NOT NULL DEFAULT 60,
                client_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                first_name TEXT,
                got_magnet INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def save_lead(user_id: int, username: str | None, first_name: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO leads (user_id, username, first_name, got_magnet)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET got_magnet = 1
            """,
            (user_id, username, first_name),
        )
        await db.commit()


async def add_booking(user_id, username, service, date, time, duration_min, client_name, phone) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO bookings
            (user_id, username, service, date, time, duration_min, client_name, phone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, username, service, date, time, duration_min, client_name, phone),
        )
        await db.commit()
        return cursor.lastrowid


async def get_user_bookings(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, service, date, time, client_name, phone, status
            FROM bookings WHERE user_id = ? AND status = 'active'
            ORDER BY date, time
            """,
            (user_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def cancel_booking(booking_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE bookings SET status = 'cancelled' WHERE id = ? AND user_id = ? AND status = 'active'",
            (booking_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_bookings_for_date(date: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT time, duration_min FROM bookings WHERE date = ? AND status = 'active'",
            (date,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def admin_metrics(days: int = 30) -> dict:
    days = max(days, 1)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM leads")
        leads_total = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM leads WHERE created_at >= datetime('now', ?)", (f"-{days} days",))
        leads_period = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM bookings")
        bookings_total = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM bookings WHERE status = 'active'")
        active_bookings = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM bookings WHERE status = 'cancelled'")
        cancelled_bookings = (await cursor.fetchone())[0]
        cursor = await db.execute(
            "SELECT COUNT(*) FROM bookings WHERE created_at >= datetime('now', ?)",
            (f"-{days} days",),
        )
        bookings_period = (await cursor.fetchone())[0]
    conversion = round(bookings_period * 100 / leads_period, 1) if leads_period else 0.0
    return {
        "days": days,
        "leads_total": leads_total,
        "leads_period": leads_period,
        "bookings_total": bookings_total,
        "bookings_period": bookings_period,
        "active_bookings": active_bookings,
        "cancelled_bookings": cancelled_bookings,
        "lead_to_booking_percent": conversion,
    }


def score_items(metrics: dict) -> list[dict]:
    items: list[dict] = []

    def add(name: str, points: int, max_points: int, status: str, next_step: str) -> None:
        items.append({
            "name": name,
            "points": points,
            "max_points": max_points,
            "status": status,
            "next_step": next_step,
        })

    add(
        "Инфраструктура",
        (5 if BOT_TOKEN else 0) + (4 if ADMIN_ID else 0) + (3 if DB_PATH.exists() else 0),
        12,
        "ok" if BOT_TOKEN and ADMIN_ID and DB_PATH.exists() else "needs_setup",
        "Проверить BOT_TOKEN, ADMIN_ID и доступность SQLite-базы.",
    )
    add(
        "Воронка продаж",
        17,
        20,
        "ok",
        "Усилить первый экран: больше заботы, диагностика и быстрый переход к записи.",
    )
    add(
        "Запись",
        12,
        16,
        "manual_plus_dikidi",
        "Подключить реальный API Dikidi, когда будет доступ; пока работает локальная запись и ссылка.",
    )
    add(
        "Доверие",
        13,
        14,
        "ok",
        "Добавить больше кейсов, сертификатов и коротких отзывов прямо в ответы.",
    )
    add(
        "Голос",
        2,
        10,
        "needs_voice",
        "Добавить voice-ответы для приветствия, цены, записи и отличия метода.",
    )
    analytics_points = 5
    if metrics["leads_period"] >= 10:
        analytics_points += 3
    if metrics["lead_to_booking_percent"] > 0:
        analytics_points += 4
    add(
        "Аналитика",
        analytics_points,
        14,
        "ok" if analytics_points >= 10 else "needs_data",
        "Смотреть /score каждую неделю: лиды, заявки и конверсию лид -> запись.",
    )
    add(
        "Операционное управление",
        8,
        14,
        "basic",
        "Добавить задачи администратора: кому перезвонить, кого вернуть, кто ждёт подтверждения.",
    )
    return items


def bot_score_text(metrics: dict) -> str:
    items = score_items(metrics)
    points = sum(item["points"] for item in items)
    max_points = sum(item["max_points"] for item in items)
    score = round(points * 10 / max_points, 1)
    top_actions = sorted(items, key=lambda item: item["max_points"] - item["points"], reverse=True)[:3]
    lines = [
        f"Оценка бота: {score}/10",
        f"Баллы: {points}/{max_points}",
        "",
        f"За {metrics['days']} дн.: лиды {metrics['leads_period']}, заявки {metrics['bookings_period']}, "
        f"конверсия {metrics['lead_to_booking_percent']}%",
        f"Всего: лиды {metrics['leads_total']}, заявки {metrics['bookings_total']}, "
        f"активные {metrics['active_bookings']}, отмены {metrics['cancelled_bookings']}",
        "",
        "Разбор:",
    ]
    for item in items:
        lines.append(f"- {item['name']}: {item['points']}/{item['max_points']} ({item['status']})")
    lines.append("")
    lines.append("Что улучшить первым:")
    for index, item in enumerate(top_actions, start=1):
        lines.append(f"{index}. {item['name']}: {item['next_step']}")
    lines.append("")
    lines.append("Команды: /score, /orchestra <задача>, /cert")
    return "\n".join(lines)


ORCHESTRA_ROLES = (
    {
        "name": "Контент-агент",
        "triggers": ("текст", "пост", "привет", "скрипт", "оффер", "лендинг", "гайд"),
        "task": "собрать понятный текст с заботой, ценностью и мягким призывом к записи",
        "result": "черновик текста и 2 варианта CTA",
        "skills": "copywriting, редактура",
    },
    {
        "name": "Агент продаж",
        "triggers": ("продаж", "клиент", "лид", "заявк", "цена", "запис", "сертификат"),
        "task": "понять стадию клиента, возражение и лучший следующий шаг",
        "result": "предложение и безопасный CTA",
        "skills": "квалификация, возражения, оффер",
    },
    {
        "name": "Операционный агент",
        "triggers": ("задач", "crm", "таблиц", "напомин", "админ", "статус", "контроль"),
        "task": "разложить работу на задачи, сроки и статусы",
        "result": "план действий и контрольные точки",
        "skills": "CRM, automation, контроль сроков",
    },
    {
        "name": "Исследователь",
        "triggers": ("сайт", "отзыв", "конкур", "источник", "провер", "факт"),
        "task": "проверить факты, ссылки и неизвестные места",
        "result": "краткая справка: факты, гипотезы, что уточнить",
        "skills": "web research, fact check",
    },
)


def orchestra_text(task: str) -> str:
    clean_task = task.strip() or "задача не указана"
    value = clean_task.lower()
    selected = [
        role for role in ORCHESTRA_ROLES
        if any(trigger in value for trigger in role["triggers"])
    ][:2]
    if not selected:
        selected = [ORCHESTRA_ROLES[1]]

    lines = [
        "Агент-оркестратор",
        "",
        f"Цель: {clean_task}",
        "",
        "Процесс:",
        "1. Принять задачу и ожидаемый результат.",
        "2. Взять минимальную цепочку: оркестратор, 1-2 субагента, контролёр.",
        "3. Передать каждому только нужные данные и минимальные права.",
        "4. Собрать результат и проверить факты, тон, ограничения.",
        "5. Финальное действие подтверждает человек.",
        "",
        "Поручения:",
        "1. Оркестратор: держит цель, порядок и финальную сборку.",
    ]
    for index, role in enumerate(selected, start=2):
        lines.append(
            f"{index}. {role['name']}: {role['task']}.\n"
            f"   Скиллы: {role['skills']}.\n"
            f"   Результат: {role['result']}."
        )
    lines.append(
        f"{len(selected) + 2}. Контролёр: проверяет факты, тон, риски и соответствие задаче."
    )
    lines.extend([
        "",
        "Правило безопасности:",
        "- субагенты не отправляют сообщения клиентам самостоятельно;",
        "- не публикуют посты;",
        "- не меняют цены и скидки;",
        "- не удаляют данные и не меняют записи без подтверждения администратора.",
    ])
    return "\n".join(lines)


# ==================== СЛОТЫ ====================

def generate_possible_slots(duration_min: int) -> list[str]:
    slots = []
    current = datetime.strptime(f"{WORK_START_HOUR:02d}:00", "%H:%M")
    end = datetime.strptime(f"{WORK_END_HOUR:02d}:00", "%H:%M")
    while current + timedelta(minutes=duration_min) <= end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=SLOT_STEP_MINUTES)
    return slots


def time_to_minutes(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def is_slot_free(slot: str, duration_min: int, occupied: list) -> bool:
    start = time_to_minutes(slot)
    end = start + duration_min
    for b in occupied:
        bs = time_to_minutes(b["time"])
        be = bs + b["duration_min"]
        if start < be and end > bs:
            return False
    return True


async def get_free_slots(date: str, duration_min: int) -> list[str]:
    all_slots = generate_possible_slots(duration_min)
    occupied = await get_bookings_for_date(date)
    free = [s for s in all_slots if is_slot_free(s, duration_min, occupied)]
    today = datetime.now().strftime("%d.%m.%Y")
    if date == today:
        now = datetime.now().hour * 60 + datetime.now().minute
        free = [s for s in free if time_to_minutes(s) > now + 30]
    return free


# ==================== КЛАВИАТУРЫ ====================

def main_menu_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📅 Записаться"))
    builder.row(
        KeyboardButton(text="🎁 5 признаков"),
        KeyboardButton(text="🧘 Упражнения для шеи"),
    )
    builder.row(
        KeyboardButton(text="👤 Обо мне"),
        KeyboardButton(text="💅 Услуги и цены"),
    )
    builder.row(
        KeyboardButton(text="🎟 Сертификат"),
        KeyboardButton(text="⭐ Отзывы"),
    )
    builder.row(
        KeyboardButton(text="📋 Мои записи"),
        KeyboardButton(text="ℹ️ Контакты"),
    )
    return builder.as_markup(resize_keyboard=True)


def services_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    for name in SERVICES:
        builder.add(KeyboardButton(text=name))
    builder.adjust(1)
    builder.row(KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardBuilder().add(KeyboardButton(text="❌ Отмена")).as_markup(resize_keyboard=True)


def confirm_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="✅ Подтвердить"), KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True)


def free_slots_kb(slots: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in slots:
        builder.add(InlineKeyboardButton(text=s, callback_data=f"slot_{s}"))
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="slot_cancel"))
    return builder.as_markup()


def my_bookings_inline(bookings: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in bookings:
        builder.row(InlineKeyboardButton(
            text=f"❌ Отменить #{b['id']} ({b['service']} {b['date']})",
            callback_data=f"cancel_{b['id']}",
        ))
    return builder.as_markup()


def dikidi_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📅 Записаться в Dikidi", url=DIKIDI_FIRST))
    builder.row(InlineKeyboardButton(text="🌐 Сайт", url=WEBSITE))
    return builder.as_markup()


def after_magnet_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📅 Записаться на первую встречу", url=DIKIDI_FIRST))
    builder.row(InlineKeyboardButton(text="💅 Посмотреть услуги", callback_data="show_services"))
    return builder.as_markup()


# ==================== РОУТЕР ====================

router = Router()


# ---------- /start + воронка ----------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    name = message.from_user.first_name or "друг"

    text = (
        f"👋 Привет, {name}!\n\n"
        "Я бот Михаила Новосёлова — автора метода <b>«Массаж будущего»</b> в Сочи.\n\n"
        "Здесь можно:\n"
        "• Получить <b>бесплатные гайды</b> по снятию напряжения\n"
        "• Узнать обо мне и методе\n"
        "• Посмотреть услуги и записаться\n\n"
        "С чего начнём?"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())


# ---------- Лид-магниты ----------

@router.message(F.text == "🎁 5 признаков")
async def lead_magnet_signs(message: Message, state: FSMContext):
    await state.clear()
    await save_lead(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    guide = (
        "🎁 <b>«5 признаков, что ваше тело уже просит о помощи»</b>\n\n"
        "Иногда мы так привыкаем к тяжести, что считаем её нормой. "
        "А тело давно шепчет: «Хватит так жить».\n\n"
        "1. <b>К вечеру шея и плечи будто каменные.</b>\n"
        "Даже если день был обычным. Хочется растереть, размять, "
        "но облегчение приходит лишь на час — и всё возвращается.\n\n"
        "2. <b>Поясница «напоминает о себе»</b> при каждом наклоне "
        "или после долгого сидения. Как будто внутри что-то стянуло.\n\n"
        "3. <b>Тело затекает.</b>\n"
        "Сложно свободно разогнуться. Каждые 15–20 минут хочется "
        "потянуться — и даже это не даёт настоящей лёгкости.\n\n"
        "4. <b>После тренировок или дороги</b> мышцы остаются забитыми "
        "гораздо дольше, чем раньше. Восстановление будто замедлилось.\n\n"
        "5. <b>Просто хочется чувствовать себя легче.</b>\n"
        "Без острой боли. Просто чтобы тело снова стало «своим» — "
        "мягким, подвижным, живым.\n\n"
        "────────────────\n"
        "Если узнали себя хотя бы в двух пунктах — это не «просто усталость». "
        "Это сигнал, который стоит услышать.\n\n"
        "На <b>первой встрече</b> (30–40 минут, 5000 ₽) мы не будем "
        "делать «одинаковый массаж для всех». Мы посмотрим, "
        "где именно ваше тело держит напряжение, сделаем первую работу "
        "и вместе поймём, какой путь дальше вам подходит.\n\n"
        "📍 Кабинет в центре Сочи · ул. Несебрская, 4"
    )
    await message.answer(guide, parse_mode="HTML", reply_markup=after_magnet_kb())
    await message.answer(
        "Можете записаться через Dikidi или продолжить в боте 👇",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "🧘 Упражнения для шеи")
async def lead_magnet_exercises(message: Message, state: FSMContext):
    await state.clear()
    await save_lead(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )

    guide = (
        "🧘 <b>3 упражнения, которые подарят шее немного свободы</b>\n"
        "<i>Можно сделать прямо сейчас — займёт всего 5–7 минут</i>\n\n"
        "Иногда достаточно нескольких мягких движений, "
        "чтобы почувствовать: «Ах, вот оно… стало чуть легче».\n\n"
        "<b>1. Мягкие повороты головы</b>\n"
        "Сядьте удобно. Медленно поверните голову вправо — "
        "только до того момента, где ещё комфортно. "
        "Задержитесь на 3–4 секунды, будто даёте шее выдохнуть. "
        "Вернитесь в центр. То же влево. "
        "По 5 раз. Без спешки и без рывков.\n\n"
        "<b>2. «Ушко к плечу»</b>\n"
        "Плавно наклоните голову вправо, словно хотите положить ухо на плечо. "
        "Плечо при этом остаётся спокойным — не поднимайте его. "
        "Почувствуйте, как мягко тянется левая сторона шеи. "
        "5–7 секунд. Повторите влево. По 4 раза с каждой стороны.\n\n"
        "<b>3. Круги плечами</b>\n"
        "Поднимите плечи к ушам → медленно отведите назад → "
        "опустите вниз → вперёд. "
        "8 кругов назад, потом 8 вперёд. Дышите глубоко и спокойно. "
        "Пусть плечи «оттают».\n\n"
        "────────────────\n"
        "Эти движения дают облегчение. Но если напряжение "
        "возвращается снова и снова — тело просит более глубокой поддержки.\n\n"
        "На <b>первой встрече</b> (5000 ₽) мы бережно посмотрим, "
        "где именно оно «держит», и подберём работу именно под вас. "
        "Без одинаковых схем. Только то, что нужно вашему телу сегодня.\n\n"
        "📍 ул. Несебрская, 4, центр Сочи"
    )
    await message.answer(guide, parse_mode="HTML", reply_markup=after_magnet_kb())
    await message.answer(
        "Можете записаться через Dikidi или продолжить в боте 👇",
        reply_markup=main_menu_kb(),
    )


# ---------- Обо мне ----------

@router.message(F.text == "👤 Обо мне")
async def about_me(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "👤 <b>Михаил Новосёлов</b>\n"
        "Массажист и кинезиолог · Автор метода «Массаж будущего»\n\n"
        "• Практика с <b>2000 года</b>\n"
        "• Более <b>10 000 сеансов</b>\n"
        "• Победитель премии <b>2ГИС 2026</b>\n"
        "• Работал с профессиональными спортсменами и известными людьми\n\n"
        "<b>Как проходит работа:</b>\n"
        "1. Анализ движений до сеанса\n"
        "2. Индивидуальный подбор техник под ваше состояние сегодня\n"
        "3. Повторная проверка изменений после\n\n"
        "Техника подбирается под реакцию тела — без одинакового массажа для всех.\n\n"
        f"📍 {ADDRESS}\n"
        f"🌐 {WEBSITE}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=dikidi_kb())
    await message.answer("Выберите действие:", reply_markup=main_menu_kb())


# ---------- Услуги и цены ----------

@router.message(F.text == "💅 Услуги и цены")
@router.callback_query(F.data == "show_services")
async def show_services(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "💅 <b>Услуги и цены</b>\n\n"
        "🔹 <b>Первая встреча</b> — 5 000 ₽\n"
        "30–40 минут. Оценка движений, первая работа, понимание формата дальше.\n\n"
        "🔹 <b>Массаж будущего</b> — 10 000 ₽\n"
        "Индивидуальная работа. Техники под ваше состояние в конкретный день.\n\n"
        "🔹 <b>Курс «Массаж будущего»</b> — 30 000 ₽\n"
        "4 сеанса. Экономия 10 000 ₽. Цена фиксируется при записи.\n"
        "Предоплата 50% · возврат за 24 ч до визита.\n\n"
        "🎁 Подарочный сертификат — от 10 000 ₽\n\n"
        f"📍 {ADDRESS}\n"
        "Только по предварительной записи."
    )

    if isinstance(event, CallbackQuery):
        await event.message.answer(text, parse_mode="HTML", reply_markup=dikidi_kb())
        await event.message.answer("Выберите действие:", reply_markup=main_menu_kb())
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=dikidi_kb())
        await event.answer("Выберите действие:", reply_markup=main_menu_kb())


# ---------- Подарочный сертификат ----------

@router.message(F.text == "🎟 Сертификат")
async def gift_certificate(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "🎟 <b>Подарочный сертификат «Массаж будущего»</b>\n\n"
        "Красивый именной сертификат в PDF — отличный подарок.\n\n"
        "<b>Как оформить:</b>\n"
        "1. Напишите, <b>кому</b> (имя получателя)\n"
        "2. Укажите <b>вид массажа</b> и <b>количество</b> сеансов\n"
        "3. Оплатите от <b>10 000 ₽</b>\n"
        "4. После оплаты получите готовый сертификат (PDF)\n\n"
        "В сертификате:\n"
        "• Имя получателя · вид массажа · число сеансов\n"
        "• Срок действия · контакты для записи\n\n"
        f"Массажист: <b>Новосёлов Михаил Сергеевич</b>\n"
        f"📞 {PHONE}\n"
        f"📍 {ADDRESS}"
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💬 Написать и оформить", url=TG_CONTACT))
    kb.row(InlineKeyboardButton(text="📅 Записаться себе", url=DIKIDI_FIRST))
    await message.answer(text, parse_mode="HTML", reply_markup=kb.as_markup())
    await message.answer("Меню:", reply_markup=main_menu_kb())

    # Уведомление админу, что интересуются сертификатом
    if ADMIN_ID:
        try:
            u = message.from_user
            await message.bot.send_message(
                int(ADMIN_ID),
                f"🎟 Интерес к сертификату\n"
                f"от @{u.username or '—'} (id {u.id}) · {u.first_name or ''}",
            )
        except Exception:
            pass


# ---------- Отзывы ----------

@router.message(F.text == "⭐ Отзывы")
async def reviews_handler(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⭐ Отзыв в 2ГИС", url=REVIEW_2GIS))
    kb.row(InlineKeyboardButton(text="⭐ Отзыв в Яндекс.Картах", url=REVIEW_YANDEX))
    await message.answer(
        "⭐ <b>Отзывы о «Массаже будущего»</b>\n\n"
        "Буду благодарен, если поделитесь впечатлением — "
        "это помогает другим людям найти помощь.\n\n"
        "Оставить отзыв можно здесь:",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await message.answer("Меню:", reply_markup=main_menu_kb())


# ---------- Контакты ----------

@router.message(F.text == "ℹ️ Контакты")
@router.message(Command("help"))
async def contacts(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "ℹ️ <b>Контакты и запись</b>\n\n"
        f"📍 Адрес: {ADDRESS}\n"
        f"📞 Телефон: {PHONE}\n"
        f"🌐 Сайт: {WEBSITE}\n"
        f"📅 Онлайн-запись (Dikidi): {DIKIDI}\n\n"
        "Приём только по предварительной записи.\n"
        "Можно записаться в этом боте или через Dikidi.\n\n"
        "Команды: /start · /cancel"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=dikidi_kb())
    await message.answer("Меню:", reply_markup=main_menu_kb())


# ---------- Мои записи ----------

@router.message(F.text == "📋 Мои записи")
async def my_bookings(message: Message, state: FSMContext):
    await state.clear()
    bookings = await get_user_bookings(message.from_user.id)
    if not bookings:
        await message.answer(
            "У вас пока нет активных записей через бота.\n"
            "Можете записаться здесь или через Dikidi.",
            reply_markup=main_menu_kb(),
        )
        return
    text = "📋 <b>Ваши записи через бота:</b>\n\n"
    for b in bookings:
        text += f"#{b['id']} — <b>{b['service']}</b>\n📅 {b['date']} в {b['time']}\n👤 {b['client_name']} | 📞 {b['phone']}\n\n"
    await message.answer(text, parse_mode="HTML", reply_markup=my_bookings_inline(bookings))


@router.callback_query(F.data.startswith("cancel_"))
async def process_cancel(callback: CallbackQuery):
    bid = int(callback.data.split("_")[1])
    ok = await cancel_booking(bid, callback.from_user.id)
    if ok:
        await callback.message.edit_text(f"✅ Запись #{bid} отменена.")
        if ADMIN_ID:
            try:
                await callback.bot.send_message(int(ADMIN_ID), f"⚠️ Отмена записи #{bid} от {callback.from_user.id}")
            except Exception:
                pass
    else:
        await callback.answer("Не удалось отменить.", show_alert=True)
    await callback.answer()


# ---------- Запись ----------

@router.message(F.text == "📅 Записаться")
async def start_booking(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Выберите формат:\n\n"
        "• <b>Первая встреча</b> — лучший старт (5000 ₽)\n"
        "• <b>Массаж будущего</b> — полноценный сеанс\n"
        "• <b>Курс 4 сеанса</b> — системная работа\n\n"
        "Или сразу запишитесь через Dikidi 👇",
        parse_mode="HTML",
        reply_markup=services_kb(),
    )
    await message.answer("Быстрая запись:", reply_markup=dikidi_kb())
    await state.set_state(BookingStates.choosing_service)


@router.message(BookingStates.choosing_service, F.text.in_(SERVICES.keys()))
async def service_chosen(message: Message, state: FSMContext):
    service = message.text
    duration = SERVICES[service]["duration_min"]
    await state.update_data(service=service, duration_min=duration)
    await message.answer(
        f"Вы выбрали: <b>{service}</b> ({SERVICES[service]['price']} ₽)\n\n"
        "Введите дату в формате <b>ДД.ММ.ГГГГ</b>\nНапример: 28.08.2026",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await state.set_state(BookingStates.entering_date)


@router.message(BookingStates.choosing_service)
async def service_wrong(message: Message):
    await message.answer("Выберите услугу кнопкой 👇", reply_markup=services_kb())


@router.message(BookingStates.entering_date)
async def date_entered(message: Message, state: FSMContext):
    text = message.text.strip()
    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", text):
        await message.answer("Формат: <b>ДД.ММ.ГГГГ</b>", parse_mode="HTML", reply_markup=cancel_kb())
        return
    try:
        d = datetime.strptime(text, "%d.%m.%Y")
        if d.date() < datetime.now().date():
            await message.answer("Дата должна быть в будущем.", reply_markup=cancel_kb())
            return
    except ValueError:
        await message.answer("Такой даты нет. Проверьте.", reply_markup=cancel_kb())
        return

    data = await state.get_data()
    free = await get_free_slots(text, data["duration_min"])
    if not free:
        await message.answer(f"На {text} свободных слотов нет. Попробуйте другую дату.", reply_markup=cancel_kb())
        return

    await state.update_data(date=text)
    await message.answer(
        f"📅 <b>{text}</b>\nСвободное время (услуга ~{data['duration_min']} мин):",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await message.answer("Выберите слот:", reply_markup=free_slots_kb(free))
    await state.set_state(BookingStates.choosing_time)


@router.callback_query(BookingStates.choosing_time, F.data.startswith("slot_"))
async def slot_chosen(callback: CallbackQuery, state: FSMContext):
    if callback.data == "slot_cancel":
        await state.clear()
        await callback.message.edit_text("Отменено.")
        await callback.message.answer("Меню:", reply_markup=main_menu_kb())
        await callback.answer()
        return
    slot = callback.data.replace("slot_", "")
    await state.update_data(time=slot)
    await callback.message.edit_text(f"✅ Время: <b>{slot}</b>", parse_mode="HTML")
    await callback.message.answer("Ваше <b>имя</b>:", parse_mode="HTML", reply_markup=cancel_kb())
    await state.set_state(BookingStates.entering_name)
    await callback.answer()


@router.message(BookingStates.choosing_time)
async def slot_fallback(message: Message, state: FSMContext):
    await message.answer("Выберите время кнопкой выше 👆", reply_markup=cancel_kb())


@router.message(BookingStates.entering_name)
async def name_entered(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Введите имя:", reply_markup=cancel_kb())
        return
    await state.update_data(client_name=name)
    await message.answer("Номер телефона (+7... или 8...):", reply_markup=cancel_kb())
    await state.set_state(BookingStates.entering_phone)


@router.message(BookingStates.entering_phone)
async def phone_entered(message: Message, state: FSMContext):
    phone = message.text.strip()
    if len(re.sub(r"\D", "", phone)) < 10:
        await message.answer("Введите корректный номер:", reply_markup=cancel_kb())
        return
    await state.update_data(phone=phone)
    data = await state.get_data()
    text = (
        "📝 <b>Проверьте запись:</b>\n\n"
        f"Услуга: <b>{data['service']}</b>\n"
        f"Дата: <b>{data['date']}</b>\n"
        f"Время: <b>{data['time']}</b>\n"
        f"Имя: <b>{data['client_name']}</b>\n"
        f"Телефон: <b>{data['phone']}</b>\n\n"
        "Всё верно?"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=confirm_kb())
    await state.set_state(BookingStates.confirmation)


@router.message(BookingStates.confirmation, F.text == "✅ Подтвердить")
async def confirm_booking(message: Message, state: FSMContext):
    data = await state.get_data()
    user = message.from_user
    bid = await add_booking(
        user.id, user.username, data["service"], data["date"], data["time"],
        data["duration_min"], data["client_name"], data["phone"],
    )
    await state.clear()
    await message.answer(
        f"✅ <b>Заявка #{bid} принята!</b>\n\n"
        f"{data['service']} · {data['date']} в {data['time']}\n\n"
        "Я свяжусь с вами для подтверждения.\n"
        "Также можно записаться через Dikidi.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )
    if ADMIN_ID:
        try:
            await message.bot.send_message(
                int(ADMIN_ID),
                f"🆕 Заявка #{bid}\n{data['service']}\n{data['date']} {data['time']}\n"
                f"{data['client_name']} · {data['phone']}\n@{user.username or '—'} (id {user.id})",
            )
        except Exception as e:
            logger.error(e)


@router.message(BookingStates.confirmation)
async def conf_wrong(message: Message):
    await message.answer("Нажмите «✅ Подтвердить» или «❌ Отмена»", reply_markup=confirm_kb())


@router.message(Command("cancel"))
@router.message(F.text == "❌ Отмена")
async def cmd_cancel(message: Message, state: FSMContext):
    if await state.get_state() is None:
        await message.answer("Нечего отменять.", reply_markup=main_menu_kb())
        return
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu_kb())


# ---------- Генерация сертификата (админ) ----------

def _is_admin(user_id: int) -> bool:
    return bool(ADMIN_ID and str(user_id) == str(ADMIN_ID))


@router.message(Command("score"))
async def cmd_score(message: Message, state: FSMContext):
    """
    /score [days] — оценка бота до 10/10 и зоны роста (только админ).
    """
    if not _is_admin(message.from_user.id):
        await message.answer("Команда доступна только администратору.")
        return
    await state.clear()
    parts = message.text.split()
    days = 30
    if len(parts) > 1 and parts[1].isdigit():
        days = int(parts[1])
    metrics = await admin_metrics(days)
    await message.answer(bot_score_text(metrics))


@router.message(Command("orchestra"))
@router.message(Command("orchestrator"))
async def cmd_orchestra(message: Message, state: FSMContext):
    """
    /orchestra <задача> — разложить задачу на субагентов (только админ).
    """
    if not _is_admin(message.from_user.id):
        await message.answer("Команда доступна только администратору.")
        return
    await state.clear()
    command = message.text.split(maxsplit=1)
    task = command[1] if len(command) > 1 else ""
    await message.answer(orchestra_text(task))


@router.message(Command("cert"))
async def cmd_cert(message: Message, state: FSMContext):
    """
    /cert — создать подарочный сертификат (только админ).
    После генерации можно отправить клиенту.
    """
    if not _is_admin(message.from_user.id):
        await message.answer("Команда доступна только администратору.")
        return
    await state.clear()
    await message.answer(
        "🎟 <b>Создание сертификата</b>\n\n"
        "Введите имя получателя (<b>Кому</b>):\n"
        "Например: Анна Иванова",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await state.set_state(CertStates.recipient)


@router.message(CertStates.recipient)
async def cert_recipient(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Введите имя получателя:")
        return
    await state.update_data(recipient=name)
    await message.answer(
        "Вид массажа:\n"
        "Например: Массаж будущего / Первая встреча",
        reply_markup=cancel_kb(),
    )
    await state.set_state(CertStates.massage_type)


@router.message(CertStates.massage_type)
async def cert_type(message: Message, state: FSMContext):
    await state.update_data(massage_type=message.text.strip())
    await message.answer(
        "Количество сеансов:\n"
        "Например: 1 сеанс / 3 сеанса",
        reply_markup=cancel_kb(),
    )
    await state.set_state(CertStates.quantity)


@router.message(CertStates.quantity)
async def cert_qty(message: Message, state: FSMContext):
    await state.update_data(quantity=message.text.strip())
    await message.answer(
        "Срок действия:\n"
        "Например: до 31.12.2026",
        reply_markup=cancel_kb(),
    )
    await state.set_state(CertStates.valid_until)


@router.message(CertStates.valid_until)
async def cert_valid(message: Message, state: FSMContext):
    await state.update_data(valid_until=message.text.strip())
    data = await state.get_data()

    await message.answer("⏳ Генерирую сертификат...")
    try:
        path = generate_certificate(
            recipient=data["recipient"],
            massage_type=data["massage_type"],
            quantity=data["quantity"],
            valid_until=data["valid_until"],
        )
    except Exception as e:
        logger.error(f"Cert gen: {e}")
        await message.answer(f"Ошибка генерации: {e}")
        await state.clear()
        return

    await state.update_data(cert_path=str(path))
    doc = FSInputFile(path)
    await message.answer_document(
        doc,
        caption=(
            f"✅ Сертификат готов\n\n"
            f"Кому: {data['recipient']}\n"
            f"{data['massage_type']} · {data['quantity']}\n"
            f"{data['valid_until']}\n\n"
            f"Отправьте файл клиенту вручную\n"
            f"или пришлите <b>Telegram ID</b> клиента — вышлю от бота.\n"
            f"Или /cancel чтобы выйти."
        ),
        parse_mode="HTML",
    )
    await state.set_state(CertStates.send_to)


@router.message(CertStates.send_to)
async def cert_send_to(message: Message, state: FSMContext):
    data = await state.get_data()
    path = data.get("cert_path")
    text = message.text.strip()

    if not text.isdigit():
        await message.answer(
            "Пришлите числовой Telegram ID клиента\n"
            "или /cancel.",
            reply_markup=cancel_kb(),
        )
        return

    user_id = int(text)
    try:
        doc = FSInputFile(path)
        await message.bot.send_document(
            user_id,
            doc,
            caption=(
                "🎟 Ваш подарочный сертификат «Массаж будущего»\n\n"
                f"Кому: {data['recipient']}\n"
                f"{data['massage_type']} · {data['quantity']}\n"
                f"Срок: {data['valid_until']}\n\n"
                f"Для записи: {PHONE}\n{ADDRESS}"
            ),
        )
        await message.answer(f"✅ Сертификат отправлен пользователю {user_id}")
    except Exception as e:
        await message.answer(
            f"Не удалось отправить (пользователь должен хотя бы раз "
            f"написать боту /start):\n{e}"
        )
    await state.clear()



async def process_text(message: Message, state: FSMContext, text: str):
    if await state.get_state() is not None:
        await message.answer("Сейчас идёт запись. Ответьте текстом или нажмите «❌ Отмена».", reply_markup=cancel_kb())
        return
    lower = text.lower()
    if any(w in lower for w in ["запис", "хочу", "запись"]):
        await start_booking(message, state)
    elif any(w in lower for w in ["упражнен", "шея", "плеч"]):
        await lead_magnet_exercises(message, state)
    elif any(w in lower for w in ["гайд", "бесплатн", "магнит", "признак"]):
        await lead_magnet_signs(message, state)
    elif any(w in lower for w in ["сертификат", "подарок"]):
        await gift_certificate(message, state)
    elif any(w in lower for w in ["отзыв"]):
        await reviews_handler(message, state)
    elif any(w in lower for w in ["обо мне", "кто ты", "михаил"]):
        await about_me(message, state)
    elif any(w in lower for w in ["услуг", "цен", "сколько", "прайс"]):
        await show_services(message, state)
    elif any(w in lower for w in ["контакт", "адрес", "где", "телефон"]):
        await contacts(message, state)
    else:
        await message.answer(
            f"Понял: «{text}»\n\nИспользуйте меню или скажите:\n"
            "• Хочу записаться · 5 признаков · Упражнения · Сертификат · Отзывы",
            reply_markup=main_menu_kb(),
        )


# ---------- Текст ----------

@router.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        await message.answer("Следуйте шагам или нажмите «❌ Отмена».", reply_markup=cancel_kb())
        return
    await process_text(message, state, message.text)


# ==================== ЗАПУСК ====================

async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    logger.info("Бот «Массаж будущего» запускается...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
