import asyncio
import os
import random
import re
import shutil
import tempfile
import time
import unicodedata
from collections import deque
from pathlib import Path
from threading import Thread

import aiohttp
import discord
import imageio_ffmpeg
import yt_dlp
from discord.ext import commands
from flask import Flask

# ───────────────────────── Servidor web (para Render) ─────────────────────────
app = Flask('')


@app.route('/')
@app.route('/health')
def home():
    return "Bot Online"


def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()


# ───────────────────────────── Configuración ──────────────────────────────────
PREFIX = '.'
FFMPEG = shutil.which('ffmpeg') or imageio_ffmpeg.get_ffmpeg_exe()
DOWNLOAD_DIR = 'downloads'

MAX_DURATION = int(os.environ.get('MAX_DURATION', 600))   # segundos (10 min por defecto)
AUDIO_KBPS = 64
SAFETY = 0.93                                             # margen para no pasarse del límite

MENCIONES_NECESARIAS = 5
RESET_SECONDS = 1800          # 30 min sin menciones de la categoría = contador a 0
REACTION_THRESHOLD = 3        # reacciones para que el bot comente
REACTION_COOLDOWN = 1800      # 30 min entre comentarios de reacciones por canal

# IA (opcional). Prioridad: OpenRouter > Gemini > frases fijas.
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
OPENROUTER_MODEL = os.environ.get('OPENROUTER_MODEL', 'meta-llama/llama-3.3-70b-instruct:free')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash')
HISTORY_SIZE = 8  # últimos mensajes del canal que la IA "recuerda"

PERSONALIDAD_DEFAULT = "Eres Yumi, una bot de Discord curiosa, juguetona y burlona."


def cargar_personalidad() -> str:
    try:
        with open('personalidad.txt', encoding='utf-8') as f:
            return f.read().strip() or PERSONALIDAD_DEFAULT
    except FileNotFoundError:
        return PERSONALIDAD_DEFAULT


PERSONALIDAD = cargar_personalidad()

TRIGGER_WORDS = {
    "adulto": ["porno", "sexo", "hentai", "nudes", "pack", "nsfw", "rule34", "paja", "pajas", "pajero"],
    "raro": ["furros", "femboys", "pene", "vagina"],
    "follar": ["follar", "follarte", "follare", "follan", "follaron", "follaste", "follando"],
    "coger": ["coger", "coges", "cogen", "cogieron", "cogiendo", "cojas"],
    "drogas": ["drogas", "marihuana", "perico", "tusi", "poro", "weed"],
}
# Categorías que solo cuentan si el mensaje trae foto/video/link
SOLO_CON_MEDIA = {"adulto", "follar"}

FALLBACKS = {
    "media": ["otra foto raruna o… ¿por fin dejaron de mandar porno, chicos?... 😅😅😅",
              "chicos… ¿otra vez con eso?... 😅😅😅"],
    "texto": ["emmm… ¿okey? ¿de qué están hablando?... 🤨🤨🤨",
              "hmmm… ¿y esa conversación tan interesante?... 🤨🤨🤨"],
    "reaccion": ["¿qué tendrá ese link o archivo para tantas reacciones?... 😅😅😅",
                 "uy… ¿qué hay ahí que todos reaccionan?... 👀"],
}


# ───────────────────────────── Utilidades ─────────────────────────────────────
def normalizar(texto: str) -> str:
    texto = unicodedata.normalize('NFD', texto.lower())
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn')


URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)

# Palabra completa: "coger" NO se activa con "escoger" ni "pene" con "Penélope"
PATTERNS = {
    cat: re.compile(r'\b(?:' + '|'.join(re.escape(normalizar(p)) for p in words) + r')\b')
    for cat, words in TRIGGER_WORDS.items()
}


def detectar_categoria(contenido: str):
    limpio = normalizar(URL_RE.sub(' ', contenido))  # ignora palabras dentro de URLs
    for cat, patron in PATTERNS.items():
        if patron.search(limpio):
            return cat
    return None


_session = None
history = {}  # {channel_id: deque([(autor, texto), ...])}
IA_ACTIVA = bool(OPENROUTER_API_KEY or GEMINI_API_KEY)


