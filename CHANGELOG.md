# Changelog

Alle wijzigingen per versie. Het versienummer staat in `app/version.py`; elke versie heeft hier een sectie en een release op GitHub.

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
