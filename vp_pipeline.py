from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
STORE_DIR = DATA_DIR / "store"
STORE_SNAPSHOTS_DIR = DATA_DIR / "store_snapshots"
PUBLISHED_DIR = DATA_DIR / "published"
STATE_DIR = DATA_DIR / "state"
PHOTOS_DIR = DATA_DIR / "photos"

API_BASE_URL = "https://ws.vlpar.be/e/opendata"
SEARCH_API_BASE_URL = "https://ws.vlpar.be/api/search/query"
PHOTO_BASE_URL = "https://www.vlaamsparlement.be"

DEFAULT_BOOTSTRAP_DAYS = 365
DEFAULT_ROLLING_UPDATE_DAYS = 45
DEFAULT_SEARCH_PAGE_SIZE = 100
DEFAULT_MAX_SEARCH_PAGES = 40
PHOTO_REFRESH_DAYS = 30
MEETING_LOOKAHEAD_DAYS = 60
MEETING_CHUNK_DAYS = 31


def ensure_directories() -> None:
    for path in [DATA_DIR, STORE_DIR, STORE_SNAPSHOTS_DIR, PUBLISHED_DIR, STATE_DIR, PHOTOS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def normalize_opendata_url(url: str | None) -> str | None:
    if not url:
        return None
    return url.replace("http://", "https://")


def first_link_href(links: list[dict[str, Any]] | None, rel: str | None = None) -> str | None:
    if not links:
        return None
    for link in links:
        if rel is None or link.get("rel") == rel:
            href = link.get("href")
            if href:
                return normalize_opendata_url(href)
    return None


def normalize_photo_url(url: str | None) -> str | None:
    if not url:
        return None
    normalized = url.strip()
    if normalized.startswith("//"):
        return f"https:{normalized}"
    if normalized.startswith("/"):
        return f"{PHOTO_BASE_URL}{normalized}"
    return normalized.replace("http://", "https://")


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def days_since_iso(value: str | None) -> int | None:
    parsed = parse_iso_date(value)
    if not parsed:
        return None
    return (date.today() - parsed).days


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def serialize_repo_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR.resolve()))
    except ValueError:
        return str(path)


def current_store_dir(state: dict[str, Any] | None = None) -> Path:
    state = state or read_json(STATE_DIR / "sync_state.json", default={})
    configured = state.get("current_store_dir")
    if configured:
        candidate = Path(configured)
        if candidate.exists():
            return candidate
        if not candidate.is_absolute():
            relative_candidate = ROOT_DIR / candidate
            if relative_candidate.exists():
                return relative_candidate
    snapshots = sorted([path for path in STORE_SNAPSHOTS_DIR.iterdir() if path.is_dir()], reverse=True) if STORE_SNAPSHOTS_DIR.exists() else []
    if snapshots:
        return snapshots[0]
    if STORE_DIR.exists():
        return STORE_DIR
    return STORE_DIR


def load_csv(name: str, parse_dates: list[str] | None = None, store_dir: Path | None = None) -> pd.DataFrame:
    path = (store_dir or current_store_dir()) / f"{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=parse_dates)


def save_csv(name: str, frame: pd.DataFrame, store_dir: Path) -> None:
    path = store_dir / f"{name}.csv"
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_store_tables(tables: dict[str, pd.DataFrame]) -> Path:
    snapshot_dir = STORE_SNAPSHOTS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        save_csv(name, frame, snapshot_dir)
    return snapshot_dir


def flatten_list(values: list[Any]) -> str:
    return " | ".join(str(value) for value in values if value is not None)


