#!/usr/bin/env python3
“””
RESUMO DIÁRIO — Cripto, IA e Economia
Pipeline completo num único arquivo.
Roda todo dia às 08:00 BRT via cron.

Uso:
python3 resumo_diario.py
“””
import os
import re
import sys
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
import feedparser
from dotenv import load_dotenv
import anthropic

# ============================================================

# CONFIG

# ============================================================

load_dotenv()

BASE_DIR = Path(**file**).parent
OUTPUT_DIR = BASE_DIR / “output”
LOG_DIR = BASE_DIR / “logs”
OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

TELEGRAM_BOT_TOKEN = os.getenv(“TELEGRAM_BOT_TOKEN”, “”)
TELEGRAM_CHAT_ID = os.getenv(“TELEGRAM_CHAT_ID”, “”)
ANTHROPIC_API_KEY = os.getenv(“ANTHROPIC_API_KEY”, “”)
NEWSAPI_KEY = os.getenv(“NEWSAPI_KEY”, “”)
ELEVENLABS_API_KEY = os.getenv(“ELEVENLABS_API_KEY”, “”)
ELEVENLABS_VOICE_ID = os.getenv(“ELEVENLABS_VOICE_ID”, “XB0fDUnXU5powFXDhCwa”)

logging.basicConfig(
level=logging.INFO,
format=”%(asctime)s [%(levelname)s] %(message)s”,
handlers=[
logging.FileHandler(LOG_DIR / f”run_{datetime.now():%Y%m%d}.log”, encoding=“utf-8”),
logging.StreamHandler(sys.stdout),
],
)
log = logging.getLogger(**name**)

TOPICS = [“criptomoedas”, “inteligência artificial”, “economia brasil”]

RSS_FEEDS = {
“criptomoedas”: [
“https://livecoins.com.br/feed/”,
“https://www.portaldobitcoin.uol.com.br/feed/”,
],
“inteligência artificial”: [
“https://olhardigital.com.br/feed/”,
“https://tecnoblog.net/feed/”,
],
“economia brasil”: [
“https://valor.globo.com/rss/”,
“https://www.infomoney.com.br/feed/”,
],
}

# ============================================================

# 1. NOTÍCIAS

# ============================================================

def fetch_newsapi(query, hours, max_results):
if not NEWSAPI_KEY:
return []
from_date = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
try:
r = requests.get(
“https://newsapi.org/v2/everything”,
params={
“q”: query, “from”: from_date, “language”: “pt”,
“sortBy”: “popularity”, “pageSize”: max_results,
“apiKey”: NEWSAPI_KEY,
},
timeout=15,
)
r.raise_for_status()
return [
{“title”: a[“title”], “description”: a.get(“description”, “”) or “”,
“source”: a[“source”][“name”], “url”: a[“url”], “topic”: query}
for a in r.json().get(“articles”, [])
]
except Exception as e:
log.warning(f”NewsAPI falhou para ‘{query}’: {e}”)
return []

def fetch_rss(topic, max_results):
results = []
for feed_url in RSS_FEEDS.get(topic, []):
try:
feed = feedparser.parse(feed_url)
for entry in feed.entries[:max_results]:
results.append({
“title”: entry.get(“title”, “”),
“description”: entry.get(“summary”, “”)[:300],
“source”: feed.feed.get(“title”, feed_url),
“url”: entry.get(“link”, “”), “topic”: topic,
})
except Exception as e:
log.warning(f”RSS {feed_url} falhou: {e}”)
return results[:max_results]

def dedupe(items):
seen_urls, seen_titles, unique = set(), [], []
for it in items:
url = it.get(“url”, “”)
title = it.get(“title”, “”).lower().strip()
if url in seen_urls:
continue
title_key = title[:40]
if any(title_key == t[:40] for t in seen_titles):
continue
seen_urls.add(url); seen_titles.append(title); unique.append(it)
return unique

