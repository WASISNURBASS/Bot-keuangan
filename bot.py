import requests
import os

TOKEN = os.getenv("TOKEN")

# MATIKAN SESSION LAMA
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
conn.commit()

# ================= UTIL =================
def parse_amount(text):
    text=text.lower().replace(".","").replace(",","")
    angka=re.findall(r'\d+',text)
    jumlah=int(angka[0]) if angka else 0
    if "jt" in text: jumlah*=1_000_000
    elif "k" in text: jumlah*=1000
    return jumlah

def get_saldo(uid):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    d=cursor.fetchone()
    return d[0] if d else 0

def set_saldo(uid,val):
    cursor.execute("INSERT OR REPLACE INTO users VALUES (?,?)",(uid,val))

def hari(dt):
    return ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"][dt.weekday()]

# ================= COMMAND =================
async def saldo_cmd(update,context):
    uid=update.message.from_user.id
    await update.message.reply_text(f"💰 Saldo: Rp{get_saldo(uid):,}")

async def reset_all(update,context):
    uid=update.message.from_user.id
    cursor.execute("DELETE FROM transaksi WHERE user_id=?", (uid,))
    cursor.execute("DELETE FROM debt WHERE user_id=?", (uid,))
    cursor.execute("UPDATE users SET balance=0 WHERE user_id=?", (uid,))
    conn.commit()
    await update.message.reply_text("🔥 Semua data direset")

async def hapus_hutang(update,context):
    uid=update.message.from_user.id
    try:
        nama=context.args[0]
    except:
        return await update.message.reply_text("contoh: /hapus_hutang budi")

    cursor.execute("DELETE FROM debt WHERE user_id=? AND name=?", (uid,nama))
    conn.commit()
    await update.message.reply_text(f"🗑️ Hutang {nama} dihapus")

async def hapus_terakhir(update,context):
    uid=update.message.from_user.id

    cursor.execute("SELECT id,amount,type FROM transaksi WHERE user_id=? ORDER BY id DESC LIMIT 1",(uid,))
    data=cursor.fetchone()

    if not data:
        return await update.message.reply_text("❌ Tidak ada data")

    id_,amount,type_=data
    saldo_now=get_saldo(uid)

    if type_=="income":
        set_saldo(uid,saldo_now-amount)
    else:
        set_saldo(uid,saldo_now+amount)

    cursor.execute("DELETE FROM transaksi WHERE id=?", (id_,))
    conn.commit()

    await update.message.reply_text("🗑️ Transaksi terakhir dihapus")

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
    kategori = "lainnya"

    # DETEKSI ORANG
    if "ke" in words:
        try: person = words[words.index("ke")+1]
        except: pass
    if "dari" in words:
        try: person = words[words.index("dari")+1]
        except: pass

    # DETEKSI BARANG
    if "beli" in words or "jual" in words:
        try: barang = words[1]
        except: pass

    # KATEGORI
    if any(x in text for x in ["makan","minum"]):
        kategori="makanan"

    # ===== LAPORAN (FIX DI DALAM HANDLE) =====
    if "laporan" in text:
        cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='income'", (uid,))
        income = cursor.fetchone()[0] or 0

        cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='expense'", (uid,))
        expense = cursor.fetchone()[0] or 0

        laba = income - expense

        cursor.execute("""
        SELECT type, amount, created_at 
        FROM transaksi WHERE user_id=? ORDER BY id DESC LIMIT 5
        """, (uid,))
        trx=""

        for t,a,d in cursor.fetchall():
            dt=datetime.fromisoformat(d)
            trx+=f"{hari(dt)} Rp{a:,} ({t})\n"

        cursor.execute("SELECT name,amount FROM debt WHERE user_id=?", (uid,))
        hutang=""
        for n,a in cursor.fetchall():
            hutang+=f"- {n} Rp{a:,}\n"

        return await update.message.reply_text(
            f"📊 LAPORAN\n\n"
            f"💰 Saldo: Rp{get_saldo(uid):,}\n\n"
            f"📈 Income: Rp{income:,}\n"
            f"📉 Expense: Rp{expense:,}\n"
            f"🔥 Laba: Rp{laba:,}\n\n"
            f"🧾 Transaksi:\n{trx}\n"
            f"💳 Hutang:\n{hutang if hutang else 'Tidak ada'}"
        )

    # ===== HUTANG =====
    if "hutang" in text and "bayar" not in text:
        try:
            nama = words[words.index("hutang")+1]
        except:
            return await update.message.reply_text("contoh: hutang budi 100k")

        cursor.execute("INSERT INTO debt VALUES(NULL,?,?,?,CURRENT_TIMESTAMP)", (uid,nama,jumlah))
        conn.commit()
        return await update.message.reply_text(f"🧾 Hutang {nama} Rp{jumlah:,}")

    if "bayar" in text and "hutang" in text:
        try:
            nama = words[words.index("hutang")+1]
        except:
            return await update.message.reply_text("contoh: bayar hutang budi 50k")

        cursor.execute("INSERT INTO debt VALUES(NULL,?,?,?,CURRENT_TIMESTAMP)", (uid,nama,-jumlah))
        conn.commit()
        return await update.message.reply_text(f"💸 Bayar hutang {nama} Rp{jumlah:,}")

    # ===== TRANSFER MASUK =====
    if "dari" in text and jumlah>0:
        saldo_akhir=saldo_awal+jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi(user_id,type,amount,note,person,kategori) VALUES (?,?,?,?,?,?)",
                       (uid,"income",jumlah,text,person,"transfer"))
        conn.commit()

        return await update.message.reply_text(
            f"💰 Dari {person}\nRp{jumlah:,}\n{saldo_awal:,} ➜ {saldo_akhir:,}"
        )

    # ===== TRANSFER KELUAR =====
    if "ke" in text and jumlah>0:
        saldo_akhir=saldo_awal-jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi(user_id,type,amount,note,person,kategori) VALUES (?,?,?,?,?,?)",
                       (uid,"expense",jumlah,text,person,"transfer"))
        conn.commit()

        return await update.message.reply_text(
            f"💸 Ke {person}\nRp{jumlah:,}\n{saldo_awal:,} ➜ {saldo_akhir:,}"
        )

    # ===== INCOME =====
    if any(x in text for x in ["masuk","gaji","bonus","tambah"]) and jumlah>0:
        saldo_akhir=saldo_awal+jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi(user_id,type,amount,note,kategori) VALUES (?,?,?,?,?)",
                       (uid,"income",jumlah,text,"income"))
        conn.commit()

        return await update.message.reply_text(f"💰 +Rp{jumlah:,}\n{saldo_awal:,} ➜ {saldo_akhir:,}")
