import os
import re
import sqlite3
from datetime import datetime
import matplotlib.pyplot as plt

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")

# ================= DATABASE =================
conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transaksi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    amount INTEGER,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS hutang (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    nama TEXT,
    amount INTEGER,
    status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# ================= PARSER =================
def parse_input(text):
    text = text.lower()
    if text.lower() == "saldo":
    await saldo(update, context)
    return

if text.lower() == "laporan":
    await laporan(update, context)
    return

if text.lower() == "hutang":
    await hutang_list(update, context)
    return

    angka = re.findall(r'\d+', text)
    jumlah = int(angka[0]) if angka else 0

    if "jt" in text:
        jumlah *= 1_000_000
    elif "k" in text:
        jumlah *= 1000

    if any(x in text for x in ["gaji", "bonus", "masuk"]):
        tipe = "income"
    elif "hutang" in text:
        tipe = "hutang"
    elif "bayar" in text:
        tipe = "bayar"
    else:
        tipe = "expense"

    words = text.split()
    nama = None
    if "hutang" in words:
        try:
            nama = words[words.index("hutang") + 1]
        except:
            pass

    return tipe, jumlah, text, nama

# ================= COMMAND =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot Keuangan Aktif!\n\n/setsaldo 100000")

# SET SALDO
async def setsaldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    saldo = int(context.args[0])

    cursor.execute("""
    INSERT INTO users (user_id, balance)
    VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET balance=?
    """, (user_id, saldo, saldo))
    conn.commit()

    await update.message.reply_text(f"💰 Saldo diset: Rp{saldo:,}")

# CEK SALDO
async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    saldo = row[0] if row else 0

    await update.message.reply_text(f"💰 Saldo sekarang: Rp{saldo:,}")

# HUTANG LIST
async def hutang_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    cursor.execute("""
    SELECT nama, amount, created_at FROM hutang
    WHERE user_id=? AND status='belum'
    """, (user_id,))

    rows = cursor.fetchall()

    if not rows:
        await update.message.reply_text("✅ Tidak ada hutang")
        return

    text = "📌 Hutang belum dibayar:\n\n"
    for r in rows:
        text += f"{r[0]} - Rp{r[1]:,} ({r[2][:10]})\n"

    await update.message.reply_text(text)

# LAPORAN
async def laporan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    bulan = datetime.now().strftime("%Y-%m")

    cursor.execute("""
    SELECT SUM(amount) FROM transaksi
    WHERE user_id=? AND type='income'
    AND strftime('%Y-%m', created_at)=?
    """, (user_id, bulan))
    income = cursor.fetchone()[0] or 0

    cursor.execute("""
    SELECT SUM(amount) FROM transaksi
    WHERE user_id=? AND type='expense'
    AND strftime('%Y-%m', created_at)=?
    """, (user_id, bulan))
    expense = cursor.fetchone()[0] or 0

    laba = income - expense

    await update.message.reply_text(
        f"📊 Laporan {bulan}\n\n"
        f"💰 Income: Rp{income:,}\n"
        f"💸 Expense: Rp{expense:,}\n"
        f"📈 Laba: Rp{laba:,}"
    )

# GRAFIK
async def grafik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    cursor.execute("""
    SELECT DATE(created_at), SUM(amount)
    FROM transaksi
    WHERE user_id=?
    GROUP BY DATE(created_at)
    """, (user_id,))

    data = cursor.fetchall()

    if not data:
        await update.message.reply_text("Tidak ada data")
        return

    tanggal = [d[0] for d in data]
    jumlah = [d[1] for d in data]

    plt.figure()
    plt.plot(tanggal, jumlah)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig("grafik.png")

    await update.message.reply_photo(photo=open("grafik.png", "rb"))

# HANDLE CHAT
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    tipe, jumlah, note, nama = parse_input(text)

    # ambil saldo
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    saldo = row[0] if row else 0

    if tipe == "income":
        saldo += jumlah

    elif tipe == "expense":
        saldo -= jumlah

    elif tipe == "hutang":
        cursor.execute("""
        INSERT INTO hutang (user_id, nama, amount, status)
        VALUES (?, ?, ?, 'belum')
        """, (user_id, nama, jumlah))
        conn.commit()

        await update.message.reply_text(f"🧾 Hutang {nama} Rp{jumlah:,}")
        return

    elif tipe == "bayar":
        cursor.execute("""
        UPDATE hutang SET status='lunas'
        WHERE user_id=? AND nama=?
        """, (user_id, nama))
        conn.commit()

        await update.message.reply_text(f"✅ Hutang {nama} lunas")
        return

    # simpan transaksi
    cursor.execute("""
    INSERT INTO transaksi (user_id, type, amount, note)
    VALUES (?, ?, ?, ?)
    """, (user_id, tipe, jumlah, note))

    cursor.execute("""
    INSERT INTO users (user_id, balance)
    VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET balance=?
    """, (user_id, saldo, saldo))

    conn.commit()

    await update.message.reply_text(
        f"✅ {tipe} Rp{jumlah:,}\n💰 Saldo: Rp{saldo:,}"
    )

# ================= RUN =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("setsaldo", setsaldo))
app.add_handler(CommandHandler("saldo", saldo))
app.add_handler(CommandHandler("hutang", hutang_list))
app.add_handler(CommandHandler("laporan", laporan))
app.add_handler(CommandHandler("grafik", grafik))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

app.run_polling()
