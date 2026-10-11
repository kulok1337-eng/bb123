import asyncio
import functools
import logging
import os
from datetime import datetime
from html import escape

from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove,
)

import database as db

# ---------------- НАСТРОЙКИ (переменные окружения) ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8904163540:AAEiLt8W6IAUOaIFHL38YqM7d8JjZ8pLrtE")
ADMINS = [int(x) for x in os.getenv("ADMINS", "1979046241,8079727075").split(",") if x.strip()]
MANAGER_USERNAME = os.getenv("MANAGER_USERNAME", "").lstrip("@")   # юзернейм менеджера без @
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/Baraholka_shop_tg")
SHOP_NAME = os.getenv("SHOP_NAME", "BARAHOLKA SHOP")

if not BOT_TOKEN:
    raise SystemExit("Не задана переменная окружения BOT_TOKEN")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


class Reg(StatesGroup):
    name = State()


class Adm(StatesGroup):
    find = State()
    acc_phone = State()
    acc_amount = State()
    spend_phone = State()
    spend_check = State()
    spend_points = State()
    adj_phone = State()
    adj_points = State()
    broadcast = State()


# ---------------- ХЕЛПЕРЫ ----------------
def is_admin(uid):
    return uid in ADMINS


def fmt_rub(x):
    return f"{int(round(x)):,}".replace(",", " ")


