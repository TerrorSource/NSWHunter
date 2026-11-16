# Changelog

Alle wijzigingen per versie. Het versienummer staat in `app/version.py`; elke versie heeft hier een sectie en een release op GitHub.

## [1.7.0] - 2026-11-16

### Toegevoegd

- **Meldingen via Telegram**, in te stellen op de tab Configuratie (bot-token, chat-ID, knop **Stuur testbericht**). Je krijgt een bericht als er iets vanzelf is verstuurd, iets op je keuze wacht, een download mislukt of iets binnen is.
- **Downloads volgen.** NSWHunter vraagt NZBGet of SABnzbd elke twee minuten naar de status. Mislukt een download, dan is de volgende release meteen aan de beurt. Is hij gedownload, dan krijgt switch-library-manager-web het verzoek om te scannen. Het paneel toont de status ("wordt gedownload", "gedownload, wacht op de bibliotheek").
- **Wachten op de bibliotheek** instelbaar (30 minuten tot 24 uur, standaard 60 minuten) in plaats van vast 48 uur.
- **Afgevallen releases** per game, met de reden, en een knop **Toch downloaden**.
- **Grootte telt mee in de score:** een "update" zo groot als het hele spel, of meer dan vijf keer zo groot of zo klein als je eigen update, scoort lager.
- **DLC-pakket:** releases die geen DLC bij naam noemen ("DLC Unlocker", "DLC Pack") staan één keer per game in plaats van onder elke ontbrekende DLC.

### Gewijzigd

- **Geen Switch 2.** Titels met een Switch 2-ID (`04…`) uit de bibliotheek worden overgeslagen, en releases met `Switch 2`, `NSW2` of een Switch 2-title ID vallen af.
- Van het paneelwachtwoord wordt alleen nog een hash bewaard. Een wachtwoord dat een oudere versie leesbaar opsloeg, wordt bij de start omgezet.
- Is een download gelukt maar staat hij na de wachttijd niet in de bibliotheek, dan gaat er geen volgende release uit; je krijgt een melding.
- `GRAB_WAIT_HOURS` is vervangen door `GRAB_WAIT_MINUTES`.

## [1.6.0] - 2026-11-16

### Toegevoegd

- **Sorteren** in het overzicht: op score, naam, nieuwste release, aantal releases, aantal updates achter, aantal ontbrekende DLC en laatst gezocht. De pijl ernaast keert de volgorde om. De keuze wordt in je browser onthouden.

### Gewijzigd

- Het overzicht staat standaard op score (hoogste eerst) in plaats van op naam.

## [1.5.1] - 2026-11-16

### Opgelost

- Releases voor andere consoles stonden tussen de resultaten: de categorie Console (1000) bevat ook PS4, Xbox, Wii en de rest. Een release valt nu af als de indexer hem onder een andere console heeft ingedeeld (bijvoorbeeld 1180, PS4), of als er een ander platform in de naam staat (`PS4`, `XBOX360`, een PlayStation-productcode als `CUSA34119`).

### Gewijzigd

- Staat er in een titel geen enkel platform (geen `NSW`, `Switch`, `NSP`, title ID of intern versienummer), dan is de score iets lager en staat dat bij de reden.

## [1.5.0] - 2026-11-16

### Opgelost

- Een game stond er net zo vaak in als hij DLC's mist (EA SPORTS FC 25 en 26 samen 22 keer), en onder elke DLC stonden ook de releases van de andere DLC's. Een release hoort nu bij de DLC die hij het best noemt en valt bij de andere af.
- Na het downloaden van een release verdwenen de andere releases van die game uit beeld. Ze blijven nu staan; de verstuurde is gemarkeerd en een andere kan alsnog gedownload worden.
- Dezelfde release stond dubbel als twee indexers hem met punten en met spaties schrijven.

### Gewijzigd

- **Eén kaart per game** met daarin de update en alle ontbrekende DLC's. De tabbladen tellen games. **Negeer** op de kaart negeert alles van de game; per update of DLC kan het ook.
- Komt een verstuurde update binnen die niet de nieuwste was, dan staat de game weer bij Te beoordelen in plaats van na 48 uur als "niet aangekomen" te gelden.
- Woorden uit de naam van een DLC tellen niet meer als "extra woorden in de titel".

## [1.4.0] - 2026-11-16

### Toegevoegd

- **Score van 1 tot 10** in plaats van Zeker, Waarschijnlijk en Twijfel: de kans dat een download de juiste is. Het paneel toont de score per release en de hoogste score per game.
- **Automatisch downloaden vanaf een score** (uit, of vanaf 10 tot en met 5). De oude waarden `sure` en `likely` gelden als 9 en 7.
- **Categorieën** instelbaar op de tab Configuratie (standaard `1000`, Console met alle subcategorieën). Resultaten buiten die categorieën vallen af, ook als Prowlarr ze toch teruggeeft.
- Versies die de update zelf tellen worden herkend: is je eigen 1.0.31.0 update 31, dan is 1.0.35.0 update 35.

### Gewijzigd

- **Sortering** binnen een game: score, dan leeftijd (nieuwste post eerst), dan de prioriteit van de indexer in Prowlarr. Van dezelfde release op meerdere indexers blijft die van de indexer met de hoogste prioriteit over.
- **Games staan ingeklapt.** Een klik op de naam toont de releases.
- "Update incl. Crack" is geen bundel meer; alleen "game incl. update" is dat. Een crack verlaagt de score en staat bij de reden.
- Een DLC telt als genoemd in de titel als het grootste deel van zijn naam erin staat.

## [1.3.0] - 2026-11-16

### Toegevoegd

- **Versieladder:** een zichtbare versie uit een releasenaam (`v1.7.1`) wordt vertaald naar het updatenummer (update 11, `v720896`) op volgorde in plaats van alleen op datum. Je eigen versie uit de bibliotheek is het vaste punt (1.7.0 = update 10); een hogere versie is de volgende update. Zonder versie uit de bibliotheek bepaalt de plaatsingsdatum de onderste trede.
- Is die vertaling volledig afgeleid van je eigen versie en is het de nieuwste update, dan is de release **Zeker**. Rust ze deels op datums, dan **Waarschijnlijk**.
- NSWHunter onthoudt per game elke versie die in releasenamen voorkomt, ook van releases die afvallen: die zijn treden van de ladder. Het paneel toont de ladder per game ("v1.7.0 = update 10 · v1.7.1 = update 11").

### Gewijzigd

- De lijst met updates en datums komt nu eerst van de databron van switch-library-manager-web en anders van blawar/titledb. De eerste kent nieuwe updates eerder.
- Een release valt niet meer af omdat hij vóór de datum van een update is geplaatst, tenzij dat meer dan 45 dagen scheelt: de datum van een nieuwe update staat vaak weken te laat in de lijsten (bij NARUTO X BORUTO drie weken).
- Na het bijwerken worden alle games één keer opnieuw gezocht.

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
