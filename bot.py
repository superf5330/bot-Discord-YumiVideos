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

# Control de spam inteligente: almacena {'count': int, 'last_time': float}
keyword_data = {}
last_bot_spoke = 0

# Raíces y palabras clave con sus conjugaciones comunes
TRIGGER_WORDS = {
    "adulto": ["porno", "sexo", "hentai", "nudes", "pack", "nsfw", "rule34", "paja", "pajas", "pajero"],
    "raro": ["furros", "femboys", "pene", "vagina"],
    "follar": ["follar", "follarte", "follare", "follan", "follaron", "follaste", "follando"],
    "coger": ["coger", "coges", "cogen", "cogieron", "cogiendo", "cojas"],
    "drogas": ["drogas", "marihuana", "perico", "tusi", "poro", "weed"]
}

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

    # 1. Detección de palabras clave y conjugaciones
    categoria_detectada = None
    for categoria, palabras in TRIGGER_WORDS.items():
        if any(palabra in content for palabra in palabras):
            categoria_detectada = categoria
            break

    if categoria_detectada:
        # Validar si es multimedia (fotos, videos, archivos adjuntos o embeds) para la categoría de fotos rarunas
        es_multimedia = bool(message.attachments or message.embeds)

        # Si es categoría de contenido adulto/follar pero NO tiene foto/video/embed, lo ignoramos (es texto común)
        if categoria_detectada in ["adulto", "follar"] and not es_multimedia:
            pass
        else:
            if categoria_detectada not in keyword_data:
                keyword_data[categoria_detectada] = {'count': 0, 'last_time': 0}

            data = keyword_data[categoria_detectada]

            # Si pasaron más de 30 segundos desde la última vez que se mencionó, reiniciamos el contador a 1
            if (current_time - data['last_time']) > 30:
                data['count'] = 1
            else:
                data['count'] += 1

            data['last_time'] = current_time

            # ¿Llegó a 5 menciones rápidas O pasaron más de 30 minutos (1800s) desde la última vez que habló el bot?
            if data['count'] >= 5 or (current_time - last_bot_spoke) >= 1800:
                last_bot_spoke = current_time
                data['count'] = 0  # Reiniciar contador

                if categoria_detectada in ["adulto", "follar"]:
                    await message.reply("otra foto raruna o… ¿por fin dejaron de mandar porno, chicos?... 😅😅😅")
                else:
                    await message.reply("emmm… ¿okey? ¿de qué están hablando?... 🤨🤨🤨")

    # 2. Detección de enlaces, fotos o archivos con reacciones (más de 3 emojis)
    if message.embeds or message.attachments or "http" in content:
        total_reactions = sum(reaction.count for reaction in message.reactions)
        if total_reactions >= 3 and (current_time - last_bot_spoke) >= 1800:
            last_bot_spoke = current_time
            await message.reply("¿qué tendrá ese link o archivo para tantas reacciones?... 😅😅😅")

    # IMPORTANTE: Procesar los comandos normales (como .bl)
    await bot.process_commands(message)

@bot.command(name='bl')
async def descargar_video(ctx, url: str):
    """Comando .bl <enlace> para descargar el video y subirlo al chat."""
    await ctx.reply("⏳ ya estoy descargando el video... no te preocupes...❤️❤️❤️")

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
                await ctx.reply("❌ el video es muy pesado, no creo poder subirlo. lo siento.")
            else:
                await ctx.reply(file=discord.File(filename))
            
            os.remove(filename)
        else:
            await ctx.reply("❌ No pude procesar el enlace... no se porque!!!.")

    except Exception as e:
        await ctx.reply(f"⚠️ algo malo paso al procesar el link, no se ques cariño!!!...: `{str(e)}`")
        if filename and os.path.exists(filename):
            os.remove(filename)

bot.run(os.environ.get('DISCORD_TOKEN'))