def ikb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_kb(uid):
    rows = [
        [KeyboardButton(text="💳 Моя карта"), KeyboardButton(text="⭐ Уровень")],
        [KeyboardButton(text="🔥 Сгорание"), KeyboardButton(text="🧾 История")],
        [KeyboardButton(text="ℹ️ Как это работает"), KeyboardButton(text="💬 Написать менеджеру")],
        [KeyboardButton(text="📢 Новости"), KeyboardButton(text="🔄 Войти с другим номером")],
    ]
    if is_admin(uid):
        rows.append([KeyboardButton(text="🔧 Админка")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def phone_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True)


def channel_kb():
    return ikb([[InlineKeyboardButton(text="📢 Канал", url=CHANNEL_URL)]])


def card_text(c):
    _, name, percent, _ = db.level_info(c["purchases_total"])
    return (
        f"💳 <b>{SHOP_NAME} {name}</b>\n\n"
        f"На карте: <b>{c['points']} баллов</b>\n"
        f"Начисляем: <b>{percent}%</b> от покупки\n"
        f"Оплатить баллами можно до {db.MAX_PAY_PERCENT}% чека (1 балл = 1 ₽)\n\n"
        f"Для кассира: номер <code>{c['phone']}</code>"
    )


# ---------------- ТЕХНИЧЕСКОЕ ----------------
class Track(BaseMiddleware):
    """Запоминает всех, кто писал боту (для рассылки)."""
    async def __call__(self, handler, event, data):
        u = getattr(event, "from_user", None)
        if u and not u.is_bot:
            db.register_telegram_user(u.id)
        return await handler(event, data)


dp.message.outer_middleware(Track())
dp.callback_query.outer_middleware(Track())


@dp.error()
async def on_error(event: types.ErrorEvent):
    logging.exception("Ошибка: %s", event.exception)
    try:
        if event.update.message:
            await event.update.message.answer("⚠️ Произошла ошибка. Нажмите /start")
        elif event.update.callback_query:
            await event.update.callback_query.answer("⚠️ Ошибка. Попробуйте ещё раз", show_alert=True)
    except Exception:
        pass
    return True


# ---------------- РЕГИСТРАЦИЯ / ВХОД ----------------
WELCOME = (
    f"Привет! Это бонусная карта <b>{SHOP_NAME}</b> ✌️\n\n"
    "Нажмите кнопку ниже или просто напишите свой номер телефона "
    "(например, 89131234567 или +998 90 123 45 67) — покажу баланс, уровень и когда сгорят баллы."
)


async def send_card(message, cust):
    await message.answer(card_text(cust), reply_markup=main_kb(message.from_user.id))
    await message.answer("📢 Новинки, наличие товаров и важные новости — в нашем канале:", reply_markup=channel_kb())


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    cust = db.get_by_tg(message.from_user.id)
    if cust:
        return await message.answer(card_text(cust), reply_markup=main_kb(message.from_user.id))
    await message.answer(WELCOME, reply_markup=phone_kb())
    if is_admin(message.from_user.id):
        await message.answer("🔧 Вы администратор: кнопка «Админка» появится после входа по номеру.",
                             reply_markup=main_kb(message.from_user.id))


async def handle_phone(message: types.Message, state: FSMContext, raw):
    phone = db.normalize_phone(raw)
    if not phone:
        return await message.answer("Не похоже на номер. Пример: 89131234567 или +998 90 123 45 67")
    cust = db.get_by_phone(phone)
    if cust:
        # привязываем, только если карта ещё ни к кому не привязана или это тот же человек
        if cust["telegram_id"] in (None, message.from_user.id):
            db.bind_telegram(cust["id"], message.from_user.id)
            cust = db.get_by_id(cust["id"])
            return await send_card(message, cust)
        await message.answer("Эта карта привязана к другому аккаунту Telegram. Показываю баланс:")
        return await message.answer(card_text(cust), reply_markup=main_kb(message.from_user.id))
    await state.set_state(Reg.name)
    await state.update_data(phone=phone)
    await message.answer("Регистрирую новую карту 🎉\n\nКак вас зовут? Напишите имя — можно с фамилией и отчеством.",
                         reply_markup=ReplyKeyboardRemove())


@dp.message(F.contact)
async def got_contact(message: types.Message, state: FSMContext):
    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        return await message.answer("Отправьте, пожалуйста, свой номер.")
    await handle_phone(message, state, "+" + message.contact.phone_number.lstrip("+"))


@dp.message(Reg.name, F.text)
async def reg_name(message: types.Message, state: FSMContext):
    name = message.text.strip()[:100]
    if len(name) < 2:
        return await message.answer("Напишите имя чуть подробнее.")
    d = await state.get_data()
    cust = db.create_customer(message.from_user.id, d["phone"], name)
    await state.clear()
    first = escape(name.split()[0])
    await message.answer(f"Приятно познакомиться, {first}! ✌️\nГотово! Карта привязана к номеру <b>{d['phone']}</b> 🎉")
    await send_card(message, cust)


# ---------------- МЕНЮ КЛИЕНТА ----------------
async def need_card(message: types.Message):
    cust = db.get_by_tg(message.from_user.id)
    if not cust:
        await message.answer("Сначала войдите по номеру телефона.", reply_markup=phone_kb())
    return cust


@dp.message(F.text == "💳 Моя карта")
async def my_card(message: types.Message):
    cust = await need_card(message)
    if cust:
        await message.answer(card_text(cust))


@dp.message(F.text == "⭐ Уровень")
async def my_level(message: types.Message):
    cust = await need_card(message)
    if not cust:
        return
    _, name, percent, _ = db.level_info(cust["purchases_total"])
    reg = (cust["registered_at"] or "")[:10]
    reg = datetime.strptime(reg, "%Y-%m-%d").strftime("%d.%m.%Y") if reg else "—"
    nxt = db.next_level(cust["purchases_total"])
    lines = [f"⭐ Ваш уровень: <b>{SHOP_NAME} {name} ({percent}%)</b>",
             f"Покупок с регистрации ({reg}): {fmt_rub(cust['purchases_total'])} ₽", ""]
    if nxt:
        lines.append(f"До {SHOP_NAME} {nxt[0]} ({nxt[1]}%) осталось купить на {fmt_rub(nxt[2])} ₽")
    else:
        lines.append("Вы достигли максимального уровня 🏆")
    lines.append("")
    parts = []
    for n, p, th, _ in db.LEVELS:
        parts.append(f"{n} {p}%" + (f" (от {fmt_rub(th)} ₽)" if th else ""))
    lines.append("Уровни: " + " → ".join(parts))
    await message.answer("\n".join(lines))


@dp.message(F.text == "🔥 Сгорание")
async def burn_info(message: types.Message):
    cust = await need_card(message)
    if not cust:
        return
    _, name, _, days = db.level_info(cust["purchases_total"])
    exp = db.expire_date(cust)
    if exp and (exp - datetime.now()).days <= 30:
        txt = f"🔥 <b>{cust['points']} баллов</b> сгорят {exp.strftime('%d.%m.%Y')}."
    else:
        txt = "🔥 В ближайший месяц ничего не сгорит."
    await message.answer(f"{txt}\nБаллы по карте {SHOP_NAME} {name} живут {days} дней с последнего начисления.")


@dp.message(F.text == "🧾 История")
async def my_history(message: types.Message):
    cust = await need_card(message)
    if not cust:
        return
    rows = db.history(cust["id"])
    if not rows:
        return await message.answer("🧾 Операций с баллами пока нет.")
    names = {"accrual": "Начисление", "spend": "Списание", "expire": "Сгорание", "manual": "Корректировка"}
    lines = ["🧾 <b>История операций:</b>\n"]
    for r in rows:
        date = datetime.strptime(r["created_at"], db.FMT).strftime("%d.%m.%Y")
        sign = "+" if r["points"] > 0 else ""
        extra = f" (чек {fmt_rub(r['amount_rub'])} ₽)" if r["amount_rub"] else ""
        lines.append(f"{date} · {names.get(r['type'], r['type'])}: <b>{sign}{r['points']}</b>{extra}")
    await message.answer("\n".join(lines))


def manager_line():
    return f"@{MANAGER_USERNAME}" if MANAGER_USERNAME else "менеджеру магазина"


@dp.message(F.text == "ℹ️ Как это работает")
async def how_it_works(message: types.Message):
    levels = ", ".join(f"{n} {p}%" + (f" (покупки от {fmt_rub(t)} ₽)" if t else "") for n, p, t, _ in db.LEVELS)
    burn = ", ".join(f"{n} — {d}" for n, _, _, d in db.LEVELS)
    await message.answer(
        f"ℹ️ <b>Бонусная программа {SHOP_NAME}</b>\n\n"
        f"• С каждой покупки на карту приходят баллы: от {db.LEVELS[0][1]}% суммы, чем выше уровень — тем больше\n"
        f"• 1 балл = 1 ₽, оплатить баллами можно до {db.MAX_PAY_PERCENT}% чека\n"
        "• Назовите на кассе свой номер телефона\n"
        f"• Уровни: {levels}\n"
        f"• Баллы сгорают, если их не использовать: {burn} дней\n\n"
        f"Вопросы — менеджеру: {manager_line()}")


@dp.message(F.text == "💬 Написать менеджеру")
async def write_manager(message: types.Message):
    kb = ikb([[InlineKeyboardButton(text="💬 Написать", url=f"https://t.me/{MANAGER_USERNAME}")]]) if MANAGER_USERNAME else None
    await message.answer(f"Менеджер {SHOP_NAME}: {manager_line()}\nНапишите — ответим на любые вопросы по карте и баллам.",
                         reply_markup=kb)


@dp.message(F.text == "📢 Новости")
async def news(message: types.Message):
    await message.answer("📢 Новинки, наличие товаров и важные новости — в нашем канале:", reply_markup=channel_kb())


@dp.message(F.text == "🔄 Войти с другим номером")
async def relogin(message: types.Message, state: FSMContext):
    db.unbind_telegram(message.from_user.id)
    await state.clear()
    await message.answer("Отправьте новый номер телефона:", reply_markup=phone_kb())


# ---------------- АДМИНКА ----------------
def admin_only(handler):
    @functools.wraps(handler)
    async def wrapper(event, *a, **kw):
        if not is_admin(event.from_user.id):
            if isinstance(event, types.CallbackQuery):
                return await event.answer("Нет доступа", show_alert=True)
            return
        return await handler(event, *a, **kw)
    return wrapper


def admin_kb():
    return ikb([
        [InlineKeyboardButton(text="🔎 Найти клиента", callback_data="a_find")],
        [InlineKeyboardButton(text="➕ Начислить за покупку", callback_data="a_acc")],
        [InlineKeyboardButton(text="➖ Списать баллы", callback_data="a_spend")],
        [InlineKeyboardButton(text="✏️ Корректировка баллов", callback_data="a_adj")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="a_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="a_bc")],
    ])


@dp.message(F.text == "🔧 Админка")
@admin_only
async def admin_panel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🔧 <b>Админ-панель</b>", reply_markup=admin_kb())


async def ask(cb, state, st, text):
    await state.set_state(st)
    await cb.message.answer(text + "\n\n(для отмены — /start)")
    await cb.answer()


@dp.callback_query(F.data == "a_find")
@admin_only
async def a_find(cb: types.CallbackQuery, state: FSMContext):
    await ask(cb, state, Adm.find, "Введите номер телефона клиента:")


@dp.callback_query(F.data == "a_acc")
@admin_only
async def a_acc(cb: types.CallbackQuery, state: FSMContext):
    await ask(cb, state, Adm.acc_phone, "Начисление. Введите номер телефона клиента:")


@dp.callback_query(F.data == "a_spend")
@admin_only
async def a_spend(cb: types.CallbackQuery, state: FSMContext):
    await ask(cb, state, Adm.spend_phone, "Списание. Введите номер телефона клиента:")


@dp.callback_query(F.data == "a_adj")
@admin_only
async def a_adj(cb: types.CallbackQuery, state: FSMContext):
    await ask(cb, state, Adm.adj_phone, "Корректировка. Введите номер телефона клиента:")


@dp.callback_query(F.data == "a_bc")
@admin_only
async def a_bc(cb: types.CallbackQuery, state: FSMContext):
    await ask(cb, state, Adm.broadcast, "Отправьте сообщение (текст или фото с подписью) для рассылки всем:")


@dp.callback_query(F.data == "a_stats")
@admin_only
async def a_stats(cb: types.CallbackQuery):
    n, pts, acc, sp, ex, turn = db.stats()
    await cb.message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"👥 Клиентов: <b>{n}</b>\n"
        f"💰 Оборот по начислениям: <b>{fmt_rub(turn)} ₽</b>\n"
        f"➕ Начислено баллов: <b>{acc}</b>\n"
        f"➖ Списано баллов: <b>{sp}</b>\n"
        f"🔥 Сгорело баллов: <b>{ex}</b>\n"
        f"🏦 Сейчас на картах: <b>{pts}</b>")
    await cb.answer()


async def find_customer(message: types.Message):
    phone = db.normalize_phone(message.text)
    if not phone:
        await message.answer("Неверный номер. Пример: 89131234567")
        return None
    cust = db.get_by_phone(phone)
    if not cust:
        await message.answer("❌ Клиент не найден. Пусть сначала зарегистрируется в боте.")
        return None
    return cust


def cust_line(c):
    _, name, percent, _ = db.level_info(c["purchases_total"])
    return (f"👤 {escape(c['full_name'] or '—')} · <code>{c['phone']}</code>\n"
            f"Уровень: {name} ({percent}%) · покупок {fmt_rub(c['purchases_total'])} ₽ · баллов <b>{c['points']}</b>")


@dp.message(Adm.find, F.text)
@admin_only
async def adm_find(message: types.Message, state: FSMContext):
    cust = await find_customer(message)
    if cust:
        await message.answer("🔎 " + cust_line(cust))
        await state.clear()


@dp.message(Adm.acc_phone, F.text)
@admin_only
async def adm_acc_phone(message: types.Message, state: FSMContext):
    cust = await find_customer(message)
    if cust:
        await state.update_data(cid=cust["id"])
        await state.set_state(Adm.acc_amount)
        await message.answer(cust_line(cust) + "\n\nВведите сумму чека в рублях:")


def parse_number(text):
    try:
        v = float(text.replace(" ", "").replace(",", "."))
        return v if v > 0 else None
    except ValueError:
        return None


@dp.message(Adm.acc_amount, F.text)
@admin_only
async def adm_acc_amount(message: types.Message, state: FSMContext):
    amount = parse_number(message.text)
    if not amount:
        return await message.answer("Введите положительное число.")
    d = await state.get_data()
    before = db.get_by_id(d["cid"])
    pts, after = db.accrue(d["cid"], amount, message.from_user.id)
    await state.clear()
    msg = f"✅ Начислено <b>{pts}</b> баллов. Теперь на карте: {after['points']}."
    old, new = db.level_info(before["purchases_total"])[1], db.level_info(after["purchases_total"])[1]
    if old != new:
        msg += f"\n🎉 Клиент перешёл на уровень {new}."
    await message.answer(msg)
    if after["telegram_id"]:
        try:
            await bot.send_message(after["telegram_id"],
                                   f"🎉 Вам начислено <b>{pts}</b> баллов за покупку на {fmt_rub(amount)} ₽.\n"
                                   f"Баланс: <b>{after['points']}</b> баллов." + (f"\n⭐ Новый уровень: {new}!" if old != new else ""))
        except Exception:
            pass


@dp.message(Adm.spend_phone, F.text)
@admin_only
async def adm_spend_phone(message: types.Message, state: FSMContext):
    cust = await find_customer(message)
    if cust:
        await state.update_data(cid=cust["id"])
        await state.set_state(Adm.spend_check)
        await message.answer(cust_line(cust) + "\n\nВведите сумму чека в рублях:")


@dp.message(Adm.spend_check, F.text)
@admin_only
async def adm_spend_check(message: types.Message, state: FSMContext):
    check = parse_number(message.text)
    if not check:
        return await message.answer("Введите положительное число.")
    d = await state.get_data()
    cust = db.get_by_id(d["cid"])
    mx = db.max_spend(cust, check)
    if mx <= 0:
        await state.clear()
        return await message.answer("У клиента нет баллов для списания.")
    await state.update_data(check=check)
    await state.set_state(Adm.spend_points)
    await message.answer(f"Можно списать до <b>{mx}</b> баллов (баланс {cust['points']}, лимит {db.MAX_PAY_PERCENT}% чека).\n"
                         "Сколько списать?")


@dp.message(Adm.spend_points, F.text)
@admin_only
async def adm_spend_points(message: types.Message, state: FSMContext):
    pts = parse_number(message.text)
    d = await state.get_data()
    if not pts or not db.spend(d["cid"], d["check"], int(pts), message.from_user.id):
        return await message.answer("Нельзя списать столько. Введите число не больше указанного лимита.")
    cust = db.get_by_id(d["cid"])
    await state.clear()
    await message.answer(f"✅ Списано <b>{int(pts)}</b> баллов. Остаток: {cust['points']}.\n"
                         f"К оплате деньгами: {fmt_rub(d['check'] - int(pts))} ₽.")
    if cust["telegram_id"]:
        try:
            await bot.send_message(cust["telegram_id"], f"➖ Списано <b>{int(pts)}</b> баллов. Остаток: <b>{cust['points']}</b>.")
        except Exception:
            pass


@dp.message(Adm.adj_phone, F.text)
@admin_only
async def adm_adj_phone(message: types.Message, state: FSMContext):
    cust = await find_customer(message)
    if cust:
        await state.update_data(cid=cust["id"])
        await state.set_state(Adm.adj_points)
        await message.answer(cust_line(cust) + "\n\nВведите число баллов (например 100 или -50):")


@dp.message(Adm.adj_points, F.text)
@admin_only
async def adm_adj_points(message: types.Message, state: FSMContext):
    try:
        pts = int(message.text.strip())
    except ValueError:
        return await message.answer("Введите целое число.")
    d = await state.get_data()
    if not pts or not db.manual_adjust(d["cid"], pts, message.from_user.id):
        return await message.answer("Не получилось: баланс не может стать отрицательным.")
    cust = db.get_by_id(d["cid"])
    await state.clear()
    await message.answer(f"✅ Готово. Баланс клиента: {cust['points']}.")


@dp.message(Adm.broadcast)
@admin_only
async def adm_broadcast(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🚀 Рассылка запущена...")
    ok = bad = 0
    for uid in db.all_telegram_ids():
        try:
            await message.copy_to(uid)
            ok += 1
        except Exception:
            bad += 1
        await asyncio.sleep(0.05)
    await message.answer(f"✅ Готово. Доставлено: {ok}, ошибок: {bad}")


# ---------------- ЛЮБОЙ ДРУГОЙ ТЕКСТ = НОМЕР ТЕЛЕФОНА ----------------
@dp.message(F.text)
async def any_text(message: types.Message, state: FSMContext):
    await handle_phone(message, state, message.text)


# ---------------- ФОНОВАЯ ЗАДАЧА: СГОРАНИЕ ----------------
reminded = set()


async def expiration_loop():
    while True:
        try:
            for tg_id, pts in db.run_expiration():
                if tg_id:
                    try:
                        await bot.send_message(tg_id, f"🔥 Сгорело <b>{pts}</b> баллов — срок действия истёк.")
                    except Exception:
                        pass
            for cust, exp in db.soon_expiring(7):
                key = (cust["id"], exp.strftime("%Y-%m-%d"))
                if key not in reminded:
                    reminded.add(key)
                    try:
                        await bot.send_message(
                            cust["telegram_id"],
                            f"⏳ <b>{cust['points']}</b> баллов сгорят {exp.strftime('%d.%m.%Y')}. Успейте потратить!")
                    except Exception:
                        pass
        except Exception:
            logging.exception("Ошибка в задаче сгорания")
        await asyncio.sleep(3600)


async def main():
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    await bot.delete_webhook(drop_pending_updates=False)
    asyncio.create_task(expiration_loop())
    await dp.start_polling(bot)


i