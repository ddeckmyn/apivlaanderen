import json
from typing import Any

import pandas as pd
import requests
import streamlit as st

OPENAPI_URL = "https://ws.vlpar.be/e/opendata/api-docs"
API_BASE_URL = "https://ws.vlpar.be/e/opendata"
SEARCH_API_BASE_URL = "https://ws.vlpar.be/api/search/query"

CURATED_ENDPOINTS = {
    "Huidige leden": {
        "path": "/vv/huidige",
        "params": {},
        "note": "Lijst van huidige Vlaamse volksvertegenwoordigers.",
    },
    "Lid detail": {
        "path": "/vv/{persoonId}",
        "params": {"persoonId": 4383, "lang": "nl"},
        "note": "Detailfiche van een lid, inclusief email, websites, mandaten en aanwezigheid.",
    },
    "Huidige leden per fractie": {
        "path": "/vv/huidige/perfractie",
        "params": {},
        "note": "Groepeert de huidige leden per fractie.",
    },
    "Huidige leden per kieskring": {
        "path": "/vv/huidige/perkieskring",
        "params": {},
        "note": "Groepeert de huidige leden per kieskring.",
    },
    "Adreslijst huidige leden": {
        "path": "/vv/adreslijst",
        "params": {},
        "note": "Contactgegevens van de huidige leden.",
    },
    "Schriftelijke vraag detail": {
        "path": "/schv/{idSCHV}",
        "params": {"idSCHV": 1},
        "note": "Detail van een schriftelijke vraag. Vereist een gekende vraag-id.",
    },
    "Schriftelijke vragen op id": {
        "path": "/schv/lijst",
        "params": {"id": "1,2,3"},
        "note": "Bulk-opvraag op basis van ids. Lege respons voor onbestaande ids.",
    },
    "Vraag/interpellatie detail": {
        "path": "/vi/{idVI}",
        "params": {"idVI": 1},
        "note": "Detail van een vraag of interpellatie. Vereist een gekende id.",
    },
    "Vergaderingen binnen periode": {
        "path": "/verg/zoek/datums",
        "params": {"datumVan": "2026-01-01", "datumTot": "2026-01-31", "type": "comm"},
        "note": "Zoekt vergaderingen in een periode.",
    },
}

RELEVANT_TAGS = {
    "Volksvertegenwoordigers",
    "Schriftelijke Vraag",
    "Vraag en Interpellatie",
    "Vergadering",
    "Commissie",
    "Gremia",
}


st.set_page_config(page_title="Vlaams Parlement API Explorer", layout="wide")


