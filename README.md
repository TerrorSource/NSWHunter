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
| Downloadclient | NZBGet (adres, ControlUsername, ControlPassword), SABnzbd (adres, API key) of de downloadclient die in Prowlarr is ingesteld |
| Automatisch downloaden | Zie [Automatisch downloaden](#automatisch-downloaden) |
| Automatisch zoeken | Elke 6, 12, 24 of 48 uur, zie [Zoeken en API-limieten](#zoeken-en-api-limieten) |
| Paneel | Gebruikersnaam en wachtwoord. Zonder wachtwoord heeft het paneel geen inlog. |

Elke service heeft een **Test**-knop die de verbinding probeert met wat er in het formulier staat, ook als het nog niet is opgeslagen. **Opslaan en verbindingen testen** bewaart de instellingen, probeert elke service en start een ronde. De instellingen staan in `/data/settings.json`, alleen leesbaar voor de app-gebruiker. Keys en wachtwoorden gaan nooit terug naar de browser: een leeg veld betekent "houden wat er staat", met **Wis** maak je er een leeg.

Dezelfde instellingen kunnen ook als omgevingsvariabele in de compose staan (`SLM_URL`, `PROWLARR_API_KEY`, …). Dat is dan de beginwaarde; een opgeslagen waarde gaat voor. De overige instellingen (tempo, indexers, meldingen) staan alleen in de compose, zie [.env.example](.env.example).

## Hoe een release beoordeeld wordt

Releasenamen hebben geen vast format, dus NSWHunter zoekt drie dingen ergens in de titel:

- **Welke game.** Een title ID (`0100623017A58800`) is doorslaggevend. Anders moet de gamenaam er als geheel in staan. Staat er een vervolgnummer achter (`Hades II`), dan is het een andere game. Staan er andere extra woorden bij, dan is het een twijfelgeval.
- **Welke versie.** Een intern nummer (`v131072`) wordt direct vergeleken met `localUpdate` en `latestUpdate` uit de export. Een zichtbare versie (`v1.7.1`) is niet om te rekenen naar een intern nummer. Daarvoor gebruikt NSWHunter de releasedatums van titledb: een release bevat de update die op de dag van plaatsen de nieuwste was. Kwam update 11 uit op 29 september en is `Update v1.7.1` op 30 september geplaatst, dan is dat waarschijnlijk update 11. Staan beide versies ooit samen in één titel, dan onthoudt NSWHunter die vertaling.
- **Wat het is.** Alleen DLC, het basisspel (`v0`, `1.0.0`) en versies die je al hebt vallen af. Een bundel (basisspel + update) blijft kandidaat, maar staat lager.

Dat geeft drie niveaus:

| Niveau | Betekenis |
|---|---|
| Zeker | Juiste game (title ID of exacte naam) en een intern versienummer dat nieuwer is dan het jouwe |
| Waarschijnlijk | Exacte naam, zichtbare versie, geplaatst na de release van de nieuwste update |
| Twijfel | Naam wijkt af, of niet te zien welke versie het is |

## Automatisch downloaden

`AUTO_DOWNLOAD` bepaalt wat er zonder klik gebeurt:

- `off` (standaard): niets. Alles wacht in het paneel.
- `sure`: zekere releases die de nieuwste update zijn, gaan vanzelf.
- `likely`: ook waarschijnlijke releases gaan vanzelf.

Twijfelgevallen en tussenversies gaan nooit vanzelf. Bundels alleen met `AUTO_BUNDLES=true`. Per ronde gaan er hooguit `MAX_GRABS_PER_RUN` releases uit.

Begin met `off` en kijk een paar dagen of de beoordelingen kloppen met hoe updates op jouw indexers heten.

Een verstuurde release die na `GRAB_WAIT_HOURS` (48 uur) nog niet in je bibliotheek staat, geldt als mislukt. NSWHunter slaat hem daarna over en biedt de volgende kandidaat aan.

## Zoeken en API-limieten

Elk uur (`SYNC_INTERVAL_MINUTES`) haalt NSWHunter de bibliotheek op en doet het één zoekactie zonder zoekterm: de nieuwste posts van al je usenet-indexers, vergeleken met alles wat ontbreekt.

Daarnaast wordt elke game die iets mist op naam gezocht. Hoe vaak stel je in op de tab Configuratie onder **Automatisch zoeken**: elke 6, 12, 24 of 48 uur. Dat kost per game één API-call per indexer. Met 40 games en 3 indexers is dat bij 6 uur 160 calls per indexer per dag; kies 24 of 48 uur als een indexer een daglimiet heeft. Met **Zoek nu** in het paneel zoek je één game direct.

## DLC

Met `INCLUDE_DLC=true` krijgt elke ontbrekende DLC een eigen item. Alleen een release met de title ID van die DLC is zeker. Staat alleen de naam erin, dan is het waarschijnlijk of twijfel.

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