def strip_html(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def person_name(person: dict[str, Any] | None) -> str:
    if not person:
        return ""
    first = person.get("voornaam") or ""
    last = person.get("naam") or ""
    return f"{first} {last}".strip()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def first_website_by_type(websites: list[dict[str, Any]], kind: str) -> str | None:
    for website in websites:
        if (website.get("soort") or "").lower() == kind.lower():
            return website.get("value")
    return None


def address_parts(address: dict[str, Any] | None, prefix: str) -> dict[str, Any]:
    address = address or {}
    district = address.get("deelgemeente") or {}
    phones = address.get("telnr") or address.get("telNr") or []
    faxes = address.get("faxnummer") or []
    return {
        f"{prefix}_straat": address.get("straat"),
        f"{prefix}_nr": address.get("nr"),
        f"{prefix}_postcode": district.get("postnr"),
        f"{prefix}_gemeente": district.get("naam"),
        f"{prefix}_correspondentieadres": address.get("correspondentieadres") or address.get("corrAdres"),
        f"{prefix}_telefoon": flatten_list(phones),
        f"{prefix}_fax": flatten_list(faxes),
    }


def normalize_text_list(values: Any) -> list[str]:
    if not values:
        return []
    if isinstance(values, list):
        return [str(value) for value in values if value is not None]
    return [str(values)]


def extract_metatags(item: dict[str, Any]) -> dict[str, Any]:
    meta = {}
    for tag in item.get("metatags", {}).get("metatag", []):
        meta[tag["name"]] = tag["value"]
    return meta


@dataclass
class VlaamsParlementClient:
    session: requests.Session

    @classmethod
    def create(cls) -> "VlaamsParlementClient":
        session = requests.Session()
        session.headers.update({"Accept": "application/json"})
        return cls(session=session)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(url, params=params, timeout=45)
        response.raise_for_status()
        return response.json()

    def opendata(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.get_json(f"{API_BASE_URL}{path}", params=params)

    def search(self, query: str, page: int, max_items: int) -> dict[str, Any]:
        return self.get_json(
            f"{SEARCH_API_BASE_URL}/{query}",
            params={
                "collection": "vp_collection",
                "page": page,
                "max": max_items,
                "sort": "date",
            },
        )


def bootstrap_since_date(today: date) -> date:
    return today - timedelta(days=DEFAULT_BOOTSTRAP_DAYS)


def rolling_since_date(last_successful_sync: str | None, today: date) -> date:
    if not last_successful_sync:
        return bootstrap_since_date(today)
    parsed = parse_iso_date(last_successful_sync)
    if not parsed:
        return bootstrap_since_date(today)
    return parsed - timedelta(days=DEFAULT_ROLLING_UPDATE_DAYS)


def discover_documents_via_search(
    client: VlaamsParlementClient,
    query: str,
    expected_soort: str,
    since_date: date,
    max_pages: int = DEFAULT_MAX_SEARCH_PAGES,
    max_items: int = DEFAULT_SEARCH_PAGE_SIZE,
) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for page in range(1, max_pages + 1):
        payload = client.search(query=query, page=page, max_items=max_items)
        results = payload.get("result", [])
        if not results:
            break

        matching_this_page = 0
        stale_this_page = 0
        for item in results:
            meta = extract_metatags(item)
            if meta.get("soort") != expected_soort:
                continue

            published = parse_iso_date(
                meta.get("publicatiedatum") or meta.get("datum") or meta.get("eerstepublicatie")
            )
            if published and published < since_date:
                stale_this_page += 1
                continue

            opendata_url = normalize_opendata_url(meta.get("opendata"))
            if not opendata_url:
                continue
            doc_id = int(opendata_url.rstrip("/").split("/")[-1])
            if doc_id in seen_ids:
                continue

            seen_ids.add(doc_id)
            matching_this_page += 1
            discovered.append(
                {
                    "id": doc_id,
                    "query": query,
                    "source": "search_api",
                    "soort": meta.get("soort"),
                    "aggregaattype": meta.get("aggregaattype"),
                    "publicatiedatum": meta.get("publicatiedatum"),
                    "displayurl": meta.get("displayurl"),
                    "opendata_url": opendata_url,
                    "onderwerp": meta.get("onderwerp"),
                    "titel": meta.get("titel"),
                    "nummer": meta.get("nummer"),
                    "vraagsteller": meta.get("vraagsteller"),
                    "minister": meta.get("minister"),
                    "status": meta.get("status"),
                    "zittingsjaar": meta.get("zittingsjaar"),
                    "legislatuur": meta.get("legislatuur"),
                }
            )

        if matching_this_page == 0 and stale_this_page > 0:
            break

    return discovered


def discover_oral_items_via_committees(
    client: VlaamsParlementClient,
) -> list[dict[str, Any]]:
    payload = client.opendata("/comm/huidige")
    committees = [item.get("commissie", {}) for item in payload.get("items", [])]
    discovered: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for committee in committees:
        committee_id = committee.get("id")
        if not committee_id:
            continue
        status_payload = client.opendata(f"/comm/{committee_id}/alle-stvz")
        for item in status_payload.get("items", []):
            block = item.get("commissie-status", {})
            status_name = block.get("status")
            for oral_item in block.get("vrageninterpellatie", []):
                oral_id = oral_item.get("id")
                if not oral_id or oral_id in seen_ids:
                    continue
                seen_ids.add(oral_id)
                discovered.append(
                    {
                        "id": oral_id,
                        "source": "committee_status",
                        "committee_id": committee_id,
                        "committee_name": committee.get("titel"),
                        "committee_code": committee.get("afkorting"),
                        "status": status_name,
                        "nummer": oral_item.get("nummer"),
                        "titel": oral_item.get("titel"),
                        "onderwerp": oral_item.get("onderwerp"),
                        "objecttype": (oral_item.get("objecttype") or {}).get("naam"),
                        "opendata_url": normalize_opendata_url(
                            next((link.get("href") for link in oral_item.get("link", []) if link.get("rel") == "self"), None)
                        ),
                    }
                )
    return discovered


def discover_meetings_via_date_ranges(
    client: VlaamsParlementClient,
    start_date: date,
    end_date: date,
    chunk_days: int = MEETING_CHUNK_DAYS,
) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    current = start_date

    while current <= end_date:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end_date)
        page = 1
        while True:
            payload = client.opendata(
                "/verg/zoek/datums",
                params={
                    "datumVan": current.strftime("%d%m%Y"),
                    "datumTot": chunk_end.strftime("%d%m%Y"),
                    "page": page,
                    "sort": "datum",
                },
            )
            items = payload.get("items", [])
            if not items:
                break

            for item in items:
                meeting = item.get("vergadering", {})
                meeting_id = meeting.get("id")
                if not meeting_id or int(meeting_id) in seen_ids:
                    continue
                seen_ids.add(int(meeting_id))
                discovered.append(item)

            count = int(payload.get("count") or 0)
            last_index = int(payload.get("lastindex") or 0)
            if last_index >= count or len(items) == 0:
                break
            page += 1

        current = chunk_end + timedelta(days=1)

    return discovered


def fetch_current_members(client: VlaamsParlementClient) -> list[dict[str, Any]]:
    payload = client.opendata("/vv/huidige")
    return [item.get("volksvertegenwoordiger", {}) for item in payload.get("items", []) if item.get("volksvertegenwoordiger")]


def fetch_member_detail(client: VlaamsParlementClient, person_id: int) -> dict[str, Any]:
    return client.opendata(f"/vv/{person_id}", params={"lang": "nl"})


def fetch_current_fractions(client: VlaamsParlementClient) -> list[dict[str, Any]]:
    payload = client.opendata("/vv/huidige/perfractie")
    return payload.get("items", [])


def fetch_current_committees(client: VlaamsParlementClient) -> list[dict[str, Any]]:
    payload = client.opendata("/comm/huidige")
    return [item.get("commissie", {}) for item in payload.get("items", []) if item.get("commissie")]


def fetch_committee_detail(client: VlaamsParlementClient, committee_id: int) -> dict[str, Any]:
    return client.opendata(f"/comm/{committee_id}")


def fetch_meeting_agenda(client: VlaamsParlementClient, meeting_id: int) -> dict[str, Any]:
    return client.opendata(f"/verg/{meeting_id}/agd", params={"aanpassingen": "nee"})


def fetch_meeting_proceedings(client: VlaamsParlementClient, meeting_id: int) -> dict[str, Any]:
    return client.opendata(f"/verg/{meeting_id}/hand")


def fetch_written_question_detail(client: VlaamsParlementClient, question_id: int) -> dict[str, Any]:
    return client.opendata(f"/schv/{question_id}")


def fetch_oral_item_detail(client: VlaamsParlementClient, item_id: int) -> dict[str, Any]:
    payload = client.opendata(f"/vi/{item_id}")
    payload["_id"] = item_id
    return payload


def fetch_many(fetcher, ids: list[int], max_workers: int = 8) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not ids:
        return results
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(fetcher, item_id): item_id for item_id in ids}
        for future in as_completed(future_map):
            results.append(future.result())
    return results


def member_photo_basename(member_id: int) -> str:
    return f"member_{member_id}"


def photo_extension_from_url(url: str | None) -> str | None:
    if not url:
        return None
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return suffix
    return None


def photo_extension_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    value = content_type.split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    return mapping.get(value)


def local_photo_path(member_id: int, extension: str) -> Path:
    return PHOTOS_DIR / f"{member_photo_basename(member_id)}{extension}"


def existing_photo_file_from_row(member_id: int, row: dict[str, Any]) -> Path | None:
    relative_path = row.get("photo_local_path")
    if relative_path and pd.notna(relative_path):
        candidate = ROOT_DIR / str(relative_path)
        if candidate.exists():
            return candidate
    matches = sorted(PHOTOS_DIR.glob(f"{member_photo_basename(member_id)}.*"))
    return matches[0] if matches else None


