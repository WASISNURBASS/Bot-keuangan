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
CREATE TABLE IF NOT EXISTS bisnis(
user_id INTEGER PRIMARY KEY,
modal INTEGER DEFAULT 0,
profit INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS stok(
barang TEXT PRIMARY KEY,
jumlah INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS hutang(
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER,
nama TEXT,
amount INTEGER,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# ================= UTIL =================
def clean_text(text):
    return text.lower().replace(".", "").replace(",", "")

def parse_amount(text):
    text = clean_text(text)
    total = 0
    matches = re.findall(r'(\d+)(jt|rb|k)?', text)
    for angka, satuan in matches:
        angka = int(angka)
        if satuan == "jt": angka *= 1_000_000
        elif satuan in ["rb","k"]: angka *= 1000
        total += angka
    return total

def parse_dual(text):
    text = clean_text(text)
    hasil = []
    matches = re.findall(r'(\d+)(jt|rb|k)?', text)
    for angka, satuan in matches:
        angka = int(angka)
        if satuan == "jt": angka *= 1_000_000
        elif satuan in ["rb","k"]: angka *= 1000
        hasil.append(angka)
    return hasil[0], hasil[1] if len(hasil) >= 2 else (0,0)

def detect_intent(text):
    if "jual" in text and "modal" in text: return "bisnis"
    if any(x in text for x in ["dari","masuk","transfer"]): return "income"
    if any(x in text for x in ["ke","beli","bayar","keluar"]): return "expense"
    return "expense"

def detect_person(text):
    m = re.search(r'(dari|ke)\s+(\w+)', text)
    return m.group(2) if m else None

def detect_barang(text):
    words = text.split()
    if "jual" in words:
        try: return words[words.index("jual")+1]
        except: pass
    if "beli" in words:
        try: return words[words.index("beli")+1]
        except: pass
    return None

def detect_kategori(text):
    if "dari" in text or "ke" in text: return "transfer"
    if "jual" in text and "modal" in text: return "bisnis"
    if "beli" in text: return "barang"
    if any(x in text for x in ["gaji","bonus","masuk"]): return "income"
    return "lainnya"

def get_saldo(uid):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    d = cursor.fetchone()
    return d[0] if d else 0

def set_saldo(uid,val):
    cursor.execute("INSERT OR REPLACE INTO users VALUES (?,?)",(uid,val))

def get_bisnis(uid):
    cursor.execute("SELECT modal, profit FROM bisnis WHERE user_id=?", (uid,))
    d = cursor.fetchone()
    return d if d else (0,0)

def set_modal(uid,val):
    cursor.execute("INSERT OR REPLACE INTO bisnis VALUES (?, ?, COALESCE((SELECT profit FROM bisnis WHERE user_id=?),0))",(uid,val,uid))

def tambah_profit(uid,val):
    modal, profit = get_bisnis(uid)
    cursor.execute("INSERT OR REPLACE INTO bisnis VALUES (?,?,?)",(uid,modal,profit+val))

def tambah_stok(barang):
    cursor.execute("INSERT OR IGNORE INTO stok VALUES (?,0)", (barang,))
    cursor.execute("UPDATE stok SET jumlah = jumlah + 1 WHERE barang=?", (barang,))

def kurang_stok(barang):
    cursor.execute("UPDATE stok SET jumlah = jumlah - 1 WHERE barang=?", (barang,))

def get_stok():
    cursor.execute("SELECT * FROM stok")
    return cursor.fetchall()

def hari(dt):
    return ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"][dt.weekday()]

# ================= COMMAND =================
async def saldo_cmd(update,context):
    uid = update.message.from_user.id
    await update.message.reply_text(f"💰 Saldo: Rp{get_saldo(uid):,}")

async def reset_all(update,context):
    uid = update.message.from_user.id
    cursor.execute("DELETE FROM transaksi WHERE user_id=?", (uid,))
    cursor.execute("DELETE FROM bisnis WHERE user_id=?", (uid,))
    cursor.execute("DELETE FROM stok")
    cursor.execute("DELETE FROM hutang WHERE user_id=?", (uid,))
    cursor.execute("UPDATE users SET balance=0 WHERE user_id=?", (uid,))
    conn.commit()
    await update.message.reply_text("🔥 RESET TOTAL")

# ================= HANDLE =================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text.lower()

    cursor.execute("INSERT OR IGNORE INTO users VALUES (?,0)", (uid,))

    jumlah = parse_amount(text)
    saldo_awal = get_saldo(uid)
    saldo_akhir = saldo_awal

    intent = detect_intent(text)
    barang = detect_barang(text)
    person = detect_person(text)
    kategori = detect_kategori(text)

    # ===== SET MODAL =====
    if "modal" in text and "jual" not in text:
        set_modal(uid, jumlah)
        set_saldo(uid, jumlah)
        conn.commit()
        return await update.message.reply_text(f"💼 Modal: Rp{jumlah:,}")

    # ===== HUTANG =====
    if "ngutang" in text:
        cursor.execute("INSERT INTO hutang VALUES(NULL,?,?,?,CURRENT_TIMESTAMP)", (uid,person,jumlah))
        conn.commit()
        return await update.message.reply_text(f"🧾 {person} hutang Rp{jumlah:,}")

    if "bayar" in text and "utang" in text:
        cursor.execute("INSERT INTO hutang VALUES(NULL,?,?,?,CURRENT_TIMESTAMP)", (uid,person,-jumlah))
        conn.commit()
        return await update.message.reply_text(f"💸 {person} bayar Rp{jumlah:,}")

    # ===== BISNIS =====
    if intent == "bisnis":
        jual, modal = parse_dual(text)
        profit = jual - modal

        saldo_akhir += profit
        set_saldo(uid, saldo_akhir)
        tambah_profit(uid, profit)

        kurang_stok(barang)

        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"income",profit,text,None,barang,"bisnis"))
        conn.commit()

        return await update.message.reply_text(f"🔥 Profit Rp{profit:,}")

    # ===== BELI (STOK) =====
    if "beli" in text and barang:
        tambah_stok(barang)

    # ===== TRANSAKSI =====
    if jumlah <= 0:
        return

    if intent == "income":
        saldo_akhir += jumlah
        tipe = "income"
    else:
        saldo_akhir -= jumlah
        tipe = "expense"

    set_saldo(uid, saldo_akhir)

    cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                   (uid, tipe, jumlah, text, person, barang, kategori))

    conn.commit()

    # ===== LAPORAN =====
    if "laporan" in text:
        modal, profit = get_bisnis(uid)

        stok_text = "\n".join([f"- {b}: {j}" for b,j in get_stok()]) or "-"

        cursor.execute("SELECT nama, SUM(amount) FROM hutang WHERE user_id=? GROUP BY nama",(uid,))
        hutang_text = "\n".join([f"- {n}: Rp{t:,}" for n,t in cursor.fetchall()]) or "-"

        return await update.message.reply_text(
            f"📊 TOKO\n"
            f"Saldo: Rp{saldo_akhir:,}\n"
            f"Modal: Rp{modal:,}\n"
            f"Profit: Rp{profit:,}\n\n"
            f"📦 Stok:\n{stok_text}\n\n"
            f"💳 Hutang:\n{hutang_text}"
        )

    return await update.message.reply_text(f"💰 {saldo_awal:,} ➜ {saldo_akhir:,}")

# ================= MAIN =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("saldo", saldo_cmd))
app.add_handler(CommandHandler("reset", reset_all))
app.add_handler(MessageHandler(filters.TEXT, handle))

print("🔥 TOKO PRO MAX AKTIF")
app.run_polling()