def fetch_news():
all_items = []
for topic in TOPICS:
items = fetch_newsapi(topic, 24, 5)
if not items:
log.info(f”RSS fallback para ‘{topic}’”)
items = fetch_rss(topic, 5)
all_items.extend(items)
return dedupe(all_items)

# ============================================================

# 2. RESUMO (LLM)

# ============================================================

SYSTEM_PROMPT = “”“Você é o editor-chefe de um canal premium brasileiro sobre Cripto, IA e Economia.
Seu público paga por CLAREZA e INSIGHTS ACIONÁVEIS - não quer papo furado.

REGRAS:

- Português brasileiro natural, direto, profissional
- Use APENAS as notícias fornecidas (não invente fatos ou números)
- Cada bullet: fato concreto + número/dado + por quê importa
- Tom: analista confiante, não influencer eufórico
- Emojis com moderação (1 por seção)
- Tamanho total: 250-400 palavras”””

USER_TEMPLATE = “”“Monte o resumo do dia {date} usando EXATAMENTE este formato:

🔥 RESUMO DIÁRIO — {date}

💰 CRIPTO
• [bullet 1: fato + número + por quê importa]
• [bullet 2]

🤖 INTELIGÊNCIA ARTIFICIAL
• [bullet 1]
• [bullet 2]

📊 ECONOMIA
• [bullet 1]
• [bullet 2]

🎯 MOVIMENTO DO DIA
[1-2 frases com o insight mais acionável de hoje]

-----

NOTÍCIAS DE HOJE:
{news_block}
“””

def generate_summary(news_items, date_str):
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
news_block = “\n”.join(
f”{i}. [{it[‘topic’].upper()}] {it[‘title’]}\n   Fonte: {it[‘source’]}\n   Resumo: {it[‘description’]}\n”
for i, it in enumerate(news_items, 1)
)
prompt = USER_TEMPLATE.format(date=date_str, news_block=news_block)
response = client.messages.create(
model=“claude-haiku-4-5-20251001”,
max_tokens=1200,
system=SYSTEM_PROMPT,
messages=[{“role”: “user”, “content”: prompt}],
)
return response.content[0].text.strip()

# ============================================================

# 3. IMAGENS (Pollinations - grátis)

# ============================================================

IMG_PROMPTS = [
“modern financial dashboard with cryptocurrency charts and AI neural network, dark theme, professional, cinematic, 4k”,
“futuristic brazilian economy concept with digital money flow and AI, sao paulo skyline, editorial illustration”,
]

def generate_images():
paths = []
for i, prompt in enumerate(IMG_PROMPTS, 1):
url = f”https://image.pollinations.ai/prompt/{quote(prompt)}?width=1024&height=1024&nologo=true”
try:
r = requests.get(url, timeout=60)
r.raise_for_status()
img_path = OUTPUT_DIR / f”imagem_{i}.jpg”
img_path.write_bytes(r.content)
paths.append(img_path)
log.info(f”Imagem {i} OK”)
except Exception as e:
log.warning(f”Imagem {i} falhou: {e}”)
return paths

# ============================================================

# 4. TTS (ElevenLabs → gTTS fallback)

# ============================================================

def clean_for_tts(text):
text = re.sub(
“[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF”
“\U0001F1E0-\U0001F1FF\U00002600-\U000027BF\U0001F900-\U0001F9FF]+”,
“”, text, flags=re.UNICODE,
)
text = text.replace(”•”, “”).replace(”—”, “”).replace(”—”, “-”)
return re.sub(r”\s+”, “ “, text).strip()

def tts_elevenlabs(text, output_path):
if not ELEVENLABS_API_KEY:
return False
try:
r = requests.post(
f”https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}”,
headers={“xi-api-key”: ELEVENLABS_API_KEY, “Content-Type”: “application/json”},
json={“text”: text, “model_id”: “eleven_multilingual_v2”,
“voice_settings”: {“stability”: 0.5, “similarity_boost”: 0.75}},
timeout=120,
)
r.raise_for_status()
output_path.write_bytes(r.content)
log.info(“TTS via ElevenLabs”)
return True
except Exception as e:
log.warning(f”ElevenLabs falhou: {e}”)
return False

