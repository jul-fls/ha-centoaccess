"""Resolve user input to an official French commune."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

import aiohttp

from .const import ADDRESS_URL, GEO_URL


class InvalidLocation(Exception):
    """No confident French commune match was found."""


class AmbiguousLocation(Exception):
    """The input matches more than one commune."""


@dataclass(frozen=True)
class Location:
    """An official French commune resolved from user input."""

    code: str
    commune: str
    label: str
    source: str
    unique_id: str
    latitude: float | None = None
    longitude: float | None = None
    postcode: str | None = None


@dataclass(frozen=True)
class PostalChoice:
    """A commune and postal-code pair offered by the setup flow."""

    postcode: str
    code: str
    commune: str

    @property
    def value(self) -> str:
        """Return a stable selector value."""
        return f"{self.postcode}:{self.code}"

    @property
    def label(self) -> str:
        """Return the human-readable selector label."""
        return f"{self.postcode} - {self.commune} ({self.code})"


def normalize_name(value: str) -> str:
    """Normalize names from the French and CentoAccess catalogues."""
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    words = re.findall(r"[a-z0-9]+", ascii_value.casefold())
    prefixes = (
        ("ville", "de"),
        ("ville", "d"),
        ("ville", "du"),
        ("ville", "des"),
        ("mairie", "de"),
        ("mairie", "d"),
        ("mairie", "du"),
        ("mairie", "des"),
        ("commune", "de"),
        ("commune", "d"),
        ("commune", "du"),
        ("commune", "des"),
    )
    for prefix in prefixes:
        if tuple(words[: len(prefix)]) == prefix:
            words = words[len(prefix) :]
            break
    return " ".join(words)


def matching_applications(commune: str, applications: list[dict]) -> list[dict]:
    """Keep only CentoAccess applications matching the official commune."""
    expected = normalize_name(commune)
    return [
        application
        for application in applications
        if application.get("id")
        and normalize_name(str(application.get("name") or "")) == expected
    ]


def _commune_code(code: str) -> str:
    """Map Paris, Lyon and Marseille arrondissements to their commune."""
    if re.fullmatch(r"751(0[1-9]|1[0-9]|20)", code):
        return "75056"
    if re.fullmatch(r"6938[1-9]", code):
        return "69123"
    if re.fullmatch(r"132(0[1-9]|1[0-6])", code):
        return "13055"
    return code


async def _get_json(
    session: aiohttp.ClientSession, url: str, params: dict | None = None
):
    async with session.get(
        url, params=params, timeout=aiohttp.ClientTimeout(total=15)
    ) as response:
        if response.status == 404:
            raise InvalidLocation
        response.raise_for_status()
        return await response.json()


async def _canonical_commune(
    session: aiohttp.ClientSession, code: str
) -> tuple[str, str, list[str]]:
    code = _commune_code(code)
    if not re.fullmatch(r"[0-9AB]{5}", code):
        raise InvalidLocation
    data = await _get_json(
        session, f"{GEO_URL}/{code}", {"fields": "nom,code,codesPostaux"}
    )
    if not isinstance(data, dict) or not data.get("nom") or data.get("code") != code:
        raise InvalidLocation
    postcodes = [
        item for item in data.get("codesPostaux") or [] if isinstance(item, str)
    ]
    return code, data["nom"], postcodes


async def from_insee(session: aiohttp.ClientSession, code: str) -> Location:
    """Resolve an INSEE code."""
    code, name, postcodes = await _canonical_commune(session, code.strip().upper())
    return Location(
        code,
        name,
        name,
        "insee",
        f"insee:{code}",
        postcode=postcodes[0] if postcodes else None,
    )


async def from_coordinates(
    session: aiohttp.ClientSession,
    latitude: float,
    longitude: float,
    source: str = "gps",
) -> Location:
    """Resolve coordinates to their containing commune."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise InvalidLocation
    results = await _get_json(
        session,
        GEO_URL,
        {"lat": latitude, "lon": longitude, "fields": "nom,code"},
    )
    if not isinstance(results, list) or len(results) != 1:
        raise InvalidLocation
    code, name, postcodes = await _canonical_commune(session, results[0]["code"])
    label = (
        f"Home Assistant ({name})"
        if source == "home"
        else f"{latitude:.6f}, {longitude:.6f} ({name})"
    )
    unique_id = "home" if source == "home" else f"gps:{latitude:.6f}:{longitude:.6f}"
    return Location(
        code,
        name,
        label,
        source,
        unique_id,
        latitude,
        longitude,
        postcodes[0] if postcodes else None,
    )


async def search_postal_prefix(
    session: aiohttp.ClientSession, prefix: str
) -> list[PostalChoice]:
    """List every commune with a postal code beginning with the given digits."""
    prefix = prefix.strip()
    if not re.fullmatch(r"\d{2,5}", prefix):
        raise InvalidLocation
    results = await _get_json(
        session, GEO_URL, {"fields": "nom,code,codesPostaux"}
    )
    if not isinstance(results, list):
        raise InvalidLocation
    choices: dict[str, PostalChoice] = {}
    for candidate in results:
        code = candidate.get("code", "")
        name = candidate.get("nom", "")
        for postcode in candidate.get("codesPostaux") or []:
            if (
                isinstance(postcode, str)
                and postcode.startswith(prefix)
                and code
                and name
            ):
                choice = PostalChoice(postcode, code, name)
                choices[choice.value] = choice
    if not choices:
        raise InvalidLocation
    return sorted(
        choices.values(),
        key=lambda choice: (
            choice.postcode,
            normalize_name(choice.commune),
            choice.code,
        ),
    )


async def from_postal_choice(
    session: aiohttp.ClientSession, choice: PostalChoice
) -> Location:
    """Resolve a postal selector choice to its canonical commune."""
    code, name, _ = await _canonical_commune(session, choice.code)
    return Location(
        code,
        name,
        f"{name} ({choice.postcode})",
        "postal_commune",
        f"postal:{choice.postcode}:{code}",
        postcode=choice.postcode,
    )


async def from_address(session: aiohttp.ClientSession, address: str) -> Location:
    """Resolve a complete address with the French national geocoder."""
    address = address.strip()
    if len(address) < 8:
        raise InvalidLocation
    result = await _get_json(
        session, ADDRESS_URL, {"q": address, "index": "address", "limit": 5}
    )
    features = result.get("features", []) if isinstance(result, dict) else []
    if not features:
        raise InvalidLocation
    first = features[0]
    properties = first.get("properties", {})
    score = properties.get("score", 0)
    code = properties.get("citycode", "")
    label = properties.get("label", "")
    if not isinstance(score, (float, int)) or score < 0.75 or not code or not label:
        raise InvalidLocation
    if re.match(r"^\d+\s", address) and properties.get("type") != "housenumber":
        raise InvalidLocation
    for other in features[1:]:
        other_properties = other.get("properties", {})
        if (
            _commune_code(other_properties.get("citycode", ""))
            != _commune_code(code)
            and other_properties.get("score", 0) >= score - 0.05
        ):
            raise AmbiguousLocation
    code, name, postcodes = await _canonical_commune(session, code)
    coordinates = first.get("geometry", {}).get("coordinates", [])
    longitude, latitude = (
        (coordinates[0], coordinates[1])
        if len(coordinates) == 2
        else (None, None)
    )
    address_id = properties.get("id") or normalize_name(label)
    postcode = properties.get("postcode") or (postcodes[0] if postcodes else None)
    return Location(
        code,
        name,
        label,
        "address",
        f"address:{address_id}",
        latitude,
        longitude,
        postcode,
    )
