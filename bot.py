import os
import re
import asyncio
import threading

# -------- Keep-alive web server for Render free Web Service --------
from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Discord TTS bot is running!"

def run_web():
    # Render injects a dynamic port via the PORT env var
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)

# Start Flask in a background thread (daemon so it won't block shutdown)
threading.Thread(target=run_web, daemon=True).start()

# ------------------ Discord / TTS imports ------------------
import discord
from discord.ext import commands
from discord import app_commands
from gtts import gTTS
from langdetect import detect, LangDetectException
from imageio_ffmpeg import get_ffmpeg_exe
import google.generativeai as genai

# --------------- External services config -----------------
FFMPEG_PATH = get_ffmpeg_exe()  # portable ffmpeg binary
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# --------------------- Helpers ----------------------------
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

def split_sentences(text: str):
    """Simple chat-friendly sentence splitter."""
    parts = re.split(r'([.!?।]+)\s*', text)
    chunks = []
    for i in range(0, len(parts), 2):
        sent = (parts[i] or "").strip()
        punc = parts[i+1] if i+1 < len(parts) else ""
        if sent:
            chunks.append((sent + punc).strip())
    return chunks if chunks else [text]

def clean_content(message: discord.Message) -> str:
    """Make mentions/links readable and trim very long messages."""
    txt = message.content

    # Mentions to readable names
    for user in message.mentions:
        txt = txt.replace(f"<@{user.id}>", user.display_name).replace(f"<@!{user.id}>", user.display_name)
    for role in message.role_mentions:
        txt = txt.replace(f"<@&{role.id}>", role.name)
    for ch in message.channel_mentions:
        txt = txt.replace(f"<#{ch.id}>", ch.name)

    # So TTS doesn't shout @everyone/@here
    txt = txt.replace("@everyone", "everyone").replace("@here", "here")

    # Shorten links; mark attachments
    txt = re.sub(r"https?://\S+", "[link]", txt)
    if message.attachments:
        txt += " [attachment]"

    txt = txt.strip()
    if len(txt) > 400:
        txt = txt[:400] + "…"
    return txt

def looks_hinglish(text: str) -> bool:
    """Heuristic: no Devanagari but has common Roman-Hindi markers."""
    if DEVANAGARI_RE.search(text):
        return False
    markers = {
        "hai","nahi","nahin","kya","kyu","kyun","haan","acha","accha","theek","bhai",
        "tum","mai","main","mera","meri","tere","tera","teri","hum","ham","bahut","bohot",
        "kaise","kahan","bilkul","sahi","galat","aaj","kal","abhi","chalo","ruk","ruko"
    }
    tokens = re.findall(r"[A-Za-z]+", text.lower())
    return any(t in markers for t in tokens)

def gemini_normalize(text: str) -> str:
    """
    Use Gemini Free API to rewrite Hinglish → natural Hindi-English mix.
    - Convert Roman Hindi to Devanagari
    - Keep English words, usernames, hashtags, emojis as-is
    - Preserve tone & meaning
    """
    try:
        prompt = (
            "Rewrite this chat text as a natural Hindi–English mix for Text-to-Speech. "
            "If words are Roman Hindi, convert them to Devanagari Hindi. "
            "Do NOT translate English words, usernames, hashtags, or emojis. "
            "Preserve tone and meaning. Return only the rewritten text.\n\n"
            f"Text:\n{text}"
        )
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(prompt)
        out = (resp.text or "").strip()
        return out if out else text
    except Exception as e:
        print("Gemini normalize error:", e)
        return text

def route_lang_for_chunk(text: str) -> str:
    """After normalization, choose TTS voice: Hindi if Devanagari appears; else English."""
    return "hi" if DEVANAGARI_RE.search(text) else "en"

