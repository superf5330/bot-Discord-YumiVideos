import os
import time
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands
import yt_dlp

app = Flask('')

@app.route('/')
def home():
    return "Bot Online"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

# Configurar intents para leer los mensajes, contenido y reacciones
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix='.', intents=intents)

# Control de spam y memoria temporal
keyword_counts = {}
last_bot_spoke = 0

# Lista ampliada de palabras clave "incómodas" o raras
TRIGGER_WORDS = [
    "porno", "sexo", "drogas", "hentai", "furros", "femboys", 
    "nudes", "pack", "nsfw", "rule34", "paja", "coger", 
    "follar", "marihuana", "perico", "tusi", "pene", "vagina"
]

@bot.event
async def on_ready():
    print(f'¡Bot conectado con éxito como {bot.user}!')

@bot.event
async def on_message(message):
    global last_bot_spoke
    
    # Evitar que el bot se responda a sí mismo
    if message.author == bot.user:
        return

    current_time = time.time()
    content = message.content.lower()

    # 1. Detección de palabras clave con control anti-spam (5 menciones o 30 minutos sin hablar)
    palabra_detectada = None
    for word in TRIGGER_WORDS:
        if word in content:
            palabra_detectada = word
            break

    if palabra_detectada:
        if palabra_detectada not in keyword_counts:
            keyword_counts[palabra_detectada] = 0
        
        keyword_counts[palabra_detectada] += 1

        # ¿Llegó a 5 menciones o pasaron 30 minutos (1800 segundos) desde la última vez?
        if keyword_counts[palabra_detectada] >= 5 or (current_time - last_bot_spoke) >= 1800:
            last_bot_spoke = current_time
            keyword_counts[palabra_detectada] = 0  # Reiniciar contador

            if palabra_detectada in ["porno", "sexo", "hentai", "nudes", "pack", "nsfw", "rule34", "paja"]:
                await message.channel.send("otra foto raruna o… ¿por fin dejaron de mandar porno, chicos?")
            else:
                await message.channel.send("emmm… ¿okey? ¿de qué están hablando?")

    # 2. Detección de enlaces o archivos multimedia con muchas reacciones (más de 3 emojis)
    if message.embeds or message.attachments or "http" in content:
        total_reactions = sum(reaction.count for reaction in message.reactions)
        if total_reactions >= 3 and (current_time - last_bot_spoke) >= 1800:
            last_bot_spoke = current_time
            await message.channel.send("¿qué tendrá ese link o archivo para tantas reacciones?")

    # IMPORTANTE: Permitir que funcionen los comandos del bot (como .bl)
    await bot.process_commands(message)

@bot.command(name='bl')
async def descargar_video(ctx, url: str):
    """Comando .bl <enlace> para descargar el video y subirlo al chat."""
    await ctx.send("⏳ ya estoy descargando el video... no te preocupes...")

    ydl_opts = {
        'format': 'best[height<=360]/best',
        'outtmpl': '%(id)s.%(ext)s',
        'max_filesize': 8 * 1024 * 1024,
        'noplaylist': True,
    }

    filename = None
    try:
        os.makedirs('downloads', exist_ok=True)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

        if filename and os.path.exists(filename):
            file_size = os.path.getsize(filename)
            
            if file_size > ctx.guild.filesize_limit:
                await ctx.send("❌ el video es muy pesado, no creo poder subirlo.")
            else:
                await ctx.send(file=discord.File(filename))
            
            os.remove(filename)
        else:
            await ctx.send("❌ No pude procesar el enlace... no se porque!!!.")

    except Exception as e:
        await ctx.send(f"⚠️ algo malo paso al procesar el link...: `{str(e)}`")
        if filename and os.path.exists(filename):
            os.remove(filename)

bot.run(os.environ.get('DISCORD_TOKEN'))
