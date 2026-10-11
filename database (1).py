import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

def _resolve_db_path():
    """Путь к базе. Если папка из DB_PATH недоступна — используем bonus.db рядом с кодом."""
    path = os.getenv("DB_PATH", "bonus.db")
    folder = os.path.dirname(path)
    if folder:
        try:
            os.makedirs(folder, exist_ok=True)
            test = os.path.join(folder, ".write_test")
            open(test, "w").close()
            os.remove(test)
        except OSError:
            print(f"[!] Папка {folder} недоступна, использую bonus.db рядом с кодом")
            return "bonus.db"
    return path


DB_PATH = _resolve_db_path()

# ---------- ПРАВИЛА ПРОГРАММЫ (меняйте здесь) ----------
# название, процент начисления, порог покупок с даты регистрации (₽), срок жизни баллов (дней)
LEVELS = [
    ("BLACK", 10, 0, 45),
    ("GOLD", 11, 100_000, 60),
    ("PLATINUM", 13, 300_000, 90),
]
MAX_PAY_PERCENT = 30  # баллами можно оплатить до 30% чека (1 балл = 1 ₽)

FMT = "%Y-%m-%d %H:%M:%S"


def now():
    return datetime.now()


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                phone TEXT UNIQUE,
                full_name TEXT,
                purchases_total REAL DEFAULT 0,
                points INTEGER DEFAULT 0,
                registered_at TEXT,
                last_accrual_at TEXT
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER,
                type TEXT,          -- accrual / spend / expire / manual
                amount_rub REAL DEFAULT 0,
                points INTEGER,     -- со знаком: + начислено, - списано
                created_at TEXT,
                admin_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY
            );
            """
        )


# ---------- ТЕЛЕФОН ----------
def normalize_phone(raw):
    """Приводит номер к виду +79131234567. Возвращает None, если не похоже на номер."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]
    if len(digits) == 10 and digits[0] == "9":
        return "+7" + digits
    if 9 <= len(digits) <= 15 and (raw or "").strip().startswith("+"):
        return "+" + digits
    return None


# ---------- УРОВНИ ----------
def level_info(purchases_total):
    """(индекс, название, процент, дней жизни баллов)"""
    idx = 0
    for i, (_, _, threshold, _) in enumerate(LEVELS):
        if purchases_total >= threshold:
            idx = i
    name, percent, _, days = LEVELS[idx]
    return idx, name, percent, days


def next_level(purchases_total):
    idx, *_ = level_info(purchases_total)
    if idx + 1 >= len(LEVELS):
        return None
    name, percent, threshold, _ = LEVELS[idx + 1]
    return name, percent, threshold - purchases_total


# ---------- КЛИЕНТЫ ----------
def register_telegram_user(tg_id):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (tg_id,))


def all_telegram_ids():
    with db() as c:
        return [r["telegram_id"] for r in c.execute("SELECT telegram_id FROM users")]


def get_by_phone(phone):
    with db() as c:
        return c.execute("SELECT * FROM customers WHERE phone=?", (phone,)).fetchone()


def get_by_tg(tg_id):
    with db() as c:
        return c.execute("SELECT * FROM customers WHERE telegram_id=?", (tg_id,)).fetchone()


def get_by_id(cid):
    with db() as c:
        return c.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()


def create_customer(tg_id, phone, full_name):
    with db() as c:
        c.execute(
            "INSERT INTO customers (telegram_id, phone, full_name, registered_at) VALUES (?,?,?,?)",
            (tg_id, phone, full_name, now().strftime(FMT)))
    return get_by_phone(phone)


def bind_telegram(cid, tg_id):
    with db() as c:
        c.execute("UPDATE customers SET telegram_id=NULL WHERE telegram_id=? AND id<>?", (tg_id, cid))
        c.execute("UPDATE customers SET telegram_id=? WHERE id=?", (tg_id, cid))


def unbind_telegram(tg_id):
    with db() as c:
        c.execute("UPDATE customers SET telegram_id=NULL WHERE telegram_id=?", (tg_id,))


