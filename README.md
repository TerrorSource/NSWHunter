# NSWHunter

Zoekt de Switch-updates die in je bibliotheek ontbreken op usenet en stuurt ze naar je downloadclient.

1. Haalt de export van [switch-library-manager-web](https://github.com/DeLFuS77/switch-library-manager-web) op (`/export/library.json`) en neemt alle games met `updateMissing: true`.
2. Zoekt via Prowlarr naar releases van die games.
3. Beoordeelt elke release: is het de juiste game, is de versie nieuwer dan de jouwe, is het een update?
4. Toont de kandidaten in een webpaneel. Jij klikt op **Download**, of je laat zekere releases vanzelf gaan.
5. Stuurt de NZB naar NZBGet (categorie `games`), SABnzbd of de downloadclient van Prowlarr.

Staat de update daarna in je bibliotheek, dan verdwijnt het item vanzelf.

## Installeren

Het image staat op `ghcr.io/<account>/nswhunter`. In Portainer: **Stacks > Add stack** en plak [docker-compose.yml](docker-compose.yml):

```yaml
services:
  nswhunter:
    container_name: nswhunter
    image: ghcr.io/<account>/nswhunter:latest
    restart: always
    network_mode: bridge
    environment:
      - TZ=Etc/UTC
      - PUID=1000
      - PGID=1000
    ports:
      - 3033:3033
    volumes:
      - /path/to/nswhunter/data:/data
```

De repo is privé, en daarmee het image ook. Portainer heeft dan een registry nodig om het op te halen: **Registries > Add registry > Custom**, URL `ghcr.io`, gebruikersnaam `<account>` en als wachtwoord een GitHub-token met het recht `read:packages`. Of zet het pakket op openbaar onder GitHub > Packages > nswhunter > Package settings.

## Instellen

Open `http://<nas>:3033`. Zonder instellingen kom je op de tab **Configuratie**:

| Instelling | Waar je hem vindt |
|---|---|
| Bibliotheek: adres en API key | Switch-library-manager-web > My account > API keys > Make a key, met het recht Read only. De key begint met `slm_` en wordt één keer getoond. Staat inloggen daar uit, dan is er geen key nodig. |
| Prowlarr: adres en API key | Prowlarr > Settings > General > API Key |
| Prowlarr: categorieën | `1000` is Console met alle subcategorieën. Alleen daarin wordt gezocht. Releases die de indexer onder een andere console heeft ingedeeld (PS4, Xbox, Wii, …) of die een ander platform in de naam hebben, vallen af: de Switch heeft geen eigen categorie. |
| Downloadclient | NZBGet (adres, ControlUsername, ControlPassword), SABnzbd (adres, API key) of de downloadclient die in Prowlarr is ingesteld |
| Automatisch downloaden | Zie [Automatisch downloaden](#automatisch-downloaden) |
| Automatisch zoeken | Elke 6, 12, 24 of 48 uur, zie [Zoeken en API-limieten](#zoeken-en-api-limieten) |
| Paneel | Gebruikersnaam en wachtwoord. Zonder wachtwoord heeft het paneel geen inlog. |

Elke service heeft een **Test**-knop die de verbinding probeert met wat er in het formulier staat, ook als het nog niet is opgeslagen. **Opslaan en verbindingen testen** bewaart de instellingen, probeert elke service en start een ronde. De instellingen staan in `/data/settings.json`, alleen leesbaar voor de app-gebruiker. Keys en wachtwoorden gaan nooit terug naar de browser: een leeg veld betekent "houden wat er staat", met **Wis** maak je er een leeg.

Dezelfde instellingen kunnen ook als omgevingsvariabele in de compose staan (`SLM_URL`, `PROWLARR_API_KEY`, …). Dat is dan de beginwaarde; een opgeslagen waarde gaat voor. De overige instellingen (tempo, indexers, meldingen) staan alleen in de compose, zie [.env.example](.env.example).

## Hoe een release beoordeeld wordt

Releasenamen hebben geen vast format, dus NSWHunter zoekt drie dingen ergens in de titel:

- **Welke game.** Een title ID (`0100623017A58800`) is doorslaggevend. Anders moet de gamenaam er als geheel in staan. Staat er een vervolgnummer achter (`Hades II`), dan is het een andere game. Staan er andere extra woorden bij, dan is het een twijfelgeval.
- **Welke versie.** Een intern nummer (`v131072`) wordt direct vergeleken met `localUpdate` en `latestUpdate` uit de export. Een zichtbare versie (`v1.7.1`) wordt vertaald met de versieladder, zie hieronder.
- **Wat het is.** Alleen DLC, het basisspel (`v0`, `1.0.0`) en versies die je al hebt vallen af. Een bundel (basisspel + update) blijft kandidaat, maar staat lager.

### De versieladder

Geen enkele bron heeft van een update zowel het zichtbare als het interne versienummer. NSWHunter legt het verband zelf, per game:

1. **Het vaste punt is je eigen versie.** De bibliotheek kent van jouw update beide nummers, bijvoorbeeld 1.7.0 = update 10.
2. **Hogere versies zijn latere updates.** Staat er in releasenamen een `v1.7.1`, dan is dat de volgende update die bekend is: update 11.
3. **Zonder vast punt bepaalt de datum de onderste trede.** Een versie die voor het eerst is geplaatst toen update 10 de nieuwste was, is update 10. Daarboven telt weer de volgorde.

De volgorde is betrouwbaarder dan de datum: de lijsten met updates zetten een nieuwe update er vaak weken te laat in. Daarom onthoudt NSWHunter elke versie die in releasenamen voorkomt, ook van releases die afvallen. Het paneel toont de ladder per game: "v1.7.0 = update 10 · v1.7.1 = update 11".

### De score

Elke release krijgt een score van 1 tot 10: de kans dat de download de juiste is. De score is het product van drie kansen: dat het deze game is, dat het de nieuwste update is, en dat het een update is en niets anders.

| Score | Wat het meestal is |
|---|---|
| 10 | Title ID van de game en het interne versienummer van de nieuwste update |
| 9 | Exacte naam met het interne versienummer, of een zichtbare versie die via je eigen versie als nieuwste update is afgeleid |
| 7-8 | Exacte naam; de versie is afgeleid van plaatsingsdatums of van de nummering (1.0.35.0 = update 35) |
| 4-6 | Een tussenversie, een bundel, een update met crack, extra woorden in de naam, of niet te zien welke versie het is |
| 1-3 | De naam lijkt er alleen op, of er staat geen versie in |

Wat de score verlaagt: een bundel met het basisspel (×0,75), een crack (×0,9), extra woorden in de naam (×0,5 in plaats van ×0,9). In het paneel staat bij elke release waarom.

Binnen een game staan de releases op score, dan op leeftijd (nieuwste post eerst), dan op de prioriteit van de indexer in Prowlarr. Staat dezelfde release op meerdere indexers, dan blijft die van de indexer met de hoogste prioriteit over.

## Automatisch downloaden

Op de tab Configuratie kies je vanaf welke score de beste release van een game vanzelf gaat: uit (standaard), of vanaf 10, 9, 8, 7, 6 of 5.

Bundels gaan alleen vanzelf met `AUTO_BUNDLES=true`. Per ronde gaan er hooguit `MAX_GRABS_PER_RUN` releases uit.

Begin met uit en kijk een paar dagen of de scores kloppen met hoe updates op jouw indexers heten. Vanaf 9 is voorzichtig; vanaf 7 neemt ook releases mee waarvan de versie is afgeleid.

Een verstuurde release die na `GRAB_WAIT_HOURS` (48 uur) nog niet in je bibliotheek staat, geldt als mislukt. NSWHunter slaat hem daarna over en biedt de volgende kandidaat aan.

## Zoeken en API-limieten

Elk uur (`SYNC_INTERVAL_MINUTES`) haalt NSWHunter de bibliotheek op en doet het één zoekactie zonder zoekterm: de nieuwste posts van al je usenet-indexers, vergeleken met alles wat ontbreekt.

Daarnaast wordt elke game die iets mist op naam gezocht. Hoe vaak stel je in op de tab Configuratie onder **Automatisch zoeken**: elke 6, 12, 24 of 48 uur. Dat kost per game één API-call per indexer. Met 40 games en 3 indexers is dat bij 6 uur 160 calls per indexer per dag; kies 24 of 48 uur als een indexer een daglimiet heeft. Met **Zoek nu** in het paneel zoek je één game direct.

## DLC

Met **Ook ontbrekende DLC zoeken** op de tab Configuratie worden ook de DLC's gezocht die je bibliotheek mist. Ze staan in de kaart van de game, onder de update.

- Een release met de title ID van de DLC krijgt score 10.
- Staat de naam van de DLC in de titel, dan is de score 8. Heeft een game meerdere DLC's met bijna dezelfde naam ("In-Game Commentary - Dutch", "... - Spanish"), dan hoort een release bij de DLC die hij het best noemt en valt hij bij de andere af.
- Een release die alleen zegt dat het DLC van de game is ("DLC Unlocker", "DLC Pack") krijgt score 3 en staat bij elke ontbrekende DLC van die game.

## Ontwikkelen en testen

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

De tests draaien tegen nagebootste versies van de bibliotheek, Prowlarr en NZBGet (`tests/fakes.py`). `commit-git.sh` draait ze vanzelf in het image. Los draaien:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

```bash
python -m pytest
```

## Nieuwe versie uitbrengen

1. Verhoog `__version__` in `app/version.py`.
2. Zet bovenaan in [CHANGELOG.md](CHANGELOG.md) een sectie `## [X.Y.Z] - JJJJ-MM-DD` met wat er veranderd is.
3. Draai `./commit-git.sh -r "korte omschrijving"`.

Het script draait de tests, controleert op geheimen, pusht naar `main` en maakt release `vX.Y.Z` met de tekst uit de changelog. GitHub bouwt daarna de images:

| Gebeurtenis | Image |
|---|---|
| Push naar `main` | `ghcr.io/<account>/nswhunter:latest` |
| Release `vX.Y.Z` | `ghcr.io/<account>/nswhunter:X.Y.Z` en `:X.Y` |

Zonder `-r` pusht het script alleen; `latest` wordt dan opnieuw gebouwd, zonder nieuwe release. Haal daarna in Portainer de stack opnieuw op (**Pull and redeploy**).

## Opbouw

| Bestand | Inhoud |
|---|---|
| `app/matcher.py` | Beoordeelt één releasenaam voor één game |
| `app/clients.py` | Praat met de bibliotheek, Prowlarr, NZBGet en SABnzbd |
| `app/hunter.py` | Een ronde: ophalen, zoeken, beoordelen, versturen |
| `app/main.py` | Webpaneel en planning |
| `app/config.py` | Instellingen uit omgevingsvariabelen |
| `entrypoint.sh` | Start de app als `PUID`:`PGID` |
| `commit-git.sh` | Zet de werkmap op GitHub en maakt een release |
| `.github/workflows/docker.yml` | Test, scant en bouwt het image op GitHub |

De toestand staat in `/data/state.json`. Verwijder dat bestand om opnieuw te beginnen.
