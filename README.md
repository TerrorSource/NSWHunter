# NSWHunter

Searches your indexers for the Switch updates and DLC that your library misses and sends them to your download client.

1. Fetches the export of [switch-library-manager-web](https://github.com/DeLFuS77/switch-library-manager-web) and takes all games that miss an update or DLC.
2. Searches for releases of those games: through Prowlarr, or on a Newznab or Torznab indexer directly.
3. Judges each release: is it the right game, is the version newer than yours, is it an update?
4. Shows the candidates in a web panel. You click **Download**, or you let certain releases be sent automatically.
5. Sends the release to a download client: NZBGet or SABnzbd for usenet, qBittorrent, Transmission or uTorrent for torrents.

Once the update is in your library, the item disappears by itself.

## Installing

Use [docker-compose.yml](docker-compose.yml): replace the two `/path/to/...` folders by folders on your server and set `TZ`, `PUID` and `PGID` to yours. The panel is on port 3033.

- `/data` holds the settings and the state, `/backup` the backups of both.
- The container runs read-only and without privileges; it only writes to those two folders.
- If the image is private, the server needs a login for `ghcr.io` to pull it: your GitHub username and a token with the `read:packages` scope.

## The first login

At the first start NSWHunter makes the user `admin` with a password it makes up, and writes both to the log of the container:

```
  Log in to the panel on port 3033 with
    username: admin
    password: 4mZ0-example-Qx7
  You have to choose a password of your own at the first login.
```

With that password the panel lets you do one thing: choose a password of your own (at least 8 characters) and, if you want, another username. Until then the lines are in the log at every start; after that they are gone and the made-up password no longer works.

## Setting up

The settings are in the menu on the left; every field has its explanation next to it. Three things have to be filled in:

1. **Settings > Connect**: the address of Switch-library-manager-web and an API key (My account > API keys; Read only is enough). Optionally a connection for notifications: Telegram, Discord or Apprise.
2. **Settings > Indexers**: your Prowlarr, or a Newznab or Torznab indexer directly.
3. **Settings > Download Clients**: NZBGet or SABnzbd for usenet; qBittorrent, Transmission or uTorrent for torrents. Torrents are only searched when a torrent client is enabled.

The rest has defaults that work: **Media Management** (automatic download, searching, DLC), **General** (login, logging, backups) and **UI** (theme, dates).

## The panel

The panel is laid out as Sonarr and Radarr are.

- **Games**: every game of your library and whether it is complete.
- **Wanted**: every game that misses an update or DLC, with the releases that were found. A row has a **Download** button for its best release; a click on the name shows all of them. The tiles on top filter the list.
- **Activity**: the **Queue** (sent, not in the library yet), the **History** (sent, arrived, failed) and the **Blocklist** (rejected and failed releases).
- **System**: **Status** (what does not work), **Backup**, **Events** and **Log Files**.

In the toolbar of Wanted, **Search All** searches every game now and **Download All** sends the best release of every game that scores 9 or 10. If a round breaks, every page says so in a red bar.

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

On the Media Management page you choose from which score the best release of a game is sent automatically: off (default), or from 10, 9, 8, 7, 6 or 5.

Bundles are sent automatically only with `AUTO_BUNDLES=true`. Per round at most `MAX_GRABS_PER_RUN` releases are sent.

Start with off and watch for a few days whether the scores match how updates are named on your indexers. From 9 is careful; from 7 also takes releases whose version is derived.

## After sending

NSWHunter asks the download client every two minutes how a sent release is doing.

- **Failed:** the release goes to the blocklist and the next one gets its turn.
- **Downloaded:** Switch-library-manager-web is asked to scan and the library is read again. Scanning on request needs an API key with the Editor role.
- **Downloaded, but not in the library after the waiting time** (default 60 minutes, under Media Management): you get a notification and nothing else is sent.
- **Unknown to the client after the waiting time:** it counts as failed.

## Choosing in Telegram

**Choose in Telegram** is a setting of a Telegram connection (Settings > Connect) and is off until you switch it on. It also needs the trigger On Manual Interaction Required. With it on, you get one message for every release that awaits your choice, with the buttons **Download** and **Reject**. A press does the same as the button in the panel, and the message then says what was done.

- At most 10 questions per round, the highest scores first; the rest follow in the next rounds. Every release is asked about once.
- Only the chat that is set as Chat ID can press the buttons. A press from anywhere else is ignored.
- Switch it on only for a bot that NSWHunter has to itself. NSWHunter then reads what the bot receives, and two programs cannot read one bot: the other one would miss its messages, or NSWHunter its presses. NSWHunter only listens to Telegram while a question is open.
- Switched off, you get one message that says how many releases await your choice.

## Security

- **Login.** The panel has a login screen of its own; the browser shows no pop-up. The first start makes up a password that has to be changed at the first login (see [The first login](#the-first-login)). A login lasts 30 days in a cookie that scripts cannot read and that other sites cannot send. **Log out** ends it. Only a hash of the password is stored, and a new password logs every other browser out.
- **Wrong logins.** After 5 wrong logins from one address it has to wait: 30 seconds, and twice as long after every next wrong one, up to 15 minutes.
- **No encryption by itself.** The panel speaks HTTP. Inside your home network that is usual; to reach it from outside, put it behind a reverse proxy with HTTPS. The password then crosses the network once per login instead of with every request.
- **Host names.** The panel answers to an IP address and to names that only exist inside a home network (`nas`, `nas.local`, `nas.lan`). Any other name is refused, so a website cannot reach the panel through your browser by pointing a name of its own at your NAS. If you use a domain name, fill it in under **Host names** on the General page or in `PANEL_HOSTS`.
- **Keys stay with their address.** A saved key or password is never sent to a changed address; you fill it in again.
- **The page.** It runs only its own script, loads nothing from elsewhere and cannot be shown inside another page.
- **The container.** Read-only file system, no privileges, every answer of a service limited in size.

Forgot the password? Stop the container, remove `PANEL_PASSWORD` from `/data/settings.json` and start it again: NSWHunter makes up a new password and writes it to the log of the container.

## Backups

A backup is a zip of the settings (with their keys and passwords) and the state. NSWHunter makes one every 7 days in `/backup` and removes the automatic ones after 28 days; folder, interval and retention are on the General page. **System > Backup** lists the backups, with **Backup Now**, **Download**, **Restore** and **Delete**. A backup you make yourself stays until you remove it. Restoring replaces the settings and the state at once, without a restart.

## Searching and API limits

Every hour (`SYNC_INTERVAL_MINUTES`) NSWHunter fetches the library and does one search without a search term: the newest posts of all your indexers, compared with everything that is missing.

In addition, every game that misses something is searched by name. You set how often on the Media Management page under **Automatic search**: every 6, 12, 24 or 48 hours. That costs one API call per indexer per game. With 40 games and 3 indexers that is 160 calls per indexer per day at 6 hours; choose 24 or 48 hours if an indexer has a daily limit. With **Search now** in the panel you search one game at once.

## DLC

With **Also search for missing DLC** on the Media Management page the DLC that your library misses is searched as well. It is in the card of the game, below the update.

- A release with the title ID of the DLC gets score 10.
- If the name of the DLC is in the title, the score is 8. If a game has several DLC with almost the same name ("In-Game Commentary - Dutch", "... - Spanish"), a release belongs to the DLC it names best and is ruled out for the others.
- A release that names no DLC ("DLC Unlocker", "DLC Pack") is listed once per game, under **DLC pack**, with score 5.