def sync_member_photo(session: requests.Session, member_id: int, source_url: str | None, existing_row: dict[str, Any]) -> dict[str, Any]:
    normalized_source_url = normalize_photo_url(source_url)
    existing_file = existing_photo_file_from_row(member_id, existing_row)
    existing_source = existing_row.get("photo_source_url")
    existing_downloaded_at = existing_row.get("photo_last_downloaded_at")
    age_days = days_since_iso(existing_downloaded_at)

    if not normalized_source_url:
        return {
            "photo_source_url": None,
            "photo_local_path": str(existing_file.relative_to(ROOT_DIR)) if existing_file else None,
            "photo_last_downloaded_at": existing_downloaded_at if existing_file else None,
            "photo_download_status": "missing_source",
        }

    should_refresh = (
        existing_file is None
        or existing_source != normalized_source_url
        or age_days is None
        or age_days >= PHOTO_REFRESH_DAYS
    )
    if not should_refresh and existing_file:
        return {
            "photo_source_url": normalized_source_url,
            "photo_local_path": str(existing_file.relative_to(ROOT_DIR)),
            "photo_last_downloaded_at": existing_downloaded_at,
            "photo_download_status": "cached",
        }

    try:
        response = session.get(normalized_source_url, timeout=45)
        response.raise_for_status()
        extension = photo_extension_from_content_type(response.headers.get("Content-Type")) or photo_extension_from_url(
            normalized_source_url
        )
        if not extension:
            extension = ".jpg"
        destination = local_photo_path(member_id, extension)
        for candidate in PHOTOS_DIR.glob(f"{member_photo_basename(member_id)}.*"):
            if candidate != destination and candidate.exists():
                candidate.unlink()
        destination.write_bytes(response.content)
        downloaded_at = iso_now()
        return {
            "photo_source_url": normalized_source_url,
            "photo_local_path": str(destination.relative_to(ROOT_DIR)),
            "photo_last_downloaded_at": downloaded_at,
            "photo_download_status": "downloaded",
        }
    except requests.RequestException:
        return {
            "photo_source_url": normalized_source_url,
            "photo_local_path": str(existing_file.relative_to(ROOT_DIR)) if existing_file else None,
            "photo_last_downloaded_at": existing_downloaded_at if existing_file else None,
            "photo_download_status": "failed_cached" if existing_file else "failed",
        }


def sync_member_photos(
    session: requests.Session, details: list[dict[str, Any]], existing_members: pd.DataFrame
) -> dict[int, dict[str, Any]]:
    existing_by_id = {}
    if not existing_members.empty and "member_id" in existing_members.columns:
        existing_by_id = {
            int(row["member_id"]): row
            for row in existing_members.to_dict(orient="records")
            if row.get("member_id") is not None
        }

    metadata_by_id: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {
            executor.submit(
                sync_member_photo,
                session,
                int(detail["id"]),
                detail.get("fotowebpath"),
                existing_by_id.get(int(detail["id"]), {}),
            ): int(detail["id"])
            for detail in details
            if detail.get("id") is not None
        }
        for future in as_completed(future_map):
            metadata_by_id[future_map[future]] = future.result()
    return metadata_by_id


def normalize_member_api_payloads(details: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "member_id": int(detail["id"]),
            "payload_json": json.dumps(detail, ensure_ascii=False),
        }
        for detail in details
        if detail.get("id") is not None
    ]
    return pd.DataFrame(rows)


