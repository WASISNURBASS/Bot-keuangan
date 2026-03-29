import os
import re
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TOKEN")

# ================= DATABASE =================
conn = sqlite3.connect("finance.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transaksi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tipe TEXT,
    kategori TEXT,
    amount INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS debt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT,
    amount INTEGER,
    status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# ================= AI KATEGORI =================
def get_category(text):
    if any(x in text for x in ["makan","nasi","ayam","mie"]):
        return "🍔 makanan"
    elif any(x in text for x in ["kopi","ngopi","cafe"]):
        return "☕ kopi"
    elif any(x in text for x in ["bensin","pertalite"]):
        return "⛽ transport"
    elif any(x in text for x in ["listrik","air","wifi"]):
        return "🏠 tagihan"
    elif any(x in text for x in ["belanja","shopee"]):
        return "🛍️ belanja"
    else:
        return "📦 lainnya"

# ================= PARSER =================
def parse_input(text):
    angka = re.findall(r'\d+', text)
    jumlah = int(angka[0]) if angka else 0

    if "jt" in text:
        jumlah *= 1_000_000
    elif "k" in text:
        jumlah *= 1000

    if any(x in text for x in ["gaji","bonus","masuk"]):
        tipe = "income"
    elif "hutang" in text:
        tipe = "hutang"
    elif "bayar" in text:
        tipe = "bayar"
    else:
        tipe = "expense"

    words = text.split()
    nama = words[1] if len(words) > 1 else None

    return tipe, jumlah, nama

# ================= AI CHAT =================
def ai_chat(text):
    text = text.lower()

    if "halo" in text or "hai" in text:
        return "👋 Halo! Aku siap bantu catat keuangan kamu!"
    elif "siapa kamu" in text:
        return "🤖 Aku bot keuangan pintar kamu 😎"
    elif "makasih" in text:
        return "🙏 Sama-sama!"
    elif "capek" in text:
        return "😅 Istirahat dulu, jangan lupa atur keuangan juga!"
    else:
        return "🤖 Aku belum paham, tapi tetap semangat ya!"

# ================= FITUR =================
async def saldo(update, context):
    user_id = update.message.from_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    data = cursor.fetchone()
    await update.message.reply_text(f"💰 Saldo: Rp{(data[0] if data else 0):,}")

async def hutang_list(update, context):
    user_id = update.message.from_user.id
    cursor.execute("SELECT name,SUM(amount) FROM debt WHERE user_id=? AND status='belum' GROUP BY name",(user_id,))
    data = cursor.fetchall()
    if not data:
        await update.message.reply_text("✅ Tidak ada hutang")
        return
    text = "📋 Hutang:\n"
    for n,j in data:
        text += f"\n- {n} Rp{j:,}"
    await update.message.reply_text(text)

async def laporan(update, context, text):
    user_id = update.message.from_user.id

    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND tipe='income'",(user_id,))
    income = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND tipe='expense'",(user_id,))
    expense = cursor.fetchone()[0] or 0

    await update.message.reply_text(
        f"📊 Laporan\n\n💰 {income:,}\n💸 {expense:,}\n📈 {income-expense:,}"
    )

async def kategori_report(update, context):
    user_id = update.message.from_user.id
    cursor.execute("SELECT kategori,SUM(amount) FROM transaksi WHERE user_id=? AND tipe='expense' GROUP BY kategori",(user_id,))
    data = cursor.fetchall()
    text="📊 Kategori:\n"
    for k,j in data:
        text+=f"\n{k} Rp{j:,}"
    await update.message.reply_text(text)

async def insight(update, context):
    user_id = update.message.from_user.id
    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND tipe='income'",(user_id,))
    income=cursor.fetchone()[0] or 0
    cursor.execute("SELECT SUM(amount) FROM transaksi WHERE user_id=? AND tipe='expense'",(user_id,))
    expense=cursor.fetchone()[0] or 0

    if income==0:
        await update.message.reply_text("⚠️ Belum ada income")
        return

    persen=int((expense/income)*100)
    status="😎 Aman" if persen<50 else "⚠️ Boros"
    await update.message.reply_text(f"{persen}% dipakai\n{status}")

async def hapus(update, context):
    user_id = update.message.from_user.id
    cursor.execute("SELECT id,tipe,amount FROM transaksi WHERE user_id=? ORDER BY id DESC LIMIT 1",(user_id,))
    d=cursor.fetchone()
    if not d:
        await update.message.reply_text("❌ kosong")
        return
    id_,t,a=d
    if t=="income":
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?",(a,user_id))
    else:
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(a,user_id))
    cursor.execute("DELETE FROM transaksi WHERE id=?",(id_,))
    conn.commit()
    await update.message.reply_text("✅ dihapus")

