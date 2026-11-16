# NSWHunter

Zoekt de Switch-updates die in je bibliotheek ontbreken op usenet en stuurt ze naar je downloadclient.

1. Haalt de export van [switch-library-manager-web](https://github.com/DeLFuS77/switch-library-manager-web) op (`/export/library.json`) en neemt alle games met `updateMissing: true`.
2. Zoekt via Prowlarr naar releases van die games.
3. Beoordeelt elke release: is het de juiste game, is de versie nieuwer dan de jouwe, is het een update?
4. Toont de kandidaten in een webpaneel. Jij klikt op **Download**, of je laat zekere releases vanzelf gaan.
5. Stuurt de NZB naar NZBGet (categorie `games`), SABnzbd of de downloadclient van Prowlarr.

Staat de update daarna in je bibliotheek, dan verdwijnt het item vanzelf.

## Installeren

Het image staat op `ghcr.io/<account>/nswhunter`. In Portainer: **Stacks > Add stack**, plak [docker-compose.yml](docker-compose.yml) en vul de waarden in.

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
      - SLM_URL=http://192.168.1.10:3000
      - SLM_API_KEY=
      - PROWLARR_URL=http://192.168.1.10:9696
      - PROWLARR_API_KEY=
      - DOWNLOAD_CLIENT=nzbget
      - DOWNLOAD_CATEGORY=games
      - NZBGET_URL=http://192.168.1.10:6789
      - NZBGET_USER=nzbget
      - NZBGET_PASSWORD=
      - AUTO_DOWNLOAD=off
      - INCLUDE_DLC=false
      - PANEL_USER=admin
      - PANEL_PASSWORD=
    ports:
      - 3033:3033
    volumes:
      - /path/to/nswhunter/data:/data
```

| Instelling | Waar je hem vindt |
|---|---|
| `SLM_URL`, `SLM_API_KEY` | Switch-library-manager-web > Mijn account > API keys > maak een key met "Alleen lezen". De key begint met `slm_`. |
| `PROWLARR_URL`, `PROWLARR_API_KEY` | Prowlarr > Settings > General > API Key |
| `NZBGET_URL`, `NZBGET_USER`, `NZBGET_PASSWORD` | NZBGet > Settings > Security (ControlUsername en ControlPassword) |
| `AUTO_DOWNLOAD` | `off`, `sure` of `likely`, zie [Automatisch downloaden](#automatisch-downloaden) |
| `PANEL_PASSWORD` | Leeg = paneel zonder inlog |

Het paneel staat daarna op `http://<nas>:3033`. Alle instellingen met uitleg staan in [.env.example](.env.example).

De repo is privé, en daarmee het image ook. Portainer heeft dan een registry nodig om het op te halen: **Registries > Add registry > Custom**, URL `ghcr.io`, gebruikersnaam `<account>` en als wachtwoord een GitHub-token met het recht `read:packages`. Of zet het pakket op openbaar onder GitHub > Packages > nswhunter > Package settings.

Vul keys en wachtwoorden in Portainer in, niet in `docker-compose.yml` in deze map: dat bestand gaat naar GitHub, en `commit-git.sh` weigert een compose met ingevulde keys.

## Hoe een release beoordeeld wordt

Releasenamen hebben geen vast format, dus NSWHunter zoekt drie dingen ergens in de titel:

- **Welke game.** Een title ID (`0100623017A58800`) is doorslaggevend. Anders moet de gamenaam er als geheel in staan. Staat er een vervolgnummer achter (`Hades II`), dan is het een andere game. Staan er andere extra woorden bij, dan is het een twijfelgeval.
- **Welke versie.** Een intern nummer (`v131072`) wordt direct vergeleken met `localUpdate` en `latestUpdate` uit de export. Een zichtbare versie (`v1.0.4`) is niet om te rekenen naar een intern nummer. Daarvoor gebruikt NSWHunter de releasedatums van titledb: een release die is geplaatst nadat de nieuwste update uitkwam, bevat waarschijnlijk die update. Staan beide versies ooit samen in één titel, dan onthoudt NSWHunter die vertaling.
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

Elke ronde (`SYNC_INTERVAL_MINUTES`, standaard 60) doet NSWHunter:

- één zoekactie zonder zoekterm: de nieuwste posts van al je usenet-indexers, vergeleken met alle ontbrekende updates;
- een zoekactie op naam voor hooguit `BACKLOG_PER_RUN` (10) games. Elke game komt eens per `BACKLOG_DAYS` (7) aan de beurt.

Op naam zoeken kost per game één API-call per indexer. Heb je veel ontbrekende updates en een indexer met een daglimiet, verlaag dan `BACKLOG_PER_RUN`. Met **Zoek nu** in het paneel zoek je één game direct.

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
