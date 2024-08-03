import aiohttp
import asyncio
import base64
import logging
import os
from quart import Quart, redirect, Response, jsonify

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration for external service URLs and server settings
CONFIG = {
    "channels_url": "https://fox.toxic-gang.xyz/tata/channels",
    "keys_url": "https://fox.toxic-gang.xyz/tata/key",
    "hmac_url": "https://fox.toxic-gang.xyz/tata/hmac",
    "epg_url": "https://raw.githubusercontent.com/mitthu786/tvepg/main/tataplay/epg.xml.gz",
    "FQDN": os.getenv('FQDN', 'localhost:5000')
}

app = Quart(__name__)

def hex_to_base64(hex_string):
    """
    Convert a hexadecimal string to a Base64 encoded string without trailing '='.

    Args:
        hex_string (str): Hexadecimal string to convert.

    Returns:
        str: Base64 encoded string without padding.
    """
    try:
        return base64.b64encode(bytes.fromhex(hex_string)).decode('utf-8').replace("+", "-").replace("/", "_").rstrip('=')
    except ValueError as e:
        logger.error(f"Hex to Base64 conversion error: {e}")
        return ''

async def fetch_json(session, url):
    """
    Asynchronously fetch JSON data from a URL.

    Args:
        session (aiohttp.ClientSession): The aiohttp session to use.
        url (str): URL to fetch data from.

    Returns:
        dict: Parsed JSON data.

    Raises:
        aiohttp.ClientResponseError: If the request fails.
    """
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.json()

async def fetch_all_data():
    """
    Fetch channels and HMAC data from configured URLs asynchronously.

    Returns:
        tuple: A tuple containing channels data and HMAC data.
    """
    async with aiohttp.ClientSession() as session:
        return await asyncio.gather(
            fetch_json(session, CONFIG["channels_url"]),
            fetch_json(session, CONFIG["hmac_url"])
        )

async def fetch_keys(tvg_id):
    """
    Fetch keys data for a given TVG ID.

    Args:
        tvg_id (str): TVG ID to fetch keys for.

    Returns:
        tuple: A tuple containing Base64 encoded license keys.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(f'{CONFIG["keys_url"]}/{tvg_id}') as response:
            response.raise_for_status()
            keys = await response.json()
            licence1 = keys[0]["data"]["licence1"]
            licence2 = keys[0]["data"]["licence2"]
            return hex_to_base64(licence2), hex_to_base64(licence1)

@app.route("/")
async def index():
    """
    Redirect to the channel URL obtained from the HMAC service.

    Returns:
        Redirect: Redirects to the channel URL.
        JSON: Error message in case of failure.
    """
    try:
        _, hmac = await fetch_all_data()
        channel_url = hmac[0]["channel"]
        return redirect(channel_url)
    except Exception as e:
        logger.error(f"Failed to fetch channel URL: {e}")
        return jsonify({"error": "Failed to fetch channel URL"}), 500

@app.route("/tataplay/keys/<tvg_id>", methods=["GET", "POST"])
async def tataplay_keys(tvg_id):
    """
    Provide license key for the given TVG ID.

    Args:
        tvg_id (str): TVG ID to get the license key for.

    Returns:
        JSON: License key in JSON format.
        tuple: Error status code if an exception occurs.
    """
    try:
        licence2, licence1 = await fetch_keys(tvg_id)
        license_key = {
            "keys": [
                {
                    "kty": "oct",
                    "k": licence2,
                    "kid": licence1
                }
            ],
            "type": "temporary"
        }
        return jsonify(license_key)
    except Exception as e:
        logger.error(f"Error processing license key for channel {tvg_id}: {e}")
        return '', 500

@app.route("/tataplay/playlist")
async def tataplay_playlist():
    """
    Generate and serve an M3U playlist based on data from remote services.

    Returns:
        Response: M3U playlist content with appropriate headers.
        JSON: Error message in case of failure.
    """
    try:
        channels, hmac = await fetch_all_data()
        user_agent = hmac[0]["userAgent"]
        hdntl = hmac[0]["data"]["hdntl"]

        # Build M3U playlist
        m3u_playlist = [f'#EXTM3U x-tvg-url="{CONFIG["epg_url"]}"\n\n']

        async def create_playlist_entry(channel):
            """
            Create a playlist entry for a given channel.

            Args:
                channel (dict): Channel data.

            Returns:
                str: Playlist entry.
            """
            tvg_id = channel["id"]
            group_title = channel["genre"]
            tvg_logo = channel["logo"]
            title = channel["title"]
            mpd = channel["initialUrl"]
            license_key_url = f'http://{CONFIG["FQDN"]}/tataplay/keys/{tvg_id}'

            return (
                f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{group_title}", tvg-logo="{tvg_logo}", {title}\n'
                f'#KODIPROP:inputstream.adaptive.license_type=clearkey\n'
                f'#KODIPROP:inputstream.adaptive.license_key={license_key_url}\n'
                f'#EXTVLCOPT:http-user-agent={user_agent}\n'
                f'#EXTHTTP:{{"cookie":"{hdntl}"}}\n'
                f'{mpd}|cookie:{hdntl}\n\n'
            )

        playlist_entries = await asyncio.gather(*(create_playlist_entry(ch) for ch in channels["data"]))

        m3u_playlist.extend(playlist_entries)

        return Response(''.join(m3u_playlist), content_type='text/plain')
    except Exception as e:
        logger.error(f"Failed to fetch playlist data: {e}")
        return jsonify({"error": "Failed to fetch playlist data"}), 500