def add_tx(c, cid, typ, amount_rub, points, admin_id=None):
    c.execute("INSERT INTO transactions (customer_id, type, amount_rub, points, created_at, admin_id) VALUES (?,?,?,?,?,?)",
              (cid, typ, amount_rub, points, now().strftime(FMT), admin_id))


def accrue(cid, amount_rub, admin_id):
    """Начисляет баллы за покупку по текущему уровню. Возвращает (начислено, новый клиент)."""
    cust = get_by_id(cid)
    _, _, percent, _ = level_info(cust["purchases_total"])
    pts = int(amount_rub * percent // 100)
    with db() as c:
        c.execute("UPDATE customers SET points=points+?, purchases_total=purchases_total+?, last_accrual_at=? WHERE id=?",
                  (pts, amount_rub, now().strftime(FMT), cid))
        add_tx(c, cid, "accrual", amount_rub, pts, admin_id)
    return pts, get_by_id(cid)


def max_spend(cust, check_rub):
    return int(min(cust["points"], check_rub * MAX_PAY_PERCENT // 100))


def spend(cid, check_rub, points, admin_id):
    cust = get_by_id(cid)
    if points <= 0 or points > max_spend(cust, check_rub):
        return False
    with db() as c:
        c.execute("UPDATE customers SET points=points-? WHERE id=?", (points, cid))
        add_tx(c, cid, "spend", check_rub, -points, admin_id)
    return True


def manual_adjust(cid, points, admin_id):
    cust = get_by_id(cid)
    if cust["points"] + points < 0:
        return False
    with db() as c:
        c.execute("UPDATE customers SET points=points+?, last_accrual_at=CASE WHEN ?>0 THEN ? ELSE last_accrual_at END WHERE id=?",
                  (points, points, now().strftime(FMT), cid))
        add_tx(c, cid, "manual", 0, points, admin_id)
    return True


def history(cid, limit=15):
    with db() as c:
        return c.execute("SELECT * FROM transactions WHERE customer_id=? ORDER BY id DESC LIMIT ?", (cid, limit)).fetchall()


# ---------- СГОРАНИЕ ----------
def expire_date(cust):
    """Когда сгорят баллы клиента (или None)."""
    if not cust["points"] or not cust["last_accrual_at"]:
        return None
    _, _, _, days = level_info(cust["purchases_total"])
    return datetime.strptime(cust["last_accrual_at"], FMT) + timedelta(days=days)


def run_expiration():
    """Сжигает баллы у клиентов, у которых срок вышел. Возвращает список (telegram_id, сгорело баллов)."""
    burned = []
    with db() as c:
        rows = c.execute("SELECT * FROM customers WHERE points>0 AND last_accrual_at IS NOT NULL").fetchall()
        for cust in rows:
            exp = expire_date(cust)
            if exp and exp <= now():
                c.execute("UPDATE customers SET points=0 WHERE id=?", (cust["id"],))
                add_tx(c, cust["id"], "expire", 0, -cust["points"])
                burned.append((cust["telegram_id"], cust["points"]))
    return burned


def soon_expiring(days=7):
    """Клиенты, у которых баллы сгорят в ближайшие days дней (для напоминаний)."""
    out = []
    with db() as c:
        for cust in c.execute("SELECT * FROM customers WHERE points>0 AND telegram_id IS NOT NULL").fetchall():
            exp = expire_date(cust)
            if exp and now() < exp <= now() + timedelta(days=days):
                out.append((cust, exp))
    return out


def stats():
    with db() as c:
        n = c.execute("SELECT COUNT(*) n FROM customers").fetchone()["n"]
        pts = c.execute("SELECT COALESCE(SUM(points),0) s FROM customers").fetchone()["s"]
        acc = c.execute("SELECT COALESCE(SUM(points),0) s FROM transactions WHERE type='accrual'").fetchone()["s"]
        sp = c.execute("SELECT COALESCE(-SUM(points),0) s FROM transactions WHERE type='spend'").fetchone()["s"]
        ex = c.execute("SELECT COALESCE(-SUM(points),0) s FROM transactions WHERE type='expire'").fetchone()["s"]
        turn = c.execute("SELECT COALESCE(SUM(amount_rub),0) s FROM transactions WHERE type='accrual'").fetchone()["s"]
    return n, pts, acc, sp, ex, turn
