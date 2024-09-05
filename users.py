import discord
from discord.ext import tasks, commands
from discord import app_commands
import requests
import datetime
import pytz
import os
import json
from dotenv import load_dotenv

intents = discord.Intents.all()
client = commands.Bot(command_prefix="!", intents=intents)

stream_channel_id = 1244537836837797929

# you can comment these out if you dont want to get pinged
odd_id = 745762346479386686
stream_ping = f"<@{odd_id}>"

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
TWITCH_OAUTH_TOKEN = os.getenv('TWITCH_OAUTH_TOKEN')
TWITCH_REFRESH_TOKEN = os.getenv('TWITCH_REFRESH_TOKEN')
TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')

streamers_list = {}
sent_streams = {}
json_file = "streamers.json"

token_expiry = datetime.datetime.utcnow()

def load_streamers():
    global streamers_list
    try:
        with open(json_file, 'r') as file:
            streamers_list = json.load(file)
    except FileNotFoundError:
        with open(json_file, 'w') as file:
            json.dump({}, file)
    print(f"Loaded streamers: {streamers_list}")

def save_streamers():
    with open(json_file, 'w') as file:
        json.dump(streamers_list, file)

def refresh_twitch_token():
    global TWITCH_OAUTH_TOKEN, TWITCH_REFRESH_TOKEN, token_expiry
    url = "https://id.twitch.tv/oauth2/token"
    params = {
        "grant_type": "refresh_token",
        "refresh_token": TWITCH_REFRESH_TOKEN,
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET
    }
    response = requests.post(url, params=params)
    if response.status_code == 200:
        data = response.json()
        TWITCH_OAUTH_TOKEN = data['access_token']
        TWITCH_REFRESH_TOKEN = data['refresh_token']
        token_expiry = datetime.datetime.utcnow() + datetime.timedelta(seconds=data['expires_in'])
        print("Twitch OAuth token refreshed successfully.")
    else:
        print(f"Error refreshing Twitch token: {response.status_code}")
        print("Response:", response.content)

def get_twitch_id(username):
    url = "https://api.twitch.tv/helix/users"
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {TWITCH_OAUTH_TOKEN}"
    }
    params = {
        "login": username
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json()['data']
        if data:
            return data[0]['id'], data[0]['display_name']
        else:
            return None, None
    else:
        print(f"Error fetching Twitch ID: {response.status_code}")
        return None, None

def get_active_streams(streamer_id):
    global TWITCH_OAUTH_TOKEN
    url = "https://api.twitch.tv/helix/streams"
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {TWITCH_OAUTH_TOKEN}"
    }
    params = {
        "user_id": streamer_id
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()["data"]
    else:
        print(f"Error fetching streams: {response.status_code}")
        return []

async def send_streams_to_channels():
    global sent_streams
    for streamer_id, streamer_name in streamers_list.items():
        active_streams = get_active_streams(streamer_id)
        for stream in active_streams:
            stream_id = stream['id']
            if stream_id not in sent_streams or not sent_streams[stream_id]:
                stream_link = f"https://www.twitch.tv/{stream['user_login']}"
                start_time = datetime.datetime.strptime(stream['started_at'], "%Y-%m-%dT%H:%M:%SZ")
                utc = pytz.utc
                est = pytz.timezone('America/New_York')
                start_time = utc.localize(start_time).astimezone(est)
                formatted_start_time = start_time.strftime("%m/%d/%Y, %I:%M %p")
                message = f"{stream_ping}\nTitle: {stream['title']}\nStream Started at: {formatted_start_time} EST\nViewer Count: {stream['viewer_count']}\nStream Link: {stream_link}\n-------------"
                channel = client.get_channel(stream_channel_id)
                if channel:
                    await channel.send(message)
                sent_streams[stream_id] = True
                print(f"Stream detected and sent: {stream['title']} - Viewer Count: {stream['viewer_count']}")
            else:
                if stream_id in sent_streams and not stream['type'] == 'live':
                    sent_streams[stream_id] = False

@tasks.loop(seconds=2)
async def automatic_stream_check():
    if datetime.datetime.utcnow() > token_expiry:
        refresh_twitch_token()
    await send_streams_to_channels()

@client.tree.command(name="add", description="Add a streamer by their Twitch username.")
async def add(interaction: discord.Interaction, username: str, streamer_id: str = None):
    twitch_id, display_name = get_twitch_id(username)
    if twitch_id and display_name:
        if streamer_id:
            twitch_id = streamer_id
        if twitch_id not in streamers_list:
            streamers_list[twitch_id] = display_name
            save_streamers()
            await interaction.response.send_message(f"Added streamer: {display_name}")
        else:
            await interaction.response.send_message(f"{display_name} is already in the list.", ephemeral=True)
    else:
        await interaction.response.send_message("Username not found on Twitch.", ephemeral=True)

@client.tree.command(name="remove", description="Remove a streamer by their index in the list.")
async def remove(interaction: discord.Interaction, index: int):
    if index < 1 or index > len(streamers_list):
        await interaction.response.send_message("Invalid index.", ephemeral=True)
        return
    streamer_id = list(streamers_list.keys())[index - 1]
    removed_name = streamers_list.pop(streamer_id)
    save_streamers()
    await interaction.response.send_message(f"Removed streamer: {removed_name}")

@client.tree.command(name="view", description="View all currently added streamers.")
async def view(interaction: discord.Interaction):
    if streamers_list:
        streamers = "\n".join([f"{i + 1}. {name} (ID: {id_})" for i, (id_, name) in enumerate(streamers_list.items())])
        await interaction.response.send_message(f"Current streamers:\n{streamers}")
    else:
        await interaction.response.send_message("No streamers added yet.")

@client.tree.command(name="streams", description="View all currently active streams.")
async def streams(interaction: discord.Interaction):
    active_streams_list = []
    for streamer_id, streamer_name in streamers_list.items():
        active_streams = get_active_streams(streamer_id)
        for stream in active_streams:
            stream_link = f"https://www.twitch.tv/{stream['user_login']}"
            active_streams_list.append(f"{streamer_name}: {stream_link}")
    
    if active_streams_list:
        active_streams_str = "\n".join(active_streams_list)
        await interaction.response.send_message(f"Currently live streams:\n{active_streams_str}")
    else:
        await interaction.response.send_message("No active streams at the moment.")

@client.event
async def on_ready():
    load_streamers()
    await client.tree.sync()
    print(f"Logged in as {client.user}")
    automatic_stream_check.start()

client.run(DISCORD_TOKEN)
