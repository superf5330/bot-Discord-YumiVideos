import os
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

import os
import discord
from discord.ext import commands
import yt_dlp

# Configurar intents para leer los mensajes
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='.', intents=intents)

@bot.event
async def on_ready():
    print(f'¡Bot conectado con éxito como {bot.YumiVideos}!')

@bot.command(name='bl')
async def descargar_video(ctx, url: str):
    """Comando .bl <enlace> para descargar el video y subirlo al chat."""
    await ctx.send("⏳ ya estoy descargado el vide... no te preocupes...")

    # Opciones de yt-dlp para capturar el video en MP4
    ydl_opts = {
    'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
    'outtmpl': '%(id)s.%(ext)s',
    'postprocessors': [{
        'key': 'FFmpegVideoConvertor',
        'preferedformat': 'mp4',
    }],
}

    filename = None
    try:
        os.makedirs('downloads', exist_ok=True)
        
        # Descargar el video del enlace proporcionado
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

        # Verificar si el archivo se descargó correctamente
        if filename and os.path.exists(filename):
            file_size = os.path.getsize(filename)
            
            # Comprobar el límite del servidor de Discord
            if file_size > ctx.guild.filesize_limit:
                await ctx.send("❌ el video es muy pesado, no creo poder subirlo.")
            else:
                # Subir el archivo directamente al mismo chat
                await ctx.send(file=discord.File(filename))
            
            # Borrar el archivo localmente para liberar espacio
            os.remove(filename)
        else:
            await ctx.send("❌ No pude procesar en elace... no se porque!!!.")

    except Exception as e:
        await ctx.send(f"⚠️ algo malo paso al procesar el link...: `{str(e)}`")
        # Limpieza de emergencia por si falla a mitad de descarga
        if filename and os.path.exists(filename):
            os.remove(filename)

# Conexión segura usando la variable de entorno de la nube
bot.run(os.environ.get('DISCORD_TOKEN'))
