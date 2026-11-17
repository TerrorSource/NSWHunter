# Changelog

All changes per version. The version number is in `app/version.py`; each version has a section here and a release on GitHub.

## [2.0.0] - 2026-11-17

Version 2 because the panel now always has a login, and the login of the browser (the pop-up) is gone. After the update the panel asks you to log in, or to make a login if you had no password. Take the new [docker-compose.yml](docker-compose.yml) over in your stack to get the hardened container.

### Security

- **Login screen in the page.** The pop-up of the browser is gone. A login lasts 30 days in a cookie that scripts cannot read and other sites cannot send; **Log out** ends it. A new password logs every other browser out.
- **A login is required.** Without a password the panel shows nothing and asks to make a login: a username and a password of at least 8 characters. The password can be replaced, no longer removed.
- **Wrong logins have to wait:** after 5 from one address 30 seconds, twice as long after every next one, up to 15 minutes.
- **A saved key is only sent to its own address.** Before, the Test button used the address in the form with the key that was saved, so anyone who could reach the panel could have a key sent to an address of their own. Now a changed address needs its key or password typed again, for testing and for saving.
- **Host names.** The panel answers to an IP address and to names that only exist inside a home network. Other names are refused, unless they are filled in under **Host names** (`PANEL_HOSTS`). This stops a website from reaching the panel through your browser (DNS rebinding). Requests that come from another site are refused as well.
- **Headers** on every answer: the page runs only its own script, loads nothing from elsewhere and cannot be shown inside another page.
- **Limits** on the size of every answer of a service.
- **The container** in `docker-compose.yml` runs with a read-only file system, without privileges and with only the four capabilities the start needs.

### Added

- **A round that breaks is said out loud:** a red bar on every page, one message in Telegram, and the health check of the container turns red.
- **One game that cannot be handled no longer stops the round.** It is left out, written to the log once, and a yellow bar says how many were left out.
- **Download on the card.** A card names the best release of its game and has a Download button, so it need not be opened.
- **Download all with score 9+** sends the best release of every waiting game that scores 9 or 10. It asks once more in the page, and leaves bundles alone.
- **Restore.** What you rejected is listed below the releases of a game and can be taken back. Rejections of older versions, of which no name was kept, can be restored together.
- **Progress** of a download in the queue, as NZBGet or SABnzbd reports it.
- **Arrived:** a tile with what was sent and is now in your library, of the last 30 days.
- **Log:** the last 1000 lines instead of 60, with a filter for warnings and errors and a search box.
- **Choose in Telegram.** For a release that awaits your choice you get a message with the buttons Download and Reject, at most 10 per round. Only the chat that is set up can press them. It is off until you switch it on, on the Configuration tab, because it needs a bot that NSWHunter has to itself: it reads what the bot receives. Switched on, it replaces the message that says how many releases await your choice.

### Changed

- A DLC pack no longer asks for a choice while every missing DLC of its game is already on its way.
- Dismissing a failed download moves it to what you rejected, so it can still be restored.

## [1.8.0] - 2026-11-17

### Fixed

- **Rounds failed** with `TypeError: '<' not supported between instances of 'NoneType' and 'NoneType'`. Releases kept by an older version had no indexer priority, and sorting them stopped the round. They now get the priority Prowlarr has for their indexer.

### Added

- **The tiles are buttons.** A click on a tile on the Updates tab shows only the games that belong to it: games in your library, updates missing, DLC missing, awaiting your choice, added to queue, download failed, and ignored (only shown when you ignore something). The choice is remembered in your browser.
- **Download failed.** A download that the download client reports as failed, or that it does not know and that has not arrived in the library after the waiting time, is kept in a list per game with the reason. **Try again** sends it once more, **Dismiss** takes it off the list.
- In the queue and in the failed list the card of a game names the releases without opening it.

### Changed