def fetch_json(url: str, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(
        url,
        params=params,
        headers={"Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=3600)
def load_openapi_spec() -> dict[str, Any]:
    return fetch_json(OPENAPI_URL)


@st.cache_data(ttl=1800)
def load_current_members() -> list[dict[str, Any]]:
    payload = fetch_json(f"{API_BASE_URL}/vv/huidige")
    members: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        member = item.get("volksvertegenwoordiger", {})
        if member:
            members.append(member)
    return members


@st.cache_data(ttl=1800)
def load_member_detail(person_id: int, lang: str = "nl") -> dict[str, Any]:
    return fetch_json(f"{API_BASE_URL}/vv/{person_id}", params={"lang": lang})


@st.cache_data(ttl=1800)
def load_committees() -> list[dict[str, Any]]:
    payload = fetch_json(f"{API_BASE_URL}/comm/huidige")
    committees: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        committee = item.get("commissie", {})
        if committee:
            committees.append(committee)
    return committees


@st.cache_data(ttl=1800)
def load_committee_status(committee_id: int) -> dict[str, Any]:
    return fetch_json(f"{API_BASE_URL}/comm/{committee_id}/alle-stvz")


@st.cache_data(ttl=1800)
def search_documents(query: str, page: int = 1, max_items: int = 20, sort: str = "date") -> dict[str, Any]:
    return fetch_json(
        f"{SEARCH_API_BASE_URL}/{query}",
        params={
            "collection": "vp_collection",
            "page": page,
            "max": max_items,
            "sort": sort,
        },
    )


def extract_relevant_paths(spec: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path, methods in spec.get("paths", {}).items():
        get_operation = methods.get("get")
        if not get_operation:
            continue
        tags = get_operation.get("tags", [])
        if not any(tag in RELEVANT_TAGS for tag in tags):
            continue
        rows.append(
            {
                "tag": ", ".join(tags),
                "path": path,
                "summary": get_operation.get("summary", ""),
            }
        )
    return sorted(rows, key=lambda row: (row["tag"], row["path"]))


def extract_properties(spec: dict[str, Any], schema_name: str) -> pd.DataFrame:
    schema = spec.get("components", {}).get("schemas", {}).get(schema_name, {})
    rows: list[dict[str, str]] = []
    for name, value in schema.get("properties", {}).items():
        prop_type = value.get("$ref") or value.get("type") or "object"
        rows.append({"veld": name, "type": prop_type})
    return pd.DataFrame(rows)


def render_key_value_block(data: dict[str, Any], fields: list[str]) -> None:
    rows = []
    for field in fields:
        rows.append({"veld": field, "waarde": data.get(field)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_overview(spec: dict[str, Any]) -> None:
    st.title("Vlaams Parlement Open Data Explorer")
    st.markdown(
        """
        Deze app gebruikt de live Open Data API van het Vlaams Parlement:
        `https://ws.vlpar.be/e/opendata`.

        Eerste bevindingen:
        - De oude basis-URL `https://data.vlaamsparlement.be/v1/` resolveert hier niet.
        - De actuele publieke OpenAPI-spec staat op `https://ws.vlpar.be/e/opendata/api-docs`.
        - Leden (`/vv/...`) zijn goed ontsloten.
        - Schriftelijke vragen (`/schv/...`) en vragen/interpellaties (`/vi/...`) hebben detail- en bulk-endpoints op basis van ids, maar geen publieke zoekendpoint in deze Open Data API.
        - De aparte `Document Search API` werkt publiek via `https://ws.vlpar.be/api/search/query/...` en levert `soort`- en `opendata`-metadata die bruikbaar zijn voor discovery.
        """
    )

    endpoint_df = pd.DataFrame(extract_relevant_paths(spec))
    st.subheader("Relevante endpoints uit de live OpenAPI-spec")
    st.dataframe(endpoint_df, use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Schema: WVolksVertegenwoordigerF")
        st.dataframe(
            extract_properties(spec, "WVolksVertegenwoordigerF"),
            use_container_width=True,
            hide_index=True,
        )
    with col2:
        st.subheader("Schema: WSchriftelijkeVraagF")
        st.dataframe(
            extract_properties(spec, "WSchriftelijkeVraagF"),
            use_container_width=True,
            hide_index=True,
        )


def render_members_page() -> None:
    st.title("Volksvertegenwoordigers")
    members = load_current_members()
    if not members:
        st.warning("Geen leden opgehaald.")
        return

    rows = []
    for member in members:
        fractie = member.get("fractie", {}) or {}
        rows.append(
            {
                "id": member.get("id"),
                "naam": f"{member.get('voornaam', '')} {member.get('naam', '')}".strip(),
                "fractie": fractie.get("naam"),
                "kieskring": member.get("kieskring"),
                "zetel": member.get("zetel"),
                "deelstaatsenator": member.get("deelstaatsenator"),
            }
        )
    member_df = pd.DataFrame(rows).sort_values("naam")

    selected_id = st.selectbox(
        "Kies een lid",
        options=member_df["id"].tolist(),
        format_func=lambda person_id: member_df.loc[member_df["id"] == person_id, "naam"].iloc[0],
    )

    col1, col2 = st.columns([1.2, 1])
    with col1:
        st.subheader("Huidige leden")
        st.dataframe(member_df, use_container_width=True, hide_index=True)

    detail = load_member_detail(int(selected_id))
    with col2:
        st.subheader("Detailfiche")
        render_key_value_block(
            detail,
            [
                "id",
                "voornaam",
                "naam",
                "geslacht",
                "geboortedatum",
                "geboorteplaats",
                "kieskring",
                "is-huidige-vv",
            ],
        )
        st.markdown("**Email**")
        st.write(detail.get("email", []))
        st.markdown("**Websites en socials**")
        st.write(detail.get("website", []))
        st.markdown("**Huidige fractie**")
        st.json(detail.get("huidigefractie", {}))

    st.subheader("Aanwezigheden huidige legislatuur")
    st.json(detail.get("aanwezigheden-huidige-legislatuur", {}))

    st.subheader("Lidmaatschappen en mandaten")
    tab1, tab2, tab3 = st.tabs(
        ["Lidmaatschap", "Mandaat Vlaams Parlement", "Andere mandaten"]
    )
    with tab1:
        st.json(detail.get("lidmaatschap", []))
    with tab2:
        st.json(detail.get("mandaat-vlaams-parlement", []))
    with tab3:
        st.json(detail.get("mandaat-andere", []))

    with st.expander("Ruwe JSON detailfiche"):
        st.code(json.dumps(detail, indent=2, ensure_ascii=False), language="json")


def render_api_explorer() -> None:
    st.title("API Explorer")
    choice = st.selectbox("Endpoint", list(CURATED_ENDPOINTS.keys()))
    config = CURATED_ENDPOINTS[choice]
    st.caption(config["note"])

    path_template = config["path"]
    values: dict[str, Any] = {}
    query_params: dict[str, Any] = {}

    for key, default in config["params"].items():
        if isinstance(default, int):
            values[key] = st.number_input(key, value=default, step=1)
        else:
            values[key] = st.text_input(key, value=str(default))

    path = path_template
    for key, value in values.items():
        placeholder = "{" + key + "}"
        if placeholder in path:
            path = path.replace(placeholder, str(value))
        else:
            query_params[key] = value

    full_url = f"{API_BASE_URL}{path}"
    st.markdown(f"**Request URL**: `{full_url}`")
    if query_params:
        st.markdown(f"**Query params**: `{query_params}`")

    if st.button("Voer request uit", type="primary"):
        try:
            payload = fetch_json(full_url, params=query_params or None)
            st.success("Request geslaagd.")
            st.json(payload)
        except Exception as exc:
            st.error(f"Request mislukt: {exc}")


def render_discovery_page() -> None:
    st.title("Discovery van ids")
    st.markdown(
        """
        Deze pagina test twee discovery-routes:

        - `SCHV`: via de publieke zoek-API `https://ws.vlpar.be/api/search/query/...`
        - `VI`: via zowel de zoek-API als `commissie -> alle-stvz`
        """
    )

    st.subheader("Recente schriftelijke vragen via zoek-API")
    query = st.text_input("Zoekterm voor written-question discovery", value="schriftelijke vraag")
    max_items = st.slider("Aantal resultaten", min_value=10, max_value=100, value=30, step=10)

    try:
        search_payload = search_documents(query=query, max_items=max_items)
        rows = []
        for item in search_payload.get("result", []):
            metatags = {tag["name"]: tag["value"] for tag in item.get("metatags", {}).get("metatag", [])}
            if metatags.get("soort") != "SCHV":
                continue
            rows.append(
                {
                    "publicatiedatum": metatags.get("publicatiedatum"),
                    "nummer": metatags.get("nummer"),
                    "vraagsteller": metatags.get("vraagsteller"),
                    "minister": metatags.get("minister"),
                    "onderwerp": metatags.get("onderwerp"),
                    "opendata": metatags.get("opendata"),
                    "displayurl": metatags.get("displayurl"),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"Zoek-API mislukt: {exc}")

    st.subheader("Vragen/interpellaties via commissie-status")
    committees = load_committees()
    committee_options = {
        f"{committee.get('afkorting')} - {committee.get('titel')}": committee.get("id")
        for committee in committees
    }
    selected_committee_label = st.selectbox("Kies een commissie", list(committee_options.keys()))
    selected_committee_id = committee_options[selected_committee_label]

    try:
        status_payload = load_committee_status(int(selected_committee_id))
        rows = []
        for item in status_payload.get("items", []):
            status_block = item.get("commissie-status", {})
            status_name = status_block.get("status")
            for vi in status_block.get("vrageninterpellatie", []):
                rows.append(
                    {
                        "status": status_name,
                        "id": vi.get("id"),
                        "nummer": vi.get("nummer"),
                        "titel": vi.get("titel"),
                        "onderwerp": vi.get("onderwerp"),
                        "type": (vi.get("objecttype") or {}).get("naam"),
                    }
                )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"Commissie-status mislukt: {exc}")

    st.subheader("Ruwe zoek-API sample")
    with st.expander("Toon sample van zoek-API response"):
        try:
            st.json(search_documents(query=query, max_items=3))
        except Exception as exc:
            st.error(f"Kon sample niet tonen: {exc}")


def render_data_model_page(spec: dict[str, Any]) -> None:
    st.title("Datamodel startpunt")
    st.markdown(
        """
        Voor een eerste databank over elk parlementslid lijken minstens deze entiteiten nodig:

        - `members`: kernfiche per volksvertegenwoordiger
        - `member_memberships`: fractiehistoriek en lidmaatschappen
        - `member_mandates_vp`: functies en commissieposities binnen het Vlaams Parlement
        - `member_mandates_other`: lokale en andere mandaten
        - `member_attendance`: plenaire en commissie-aanwezigheden
        - `written_questions`: schriftelijke vragen
        - `question_answers`: antwoorden / antwoordende ministers / bestanden
        - `oral_items`: vragen en interpellaties
        - `meetings`: vergaderingen en koppelingen naar commissies/gremia
        """
    )

    st.subheader("Publieke API-dekking")
    coverage = pd.DataFrame(
        [
            {
                "domein": "Leden",
                "status": "goed gedekt",
                "opmerking": "lijst, detail, adreslijst, per fractie, per kieskring",
            },
            {
                "domein": "Schriftelijke vragen",
                "status": "werkbare discovery",
                "opmerking": "detail op `/schv/...`, discovery via publieke zoek-API `/api/search/query/...` met `soort=SCHV` in metadata",
            },
            {
                "domein": "Vragen/interpellaties",
                "status": "werkbare discovery",
                "opmerking": "detail op `/vi/...`, discovery via commissie-status en ook via zoek-API metadata `soort=VI`",
            },
            {
                "domein": "Vergaderingen",
                "status": "goed gedekt",
                "opmerking": "zoek op periode, detail, agenda, handelingen",
            },
            {
                "domein": "Commissies/gremia",
                "status": "goed gedekt",
                "opmerking": "detail, stand van zaken, verslagen, geplande vergaderingen",
            },
        ]
    )
    st.dataframe(coverage, use_container_width=True, hide_index=True)

    st.subheader("Schema: WVragenInterpellatieF")
    st.dataframe(
        extract_properties(spec, "WVragenInterpellatieF"),
        use_container_width=True,
        hide_index=True,
    )


spec = load_openapi_spec()
page = st.sidebar.radio(
    "Navigatie",
    ["Overzicht", "Volksvertegenwoordigers", "Discovery", "API Explorer", "Datamodel startpunt"],
)

if page == "Overzicht":
    render_overview(spec)
elif page == "Volksvertegenwoordigers":
    render_members_page()
elif page == "Discovery":
    render_discovery_page()
elif page == "API Explorer":
    render_api_explorer()
else:
    render_data_model_page(spec)
