# Deploy naar Streamlit Community Cloud

Deze app is voorbereid om rechtstreeks vanaf GitHub te draaien op Streamlit Community Cloud.

## Wat al in orde is

- `requirements.txt` staat in de repo
- entrypoint is `app.py`
- de app valt automatisch terug op de nieuwste lokale snapshot in `data/store_snapshots/`
- `venv/` en lokale secrets worden niet mee gecommit

## Wat jij zelf moet doen

### 1. GitHub-repo maken

In deze map:

```powershell
git status
git add .
git commit -m "Prepare Streamlit Community Cloud deployment"
```

Daarna:

```powershell
git remote add origin <jouw-github-repo-url>
git push -u origin main
```

Als er al een remote bestaat, gebruik gewoon `git push`.

### 2. Controleren welke data je online wilt zetten

De online app leest de snapshot uit `data/store_snapshots/`.

Voor een eerste deploy is het best:

- de nieuwste snapshot behouden
- oude snapshots eventueel later verwijderen
- geen `venv/` of andere lokale rommel committen

## Aanbevolen minimale online dataset

Hou zeker deze mappen/bestanden in GitHub:

- `data/store_snapshots/<laatste snapshot>/`
- `data/reference/seat_layout.json`
- `data/state/sync_state.json`
- `data/photos/` voor profielbeelden

## 3. Deployen op Streamlit Community Cloud

1. Ga naar [https://share.streamlit.io/](https://share.streamlit.io/)
2. Log in met GitHub
3. Kies `New app`
4. Selecteer:
   - repository: jouw repo
   - branch: `main`
   - main file path: `app.py`
5. Klik `Deploy`

## 4. Toegang beperken

Op Community Cloud kun je per app kijkers beperken. Stel dat meteen in als de app enkel voor collega’s bedoeld is.

## 5. Hoe updates later werken

De dataverzameling blijft lokaal:

```powershell
.\scripts\run_weekly_update.ps1
```

Daarna commit en push je de vernieuwde snapshot:

```powershell
git add data
git commit -m "Refresh Vlaams Parlement snapshot"
git push
```

De online app pikt die update daarna automatisch op.

## Mogelijke volgende stap

Als de repo te zwaar wordt door meerdere snapshots of veel foto’s:

- enkel de laatste snapshot bewaren
- of later data apart hosten en de app die remote laten lezen
