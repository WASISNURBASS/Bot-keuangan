import os, re, sqlite3, json
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")

conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

# ================= DB =================
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

    # rollback saldo
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
    uid=update.message.from_user.id
    text=update.message.text.lower()

    cursor.execute("INSERT OR IGNORE INTO users VALUES (?,0)",(uid,))

    jumlah=parse_amount(text)
    saldo_awal=get_saldo(uid)

    words=text.split()
    person=None
    barang=None
    kategori="lainnya"

    # ORANG
    if "ke" in words:
        try: person=words[words.index("ke")+1]
        except: pass
    if "dari" in words:
        try: person=words[words.index("dari")+1]
        except: pass

    # BARANG
    if "beli" in words or "jual" in words:
        try: barang=words[1]
        except: pass

    # KATEGORI
    if any(x in text for x in ["makan","minum"]):
        kategori="makanan"

    # ================= HUTANG =================
    if "hutang" in text and "bayar" not in text:
        nama=words[words.index("hutang")+1]
        cursor.execute("INSERT INTO debt VALUES(NULL,?,?,?,CURRENT_TIMESTAMP)",(uid,nama,jumlah))
        conn.commit()
        return await update.message.reply_text(f"🧾 Hutang {nama} Rp{jumlah:,}")

    if "bayar" in text and "hutang" in text:
        nama=words[words.index("hutang")+1]
        cursor.execute("INSERT INTO debt VALUES(NULL,?,?,?,CURRENT_TIMESTAMP)",(uid,nama,-jumlah))
        conn.commit()
        return await update.message.reply_text(f"💸 Bayar hutang {nama} Rp{jumlah:,}")

    # ================= TRANSFER MASUK =================
    if "dari" in text:
        saldo_akhir=saldo_awal+jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"income",jumlah,text,person,None,"transfer"))
        conn.commit()

        return await update.message.reply_text(
            f"💰 Dari {person}\nNominal: Rp{jumlah:,}\nSaldo awal: Rp{saldo_awal:,}\n+ Rp{jumlah:,}\nSaldo akhir: Rp{saldo_akhir:,}"
        )

    # ================= TRANSFER KELUAR =================
    if "ke" in text:
        saldo_akhir=saldo_awal-jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"expense",jumlah,text,person,None,"transfer"))
        conn.commit()

        return await update.message.reply_text(
            f"💸 Ke {person}\nNominal: Rp{jumlah:,}\nSaldo awal: Rp{saldo_awal:,}\n- Rp{jumlah:,}\nSaldo akhir: Rp{saldo_akhir:,}"
        )

    # ================= BELI =================
    if "beli" in text:
        saldo_akhir=saldo_awal-jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"expense",jumlah,text,None,barang,"barang"))
        conn.commit()

        return await update.message.reply_text(
            f"📦 Beli {barang}\nRp{jumlah:,}\nSaldo: {saldo_awal:,} → {saldo_akhir:,}"
        )

    # ================= JUAL =================
    if "jual" in text:
        saldo_akhir=saldo_awal+jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"income",jumlah,text,None,barang,"barang"))
        conn.commit()

        return await update.message.reply_text(
            f"💰 Jual {barang}\nRp{jumlah:,}\nSaldo: {saldo_awal:,} → {saldo_akhir:,}"
        )

    # ================= EXPENSE =================
    if jumlah>0:
        saldo_akhir=saldo_awal-jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"expense",jumlah,text,None,None,kategori))
        conn.commit()

        return await update.message.reply_text(
            f"💸 {kategori}\nRp{jumlah:,}\nSaldo: {saldo_awal:,} → {saldo_akhir:,}"
        )

    # ================= LAPORAN =================
    if "laporan" in text:
        cursor.execute("SELECT name,amount,created_at FROM debt WHERE user_id=?", (uid,))
        hut=""
        for n,a,d in cursor.fetchall():
            dt=datetime.fromisoformat(d)
            hut+=f"- {n} Rp{a:,} ({dt.strftime('%d %b')})\n"

        return await update.message.reply_text(
            f"📊 LAPORAN\n\n💰 Saldo: Rp{get_saldo(uid):,}\n\n💳 Hutang:\n{hut}"
        )

# ================= MAIN =================
app=ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("saldo", saldo_cmd))
app.add_handler(CommandHandler("reset", reset_all))
app.add_handler(CommandHandler("hapus_hutang", hapus_hutang))
app.add_handler(CommandHandler("hapus", hapus_terakhir))

app.add_handler(MessageHandler(filters.TEXT, handle))

print("🔥 SUPER ALL-IN BOT AKTIF")
app.run_polling()