- **Everything is in English:** the panel, the log, the notifications, the error messages, the README, this changelog and the comments in the code. Lines that are already in your log stay as they were written.
- "Games with something on its way" is now **added to queue**: the games with a release that was sent to the download client.
- The buttons Te beoordelen, Verstuurd, Nog niets gevonden, Genegeerd and Alles are gone; the tiles replace them.
- The row with the checks (Library, Prowlarr, Download client, Version list and the settings next to them) is on the Configuration tab only.
- The log shows dates and times in the format of your browser.

## [1.7.0] - 2026-11-16

### Added

- **Notifications through Telegram**, set on the Configuration tab (bot token, chat ID, button **Send test message**). You get a message when something was sent automatically, something awaits your choice, a download failed or something arrived.
- **Following downloads.** NSWHunter asks NZBGet or SABnzbd for the status every two minutes. If a download fails, the next release gets its turn at once. If it is downloaded, switch-library-manager-web gets the request to scan. The panel shows the status ("downloading", "downloaded, waiting for the library").
- **Wait for the library** can be set (30 minutes to 24 hours, default 60 minutes) instead of a fixed 48 hours.
- **Ruled out releases** per game, with the reason, and a button **Download anyway**.
- **Size counts in the score:** an "update" as big as the whole game, or more than five times as big or as small as your own update, scores lower.
- **DLC pack:** releases that name no DLC ("DLC Unlocker", "DLC Pack") are listed once per game instead of under every missing DLC.

### Changed

- **No Switch 2.** Titles with a Switch 2 ID (`04…`) from the library are skipped, and releases with `Switch 2`, `NSW2` or a Switch 2 title ID are ruled out.
- Only a hash of the panel password is stored now. A password that an older version stored in readable form is converted at start.
- If a download succeeded but is not in the library after the waiting time, no next release is sent; you get a notification.
- `GRAB_WAIT_HOURS` is replaced by `GRAB_WAIT_MINUTES`.

## [1.6.0] - 2026-11-16

### Added

- **Sorting** in the overview: by score, name, newest release, number of releases, number of updates behind, number of missing DLC and last searched. The arrow next to it reverses the order. The choice is remembered in your browser.

### Changed

- The overview is sorted by score (highest first) by default instead of by name.

## [1.5.1] - 2026-11-16

### Fixed

- Releases for other consoles were among the results: the Console category (1000) also contains PS4, Xbox, Wii and the rest. A release is now ruled out if the indexer filed it under another console (for example 1180, PS4), or if there is another platform in the name (`PS4`, `XBOX360`, a PlayStation product code like `CUSA34119`).

### Changed

- If a title contains no platform at all (no `NSW`, `Switch`, `NSP`, title ID or internal version number), the score is slightly lower and that is listed with the reason.

## [1.5.0] - 2026-11-16

### Fixed

- A game was listed as many times as it misses DLC (EA SPORTS FC 25 and 26 together 22 times), and under each DLC the releases of the other DLC were listed too. A release now belongs to the DLC it names best and is ruled out for the others.
- After downloading a release the other releases of that game disappeared from view. They now stay; the sent one is marked and another can still be downloaded.
- The same release was listed twice if two indexers write it with dots and with spaces.

### Changed

- **One card per game** that holds the update and all missing DLC. The tabs count games. **Ignore** on the card ignores everything of the game; it can also be done per update or DLC.
- If a sent update arrives that was not the latest, the game is back under awaiting your choice instead of counting as "not arrived" after 48 hours.
- Words from the name of a DLC no longer count as "extra words in the title".

## [1.4.0] - 2026-11-16

### Added

- **Score from 1 to 10** instead of Sure, Likely and Doubtful: the chance that a download is the right one. The panel shows the score per release and the highest score per game.
- **Automatic download from a score** (off, or from 10 down to 5). The old values `sure` and `likely` count as 9 and 7.
- **Categories** can be set on the Configuration tab (default `1000`, Console with all its subcategories). Results outside those categories are ruled out, even if Prowlarr returns them anyway.
- Versions that count the update themselves are recognised: if your own 1.0.31.0 is update 31, then 1.0.35.0 is update 35.

### Changed