def tts_gtts(text, output_path):
try:
from gtts import gTTS
gTTS(text=text, lang=“pt”, tld=“com.br”, slow=False).save(str(output_path))
log.info(“TTS via gTTS (fallback)”)
return True
except Exception as e:
log.error(f”gTTS falhou: {e}”)
return False

def generate_audio(summary_text):
clean = clean_for_tts(summary_text)
output_path = OUTPUT_DIR / “resumo_audio.mp3”
if tts_elevenlabs(clean, output_path):
return output_path
if tts_gtts(clean, output_path):
return output_path
raise RuntimeError(“Nenhum TTS funcionou”)

# ============================================================

# 5. TELEGRAM

# ============================================================

TG_API = f”https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}”

def tg_retry(method, url, max_attempts=3, **kwargs):
for attempt in range(1, max_attempts + 1):
try:
r = requests.request(method, url, timeout=60, **kwargs)
r.raise_for_status()
return r.json()
except Exception as e:
wait = 2 ** attempt
log.warning(f”Telegram tentativa {attempt}: {e}. Aguardando {wait}s”)
if attempt == max_attempts:
raise
time.sleep(wait)

def tg_send_message(text):
if len(text) > 4096:
text = text[:4070] + “\n\n[…continua]”
tg_retry(“POST”, f”{TG_API}/sendMessage”,
data={“chat_id”: TELEGRAM_CHAT_ID, “text”: text, “parse_mode”: “HTML”})
log.info(“Texto enviado”)

def tg_send_photo(image_path):
with open(image_path, “rb”) as f:
tg_retry(“POST”, f”{TG_API}/sendPhoto”,
data={“chat_id”: TELEGRAM_CHAT_ID},
files={“photo”: f})
log.info(f”Foto enviada: {image_path.name}”)

def tg_send_audio(audio_path, caption=””):
with open(audio_path, “rb”) as f:
tg_retry(“POST”, f”{TG_API}/sendAudio”,
data={“chat_id”: TELEGRAM_CHAT_ID, “caption”: caption[:1024],
“title”: “Resumo Diário”, “performer”: “Canal Premium”},
files={“audio”: f})
log.info(f”Áudio enviado: {audio_path.name}”)

def send_to_telegram(text, image_paths, audio_path):
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
raise RuntimeError(“TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID ausentes”)
tg_send_message(text)
for img in image_paths:
tg_send_photo(img)
time.sleep(1)
tg_send_audio(audio_path, caption=“🎧 Ouça o resumo completo”)

# ============================================================

# MAIN

# ============================================================

def main():
today = datetime.now().strftime(”%d/%m/%Y”)
log.info(f”🚀 Iniciando pipeline — {today}”)

```
try:
    log.info("📰 Buscando notícias...")
    news = fetch_news()
    if not news:
        log.error("Sem notícias. Abortando.")
        return
    log.info(f"✅ {len(news)} notícias")

    log.info("🧠 Gerando resumo...")
    summary = generate_summary(news, today)
    (OUTPUT_DIR / f"resumo_{datetime.now():%Y%m%d}.txt").write_text(summary, encoding="utf-8")
    log.info("✅ Resumo OK")

    log.info("🎨 Gerando imagens...")
    images = generate_images()
    log.info(f"✅ {len(images)} imagens")

    log.info("🎧 Gerando áudio...")
    audio = generate_audio(summary)
    log.info("✅ Áudio OK")

    log.info("📤 Enviando ao Telegram...")
    send_to_telegram(summary, images, audio)
    log.info("🎉 Pipeline concluído!")

except Exception as e:
    log.exception(f"❌ Erro fatal: {e}")
    sys.exit(1)
```

if **name** == “**main**”:
main()
