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
        if satuan == "jt":
            angka *= 1_000_000
        elif satuan in ["rb", "k"]:
            angka *= 1000
        total += angka

    return total

def parse_dual(text):
    text = clean_text(text)
    hasil = []
    matches = re.findall(r'(\d+)(jt|rb|k)?', text)

    for angka, satuan in matches:
        angka = int(angka)
        if satuan == "jt":
            angka *= 1_000_000
        elif satuan in ["rb", "k"]:
            angka *= 1000
        hasil.append(angka)

    if len(hasil) < 2:
        return 0, 0

    return hasil[0], hasil[1]

def detect_intent(text):
    if "jual" in text and "modal" in text:
        return "bisnis"
    if any(x in text for x in ["dari","masuk","transfer","kirim"]):
        return "income"
    if any(x in text for x in ["ke","bayar","beli","keluar"]):
        return "expense"
    return "expense"

def detect_person(text):
    match = re.search(r'(dari|ke)\s+(\w+)', text)
    if match:
        return match.group(2)
    return None

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
    if "dari" in text or "ke" in text:
        return "transfer"
    if "jual" in text and "modal" in text:
        return "bisnis"
    if "beli" in text:
        return "barang"
    if any(x in text for x in ["gaji","bonus","masuk"]):
        return "income"
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
    cursor.execute("""
    INSERT OR REPLACE INTO bisnis 
    VALUES (?, ?, COALESCE((SELECT profit FROM bisnis WHERE user_id=?),0))
    """,(uid,val,uid))

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

    intent = detect_intent(text)
    person = detect_person(text)
    barang = detect_barang(text)
    kategori = detect_kategori(text)

    # ===== LAPORAN (PALING ATAS BIAR GAK KE-SKIP) =====
    if text.strip() == "laporan":
        cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='income'", (uid,))
        income = cursor.fetchone()[0] or 0

        cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='expense'", (uid,))
        expense = cursor.fetchone()[0] or 0

        laba = income - expense
        modal, profit = get_bisnis(uid)

        # kategori
        cursor.execute("SELECT kategori, SUM(amount) FROM transaksi WHERE user_id=? GROUP BY kategori",(uid,))
        kategori_text = "\n".join([f"- {k}: Rp{t:,}" for k,t in cursor.fetchall()]) or "-"

        # transaksi
        cursor.execute("SELECT type, amount, created_at FROM transaksi WHERE user_id=? ORDER BY id DESC LIMIT 5",(uid,))
        trx=""
        for t,a,d in cursor.fetchall():
            dt=datetime.fromisoformat(d)
            trx+=f"{hari(dt)} {dt.strftime('%H:%M')} Rp{a:,} ({t})\n"

        return await update.message.reply_text(
            f"📊 LAPORAN TOKO\n"
            f"{datetime.now().strftime('%d %b %Y %H:%M')}\n\n"
            f"💰 Saldo: Rp{get_saldo(uid):,}\n"
            f"💼 Modal: Rp{modal:,}\n"
            f"🔥 Profit: Rp{profit:,}\n\n"
            f"📈 Income: Rp{income:,}\n"
            f"📉 Expense: Rp{expense:,}\n"
            f"🔥 Laba: Rp{laba:,}\n\n"
            f"📊 Kategori:\n{kategori_text}\n\n"
            f"🧾 Transaksi:\n{trx if trx else '-'}"
        )

    # ===== SET MODAL =====
    if ("modal" in text or "set modal" in text) and "jual" not in text:
        set_modal(uid, jumlah)
        set_saldo(uid, jumlah)
        conn.commit()
        return await update.message.reply_text(f"💼 MODAL DISET Rp{jumlah:,}")

    # ===== BISNIS =====
    if intent == "bisnis":
        jual, modal = parse_dual(text)
        if jual == 0 or modal == 0:
            return await update.message.reply_text("❌ contoh: jual 10k modal 5k")

        profit = jual - modal
        saldo_akhir += profit

        set_saldo(uid, saldo_akhir)
        tambah_profit(uid, profit)

        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"income",profit,text,None,barang,"bisnis"))

        conn.commit()

        return await update.message.reply_text(
            f"🔥 PROFIT Rp{profit:,}\n{saldo_awal:,} ➜ {saldo_akhir:,}"
        )

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

    return await update.message.reply_text(
        f"💰 {tipe.upper()}\nRp{jumlah:,}\n{saldo_awal:,} ➜ {saldo_akhir:,}"
    )

# ================= MAIN =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("saldo", saldo_cmd))
app.add_handler(CommandHandler("reset", reset_all))
app.add_handler(MessageHandler(filters.TEXT, handle))

print("🔥 TOKO PRO FINAL AKTIF")
app.run_polling()
