"""Step 2: resolve {artist, track} on Spotify via the client-credentials flow."""
import os


def resolve(artist: str, track: str) -> dict | None:
    if not (os.getenv("SPOTIPY_CLIENT_ID") and os.getenv("SPOTIPY_CLIENT_SECRET")):
        print("  [spotify] no credentials, skipping")
        return None
    if not track:
        return None
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials

        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials())
        q = f"track:{track}" + (f" artist:{artist}" if artist else "")
        items = sp.search(q=q, type="track", limit=1)["tracks"]["items"]
        if not items:
            items = sp.search(q=f"{track} {artist}".strip(), type="track", limit=1)["tracks"]["items"]
        if not items:
            return None
        t = items[0]
        return {
            "id": t["id"],
            "track": t["name"],
            "artist": ", ".join(a["name"] for a in t["artists"]),
            "album": t["album"]["name"],
            "year": (t["album"].get("release_date") or "")[:4],
            "url": t["external_urls"].get("spotify"),
        }
    except Exception as e:
        print(f"  [spotify] failed: {e}")
        return None
