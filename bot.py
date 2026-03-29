import os
import re
import sqlite3
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")  # untuk deploy

# ================= DATABASE =================
conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS transaksi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    category TEXT,
    amount INTEGER,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS debt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    amount INTEGER,
    status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# ================= PARSER =================
def parse_input(text):
    text = text.lower()

    angka = re.findall(r'\d+', text)
    jumlah = int(angka[0]) if angka else 0

    if "jt" in text:
        jumlah *= 1_000_000
    elif "k" in text or "ribu" in text:
        jumlah *= 1000

    if any(x in text for x in ["gaji", "bonus", "masuk"]):
        tipe = "income"
    elif "hutang" in text:
        tipe = "hutang"
    elif "bayar" in text:
        tipe = "piutang"
    else:
        tipe = "expense"

    kategori = text.split()[0]

    nama = "umum"
    words = text.split()
    if "hutang" in words:
        try:
            nama = words[words.index("hutang") + 1]
        except:
            pass

    return tipe, kategori, jumlah, text, nama

# ================= COMMAND =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot Keuangan Aktif\n\n/setsaldo 1000000")

async def setsaldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    saldo = int(context.args[0])

    cursor.execute("""
        INSERT INTO users (user_id, balance)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance
    """, (user_id, saldo))
    conn.commit()

    await update.message.reply_text(f"💰 Saldo: Rp{saldo:,}")

async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    saldo = cursor.fetchone()
    saldo = saldo[0] if saldo else 0

    await update.message.reply_text(f"💰 Saldo: Rp{saldo:,}")

async def hutang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    cursor.execute("SELECT name, amount FROM debt WHERE user_id=? AND status='belum'", (user_id,))
    rows = cursor.fetchall()

    if not rows:
        await update.message.reply_text("Tidak ada hutang")
        return

    text = "💳 Hutang:\n"
    for r in rows:
        text += f"{r[0]} - Rp{r[1]:,}\n"

    await update.message.reply_text(text)

async def bayar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    nama = context.args[0]

    cursor.execute("UPDATE debt SET status='lunas' WHERE user_id=? AND name=?", (user_id, nama))
    conn.commit()

    await update.message.reply_text("Lunas!")

async def grafik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    cursor.execute("""
        SELECT category, SUM(amount) FROM transaksi
        WHERE user_id=? AND type='expense'
        GROUP BY category
    """, (user_id,))

    data = cursor.fetchall()

    if not data:
        await update.message.reply_text("Tidak ada data")
        return

    text = "📊 Pengeluaran:\n\n"
    total = sum([d[1] for d in data])

    for kategori, jumlah in data:
        bar = "█" * int((jumlah / total) * 10)
        text += f"{kategori}: {bar} Rp{jumlah:,}\n"

    await update.message.reply_text(text)

# ================= HANDLER =================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    tipe, kategori, jumlah, note, nama = parse_input(text)

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    saldo = cursor.fetchone()
    saldo = saldo[0] if saldo else 0

    if tipe == "expense":
        saldo -= jumlah
    elif tipe == "income":
        saldo += jumlah
    elif tipe == "hutang":
        saldo += jumlah
        cursor.execute("INSERT INTO debt (user_id, name, amount, status) VALUES (?, ?, ?, 'belum')",
                       (user_id, nama, jumlah))
    elif tipe == "piutang":
        saldo -= jumlah

    cursor.execute("""
        INSERT INTO users (user_id, balance)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance
    """, (user_id, saldo))

    cursor.execute("INSERT INTO transaksi (user_id, type, category, amount, note) VALUES (?, ?, ?, ?, ?)",
                   (user_id, tipe, kategori, jumlah, note))

    conn.commit()

    await update.message.reply_text(f"✅ {kategori} Rp{jumlah:,}\n💰 Saldo: Rp{saldo:,}")

# ================= APP =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("setsaldo", setsaldo))
app.add_handler(CommandHandler("saldo", saldo))
app.add_handler(CommandHandler("hutang", hutang))
app.add_handler(CommandHandler("bayar", bayar))
app.add_handler(CommandHandler("grafik", grafik))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

if __name__ == "__main__":
    print("Bot jalan...")
    app.run_polling()
