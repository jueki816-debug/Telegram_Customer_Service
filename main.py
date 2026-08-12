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

# AI Client နှင့် RAG Engine စတင်ခြင်း
ai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
rag = LightRAGEngine("knowledge.pdf")

# Telegram Client စတင်ခြင်း
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# State Management (Memory & Controls)
chat_history = {}  # format: {chat_id: "history_string"}
paused_chats = set()  # AI ရပ်ထားသော chat_id များ သိမ်းရန်

# စကားပြောမှတ်ဉာဏ်ကို စာလုံးရေ ၅၀၀၀ ထက်မကျော်စေရန် ထိန်းချုပ်သည့် Function
def update_memory(chat_id, new_text):
    current = chat_history.get(chat_id, "")
    current += f"\n{new_text}"
    
    if len(current) > 5000:
        current = current[-5000:]
        # စာကြောင်းတစ်ဝက်တွင် ပြတ်မသွားစေရန် ပထမဆုံး Newline နေရာမှ စဖြတ်သည်
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

    if text == ".pause":
        paused_chats.add(chat_id)
        await event.delete() # Customer မမြင်ရအောင် ချက်ချင်းဖျက်သည်
        print(f"[Override] AI Paused for Chat ID: {chat_id}")
        
    elif text == ".resume":
        paused_chats.discard(chat_id)
        await event.delete()
        print(f"[Override] AI Resumed for Chat ID: {chat_id}")

# -----------------------------------------------------------
# Handler 2: Customer များထံမှ လာသော စာများကို AI ဖြင့် ပြန်ခြင်း
# -----------------------------------------------------------
@client.on(events.NewMessage(incoming=True))
async def ai_reply_handler(event):
    # Group များတွင် အလုပ်မလုပ်စေရန် ကာကွယ်ခြင်း (Private သီးသန့်)
    if not event.is_private:
        return
    
    chat_id = event.chat_id
    user_message = event.raw_text

    # AI ကို .pause ဖြင့် ရပ်ထားလျှင် မည်သို့မျှ မတုံ့ပြန်ပါ
    if chat_id in paused_chats:
        return

    try:
        # 1. RAG ဖြင့် ကိုးကားချက်ရှာဖွေခြင်း
        context = rag.retrieve(user_message)
        
        # 2. History ရယူခြင်း
        history = chat_history.get(chat_id, "")
        
        # 3. System Prompt တည်ဆောက်ခြင်း
        system_prompt = f"""
        သင်သည် လူသားဆန်ပြီး ယဉ်ကျေးပျူငှာသော Customer Service AI ကိုယ်စားလှယ်ဖြစ်သည်။ အောက်ပါ အချက်အလက် (Context) ကို အခြေခံ၍ Customer ၏ မေးခွန်းများကို မြန်မာလို အကောင်းဆုံး ဖြေကြားပေးပါ။
        
        [ကိုးကားရန် အချက်အလက်များ]
        {context}
        
        စည်းကမ်းချက်များ:
        ၁။ အချက်အလက်ထဲတွင် မပါသော အရာများကို ကိုယ်တိုင် ဖန်တီးမဖြေပါနှင့်။
        ၂။ ယဉ်ကျေးပြီး ရင်းနှီးသော အသုံးအနှုန်းကို အသုံးပြုပါ။
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"ယခင်စကားပြောမှတ်တမ်းများ:\n{history}\n\nယခုမေးခွန်း: {user_message}"}
        ]

        # 4. OpenRouter AI (Gemma 4 31B) ကို ခေါ်ယူခြင်း
        response = await ai_client.chat.completions.create(
            model="google/gemma-4-31b-it", # သင်ရွေးချယ်ထားသော Model
            messages=messages,
            max_tokens=1000,
            temperature=0.3 # တိကျမှုရှိစေရန် 0.3 သာထားသည်
        )

        ai_reply = response.choices[0].message.content.strip()

        # 5. Customer ထံသို့ စာပြန်ခြင်း
        await event.reply(ai_reply)

        # 6. Memory ကို Update လုပ်ခြင်း (User မေးခွန်းနှင့် AI အဖြေကို သိမ်းသည်)
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
    
    # Web Server နှင့် Telegram Client ကို တစ်ပြိုင်နက်တည်း Run ခြင်း
    await asyncio.gather(
        start_web_server(),
        client.run_until_disconnected()
    )

if __name__ == "__main__":
    asyncio.run(main())