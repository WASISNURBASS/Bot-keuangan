import os
import re
import sqlite3
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ================= TOKEN =================
TOKEN = os.getenv("TOKEN")

# FIX TELEGRAM CONFLICT
requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")

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
CREATE TABLE IF NOT EXISTS debt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    amount INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# ================= PARSER =================
def parse_amount(text):
    text = text.lower().replace(".", "").replace(",", "")
    angka = re.findall(r'\d+', text)
    jumlah = int(angka[0]) if angka else 0

    if "jt" in text or "juta" in text:
        jumlah *= 1_000_000
    elif "k" in text or "ribu" in text:
        jumlah *= 1000

    return jumlah

# ================= AI SIMPLE =================
def ai_reply(text):
    if "halo" in text:
        return "👋 Halo juga!"
    if "siapa kamu" in text:
        return "🤖 Aku bot keuangan pintar 😎"
    if "lagi apa" in text:
        return "💰 Lagi ngatur duit kamu 😆"
    return None

# ================= SALDO =================
async def saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    data = cursor.fetchone()
    saldo = data[0] if data else 0
    await update.message.reply_text(f"💰 Saldo: Rp{saldo:,}")

# ================= SET SALDO =================
async def setsaldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        jumlah = int(context.args[0])
    except:
        await update.message.reply_text("❌ /setsaldo 100000")
        return

    cursor.execute("INSERT OR REPLACE INTO users (user_id, balance) VALUES (?, ?)", (user_id, jumlah))
    conn.commit()
    await update.message.reply_text(f"✅ Saldo Rp{jumlah:,}")

# ================= LAPORAN =================
async def laporan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    now = datetime.now().strftime("%Y-%m")

    cursor.execute("""
    SELECT type, SUM(amount) FROM transaksi 
    WHERE user_id=? AND strftime('%Y-%m', created_at)=?
    GROUP BY type
    """, (user_id, now))

    data = cursor.fetchall()
    income, expense = 0, 0

    for tipe, jumlah in data:
        if tipe == "income":
            income = jumlah
        elif tipe == "expense":
            expense = jumlah

    laba = income - expense

    await update.message.reply_text(
        f"📊 Laporan {now}\n\n"
        f"💰 Income: Rp{income:,}\n"
        f"💸 Expense: Rp{expense:,}\n"
        f"📈 Laba: Rp{laba:,}"
    )

# ================= HUTANG =================
async def hutang_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    cursor.execute("SELECT name, SUM(amount) FROM debt WHERE user_id=? GROUP BY name", (user_id,))
    data = cursor.fetchall()

    if not data:
        await update.message.reply_text("✅ Tidak ada hutang")
        return

    text = "📋 Hutang:\n\n"
    for nama, jumlah in data:
        text += f"- {nama} Rp{jumlah:,}\n"

    await update.message.reply_text(text)

# ================= HAPUS =================
async def hapus_hutang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        nama = context.args[0].lower()
    except:
        await update.message.reply_text("❌ /hapus_hutang nama")
        return

    cursor.execute("DELETE FROM debt WHERE user_id=? AND name=?", (user_id, nama))
    conn.commit()
    await update.message.reply_text(f"🗑️ Hutang {nama} dihapus")

# ================= RESET =================
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cursor.execute("DELETE FROM transaksi WHERE user_id=?", (user_id,))
    cursor.execute("DELETE FROM debt WHERE user_id=?", (user_id,))
    cursor.execute("UPDATE users SET balance=0 WHERE user_id=?", (user_id,))
    conn.commit()

    await update.message.reply_text("🔥 Data direset!")

# ================= HANDLE =================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.lower()

    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (user_id,))

    # AI CHAT
    ai = ai_reply(text)
    if ai:
        await update.message.reply_text(ai)
        return

    if text == "saldo":
        await saldo(update, context)
        return

    if text == "laporan":
        await laporan(update, context)
        return

    if text == "hutang":
        await hutang_list(update, context)
        return

    jumlah = parse_amount(text)

    # HUTANG
    if "hutang" in text and "bayar" not in text:
        try:
            nama = text.split()[1]
        except:
            await update.message.reply_text("❌ hutang riska 100k")
            return

        cursor.execute("INSERT INTO debt VALUES (NULL,?,?,?,CURRENT_TIMESTAMP)", (user_id, nama, jumlah))
        conn.commit()
        await update.message.reply_text(f"🧾 Hutang {nama} Rp{jumlah:,}")
        return

    # BAYAR
    if "bayar" in text and "hutang" in text:
        try:
            nama = text.split()[2]
        except:
            await update.message.reply_text("❌ bayar hutang riska 50k")
            return

        cursor.execute("INSERT INTO debt VALUES (NULL,?,?,?,CURRENT_TIMESTAMP)", (user_id, nama, -jumlah))
        conn.commit()
        await update.message.reply_text(f"💸 Bayar {nama} Rp{jumlah:,}")
        return

    # INCOME
    if any(x in text for x in ["gaji", "bonus", "masuk"]):
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (jumlah, user_id))
        cursor.execute("INSERT INTO transaksi VALUES (NULL,?,?,?, ?,CURRENT_TIMESTAMP)", (user_id, "income", jumlah, text))
        conn.commit()
        await update.message.reply_text(f"💰 +Rp{jumlah:,}")
        return

    # EXPENSE
    if jumlah > 0:
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (jumlah, user_id))
        cursor.execute("INSERT INTO transaksi VALUES (NULL,?,?,?, ?,CURRENT_TIMESTAMP)", (user_id, "expense", jumlah, text))
        conn.commit()
        await update.message.reply_text(f"💸 -Rp{jumlah:,}")
        return

# ================= MAIN =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("setsaldo", setsaldo))
app.add_handler(CommandHandler("hapus_hutang", hapus_hutang))
app.add_handler(CommandHandler("reset", reset))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("🚀 Bot jalan...")
app.run_polling()