async def get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    return _session


def recordar(channel_id: int, autor: str, texto: str):
    texto = URL_RE.sub('[link]', texto).strip()
    if texto:
        history.setdefault(channel_id, deque(maxlen=HISTORY_SIZE)).append((autor, texto[:300]))


def contexto(channel_id) -> str:
    h = history.get(channel_id)
    if not h:
        return ""
    return "Últimos mensajes del chat:\n" + "\n".join(f"{a}: {t}" for a, t in h) + "\n\n"


async def _openrouter(prompt: str) -> str:
    session = await get_session()
    body = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "system", "content": PERSONALIDAD},
                     {"role": "user", "content": prompt}],
        "max_tokens": 200,
        "temperature": 1.0,
    }
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
    async with session.post("https://openrouter.ai/api/v1/chat/completions",
                            json=body, headers=headers) as r:
        if r.status != 200:
            raise RuntimeError(f"openrouter {r.status}")
        data = await r.json()
    return data["choices"][0]["message"]["content"].strip()


async def _gemini(prompt: str) -> str:
    session = await get_session()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": PERSONALIDAD}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 200, "temperature": 1.0},
    }
    async with session.post(url, json=body, headers={"x-goog-api-key": GEMINI_API_KEY}) as r:
        if r.status != 200:
            raise RuntimeError(f"gemini {r.status}")
        data = await r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


async def respuesta_ia(situacion: str, fallback_key: str, channel_id=None) -> str:
    """Genera la respuesta con la IA; si falla o no hay clave, usa una frase fija."""
    fallback = random.choice(FALLBACKS[fallback_key])
    if not IA_ACTIVA:
        return fallback
    prompt = (contexto(channel_id) if channel_id else "") + situacion
    for motor, activo in ((_openrouter, OPENROUTER_API_KEY), (_gemini, GEMINI_API_KEY)):
        if not activo:
            continue
        try:
            texto = await motor(prompt)
            if texto:
                return texto[:600]
        except Exception as e:
            print(f"IA falló ({motor.__name__}): {e}")
    return fallback


# ───────────────────────────── Bot ────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

keyword_data = {}        # {categoria: {'count': int, 'last_time': float}}
historial = {}           # {channel_id: deque con los últimos mensajes}
reaction_counts = {}     # {message_id: {'n': int, 't': float, 'done': bool}}
last_reaction_spoke = {}  # {channel_id: float}
last_chat = {}           # {user_id: float}  (anti-spam de la charla con IA)
descargas = asyncio.Semaphore(1)  # una descarga a la vez (Render gratis tiene poca RAM)


@bot.event
async def on_ready():
    print(f'¡Bot conectado con éxito como {bot.user}! IA: {"OpenRouter" if OPENROUTER_API_KEY else "Gemini" if GEMINI_API_KEY else "no (frases fijas)"}')