- **Sorting** within a game: score, then age (newest post first), then the priority of the indexer in Prowlarr. Of the same release on several indexers, the one from the indexer with the highest priority remains.
- **Games are collapsed.** A click on the name shows the releases.
- "Update incl. Crack" is no longer a bundle; only "game incl. update" is. A crack lowers the score and is listed with the reason.
- A DLC counts as named in the title if the largest part of its name is in it.

## [1.3.0] - 2026-11-16

### Added

- **Version ladder:** a visible version from a release name (`v1.7.1`) is translated to the update number (update 11, `v720896`) by order instead of by date only. Your own version from the library is the fixed point (1.7.0 = update 10); a higher version is the next update. Without a version from the library the posting date sets the bottom rung.
- If that translation is derived entirely from your own version and it is the latest update, the release is **Sure**. If it rests partly on dates, it is **Likely**.
- NSWHunter remembers per game every version that occurs in release names, also of releases that are ruled out: those are rungs of the ladder. The panel shows the ladder per game ("v1.7.0 = update 10 · v1.7.1 = update 11").

### Changed

- The list of updates and dates now comes from the data source of switch-library-manager-web first and otherwise from blawar/titledb. The first one knows new updates sooner.
- A release is no longer ruled out because it was posted before the date of an update, unless the difference is more than 45 days: the date of a new update is often added to the lists weeks late (three weeks for NARUTO X BORUTO).
- After updating, all games are searched again once.

## [1.2.0] - 2026-11-16

### Fixed

- Searching never gave results: NSWHunter asked Prowlarr for all torrent indexers (`-2`) instead of all usenet indexers (`-1`).

### Added

- **Test** button for Library, Prowlarr and Download client on the Configuration tab. The test uses what is in the form, even if it has not been saved yet. The Prowlarr test reports how many usenet indexers there are.
- **Automatic search** can be set to every 6, 12, 24 or 48 hours (`SEARCH_INTERVAL_HOURS`). Every game that misses something is searched by name once per that time.
- **Log** tab.
- A release with only a visible version (`v1.7.1`) gets the update number that was the latest on the day of posting ("probably update 11"). If that is the latest update, the release is "likely".
- The panel shows update numbers ("you have update 10 → latest is update 11") next to the internal version numbers.

### Changed

- **Search now** no longer waits for a running round.
- If a visible version is higher than your own version, the release is no longer ruled out on the date alone.
- Of equivalent releases the most downloaded one is at the top.
- Downloading through Prowlarr searches again by itself if Prowlarr no longer knows the release (after half an hour).
- `BACKLOG_DAYS` is replaced by `SEARCH_INTERVAL_HOURS`; `BACKLOG_PER_RUN` is 0 by default (no limit).

## [1.1.0] - 2026-11-16

### Added

- **Configuration** tab in the panel: you set the addresses and keys of the library, Prowlarr and the download client, automatic download, DLC and the login of the panel there. Saving tests the connections at once and starts a round.
- The settings are in `/data/settings.json` (readable only by the app user) and take precedence over the values in the compose file. Keys and passwords are never sent back to the browser.
- Without settings the panel opens directly on the Configuration tab.

### Changed

- `docker-compose.yml` now contains only `TZ`, `PUID`, `PGID`, the port and the data folder.
- Python 3.12 to 3.15 and apprise 1.13.1 to 2.2.0 (taken over from Dependabot).

## [1.0.0] - 2026-11-16

First version.

### Added

- Fetches `/export/library.json` from switch-library-manager-web and keeps one item per missing update (and optionally per missing DLC).
- Searches through Prowlarr: every round the newest posts of all usenet indexers, plus a few games by name.
- Judges releases without a fixed name format on game (title ID or name), version (internal number or visible version) and kind (update, bundle, DLC, base game).
- Sends a chosen release to NZBGet, SABnzbd or the download client of Prowlarr. Sending automatically can be set with `AUTO_DOWNLOAD`.
- Web panel on port 3033 to judge candidates, send them, reject them and ignore games.
- Runs as `PUID`:`PGID` (default 1000:1000); `/data` gets that owner at start.
- Image at `ghcr.io/<account>/nswhunter` for amd64 and arm64: `latest` on every push, `X.Y.Z` and `X.Y` on a release.