def normalize_members(
    details: list[dict[str, Any]], current_list: list[dict[str, Any]], photo_metadata_by_id: dict[int, dict[str, Any]]
) -> dict[str, pd.DataFrame]:
    current_by_id = {int(item["id"]): item for item in current_list if item.get("id")}

    members: list[dict[str, Any]] = []
    memberships: list[dict[str, Any]] = []
    vp_mandates: list[dict[str, Any]] = []
    vp_other_mandates: list[dict[str, Any]] = []
    other_mandates: list[dict[str, Any]] = []
    attendance_rows: list[dict[str, Any]] = []
    websites_rows: list[dict[str, Any]] = []
    email_rows: list[dict[str, Any]] = []
    education_rows: list[dict[str, Any]] = []
    professions_rows: list[dict[str, Any]] = []
    interests_rows: list[dict[str, Any]] = []
    functions_rows: list[dict[str, Any]] = []
    honors_rows: list[dict[str, Any]] = []

    for detail in details:
        member_id = int(detail["id"])
        current_item = current_by_id.get(member_id, {})
        current_party = detail.get("huidigefractie") or current_item.get("fractie") or {}
        websites = detail.get("website", [])
        office_address = detail.get("kantooradres")
        domicile_address = detail.get("domicillieadres")
        second_office_address = detail.get("tweedekantooradres")
        photo_metadata = photo_metadata_by_id.get(member_id, {})

        members.append(
            {
                "member_id": member_id,
                "voornaam": detail.get("voornaam"),
                "naam": detail.get("naam"),
                "volledige_naam": person_name(detail),
                "geslacht": detail.get("geslacht"),
                "geboortedatum": detail.get("geboortedatum"),
                "geboorteplaats": detail.get("geboorteplaats"),
                "kieskring": detail.get("kieskring"),
                "zetel": current_item.get("zetel"),
                "deelstaatsenator": detail.get("deelstaatsenator"),
                "is_huidige_vv": detail.get("is-huidige-vv"),
                "self_opendata_url": first_link_href(current_item.get("link", []), rel="self"),
                "fractie_naam": current_party.get("naam"),
                "fractie_kleur": current_party.get("kleur"),
                "fractie_id": current_party.get("id"),
                "fractie_logo_url": normalize_photo_url(current_party.get("logo")),
                "fractie_volgnr": current_party.get("volgnr"),
                "fractie_zetel_aantal": current_party.get("zetel-aantal"),
                "email": flatten_list(detail.get("email", [])),
                "gsm": detail.get("gsmnr"),
                "overlijdensdatum": detail.get("overlijdensdatum"),
                "disclaimer": detail.get("disclaimer"),
                "website": json_text(websites),
                "website_officieel": first_website_by_type(websites, "Website"),
                "website_facebook": first_website_by_type(websites, "Facebook"),
                "website_twitter": first_website_by_type(websites, "Twitter"),
                "fotowebpath": normalize_photo_url(detail.get("fotowebpath")),
                "photo_source_url": photo_metadata.get("photo_source_url"),
                "photo_local_path": photo_metadata.get("photo_local_path"),
                "photo_last_downloaded_at": photo_metadata.get("photo_last_downloaded_at"),
                "photo_download_status": photo_metadata.get("photo_download_status"),
                **address_parts(office_address, "kantoor"),
                **address_parts(domicile_address, "domicilie"),
                **address_parts(second_office_address, "tweedekantoor"),
            }
        )

        for membership in detail.get("lidmaatschap", []):
            fraction = membership.get("fractie", {})
            memberships.append(
                {
                    "member_id": member_id,
                    "datum_van": membership.get("datumVan"),
                    "datum_tot": membership.get("datumTot"),
                    "fractie_id": fraction.get("id"),
                    "fractie_naam": fraction.get("naam"),
                    "fractie_kleur": fraction.get("kleur"),
                }
            )

        for mandate_group in detail.get("mandaat-vlaams-parlement", []):
            for function in mandate_group.get("completepersoonsfunctie", []):
                committee = function.get("commissie", {})
                vp_mandates.append(
                    {
                        "member_id": member_id,
                        "belangrijk_mandaat": mandate_group.get("belangrijkmandaat"),
                        "titel": function.get("titel"),
                        "omschrijving": function.get("omschrijving"),
                        "datum_van": function.get("datumvan"),
                        "datum_tot": function.get("datumtot"),
                        "commissie_id": committee.get("id"),
                        "commissie_afkorting": committee.get("afkorting"),
                        "commissie_titel": committee.get("titel"),
                }
            )

        for mandate_group in detail.get("mandaat-vlaams-parlement-andere", []):
            for mandate in mandate_group.get("parlmandaat", []):
                vp_other_mandates.append(
                    {
                        "member_id": member_id,
                        "mandaatgroep": mandate_group.get("mandaatgroepnaam"),
                        "mandaat": mandate.get("mandaat"),
                        "belangrijk_mandaat": mandate.get("belangrijkmandaat"),
                        "datum_van": mandate.get("datumvan"),
                        "datum_tot": mandate.get("datumtot"),
                    }
                )

        for group in detail.get("mandaat-andere", []):
            for mandate in group.get("parlmandaat", []):
                other_mandates.append(
                    {
                        "member_id": member_id,
                        "mandaatgroep": group.get("mandaatgroepnaam"),
                        "mandaat": mandate.get("mandaat"),
                        "belangrijk_mandaat": mandate.get("belangrijkmandaat"),
                        "datum_van": mandate.get("datumvan"),
                        "datum_tot": mandate.get("datumtot"),
                    }
                )

        for website in websites:
            websites_rows.append(
                {
                    "member_id": member_id,
                    "soort": website.get("soort"),
                    "url": website.get("value"),
                }
            )

        for rank, email in enumerate(normalize_text_list(detail.get("email")), start=1):
            email_rows.append(
                {
                    "member_id": member_id,
                    "volgorde": rank,
                    "email": email,
                }
            )

        for rank, education in enumerate(normalize_text_list(detail.get("opleiding")), start=1):
            education_rows.append(
                {
                    "member_id": member_id,
                    "volgorde": rank,
                    "opleiding": education,
                }
            )

        for profession in detail.get("beroep", []):
            professions_rows.append(
                {
                    "member_id": member_id,
                    "titel": profession.get("titel"),
                    "werkgever": profession.get("werkgever"),
                    "datum_van": profession.get("datumvan"),
                    "datum_tot": profession.get("datumtot"),
                    "datum_van_formaat": profession.get("datumvanformaat"),
                    "datum_tot_formaat": profession.get("datumtotformaat"),
                }
            )

        for interest in detail.get("interesse", []):
            if isinstance(interest, dict):
                interests_rows.append(
                    {
                        "member_id": member_id,
                        "interesse": interest.get("interesse"),
                        "volgorde": interest.get("volgorde"),
                    }
                )
            else:
                interests_rows.append(
                    {
                        "member_id": member_id,
                        "interesse": str(interest),
                        "volgorde": None,
                    }
                )

        for function in detail.get("functie", []):
            if isinstance(function, dict):
                functions_rows.append(
                    {
                        "member_id": member_id,
                        "omschrijving": function.get("omschrijving"),
                        "start_datum": function.get("startdatum"),
                        "eind_datum": function.get("einddatum"),
                        "start_datum_formaat": function.get("startdatumformaat"),
                        "eind_datum_formaat": function.get("einddatumformaat"),
                    }
                )
            else:
                functions_rows.append(
                    {
                        "member_id": member_id,
                        "omschrijving": str(function),
                        "start_datum": None,
                        "eind_datum": None,
                        "start_datum_formaat": None,
                        "eind_datum_formaat": None,
                    }
                )

        for honor in detail.get("ereteken", []):
            if isinstance(honor, dict):
                honors_rows.append(
                    {
                        "member_id": member_id,
                        "titel": honor.get("titel"),
                    }
                )
            else:
                honors_rows.append(
                    {
                        "member_id": member_id,
                        "titel": str(honor),
                    }
                )

        attendance = detail.get("aanwezigheden-huidige-legislatuur", {})
        plenary = attendance.get("plenaire-aanw", {})
        if plenary:
            attendance_rows.append(
                {
                    "member_id": member_id,
                    "scope": "plenaire",
                    "committee_id": None,
                    "committee_name": None,
                    "role": None,
                    "aanwezig": plenary.get("aanwezig"),
                    "afwezig": plenary.get("afwezig"),
                    "verontschuldigd": plenary.get("verontschuldigd"),
                }
            )
        for committee_attendance in attendance.get("commissie-aanw", []):
            committee = committee_attendance.get("commissie", {})
            for role_name, values in committee_attendance.items():
                if role_name == "commissie":
                    continue
                attendance_rows.append(
                    {
                        "member_id": member_id,
                        "scope": "commissie",
                        "committee_id": committee.get("id"),
                        "committee_name": committee.get("titel"),
                        "role": role_name,
                        "aanwezig": values.get("aanwezig"),
                        "afwezig": values.get("afwezig"),
                        "verontschuldigd": values.get("verontschuldigd"),
                    }
                )

    return {
        "members": pd.DataFrame(members).sort_values("volledige_naam"),
        "member_memberships": pd.DataFrame(memberships),
        "member_mandates_vp": pd.DataFrame(vp_mandates),
        "member_mandates_vp_other": pd.DataFrame(vp_other_mandates),
        "member_mandates_other": pd.DataFrame(other_mandates),
        "member_attendance": pd.DataFrame(attendance_rows),
        "member_websites": pd.DataFrame(websites_rows),
        "member_emails": pd.DataFrame(email_rows),
        "member_education": pd.DataFrame(education_rows),
        "member_professions": pd.DataFrame(professions_rows),
        "member_interests": pd.DataFrame(interests_rows),
        "member_functions": pd.DataFrame(functions_rows),
        "member_honors": pd.DataFrame(honors_rows),
        "member_api_payloads": normalize_member_api_payloads(details),
    }


def normalize_written_questions(details: list[dict[str, Any]], discovery_rows: pd.DataFrame) -> pd.DataFrame:
    discovery_by_id = {
        int(row["id"]): row for row in discovery_rows.to_dict(orient="records") if row.get("id") is not None
    }
    rows: list[dict[str, Any]] = []
    for detail in details:
        question_id = int(detail["id"])
        discovery = discovery_by_id.get(question_id, {})
        questioner = detail.get("vraagsteller", {})
        minister = detail.get("minister", {})
        rows.append(
            {
                "question_id": question_id,
                "vraagnummer": detail.get("vraagnummer"),
                "titel": detail.get("titel"),
                "onderwerp": detail.get("onderwerp"),
                "zittingsjaar": detail.get("zittingsjaar"),
                "soort_antwoord": detail.get("soort-antwoord"),
                "tijdig": detail.get("tijdig"),
                "thema": json.dumps(detail.get("thema", []), ensure_ascii=False),
                "vraagsteller_id": questioner.get("id"),
                "vraagsteller_naam": person_name(questioner),
                "minister_id": minister.get("id"),
                "minister_naam": person_name(minister),
                "publicatiedatum": discovery.get("publicatiedatum"),
                "status": discovery.get("status"),
                "displayurl": discovery.get("displayurl"),
                "opendata_url": discovery.get("opendata_url"),
                "document_url": next((item.get("URL") for item in detail.get("bestand-ordered", []) if item.get("URL")), None),
                "procedure_verloop_json": json.dumps(detail.get("procedureverloop", []), ensure_ascii=False),
            }
        )
    return pd.DataFrame(rows).sort_values(["publicatiedatum", "question_id"], ascending=[False, False])


