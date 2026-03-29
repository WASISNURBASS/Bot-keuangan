import os
import re
import sqlite3
import json
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")

conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

# ================= DB =================
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0)")
cursor.execute("CREATE TABLE IF NOT EXISTS transaksi (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,type TEXT,amount INTEGER,note TEXT,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
cursor.execute("CREATE TABLE IF NOT EXISTS debt (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,name TEXT,amount INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS barang (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,nama TEXT,qty INTEGER,harga_beli INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS recycle_bin (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,tipe TEXT,data TEXT)")
conn.commit()

# ================= UTIL =================
def parse_amount(text):
    text = text.lower().replace(".", "").replace(",", "")
    angka = re.findall(r'\d+', text)
    jumlah = int(angka[0]) if angka else 0
    if "jt" in text or "juta" in text:
        jumlah *= 1_000_000
    elif "k" in text or "ribu" in text:
        jumlah *= 1000
    return jumlah

def normalize_nama(n):
    n = n.lower()
    if "kartu" in n: return "kartu"
    if "pulsa" in n: return "pulsa"
    if "token" in n: return "token"
    return n

def save_deleted(user_id, tipe, data):
    cursor.execute("INSERT INTO recycle_bin (user_id,tipe,data) VALUES (?,?,?)",
                   (user_id, tipe, json.dumps(data)))
    conn.commit()

# ================= AI =================
def ai_financial(user_id, text):
    if not OPENAI_API_KEY:
        return None

    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    saldo = cursor.fetchone()
    saldo = saldo[0] if saldo else 0

    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='income'", (user_id,))
    income = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='expense'", (user_id,))
    expense = cursor.fetchone()[0] or 0

    cursor.execute("SELECT name,SUM(amount) FROM debt WHERE user_id=? GROUP BY name", (user_id,))
    debts = cursor.fetchall()

    debt_text = "\n".join([f"{n}:{a}" for n,a in debts]) if debts else "tidak ada"

    try:
        res = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system","content": f"""
Kamu financial advisor santai.
Saldo:{saldo}
Income:{income}
Expense:{expense}
Hutang:{debt_text}
Kasih saran jelas & singkat.
"""},
                    {"role": "user","content": text}
                ]
            }
        )
        return res.json()["choices"][0]["message"]["content"]
    except:
        return None

# ================= FITUR =================
async def saldo(update,context):
    user_id=update.message.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    d=cursor.fetchone()
    await update.message.reply_text(f"💰 Saldo: Rp{(d[0] if d else 0):,}")

async def laporan(update,context):
    user_id=update.message.from_user.id
    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='income'",(user_id,))
    i=cursor.fetchone()[0] or 0
    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='expense'",(user_id,))
    e=cursor.fetchone()[0] or 0
    await update.message.reply_text(f"📊 Income:{i:,}\nExpense:{e:,}\nLaba:{i-e:,}")

async def hutang_list(update,context):
    user_id=update.message.from_user.id
    cursor.execute("SELECT name,SUM(amount) FROM debt WHERE user_id=? GROUP BY name",(user_id,))
    rows=cursor.fetchall()
    if not rows:
        return await update.message.reply_text("✅ Tidak ada hutang")
    txt="📋 Hutang:\n"
    for n,j in rows:
        txt+=f"- {n} Rp{j:,}\n"
    await update.message.reply_text(txt)

async def laporan_bisnis(update,context):
    user_id=update.message.from_user.id
    cursor.execute("SELECT nama,SUM(qty),SUM(qty*harga_beli) FROM barang WHERE user_id=? GROUP BY nama",(user_id,))
    beli=cursor.fetchall()
    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND type='income'",(user_id,))
    income=cursor.fetchone()[0] or 0
    cursor.execute("SELECT SUM(qty*harga_beli) FROM barang WHERE user_id=?",(user_id,))
    modal=cursor.fetchone()[0] or 0
    txt="📊 BISNIS\n"
    for n,q,t in beli:
        txt+=f"- {n} x{q} Rp{t:,}\n"
    txt+=f"\nModal:{modal:,}\nOmset:{income:,}\nLaba:{income-modal:,}"
    await update.message.reply_text(txt)

async def rekap(update,context):
    user_id=update.message.from_user.id
    try: nama=context.args[0]
    except: return await update.message.reply_text("❌ /rekap budi")
    cursor.execute("SELECT type,amount,created_at FROM transaksi WHERE user_id=? AND note LIKE ?",(user_id,f"%{nama}%"))
    rows=cursor.fetchall()
    if not rows:
        return await update.message.reply_text("❌ Tidak ada data")
    txt=f"📊 Rekap {nama}\n"
    masuk=keluar=0
    for t,a,d in rows:
        d=d.split()[0]
        if t=="income":
            txt+=f"{d} +{a:,}\n"
            masuk+=a
        else:
            txt+=f"{d} -{a:,}\n"
            keluar+=a
    txt+=f"\nMasuk:{masuk:,}\nKeluar:{keluar:,}\nSelisih:{masuk-keluar:,}"
    await update.message.reply_text(txt)

async def undo(update,context):
    user_id=update.message.from_user.id
    cursor.execute("SELECT id,tipe,data FROM recycle_bin WHERE user_id=? ORDER BY id DESC LIMIT 1",(user_id,))
    r=cursor.fetchone()
    if not r:
        return await update.message.reply_text("❌ kosong")
    id_,t,d=r
    d=json.loads(d)
    if t=="transaksi":
        cursor.execute("INSERT INTO transaksi (user_id,type,amount,note) VALUES (?,?,?,?)",(user_id,d["type"],d["amount"],d["note"]))
    elif t=="hutang":
        cursor.execute("INSERT INTO debt (user_id,name,amount) VALUES (?,?,?)",(user_id,d["name"],d["amount"]))
    elif t=="barang":
        cursor.execute("INSERT INTO barang (user_id,nama,qty,harga_beli) VALUES (?,?,?,?)",(user_id,d["nama"],d["qty"],d["harga"]))
    cursor.execute("DELETE FROM recycle_bin WHERE id=?", (id_,))
    conn.commit()
    await update.message.reply_text("♻️ undo berhasil")

async def history(update,context):
    user_id=update.message.from_user.id
    cursor.execute("SELECT tipe,data FROM recycle_bin WHERE user_id=? ORDER BY id DESC LIMIT 5",(user_id,))
    rows=cursor.fetchall()
    txt="🗑️ History:\n"
    for t,d in rows:
        txt+=f"{t}:{d}\n"
    await update.message.reply_text(txt)

# ================= HANDLE =================
async def handle(update,context):
    user_id=update.message.from_user.id
    text=update.message.text.lower()
    cursor.execute("INSERT OR IGNORE INTO users VALUES (?,0)", (user_id,))

    if text=="saldo": return await saldo(update,context)
    if text=="laporan": return await laporan(update,context)
    if text=="hutang": return await hutang_list(update,context)

    jumlah=parse_amount(text)

    # TRANSFER MASUK
    if text.startswith("masuk"):
        nama=text.split()[1]
        cursor.execute("INSERT INTO transaksi VALUES (NULL,?,?,?,CURRENT_TIMESTAMP)",(user_id,"income",jumlah,f"masuk {nama}"))
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (jumlah,user_id))
        conn.commit()
        return await update.message.reply_text(f"💸 masuk {nama} Rp{jumlah:,}")

    # TRANSFER KELUAR
    if text.startswith("keluar"):
        nama=text.split()[1]
        cursor.execute("INSERT INTO transaksi VALUES (NULL,?,?,?,CURRENT_TIMESTAMP)",(user_id,"expense",jumlah,f"keluar {nama}"))
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (jumlah,user_id))
        conn.commit()
        return await update.message.reply_text(f"💸 keluar {nama} Rp{jumlah:,}")

    # BELI
    if text.startswith("beli"):
        _,nama,h,q=text.split()
        nama=normalize_nama(nama)
        h=parse_amount(h); q=int(q)
        total=h*q
        cursor.execute("INSERT INTO barang VALUES (NULL,?,?,?,?)",(user_id,nama,q,h))
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (total,user_id))
        conn.commit()
        return await update.message.reply_text(f"📥 {nama} x{q} Rp{total:,}")

    # JUAL
    if text.startswith("jual"):
        _,nama,h,q=text.split()
        nama=normalize_nama(nama)
        h=parse_amount(h); q=int(q)
        total=h*q
        cursor.execute("INSERT INTO transaksi VALUES (NULL,?,?,?,CURRENT_TIMESTAMP)",(user_id,"income",total,f"jual {nama}"))
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (total,user_id))
        conn.commit()
        return await update.message.reply_text(f"🛒 {nama} Rp{total:,}")

    # HUTANG
    if "hutang" in text and "bayar" not in text:
        nama=text.split()[1]
        cursor.execute("INSERT INTO debt VALUES (NULL,?,?,?)",(user_id,nama,jumlah))
        conn.commit()
        return await update.message.reply_text(f"🧾 hutang {nama} Rp{jumlah:,}")

    if "bayar hutang" in text:
        nama=text.split()[2]
        cursor.execute("INSERT INTO debt VALUES (NULL,?,?,?)",(user_id,nama,-jumlah))
        conn.commit()
        return await update.message.reply_text(f"💸 bayar {nama} Rp{jumlah:,}")

    # HAPUS TERAKHIR
    if text=="hapus terakhir":
        cursor.execute("SELECT id,type,amount,note FROM transaksi WHERE user_id=? ORDER BY id DESC LIMIT 1",(user_id,))
        d=cursor.fetchone()
        if d:
            save_deleted(user_id,"transaksi",{"type":d[1],"amount":d[2],"note":d[3]})
            cursor.execute("DELETE FROM transaksi WHERE id=?", (d[0],))
            conn.commit()
        return await update.message.reply_text("🗑️ terakhir dihapus")

    # INCOME
    if any(x in text for x in ["gaji","bonus"]):
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (jumlah,user_id))
        cursor.execute("INSERT INTO transaksi VALUES (NULL,?,?,?,CURRENT_TIMESTAMP)",(user_id,"income",jumlah,text))
        conn.commit()
        return await update.message.reply_text(f"💰 +Rp{jumlah:,}")

    # EXPENSE
    if jumlah>0:
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (jumlah,user_id))
        cursor.execute("INSERT INTO transaksi VALUES (NULL,?,?,?,CURRENT_TIMESTAMP)",(user_id,"expense",jumlah,text))
        conn.commit()
        return await update.message.reply_text(f"💸 -Rp{jumlah:,}")

    # AI (LAST)
    ai = ai_financial(user_id, text)
    if ai:
        await update.message.reply_text(ai)

# ================= MAIN =================
app=ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("saldo",saldo))
app.add_handler(CommandHandler("laporan",laporan))
app.add_handler(CommandHandler("bisnis",laporan_bisnis))
app.add_handler(CommandHandler("rekap",rekap))
app.add_handler(CommandHandler("undo",undo))
app.add_handler(CommandHandler("history",history))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("🔥 AI FINAL SYSTEM AKTIF")
app.run_polling()