# ================= AUTO BISNIS =================
    if "jual" in text and "modal" in text:
        try:
            angka = re.findall(r'\d+', text.replace(".", "").replace(",", ""))
            jual = int(angka[0])
            modal = int(angka[1])
        except:
            return await update.message.reply_text("contoh: jual pulsa 7000 modal 5500")

        profit = jual - modal

        saldo_akhir = saldo_awal + profit
        set_saldo(uid, saldo_akhir)

        barang = words[1] if len(words) > 1 else "barang"

        cursor.execute("""
        INSERT INTO transaksi(user_id,type,amount,note,barang,kategori)
        VALUES (?,?,?,?,?,?)
        """, (uid, "income", profit, text, barang, "bisnis"))

        conn.commit()

        return await update.message.reply_text(
            f"📦 {barang}\n"
            f"Modal: Rp{modal:,}\n"
            f"Jual: Rp{jual:,}\n"
            f"🔥 Profit: Rp{profit:,}\n\n"
            f"Saldo: Rp{saldo_awal:,} ➜ Rp{saldo_akhir:,}"
        )

    # ===== BELI =====
    if "beli" in text and jumlah>0:
        saldo_akhir=saldo_awal-jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi(user_id,type,amount,note,barang,kategori) VALUES (?,?,?,?,?,?)",
                       (uid,"expense",jumlah,text,barang,"barang"))
        conn.commit()

        return await update.message.reply_text(f"📦 {barang}\n-Rp{jumlah:,}\n{saldo_awal:,} ➜ {saldo_akhir:,}")


        return await update.message.reply_text(f"📦 {barang}\n-Rp{jumlah:,}\n{saldo_awal:,} ➜ {saldo_akhir:,}")

    # ===== JUAL =====
    if "jual" in text and jumlah>0:
        saldo_akhir=saldo_awal+jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi(user_id,type,amount,note,barang,kategori) VALUES (?,?,?,?,?,?)",
                       (uid,"income",jumlah,text,barang,"barang"))
        conn.commit()

        return await update.message.reply_text(f"💰 {barang}\n+Rp{jumlah:,}\n{saldo_awal:,} ➜ {saldo_akhir:,}")

    # ===== EXPENSE =====
    if jumlah>0:
        saldo_akhir=saldo_awal-jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi(user_id,type,amount,note,kategori) VALUES (?,?,?,?,?)",
                       (uid,"expense",jumlah,text,kategori))
        conn.commit()

        return await update.message.reply_text(f"💸 -Rp{jumlah:,}\n{saldo_awal:,} ➜ {saldo_akhir:,}")

# ================= MAIN =================
app=ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("saldo", saldo_cmd))
app.add_handler(CommandHandler("reset", reset_all))
app.add_handler(CommandHandler("hapus_hutang", hapus_hutang))
app.add_handler(CommandHandler("hapus", hapus_terakhir))

app.add_handler(MessageHandler(filters.TEXT, handle))

print("🔥 BOT FIX SIAP JALAN")
app.run_polling()
