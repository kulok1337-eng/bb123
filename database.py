import sqlite3

def init_db():
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            rating REAL DEFAULT 5.0,
            is_courier INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
        )
    ''')
    
    # Таблица категорий
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    ''')
    
    # Таблица товаров
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER,
            name TEXT,
            description TEXT,
            price REAL,
            photo_id TEXT,
            FOREIGN KEY (category_id) REFERENCES categories (id)
        )
    ''')

    # Таблица корзины
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cart (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id INTEGER,
            count INTEGER DEFAULT 1,
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')

    # Таблица заказов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            items_text TEXT,
            total_price REAL,
            status TEXT DEFAULT 'new',
            courier_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица отзывов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            user_id INTEGER,
            courier_id INTEGER,
            rating INTEGER,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Начальные категории
    categories = [
        'Подики', 'Одноразки', 'Никотиновые пластинки (вата)',
        'Испарители', 'Шайбы', 'SALE', 'Жижи', 'Картриджи'
    ]
    for cat in categories:
        cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))
            
    conn.commit()
    conn.close()

# --- ПОЛЬЗОВАТЕЛИ ---

def register_user(user_id, username):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, username) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
    ''', (user_id, username))
    conn.commit()
    conn.close()

def get_user_info(user_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, balance, rating, is_courier, is_admin FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_all_users_ids():
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def update_user_balance(user_id, amount):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def set_courier_status(user_id, is_courier: int):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_courier = ? WHERE user_id = ?", (is_courier, user_id))
    conn.commit()
    conn.close()

# --- КАТЕГОРИИ И ТОВАРЫ ---

def get_categories():
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM categories")
    cats = cursor.fetchall()
    conn.close()
    return cats

def add_category(name):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO categories (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()

def rename_category(cat_id, new_name):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE categories SET name = ? WHERE id = ?", (new_name, cat_id))
    conn.commit()
    conn.close()

def delete_category(cat_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
    cursor.execute("DELETE FROM products WHERE category_id = ?", (cat_id,))
    conn.commit()
    conn.close()

def add_product_to_db(category_id, name, description, price, photo_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO products (category_id, name, description, price, photo_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (category_id, name, description, price, photo_id))
    conn.commit()
    conn.close()

def get_products_by_category(category_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description, price, photo_id FROM products WHERE category_id = ?", (category_id,))
    products = cursor.fetchall()
    conn.close()
    return products

# --- КОРЗИНА ---

def add_to_cart(user_id, product_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, count FROM cart WHERE user_id = ? AND product_id = ?", (user_id, product_id))
    item = cursor.fetchone()
    if item:
        cursor.execute("UPDATE cart SET count = count + 1 WHERE id = ?", (item[0],))
    else:
        cursor.execute("INSERT INTO cart (user_id, product_id, count) VALUES (?, ?, 1)", (user_id, product_id))
    conn.commit()
    conn.close()

def get_user_cart(user_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.name, p.price, c.count, p.id
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id = ?
    ''', (user_id,))
    cart_items = cursor.fetchall()
    conn.close()
    return cart_items

def clear_user_cart(user_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# --- ЗАКАЗЫ И ОТЗЫВЫ ---

def create_order(user_id):
    cart_items = get_user_cart(user_id)
    if not cart_items:
        return None
    
    total_price = 0
    items_list = []
    for name, price, count, _ in cart_items:
        item_total = price * count
        total_price += item_total
        items_list.append(f"{name} x{count} ({item_total} руб.)")
        
    items_text = ", ".join(items_list)
    
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO orders (user_id, items_text, total_price, status)
        VALUES (?, ?, ?, 'new')
    ''', (user_id, items_text, total_price))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    clear_user_cart(user_id)
    return order_id

def get_orders_by_status(status):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, items_text, total_price, created_at FROM orders WHERE status = ? ORDER BY id DESC", (status,))
    orders = cursor.fetchall()
    conn.close()
    return orders

def get_order_by_id(order_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, items_text, total_price, status, courier_id FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    conn.close()
    return order

def get_user_taken_orders(courier_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, items_text, total_price, created_at FROM orders WHERE courier_id = ? AND status = 'in_progress' ORDER BY id DESC", (courier_id,))
    orders = cursor.fetchall()
    conn.close()
    return orders

def take_order(order_id, courier_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = 'in_progress', courier_id = ? WHERE id = ?", (courier_id, order_id))
    conn.commit()
    conn.close()

def complete_order(order_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()

def add_review(order_id, user_id, courier_id, rating, comment=""):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO reviews (order_id, user_id, courier_id, rating, comment)
        VALUES (?, ?, ?, ?, ?)
    ''', (order_id, user_id, courier_id, rating, comment))
    
    # Перерасчет среднего рейтинга курьера
    if courier_id:
        cursor.execute("SELECT AVG(rating) FROM reviews WHERE courier_id = ?", (courier_id,))
        avg_rating = cursor.fetchone()[0]
        if avg_rating:
            cursor.execute("UPDATE users SET rating = ? WHERE user_id = ?", (round(avg_rating, 1), courier_id))
            
    conn.commit()
    conn.close()

def get_recent_reviews(limit=5):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.rating, r.comment, r.created_at, u.username
        FROM reviews r
        LEFT JOIN users u ON r.courier_id = u.user_id
        ORDER BY r.id DESC LIMIT ?
    ''', (limit,))
    reviews = cursor.fetchall()
    conn.close()
    return reviews

def get_user_orders_count(user_id):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM orders WHERE user_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_stats(day_only=False):
    conn = sqlite3.connect('shop.db')
    cursor = conn.cursor()
    if day_only:
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(total_price), 0) FROM orders WHERE status = 'completed' AND DATE(created_at) = DATE('now')")
    else:
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(total_price), 0) FROM orders WHERE status = 'completed'")
    orders_count, total_sum = cursor.fetchone()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]
    conn.close()
    return orders_count, total_sum, users_count

if __name__ == '__main__':
    init_db()
