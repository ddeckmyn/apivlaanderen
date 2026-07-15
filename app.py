from __future__ import annotations

import json
import math
from html import escape
from pathlib import Path
from urllib.parse import urlencode

try:
    import altair as alt
    ALTAIR_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - cloud dependency fallback
    alt = None
    ALTAIR_IMPORT_ERROR = exc
import pandas as pd
import streamlit as st
from pandas.errors import EmptyDataError

from member_ai_overviews import build_member_overview_text, write_member_ai_overviews
from member_topics import extract_member_themes
from vp_pipeline import PUBLISHED_DIR, STATE_DIR, current_store_dir, read_json

st.set_page_config(page_title="Vlaams Parlement Data GUI", layout="wide")

VIEW_OPTIONS = {
    "Parlement": "parliament",
    "Fractie": "fraction",
    "Politicus": "member",
    "Commissie": "committee",
    "Agenda/Vergaderingen": "meetings",
    "Teksten": "texts",
    "Schriftelijke vragen": "written",
    "Vragen en interpellaties": "oral",
    "Beheer": "admin",
}

HEMICYCLE_FILTERS = {
    "Fractiekleuren": {"mode": "party", "label": "Fractie"},
    "Aanwezigheid plenaire": {"mode": "metric", "column": "plenary_attendance_rate", "label": "Plenaire aanwezigheid"},
    "Aanwezigheid commissie": {"mode": "metric", "column": "committee_attendance_rate", "label": "Commissie-aanwezigheid"},
    "Vraagsteller-activiteit": {"mode": "metric", "column": "questioner_activity", "label": "Vraagsteller-activiteit"},
    "Totale activiteit": {"mode": "metric", "column": "total_activity", "label": "Totale activiteit"},
    "Schriftelijke vragen": {"mode": "metric", "column": "written_questions_asked", "label": "Schriftelijke vragen"},
    "Mondelinge vragen": {"mode": "metric", "column": "oral_items_asked", "label": "Mondelinge vragen"},
    "Minister-activiteit": {"mode": "metric", "column": "minister_activity", "label": "Minister-activiteit"},
}

PARLIAMENT_VISUAL_OPTIONS = {
    "Visualiseer fracties": {"hemicycle_filter": "Fractiekleuren", "top_metric": ("questioner_activity", "Vraagsteller-dossiers")},
    "Actiefste parlementsleden": {"hemicycle_filter": "Totale activiteit", "top_metric": ("total_activity", "Totale activiteit")},
    "Meeste vraagstellers": {"hemicycle_filter": "Vraagsteller-activiteit", "top_metric": ("questioner_activity", "Vraagsteller-dossiers")},
    "Meest aanwezig": {"hemicycle_filter": "Aanwezigheid plenaire", "top_metric": ("plenary_attendance_rate", "Plenaire aanwezigheid")},
}

SEAT_LAYOUT_PATH = Path(__file__).resolve().parent / "data" / "reference" / "seat_layout.json"


def load_state() -> dict:
    return read_json(STATE_DIR / "sync_state.json", default={})


def load_table(name: str) -> pd.DataFrame:
    path = current_store_dir(load_state()) / f"{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame()


def load_seat_layout() -> pd.DataFrame:
    if not SEAT_LAYOUT_PATH.exists():
        return pd.DataFrame()
    rows = json.loads(SEAT_LAYOUT_PATH.read_text(encoding="utf-8"))
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["seat_number"] = pd.to_numeric(frame["seat_number"], errors="coerce")
    frame = frame[frame["seat_number"].notna()].copy()
    frame["seat_number"] = frame["seat_number"].astype(int)
    return frame


def coerce_int(value) -> int | None:
    if pd.isna(value) or value in ("", None):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_int(value) -> int:
    coerced = coerce_int(value)
    return coerced if coerced is not None else 0


def safe_float(value) -> float:
    if pd.isna(value) or value in ("", None):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def color_with_hash(value: str | None) -> str:
    if not value:
        return "#6b7280"
    value = value.strip()
    return value if value.startswith("#") else f"#{value}"


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = color_with_hash(value).lstrip("#")
    return tuple(int(normalized[index : index + 2], 16) for index in (0, 2, 4))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def blend_colors(left: str, right: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, float(ratio)))
    left_rgb = hex_to_rgb(left)
    right_rgb = hex_to_rgb(right)
    mixed = tuple(round(left_rgb[index] + (right_rgb[index] - left_rgb[index]) * ratio) for index in range(3))
    return rgb_to_hex(mixed)


def color_from_metric(value: float | int | None, minimum: float, maximum: float) -> str:
    if pd.isna(value):
        return "#9ca3af"
    if maximum <= minimum:
        return "#84cc16"
    normalized = (float(value) - minimum) / (maximum - minimum)
    if normalized <= 0.5:
        return blend_colors("#dc2626", "#facc15", normalized / 0.5)
    return blend_colors("#facc15", "#16a34a", (normalized - 0.5) / 0.5)


def format_pct(value) -> str:
    if pd.isna(value):
        return "n.v.t."
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n.v.t."


def render_breadcrumb(items: list[str]) -> None:
    st.caption(" > ".join(items))


def altair_ready() -> bool:
    return alt is not None


def render_altair_fallback(title: str, frame: pd.DataFrame, columns: list[str] | None = None) -> None:
    if ALTAIR_IMPORT_ERROR and not st.session_state.get("_altair_import_warning_shown"):
        st.warning(
            "Geavanceerde grafieken zijn tijdelijk niet beschikbaar in deze omgeving. "
            "De kerngegevens blijven wel zichtbaar."
        )
        st.session_state["_altair_import_warning_shown"] = True
    st.caption(f"{title} wordt tijdelijk als tabel getoond.")
    if frame.empty:
        st.caption("Geen gegevens beschikbaar.")
        return
    display = frame.copy()
    if columns:
        available = [column for column in columns if column in display.columns]
        display = display[available]
    st.dataframe(display, use_container_width=True, hide_index=True)


