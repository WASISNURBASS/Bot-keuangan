import os
import re
import sqlite3
import json
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")

# fix telegram conflict
requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")

# ================= DB =================
conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS transaksi (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,type TEXT,amount INTEGER,note TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
cursor.execute("CREATE TABLE IF NOT EXISTS debt (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,name TEXT,amount INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS barang (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,nama TEXT,qty INTEGER,harga_beli INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS recycle_bin (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,tipe TEXT,data TEXT)")
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

# ================= RECYCLE =================
def save_deleted(user_id, tipe, data):
    cursor.execute("INSERT INTO recycle_bin (user_id,tipe,data) VALUES (?,?,?)",
                   (user_id, tipe, json.dumps(data)))
    conn.commit()

# ================= FITUR =================
async def saldo(update, context):
    user_id = update.message.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    data = cursor.fetchone()
    await update.message.reply_text(f"💰 Saldo: Rp{(data[0] if data else 0):,}")

async def laporan(update, context):
    user_id = update.message.from_user.id

    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='income'", (user_id,))
    income = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='expense'", (user_id,))
    expense = cursor.fetchone()[0] or 0

    await update.message.reply_text(f"📊 Income: {income:,}\n💸 Expense: {expense:,}\n📈 Laba: {income-expense:,}")

async def hutang_list(update, context):
    user_id = update.message.from_user.id
    cursor.execute("SELECT name,SUM(amount) FROM debt WHERE user_id=? GROUP BY name", (user_id,))
    rows = cursor.fetchall()

    if not rows:
        await update.message.reply_text("✅ Tidak ada hutang")
        return

    text = "📋 Hutang:\n"
    for n,j in rows:
        text += f"- {n} Rp{j:,}\n"

    await update.message.reply_text(text)

async def laporan_bisnis(update, context):
    user_id = update.message.from_user.id

    cursor.execute("SELECT nama,SUM(qty),SUM(qty*harga_beli) FROM barang WHERE user_id=? GROUP BY nama", (user_id,))
    beli = cursor.fetchall()

    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='income'", (user_id,))
    income = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(qty*harga_beli) FROM barang WHERE user_id=?", (user_id,))
    modal = cursor.fetchone()[0] or 0

    text = "📊 Bisnis\n\n📥 Pembelian:\n"
    for n,q,t in beli:
        text += f"- {n} x{q} = Rp{t:,}\n"

    text += f"\n💰 Modal: Rp{modal:,}\n💰 Omset: Rp{income:,}\n📈 Laba: Rp{income-modal:,}"

    await update.message.reply_text(text)

async def undo(update, context):
    user_id = update.message.from_user.id
    cursor.execute("SELECT id,tipe,data FROM recycle_bin WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()

    if not row:
        await update.message.reply_text("❌ Tidak ada undo")
        return

    id_, tipe, data = row
    data = json.loads(data)

    if tipe == "transaksi":
        cursor.execute("INSERT INTO transaksi (user_id,type,amount,note) VALUES (?,?,?,?)",
                       (user_id,data["type"],data["amount"],data["note"]))

    elif tipe == "hutang":
        cursor.execute("INSERT INTO debt (user_id,name,amount) VALUES (?,?,?)",
                       (user_id,data["name"],data["amount"]))

    elif tipe == "barang":
        cursor.execute("INSERT INTO barang (user_id,nama,qty,harga_beli) VALUES (?,?,?,?)",
                       (user_id,data["nama"],data["qty"],data["harga"]))

    cursor.execute("DELETE FROM recycle_bin WHERE id=?", (id_,))
    conn.commit()

    await update.message.reply_text("♻️ Berhasil undo")

async def history(update, context):
    user_id = update.message.from_user.id
    cursor.execute("SELECT tipe,data FROM recycle_bin WHERE user_id=? ORDER BY id DESC LIMIT 5", (user_id,))
    rows = cursor.fetchall()

    text = "🗑️ History:\n"
    for t,d in rows:
        text += f"- {t}: {d}\n"

    await update.message.reply_text(text)

# ================= HANDLE =================
async def handle(update, context):
    user_id = update.message.from_user.id
    text = update.message.text.lower()

    cursor.execute("INSERT OR IGNORE INTO users VALUES (?,0)", (user_id,))

    if text == "saldo": return await saldo(update,context)
    if text == "laporan": return await laporan(update,context)
    if text == "hutang": return await hutang_list(update,context)

    jumlah = parse_amount(text)

    # ===== BELI =====
    if text.startswith("beli"):
        _, nama, harga, qty = text.split()
        harga = parse_amount(harga)
        qty = int(qty)
        total = harga * qty

        cursor.execute("INSERT INTO barang VALUES (NULL,?,?,?,?)",(user_id,nama,qty,harga))
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (total,user_id))
        conn.commit()

        await update.message.reply_text(f"📥 {nama} x{qty} = Rp{total:,}")
        return

    # ===== JUAL =====
    if text.startswith("jual"):
        _, nama, harga, qty = text.split()
        harga = parse_amount(harga)
        qty = int(qty)
        total = harga * qty

        cursor.execute("INSERT INTO transaksi VALUES (NULL,?,?,?, ?,CURRENT_TIMESTAMP)",
                       (user_id,"income",total,f"jual {nama}"))

        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (total,user_id))
        conn.commit()

        await update.message.reply_text(f"🛒 {nama} terjual Rp{total:,}")
        return

    # ===== HUTANG =====
    if "hutang" in text and "bayar" not in text:
        nama = text.split()[1]
        cursor.execute("INSERT INTO debt VALUES (NULL,?,?,?)",(user_id,nama,jumlah))
        conn.commit()
        await update.message.reply_text(f"🧾 Hutang {nama} Rp{jumlah:,}")
        return

    if "bayar hutang" in text:
        nama = text.split()[2]
        cursor.execute("INSERT INTO debt VALUES (NULL,?,?,?)",(user_id,nama,-jumlah))
        conn.commit()
        await update.message.reply_text("💸 Hutang dibayar")
        return

    # ===== HAPUS =====
    if text == "hapus terakhir":
        cursor.execute("SELECT id,type,amount,note FROM transaksi WHERE user_id=? ORDER BY id DESC LIMIT 1",(user_id,))
        d = cursor.fetchone()

        if d:
            id_,t,a,n=d
            save_deleted(user_id,"transaksi",{"type":t,"amount":a,"note":n})
            cursor.execute("DELETE FROM transaksi WHERE id=?", (id_,))
            conn.commit()
            await update.message.reply_text("🗑️ terakhir dihapus")
        return

    # ===== INCOME =====
    if any(x in text for x in ["gaji","bonus","masuk"]):
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (jumlah,user_id))
        cursor.execute("INSERT INTO transaksi VALUES (NULL,?,?,?, ?,CURRENT_TIMESTAMP)",
                       (user_id,"income",jumlah,text))
        conn.commit()
        await update.message.reply_text(f"💰 +Rp{jumlah:,}")
        return

    # ===== EXPENSE =====
    if jumlah > 0:
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (jumlah,user_id))
        cursor.execute("INSERT INTO transaksi VALUES (NULL,?,?,?, ?,CURRENT_TIMESTAMP)",
                       (user_id,"expense",jumlah,text))
        conn.commit()
        await update.message.reply_text(f"💸 -Rp{jumlah:,}")
        return

# ================= MAIN =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("saldo", saldo))
app.add_handler(CommandHandler("laporan", laporan))
app.add_handler(CommandHandler("bisnis", laporan_bisnis))
app.add_handler(CommandHandler("undo", undo))
app.add_handler(CommandHandler("history", history))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("🔥 GOD MODE AKTIF")
app.run_polling()
