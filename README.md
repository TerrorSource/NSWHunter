# NSWHunter

Searches your indexers for the Switch updates and DLC that your library misses, and for games you add yourself, and sends them to your download client.

1. Fetches the export of [switch-library-manager-web](https://github.com/DeLFuS77/switch-library-manager-web) and takes all games that miss an update or DLC.
2. Searches for releases of those games: through Prowlarr, or on a Newznab or Torznab indexer directly.
3. Judges each release: is it the right game, is the version newer than yours, is it an update?
4. Shows the candidates in a web panel. You click **Download**, or you let certain releases be sent automatically.
5. Sends the release to a download client: NZBGet or SABnzbd for usenet, qBittorrent, Transmission or uTorrent for torrents.

Once the update is in your library, the item disappears by itself.

The [wiki](../../wiki) has the rest: a step-by-step start, a tour of the panel with screenshots, every guide, and help when something does not work.

## Installing

Use [docker-compose.yml](docker-compose.yml): replace the `/path/to/...` folder by a folder on your server, and set `TZ` and the `user:` line to yours. The panel is on port 3033.

- `/config` holds the settings, the state and the backups of both, as with Sonarr and Radarr. The folder has to belong to the user of the `user:` line: `chown -R 1000:1000 <folder>`.
- `/data` is left free for the folder of your media.
- The container runs read-only, never as root and without privileges; it only writes to the folders you give it.
- An installation of before version 3.11 has its settings in `/data`. That keeps working; to move, mount the same folder at `/config` instead.
- HTTPS is optional (Settings > General): publish its port as well, like `3443:3443`.
- Importing is optional (Settings > Media Management): to have finished downloads put in the folder of their game, add the folder with your downloads and your library as a volume too, under the same path your download client uses for it (like `/data`).
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

Forgot your password, or lost the phone of your two-step login (optional, Settings > General)? Put an empty file named `reset-password` in the config folder and restart the container: a new password is made up and written to the log, and two-step login is off. Your username and all other settings stay.

## Setting up

The settings are in the menu on the left; every field has its explanation next to it. Three things have to be filled in:

1. **Settings > Connect**: the address of Switch-library-manager-web and an API key (My account > API keys; Read only is enough). Optionally a connection for notifications: Telegram, Discord or Apprise.
2. **Settings > Indexers**: your Prowlarr, or a Newznab or Torznab indexer directly.
3. **Settings > Download Clients**: NZBGet or SABnzbd for usenet; qBittorrent, Transmission or uTorrent for torrents. Torrents are only searched when a torrent client is enabled.

**SABnzbd** renames files with an extension it does not know, because of its option *Deobfuscate final filenames* (on by default), and `.nsp` is not on its list. Add `nsp, nsz, xci, xcz` to **Config > Special > ext_rename_ignore** in SABnzbd, and it leaves Switch files as they are.

The rest has defaults that work: **Media Management** (automatic download, searching, DLC), **General** (login, logging, backups) and **UI** (theme, dates).

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

Bundles are sent automatically only with `AUTO_BUNDLES=true`, a game of the wishlist only with **Automatic Download for the Wishlist** on. Per round at most `MAX_GRABS_PER_RUN` releases are sent.

Start with off and watch for a few days whether the scores match how updates are named on your indexers. From 9 is careful; from 7 also takes releases whose version is derived.

## Choosing in Telegram

**Choose in Telegram** is a setting of a Telegram connection (Settings > Connect) and is off until you switch it on. It also needs the trigger On Manual Interaction Required. With it on, you get one message for every release that awaits your choice, with the buttons **Download** and **Reject**. A press does the same as the button in the panel, and the message then says what was done.

- At most 10 questions per round, the highest scores first; the rest follow in the next rounds. Every release is asked about once.
- Only the chat that is set as Chat ID can press the buttons. A press from anywhere else is ignored.
- Switch it on only for a bot that NSWHunter has to itself. NSWHunter then reads what the bot receives, and two programs cannot read one bot: the other one would miss its messages, or NSWHunter its presses. NSWHunter only listens to Telegram while a question is open.
- Switched off, you get one message that says how many releases await your choice.

## Backups

A backup is a zip of the settings (with their keys and passwords) and the state; with a **Backup Password** on the General page it is encrypted, and only NSWHunter can put it back, with that password. NSWHunter makes one every 7 days, in `/config/backups`, and removes the automatic ones after 28 days; folder, interval and retention are on the General page. **System > Backup** lists the backups, with **Backup Now**, **Download**, **Restore** and **Delete**. A backup you make yourself stays until you remove it. Restoring replaces the settings and the state at once, without a restart.
