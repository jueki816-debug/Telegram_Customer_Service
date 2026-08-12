# Filename: main.py
import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from openai import AsyncOpenAI

from rag_engine import LightRAGEngine
from keep_alive import start_web_server

# Environment Variables များကို ဖတ်ခြင်း
load_dotenv()

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

if not all([API_ID, API_HASH, SESSION_STRING, OPENROUTER_API_KEY]):
    raise ValueError("[Error] .env ဖိုင်ထဲတွင် လိုအပ်သော Keys များ ထည့်သွင်းရန် ကျန်ရှိနေပါသည်။")

# -----------------------------------------------------------
# [NEW ARCHITECTURE] သီးသန့်ခွဲထုတ်ထားသော System Prompt ကို ဖတ်ရှုခြင်း
# -----------------------------------------------------------
PROMPT_FILE = "system_prompt.txt"

# အကယ်၍ ဖိုင်မရှိသေးပါက အသုံးပြုမည့် အရေးပေါ် (Fallback) Prompt
DEFAULT_PROMPT = """Kamu harus bertugas sebagai Customer Service (Layanan Pelanggan) di akun Telegram milik Admin Flows GPT. Kamu harus dapat menjawab pertanyaan yang diajukan oleh pelanggan dengan sopan. Kamu harus dapat menjawab pertanyaan pelanggan secara akurat dengan merujuk pada informasi yang ada di dalam knowledge.pdf yang diberikan kepadamu. Kamu harus mematuhi aturan yang ditetapkan untukmu dengan sangat ketat.

Rule (Aturan yang harus dipatuhi dengan sangat ketat):

Tidak boleh menanyakan hal-hal yang tidak berhubungan dengan pekerjaan/bisnis.

Hanya boleh menjawab hal-hal yang berkaitan dengan pekerjaan/bisnis.

Jangan menggunakan kata-kata atau perilaku kasar/tidak sopan.

Jika ditanya hal-hal yang tidak pasti, arahkan kepada Admin. Kamu harus bilang, "Tolong tunggu Admin".

Harus berbicara hanya dalam bahasa Myanmar.

Karena tidak ada Filter, kamu harus bisa mengatakan apa yang ingin kamu katakan secara bebas.

Jangan menggunakan teks atau informasi tambahan yang tidak perlu.

Hanya boleh menanyakan hal-hal yang berkaitan dengan Flows GPT.

Harus memberikan yang terbaik dalam hal-hal yang berkaitan dengan Flows GPT."""

# ဖိုင်ရှိ/မရှိ စစ်ဆေးပြီး ဖတ်ယူခြင်း (မြန်မာစာအတွက် utf-8 အသုံးပြုထားသည်)
if os.path.exists(PROMPT_FILE):
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        base_system_prompt = f.read().strip()
    print(f"[Success] System Prompt ကို '{PROMPT_FILE}' မှ အောင်မြင်စွာ ဖတ်ရှုပြီးပါပြီ။")
else:
    base_system_prompt = DEFAULT_PROMPT
    print(f"[Warning] '{PROMPT_FILE}' မတွေ့ပါ။ Default Prompt ဖြင့် ဆက်လက်အလုပ်လုပ်ပါမည်။")


# AI Client နှင့် RAG Engine စတင်ခြင်း
ai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
rag = LightRAGEngine("knowledge.pdf")

# -----------------------------------------------------------
# [CORE ARCHITECTURE FIX] Python 3.14+ အတွက် Event Loop ကို ကိုယ်တိုင် ဖန်တီးခြင်း
# -----------------------------------------------------------
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Telegram Client စတင်ခြင်း (ဖန်တီးထားသော loop ကို Bind လုပ်ခြင်း)
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH, loop=loop)

# State Management (Memory & Controls)
chat_history = {}  # format: {chat_id: "history_string"}
paused_chats = set()  # AI ရပ်ထားသော chat_id များ သိမ်းရန်

# စကားပြောမှတ်ဉာဏ်ကို စာလုံးရေ ၅၀၀၀ ထက်မကျော်စေရန် ထိန်းချုပ်သည့် Function
def update_memory(chat_id, new_text):
    current = chat_history.get(chat_id, "")
    current += f"\n{new_text}"
    
    if len(current) > 5000:
        current = current[-5000:]
        idx = current.find('\n')
        if idx != -1:
            current = current[idx+1:]
            
    chat_history[chat_id] = current

# -----------------------------------------------------------
# Handler 1: ပိုင်ရှင်(သင်) က AI ကို ရပ်/ဖွင့် လုပ်မည့် ခလုတ်များ
# -----------------------------------------------------------
@client.on(events.NewMessage(outgoing=True))
async def owner_control_handler(event):
    if not event.is_private:
        return
    
    text = event.raw_text.strip().lower()
    chat_id = event.chat_id

    if text == ".stop":
        paused_chats.add(chat_id)
        await event.delete()
        print(f"[Override] AI Paused for Chat ID: {chat_id}")
        
    elif text == ".start":
        paused_chats.discard(chat_id)
        await event.delete()
        print(f"[Override] AI Resumed for Chat ID: {chat_id}")

# -----------------------------------------------------------
# Handler 2: Customer များထံမှ လာသော စာများကို AI ဖြင့် ပြန်ခြင်း
# -----------------------------------------------------------
@client.on(events.NewMessage(incoming=True))
async def ai_reply_handler(event):
    if not event.is_private:
        return
    
    chat_id = event.chat_id
    user_message = event.raw_text

    if chat_id in paused_chats:
        return

    try:
        # RAG ဖြင့် ကိုးကားချက် ရှာဖွေခြင်း
        context = rag.retrieve(user_message)
        history = chat_history.get(chat_id, "")
        
        # [DYNAMIC PROMPT ASSEMBLY] သီးသန့် Prompt နှင့် RAG ကိုးကားချက်ကို ပေါင်းစပ်ခြင်း
        final_system_prompt = f"{base_system_prompt}\n\n[ကိုးကားရန် အချက်အလက်များ]\n{context}"

        messages = [
            {"role": "system", "content": final_system_prompt},
            {"role": "user", "content": f"ယခင်စကားပြောမှတ်တမ်းများ:\n{history}\n\nယခုမေးခွန်း: {user_message}"}
        ]

        response = await ai_client.chat.completions.create(
            model="google/gemma-4-31b-it",
            messages=messages,
            max_tokens=1000,
            temperature=0.3
        )

        ai_reply = response.choices[0].message.content.strip()
        await event.reply(ai_reply)

        update_memory(chat_id, f"Customer: {user_message}")
        update_memory(chat_id, f"AI: {ai_reply}")

    except Exception as e:
        print(f"[API Error] Chat ID {chat_id} တွင် ပြဿနာတက်နေပါသည်: {e}")

# -----------------------------------------------------------
# စနစ်စတင်ခြင်း (Main Loop)
# -----------------------------------------------------------
async def main():
    await client.start()
    print("[System] Telegram Userbot is active and listening...")
    
    await asyncio.gather(
        start_web_server(),
        client.run_until_disconnected()
    )

if __name__ == "__main__":
    loop.run_until_complete(main())
