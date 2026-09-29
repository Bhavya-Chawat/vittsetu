"""OpenStreetMap Nominatim geocoding, shared by partner ingest and the admin console.

Nominatim's usage policy allows at most 1 request per second and requires an
identifying User-Agent. The limit is enforced here, process-wide, so the
ingest script and the admin "Geocode address" button can't exceed it.
"""

import threading
import time
from dataclasses import dataclass

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {"User-Agent": "VittSetu-Hackathon-Prototype/1.0 (contact: project maintainer)"}
MIN_INTERVAL_SECONDS = 1.1  # a little over 1 req/sec, per the usage policy

_lock = threading.Lock()
_last_request_at = 0.0


class GeocodingError(RuntimeError):
    """Nominatim couldn't be reached or returned an error (as opposed to no match)."""


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lon: float
    display_name: str


def _wait_for_slot() -> None:
    global _last_request_at
    with _lock:
        wait = _last_request_at + MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def geocode(query: str) -> GeocodeResult | None:
    """Best match for `query` within India, or None if Nominatim finds nothing.
    Raises GeocodingError on network/HTTP failures."""
    _wait_for_slot()
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": f"{query}, India", "format": "json", "limit": 1, "countrycodes": "in"},
            headers=NOMINATIM_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise GeocodingError(str(e)) from e
    if not results:
        return None
    top = results[0]
    return GeocodeResult(float(top["lat"]), float(top["lon"]), top.get("display_name", ""))