def normalize_oral_items(details: list[dict[str, Any]], discovery_rows: pd.DataFrame) -> pd.DataFrame:
    discovery_by_id = {
        int(row["id"]): row for row in discovery_rows.to_dict(orient="records") if row.get("id") is not None
    }
    rows: list[dict[str, Any]] = []
    for detail in details:
        item_id = int(detail.get("id") or detail.get("_id"))
        discovery = discovery_by_id.get(item_id, {})
        contacts = detail.get("contacttype", [])
        askers = []
        ministers = []
        for contact_block in contacts:
            description = (contact_block.get("beschrijving") or "").lower()
            names = [person_name(person) for person in contact_block.get("contact", [])]
            if "vraagsteller" in description or "interpellant" in description:
                askers.extend(name for name in names if name)
            if "minister" in description:
                ministers.extend(name for name in names if name)
        committee = detail.get("commissie", {})
        rows.append(
            {
                "oral_item_id": item_id,
                "nummer": detail.get("nummer"),
                "titel": detail.get("titel"),
                "onderwerp": detail.get("onderwerp"),
                "objectstatus": detail.get("objectstatus"),
                "objecttype": (detail.get("objecttype") or {}).get("naam"),
                "zittingsjaar": detail.get("zittingsjaar"),
                "commissie_id": committee.get("id"),
                "commissie_naam": committee.get("titel"),
                "vraagstellers": flatten_list(askers),
                "ministers": flatten_list(ministers),
                "publicatiedatum": discovery.get("publicatiedatum"),
                "status": discovery.get("status"),
                "displayurl": discovery.get("displayurl"),
                "opendata_url": discovery.get("opendata_url"),
                "procedure_verloop_json": json.dumps(detail.get("procedureverloop", []), ensure_ascii=False),
            }
        )
    return pd.DataFrame(rows).sort_values(["publicatiedatum", "oral_item_id"], ascending=[False, False])


def normalize_fractions(fraction_items: list[dict[str, Any]]) -> dict[str, pd.DataFrame]:
    fraction_rows: list[dict[str, Any]] = []
    fraction_member_rows: list[dict[str, Any]] = []
    payload_rows: list[dict[str, Any]] = []

    for item in fraction_items:
        block = item.get("fractielijst", {})
        fraction = block.get("fractie", {})
        members = block.get("volksvertegenwoordiger", [])
        fraction_id = fraction.get("id")
        if not fraction_id:
            continue

        fraction_rows.append(
            {
                "fractie_id": int(fraction_id),
                "fractie_naam": fraction.get("naam"),
                "fractie_kleur": fraction.get("kleur"),
                "fractie_logo_url": normalize_photo_url(fraction.get("logo")),
                "fractie_volgnr": fraction.get("volgnr"),
                "fractie_zetel_aantal": fraction.get("zetel-aantal"),
            }
        )
        payload_rows.append(
            {
                "fractie_id": int(fraction_id),
                "payload_json": json.dumps(block, ensure_ascii=False),
            }
        )

        for member in members:
            fraction_member_rows.append(
                {
                    "fractie_id": int(fraction_id),
                    "member_id": int(member["id"]),
                    "volledige_naam": person_name(member),
                    "voornaam": member.get("voornaam"),
                    "naam": member.get("naam"),
                    "kieskring": member.get("kieskring"),
                    "zetel": member.get("zetel"),
                    "deelstaatsenator": member.get("deelstaatsenator"),
                    "is_huidige_vv": member.get("is-huidige-vv"),
                    "self_opendata_url": first_link_href(member.get("link", []), rel="self"),
                    "fotowebpath": normalize_photo_url(member.get("fotowebpath")),
                }
            )

    return {
        "fractions": pd.DataFrame(fraction_rows).drop_duplicates(subset=["fractie_id"], keep="last"),
        "fraction_members": pd.DataFrame(fraction_member_rows),
        "fraction_api_payloads": pd.DataFrame(payload_rows).drop_duplicates(subset=["fractie_id"], keep="last"),
    }


def normalize_committees(committee_details: list[dict[str, Any]]) -> dict[str, pd.DataFrame]:
    committee_rows: list[dict[str, Any]] = []
    secretary_rows: list[dict[str, Any]] = []
    membership_rows: list[dict[str, Any]] = []
    payload_rows: list[dict[str, Any]] = []

    for detail in committee_details:
        committee_id = detail.get("id")
        if not committee_id:
            continue

        committee_rows.append(
            {
                "committee_id": int(committee_id),
                "committee_name": detail.get("naam"),
                "committee_code": detail.get("afkorting"),
                "datum_van": detail.get("datumvan"),
                "datum_van_samenstelling": detail.get("datum-van-samenstelling"),
                "ministers": detail.get("ministers"),
                "disclaimer": detail.get("disclaimer"),
            }
        )
        payload_rows.append(
            {
                "committee_id": int(committee_id),
                "payload_json": json.dumps(detail, ensure_ascii=False),
            }
        )

        for secretary in detail.get("commissiesecretaris", []):
            secretary_rows.append(
                {
                    "committee_id": int(committee_id),
                    "person_id": secretary.get("id"),
                    "aanspreking": secretary.get("aanspreking"),
                    "voornaam": secretary.get("voornaam"),
                    "naam": secretary.get("naam"),
                    "email": flatten_list(secretary.get("email", []))
                    if isinstance(secretary.get("email"), list)
                    else secretary.get("email"),
                    "telefoon": flatten_list(secretary.get("telnr", [])),
                }
            )

        for function in detail.get("functie", []):
            role_name = function.get("naam")
            for member in function.get("lid", []):
                fraction = member.get("fractie", {})
                membership_rows.append(
                    {
                        "committee_id": int(committee_id),
                        "committee_name": detail.get("naam"),
                        "role_name": role_name,
                        "member_id": member.get("id"),
                        "member_name": person_name(member),
                        "aanspreking": member.get("aanspreking"),
                        "fractie_id": fraction.get("id"),
                        "fractie_naam": fraction.get("naam"),
                        "fractie_kleur": fraction.get("kleur"),
                        "fractie_logo_url": normalize_photo_url(fraction.get("logo")),
                        "is_huidige_vv": member.get("is-huidige-vv"),
                        "self_opendata_url": first_link_href(member.get("link", []), rel="self"),
                        "fotowebpath": normalize_photo_url(member.get("fotowebpath")),
                    }
                )

    return {
        "committees": pd.DataFrame(committee_rows).drop_duplicates(subset=["committee_id"], keep="last"),
        "committee_secretaries": pd.DataFrame(secretary_rows),
        "committee_memberships": pd.DataFrame(membership_rows),
        "committee_api_payloads": pd.DataFrame(payload_rows).drop_duplicates(subset=["committee_id"], keep="last"),
    }


