# Vlaams Parlement Dashboard

Streamlit-app en Python-datalaag voor een lokaal gevoede dataset over het Vlaams Parlement:

- parlementsleden
- fracties
- commissies
- aanwezigheid
- schriftelijke vragen
- mondelinge vragen en interpellaties
- agenda/vergaderingen

## Lokaal starten

```powershell
streamlit run .\app.py
```

## Data-update

Volledige of gerichte sync:

```powershell
python .\scripts\sync_vlaams_parlement.py --since 2024-06-09
```

Wekelijkse routine:

```powershell
.\scripts\run_weekly_update.ps1
```

AI-overzichten opnieuw opbouwen:

```powershell
python .\scripts\generate_member_ai_overviews.py
```

## Deploy op Streamlit Community Cloud

Zie [docs/streamlit_community_cloud.md](docs/streamlit_community_cloud.md).

## Belangrijke noot

Deze repo bevat een gepubliceerde snapshot voor de online app. De dataverzameling en refresh kunnen lokaal blijven draaien; daarna commit je een nieuwe snapshot naar GitHub zodat de gedeelde app automatisch ververst.
