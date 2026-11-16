# Changelog

Alle wijzigingen per versie. Het versienummer staat in `app/version.py`; elke versie heeft hier een sectie en een release op GitHub.

## [1.2.0] - 2026-11-16

### Opgelost

- Zoeken gaf nooit resultaten: NSWHunter vroeg Prowlarr om alle torrent-indexers (`-2`) in plaats van alle usenet-indexers (`-1`).

### Toegevoegd

- **Test**-knop bij Bibliotheek, Prowlarr en Downloadclient op de tab Configuratie. De test gebruikt wat er in het formulier staat, ook als het nog niet is opgeslagen. De Prowlarr-test meldt hoeveel usenet-indexers er zijn.
- **Automatisch zoeken** instelbaar op elke 6, 12, 24 of 48 uur (`SEARCH_INTERVAL_HOURS`). Elke game die iets mist wordt eens per die tijd op naam gezocht.
- Tab **Logboek**.
- Een release met alleen een zichtbare versie (`v1.7.1`) krijgt het updatenummer dat op de dag van plaatsen het nieuwste was ("waarschijnlijk update 11"). Is dat de nieuwste update, dan is de release "waarschijnlijk".
- Het paneel toont updatenummers ("je hebt update 10 → nieuwste is update 11") naast de interne versienummers.

### Gewijzigd

- **Zoek nu** wacht niet meer op een lopende ronde.
- Is een zichtbare versie hoger dan je eigen versie, dan valt de release niet meer af op de datum alleen.
- Van gelijkwaardige releases staat de meest gedownloade bovenaan.
- Downloaden via Prowlarr zoekt zelf opnieuw als Prowlarr de release niet meer kent (na een half uur).
- `BACKLOG_DAYS` is vervangen door `SEARCH_INTERVAL_HOURS`; `BACKLOG_PER_RUN` staat standaard op 0 (geen limiet).

## [1.1.0] - 2026-11-16

### Toegevoegd

- Tab **Configuratie** in het paneel: de adressen en keys van de bibliotheek, Prowlarr en de downloadclient, automatisch downloaden, DLC en de inlog van het paneel stel je daar in. Opslaan test meteen de verbindingen en start een ronde.
- De instellingen staan in `/data/settings.json` (alleen leesbaar voor de app-gebruiker) en gaan voor op de waarden in de compose. Keys en wachtwoorden worden nooit teruggestuurd naar de browser.
- Zonder instellingen opent het paneel direct op de tab Configuratie.

### Gewijzigd

- `docker-compose.yml` bevat alleen nog `TZ`, `PUID`, `PGID`, de poort en de datamap.
- Python 3.12 naar 3.15 en apprise 1.13.1 naar 2.2.0 (overgenomen van Dependabot).

## [1.0.0] - 2026-11-16

Eerste versie.

### Toegevoegd

- Haalt `/export/library.json` van switch-library-manager-web op en houdt per ontbrekende update (en optioneel per ontbrekende DLC) een item bij.
- Zoekt via Prowlarr: elke ronde de nieuwste posts van alle usenet-indexers, plus een paar games op naam.
- Beoordeelt releases zonder vast naamformaat op game (title ID of naam), versie (intern nummer of zichtbare versie) en soort (update, bundel, DLC, basisspel).
- Stuurt een gekozen release naar NZBGet, SABnzbd of de downloadclient van Prowlarr. Automatisch versturen is in te stellen met `AUTO_DOWNLOAD`.
- Webpaneel op poort 3033 om kandidaten te beoordelen, te versturen, te verwerpen en games te negeren.
- Draait als `PUID`:`PGID` (standaard 1000:1000); `/data` krijgt bij de start die eigenaar.
- Image op `ghcr.io/<account>/nswhunter` voor amd64 en arm64: `latest` bij elke push, `X.Y.Z` en `X.Y` bij een release.
