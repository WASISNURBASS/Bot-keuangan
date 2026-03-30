import os, re, sqlite3, json, requests, asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN=os.getenv("TOKEN")
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY")
OCR_API_KEY=os.getenv("OCR_API_KEY","helloworld")

requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")

conn=sqlite3.connect("finance.db",check_same_thread=False)
cursor=conn.cursor()

# ================= DB =================
cursor.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,balance INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS transaksi(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,type TEXT,amount INTEGER,note TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
cursor.execute("CREATE TABLE IF NOT EXISTS debt(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,name TEXT,amount INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS barang(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,nama TEXT,qty INTEGER,harga_beli INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS recycle_bin(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,tipe TEXT,data TEXT)")
conn.commit()

# ================= UTIL =================
def parse_amount(text):
    text=text.lower().replace(".","").replace(",","")
    angka=re.findall(r'\d+',text)
    jumlah=int(angka[0]) if angka else 0
    if "jt" in text or "juta" in text: jumlah*=1_000_000
    elif "k" in text or "ribu" in text: jumlah*=1000
    return jumlah

def get_saldo(uid):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    d=cursor.fetchone()
    return d[0] if d else 0

def set_saldo(uid,val):
    cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (val,uid))

def hari_indo(d):
    return ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"][d.weekday()]

def save_deleted(uid,tipe,data):
    cursor.execute("INSERT INTO recycle_bin(user_id,tipe,data) VALUES(?,?,?)",(uid,tipe,json.dumps(data)))
    conn.commit()

# ================= OCR =================
def ocr_image(url):
    try:
        r=requests.post("https://api.ocr.space/parse/image",data={"apikey":OCR_API_KEY,"url":url})
        return r.json()["ParsedResults"][0]["ParsedText"]
    except:
        return ""

# ================= AI =================
def ai_financial(uid,text):
    if not OPENAI_API_KEY: return None
    saldo=get_saldo(uid)
    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='expense'",(uid,))
    expense=cursor.fetchone()[0] or 0
    try:
        r=requests.post("https://api.openai.com/v1/chat/completions",
        headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},
        json={"model":"gpt-4o-mini","messages":[
            {"role":"system","content":f"Saldo:{saldo},Expense:{expense}. Kasih saran keuangan."},
            {"role":"user","content":text}
        ]})
        return r.json()["choices"][0]["message"]["content"]
    except:
        return None

# ================= LAPORAN =================
async def laporan(update,context):
    uid=update.message.from_user.id
    now=datetime.now()
    bulan=now.strftime("%Y-%m")

    # income & expense
    cursor.execute("SELECT type,SUM(amount) FROM transaksi WHERE user_id=? AND strftime('%Y-%m',created_at)=? GROUP BY type",(uid,bulan))
    income=expense=0
    for t,j in cursor.fetchall():
        if t=="income": income=j
        else: expense=j

    laba=income-expense

    # hutang aktif
    cursor.execute("SELECT name,SUM(amount) FROM debt WHERE user_id=? GROUP BY name HAVING SUM(amount)>0",(uid,))
    hutang="\n".join([f"- {n}: Rp{j:,}" for n,j in cursor.fetchall()]) or "- Tidak ada"

    # bulan lalu
    bulan_lalu=(now.replace(day=1)-timedelta(days=1)).strftime("%Y-%m")
    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='expense' AND strftime('%Y-%m',created_at)=?",(uid,bulan_lalu))
    prev=cursor.fetchone()[0] or 0
    diff=expense-prev
    status="🔺 Naik" if diff>0 else "🔻 Turun" if diff<0 else "➖ Stabil"

    # detail
    cursor.execute("SELECT amount,note,created_at FROM transaksi WHERE user_id=? AND strftime('%Y-%m',created_at)=?",(uid,bulan))
    detail=""
    for a,n,d in cursor.fetchall():
        dt=datetime.fromisoformat(d)
        detail+=f"- {hari_indo(dt)}, {dt.strftime('%d %b')} | {'+' if a>0 else ''}{a:,} ({n})\n"

    text=f"📊 LAPORAN {now.strftime('%B %Y')}\n\n"
    text+=f"💰 Income: Rp{income:,}\n💸 Expense: Rp{expense:,}\n📈 Laba: Rp{laba:,}\n\n"
    text+=f"💳 Hutang:\n{hutang}\n\n"
    text+=f"📉 Bulanan:\nBulan ini:{expense:,}\nBulan lalu:{prev:,}\n{status} Rp{abs(diff):,}\n\n"
    text+=f"📅 Detail:\n{detail}"

    await update.message.reply_text(text)

# ================= HANDLE =================
async def handle(update,context):
    uid=update.message.from_user.id
    text=update.message.text.lower() if update.message.text else ""

    cursor.execute("INSERT OR IGNORE INTO users VALUES (?,0)",(uid,))

    if text=="laporan":
        return await laporan(update,context)

    jumlah=parse_amount(text)
    saldo_awal=get_saldo(uid)

    # OCR FOTO
    if update.message.photo:
        f=await update.message.photo[-1].get_file()
        ocr_text=ocr_image(f.file_path)
        jumlah=parse_amount(ocr_text)

    # INCOME
    if any(x in text for x in ["masuk","gaji","bonus","uang masuk","transfer masuk"]):
        saldo_akhir=saldo_awal+jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"income",jumlah,text))
        conn.commit()

        return await update.message.reply_text(
            f"💰 Income: Rp{jumlah:,}\n"
            f"Saldo awal: Rp{saldo_awal:,}\n"
            f"Penambahan: Rp{jumlah:,}\n"
            f"Saldo akhir: Rp{saldo_akhir:,}"
        )

    # EXPENSE
    if jumlah>0:
        saldo_akhir=saldo_awal-jumlah
        set_saldo(uid,saldo_akhir)

        cursor.execute("INSERT INTO transaksi VALUES(NULL,?,?,?,CURRENT_TIMESTAMP)",
                       (uid,"expense",jumlah,text))
        conn.commit()

        return await update.message.reply_text(
            f"💸 Expense: Rp{jumlah:,}\n"
            f"Saldo awal: Rp{saldo_awal:,}\n"
            f"Pengurangan: Rp{jumlah:,}\n"
            f"Saldo akhir: Rp{saldo_akhir:,}"
        )

    # AI
    ai=ai_financial(uid,text)
    if ai:
        await update.message.reply_text(ai)

# ================= AUTO LAPORAN =================
async def auto_laporan(app):
    while True:
        now=datetime.now()
        if now.day==28 and now.hour==9:
            cursor.execute("SELECT user_id FROM users")
            for (uid,) in cursor.fetchall():
                try:
                    await app.bot.send_message(uid,"📊 Laporan otomatis tersedia")
                except: pass
        await asyncio.sleep(3600)

# ================= MAIN =================
app=ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("laporan",laporan))
app.add_handler(MessageHandler(filters.ALL,handle))

async def main():
    asyncio.create_task(auto_laporan(app))
    print("🔥 FULL SYSTEM AKTIF (SEMUA FITUR)")
    await app.run_polling()

asyncio.run(main())