# --------------------- Discord Setup ----------------------
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.message_content = True  # enable in Dev Portal too!

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Runtime state
listening_channel_id: int | None = None
tts_queue: asyncio.Queue = asyncio.Queue()
tts_worker_task: asyncio.Task | None = None

async def ensure_voice_client() -> discord.VoiceClient | None:
    return bot.voice_clients[0] if bot.voice_clients else None

async def tts_worker():
    """Single consumer: generates & plays audio sequentially."""
    while True:
        vc, say_text, lang = await tts_queue.get()
        filename = f"speech_{asyncio.get_event_loop().time():.0f}.mp3"
        try:
            gTTS(text=say_text, lang=lang, slow=False).save(filename)

            # If already playing, wait
            while vc.is_playing() or vc.is_paused():
                await asyncio.sleep(0.1)

            src = discord.FFmpegPCMAudio(executable=FFMPEG_PATH, source=filename)
            vc.play(src)

            while vc.is_playing():
                await asyncio.sleep(0.1)
        except Exception as e:
            print("TTS worker error:", e)
        finally:
            try:
                if os.path.exists(filename):
                    os.remove(filename)
            except:
                pass
            tts_queue.task_done()

# --------------------- Events & Commands ------------------
@bot.event
async def on_ready():
    global tts_worker_task
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    try:
        synced = await tree.sync()
        print(f"🔧 Synced {len(synced)} command(s)")
    except Exception as e:
        print("Slash sync error:", e)
    if not tts_worker_task or tts_worker_task.done():
        tts_worker_task = asyncio.create_task(tts_worker())
    print("🎙️ TTS bot ready (Gemini-enabled).")

@bot.event
async def on_message(message: discord.Message):
    global listening_channel_id
    if message.author == bot.user:
        return
    if listening_channel_id is None or message.channel.id != listening_channel_id:
        return

    vc = await ensure_voice_client()
    if not vc:
        listening_channel_id = None
        return

    raw = clean_content(message)
    if not raw:
        return

    # Normalize with Gemini if likely Hinglish or no Devanagari
    text = gemini_normalize(raw) if (looks_hinglish(raw) or not DEVANAGARI_RE.search(raw)) else raw

    # Split into sentences and enqueue with per-chunk lang routing
    chunks = split_sentences(text)
    prefix = f"{message.author.display_name} said: "
    first = True
    for ch in chunks:
        lang = route_lang_for_chunk(ch)
        say = (prefix + ch) if first else ch
        first = False
        await tts_queue.put((vc, say, lang))

@tree.command(name="join", description="Join your voice channel and read messages from this text channel.")
async def join(interaction: discord.Interaction):
    global listening_channel_id
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❌ You are not in a voice channel.", ephemeral=True)
        return

    target_vc = interaction.user.voice.channel
    vc = await ensure_voice_client()
    try:
        if vc and vc.channel != target_vc:
            await vc.move_to(target_vc)
        elif not vc:
            await target_vc.connect()
    except discord.ClientException as e:
        await interaction.response.send_message(f"⚠️ Couldn’t connect: {e}", ephemeral=True)
        return

    listening_channel_id = interaction.channel.id
    await interaction.response.send_message(
        f"✅ Joined **{target_vc.name}** and will read from **#{interaction.channel.name}**."
    )

@tree.command(name="leave", description="Leave the voice channel and stop reading.")
async def leave(interaction: discord.Interaction):
    global listening_channel_id
    vc = await ensure_voice_client()
    if vc:
        await vc.disconnect(force=True)
        listening_channel_id = None
        await interaction.response.send_message("👋 Left the voice channel and stopped reading.")
    else:
        await interaction.response.send_message("ℹ️ I am not in a voice channel.", ephemeral=True)

# ----------------------- Main ----------------------------
if __name__ == "__main__":
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN")
    if not os.environ.get("GEMINI_API_KEY"):
        print("⚠️ Warning: GEMINI_API_KEY not set. Hinglish normalization will be degraded.")
    bot.run(token)
