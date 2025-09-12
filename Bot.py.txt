import discord
from discord.ext import commands
from gtts import gTTS
import asyncio
import os

# --- 1. BOT SETUP ---
# Define the permissions (Intents) the bot needs to function.
# It needs to read messages and see who is in a voice channel.
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

# Create the bot with a command prefix "!" and the defined intents.
bot = commands.Bot(command_prefix='!', intents=intents)


# --- 2. EVENT: WHEN THE BOT IS READY ---
@bot.event
async def on_ready():
    """This function runs when the bot has successfully connected to Discord."""
    print(f'✅ Logged in as {bot.user.name}')
    print(f'Bot ID: {bot.user.id}')
    print('Bot is online and ready to speak!')
    print('------')


# --- 3. COMMAND: !say ---
@bot.command()
async def say(ctx, language: str, *, text: str):
    """
    Converts text to speech and plays it in the user's voice channel.
    Usage: !say <language> <text>
    Supported Languages: english, hindi, hinglish
    """

    # First, check if the person who sent the command is in a voice channel.
    if not ctx.author.voice:
        await ctx.send("You need to be in a voice channel to use this command.")
        return

    # Map the user-friendly language names to the codes gTTS understands.
    lang_map = {
        'english': 'en',
        'hindi': 'hi',
        'hinglish': 'hi'  # 'hi' code works well for Hinglish (mixed Hindi/English).
    }

    # Check if the language the user provided is one we support.
    lang_code = lang_map.get(language.lower())
    if not lang_code:
        await ctx.send("Invalid language. Please use 'english', 'hindi', or 'hinglish'.")
        return

    try:
        # Connect to the voice channel the user is in.
        voice_channel = ctx.author.voice.channel
        voice_client = await voice_channel.connect()

        # Generate the speech using Google Text-to-Speech (gTTS).
        tts = gTTS(text=text, lang=lang_code, slow=False)
        
        # Save the generated speech to a temporary audio file.
        speech_file = 'speech.mp3'
        tts.save(speech_file)

        # Play the audio file in the voice channel.
        voice_client.play(discord.FFmpegPCMAudio(source=speech_file))

        # Wait in the channel until the audio is finished playing.
        while voice_client.is_playing():
            await asyncio.sleep(1)

        # Once done, disconnect from the voice channel.
        await voice_client.disconnect()

        # Clean up by deleting the temporary audio file.
        os.remove(speech_file)

    except Exception as e:
        # Send an error message if something goes wrong.
        await ctx.send(f"An error occurred: {e}")
        # Make sure to disconnect and clean up if an error happens.
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
        if os.path.exists('speech.mp3'):
            os.remove('speech.mp3')


# --- 4. COMMAND: !leave (Optional but helpful) ---
@bot.command()
async def leave(ctx):
    """Makes the bot leave its current voice channel."""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("I have left the voice channel.")
    else:
        await ctx.send("I am not in a voice channel.")


# --- 5. RUN THE BOT ---
# This line securely gets the bot's token from the hosting environment (like Render or Replit).
# Make sure you have set up the 'DISCORD_TOKEN' secret!
bot.run(os.environ.get('DISCORD_TOKEN'))