def normalize_meetings(
    meeting_items: list[dict[str, Any]],
    agenda_payloads_by_id: dict[int, dict[str, Any]],
    proceedings_payloads_by_id: dict[int, dict[str, Any]],
) -> dict[str, pd.DataFrame]:
    meeting_rows: list[dict[str, Any]] = []
    meeting_committee_rows: list[dict[str, Any]] = []
    meeting_attribute_rows: list[dict[str, Any]] = []
    agenda_item_rows: list[dict[str, Any]] = []
    agenda_line_rows: list[dict[str, Any]] = []
    agenda_reference_rows: list[dict[str, Any]] = []
    proceeding_line_rows: list[dict[str, Any]] = []
    proceeding_reference_rows: list[dict[str, Any]] = []
    text_rows: list[dict[str, Any]] = []

    def append_text_reference(source: str, meeting_id: int, line_id: str, item: dict[str, Any]) -> None:
        text_id = item.get("id")
        if not text_id:
            return
        document = item.get("document", {})
        object_type = item.get("objecttype", {})
        text_rows.append(
            {
                "text_id": int(text_id),
                "meeting_id": meeting_id,
                "source": source,
                "line_id": line_id,
                "nummer": item.get("nummer"),
                "volgnr": item.get("volgnr"),
                "titel": item.get("titel"),
                "onderwerp": item.get("onderwerp"),
                "objecttype": object_type.get("naam"),
                "zittingsjaar": item.get("zittingsjaar"),
                "materie": item.get("materie"),
                "document_bestandsnaam": document.get("bestandsnaam"),
                "document_doel": document.get("doel"),
                "document_titel": document.get("titel"),
                "document_url": document.get("url") or item.get("filewebpath"),
                "opendata_url": first_link_href(item.get("link", []), rel="self"),
            }
        )

    def append_reference_rows(
        *,
        source: str,
        meeting_id: int,
        line_id: str,
        title: str | None,
        block_name: str,
        items: list[dict[str, Any]],
    ) -> None:
        for position, item in enumerate(items, start=1):
            object_type = item.get("objecttype", {})
            agenda_reference_rows_target = agenda_reference_rows if source == "agenda" else proceeding_reference_rows
            agenda_reference_rows_target.append(
                {
                    "meeting_id": meeting_id,
                    "line_id": line_id,
                    "line_title": title,
                    "source": source,
                    "reference_group": block_name,
                    "reference_position": position,
                    "reference_id": item.get("id"),
                    "reference_nummer": item.get("nummer"),
                    "reference_titel": item.get("titel"),
                    "reference_onderwerp": item.get("onderwerp"),
                    "reference_status": item.get("objectstatus"),
                    "reference_objecttype": object_type.get("naam"),
                    "reference_zittingsjaar": item.get("zittingsjaar"),
                    "reference_opendata_url": first_link_href(item.get("link", []), rel="self"),
                    "reference_document_url": (item.get("document") or {}).get("url") or item.get("filewebpath"),
                }
            )
            if block_name == "parlementair-initiatief":
                append_text_reference(source, meeting_id, line_id, item)

    for meeting_item in meeting_items:
        meeting = meeting_item.get("vergadering", {})
        meeting_id = meeting.get("id")
        if not meeting_id:
            continue
        meeting_id = int(meeting_id)
        chair = meeting.get("voorzitter", {})
        meeting_rows.append(
            {
                "meeting_id": meeting_id,
                "status": meeting.get("status"),
                "type": meeting.get("type"),
                "subtype": meeting.get("subtype"),
                "agenda_gewijzigd": meeting.get("agenda-gewijzigd"),
                "agenda_versie": meeting.get("agenda-versie"),
                "besloten_vergadering": meeting.get("besloten-vergadering"),
                "datum_agendering": meeting.get("datumagendering"),
                "datum_begin": meeting.get("datumbegin"),
                "datum_einde": meeting.get("datumeinde"),
                "laatste_wijziging": meeting.get("laatste-wijziging"),
                "vergadering_met_verslag": meeting.get("vergadering-met-verslag"),
                "uses_beknopt_verslag": meeting.get("uses-beknopt-verslag"),
                "uses_webhandelingen": meeting.get("uses-webhandelingen"),
                "voorlopig_verslag": meeting.get("voorlopig-verslag"),
                "vergaderingnummer": meeting.get("vergaderingnummer"),
                "omschrijving_kort": flatten_list(meeting.get("omschrijving-kort", [])),
                "omschrijving_preview": strip_html(meeting.get("omschrijving")),
                "video_youtube_id": meeting.get("video-youtube-id"),
                "vergaderzaal_naam": (meeting.get("vergaderzaal") or {}).get("naam"),
                "vergaderzaal_verdieping": (meeting.get("vergaderzaal") or {}).get("verdieping"),
                "chair_member_id": chair.get("id"),
                "chair_name": person_name(chair),
                "chair_fraction_name": (chair.get("fractie") or {}).get("naam"),
                "agenda_url": first_link_href(meeting.get("link", []), rel="agenda"),
                "self_opendata_url": first_link_href(meeting.get("link", []), rel="self"),
                "handelingen_url": first_link_href(meeting.get("link", []), rel="handelingen"),
            }
        )

        for committee in meeting.get("commissie", []):
            meeting_committee_rows.append(
                {
                    "meeting_id": meeting_id,
                    "committee_id": committee.get("id"),
                    "committee_code": committee.get("afkorting"),
                    "committee_name": committee.get("titel"),
                    "committee_opendata_url": first_link_href(committee.get("link", []), rel="self"),
                }
            )

        for attribute in meeting.get("attribuut", []):
            meeting_attribute_rows.append(
                {
                    "meeting_id": meeting_id,
                    "attribute_name": attribute.get("naam"),
                    "attribute_value": attribute.get("waarde"),
                }
            )

        agenda_payload = agenda_payloads_by_id.get(meeting_id, {})
        for agenda_item_index, agenda_item in enumerate(agenda_payload.get("agenda-item", []), start=1):
            agenda_item_id = f"{meeting_id}_item_{agenda_item_index}"
            agenda_item_rows.append(
                {
                    "agenda_item_id": agenda_item_id,
                    "meeting_id": meeting_id,
                    "agenda_item_index": agenda_item_index,
                    "heeft_1_titel": agenda_item.get("heeft-1-titel"),
                    "heeft_gemeenschappelijke_sprekers": agenda_item.get("heeft-gemeenschappelijke-sprekers"),
                    "heeft_gemeenschappelijke_verslaggevers": agenda_item.get("heeft-gemeenschappelijke-verslaggevers"),
                    "opmaak": agenda_item.get("opmaak"),
                }
            )

            for line_index, line in enumerate(agenda_item.get("agenda-lijn", []), start=1):
                line_id = f"{agenda_item_id}_line_{line_index}"
                line_type = line.get("agenda-lijn-type", {})
                agenda_line_rows.append(
                    {
                        "agenda_line_id": line_id,
                        "agenda_item_id": agenda_item_id,
                        "meeting_id": meeting_id,
                        "line_index": line_index,
                        "line_type": line_type.get("naam"),
                        "title_html": line.get("titel"),
                        "title_text": strip_html(line.get("titel")),
                        "vet": line.get("vet"),
                    }
                )

                for block_name in [
                    "vrageninterpellatie",
                    "parlementair-initiatief",
                    "debat",
                    "gedachtewisseling",
                    "verzoekschrift",
                ]:
                    append_reference_rows(
                        source="agenda",
                        meeting_id=meeting_id,
                        line_id=line_id,
                        title=strip_html(line.get("titel")),
                        block_name=block_name,
                        items=line.get(block_name, []),
                    )

        proceedings_payload = proceedings_payloads_by_id.get(meeting_id, {})
        for line_index, line in enumerate(proceedings_payload.get("journaallijn", []), start=1):
            line_id = f"{meeting_id}_proc_{line.get('id') or line_index}"
            proceeding_line_rows.append(
                {
                    "proceeding_line_id": line_id,
                    "meeting_id": meeting_id,
                    "journaallijn_id": line.get("id"),
                    "line_index": line_index,
                    "datum": line.get("datum"),
                    "title_html": line.get("titel"),
                    "title_text": strip_html(line.get("titel")),
                    "titel_samenstelling": line.get("titel-samenstelling"),
                    "line_opendata_url": first_link_href(line.get("link", []), rel="self"),
                }
            )

            for block_name in [
                "vrageninterpellatie",
                "parlementair-initiatief",
                "debat",
                "gedachtewisseling",
                "verzoekschrift",
            ]:
                append_reference_rows(
                    source="proceeding",
                    meeting_id=meeting_id,
                    line_id=line_id,
                    title=strip_html(line.get("titel")),
                    block_name=block_name,
                    items=line.get(block_name, []),
                )

    return {
        "meetings": pd.DataFrame(meeting_rows).drop_duplicates(subset=["meeting_id"], keep="last"),
        "meeting_committees": pd.DataFrame(meeting_committee_rows),
        "meeting_attributes": pd.DataFrame(meeting_attribute_rows),
        "agenda_items": pd.DataFrame(agenda_item_rows),
        "agenda_lines": pd.DataFrame(agenda_line_rows),
        "agenda_line_references": pd.DataFrame(agenda_reference_rows),
        "proceeding_lines": pd.DataFrame(proceeding_line_rows),
        "proceeding_line_references": pd.DataFrame(proceeding_reference_rows),
        "parliamentary_texts": pd.DataFrame(text_rows).drop_duplicates(subset=["text_id"], keep="last"),
    }


