"""
iCloud Shared Album API — reverse-engineered, no official Apple support.

Protocol reference:
  https://gist.github.com/fay59/5cf1f9a19d7d1a38abb4d60d50e67bdc

Flow:
  1. Extract token from URL (fragment after #)
  2. Derive cluster ID from token prefix
  3. POST /webstream → photo list (handle 330 redirect)
  4. POST /webasseturls with photoGuids → download URLs

IMPORTANT — two different URL formats exist:
  - "Public Website" link: https://www.icloud.com/photos/#TOKEN  (TOKEN starts with A or B)
    → Unauthenticated sharedstreams API works here. USE THIS ONE.
  - Invitation/share link: https://share.icloud.com/photos/TOKEN  (TOKEN contains a hyphen)
    → Requires Apple ID login; the sharedstreams API does NOT work here.
    share.icloud.com URLs redirect (HTTP 301) to www.icloud.com/photos/#TOKEN but with
    the same invitation token — it still won't work without login.

Users must enable "Öffentliche Website" (Public Website) in the album's People settings
and share the www.icloud.com link, NOT the regular share/invitation link.
"""
from __future__ import annotations
import re
import httpx


# Matches public-website links from www.icloud.com — both URL formats:
#   /photos/#TOKEN      (older Shared Photo Stream links)
#   /sharedalbum/#TOKEN (newer iCloud Shared Album links)
# Explicitly anchored to www.icloud.com to exclude share.icloud.com invite links.
_URL_RE = re.compile(
    r"(?:www\.)?icloud\.com/(?:photos|sharedalbum)/(?:[^#]*#)?([A-Za-z0-9_-]{10,})"
)

# share.icloud.com links are invitation links that require Apple ID login.
_INVITE_URL_RE = re.compile(r"share\.icloud\.com")

# Characters used for Base62 decoding (token cluster derivation)
_B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def extract_token(url: str) -> str | None:
    """Return the public-website album token from an iCloud URL, or None.

    Only matches www.icloud.com public-website links. Returns None for
    share.icloud.com invitation links so callers can give a clear error.
    """
    if _INVITE_URL_RE.search(url):
        return None
    m = _URL_RE.search(url)
    return m.group(1) if m else None


def is_invite_url(url: str) -> bool:
    """Return True if this is a share.icloud.com invitation link."""
    return bool(_INVITE_URL_RE.search(url))


def _cluster(token: str) -> str:
    """Derive the two-digit iCloud cluster number from the album token."""
    if token.startswith("A"):
        # Second character is the cluster digit (base-36)
        return str(int(token[1], 36)).zfill(2)
    if token.startswith("B"):
        # Characters 2+3 are a base-62 encoded cluster number
        val = _B62.index(token[1]) * 62 + _B62.index(token[2])
        return str(val).zfill(2)
    # Unknown prefix — fall back to cluster 01
    return "01"


async def fetch_album_metadata(token: str) -> dict:
    """
    Fetch album name, contributor, and photo count from iCloud.

    Returns:
        dict with keys: album_name, owner_first, owner_last, photo_count
    Raises:
        httpx.HTTPStatusError on non-2xx/non-330 responses
        ValueError if the 330 redirect response is malformed
    """
    cluster_id = _cluster(token)
    base = f"https://p{cluster_id}-sharedstreams.icloud.com/{token}/sharedstreams"

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        resp = await client.post(
            f"{base}/webstream",
            json={"streamCtag": None},
            headers={"Content-Type": "application/json"},
        )

        # iCloud may redirect to a different cluster (HTTP 330)
        if resp.status_code == 330:
            body = resp.json()
            new_host = body.get("X-Apple-MMe-Host")
            if not new_host:
                raise ValueError(f"iCloud 330 redirect missing X-Apple-MMe-Host: {body}")
            base = f"https://{new_host}/{token}/sharedstreams"
            resp = await client.post(
                f"{base}/webstream",
                json={"streamCtag": None},
                headers={"Content-Type": "application/json"},
            )

        resp.raise_for_status()
        data = resp.json()

    photos: list[dict] = data.get("photos", [])
    stream_name: str = data.get("streamName", "")

    # Contributor info lives on individual photos; take the first available
    owner_first = owner_last = None
    for photo in photos:
        f = photo.get("contributorFirstName")
        l = photo.get("contributorLastName")
        if f or l:
            owner_first, owner_last = f, l
            break

    return {
        "album_name": stream_name or None,
        "owner_first": owner_first,
        "owner_last": owner_last,
        "photo_count": len(photos),
    }


async def fetch_asset_urls(token: str, photo_guids: list[str]) -> dict[str, str]:
    """
    Resolve photo GUIDs to download URLs.

    Returns:
        dict mapping guid → download URL (largest available derivative)
    """
    cluster_id = _cluster(token)
    base = f"https://p{cluster_id}-sharedstreams.icloud.com/{token}/sharedstreams"

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        resp = await client.post(
            f"{base}/webasseturls",
            json={"photoGuids": photo_guids},
            headers={"Content-Type": "application/json"},
        )

        if resp.status_code == 330:
            body = resp.json()
            new_host = body.get("X-Apple-MMe-Host")
            if not new_host:
                raise ValueError(f"iCloud 330 redirect missing X-Apple-MMe-Host: {body}")
            base = f"https://{new_host}/{token}/sharedstreams"
            resp = await client.post(
                f"{base}/webasseturls",
                json={"photoGuids": photo_guids},
                headers={"Content-Type": "application/json"},
            )

        resp.raise_for_status()
        items: dict = resp.json().get("items", {})

    result: dict[str, str] = {}
    for guid, item in items.items():
        url_info = item.get("url_location") or item.get("url")
        if url_info:
            result[guid] = url_info
    return result