async def me_hablan(message: discord.Message) -> bool:
    if bot.user in message.mentions:
        return True
    ref = message.reference
    if ref and ref.message_id:
        resuelto = ref.resolved
        if isinstance(resuelto, discord.Message):
            return resuelto.author == bot.user
    return False


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:  # ignora a otros bots y a sí mismo (evita loops)
        return

    now = time.time()

    # Memoria corta del canal para que Yumi entienda de qué se habla
    if message.content and not message.content.startswith(PREFIX):
        historial.setdefault(message.channel.id, deque(maxlen=8)).append(
            f"{message.author.display_name}: {message.content[:200]}")

    # 1. Palabras clave con contador por categoría
    cat = detectar_categoria(message.content)
    if cat:
        tiene_media = bool(message.attachments or message.embeds or URL_RE.search(message.content))
        if cat not in SOLO_CON_MEDIA or tiene_media:
            data = keyword_data.setdefault(cat, {'count': 0, 'last_time': 0})

            if now - data['last_time'] > RESET_SECONDS:  # la charla murió: empezar de cero
                data['count'] = 0
            data['count'] += 1
            data['last_time'] = now

            if data['count'] >= MENCIONES_NECESARIAS:
                data['count'] = 0
                clave = "media" if cat in SOLO_CON_MEDIA else "texto"
                situacion = (f"En el chat llevan {MENCIONES_NECESARIAS} mensajes seguidos hablando de "
                             f"'{cat}'. Comenta algo corto y gracioso sobre eso.")
                await message.reply(await respuesta_ia(situacion, clave, message.channel.id), mention_author=False)

    # 2. Charla con IA si mencionan al bot o le responden a un mensaje suyo
    elif IA_ACTIVA and not message.content.startswith(PREFIX) and await me_hablan(message):
        if now - last_chat.get(message.author.id, 0) > 8:
            last_chat[message.author.id] = now
            texto = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
            situacion = f"[{message.author.display_name} te habla directamente]: {texto or '(te mencionó sin decir nada)'}"
            async with message.channel.typing():
                resp = await respuesta_ia(situacion, "texto", message.channel.id)
            await message.reply(resp, mention_author=False)
            recordar(message.channel.id, "Yumi", resp)

    await bot.process_commands(message)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Salta cada vez que alguien reacciona (on_message nunca ve las reacciones)."""
    if payload.user_id == bot.user.id:
        return

    now = time.time()
    entry = reaction_counts.get(payload.message_id)
    if not entry or now - entry['t'] > 3600:
        entry = {'n': 0, 't': now, 'done': False}
    entry['n'] += 1
    entry['t'] = now
    reaction_counts[payload.message_id] = entry

    if len(reaction_counts) > 500:  # limpieza de memoria
        for mid in [m for m, e in reaction_counts.items() if now - e['t'] > 3600]:
            del reaction_counts[mid]

    if entry['done'] or entry['n'] < REACTION_THRESHOLD:
        return
    if now - last_reaction_spoke.get(payload.channel_id, 0) < REACTION_COOLDOWN:
        return

    try:
        channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
        msg = await channel.fetch_message(payload.message_id)
    except discord.HTTPException:
        return

    if msg.author.bot:
        return
    if not (msg.attachments or msg.embeds or URL_RE.search(msg.content)):
        return

    entry['done'] = True
    last_reaction_spoke[payload.channel_id] = now
    await msg.reply(await respuesta_ia(
        "A un mensaje con un link o archivo le pusieron muchas reacciones. "
        "Pregunta con curiosidad qué tendrá de especial.", "reaccion", payload.channel_id), mention_author=False)


# ───────────────────────────── Descargas ──────────────────────────────────────
def limpiar_error(e: Exception) -> str:
    texto = re.sub(r'\x1b\[[0-9;]*m', '', str(e))  # quita colores ANSI
    return texto.strip()[:300]


def _opciones_ydl(workdir: str) -> dict:
    opts = {
        # Hasta 720p, prefiere H.264/AAC para no tener que recomprimir
        'format': 'bv*[height<=720]+ba/b[height<=720]/b',
        'format_sort': ['res:720', 'vcodec:h264', 'acodec:aac'],
        'merge_output_format': 'mp4',
        'outtmpl': os.path.join(workdir, '%(id).50s.%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 20,
        'retries': 3,
        'restrictfilenames': True,
        'max_filesize': 400 * 1024 * 1024,  # protege el disco de Render
        'ffmpeg_location': FFMPEG,
    }
    cookies = os.environ.get('COOKIES_FILE')
    if cookies and os.path.exists(cookies):
        opts['cookiefile'] = cookies
    return opts


def _probar(url: str, workdir: str):
    with yt_dlp.YoutubeDL({**_opciones_ydl(workdir), 'skip_download': True}) as ydl:
        info = ydl.extract_info(url, download=False)
        if 'entries' in info:
            info = next(iter(info['entries']))
        return info.get('duration')


def _descargar(url: str, workdir: str) -> str:
    with yt_dlp.YoutubeDL(_opciones_ydl(workdir)) as ydl:
        info = ydl.extract_info(url, download=True)
        if 'entries' in info:
            info = next(iter(info['entries']))
        rd = info.get('requested_downloads') or []
        path = rd[0].get('filepath') if rd else None
        return path or ydl.prepare_filename(info)


async def duracion_ffmpeg(path: str):
    proc = await asyncio.create_subprocess_exec(
        FFMPEG, '-i', path, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.?\d*)', err.decode(errors='ignore'))
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


class DemasiadoLargo(Exception):
    pass


async def comprimir(src: str, dst: str, duracion: float, limite: int) -> None:
    """Recomprime con ffmpeg al bitrate justo para que quepa en `limite` bytes."""
    video_k = int(limite * SAFETY * 8 / duracion / 1000) - AUDIO_KBPS

    for _ in range(3):
        if video_k < 120:
            raise DemasiadoLargo()
        alto = 720 if video_k >= 1400 else 480 if video_k >= 700 else 360 if video_k >= 250 else 240
        cmd = [
            FFMPEG, '-y', '-i', src,
            '-vf', f'scale=-2:min(ih\\,{alto})',
            '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
            '-b:v', f'{video_k}k', '-maxrate', f'{int(video_k * 1.3)}k', '-bufsize', f'{video_k * 2}k',
            '-c:a', 'aac', '-b:a', f'{AUDIO_KBPS}k', '-ac', '2',
            '-movflags', '+faststart', '-threads', '2', dst,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await asyncio.wait_for(proc.wait(), timeout=900)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("la compresión tardó demasiado")
        if proc.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError("ffmpeg falló al comprimir")

        tam = os.path.getsize(dst)
        if tam <= limite * 0.98:
            return
        video_k = int(video_k * (limite * SAFETY) / tam)  # quedó grande: reintentar más bajo
    raise DemasiadoLargo()


def limite_subida(ctx: commands.Context) -> int:
    env = os.environ.get('MAX_UPLOAD_MB')
    if env:
        return int(float(env) * 1024 * 1024)
    if ctx.guild:
        return ctx.guild.filesize_limit
    return 10 * 1024 * 1024


@bot.command(name='bl')
async def descargar_video(ctx: commands.Context, url: str = None):
    """Comando .bl <enlace> para descargar el video y subirlo al chat."""
    if not url:
        await ctx.reply("pásame un link, cariño: `.bl <enlace>` 🙃")
        return
    url = url.strip('<>')

    aviso = await ctx.reply("⏳ ya estoy descargando el video... no te preocupes...❤️❤️❤️")
    limite = limite_subida(ctx)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    workdir = tempfile.mkdtemp(dir=DOWNLOAD_DIR)

    try:
        async with descargas:
            duracion = await asyncio.to_thread(_probar, url, workdir)
            if duracion and duracion > MAX_DURATION:
                await ctx.reply(f"❌ ese video dura {int(duracion // 60)} min y mi límite es "
                                f"{MAX_DURATION // 60} min. lo siento...")
                return

            path = await asyncio.to_thread(_descargar, url, workdir)
            if not path or not os.path.exists(path):
                await ctx.reply("❌ No pude procesar el enlace... no se porque!!!.")
                return

            final = path
            if os.path.getsize(path) > limite * 0.98:
                duracion = duracion or await duracion_ffmpeg(path)
                if not duracion:
                    await ctx.reply("❌ no pude saber cuánto dura el video para comprimirlo.")
                    return
                await aviso.edit(content="🗜️ está pesado, lo estoy comprimiendo para que quepa...")
                final = os.path.join(workdir, 'comprimido.mp4')
                await comprimir(path, final, duracion, limite)

        try:
            await ctx.reply(file=discord.File(final, filename='video.mp4'))
        except discord.HTTPException as e:
            if e.status == 413:
                await ctx.reply("❌ Discord no me dejó subirlo, sigue siendo muy pesado.")
            else:
                raise

    except DemasiadoLargo:
        await ctx.reply(f"❌ el video es muy largo para el límite de {limite // (1024 * 1024)} MB "
                        "sin dejarlo ilegible. prueba con uno más corto.")
    except Exception as e:
        await ctx.reply(f"⚠️ algo malo paso al procesar el link, no se ques cariño!!!...: `{limpiar_error(e)}`")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == '__main__':
    keep_alive()
    token = os.environ.get('DISCORD_TOKEN')
    if not token:
        raise SystemExit("Falta la variable de entorno DISCORD_TOKEN")
    bot.run(token)


