import os, re, sqlite3
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")

conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

# DB
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

# UTIL
def parse_amount(text):
    text=text.lower().replace(".","").replace(",","")
    n=re.findall(r'\d+',text)
    j=int(n[0]) if n else 0
    if "jt" in text: j*=1_000_000
    elif "k" in text: j*=1000
    return j

def saldo(uid):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    d=cursor.fetchone()
    return d[0] if d else 0

def set_saldo(uid,val):
    cursor.execute("INSERT OR REPLACE INTO users VALUES (?,?)",(uid,val))

def hari(dt):
    return ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"][dt.weekday()]

# HANDLE
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.message.from_user.id
    text=update.message.text.lower()

    cursor.execute("INSERT OR IGNORE INTO users VALUES (?,0)",(uid,))

    jumlah=parse_amount(text)
    saldo_awal=saldo(uid)

    words=text.split()
    person=None
    barang=None
    kategori="lainnya"

    # DETEKSI ORANG
    if "ke" in words:
        try: person=words[words.index("ke")+1]
        except: pass
    if "dari" in words:
        try: person=words[words.index("dari")+1]
        except: pass

    # DETEKSI BARANG
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

        cursor.execute("""
        INSERT INTO transaksi(user_id,type,amount,note,person,kategori)
        VALUES (?,?,?,?,?,?)
        """,(uid,"income",jumlah,text,person,"transfer"))

        conn.commit()

        return await update.message.reply_text(
            f"💰 Transfer Masuk dari {person}\n"
            f"Nominal: Rp{jumlah:,}\n"
            f"Saldo awal: Rp{saldo_awal:,}\n"
            f"Penambahan: Rp{jumlah:,}\n"
            f"Saldo akhir: Rp{saldo_akhir:,}"
        )

    # ================= TRANSFER KELUAR =================
    if "ke" in text:
        saldo_akhir=saldo_awal-jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("""
        INSERT INTO transaksi(user_id,type,amount,note,person,kategori)
        VALUES (?,?,?,?,?,?)
        """,(uid,"expense",jumlah,text,person,"transfer"))

        conn.commit()

        return await update.message.reply_text(
            f"💸 Transfer ke {person}\n"
            f"Nominal: Rp{jumlah:,}\n"
            f"Saldo awal: Rp{saldo_awal:,}\n"
            f"Pengurangan: Rp{jumlah:,}\n"
            f"Saldo akhir: Rp{saldo_akhir:,}"
        )

    # ================= BELI =================
    if "beli" in text:
        saldo_akhir=saldo_awal-jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("""
        INSERT INTO transaksi(user_id,type,amount,note,barang,kategori)
        VALUES (?,?,?,?,?,?)
        """,(uid,"expense",jumlah,text,barang,"barang"))

        conn.commit()

        return await update.message.reply_text(
            f"📦 Beli {barang}\n"
            f"Nominal: Rp{jumlah:,}\n"
            f"Saldo awal: Rp{saldo_awal:,}\n"
            f"Pengurangan: Rp{jumlah:,}\n"
            f"Saldo akhir: Rp{saldo_akhir:,}"
        )

    # ================= JUAL =================
    if "jual" in text:
        saldo_akhir=saldo_awal+jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("""
        INSERT INTO transaksi(user_id,type,amount,note,barang,kategori)
        VALUES (?,?,?,?,?,?)
        """,(uid,"income",jumlah,text,barang,"barang"))

        conn.commit()

        return await update.message.reply_text(
            f"💰 Jual {barang}\n"
            f"Nominal: Rp{jumlah:,}\n"
            f"Saldo awal: Rp{saldo_awal:,}\n"
            f"Penambahan: Rp{jumlah:,}\n"
            f"Saldo akhir: Rp{saldo_akhir:,}"
        )

    # ================= EXPENSE =================
    if jumlah>0:
        saldo_akhir=saldo_awal-jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("""
        INSERT INTO transaksi(user_id,type,amount,note,kategori)
        VALUES (?,?,?,?,?)
        """,(uid,"expense",jumlah,text,kategori))

        conn.commit()

        return await update.message.reply_text(
            f"💸 Pengeluaran ({kategori})\n"
            f"Nominal: Rp{jumlah:,}\n"
            f"Saldo awal: Rp{saldo_awal:,}\n"
            f"Pengurangan: Rp{jumlah:,}\n"
            f"Saldo akhir: Rp{saldo_akhir:,}"
        )

    # ================= LAPORAN =================
    if "laporan" in text:
        now=datetime.now()

        # hutang detail
        cursor.execute("SELECT name,amount,created_at FROM debt WHERE user_id=?",(uid,))
        hutang_txt=""
        for n,a,d in cursor.fetchall():
            dt=datetime.fromisoformat(d)
            hutang_txt+=f"- {n} Rp{a:,} ({dt.strftime('%d %b')})\n"

        await update.message.reply_text(
            f"📊 LAPORAN\n\n"
            f"💰 Saldo: Rp{saldo(uid):,}\n\n"
            f"💳 Hutang Detail:\n{hutang_txt}"
        )

# MAIN
app=ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT, handle))

print("🔥 FINAL ALL IN AKTIF")
app.run_polling()