def build_data_status(state: dict, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = [
        {
            "Domein": "Leden",
            "Status": "Beschikbaar" if not tables["members"].empty else "Ontbreekt",
            "Records": len(tables["members"]),
            "Opmerking": "Profielen, mandaten, contact, foto, aanwezigheid",
        },
        {
            "Domein": "Fracties",
            "Status": "Beschikbaar" if not tables["fractions"].empty else "Ontbreekt",
            "Records": len(tables["fractions"]),
            "Opmerking": "Fracties en huidige samenstelling",
        },
        {
            "Domein": "Commissies",
            "Status": "Beschikbaar" if not tables["committees"].empty else "Ontbreekt",
            "Records": len(tables["committees"]),
            "Opmerking": "Commissies, rollen en secretariaat",
        },
        {
            "Domein": "Schriftelijke vragen",
            "Status": "Beschikbaar" if not tables["written_questions"].empty else "Ontbreekt",
            "Records": len(tables["written_questions"]),
            "Opmerking": "Historiek sinds huidige backfill",
        },
        {
            "Domein": "Mondelinge vragen",
            "Status": "Beschikbaar" if not tables["oral_items"].empty else "Ontbreekt",
            "Records": len(tables["oral_items"]),
            "Opmerking": "Historiek sinds huidige backfill",
        },
        {
            "Domein": "Vergaderingen en agenda",
            "Status": "Nog niet in actieve snapshot" if tables["meetings"].empty else "Beschikbaar",
            "Records": len(tables["meetings"]),
            "Opmerking": "Code voorbereid, actieve snapshot nog niet bijgewerkt",
        },
        {
            "Domein": "Parlementaire teksten",
            "Status": "Nog niet in actieve snapshot" if tables["parliamentary_texts"].empty else "Beschikbaar",
            "Records": len(tables["parliamentary_texts"]),
            "Opmerking": "Metadata en links, geen zware documenten lokaal",
        },
    ]
    return pd.DataFrame(rows)


def render_data_status_banner(state: dict, data_status: pd.DataFrame) -> None:
    unavailable = data_status[data_status["Status"] != "Beschikbaar"]
    with st.container():
        st.caption(
            f"Actieve snapshot: {current_store_dir(state)} | "
            f"Laatste succesvolle sync: {state.get('last_run_at', 'onbekend')} | "
            f"Bootstrap vanaf: {state.get('bootstrap_since', 'onbekend')}"
        )
        if unavailable.empty:
            st.success("Alle MVP-domeinen in deze snapshot beschikbaar.")
        else:
            missing = ", ".join(unavailable["Domein"].tolist())
            st.warning(f"Deze snapshot is gedeeltelijk: {missing}.")


def resolve_member_photo(detail: pd.Series) -> str | None:
    local_path = detail.get("photo_local_path")
    if pd.notna(local_path) and local_path:
        candidate = Path(local_path)
        if not candidate.is_absolute():
            candidate = Path(__file__).resolve().parent / candidate
        if candidate.exists():
            return str(candidate)
    source_url = detail.get("photo_source_url") or detail.get("fotowebpath")
    if pd.notna(source_url) and source_url:
        return str(source_url)
    return None


def build_hemicycle_frame(members: pd.DataFrame) -> pd.DataFrame:
    frame = members.copy()
    frame = frame[frame["zetel"].notna()].copy()
    if frame.empty:
        return frame

    frame["zetel"] = pd.to_numeric(frame["zetel"], errors="coerce")
    frame = frame[frame["zetel"].notna()].sort_values("zetel").reset_index(drop=True)
    seat_layout = load_seat_layout()
    if not seat_layout.empty:
        merged = frame.merge(seat_layout, left_on="zetel", right_on="seat_number", how="left")
        matched = merged["x"].notna().sum()
        if matched >= max(20, int(len(frame) * 0.8)):
            x_min = merged["x"].min()
            x_max = merged["x"].max()
            y_min = merged["y"].min()
            y_max = merged["y"].max()
            x_center = (x_min + x_max) / 2
            y_center = (y_min + y_max) / 2
            scale = max(x_max - x_min, y_max - y_min) / 2
            if not scale:
                scale = 1
            merged["x"] = (merged["x"] - x_center) / scale * 10
            merged["y"] = -((merged["y"] - y_center) / scale * 10)
            merged["fractie_kleur_plot"] = merged["fractie_kleur"].apply(color_with_hash)
            return merged

    total = len(frame)

    left_count = max(1, round(total * 0.20))
    right_count = max(1, round(total * 0.20))
    center_count = max(1, total - left_count - right_count)

    left_block = frame.iloc[:left_count].copy()
    center_block = frame.iloc[left_count : left_count + center_count].copy()
    right_block = frame.iloc[left_count + center_count :].copy()

    def split_counts(count: int, row_count: int) -> list[int]:
        base = count // row_count
        remainder = count % row_count
        return [base + (1 if index < remainder else 0) for index in range(row_count)]

    rows: list[pd.DataFrame] = []

    left_counts = split_counts(len(left_block), 5)
    cursor = 0
    for row_index, row_size in enumerate(left_counts):
        if row_size <= 0:
            continue
        row_members = left_block.iloc[cursor : cursor + row_size].copy()
        cursor += row_size
        seat_positions = list(range(row_size))
        row_members["x"] = [-1.18 + position * 0.105 + row_index * 0.055 for position in seat_positions]
        row_members["y"] = [0.56 - position * 0.115 - row_index * 0.085 for position in seat_positions]
        row_members["bloc"] = "left"
        rows.append(row_members)

    center_counts = split_counts(len(center_block), 5)
    cursor = 0
    center_radii = [0.92, 0.78, 0.64, 0.50, 0.36]
    for row_index, row_size in enumerate(center_counts):
        if row_size <= 0:
            continue
        row_members = center_block.iloc[cursor : cursor + row_size].copy()
        cursor += row_size
        angles = [180 - ((index + 0.5) * 180 / row_size) for index in range(row_size)]
        radius = center_radii[row_index]
        row_members["x"] = [radius * math.cos(math.radians(angle)) * 0.72 for angle in angles]
        row_members["y"] = [radius * math.sin(math.radians(angle)) * 1.02 for angle in angles]
        row_members["bloc"] = "center"
        rows.append(row_members)

    right_counts = split_counts(len(right_block), 5)
    cursor = 0
    for row_index, row_size in enumerate(right_counts):
        if row_size <= 0:
            continue
        row_members = right_block.iloc[cursor : cursor + row_size].copy()
        cursor += row_size
        seat_positions = list(range(row_size))
        row_members["x"] = [1.18 - position * 0.105 - row_index * 0.055 for position in seat_positions]
        row_members["y"] = [0.56 - position * 0.115 - row_index * 0.085 for position in seat_positions]
        row_members["bloc"] = "right"
        rows.append(row_members)

    result = pd.concat(rows, ignore_index=True)
    result["fractie_kleur_plot"] = result["fractie_kleur"].apply(color_with_hash)
    return result


def build_hemicycle_svg(hemi: pd.DataFrame, visual_mode: str) -> str:
    if hemi.empty:
        return ""

    width = 980
    height = 560
    padding = 44
    radius = 9
    x_min = float(hemi["x"].min())
    x_max = float(hemi["x"].max())
    y_min = float(hemi["y"].min())
    y_max = float(hemi["y"].max())
    x_span = max(x_max - x_min, 1e-6)
    y_span = max(y_max - y_min, 1e-6)
    scale = min((width - padding * 2) / x_span, (height - padding * 2) / y_span)

    display = hemi.copy()
    display["cx"] = padding + (display["x"].astype(float) - x_min) * scale
    display["cy"] = height - padding - (display["y"].astype(float) - y_min) * scale

    seat_nodes: list[str] = []
    for _, row in display.sort_values(["fractie_volgnr", "zetel", "volledige_naam"], na_position="last").iterrows():
        cx = float(row["cx"])
        cy = float(row["cy"])
        member_id = coerce_int(row.get("member_id"))
        fraction_id = coerce_int(row.get("fractie_id"))
        params = urlencode(
            {
                "view": "parliament",
                "popup_member_id": member_id or "",
                "selected_fraction_id": fraction_id or "",
                "parliament_visual_mode": visual_mode,
            }
        )
        tooltip = (
            f"{row.get('volledige_naam', 'Onbekend')} | "
            f"{row.get('fractie_naam', 'Onbekend')} | "
            f"zetel {coerce_int(row.get('zetel')) or '?'}"
        )
        seat_nodes.append(
            f'<a href="?{params}" target="_self">'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{escape(color_with_hash(row.get("seat_fill_color")))}" '
            f'stroke="#ffffff" stroke-width="3"></circle>'
            f"<title>{escape(tooltip)}</title>"
            f"</a>"
        )

    return f"""
    <div style="display:flex;justify-content:center;width:100%;padding:0.5rem 0 0.25rem 0;">
      <svg viewBox="0 0 {width} {height}" style="width:100%;max-width:980px;height:auto;overflow:visible;">
        {' '.join(seat_nodes)}
        <text x="{width / 2:.0f}" y="{height - 6}" text-anchor="middle"
              style="font-size:34px;font-weight:700;fill:#111827;font-family:Georgia, serif;">{len(hemi)}</text>
      </svg>
    </div>
    """


def prepare_hemicycle_colors(hemi: pd.DataFrame, filter_name: str) -> tuple[pd.DataFrame, str]:
    display = hemi.copy()
    config = HEMICYCLE_FILTERS.get(filter_name, HEMICYCLE_FILTERS["Fractiekleuren"])
    if config["mode"] == "party":
        display["seat_fill_color"] = display["fractie_kleur_plot"]
        return display, "Fractiekleur per zetel."

    column = config["column"]
    series = pd.to_numeric(display[column], errors="coerce")
    minimum = float(series.min()) if series.notna().any() else 0.0
    maximum = float(series.max()) if series.notna().any() else 1.0
    display["seat_fill_color"] = [
        color_from_metric(value, minimum, maximum) for value in series
    ]
    return (
        display,
        f"{config['label']}: rood = laagste waarde, geel = midden, groen = hoogste waarde.",
    )


def build_top_members_preview(member_stats: pd.DataFrame, metric_column: str) -> pd.DataFrame:
    preview = (
        member_stats.assign(
            metric_value=pd.to_numeric(member_stats[metric_column], errors="coerce").fillna(0),
            attendance_pct=member_stats["plenary_attendance_rate"].fillna(0) * 100,
        )
        .sort_values(["metric_value", "total_activity"], ascending=False)
        .head(12)
        .sort_values("metric_value", ascending=True)
    )
    preview["label"] = preview["volledige_naam"] + " (" + preview["fractie_naam"].fillna("?") + ")"
    return preview


def build_member_popup_card(member_stats: pd.DataFrame, popup_member_id: int | None) -> pd.DataFrame:
    if popup_member_id is None or member_stats.empty:
        return pd.DataFrame()
    return member_stats[member_stats["member_id"].apply(coerce_int) == popup_member_id].head(1)


def build_top_members_visual(member_stats: pd.DataFrame, metric_column: str, metric_label: str):
    preview = build_top_members_preview(member_stats, metric_column)
    return (
        alt.Chart(preview)
        .mark_bar(cornerRadiusEnd=7)
        .encode(
            x=alt.X("metric_value:Q", title=metric_label),
            y=alt.Y("label:N", title=None),
            color=alt.Color(
                "attendance_pct:Q",
                scale=alt.Scale(domain=[0, 100], range=["#dc2626", "#facc15", "#16a34a"]),
                title="Plenaire aanwezigheid %",
            ),
            tooltip=[
                alt.Tooltip("volledige_naam:N", title="Naam"),
                alt.Tooltip("fractie_naam:N", title="Fractie"),
                alt.Tooltip("metric_value:Q", title=metric_label),
                alt.Tooltip("attendance_pct:Q", title="Plenaire aanwezigheid", format=".1f"),
                alt.Tooltip("written_questions_asked:Q", title="Schriftelijke vragen"),
                alt.Tooltip("oral_items_asked:Q", title="Mondelinge vragen"),
            ],
        )
        .properties(height=360)
    )


def build_member_activity_breakdown(detail: pd.Series) -> pd.DataFrame:
    rows = [
        {"categorie": "Schriftelijk", "rol": "Vraagsteller", "aantal": int(detail.get("written_questions_asked") or 0)},
        {"categorie": "Mondeling", "rol": "Vraagsteller", "aantal": int(detail.get("oral_items_asked") or 0)},
        {"categorie": "Schriftelijk", "rol": "Minister", "aantal": int(detail.get("written_questions_as_minister") or 0)},
        {"categorie": "Mondeling", "rol": "Minister", "aantal": int(detail.get("oral_items_as_minister") or 0)},
    ]
    frame = pd.DataFrame(rows)
    frame["label"] = frame["categorie"] + " | " + frame["rol"]
    return frame


def build_member_attendance_breakdown(detail: pd.Series) -> pd.DataFrame:
    rows = [
        {"scope": "Plenair", "status": "Aanwezig", "aantal": int(detail.get("plenary_present") or 0)},
        {"scope": "Plenair", "status": "Afwezig", "aantal": int(detail.get("plenary_absent") or 0)},
        {"scope": "Plenair", "status": "Verontschuldigd", "aantal": int(detail.get("plenary_excused") or 0)},
        {"scope": "Commissie", "status": "Aanwezig", "aantal": int(detail.get("committee_present") or 0)},
        {"scope": "Commissie", "status": "Afwezig", "aantal": int(detail.get("committee_absent") or 0)},
        {"scope": "Commissie", "status": "Verontschuldigd", "aantal": int(detail.get("committee_excused") or 0)},
    ]
    return pd.DataFrame(rows)


def build_member_recent_activity(written_links: pd.DataFrame, oral_links: pd.DataFrame, member_id: int) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if not written_links.empty:
        written = written_links[written_links["member_id"].apply(coerce_int) == member_id].copy()
        if not written.empty:
            frames.append(
                written.assign(type="Schriftelijke vraag")[["publicatiedatum", "type", "role", "onderwerp"]]
            )
    if not oral_links.empty:
        oral = oral_links[oral_links["member_id"].apply(coerce_int) == member_id].copy()
        if not oral.empty:
            frames.append(
                oral.assign(type="Mondeling dossier")[["publicatiedatum", "type", "role", "onderwerp"]]
            )
    if not frames:
        return pd.DataFrame(columns=["publicatiedatum", "type", "role", "onderwerp"])
    recent = pd.concat(frames, ignore_index=True)
    recent["publicatiedatum"] = pd.to_datetime(recent["publicatiedatum"], errors="coerce")
    recent = recent.sort_values("publicatiedatum", ascending=False)
    recent["publicatiedatum"] = recent["publicatiedatum"].dt.strftime("%Y-%m-%d")
    return recent.head(10)


def sync_state_from_query_params() -> None:
    params = st.query_params
    view = params.get("view")
    if view in VIEW_OPTIONS.values():
        st.session_state["view_key"] = view
    mode = params.get("parliament_visual_mode")
    if mode in PARLIAMENT_VISUAL_OPTIONS:
        st.session_state["parliament_visual_mode"] = mode
    for key in ["selected_member_id", "selected_fraction_id", "selected_committee_id", "popup_member_id"]:
        value = params.get(key)
        coerced = coerce_int(value)
        if coerced is not None:
            st.session_state[key] = coerced


def sync_query_params_from_state() -> None:
    params = {"view": st.session_state.get("view_key", "parliament")}
    mode = st.session_state.get("parliament_visual_mode")
    if mode in PARLIAMENT_VISUAL_OPTIONS:
        params["parliament_visual_mode"] = mode
    for key in ["selected_member_id", "selected_fraction_id", "selected_committee_id", "popup_member_id"]:
        value = st.session_state.get(key)
        if value is not None:
            params[key] = value
    st.query_params.clear()
    for key, value in params.items():
        st.query_params[key] = value


def build_member_stats(
    members: pd.DataFrame,
    attendance: pd.DataFrame,
    written_links: pd.DataFrame,
    oral_links: pd.DataFrame,
) -> pd.DataFrame:
    stats = members.copy()
    if stats.empty:
        return stats

    stats["member_id"] = pd.to_numeric(stats["member_id"], errors="coerce").astype("Int64")
    stats["fractie_id"] = pd.to_numeric(stats["fractie_id"], errors="coerce").astype("Int64")

    if written_links.empty:
        written_counts = pd.DataFrame(columns=["member_id", "written_questions_asked", "written_questions_as_minister"])
    else:
        written = written_links.copy()
        written["member_id"] = pd.to_numeric(written["member_id"], errors="coerce").astype("Int64")
        written_counts = (
            written.assign(
                written_questions_asked=(written["role"] == "vraagsteller").astype(int),
                written_questions_as_minister=(written["role"] == "minister").astype(int),
            )
            .groupby("member_id", dropna=True)[["written_questions_asked", "written_questions_as_minister"]]
            .sum()
            .reset_index()
        )

    if oral_links.empty:
        oral_counts = pd.DataFrame(columns=["member_id", "oral_items_asked", "oral_items_as_minister"])
    else:
        oral = oral_links.copy()
        oral["member_id"] = pd.to_numeric(oral["member_id"], errors="coerce").astype("Int64")
        oral_counts = (
            oral.assign(
                oral_items_asked=(oral["role"] == "vraagsteller").astype(int),
                oral_items_as_minister=(oral["role"] == "minister").astype(int),
            )
            .groupby("member_id", dropna=True)[["oral_items_asked", "oral_items_as_minister"]]
            .sum()
            .reset_index()
        )

    if attendance.empty:
        plenary = pd.DataFrame(columns=["member_id"])
        committee = pd.DataFrame(columns=["member_id"])
    else:
        attendance_frame = attendance.copy()
        attendance_frame["member_id"] = pd.to_numeric(attendance_frame["member_id"], errors="coerce").astype("Int64")
        for column in ["aanwezig", "afwezig", "verontschuldigd"]:
            attendance_frame[column] = pd.to_numeric(attendance_frame[column], errors="coerce").fillna(0)

        plenary = (
            attendance_frame[attendance_frame["scope"] == "plenaire"][
                ["member_id", "aanwezig", "afwezig", "verontschuldigd"]
            ]
            .rename(
                columns={
                    "aanwezig": "plenary_present",
                    "afwezig": "plenary_absent",
                    "verontschuldigd": "plenary_excused",
                }
            )
        )
        committee = (
            attendance_frame[attendance_frame["scope"] == "commissie"]
            .groupby("member_id", dropna=True)[["aanwezig", "afwezig", "verontschuldigd"]]
            .sum()
            .reset_index()
            .rename(
                columns={
                    "aanwezig": "committee_present",
                    "afwezig": "committee_absent",
                    "verontschuldigd": "committee_excused",
                }
            )
        )

    for frame in [written_counts, oral_counts, plenary, committee]:
        stats = stats.merge(frame, on="member_id", how="left")

    numeric_columns = [
        "written_questions_asked",
        "written_questions_as_minister",
        "oral_items_asked",
        "oral_items_as_minister",
        "plenary_present",
        "plenary_absent",
        "plenary_excused",
        "committee_present",
        "committee_absent",
        "committee_excused",
    ]
    for column in numeric_columns:
        if column not in stats.columns:
            stats[column] = 0
        stats[column] = pd.to_numeric(stats[column], errors="coerce").fillna(0)

    stats["questioner_activity"] = stats["written_questions_asked"] + stats["oral_items_asked"]
    stats["minister_activity"] = stats["written_questions_as_minister"] + stats["oral_items_as_minister"]
    stats["total_activity"] = stats["questioner_activity"] + stats["minister_activity"]
    stats["plenary_total"] = stats["plenary_present"] + stats["plenary_absent"] + stats["plenary_excused"]
    stats["committee_total"] = stats["committee_present"] + stats["committee_absent"] + stats["committee_excused"]
    stats["plenary_attendance_rate"] = stats["plenary_present"].div(stats["plenary_total"].replace(0, pd.NA))
    stats["committee_attendance_rate"] = stats["committee_present"].div(stats["committee_total"].replace(0, pd.NA))
    return stats


def build_fraction_stats(fractions: pd.DataFrame, member_stats: pd.DataFrame) -> pd.DataFrame:
    if member_stats.empty:
        return pd.DataFrame()

    grouped = (
        member_stats.groupby(["fractie_id", "fractie_naam", "fractie_kleur"], dropna=False)
        .agg(
            members=("member_id", "count"),
            questioner_activity=("questioner_activity", "sum"),
            minister_activity=("minister_activity", "sum"),
            total_activity=("total_activity", "sum"),
            avg_plenary_attendance=("plenary_attendance_rate", "mean"),
        )
        .reset_index()
    )

    top_members = (
        member_stats.sort_values(["fractie_id", "questioner_activity", "total_activity"], ascending=[True, False, False])
        .drop_duplicates(subset=["fractie_id"])
        [["fractie_id", "volledige_naam"]]
        .rename(columns={"volledige_naam": "top_active_member"})
    )
    grouped = grouped.merge(top_members, on="fractie_id", how="left")

    if not fractions.empty:
        base = fractions.copy()
        base["fractie_id"] = pd.to_numeric(base["fractie_id"], errors="coerce").astype("Int64")
        grouped["fractie_id"] = pd.to_numeric(grouped["fractie_id"], errors="coerce").astype("Int64")
        grouped = base.merge(grouped, on="fractie_id", how="left", suffixes=("", "_agg"))
        grouped["fractie_naam"] = grouped["fractie_naam"].fillna(grouped.get("fractie_naam_agg"))
        grouped["fractie_kleur"] = grouped["fractie_kleur"].fillna(grouped.get("fractie_kleur_agg"))
        grouped["members"] = grouped["members"].fillna(grouped.get("fractie_zetel_aantal", 0))
    else:
        grouped["fractie_logo_url"] = None
        grouped["fractie_volgnr"] = None
        grouped["fractie_zetel_aantal"] = grouped["members"]

    grouped["avg_plenary_attendance_pct"] = grouped["avg_plenary_attendance"].fillna(0) * 100
    grouped = grouped.sort_values(["fractie_volgnr", "fractie_zetel_aantal", "members"], ascending=[True, False, False])
    return grouped


def build_committee_stats(
    committees: pd.DataFrame,
    committee_memberships: pd.DataFrame,
    member_stats: pd.DataFrame,
    oral_items: pd.DataFrame,
) -> pd.DataFrame:
    if committees.empty:
        return pd.DataFrame()

    base = committees.copy()
    base["committee_id"] = pd.to_numeric(base["committee_id"], errors="coerce").astype("Int64")

    memberships = committee_memberships.copy() if not committee_memberships.empty else pd.DataFrame(columns=["committee_id"])
    if not memberships.empty:
        memberships["committee_id"] = pd.to_numeric(memberships["committee_id"], errors="coerce").astype("Int64")
        memberships["member_id"] = pd.to_numeric(memberships["member_id"], errors="coerce").astype("Int64")
        member_counts = (
            memberships.drop_duplicates(subset=["committee_id", "member_id"])
            .groupby("committee_id", dropna=True)
            .size()
            .reset_index(name="members")
        )
        role_counts = (
            memberships.groupby("committee_id", dropna=True)
            .size()
            .reset_index(name="roles")
        )
        enriched = memberships.merge(
            member_stats[["member_id", "questioner_activity", "plenary_attendance_rate"]],
            on="member_id",
            how="left",
        )
        activity = (
            enriched.groupby("committee_id", dropna=True)
            .agg(
                avg_member_activity=("questioner_activity", "mean"),
                avg_plenary_attendance=("plenary_attendance_rate", "mean"),
            )
            .reset_index()
        )
    else:
        member_counts = pd.DataFrame(columns=["committee_id", "members"])
        role_counts = pd.DataFrame(columns=["committee_id", "roles"])
        activity = pd.DataFrame(columns=["committee_id", "avg_member_activity", "avg_plenary_attendance"])

    oral = oral_items.copy() if not oral_items.empty else pd.DataFrame(columns=["commissie_id"])
    if not oral.empty:
        oral["commissie_id"] = pd.to_numeric(oral["commissie_id"], errors="coerce").astype("Int64")
        oral_counts = oral.groupby("commissie_id", dropna=True).size().reset_index(name="oral_items")
        oral_counts = oral_counts.rename(columns={"commissie_id": "committee_id"})
    else:
        oral_counts = pd.DataFrame(columns=["committee_id", "oral_items"])

    result = base.merge(member_counts, on="committee_id", how="left")
    result = result.merge(role_counts, on="committee_id", how="left")
    result = result.merge(activity, on="committee_id", how="left")
    result = result.merge(oral_counts, on="committee_id", how="left")
    for column in ["members", "roles", "oral_items", "avg_member_activity", "avg_plenary_attendance"]:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)
    result["avg_plenary_attendance_pct"] = result["avg_plenary_attendance"] * 100
    return result.sort_values("committee_name")