def build_member_activity_links(
    members: pd.DataFrame,
    written_questions: pd.DataFrame,
    oral_items: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    written_links: list[dict[str, Any]] = []
    oral_links: list[dict[str, Any]] = []
    member_id_by_name = {}
    if not members.empty:
        for row in members[["member_id", "volledige_naam"]].dropna().to_dict(orient="records"):
            member_id_by_name[str(row["volledige_naam"]).strip()] = int(row["member_id"])

    if not written_questions.empty:
        for row in written_questions.to_dict(orient="records"):
            if pd.notna(row.get("vraagsteller_id")):
                written_links.append(
                    {
                        "member_id": int(row["vraagsteller_id"]),
                        "question_id": int(row["question_id"]),
                        "role": "vraagsteller",
                        "publicatiedatum": row.get("publicatiedatum"),
                        "onderwerp": row.get("onderwerp"),
                    }
                )
            if pd.notna(row.get("minister_id")):
                written_links.append(
                    {
                        "member_id": int(row["minister_id"]),
                        "question_id": int(row["question_id"]),
                        "role": "minister",
                        "publicatiedatum": row.get("publicatiedatum"),
                        "onderwerp": row.get("onderwerp"),
                    }
                )

    if not oral_items.empty:
        for row in oral_items.to_dict(orient="records"):
            if row.get("vraagstellers"):
                for name in [part.strip() for part in str(row["vraagstellers"]).split("|") if part.strip()]:
                    oral_links.append(
                        {
                            "member_id": member_id_by_name.get(name),
                            "member_name": name,
                            "oral_item_id": int(row["oral_item_id"]),
                            "role": "vraagsteller",
                            "publicatiedatum": row.get("publicatiedatum"),
                            "onderwerp": row.get("onderwerp"),
                        }
                    )
            if row.get("ministers"):
                for name in [part.strip() for part in str(row["ministers"]).split("|") if part.strip()]:
                    oral_links.append(
                        {
                            "member_id": member_id_by_name.get(name),
                            "member_name": name,
                            "oral_item_id": int(row["oral_item_id"]),
                            "role": "minister",
                            "publicatiedatum": row.get("publicatiedatum"),
                            "onderwerp": row.get("onderwerp"),
                        }
                    )

    return {
        "member_written_question_links": pd.DataFrame(written_links),
        "member_oral_item_links": pd.DataFrame(oral_links),
    }


def merge_upsert(existing: pd.DataFrame, fresh: pd.DataFrame, key: str) -> pd.DataFrame:
    if fresh.empty:
        return existing.copy() if not existing.empty else fresh
    if existing.empty:
        return fresh.drop_duplicates(subset=[key], keep="last")
    combined = pd.concat([existing, fresh], ignore_index=True)
    return combined.drop_duplicates(subset=[key], keep="last")


def replace_scope(existing: pd.DataFrame, fresh: pd.DataFrame, scope_key: str) -> pd.DataFrame:
    if fresh.empty:
        return existing.copy() if not existing.empty else fresh
    if existing.empty or scope_key not in existing.columns or scope_key not in fresh.columns:
        return fresh.copy()
    scoped_values = set(value for value in fresh[scope_key].dropna().tolist())
    if not scoped_values:
        return fresh.copy()
    remaining = existing[~existing[scope_key].isin(scoped_values)].copy()
    return pd.concat([remaining, fresh], ignore_index=True)


def export_workbook(tables: dict[str, pd.DataFrame]) -> Path:
    preferred_path = PUBLISHED_DIR / "vlaams_parlement_data.xlsx"
    candidate_paths = [preferred_path]
    timestamped = PUBLISHED_DIR / f"vlaams_parlement_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    candidate_paths.append(timestamped)

    last_error: Exception | None = None
    for workbook_path in candidate_paths:
        try:
            with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
                for sheet_name, frame in tables.items():
                    output = frame.copy()
                    if output.empty:
                        output = pd.DataFrame(columns=frame.columns)
                    output.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            return workbook_path
        except PermissionError as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error
    raise RuntimeError("Workbook export failed unexpectedly.")


def sync_all(
    bootstrap_since: date | None = None,
    rolling_days: int = DEFAULT_ROLLING_UPDATE_DAYS,
    max_pages: int = DEFAULT_MAX_SEARCH_PAGES,
    force_full_refresh: bool = False,
) -> dict[str, Any]:
    ensure_directories()
    state_path = STATE_DIR / "sync_state.json"
    state = read_json(state_path, default={})
    client = VlaamsParlementClient.create()
    today = date.today()

    if bootstrap_since is None:
        bootstrap_since = bootstrap_since_date(today)

    state_last = state.get("last_successful_sync")
    if force_full_refresh or not state_last:
        since_date = bootstrap_since
    else:
        parsed = parse_iso_date(state_last)
        since_date = bootstrap_since if not parsed else max(
            bootstrap_since,
            parsed - timedelta(days=rolling_days),
        )

    active_store = current_store_dir(state)
    existing_members = load_csv("members", store_dir=active_store)
    existing_meetings = load_csv("meetings", store_dir=active_store)
    existing_meeting_committees = load_csv("meeting_committees", store_dir=active_store)
    existing_meeting_attributes = load_csv("meeting_attributes", store_dir=active_store)
    existing_agenda_items = load_csv("agenda_items", store_dir=active_store)
    existing_agenda_lines = load_csv("agenda_lines", store_dir=active_store)
    existing_agenda_references = load_csv("agenda_line_references", store_dir=active_store)
    existing_proceeding_lines = load_csv("proceeding_lines", store_dir=active_store)
    existing_proceeding_references = load_csv("proceeding_line_references", store_dir=active_store)
    existing_parliamentary_texts = load_csv("parliamentary_texts", store_dir=active_store)
    current_members = fetch_current_members(client)
    current_fractions = fetch_current_fractions(client)
    current_committees = fetch_current_committees(client)
    member_ids = [int(member["id"]) for member in current_members if member.get("id")]
    committee_ids = [int(committee["id"]) for committee in current_committees if committee.get("id")]
    member_details = fetch_many(lambda item_id: fetch_member_detail(client, item_id), member_ids, max_workers=10)
    committee_details = fetch_many(lambda item_id: fetch_committee_detail(client, item_id), committee_ids, max_workers=6)
    member_photo_metadata = sync_member_photos(client.session, member_details, existing_members)
    member_tables = normalize_members(member_details, current_members, member_photo_metadata)
    fraction_tables = normalize_fractions(current_fractions)
    committee_tables = normalize_committees(committee_details)
    meetings_end_date = today + timedelta(days=MEETING_LOOKAHEAD_DAYS)
    meeting_items = discover_meetings_via_date_ranges(client, since_date, meetings_end_date)
    meeting_ids = sorted(
        {
            int(item.get("vergadering", {}).get("id"))
            for item in meeting_items
            if item.get("vergadering", {}).get("id") is not None
        }
    )
    agenda_payloads = fetch_many(
        lambda item_id: {"_meeting_id": item_id, **fetch_meeting_agenda(client, item_id)},
        meeting_ids,
        max_workers=8,
    )
    proceedings_payloads: list[dict[str, Any]] = []
    meeting_tables = normalize_meetings(
        meeting_items,
        {int(payload["_meeting_id"]): payload for payload in agenda_payloads} if agenda_payloads else {},
        {int(payload["_meeting_id"]): payload for payload in proceedings_payloads} if proceedings_payloads else {},
    )
    meeting_tables["meetings"] = replace_scope(existing_meetings, meeting_tables["meetings"], "meeting_id")
    meeting_tables["meeting_committees"] = replace_scope(
        existing_meeting_committees,
        meeting_tables["meeting_committees"],
        "meeting_id",
    )
    meeting_tables["meeting_attributes"] = replace_scope(
        existing_meeting_attributes,
        meeting_tables["meeting_attributes"],
        "meeting_id",
    )
    meeting_tables["agenda_items"] = replace_scope(existing_agenda_items, meeting_tables["agenda_items"], "meeting_id")
    meeting_tables["agenda_lines"] = replace_scope(existing_agenda_lines, meeting_tables["agenda_lines"], "meeting_id")
    meeting_tables["agenda_line_references"] = replace_scope(
        existing_agenda_references,
        meeting_tables["agenda_line_references"],
        "meeting_id",
    )
    meeting_tables["proceeding_lines"] = replace_scope(
        existing_proceeding_lines,
        meeting_tables["proceeding_lines"],
        "meeting_id",
    )
    meeting_tables["proceeding_line_references"] = replace_scope(
        existing_proceeding_references,
        meeting_tables["proceeding_line_references"],
        "meeting_id",
    )
    meeting_tables["parliamentary_texts"] = replace_scope(
        existing_parliamentary_texts,
        meeting_tables["parliamentary_texts"],
        "meeting_id",
    ).drop_duplicates(subset=["text_id"], keep="last")

    written_discovery = discover_documents_via_search(
        client=client,
        query="schriftelijke vraag",
        expected_soort="SCHV",
        since_date=since_date,
        max_pages=max_pages,
    )

    oral_discovery_search = []
    for query in ["vraag om uitleg", "interpellatie", "actuele vraag"]:
        oral_discovery_search.extend(
            discover_documents_via_search(
                client=client,
                query=query,
                expected_soort="VI",
                since_date=since_date,
                max_pages=max_pages,
            )
        )
    oral_discovery_committee = discover_oral_items_via_committees(client)

    written_discovery_df = pd.DataFrame(written_discovery)
    if written_discovery_df.empty:
        written_discovery_df = pd.DataFrame(columns=["id"])
    else:
        written_discovery_df = written_discovery_df.drop_duplicates(subset=["id"], keep="last")

    oral_discovery_df = pd.DataFrame(oral_discovery_search + oral_discovery_committee)
    if oral_discovery_df.empty:
        oral_discovery_df = pd.DataFrame(columns=["id"])
    else:
        oral_discovery_df = oral_discovery_df.drop_duplicates(subset=["id"], keep="last")

    existing_written = load_csv("written_questions", store_dir=active_store)
    existing_oral = load_csv("oral_items", store_dir=active_store)

    written_ids_to_refresh = set(written_discovery_df["id"].tolist()) if not written_discovery_df.empty else set()
    oral_ids_to_refresh = set(oral_discovery_df["id"].tolist()) if not oral_discovery_df.empty else set()

    written_details = fetch_many(
        lambda question_id: fetch_written_question_detail(client, question_id),
        sorted(written_ids_to_refresh),
        max_workers=10,
    )
    oral_details = fetch_many(
        lambda item_id: fetch_oral_item_detail(client, item_id),
        sorted(oral_ids_to_refresh),
        max_workers=10,
    )

    fresh_written = normalize_written_questions(written_details, written_discovery_df) if written_details else pd.DataFrame()
    fresh_oral = normalize_oral_items(oral_details, oral_discovery_df) if oral_details else pd.DataFrame()

    written_questions = merge_upsert(existing_written, fresh_written, key="question_id")
    oral_items = merge_upsert(existing_oral, fresh_oral, key="oral_item_id")
    activity_link_tables = build_member_activity_links(
        members=member_tables["members"],
        written_questions=written_questions,
        oral_items=oral_items,
    )

    discovery_log = pd.concat(
        [
            written_discovery_df.assign(document_type="SCHV"),
            oral_discovery_df.assign(document_type="VI"),
        ],
        ignore_index=True,
    )
    sync_log = pd.DataFrame(
        [
            {
                "synced_at": iso_now(),
                "bootstrap_since": bootstrap_since.isoformat(),
                "effective_since": since_date.isoformat(),
                "members": len(member_tables["members"]),
                "fractions": len(fraction_tables["fractions"]),
                "committees": len(committee_tables["committees"]),
                "meetings": len(meeting_tables["meetings"]),
                "member_photos_downloaded": sum(
                    1 for item in member_photo_metadata.values() if item.get("photo_download_status") == "downloaded"
                ),
                "written_questions_refreshed": len(written_ids_to_refresh),
                "oral_items_refreshed": len(oral_ids_to_refresh),
            }
        ]
    )

    tables = {
        **member_tables,
        **fraction_tables,
        **committee_tables,
        **meeting_tables,
        "written_questions": written_questions,
        "oral_items": oral_items,
        **activity_link_tables,
        "discovery_log": discovery_log,
        "sync_log": sync_log,
    }

    store_snapshot_dir = write_store_tables(tables)

    workbook_path = export_workbook(tables)

    state.update(
        {
            "last_successful_sync": today.isoformat(),
            "last_run_at": iso_now(),
            "bootstrap_since": bootstrap_since.isoformat(),
            "rolling_days": rolling_days,
            "current_store_dir": serialize_repo_path(store_snapshot_dir),
            "published_workbook": serialize_repo_path(workbook_path),
        }
    )
    write_json(state_path, state)

    return {
        "state": state,
        "tables": {name: len(frame) for name, frame in tables.items()},
        "workbook_path": str(workbook_path),
    }
