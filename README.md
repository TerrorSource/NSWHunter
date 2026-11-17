# NSWHunter

Searches usenet for the Switch updates that your library misses and sends them to your download client.

1. Fetches the export of [switch-library-manager-web](https://github.com/DeLFuS77/switch-library-manager-web) (`/export/library.json`) and takes all games with `updateMissing: true`.
2. Searches for releases of those games through Prowlarr.
3. Judges each release: is it the right game, is the version newer than yours, is it an update?
4. Shows the candidates in a web panel. You click **Download**, or you let certain releases be sent automatically.
5. Sends the NZB to NZBGet (category `games`), SABnzbd or the download client of Prowlarr.

Once the update is in your library, the item disappears by itself.

## Installing

The image is at `ghcr.io/<account>/nswhunter`. In Portainer: **Stacks > Add stack** and paste [docker-compose.yml](docker-compose.yml):

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

The repo is private, and so is the image. Portainer then needs a registry to pull it: **Registries > Add registry > Custom**, URL `ghcr.io`, username `<account>` and as password a GitHub token with the `read:packages` scope. Or make the package public under GitHub > Packages > nswhunter > Package settings.

## Setting up

Open `http://<nas>:3033`. Without settings you land on the **Configuration** tab:

| Setting | Where to find it |
|---|---|
| Library: address and API key | Switch-library-manager-web > My account > API keys > Make a key, with the Read only role. The key starts with `slm_` and is shown once. If login is switched off there, no key is needed. |
| Prowlarr: address and API key | Prowlarr > Settings > General > API Key |
| Prowlarr: categories | `1000` is Console with all its subcategories. Only those are searched. Releases that the indexer filed under another console (PS4, Xbox, Wii, …) or that have another platform in the name are ruled out: the Switch has no category of its own. |
| Download client | NZBGet (address, ControlUsername, ControlPassword), SABnzbd (address, API key) or the download client that is set up in Prowlarr |
| Automatic download | See [Automatic download](#automatic-download) |
| Automatic search | Every 6, 12, 24 or 48 hours, see [Searching and API limits](#searching-and-api-limits) |
| Wait for the library | How long a sent release may take to show up in your library, see [After sending](#after-sending) |
| Notifications (Telegram) | Bot token from @BotFather and your chat ID (from @userinfobot). First send your bot one message yourself. You get a message when something was sent automatically, something awaits your choice, a download failed or something arrived. |
| Panel | Username and password. Without a password the panel has no login. Only a hash of the password is stored. |

Each service has a **Test** button that tries the connection with what is in the form, even if it has not been saved yet. **Save and test the connections** stores the settings, tries each service and starts a round. The settings are in `/data/settings.json`, readable only by the app user. Keys and passwords never go back to the browser: an empty field means "keep what is there", and **Clear** empties one.

The same settings can also be environment variables in the compose file (`SLM_URL`, `PROWLARR_API_KEY`, …). That is then the initial value; a saved value takes precedence. The other settings (timing, indexers, notifications through Apprise) are in the compose file only, see [.env.example](.env.example).

## The panel

The tiles at the top of the **Updates** tab are buttons. A click on one shows only the games that belong to it:

- **games in your library**: the number is your whole library; the list holds every game that misses an update or DLC.
- **updates missing** and **DLC missing**; the DLC tile is only shown when missing DLC is searched.
- **awaiting your choice**: games with a candidate release that has not been sent.
- **added to queue**: games with a release that was sent to the download client.
- **download failed**: downloads that the download client reported as failed, or that it did not know and that had not arrived in the library after the waiting time. Each can be sent once more with **Try again** or taken off the list with **Dismiss**.
- **ignored**: only shown when you ignore something.

The row with the service checks (Library, Prowlarr, Download client, Version list, …) is on the **Configuration** tab only.

## How a release is judged

Release names have no fixed format, so NSWHunter looks for three things anywhere in the title:

- **Which game.** A title ID (`0100623017A58800`) is decisive. Otherwise the game name must be in it as a whole. If a sequel number follows it (`Hades II`), it is another game. If there are other extra words, it is a doubtful case.
- **Which version.** An internal number (`v131072`) is compared directly with `localUpdate` and `latestUpdate` from the export. A visible version (`v1.7.1`) is translated with the version ladder, see below.
- **What it is.** DLC only, the base game (`v0`, `1.0.0`) and versions you already have are ruled out. A bundle (base game + update) stays a candidate, but ranks lower.

### The version ladder

No single source has both the visible and the internal version number of an update. NSWHunter makes the link itself, per game:

1. **The fixed point is your own version.** The library knows both numbers of your update, for example 1.7.0 = update 10.
2. **Higher versions are later updates.** If release names contain a `v1.7.1`, that is the next update that is known: update 11.
3. **Without a fixed point the date sets the bottom rung.** A version that was first posted when update 10 was the latest, is update 10. Above that the order counts again.

The order is more reliable than the date: the lists of updates often add a new update weeks late. That is why NSWHunter remembers every version that occurs in release names, also of releases that are ruled out. The panel shows the ladder per game: "v1.7.0 = update 10 · v1.7.1 = update 11".

### The score

Each release gets a score from 1 to 10: the chance that the download is the right one. The score is the product of three chances: that it is this game, that it is the latest update, and that it is an update and nothing else.

| Score | What it usually is |
|---|---|
| 10 | Title ID of the game and the internal version number of the latest update |
| 9 | Exact name with the internal version number, or a visible version that is derived through your own version as the latest update |
| 7-8 | Exact name; the version is derived from posting dates or from the numbering (1.0.35.0 = update 35) |
| 4-6 | An in-between version, a bundle, an update with a crack, extra words in the name, or no way to see which version it is |
| 1-3 | The name only resembles it, or there is no version in it |

What lowers the score: a bundle with the base game (×0.75), a crack (×0.9), extra words in the name (×0.5 instead of ×0.9), a title without a platform (×0.85) and a deviating size. If an "update" is as big as the whole game, the base game is probably included (×0.75); if it is more than five times as big or as small as your own update, that counts too (×0.8). The panel shows the reason with each release.

Below the releases of a game is **ruled out**: the releases of that game that do not take part, with the reason (another platform, not newer than your own version, base game). With **Download anyway** you send one after all.

Within a game the releases are ordered by score, then by age (newest post first), then by the priority of the indexer in Prowlarr. If the same release is on several indexers, the one from the indexer with the highest priority remains.

## Automatic download

On the Configuration tab you choose from which score the best release of a game is sent automatically: off (default), or from 10, 9, 8, 7, 6 or 5.

Bundles are sent automatically only with `AUTO_BUNDLES=true`. Per round at most `MAX_GRABS_PER_RUN` releases are sent.

Start with off and watch for a few days whether the scores match how updates are named on your indexers. From 9 is careful; from 7 also takes releases whose version is derived.

## After sending

NSWHunter asks the download client every two minutes how a sent release is doing. That works with NZBGet and SABnzbd; if the download goes through Prowlarr, there is no status and only the time counts.

| What the download client says | What NSWHunter does |
|---|---|
| Busy or in the queue | Wait, however long it takes |
| Failed | The release is skipped and listed under **download failed**; the next one gets its turn at once |
| Downloaded | Switch-library-manager-web gets the request to scan, and the library is read again |
| Downloaded, but not in the library after the waiting time | You get a notification. No next release is sent: the folder of your download client apparently does not reach the library |
| Does not know the release | After the waiting time it counts as not arrived: it is listed under **download failed** and the next one gets its turn |

You set the waiting time on the Configuration tab (**Wait for the library**, default 60 minutes). Scanning on request only works if the API key of Switch-library-manager-web has the Editor role; with "Read only" NSWHunter waits for the library's own scan.

## Searching and API limits

Every hour (`SYNC_INTERVAL_MINUTES`) NSWHunter fetches the library and does one search without a search term: the newest posts of all your usenet indexers, compared with everything that is missing.

In addition, every game that misses something is searched by name. You set how often on the Configuration tab under **Automatic search**: every 6, 12, 24 or 48 hours. That costs one API call per indexer per game. With 40 games and 3 indexers that is 160 calls per indexer per day at 6 hours; choose 24 or 48 hours if an indexer has a daily limit. With **Search now** in the panel you search one game at once.

## DLC

With **Also search for missing DLC** on the Configuration tab the DLC that your library misses is searched as well. It is in the card of the game, below the update.

- A release with the title ID of the DLC gets score 10.
- If the name of the DLC is in the title, the score is 8. If a game has several DLC with almost the same name ("In-Game Commentary - Dutch", "... - Spanish"), a release belongs to the DLC it names best and is ruled out for the others.
- A release that names no DLC ("DLC Unlocker", "DLC Pack") is listed once per game, under **DLC pack**, with score 5.

## Developing and testing

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

The tests run against fake versions of the library, Prowlarr and NZBGet (`tests/fakes.py`). `commit-git.sh` runs them by itself in the image. To run them separately:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

```bash
python -m pytest
```

## Releasing a new version

1. Raise `__version__` in `app/version.py`.
2. Put a section `## [X.Y.Z] - YYYY-MM-DD` at the top of [CHANGELOG.md](CHANGELOG.md) with what changed.
3. Run `./commit-git.sh -r "short description"`.

The script runs the tests, checks for secrets, pushes to `main` and creates release `vX.Y.Z` with the text from the changelog. GitHub then builds the images:

| Event | Image |
|---|---|
| Push to `main` | `ghcr.io/<account>/nswhunter:latest` |
| Release `vX.Y.Z` | `ghcr.io/<account>/nswhunter:X.Y.Z` and `:X.Y` |

Without `-r` the script only pushes; `latest` is then rebuilt, without a new release. After that, pull the stack again in Portainer (**Pull and redeploy**).

## Layout

| File | Contents |
|---|---|
| `app/matcher.py` | Judges one release name for one game |
| `app/clients.py` | Talks to the library, Prowlarr, NZBGet and SABnzbd |
| `app/hunter.py` | One round: fetch, search, judge, send |
| `app/main.py` | Web panel and scheduling |
| `app/config.py` | Settings from environment variables |
| `entrypoint.sh` | Starts the app as `PUID`:`PGID` |
| `commit-git.sh` | Puts the working directory on GitHub and creates a release |
| `.github/workflows/docker.yml` | Tests, scans and builds the image on GitHub |

The state is in `/data/state.json`. Delete that file to start over.
