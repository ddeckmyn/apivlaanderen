# Dataverzameling TODO

## Huidige status

- Leden, fracties, commissies, aanwezigheid, schriftelijke vragen en mondelinge vragen zitten in de pipeline.
- Foto's worden lokaal gecachet.
- Vergaderingen, agenda-lijnen en een eerste lichte laag parlementaire teksten zitten in het model.
- De dataset is **niet gegarandeerd volledig voor de hele legislatuur** voor alle domeinen.
- De sync is ontworpen zodat latere aanvulling mogelijk blijft via nieuwe snapshots.

## Belangrijke werkafspraken

- Geen zware documenten lokaal opslaan als dat niet nodig is.
- Waar mogelijk alleen metadata en bronlinks bewaren.
- Altijd onderscheid maken tussen:
  - volledig lokaal opgehaalde data
  - gedeeltelijk opgehaalde data
  - data die voorlopig alleen via link beschikbaar is

## Nog te doen aan dataverzameling

### 1. Dekkingsstatus expliciet maken

- In `sync_state.json` of aparte metadata bijhouden welke domeinen volledig of onvolledig zijn.
- Per domein opslaan vanaf welke datum de dekking betrouwbaar is.
- In de GUI tonen wanneer data slechts gedeeltelijk is ingeladen.

### 2. Vergaderingen en agenda robuuster maken

- De meeting-sync sneller en betrouwbaarder maken zodat een volledige run opnieuw haalbaar wordt.
- Historische vergaderingen later gefaseerd aanvullen in plaats van alles tegelijk.
- Controleren of de huidige agenda-tabellen goed incrementeel blijven updaten.

### 3. Parlementaire teksten verdiepen

- `pi/{idPI}` detail-ophaling toevoegen.
- Extra velden uit parlementaire initiatieven normaliseren:
  - procedureverloop
  - status
  - thema
  - journaallijn-koppelingen
  - is-basis-van
  - is-verslag-van
  - documentmetadata
- Beslissen welke PI-detailvelden in aparte tabellen horen en welke enkel als link of samenvattende metadata volstaan.

### 4. Handelingen en journaallijnen

- `jln/{idJLN}` detail-ophaling toevoegen.
- Alleen gestructureerde metadata opslaan, niet volledige zware handelingen.
- Koppeling maken tussen journaallijnen, vergaderingen en parlementaire teksten.

### 5. Stemmingen

- Uitzoeken of stemmingsinformatie voldoende gestructureerd beschikbaar is via:
  - `journaallijn-stemmingen`
  - `stemming`
  - gerelateerde PI- of JLN-detailpayloads
- Indien bruikbaar: aparte vote-tabellen toevoegen.
- Indien niet volledig gestructureerd: alleen linkniveau en statusniveau bewaren.

### 6. Debatten

- `debat/{debatId}` en eventueel `debat/lijst` opnemen.
- Nagaan of debatdetail nuttige extra koppelingen oplevert naar politici, teksten of vergaderingen.

### 7. Kwaliteitscontrole

- Controles toevoegen op:
  - dubbele records
  - ontbrekende foreign keys
  - lege of inconsistente links
  - onverwachte dalingen in aantallen per sync
- Een beperkte validatietabel of sync-waarschuwingen voorzien.

### 8. Prioritaire aanvullende bronnen binnen dezelfde API

- Nagaan welke relevante objecttypes we nog niet meenemen buiten SCHV, VI en PI.
- Beslissen welke daarvan beleidsmatig relevant zijn voor dit project en welke niet.

## Nog te doen aan data-ophalen

### Korte termijn

- Geen brede legislatuur-backfill nu forceren.
- Wel kleine gecontroleerde sync-runs blijven doen voor nieuwe domeinen.
- Nieuwe domeinen eerst technisch valideren op kleine vensters.

### Middellange termijn

- Gefaseerde backfill per domein:
  - eerst vergaderingen
  - dan parlementaire teksten
  - dan journaallijnen/stemmingen
- Per stap expliciet noteren vanaf welke datum het domein volledig is.

## GUI-gevolgen

- De GUI moet duidelijk tonen wanneer een view op volledige of gedeeltelijke data steunt.
- Agenda- en tekstviews mogen voorlopig metadata-first zijn.
- Volledige documenten openen via bronlink is voorlopig voldoende.
