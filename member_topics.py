from __future__ import annotations

from collections import Counter
import re

import pandas as pd

STOPWORDS = {
    "aan",
    "als",
    "bij",
    "dat",
    "de",
    "den",
    "der",
    "des",
    "die",
    "dit",
    "door",
    "een",
    "en",
    "er",
    "geen",
    "het",
    "hun",
    "in",
    "is",
    "met",
    "naar",
    "niet",
    "nog",
    "of",
    "om",
    "onder",
    "op",
    "over",
    "te",
    "ter",
    "tot",
    "uit",
    "van",
    "voor",
    "waar",
    "wat",
    "wie",
    "zijn",
    "haar",
    "hem",
    "ons",
}

THEME_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Zorg en welzijn", ("zorg", "welzijn", "jeugdhulp", "woonzorg", "ouderen", "gehandicap", "geestelijke", "kinderopvang", "thuiszorg", "zorgbudget")),
    ("Werk en economie", ("werk", "tewerk", "arbeid", "jobs", "ondernem", "kmo", "economie", "industrie", "handel", "zelfstandig")),
    ("Migratie en inburgering", ("migratie", "asiel", "vluchteling", "inburger", "integratie", "nationaliteit", "vreemdeling")),
    ("Onderwijs", ("onderwijs", "school", "scholen", "leraar", "student", "universiteit", "hogeschool", "studie")),
    ("Wonen en energie", ("wonen", "woning", "huur", "woon", "renovatie", "energie", "isolatie", "sociaal wonen")),
    ("Klimaat en milieu", ("klimaat", "milieu", "natuur", "stikstof", "water", "afval", "biodiversiteit", "vervuiling")),
    ("Mobiliteit", ("mobiliteit", "verkeer", "vervoer", "bus", "tram", "trein", "fiets", "weg", "wegen", "lijn")),
    ("Veiligheid en justitie", ("veiligheid", "justitie", "politie", "criminaliteit", "gevangenis", "brandweer", "handhaving")),
    ("Binnenlands bestuur", ("gemeente", "lokaal bestuur", "provincie", "bestuur", "verkiezing", "stads", "vlaamse rand")),
    ("Cultuur, media en sport", ("cultuur", "media", "sport", "jeugd", "omroep", "erfgoed", "kunsten")),
    ("Landbouw en dierenwelzijn", ("landbouw", "visserij", "boer", "dierenwelzijn", "dier", "voeding", "veeteelt")),
    ("Begroting en financiën", ("begroting", "financien", "financi", "belasting", "subsidie", "fiscal", "schuld")),
    ("Armoede en sociale bescherming", ("armoede", "sociaal", "uitkering", "kansarmoede", "leefloon", "schuldhulp")),
]


def tokenize_subjects(subjects: list[str]) -> list[str]:
    tokens: list[str] = []
    for subject in subjects:
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9'-]{4,}", str(subject).lower()):
            cleaned = token.strip("-'")
            if cleaned and cleaned not in STOPWORDS:
                tokens.append(cleaned)
    return tokens


def extract_member_themes(subjects: list[str], interests: list[str] | None = None, limit: int = 5) -> pd.DataFrame:
    interests = interests or []
    text_items = subjects + interests
    lowered = [item.lower() for item in text_items if item]
    token_counts = Counter(tokenize_subjects(text_items))
    rows: list[dict[str, object]] = []

    for theme, keywords in THEME_RULES:
        score = 0
        matches: list[str] = []
        for keyword in keywords:
            keyword_lower = keyword.lower()
            token_score = sum(count for token, count in token_counts.items() if keyword_lower in token)
            text_score = sum(1 for item in lowered if keyword_lower in item)
            total = token_score + text_score
            if total > 0:
                score += total
                matches.append(keyword)
        if score > 0:
            rows.append({"theme": theme, "score": score, "matches": ", ".join(matches[:4])})

    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["theme", "score", "matches"])
    return frame.sort_values(["score", "theme"], ascending=[False, True]).head(limit).reset_index(drop=True)


def top_theme_labels(subjects: list[str], interests: list[str] | None = None, limit: int = 3) -> list[str]:
    frame = extract_member_themes(subjects, interests=interests, limit=limit)
    return frame["theme"].tolist() if not frame.empty else []
