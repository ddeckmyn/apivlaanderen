# Runbook

## Eerste vulling

Voor een eerste actuele dataset van het afgelopen jaar:

```powershell
python .\scripts\sync_vlaams_parlement.py
```

Voor een ruimere vulling vanaf de start van de huidige legislatuur:

```powershell
python .\scripts\sync_vlaams_parlement.py --since 2024-06-09
```

## Wekelijkse update

Handmatig:

```powershell
python .\scripts\sync_vlaams_parlement.py
```

Of via Task Scheduler:

Program/script:

```text
powershell.exe
```

Arguments:

```text
-ExecutionPolicy Bypass -File "C:\Users\ddeck\OneDrive\Documenten\vibecoding\apivlaanderen\scripts\run_weekly_update.ps1"
```

## Bestanden

Lokale tabellen:

- `data/store_snapshots/<timestamp>/members.csv`
- `data/store_snapshots/<timestamp>/written_questions.csv`
- `data/store_snapshots/<timestamp>/oral_items.csv`
- `data/store_snapshots/<timestamp>/meetings.csv`
- `data/store_snapshots/<timestamp>/agenda_lines.csv`
- `data/store_snapshots/<timestamp>/parliamentary_texts.csv`

Lokale fotocache:

- `data/photos/member_<id>.<ext>`

Excel-export:

- `data/published/vlaams_parlement_data.xlsx`

Sync-status:

- `data/state/sync_state.json`

## GUI

Start lokaal:

```powershell
streamlit run .\app.py
```

De GUI leest alleen lokale geexporteerde bestanden. Voor delen via URL kun je dezelfde app deployen en de gegenereerde `data/store_snapshots` of `data/published` mee publiceren.
De GUI leest automatisch de laatst succesvolle snapshotmap uit `data/state/sync_state.json`.
Parlementsfoto's worden lokaal gecachet in `data/photos` en bij volgende syncs hergebruikt of periodiek ververst.
Agenda, vergaderingen en parlementaire teksten worden lokaal als metadata en links opgeslagen. Zware PDF's en volledige handelingen blijven gelinkt via de bron-URL's.
