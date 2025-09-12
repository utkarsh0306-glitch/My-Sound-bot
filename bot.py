import discord
from discord.ext import commands
from gtts import gTTS
import asyncio
import os
from langdetect import detect, LangDetectException

# --- 1. BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
# <-- THE ONLY CHANGE IS HERE
bot = commands.Bot(command_prefix='@', intents=intents)

# This variable will store the ID of the channel the bot is listening to.
listening_channel_id = None

# --- 2. EVENT: WHEN THE BOT IS READY ---
@bot.event
async def on_ready():
    """This function runs when the bot has successfully connected to Discord."""
    print(f'✅ Logged in as {bot.user.name}')
    print('Always-On TTS Bot is online!')
    print('------')

# --- 3. COMMANDS: @join and @leave (On/Off Switches) ---
@bot.command()
async def join(ctx):
    """Makes the bot join your VC and start listening to the current text channel."""
    global listening_channel_id
    if not ctx.author.voice:
        await ctx.send("You are not connected to a voice channel.")
        return
    
    channel = ctx.author.voice.channel
    if ctx.voice_client is not None:
        await ctx.voice_client.move_to(channel)
    else:
        await channel.connect()

    listening_channel_id = ctx.channel.id
    await ctx.send(f"✅ Now reading all messages sent in **#{ctx.channel.name}**.")

@bot.command()
async def leave(ctx):
    """Makes the bot leave the VC and stop listening."""
    global listening_channel_id
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("I have left the voice channel and stopped listening.")
        listening_channel_id = None
    else:
        await ctx.send("I am not in a voice channel.")

# --- 4. EVENT: ON MESSAGE (The main logic!) ---
@bot.event
async def on_message(message):
    """This event triggers for every message sent in any channel."""
    global listening_channel_id

    if message.author == bot.user:
        await bot.process_commands(message) # Still process commands, even from itself
        return

    # First, process commands to ensure @join and @leave work for all users.
    await bot.process_commands(message)

    # After checking for commands, run the TTS logic if applicable.
    if listening_channel_id is None or message.channel.id != listening_channel_id:
        return

    # Don't speak commands out loud.
    if message.content.startswith('@'):
        return

    if not bot.voice_clients:
        listening_channel_id = None
        return

    try:
        # --- Clean up mentions and other Discord-specific text ---
        cleaned_content = message.content
        for user in message.mentions:
            cleaned_content = cleaned_content.replace(f'<@{user.id}>', user.display_name)
            cleaned_content = cleaned_content.replace(f'<@!{user.id}>', user.display_name)
        for role in message.role_mentions:
            cleaned_content = cleaned_content.replace(f'<@&{role.id}>', role.name)
        for channel in message.channel_mentions:
            cleaned_content = cleaned_content.replace(f'<#{channel.id}>', channel.name)
        cleaned_content = cleaned_content.replace('@everyone', 'everyone')
        cleaned_content = cleaned_content.replace('@here', 'here')
        
        text_to_say = f"{message.author.display_name} said: {cleaned_content}"
        
        lang_code = detect(cleaned_content)
        if lang_code not in ['en', 'hi']:
            lang_code = 'en'

        tts = gTTS(text=text_to_say, lang=lang_code, slow=False)
        speech_file = 'speech.mp3'
        tts.save(speech_file)
        
        while bot.voice_clients[0].is_playing():
            await asyncio.sleep(1)

        bot.voice_clients[0].play(discord.FFmpegPCMAudio(source=speech_file))

    except LangDetectException:
        print(f"Could not detect language for: '{cleaned_content}'")
    except Exception as e:
        print(f"An error occurred: {e}")
    
# --- 5. RUN THE BOT ---
bot.run(os.environ.get('DISCORD_TOKEN'))
