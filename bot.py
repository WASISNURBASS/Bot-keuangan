import requests
import os

TOKEN = os.getenv("TOKEN")

requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true")

import re, sqlite3
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

# ================= DB =================
conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,balance INTEGER)")
cursor.execute("""
CREATE TABLE IF NOT EXISTS transaksi(
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER,
type TEXT,
amount INTEGER,
note TEXT,
person TEXT,
barang TEXT,
kategori TEXT,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS debt(
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER,
name TEXT,
amount INTEGER,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
""")

# 🔥 TAMBAHAN BISNIS
cursor.execute("""
CREATE TABLE IF NOT EXISTS bisnis(
user_id INTEGER PRIMARY KEY,
modal INTEGER DEFAULT 0,
profit INTEGER DEFAULT 0
)
""")

conn.commit()

# ================= UTIL =================
def clean_text(text):
    return text.lower().replace(".", "").replace(",", "")

def parse_amount(text):
    text = clean_text(text)
    angka = re.findall(r'\d+', text)
    if not angka:
        return 0

    jumlah = int(angka[0])

    if "jt" in text:
        jumlah *= 1_000_000
    elif "k" in text or "rb" in text:
        jumlah *= 1000

    return jumlah

def parse_dual(text):
    text = clean_text(text)
    angka = re.findall(r'\d+', text)

    if len(angka) < 2:
        return 0,0

    a = int(angka[0])
    b = int(angka[1])

    if "k" in text or "rb" in text:
        a *= 1000
        b *= 1000
    if "jt" in text:
        a *= 1_000_000
        b *= 1_000_000

    return a,b

def get_saldo(uid):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    d = cursor.fetchone()
    return d[0] if d else 0

def set_saldo(uid,val):
    cursor.execute("INSERT OR REPLACE INTO users VALUES (?,?)",(uid,val))

# 🔥 BISNIS FUNCTION
def get_bisnis(uid):
    cursor.execute("SELECT modal, profit FROM bisnis WHERE user_id=?", (uid,))
    d = cursor.fetchone()
    return d if d else (0,0)

def set_modal(uid,val):
    cursor.execute("INSERT OR REPLACE INTO bisnis VALUES (?, ?, COALESCE((SELECT profit FROM bisnis WHERE user_id=?),0))",(uid,val,uid))

def tambah_profit(uid,val):
    modal, profit = get_bisnis(uid)
    cursor.execute("INSERT OR REPLACE INTO bisnis VALUES (?,?,?)",(uid,modal,profit+val))

def hari(dt):
    return ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"][dt.weekday()]

# ================= COMMAND =================
async def saldo_cmd(update,context):
    uid = update.message.from_user.id
    await update.message.reply_text(f"💰 Saldo: Rp{get_saldo(uid):,}")

async def reset_all(update,context):
    uid = update.message.from_user.id
    cursor.execute("DELETE FROM transaksi WHERE user_id=?", (uid,))
    cursor.execute("DELETE FROM debt WHERE user_id=?", (uid,))
    cursor.execute("DELETE FROM bisnis WHERE user_id=?", (uid,))
    cursor.execute("UPDATE users SET balance=0 WHERE user_id=?", (uid,))
    conn.commit()
    await update.message.reply_text("🔥 Semua data direset")

# ================= HANDLE =================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text.lower()

    cursor.execute("INSERT OR IGNORE INTO users VALUES (?,0)", (uid,))

    jumlah = parse_amount(text)
    saldo_awal = get_saldo(uid)
    saldo_akhir = saldo_awal

    words = text.split()
    person = None
    barang = None

    # ===== SET MODAL =====
    if "modal" in text and "jual" not in text:
        set_modal(uid, jumlah)
        set_saldo(uid, jumlah)
        conn.commit()
        return await update.message.reply_text(f"💼 Modal & Saldo: Rp{jumlah:,}")

    # ===== DETEKSI =====
    if "ke" in words:
        try: person = words[words.index("ke")+1]
        except: pass
    if "dari" in words:
        try: person = words[words.index("dari")+1]
        except: pass
    if "beli" in words or "jual" in words:
        try: barang = words[1]
        except: pass

    # ================= LAPORAN =================
    if "laporan" in text:
        cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='income'", (uid,))
        income = cursor.fetchone()[0] or 0

        cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='expense'", (uid,))
        expense = cursor.fetchone()[0] or 0

        laba = income - expense

        modal, profit = get_bisnis(uid)

        # transaksi
        cursor.execute("SELECT type, amount, created_at FROM transaksi WHERE user_id=? ORDER BY id DESC LIMIT 5",(uid,))
        trx=""
        for t,a,d in cursor.fetchall():
            dt=datetime.fromisoformat(d)
            trx+=f"{hari(dt)} {dt.strftime('%H:%M')} Rp{a:,} ({t})\n"

        return await update.message.reply_text(
            f"📊 LAPORAN TOKO\n\n"
            f"💰 Saldo: Rp{get_saldo(uid):,}\n"
            f"💼 Modal: Rp{modal:,}\n"
            f"🔥 Profit: Rp{profit:,}\n\n"
            f"📈 Income: Rp{income:,}\n"
            f"📉 Expense: Rp{expense:,}\n"
            f"🔥 Laba: Rp{laba:,}\n\n"
            f"🧾 Transaksi:\n{trx}"
        )

    # ================= AUTO BISNIS =================
    if "jual" in text and "modal" in text:
        jual, modal = parse_dual(text)

        profit = jual - modal

        saldo_akhir = saldo_awal + profit
        set_saldo(uid, saldo_akhir)

        tambah_profit(uid, profit)

        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"income",profit,text,None,barang,"bisnis"))
        conn.commit()

        return await update.message.reply_text(
            f"🔥 Profit Rp{profit:,}\n{saldo_awal:,} ➜ {saldo_akhir:,}"
        )

    # ================= TRANSAKSI =================
    if "dari" in text and jumlah>0:
        saldo_akhir+=jumlah
        tipe="income"

    elif "ke" in text and jumlah>0:
        saldo_akhir-=jumlah
        tipe="expense"

    elif "beli" in text and jumlah>0:
        saldo_akhir-=jumlah
        tipe="expense"

    elif any(x in text for x in ["masuk","gaji","bonus","tambah","untung"]) and jumlah>0:
        saldo_akhir+=jumlah
        tipe="income"

    elif jumlah>0:
        saldo_akhir-=jumlah
        tipe="expense"

    else:
        return

    set_saldo(uid,saldo_akhir)

    cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                   (uid,tipe,jumlah,text,person,barang,"lainnya"))
    conn.commit()

    return await update.message.reply_text(f"💰 Rp{saldo_awal:,} ➜ Rp{saldo_akhir:,}")

# ================= MAIN =================
app=ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("saldo", saldo_cmd))
app.add_handler(CommandHandler("reset", reset_all))
app.add_handler(MessageHandler(filters.TEXT, handle))

print("🔥 TOKO MODE AKTIF")
app.run_polling()
