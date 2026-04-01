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
    nama=context.args[0]
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

    # ===== SET SALDO =====
    if "saldo awal" in text or "set saldo" in text:
        set_saldo(uid, jumlah)
        return await update.message.reply_text(f"💰 Saldo di set: Rp{jumlah:,}")

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

        # transaksi
        cursor.execute("SELECT type, amount, created_at FROM transaksi WHERE user_id=? ORDER BY id DESC LIMIT 5",(uid,))
        trx=""
        for t,a,d in cursor.fetchall():
            dt=datetime.fromisoformat(d)
            trx+=f"{hari(dt)} {dt.strftime('%H:%M')} Rp{a:,} ({t})\n"

        # hutang
        cursor.execute("SELECT name, SUM(amount) FROM debt WHERE user_id=? GROUP BY name",(uid,))
        hutang=""
        for n,total in cursor.fetchall():
            if total > 0:
                hutang += f"- {n}: Rp{total:,}\n"

        if hutang=="": hutang="Tidak ada"

        # kategori
        cursor.execute("SELECT kategori, SUM(amount) FROM transaksi WHERE user_id=? GROUP BY kategori",(uid,))
        kategori_text=""
        for k,total in cursor.fetchall():
            kategori_text+=f"- {k}: Rp{total:,}\n"

        if kategori_text=="": kategori_text="Tidak ada"

        return await update.message.reply_text(
            f"📊 LAPORAN\n\n"
            f"💰 Saldo: Rp{get_saldo(uid):,}\n\n"
            f"📈 Income: Rp{income:,}\n"
            f"📉 Expense: Rp{expense:,}\n"
            f"🔥 Laba: Rp{laba:,}\n\n"
            f"🧾 Transaksi:\n{trx}\n"
            f"💳 Hutang:\n{hutang}\n"
            f"📊 Kategori:\n{kategori_text}"
        )

    # ================= HUTANG =================
    if "hutang" in text and "bayar" not in text:
        nama = words[words.index("hutang")+1]
        cursor.execute("INSERT INTO debt VALUES(NULL,?,?,?,CURRENT_TIMESTAMP)", (uid,nama,jumlah))
        conn.commit()
        return await update.message.reply_text(f"🧾 Hutang {nama} Rp{jumlah:,}")

    if "bayar" in text and "hutang" in text:
        nama = words[words.index("hutang")+1]
        cursor.execute("INSERT INTO debt VALUES(NULL,?,?,?,CURRENT_TIMESTAMP)", (uid,nama,-jumlah))
        conn.commit()
        return await update.message.reply_text(f"💸 Bayar hutang {nama} Rp{jumlah:,}")

    # ================= AUTO BISNIS =================
    if "jual" in text and "modal" in text:
        angka = re.findall(r'\d+', text.replace(".", "").replace(",", ""))
        jual = int(angka[0])
        modal = int(angka[1])

        profit = jual - modal
        saldo_akhir = saldo_awal + profit
        set_saldo(uid, saldo_akhir)

        barang = words[1] if len(words) > 1 else "barang"

        cursor.execute("INSERT INTO transaksi(user_id,type,amount,note,barang,kategori) VALUES (?,?,?,?,?,?)",
                       (uid,"income",profit,text,barang,"bisnis"))
        conn.commit()

        return await update.message.reply_text(f"🔥 Profit Rp{profit:,}\n{saldo_awal:,} ➜ {saldo_akhir:,}")

    # ================= TRANSAKSI =================
    if "dari" in text and jumlah>0:
        saldo_akhir+=jumlah
        set_saldo(uid,saldo_akhir)
        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"income",jumlah,text,person,None,"transfer"))

    elif "ke" in text and jumlah>0:
        saldo_akhir-=jumlah
        set_saldo(uid,saldo_akhir)
        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"expense",jumlah,text,person,None,"transfer"))

    elif "beli" in text and jumlah>0:
        saldo_akhir-=jumlah
        set_saldo(uid,saldo_akhir)
        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"expense",jumlah,text,None,barang,"barang"))

    elif any(x in text for x in ["masuk","gaji","bonus","tambah","untung"]) and jumlah>0:
        saldo_akhir+=jumlah
        set_saldo(uid,saldo_akhir)
        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"income",jumlah,text,None,None,"income"))

    elif jumlah>0:
        saldo_akhir-=jumlah
        set_saldo(uid,saldo_akhir)
        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"expense",jumlah,text,None,None,"lainnya"))

    else:
        return

    conn.commit()
    return await update.message.reply_text(f"💰 Rp{saldo_awal:,} ➜ Rp{saldo_akhir:,}")

# ================= MAIN =================
app=ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("saldo", saldo_cmd))
app.add_handler(CommandHandler("reset", reset_all))
app.add_handler(CommandHandler("hapus_hutang", hapus_hutang))
app.add_handler(CommandHandler("hapus", hapus_terakhir))

app.add_handler(MessageHandler(filters.TEXT, handle))

print("🔥 BOT SIAP FULL FITUR")
app.run_polling()
