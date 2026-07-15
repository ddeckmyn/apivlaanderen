from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from member_topics import top_theme_labels
from vp_pipeline import STATE_DIR, current_store_dir, read_json


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def coerce_int(value) -> int | None:
    if pd.isna(value) or value in ("", None):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_int(value) -> int:
    if pd.isna(value) or value in ("", None):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def safe_float(value) -> float:
    if pd.isna(value) or value in ("", None):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def active_store_dir() -> Path:
    state = read_json(STATE_DIR / "sync_state.json", default={})
    return current_store_dir(state)


def load_store_table(store_dir: Path, name: str) -> pd.DataFrame:
    path = store_dir / f"{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def build_member_stats_for_overviews(
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
            attendance_frame[attendance_frame["scope"] == "plenaire"][["member_id", "aanwezig", "afwezig", "verontschuldigd"]]
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


def build_member_overview_text(
    detail: pd.Series,
    committee_rows: pd.DataFrame,
    interests_rows: pd.DataFrame,
    professions_rows: pd.DataFrame,
    functions_rows: pd.DataFrame,
    written_rows: pd.DataFrame,
    oral_rows: pd.DataFrame,
) -> str:
    full_name = detail.get("volledige_naam") or "Deze politicus"
    party = detail.get("fractie_naam") or "onbekende fractie"
    district = detail.get("kieskring") or "onbekende kieskring"
    seat = detail.get("zetel") or "onbekend"
    questioner_activity = safe_int(detail.get("questioner_activity"))
    written_count = safe_int(detail.get("written_questions_asked"))
    oral_count = safe_int(detail.get("oral_items_asked"))
    minister_activity = safe_int(detail.get("minister_activity"))
    plenary_rate = safe_float(detail.get("plenary_attendance_rate")) * 100
    committee_rate = safe_float(detail.get("committee_attendance_rate")) * 100

    committee_names = committee_rows["committee_name"].dropna().astype(str).drop_duplicates().tolist()
    committee_roles = committee_rows["role_name"].dropna().astype(str).drop_duplicates().tolist()
    interests = interests_rows.get("interesse", pd.Series(dtype=str)).dropna().astype(str).tolist()[:3]
    current_professions = professions_rows.get("titel", pd.Series(dtype=str)).dropna().astype(str).tolist()[:2]
    functions = functions_rows.get("omschrijving", pd.Series(dtype=str)).dropna().astype(str).tolist()[:2]
    subjects = (
        written_rows.get("onderwerp", pd.Series(dtype=str)).dropna().astype(str).tolist()
        + oral_rows.get("onderwerp", pd.Series(dtype=str)).dropna().astype(str).tolist()
    )
    weighted_context = (interests * 2) + (committee_names * 4)
    theme_labels = top_theme_labels(subjects, interests=weighted_context, limit=3)

    activity_label = "zeer actief" if questioner_activity >= 150 else "actief" if questioner_activity >= 60 else "eerder selectief actief"
    presence_label = "sterk aanwezig" if plenary_rate >= 95 else "redelijk aanwezig" if plenary_rate >= 85 else "wisselend aanwezig"

    lines = [
        f"{full_name} zetelt voor {party} en vertegenwoordigt {district} vanuit zetel {seat}.",
        f"In het parlementaire werk is deze politicus {activity_label}, met {written_count} schriftelijke en {oral_count} mondelinge tussenkomsten als vraagsteller.",
        f"De plenaire aanwezigheid bedraagt {plenary_rate:.1f}% en de commissie-aanwezigheid {committee_rate:.1f}%, wat wijst op een profiel dat {presence_label} is.",
    ]

    if theme_labels:
        lines.append(f"De meest zichtbare beleidsthema's zijn {', '.join(theme_labels)}.")
    elif interests:
        lines.append(f"Op basis van de beschikbare profieldata springen thema's zoals {', '.join(interests)} het meest in het oog.")
    else:
        lines.append("Er zijn nog geen duidelijke thematische zwaartepunten af te leiden uit de huidige dataset.")

    if committee_names:
        lines.append(f"Commissiewerk loopt onder meer via {', '.join(committee_names[:2])}{' en andere commissies' if len(committee_names) > 2 else ''}.")
    elif committee_roles:
        lines.append(f"In de commissies is vooral een rol zichtbaar als {committee_roles[0]}.")
    else:
        lines.append("Voor dit profiel is in de huidige snapshot weinig commissiewerk gekoppeld.")

    if minister_activity:
        lines.append(f"Daarnaast verschijnt deze politicus ook {minister_activity} keer in een ministerrol in parlementaire dossiers.")
    elif current_professions or functions:
        details = current_professions + functions
        lines.append(f"Opvallende extra profielinformatie: {details[0]}{' ; ' + details[1] if len(details) > 1 else ''}.")
    else:
        lines.append("Opvallend is dat het profiel momenteel vooral via parlementaire activiteit en aanwezigheid wordt getekend.")

    return "\n".join(lines[:6])


def generate_member_ai_overviews(store_dir: Path | None = None) -> pd.DataFrame:
    store_dir = store_dir or active_store_dir()
    members = load_store_table(store_dir, "members")
    attendance = load_store_table(store_dir, "member_attendance")
    written_links = load_store_table(store_dir, "member_written_question_links")
    oral_links = load_store_table(store_dir, "member_oral_item_links")
    interests = load_store_table(store_dir, "member_interests")
    professions = load_store_table(store_dir, "member_professions")
    functions = load_store_table(store_dir, "member_functions")
    committee_memberships = load_store_table(store_dir, "committee_memberships")

    if members.empty:
        return pd.DataFrame(
            columns=[
                "member_id",
                "member_name",
                "summary_text",
                "generated_at",
                "generator",
                "model",
                "source",
                "prompt_version",
            ]
        )

    member_stats = build_member_stats_for_overviews(members, attendance, written_links, oral_links)
    rows: list[dict[str, object]] = []

    for _, detail in member_stats.sort_values("volledige_naam").iterrows():
        member_id = coerce_int(detail.get("member_id"))
        if member_id is None:
            continue
        committee_rows = committee_memberships[committee_memberships["member_id"].apply(coerce_int) == member_id]
        interests_rows = interests[interests["member_id"].apply(coerce_int) == member_id] if not interests.empty else pd.DataFrame()
        professions_rows = professions[professions["member_id"].apply(coerce_int) == member_id] if not professions.empty else pd.DataFrame()
        functions_rows = functions[functions["member_id"].apply(coerce_int) == member_id] if not functions.empty else pd.DataFrame()
        written_rows = written_links[written_links["member_id"].apply(coerce_int) == member_id] if not written_links.empty else pd.DataFrame()
        oral_rows = oral_links[oral_links["member_id"].apply(coerce_int) == member_id] if not oral_links.empty else pd.DataFrame()
        rows.append(
            {
                "member_id": member_id,
                "member_name": detail.get("volledige_naam"),
                "summary_text": build_member_overview_text(
                    detail,
                    committee_rows,
                    interests_rows,
                    professions_rows,
                    functions_rows,
                    written_rows,
                    oral_rows,
                ),
                "generated_at": iso_now(),
                "generator": "local-template",
                "model": "pending-provider",
                "source": "snapshot",
                "prompt_version": "v1",
            }
        )
    return pd.DataFrame(rows)


def write_member_ai_overviews(store_dir: Path | None = None) -> Path:
    store_dir = store_dir or active_store_dir()
    output_path = store_dir / "member_ai_overviews.csv"
    frame = generate_member_ai_overviews(store_dir=store_dir)
    frame.to_csv(output_path, index=False)
    return output_path
