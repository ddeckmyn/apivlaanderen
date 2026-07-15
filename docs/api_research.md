# Vlaams Parlement API research

Datum van verificatie: 2026-06-26

## 1. Actuele publieke API

De publiek bruikbare Open Data API staat op:

- `https://ws.vlpar.be/e/opendata`
- OpenAPI-spec: `https://ws.vlpar.be/e/opendata/api-docs`

De oudere basis-URL `https://data.vlaamsparlement.be/v1/` resolveerde in deze omgeving niet meer.

## 2. Relevante endpointfamilies

### Volksvertegenwoordigers

- `GET /vv/huidige`
- `GET /vv/{persoonId}`
- `GET /vv/adreslijst`
- `GET /vv/huidige/perfractie`
- `GET /vv/huidige/perkieskring`
- `GET /vv/op-datum`
- `GET /vv/gewezen`

Belangrijk: `GET /vv/{persoonId}` levert veel meer op dan de lijst:

- email
- website en socials
- huidige fractie
- lidmaatschapshistoriek
- mandaten binnen het Vlaams Parlement
- andere mandaten
- aanwezigheden in huidige legislatuur

### Schriftelijke vragen

- `GET /schv/{idSCHV}`
- `GET /schv/lijst?id=...`

Belangrijk: de Open Data API toont detail en bulk op basis van id, maar ik vond geen publieke zoekendpoint om ids van schriftelijke vragen te ontdekken.

### Vragen en interpellaties

- `GET /vi/{idVI}`
- `GET /vi/lijst?id=...`

Zelfde beperking als bij schriftelijke vragen: detail is beschikbaar, discovery van ids nog niet.

### Vergaderingen

- `GET /verg/zoek`
- `GET /verg/zoek/datums`
- `GET /verg/volledig/zoek`
- `GET /verg/volledig/zoek/datums`
- `GET /verg/{idVerg}`
- `GET /verg/{idVerg}/agd`
- `GET /verg/{idVerg}/hand`

### Commissies en gremia

- `GET /comm/huidige`
- `GET /comm/{commId}`
- `GET /comm/{commId}/verslagen`
- `GET /comm/{commId}/vrg_gepland`
- `GET /comm/{commId}/alle-stvz`
- `GET /gremia/huidige`
- `GET /gremia/{gremiumId}`

Deze zijn relevant om activiteiten en context rond leden op te bouwen.

## 3. Geobserveerde payloads

### `GET /vv/huidige`

JSON-structuur:

- root object
- `items[]`
- elk item bevat `volksvertegenwoordiger`

### `GET /vv/{persoonId}?lang=nl`

Belangrijke velden in de live respons:

- `id`
- `voornaam`
- `naam`
- `email`
- `website`
- `huidigefractie`
- `kieskring`
- `lidmaatschap`
- `mandaat-vlaams-parlement`
- `mandaat-andere`
- `aanwezigheden-huidige-legislatuur`

## 4. Niet-open-data API

Op `https://ws.vlpar.be/v3/api-docs` staat een aparte `Document Search API`.

- Titel in spec: `Document Search API`
- Gedocumenteerd pad: `GET /search/query/{query}`
- Belangrijke nuance: de werkende publieke base path is `https://ws.vlpar.be/api`, dus praktisch:
  - `https://ws.vlpar.be/api/search/query/{query}?collection=vp_collection`

De root-variant zonder `/api` gaf in deze omgeving een access-policy logoutpagina terug, maar de `/api/...`-variant werkt wel publiek.

### Wat de zoek-API oplevert

De resultaten bevatten rijke `metatags`, onder meer:

- `soort`
- `opendata`
- `displayurl`
- `onderwerp`
- `vraagsteller`
- `minister`
- `nummer`
- `publicatiedatum`

Voorbeelden:

- `soort = SCHV` met `opendata = http://ws.vlpar.be/e/opendata/schv/...`
- `soort = VI` met `opendata = http://ws.vlpar.be/e/opendata/vi/...`

## 5. Eerste voorstel datamodel

Minimale tabellen:

- `members`
- `member_memberships`
- `member_mandates_vp`
- `member_mandates_other`
- `member_attendance`
- `written_questions`
- `written_question_answers`
- `oral_items`
- `meetings`
- `committees`

## 6. Discovery-status

### Schriftelijke vragen

Werkbare discovery-route:

1. zoek-API aanspreken met bijvoorbeeld query `schriftelijke vraag`
2. sorteren op datum (`sort=date`)
3. client-side filteren op `metatag.soort == SCHV`
4. `metatag.opendata` omzetten naar `https://ws.vlpar.be/e/opendata/schv/{id}`

Voor recente resultaten bleek die route in de praktijk zeer zuiver: de eerste twintig recente resultaten op 2026-06-26 waren allemaal `SCHV`.

### Vragen en interpellaties

Er zijn minstens twee werkbare discovery-routes:

1. `GET /comm/{commId}/alle-stvz`
   - bevat `vrageninterpellatie[]` met directe ids
2. zoek-API
   - filteren op `metatag.soort == VI`
   - bruikbaar, maar ruwer dan de commissie-route

## 7. Praktische conclusie

Voor leden zelf is de publieke Open Data API al sterk genoeg om een degelijke kernfiche te vullen.

De grootste open vraag is nu niet meer of discovery kan, maar hoe we die discovery het best industrialiseren:

- per dag via zoek-API incrementeel ophalen?
- per commissie via `alle-stvz` en vergaderagenda's aanvullen?
- hoe dedupliceren we `SCHV` en `VI` over meerdere discovery-routes?

Waarschijnlijke volgende stap:

1. `members` en aanverwante tabellen eerst opbouwen uit `/vv/...`
2. discovery-pipeline bouwen voor `SCHV` via `/api/search/query/...`
3. discovery-pipeline bouwen voor `VI` via `/comm/.../alle-stvz` en eventueel zoek-API
4. daarna detail-ophaling normaliseren naar relationele tabellen