async def reset_all(update, context):
    user_id = update.message.from_user.id
    cursor.execute("DELETE FROM transaksi WHERE user_id=?",(user_id,))
    cursor.execute("DELETE FROM debt WHERE user_id=?",(user_id,))
    cursor.execute("UPDATE users SET balance=0 WHERE user_id=?",(user_id,))
    conn.commit()
    await update.message.reply_text("♻️ reset")

# ================= MAIN =================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.lower()

    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)",(user_id,))
    conn.commit()

    # COMMAND
    if text=="saldo": return await saldo(update,context)
    if text=="hutang": return await hutang_list(update,context)
    if text=="kategori": return await kategori_report(update,context)
    if text=="insight": return await insight(update,context)
    if text=="hapus": return await hapus(update,context)
    if text=="reset": return await reset_all(update,context)
    if text.startswith("laporan"): return await laporan(update,context,text)

    tipe,jumlah,nama=parse_input(text)
    kategori=get_category(text)

    # VALIDASI
    if tipe in ["income","expense"] and jumlah==0:
        return await update.message.reply_text("❌ Contoh: makan 20k")

    # HUTANG
    if tipe=="hutang":
        cursor.execute("INSERT INTO debt (user_id,name,amount,status) VALUES (?,?,?,?)",(user_id,nama,jumlah,"belum"))
        conn.commit()
        return await update.message.reply_text(f"🧾 Hutang {nama} Rp{jumlah:,}")

    # BAYAR
    if tipe=="bayar":
        cursor.execute("SELECT SUM(amount) FROM debt WHERE user_id=? AND name=?",(user_id,nama))
        total=cursor.fetchone()[0] or 0
        sisa=total-jumlah
        cursor.execute("DELETE FROM debt WHERE user_id=? AND name=?",(user_id,nama))
        if sisa>0:
            cursor.execute("INSERT INTO debt (user_id,name,amount,status) VALUES (?,?,?,?)",(user_id,nama,sisa,"belum"))
            msg=f"Sisa Rp{sisa:,}"
        else:
            msg="Lunas!"
        conn.commit()
        return await update.message.reply_text(msg)

    # INCOME
    if tipe=="income":
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?",(jumlah,user_id))
        cursor.execute("INSERT INTO transaksi (user_id,tipe,kategori,amount) VALUES (?,?,?,?)",(user_id,"income",kategori,jumlah))
        conn.commit()
        return await update.message.reply_text(f"💰 {kategori}\n+Rp{jumlah:,}")

    # EXPENSE
    if tipe=="expense":
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?",(jumlah,user_id))
        cursor.execute("INSERT INTO transaksi (user_id,tipe,kategori,amount) VALUES (?,?,?,?)",(user_id,"expense",kategori,jumlah))
        conn.commit()
        return await update.message.reply_text(f"💸 {kategori}\nRp{jumlah:,}")

    # AI CHAT fallback
    await update.message.reply_text(ai_chat(text))

# ================= RUN =================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("Bot GOD AI aktif 🚀")
app.run_polling()