def navigate(view: str, **payload) -> None:
    st.session_state["view_key"] = view
    for key, value in payload.items():
        st.session_state[key] = value
    sync_query_params_from_state()
    st.rerun()


def render_missing_data() -> None:
    st.title("Vlaams Parlement Data GUI")
    st.warning("Er is nog geen lokale dataset gevonden.")
    st.markdown(
        f"""
        Run eerst lokaal de sync:

        ```powershell
        python .\\scripts\\sync_vlaams_parlement.py --since 2024-06-09
        ```

        Daarna verschijnt de data in:

        - `{current_store_dir(load_state())}`
        - `{PUBLISHED_DIR / 'vlaams_parlement_data.xlsx'}`
        """
    )


def render_parliament_view(member_stats: pd.DataFrame, fraction_stats: pd.DataFrame, committee_stats: pd.DataFrame) -> None:
    render_breadcrumb(["Parlement"])
    st.title("Vlaams Parlement")
    st.caption("Halfrond en kerncijfers voor aanwezigheid en activiteit.")

    top_fraction = fraction_stats.sort_values("questioner_activity", ascending=False).head(1)
    top_member = member_stats.sort_values("questioner_activity", ascending=False).head(1)
    avg_attendance = member_stats["plenary_attendance_rate"].mean() * 100 if not member_stats.empty else 0
    visual_mode = st.session_state.get("parliament_visual_mode", "Visualiseer fracties")
    if visual_mode not in PARLIAMENT_VISUAL_OPTIONS:
        visual_mode = "Visualiseer fracties"
    st.session_state["parliament_visual_mode"] = visual_mode
    visual_config = PARLIAMENT_VISUAL_OPTIONS[visual_mode]
    popup_member_id = coerce_int(st.session_state.get("popup_member_id"))

    st.markdown(
        """
        <style>
        .vp-card {
            background: linear-gradient(180deg, #fffdf8 0%, #f8f3ea 100%);
            border: 1px solid #eadfcd;
            border-radius: 18px;
            padding: 1rem 1.1rem;
            min-height: 118px;
            box-shadow: 0 10px 24px rgba(71, 55, 23, 0.06);
        }
        .vp-kicker {
            color: #7c6a4d;
            font-size: 0.82rem;
            margin-bottom: 0.35rem;
        }
        .vp-value {
            color: #1f2937;
            font-size: 2rem;
            font-weight: 700;
            line-height: 1.05;
        }
        .vp-subtle {
            color: #5b6472;
            font-size: 0.9rem;
            margin-top: 0.35rem;
        }
        .vp-panel {
            background: #fffdf9;
            border: 1px solid #ece3d4;
            border-radius: 20px;
            padding: 1rem 1.1rem 0.8rem 1.1rem;
            box-shadow: 0 10px 28px rgba(54, 37, 14, 0.05);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f'<div class="vp-card"><div class="vp-kicker">Huidige leden</div><div class="vp-value">{len(member_stats)}</div>'
            '<div class="vp-subtle">Volledige actuele samenstelling</div></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="vp-card"><div class="vp-kicker">Fracties</div><div class="vp-value">{len(fraction_stats)}</div>'
            '<div class="vp-subtle">Actieve fracties in het halfrond</div></div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div class="vp-card"><div class="vp-kicker">Gem. plenaire aanwezigheid</div><div class="vp-value">{avg_attendance:.1f}%</div>'
            '<div class="vp-subtle">Meteen zicht op discipline in het halfrond</div></div>',
            unsafe_allow_html=True,
        )
    with col4:
        top_fraction_name = top_fraction.iloc[0]["fractie_naam"] if not top_fraction.empty else "n.v.t."
        top_fraction_value = int(top_fraction.iloc[0]["questioner_activity"]) if not top_fraction.empty else 0
        st.markdown(
            f'<div class="vp-card"><div class="vp-kicker">Actiefste fractie</div><div class="vp-value">{top_fraction_name}</div>'
            f'<div class="vp-subtle">{top_fraction_value} dossiers als vraagsteller</div></div>',
            unsafe_allow_html=True,
        )

    hemi = build_hemicycle_frame(member_stats)
    if not hemi.empty:
        st.markdown('<div class="vp-panel">', unsafe_allow_html=True)
        filter_col1, filter_col2 = st.columns([0.7, 0.3])
        with filter_col1:
            visual_mode = st.radio(
                "Visualisatie",
                list(PARLIAMENT_VISUAL_OPTIONS.keys()),
                index=list(PARLIAMENT_VISUAL_OPTIONS.keys()).index(visual_mode),
                horizontal=True,
                label_visibility="collapsed",
                key="parliament_visual_mode",
            )
            visual_config = PARLIAMENT_VISUAL_OPTIONS[visual_mode]
        with filter_col2:
            st.markdown("**Legenda**")
        hemi_display, filter_caption = prepare_hemicycle_colors(hemi, visual_config["hemicycle_filter"])
        st.caption(filter_caption)
        st.caption("Klik op een zetel voor een korte fiche en open daarna het profiel.")
        st.markdown(build_hemicycle_svg(hemi_display, visual_mode=visual_mode), unsafe_allow_html=True)
        st.caption("Zetelindeling op basis van de officiële seat-map van het Vlaams Parlement.")
        popup_row = build_member_popup_card(member_stats, popup_member_id)
        if not popup_row.empty:
            popup = popup_row.iloc[0]
            popup_col1, popup_col2, popup_col3 = st.columns([0.56, 0.24, 0.20])
            with popup_col1:
                st.markdown(f"**{popup['volledige_naam']}**")
                st.caption(
                    f"{popup.get('fractie_naam') or 'n.v.t.'} | zetel {popup.get('zetel') or 'n.v.t.'} | "
                    f"{safe_float(popup.get('plenary_attendance_rate')) * 100:.1f}% plenaire aanwezigheid"
                )
                st.caption(
                    f"{safe_int(popup.get('written_questions_asked'))} schriftelijke vragen | "
                    f"{safe_int(popup.get('oral_items_asked'))} mondelinge vragen | "
                    f"{safe_int(popup.get('total_activity'))} totale activiteit"
                )
            with popup_col2:
                if st.button("Open profiel", key=f"popup_open_profile_{safe_int(popup['member_id'])}"):
                    navigate(
                        "member",
                        selected_member_id=safe_int(popup["member_id"]),
                        selected_fraction_id=coerce_int(popup.get("fractie_id")),
                        popup_member_id=None,
                    )
            with popup_col3:
                if st.button("Sluiten", key=f"popup_close_{safe_int(popup['member_id'])}"):
                    st.session_state["popup_member_id"] = None
                    sync_query_params_from_state()
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    preview_col1, preview_col2 = st.columns([1.2, 0.8])
    with preview_col1:
        st.subheader("Actiefste politici")
        metric_column, metric_axis_label = visual_config["top_metric"]
        top_members_preview = build_top_members_preview(member_stats, metric_column)
        if altair_ready():
            st.altair_chart(build_top_members_visual(member_stats, metric_column, metric_axis_label), use_container_width=True)
        else:
            render_altair_fallback(
                "Actiefste politici",
                top_members_preview,
                ["volledige_naam", "fractie_naam", "metric_value", "attendance_pct", "written_questions_asked", "oral_items_asked"],
            )
        if not top_member.empty:
            st.caption(
                f"Meest actieve vraagsteller: {top_member.iloc[0]['volledige_naam']} "
                f"({int(top_member.iloc[0]['questioner_activity'])} dossiers)."
            )
    with preview_col2:
        st.subheader("Snelle ingangen")
        if not fraction_stats.empty:
            for _, row in fraction_stats.head(6).iterrows():
                with st.container(border=True):
                    st.markdown(f"**{row['fractie_naam']}**")
                    st.caption(
                        f"{int(row['fractie_zetel_aantal'] or row['members'])} zetels | "
                        f"{int(row['questioner_activity'])} dossiers | "
                        f"{row['avg_plenary_attendance_pct']:.1f}% aanwezigheid"
                    )
                    if st.button("Open fractie", key=f"fraction_button_{coerce_int(row['fractie_id'])}"):
                        navigate("fraction", selected_fraction_id=coerce_int(row["fractie_id"]))
        if not committee_stats.empty:
            st.markdown("**Commissies met hoogste gemiddelde activiteit**")
            committee_preview = committee_stats.sort_values("avg_member_activity", ascending=False).head(5)
            if altair_ready():
                committee_chart = (
                    alt.Chart(committee_preview)
                    .mark_bar(cornerRadiusEnd=7)
                    .encode(
                        x=alt.X("avg_member_activity:Q", title="Gem. activiteit per lid"),
                        y=alt.Y("committee_name:N", title=None, sort="-x"),
                        color=alt.Color(
                            "avg_plenary_attendance_pct:Q",
                            scale=alt.Scale(domain=[0, 100], range=["#dc2626", "#facc15", "#16a34a"]),
                            title="Gem. aanwezigheid %",
                        ),
                        tooltip=["committee_name", "members", "oral_items", "avg_member_activity", "avg_plenary_attendance_pct"],
                    )
                    .properties(height=240)
                )
                st.altair_chart(committee_chart, use_container_width=True)
            else:
                render_altair_fallback(
                    "Commissies met hoogste gemiddelde activiteit",
                    committee_preview,
                    ["committee_name", "members", "oral_items", "avg_member_activity", "avg_plenary_attendance_pct"],
                )


def render_fraction_view(
    fraction_stats: pd.DataFrame,
    member_stats: pd.DataFrame,
    committee_memberships: pd.DataFrame,
) -> None:
    st.title("Fractie")
    if fraction_stats.empty:
        st.info("Geen fracties geladen.")
        return

    options = fraction_stats[["fractie_id", "fractie_naam"]].dropna().drop_duplicates()
    option_map = {row["fractie_naam"]: coerce_int(row["fractie_id"]) for _, row in options.iterrows()}
    names = list(option_map.keys())
    selected_fraction_id = st.session_state.get("selected_fraction_id")
    selected_name = next((name for name, value in option_map.items() if value == selected_fraction_id), names[0])
    selected_name = st.selectbox("Kies een fractie", names, index=names.index(selected_name))
    selected_fraction_id = option_map[selected_name]
    st.session_state["selected_fraction_id"] = selected_fraction_id

    detail = fraction_stats[fraction_stats["fractie_id"].apply(coerce_int) == selected_fraction_id].iloc[0]
    members_in_fraction = member_stats[member_stats["fractie_id"].apply(coerce_int) == selected_fraction_id].copy()
    members_in_fraction = members_in_fraction.sort_values(["questioner_activity", "total_activity"], ascending=False)

    top_member = members_in_fraction.head(1)
    col_back, col_title = st.columns([0.2, 0.8])
    with col_back:
        if st.button("← Parlement", key="back_to_parliament"):
            navigate("parliament")
    with col_title:
        st.subheader(detail["fractie_naam"])

    logo_url = detail.get("fractie_logo_url")
    info_col, metric_col = st.columns([1, 1.2])
    with info_col:
        if pd.notna(logo_url) and logo_url:
            st.image(logo_url, width=180)
        st.markdown(f"**Kleur:** `{color_with_hash(detail.get('fractie_kleur'))}`")
        st.markdown(f"**Volgnummer:** {int(detail.get('fractie_volgnr') or 0)}")
    with metric_col:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Zetels", int(detail.get("fractie_zetel_aantal") or len(members_in_fraction)))
        c2.metric("Dossiers als vraagsteller", int(detail.get("questioner_activity") or 0))
        c3.metric("Totale betrokkenheid", int(detail.get("total_activity") or 0))
        c4.metric(
            "Gem. plenaire aanwezigheid",
            f"{float(detail.get('avg_plenary_attendance_pct') or 0):.1f}%",
        )
        if not top_member.empty:
            st.caption(
                f"Actiefste politicus in deze fractie: {top_member.iloc[0]['volledige_naam']} "
                f"({int(top_member.iloc[0]['questioner_activity'])} dossiers)."
            )

    st.subheader("Leden")
    st.dataframe(
        members_in_fraction[
            [
                "volledige_naam",
                "kieskring",
                "zetel",
                "written_questions_asked",
                "oral_items_asked",
                "questioner_activity",
                "plenary_attendance_rate",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    member_button_cols = st.columns(4)
    for index, row in members_in_fraction.reset_index(drop=True).iterrows():
        with member_button_cols[index % 4]:
            st.markdown(f"**{row['volledige_naam']}**")
            st.caption(
                f"{row['kieskring']} | {int(row['questioner_activity'])} dossiers | "
                f"{(row['plenary_attendance_rate'] or 0) * 100:.1f}% aanwezigheid"
            )
            if st.button("Open politicus", key=f"member_button_{coerce_int(row['member_id'])}"):
                navigate("member", selected_member_id=coerce_int(row["member_id"]), selected_fraction_id=selected_fraction_id)

    if not committee_memberships.empty:
        committee_rows = committee_memberships[committee_memberships["fractie_id"].apply(coerce_int) == selected_fraction_id]
        if not committee_rows.empty:
            st.subheader("Commissierollen")
            grouped = (
                committee_rows.groupby(["committee_name", "role_name"], dropna=False)
                .size()
                .reset_index(name="aantal")
                .sort_values(["committee_name", "aantal"], ascending=[True, False])
            )
            st.dataframe(grouped, use_container_width=True, hide_index=True)


def render_member_view(
    member_stats: pd.DataFrame,
    memberships: pd.DataFrame,
    mandates_vp: pd.DataFrame,
    mandates_vp_other: pd.DataFrame,
    mandates_other: pd.DataFrame,
    attendance: pd.DataFrame,
    committee_memberships: pd.DataFrame,
    websites: pd.DataFrame,
    emails: pd.DataFrame,
    education: pd.DataFrame,
    professions: pd.DataFrame,
    interests: pd.DataFrame,
    functions: pd.DataFrame,
    honors: pd.DataFrame,
    written_links: pd.DataFrame,
    oral_links: pd.DataFrame,
    member_api_payloads: pd.DataFrame,
    member_ai_overviews: pd.DataFrame,
) -> None:
    render_breadcrumb(["Parlement", "Fractie", "Politicus"])
    st.title("Politicus")
    if member_stats.empty:
        st.info("Geen leden geladen.")
        return

    options = member_stats[["member_id", "volledige_naam"]].dropna().drop_duplicates().sort_values("volledige_naam")
    option_map = {row["volledige_naam"]: coerce_int(row["member_id"]) for _, row in options.iterrows()}
    names = list(option_map.keys())
    selected_member_id = st.session_state.get("selected_member_id")
    if selected_member_id not in option_map.values():
        selected_member_id = option_map[names[0]]
    selected_name = next((name for name, value in option_map.items() if value == selected_member_id), names[0])
    selected_name = st.selectbox("Kies een politicus", names, index=names.index(selected_name))
    selected_member_id = option_map[selected_name]
    st.session_state["selected_member_id"] = selected_member_id

    detail = member_stats[member_stats["member_id"].apply(coerce_int) == selected_member_id].iloc[0]
    parent_fraction_id = coerce_int(detail.get("fractie_id"))
    member_id_mask = lambda frame, column="member_id": frame[column].apply(coerce_int) == selected_member_id if not frame.empty else []
    committee_rows = committee_memberships[member_id_mask(committee_memberships)]
    interests_rows = interests[member_id_mask(interests)] if not interests.empty else pd.DataFrame()
    professions_rows = professions[member_id_mask(professions)] if not professions.empty else pd.DataFrame()
    functions_rows = functions[member_id_mask(functions)] if not functions.empty else pd.DataFrame()
    written_rows = written_links[member_id_mask(written_links)]
    oral_rows = oral_links[member_id_mask(oral_links)]
    subjects = (
        written_rows.get("onderwerp", pd.Series(dtype=str)).dropna().astype(str).tolist()
        + oral_rows.get("onderwerp", pd.Series(dtype=str)).dropna().astype(str).tolist()
    )
    interest_labels = interests_rows.get("interesse", pd.Series(dtype=str)).dropna().astype(str).tolist()
    committee_labels = committee_rows.get("committee_name", pd.Series(dtype=str)).dropna().astype(str).drop_duplicates().tolist()
    weighted_context = (interest_labels * 2) + (committee_labels * 4)
    theme_frame = extract_member_themes(subjects, interests=weighted_context, limit=5)
    activity_breakdown = build_member_activity_breakdown(detail)
    attendance_breakdown = build_member_attendance_breakdown(detail)
    recent_activity = build_member_recent_activity(written_links, oral_links, selected_member_id)
    overview_rows = member_ai_overviews[member_id_mask(member_ai_overviews)] if not member_ai_overviews.empty else pd.DataFrame()
    if overview_rows.empty:
        overview_text = build_member_overview_text(
            detail,
            committee_rows,
            interests_rows,
            professions_rows,
            functions_rows,
            written_rows,
            oral_rows,
        )
        overview_generator = "live-fallback"
        overview_model = "pending-provider"
    else:
        overview_text = str(overview_rows.iloc[0].get("summary_text") or "").strip()
        overview_generator = overview_rows.iloc[0].get("generator") or "onbekend"
        overview_model = overview_rows.iloc[0].get("model") or "onbekend"

    nav_col1, nav_col2 = st.columns([0.2, 0.8])
    with nav_col1:
        if parent_fraction_id and st.button("Terug naar fractie", key="back_to_fraction"):
            navigate("fraction", selected_fraction_id=parent_fraction_id)
    with nav_col2:
        st.subheader(detail["volledige_naam"])

    profile_links = []
    for label, value in [
        ("Officiële pagina", detail.get("website_officieel") or detail.get("website")),
        ("Open data", detail.get("self_opendata_url")),
        ("Foto bron", detail.get("photo_source_url") or detail.get("fotowebpath")),
    ]:
        if pd.notna(value) and value:
            profile_links.append(f"[{label}]({value})")

    left, right = st.columns([0.62, 1.38])
    with left:
        with st.container(border=True):
            photo_ref = resolve_member_photo(detail)
            if photo_ref:
                st.image(photo_ref, use_container_width=True)
            st.markdown(f"### {detail['volledige_naam']}")
            st.caption(f"{detail.get('fractie_naam') or 'n.v.t.'} | zetel {detail.get('zetel') or 'n.v.t.'}")
            st.markdown(f"**Kieskring**: {detail.get('kieskring') or 'n.v.t.'}")
            st.markdown(f"**E-mail**: {detail.get('email') or 'n.v.t.'}")
            st.markdown(f"**Gsm**: {detail.get('gsm') or 'n.v.t.'}")
            st.markdown(f"**Geboorteplaats**: {detail.get('geboorteplaats') or 'n.v.t.'}")
            st.markdown(f"**Geboortedatum**: {detail.get('geboortedatum') or 'n.v.t.'}")
            if profile_links:
                st.markdown(" | ".join(profile_links))
            office_parts = [
                str(value)
                for value in [
                    detail.get("kantoor_straat"),
                    detail.get("kantoor_nr"),
                    detail.get("kantoor_postcode"),
                    detail.get("kantoor_gemeente"),
                ]
                if pd.notna(value) and value not in ("", "nan")
            ]
            st.markdown("**Kantoor**")
            st.caption(", ".join(office_parts) if office_parts else "n.v.t.")

    with right:
        with st.container(border=True):
            summary_col1, summary_col2 = st.columns([0.78, 0.22])
            with summary_col1:
                st.markdown("**AI-overzicht**")
                st.caption(f"Bron: {overview_generator} | model: {overview_model}")
            with summary_col2:
                if st.button("Refresh overzicht", key=f"refresh_ai_overview_{selected_member_id}"):
                    write_member_ai_overviews()
                    st.rerun()
            st.markdown(overview_text.replace("\n", "\n\n"))
            st.markdown("**Beleidsthema's**")
            if theme_frame.empty:
                st.caption("Nog geen duidelijke thematische profilering afgeleid uit de huidige dossiers.")
            else:
                st.markdown(" ".join([f"`{theme}`" for theme in theme_frame["theme"].tolist()]))

        metrics_top = st.columns(4)
        metrics_top[0].metric("Schriftelijke vragen", int(detail.get("written_questions_asked") or 0))
        metrics_top[1].metric("Mondelinge vragen", int(detail.get("oral_items_asked") or 0))
        metrics_top[2].metric("Vraagsteller-activiteit", int(detail.get("questioner_activity") or 0))
        metrics_top[3].metric("Plenaire aanwezigheid", f"{safe_float(detail.get('plenary_attendance_rate')) * 100:.1f}%")

        metrics_bottom = st.columns(4)
        metrics_bottom[0].metric("Ministerrol schriftelijk", int(detail.get("written_questions_as_minister") or 0))
        metrics_bottom[1].metric("Ministerrol mondeling", int(detail.get("oral_items_as_minister") or 0))
        metrics_bottom[2].metric("Commissies", int(committee_rows["committee_id"].nunique() if not committee_rows.empty else 0))
        metrics_bottom[3].metric("Commissie-aanwezigheid", f"{safe_float(detail.get('committee_attendance_rate')) * 100:.1f}%")

        chart_col1, chart_col2, chart_col3 = st.columns([1.05, 1.05, 0.9])
        with chart_col1:
            with st.container(border=True):
                st.markdown("**Activiteitsmix**")
                if altair_ready():
                    activity_chart = (
                        alt.Chart(activity_breakdown)
                        .mark_bar(cornerRadiusEnd=6)
                        .encode(
                            x=alt.X("aantal:Q", title="Aantal dossiers"),
                            y=alt.Y("label:N", title=None, sort="-x"),
                            color=alt.Color(
                                "rol:N",
                                scale=alt.Scale(domain=["Vraagsteller", "Minister"], range=["#2563eb", "#9333ea"]),
                            ),
                            tooltip=["categorie", "rol", "aantal"],
                        )
                        .properties(height=240)
                    )
                    st.altair_chart(activity_chart, use_container_width=True)
                else:
                    render_altair_fallback("Activiteitsmix", activity_breakdown, ["categorie", "rol", "aantal"])
        with chart_col2:
            with st.container(border=True):
                st.markdown("**Themaprofiel**")
                if theme_frame.empty:
                    st.caption("Nog onvoldoende thematische signalen.")
                else:
                    theme_display = theme_frame.sort_values("score", ascending=True)
                    if altair_ready():
                        theme_chart = (
                            alt.Chart(theme_display)
                            .mark_bar(cornerRadiusEnd=6)
                            .encode(
                                x=alt.X("score:Q", title="Themascore"),
                                y=alt.Y("theme:N", title=None),
                                color=alt.Color(
                                    "score:Q",
                                    scale=alt.Scale(range=["#f59e0b", "#ea580c", "#b91c1c"]),
                                    legend=None,
                                ),
                                tooltip=["theme", "score", "matches"],
                            )
                            .properties(height=240)
                        )
                        st.altair_chart(theme_chart, use_container_width=True)
                    else:
                        render_altair_fallback("Themaprofiel", theme_display, ["theme", "score", "matches"])
        with chart_col3:
            with st.container(border=True):
                st.markdown("**Snelle lezing**")
                st.caption(
                    f"Plenair aanwezig: {int(detail.get('plenary_present') or 0)} / "
                    f"{safe_int(detail.get('plenary_total'))}"
                )
                st.progress(safe_float(detail.get("plenary_attendance_rate")))
                st.caption(
                    f"Commissie aanwezig: {int(detail.get('committee_present') or 0)} / "
                    f"{safe_int(detail.get('committee_total'))}"
                )
                st.progress(safe_float(detail.get("committee_attendance_rate")))
                latest_label = recent_activity.iloc[0]["publicatiedatum"] if not recent_activity.empty else "n.v.t."
                st.metric("Laatste activiteit", latest_label)
                st.metric("Recente dossiers", len(recent_activity))

        with st.container(border=True):
            st.markdown("**Aanwezigheid**")
            if altair_ready():
                attendance_chart = (
                    alt.Chart(attendance_breakdown)
                    .mark_bar(cornerRadiusEnd=6)
                    .encode(
                        x=alt.X("sum(aantal):Q", title="Aantal registraties"),
                        y=alt.Y("scope:N", title=None),
                        color=alt.Color(
                            "status:N",
                            scale=alt.Scale(
                                domain=["Aanwezig", "Afwezig", "Verontschuldigd"],
                                range=["#16a34a", "#dc2626", "#f59e0b"],
                            ),
                        ),
                        order=alt.Order("status:N", sort="ascending"),
                        tooltip=["scope", "status", "aantal"],
                    )
                    .properties(height=210)
                )
                st.altair_chart(attendance_chart, use_container_width=True)
            else:
                render_altair_fallback("Aanwezigheid", attendance_breakdown, ["scope", "status", "aantal"])

        with st.container(border=True):
            st.markdown("**Recente activiteit**")
            if recent_activity.empty:
                st.caption("Nog geen recente vragen of mondelinge dossiers gevonden voor deze politicus.")
            else:
                st.dataframe(recent_activity, use_container_width=True, hide_index=True)

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
        ["Activiteit", "Aanwezigheid", "Mandaten", "Commissies", "Bio", "Contact", "API raw"]
    )
    with tab1:
        st.markdown("**Schriftelijke vragen / rollen**")
        st.dataframe(
            written_rows,
            use_container_width=True,
            hide_index=True,
        )
        st.markdown("**Mondelinge vragen / rollen**")
        st.dataframe(
            oral_rows,
            use_container_width=True,
            hide_index=True,
        )
    with tab2:
        st.dataframe(
            attendance[member_id_mask(attendance)],
            use_container_width=True,
            hide_index=True,
        )
    with tab3:
        st.markdown("**Mandaten in Vlaams Parlement**")
        st.dataframe(mandates_vp[member_id_mask(mandates_vp)], use_container_width=True, hide_index=True)
        extra_vp = mandates_vp_other[member_id_mask(mandates_vp_other)]
        if not extra_vp.empty:
            st.markdown("**Andere VP-mandaten**")
            st.dataframe(extra_vp, use_container_width=True, hide_index=True)
        st.markdown("**Andere mandaten**")
        st.dataframe(mandates_other[member_id_mask(mandates_other)], use_container_width=True, hide_index=True)
        st.markdown("**Fractiehistoriek**")
        st.dataframe(memberships[member_id_mask(memberships)], use_container_width=True, hide_index=True)
    with tab4:
        st.dataframe(committee_rows, use_container_width=True, hide_index=True)
        if not committee_rows.empty:
            cols = st.columns(3)
            for index, row in committee_rows.reset_index(drop=True).iterrows():
                with cols[index % 3]:
                    st.markdown(f"**{row['committee_name']}**")
                    st.caption(row["role_name"])
                    if st.button("Open commissie", key=f"committee_from_member_{index}_{coerce_int(row['committee_id'])}"):
                        navigate("committee", selected_committee_id=coerce_int(row["committee_id"]))
    with tab5:
        st.markdown("**Opleiding**")
        st.dataframe(education[member_id_mask(education)], use_container_width=True, hide_index=True)
        st.markdown("**Beroep**")
        st.dataframe(professions_rows, use_container_width=True, hide_index=True)
        st.markdown("**Interesses**")
        st.dataframe(interests_rows, use_container_width=True, hide_index=True)
        st.markdown("**Functies**")
        st.dataframe(functions_rows, use_container_width=True, hide_index=True)
        st.markdown("**Eretekens**")
        st.dataframe(honors[member_id_mask(honors)], use_container_width=True, hide_index=True)
    with tab6:
        st.markdown("**E-mailadressen**")
        st.dataframe(emails[member_id_mask(emails)], use_container_width=True, hide_index=True)
        st.markdown("**Websites en socials**")
        st.dataframe(websites[member_id_mask(websites)], use_container_width=True, hide_index=True)
    with tab7:
        raw_row = member_api_payloads[member_id_mask(member_api_payloads)]
        if raw_row.empty:
            st.info("Geen ruwe payload gevonden.")
        else:
            st.json(json.loads(raw_row.iloc[0]["payload_json"]))


def render_committee_view(
    committee_stats: pd.DataFrame,
    committee_memberships: pd.DataFrame,
    committee_secretaries: pd.DataFrame,
    oral_items: pd.DataFrame,
) -> None:
    render_breadcrumb(["Parlement", "Commissie"])
    st.title("Commissie")
    if committee_stats.empty:
        st.info("Geen commissies geladen.")
        return

    options = committee_stats[["committee_id", "committee_name"]].dropna().drop_duplicates().sort_values("committee_name")
    option_map = {row["committee_name"]: coerce_int(row["committee_id"]) for _, row in options.iterrows()}
    names = list(option_map.keys())
    selected_committee_id = st.session_state.get("selected_committee_id")
    if selected_committee_id not in option_map.values():
        selected_committee_id = option_map[names[0]]
    selected_name = next((name for name, value in option_map.items() if value == selected_committee_id), names[0])
    selected_name = st.selectbox("Kies een commissie", names, index=names.index(selected_name))
    selected_committee_id = option_map[selected_name]
    st.session_state["selected_committee_id"] = selected_committee_id

    detail = committee_stats[committee_stats["committee_id"].apply(coerce_int) == selected_committee_id].iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Leden", int(detail.get("members") or 0))
    c2.metric("Rollen", int(detail.get("roles") or 0))
    c3.metric("Mondelinge dossiers", int(detail.get("oral_items") or 0))
    c4.metric("Gem. plenaire aanwezigheid", f"{float(detail.get('avg_plenary_attendance_pct') or 0):.1f}%")
    st.caption(detail.get("ministers") or "")

    members = committee_memberships[committee_memberships["committee_id"].apply(coerce_int) == selected_committee_id]
    secretaries = committee_secretaries[committee_secretaries["committee_id"].apply(coerce_int) == selected_committee_id]
    committee_oral = oral_items[oral_items["commissie_id"].apply(coerce_int) == selected_committee_id]

    st.subheader("Leden en rollen")
    st.dataframe(members, use_container_width=True, hide_index=True)
    if not members.empty:
        cols = st.columns(3)
        unique_members = members.drop_duplicates(subset=["member_id"])
        for index, row in unique_members.reset_index(drop=True).iterrows():
            with cols[index % 3]:
                st.markdown(f"**{row['member_name']}**")
                st.caption(f"{row['fractie_naam']} | {row['role_name']}")
                if st.button("Open politicus", key=f"member_from_committee_{index}_{coerce_int(row['member_id'])}"):
                    navigate("member", selected_member_id=coerce_int(row["member_id"]), selected_fraction_id=coerce_int(row["fractie_id"]))

    st.subheader("Commissiesecretariaat")
    st.dataframe(secretaries, use_container_width=True, hide_index=True)

    st.subheader("Mondelinge vragen en interpellaties")
    st.dataframe(
        committee_oral[
            ["publicatiedatum", "objecttype", "vraagstellers", "onderwerp", "objectstatus", "displayurl"]
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_meetings_view(
    meetings: pd.DataFrame,
    meeting_committees: pd.DataFrame,
    agenda_lines: pd.DataFrame,
    agenda_references: pd.DataFrame,
    proceeding_lines: pd.DataFrame,
) -> None:
    st.title("Agenda en Vergaderingen")
    if meetings.empty:
        st.warning("Vergaderingen en agenda zitten nog niet in de actieve snapshot. De datalaag is voorbereid, maar nog niet succesvol meegesynchroniseerd.")
        return

    meetings_frame = meetings.copy()
    for column in ["datum_begin", "datum_agendering"]:
        if column in meetings_frame.columns:
            meetings_frame[column] = pd.to_datetime(meetings_frame[column], errors="coerce")

    col1, col2, col3 = st.columns(3)
    meeting_type = col1.selectbox("Type", ["Alle"] + sorted([value for value in meetings_frame["type"].dropna().unique().tolist() if value]))
    meeting_status = col2.selectbox("Status", ["Alle"] + sorted([value for value in meetings_frame["status"].dropna().unique().tolist() if value]))
    search = col3.text_input("Zoekterm", "")

    filtered = meetings_frame.copy()
    if meeting_type != "Alle":
        filtered = filtered[filtered["type"] == meeting_type]
    if meeting_status != "Alle":
        filtered = filtered[filtered["status"] == meeting_status]
    if search:
        needle = search.lower()
        filtered = filtered[
            filtered["omschrijving_kort"].fillna("").str.lower().str.contains(needle)
            | filtered["omschrijving_preview"].fillna("").str.lower().str.contains(needle)
            | filtered["subtype"].fillna("").str.lower().str.contains(needle)
        ]

    filtered = filtered.sort_values(["datum_begin", "meeting_id"], ascending=[False, False])
    preview = filtered[
        [
            "datum_begin",
            "type",
            "subtype",
            "status",
            "omschrijving_kort",
            "chair_name",
            "agenda_url",
            "handelingen_url",
        ]
    ]
    st.dataframe(preview, use_container_width=True, hide_index=True)

    options = filtered[["meeting_id", "omschrijving_kort", "datum_begin"]].copy()
    options["label"] = options.apply(
        lambda row: f"{row['datum_begin'].date() if pd.notna(row['datum_begin']) else 'onbekend'} | {row['omschrijving_kort'] or row['meeting_id']}",
        axis=1,
    )
    selected_label = st.selectbox("Detailvergadering", options["label"].tolist())
    selected_id = int(options.loc[options["label"] == selected_label, "meeting_id"].iloc[0])
    detail = meetings_frame[meetings_frame["meeting_id"] == selected_id].iloc[0]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Agenda-lijnen", int((agenda_lines["meeting_id"] == selected_id).sum()) if not agenda_lines.empty else 0)
    m2.metric("Referenties", int((agenda_references["meeting_id"] == selected_id).sum()) if not agenda_references.empty else 0)
    m3.metric("Journaallijnen", int((proceeding_lines["meeting_id"] == selected_id).sum()) if not proceeding_lines.empty else 0)
    m4.metric("Commissies", int((meeting_committees["meeting_id"] == selected_id).sum()) if not meeting_committees.empty else 0)

    st.markdown(f"**Omschrijving:** {detail.get('omschrijving_preview') or detail.get('omschrijving_kort') or 'n.v.t.'}")
    st.markdown(f"**Voorzitter:** {detail.get('chair_name') or 'n.v.t.'}")
    st.markdown(f"**Agenda-link:** {detail.get('agenda_url') or 'n.v.t.'}")
    st.markdown(f"**Handelingen-link:** {detail.get('handelingen_url') or 'n.v.t.'}")

    tab1, tab2, tab3 = st.tabs(["Agenda", "Referenties", "Handelingen"])
    with tab1:
        st.dataframe(agenda_lines[agenda_lines["meeting_id"] == selected_id], use_container_width=True, hide_index=True)
    with tab2:
        st.dataframe(
            agenda_references[agenda_references["meeting_id"] == selected_id],
            use_container_width=True,
            hide_index=True,
        )
    with tab3:
        st.dataframe(
            proceeding_lines[proceeding_lines["meeting_id"] == selected_id],
            use_container_width=True,
            hide_index=True,
        )


def render_texts_view(parliamentary_texts: pd.DataFrame) -> None:
    st.title("Parlementaire Teksten")
    if parliamentary_texts.empty:
        st.warning("Parlementaire teksten zitten nog niet in de actieve snapshot. Voor de MVP werken we voorlopig met de andere domeinen.")
        return

    col1, col2, col3 = st.columns(3)
    objecttype = col1.selectbox(
        "Type tekst",
        ["Alle"] + sorted([value for value in parliamentary_texts["objecttype"].dropna().unique().tolist() if value]),
    )
    source = col2.selectbox(
        "Bron",
        ["Alle"] + sorted([value for value in parliamentary_texts["source"].dropna().unique().tolist() if value]),
    )
    term = col3.text_input("Zoekterm", "")

    filtered = parliamentary_texts.copy()
    if objecttype != "Alle":
        filtered = filtered[filtered["objecttype"] == objecttype]
    if source != "Alle":
        filtered = filtered[filtered["source"] == source]
    if term:
        needle = term.lower()
        filtered = filtered[
            filtered["titel"].fillna("").str.lower().str.contains(needle)
            | filtered["onderwerp"].fillna("").str.lower().str.contains(needle)
            | filtered["nummer"].fillna("").astype(str).str.lower().str.contains(needle)
        ]

    filtered = filtered.sort_values(["meeting_id", "nummer", "volgnr"], ascending=[False, False, False])
    st.dataframe(
        filtered[
            [
                "meeting_id",
                "source",
                "objecttype",
                "nummer",
                "volgnr",
                "titel",
                "onderwerp",
                "document_url",
                "opendata_url",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_written_questions(written_questions: pd.DataFrame) -> None:
    st.title("Schriftelijke vragen")
    if written_questions.empty:
        st.info("Geen schriftelijke vragen geladen.")
        return

    col1, col2, col3 = st.columns(3)
    questioner = col1.selectbox(
        "Vraagsteller",
        ["Alle"] + sorted([value for value in written_questions["vraagsteller_naam"].dropna().unique().tolist() if value]),
    )
    minister = col2.selectbox(
        "Minister",
        ["Alle"] + sorted([value for value in written_questions["minister_naam"].dropna().unique().tolist() if value]),
    )
    term = col3.text_input("Zoekterm", value="")

    filtered = written_questions.copy()
    if questioner != "Alle":
        filtered = filtered[filtered["vraagsteller_naam"] == questioner]
    if minister != "Alle":
        filtered = filtered[filtered["minister_naam"] == minister]
    if term:
        needle = term.lower()
        filtered = filtered[
            filtered["onderwerp"].str.lower().str.contains(needle, na=False)
            | filtered["titel"].str.lower().str.contains(needle, na=False)
        ]

    filtered = filtered.sort_values(["publicatiedatum", "question_id"], ascending=[False, False])
    st.dataframe(
        filtered[
            [
                "publicatiedatum",
                "vraagnummer",
                "vraagsteller_naam",
                "minister_naam",
                "onderwerp",
                "tijdig",
                "displayurl",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_oral_items(oral_items: pd.DataFrame) -> None:
    st.title("Vragen en interpellaties")
    if oral_items.empty:
        st.info("Geen vragen/interpellaties geladen.")
        return

    col1, col2, col3 = st.columns(3)
    item_type = col1.selectbox(
        "Type",
        ["Alle"] + sorted([value for value in oral_items["objecttype"].dropna().unique().tolist() if value]),
    )
    committee = col2.selectbox(
        "Commissie",
        ["Alle"] + sorted([value for value in oral_items["commissie_naam"].dropna().unique().tolist() if value]),
    )
    term = col3.text_input("Zoekterm", value="")

    filtered = oral_items.copy()
    if item_type != "Alle":
        filtered = filtered[filtered["objecttype"] == item_type]
    if committee != "Alle":
        filtered = filtered[filtered["commissie_naam"] == committee]
    if term:
        needle = term.lower()
        filtered = filtered[
            filtered["onderwerp"].str.lower().str.contains(needle, na=False)
            | filtered["titel"].str.lower().str.contains(needle, na=False)
            | filtered["vraagstellers"].str.lower().str.contains(needle, na=False)
        ]

    filtered = filtered.sort_values(["publicatiedatum", "oral_item_id"], ascending=[False, False])
    st.dataframe(
        filtered[
            [
                "publicatiedatum",
                "objecttype",
                "vraagstellers",
                "commissie_naam",
                "onderwerp",
                "objectstatus",
                "displayurl",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_admin(state: dict) -> None:
    st.title("Beheer")
    workbook_path = Path(state.get("published_workbook", PUBLISHED_DIR / "vlaams_parlement_data.xlsx"))
    store_path = current_store_dir(state)
    st.markdown(f"**Excel-export:** `{workbook_path}`")
    st.markdown(f"**Actieve snapshot:** `{store_path}`")
    st.markdown(
        """
        Volledige vulling sinds start legislatuur:

        ```powershell
        python .\\scripts\\sync_vlaams_parlement.py --since 2024-06-09 --max-pages 120
        ```

        Wekelijkse incrementele update:

        ```powershell
        python .\\scripts\\sync_vlaams_parlement.py
        ```

        AI-overzichten opnieuw opbouwen:

        ```powershell
        python .\\scripts\\generate_member_ai_overviews.py
        ```
        """
    )
    st.subheader("Sync state")
    st.json(state)


def render_sidebar_snapshot_summary(data_status: pd.DataFrame) -> None:
    st.sidebar.markdown("**Snapshotstatus**")
    for _, row in data_status.iterrows():
        label = row["Domein"]
        status = row["Status"]
        if status == "Beschikbaar":
            st.sidebar.caption(f"{label}: klaar")
        else:
            st.sidebar.caption(f"{label}: beperkt")


def main() -> None:
    sync_state_from_query_params()
    state = load_state()
    members = load_table("members")
    if members.empty:
        render_missing_data()
        return

    fractions = load_table("fractions")
    memberships = load_table("member_memberships")
    mandates_vp = load_table("member_mandates_vp")
    mandates_vp_other = load_table("member_mandates_vp_other")
    mandates_other = load_table("member_mandates_other")
    attendance = load_table("member_attendance")
    committee_memberships = load_table("committee_memberships")
    committee_secretaries = load_table("committee_secretaries")
    committees = load_table("committees")
    meetings = load_table("meetings")
    meeting_committees = load_table("meeting_committees")
    agenda_lines = load_table("agenda_lines")
    agenda_references = load_table("agenda_line_references")
    proceeding_lines = load_table("proceeding_lines")
    parliamentary_texts = load_table("parliamentary_texts")
    websites = load_table("member_websites")
    emails = load_table("member_emails")
    education = load_table("member_education")
    professions = load_table("member_professions")
    interests = load_table("member_interests")
    functions = load_table("member_functions")
    honors = load_table("member_honors")
    written_questions = load_table("written_questions")
    oral_items = load_table("oral_items")
    written_links = load_table("member_written_question_links")
    oral_links = load_table("member_oral_item_links")
    member_api_payloads = load_table("member_api_payloads")
    member_ai_overviews = load_table("member_ai_overviews")

    member_stats = build_member_stats(members, attendance, written_links, oral_links)
    fraction_stats = build_fraction_stats(fractions, member_stats)
    committee_stats = build_committee_stats(committees, committee_memberships, member_stats, oral_items)
    data_status = build_data_status(
        state,
        {
            "members": members,
            "fractions": fractions,
            "committees": committees,
            "written_questions": written_questions,
            "oral_items": oral_items,
            "meetings": meetings,
            "parliamentary_texts": parliamentary_texts,
        },
    )

    if "view_key" not in st.session_state:
        st.session_state["view_key"] = "parliament"

    render_data_status_banner(state, data_status)
    current_label = next(label for label, key in VIEW_OPTIONS.items() if key == st.session_state["view_key"])
    selected_label = st.sidebar.radio("Navigatie", list(VIEW_OPTIONS.keys()), index=list(VIEW_OPTIONS.keys()).index(current_label))
    st.session_state["view_key"] = VIEW_OPTIONS[selected_label]
    sync_query_params_from_state()
    render_sidebar_snapshot_summary(data_status)

    if st.session_state["view_key"] == "parliament":
        render_parliament_view(member_stats, fraction_stats, committee_stats)
    elif st.session_state["view_key"] == "fraction":
        render_fraction_view(fraction_stats, member_stats, committee_memberships)
    elif st.session_state["view_key"] == "member":
        render_member_view(
            member_stats,
            memberships,
            mandates_vp,
            mandates_vp_other,
            mandates_other,
            attendance,
            committee_memberships,
            websites,
            emails,
            education,
            professions,
            interests,
            functions,
            honors,
            written_links,
            oral_links,
            member_api_payloads,
            member_ai_overviews,
        )
    elif st.session_state["view_key"] == "committee":
        render_committee_view(committee_stats, committee_memberships, committee_secretaries, oral_items)
    elif st.session_state["view_key"] == "meetings":
        render_meetings_view(meetings, meeting_committees, agenda_lines, agenda_references, proceeding_lines)
    elif st.session_state["view_key"] == "texts":
        render_texts_view(parliamentary_texts)
    elif st.session_state["view_key"] == "written":
        render_written_questions(written_questions)
    elif st.session_state["view_key"] == "oral":
        render_oral_items(oral_items)
    else:
        render_admin(state)


if __name__ == "__main__":
    main()
