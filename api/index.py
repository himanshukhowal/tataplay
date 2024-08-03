import base64
import logging
import asyncio
import aiohttp
from flask import Flask, redirect, Response, jsonify

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
CONFIG = {
    "channels_url": "https://fox.toxic-gang.xyz/tata/channels",
    "hmac_url": "https://fox.toxic-gang.xyz/tata/hmac",
    "epg_url": "https://raw.githubusercontent.com/mitthu786/tvepg/main/tataplay/epg.xml.gz"
}

def hex_to_base64(hex_string):
    """Convert a hexadecimal string to a Base64 encoded string without trailing '='."""
    try:
        return base64.b64encode(bytes.fromhex(hex_string)).decode('utf-8').rstrip('=')
    except ValueError as e:
        logger.error(f"Hex to Base64 conversion error: {e}")
        return ''

async def fetch_json(session, url):
    """Asynchronously fetch JSON data from a URL."""
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.json()

async def fetch_all_data():
    """Fetch channels and HMAC data from configured URLs."""
    async with aiohttp.ClientSession() as session:
        return await asyncio.gather(
            fetch_json(session, CONFIG["channels_url"]),
            fetch_json(session, CONFIG["hmac_url"])
        )

def fetch_data_sync():
    """Fetch data using asyncio.run to handle async operations."""
    return asyncio.run(fetch_all_data())

@app.route("/")
def index():
    """Redirect to the channel URL obtained from the HMAC service."""
    try:
        _, hmac = fetch_data_sync()
        channel_url = hmac[0]["channel"]
        return redirect(channel_url)
    except Exception as e:
        logger.error(f"Failed to fetch channel URL: {e}")
        return jsonify({"error": "Failed to fetch channel URL"}), 500

@app.route("/tataplay/playlist")
def tataplay_playlist():
    """Generate and serve an M3U playlist based on data from remote services."""
    try:
        channels, hmac = fetch_data_sync()
        user_agent = hmac[0]["userAgent"]
        hdntl = hmac[0]["data"]["hdntl"]

        # Build M3U playlist
        m3u_playlist = [f'#EXTM3U x-tvg-url="{CONFIG["epg_url"]}"\n\n']

        for channel in channels["data"]:
            tvg_id, group_title, tvg_logo, title, mpd = (
                channel["id"], channel["genre"], channel["logo"], channel["title"], channel["initialUrl"]
            )

            license_key = ''
            try:
                license_key = (
                    f'{{"keys":[{{"kty":"oct","k":"{hex_to_base64(channel["licence2"])}","kid":"{hex_to_base64(channel["licence1"])}"}}],"type":"temporary"}}'
                )
            except Exception as e:
                logger.error(f"Error processing license key for channel {tvg_id}: {e}")

            m3u_playlist.append(
                f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{group_title}", tvg-logo="{tvg_logo}", {title}\n'
                f'#KODIPROP:inputstream.adaptive.license_type=clearkey\n'
                f'#KODIPROP:inputstream.adaptive.license_key={license_key}\n'
                f'#EXTVLCOPT:http-user-agent={user_agent}\n'
                f'#EXTHTTP:{{"cookie":"{hdntl}"}}\n'
                f'{mpd}|cookie:{hdntl}\n\n'
            )

        return Response(''.join(m3u_playlist), content_type='text/plain')
    except Exception as e:
        logger.error(f"Failed to fetch playlist data: {e}")
        return jsonify({"error": "Failed to fetch playlist data"}), 500
