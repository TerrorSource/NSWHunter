# Changelog

All changes per version. The version number is in `app/version.py`; each version has a section here and a release on GitHub.

## [3.7.0] - 2026-11-17

### Added

- **Every list sorts by the heads of its columns.** A click on a head sorts on that column, a second click turns the order around; an arrow shows which. That is Wanted, the lists on the page of a game, the Queue, the History, the Blocklist, Tasks, Backup, Events and Log Files (Games already did). The choice is kept per list, in your browser.
- **Download All in Interactive Search.** The button on top of the window sends the best release of every update and DLC of that game that awaits your choice, and says how many that is. A DLC pack is left out: it would bring what the DLC themselves bring.
- **Interactive Search on every row of the page of a game**, between Download and Ignore. It opens the window at that update or DLC.
- **Hide Failed Downloads** (Settings > Media Management, on by default). Failed downloads stay out of the lists: there is no "failed" label on Wanted and on the page of a game, and they are not listed in Interactive Search. And the same usenet release is not offered again when another indexer has it too: it is the same post, and would fail the same way. Failed downloads stay on Activity > Blocklist, where one can be tried again or removed, and in the History.

## [3.6.1] - 2026-11-17

### Fixed

- **Logging in over HTTPS no longer locks the same browser out of HTTP.** A browser does not let a plain cookie take the place of a secure one with the same name, so after a login over HTTPS a login over HTTP did not stick. A login over HTTPS now has a cookie of its own. Logins made before this version stay valid.
- The message for a host name the panel does not answer to pointed at a page that no longer exists; it now says Settings > General > Host Names.

### Changed

- The README points to the new wiki, and `.env.example` has the variables for HTTPS and the backup password.

## [3.6.0] - 2026-11-17

### Added

- **Two-step login, optional** (Settings > General). Set it up by scanning a QR code with an authenticator app; from then on logging in takes your password and the six-digit code of the app. A code works once, wrong codes have to wait like wrong passwords, and switching it off takes a code too. Lost your phone: remove `TOTP_SECRET` from `/data/settings.json` and restart.
- **HTTPS, optional** (Settings > General), on a port of its own next to HTTP, as in Sonarr and Radarr. With a certificate of your own (a PEM file and its key), or without one: then NSWHunter makes a certificate itself, which encrypts the connection but makes the browser warn once. It is switched on, moved and switched off without a restart; a certificate that cannot be used is refused when you save, and said on the Status page if it breaks later. The container has to publish the port.
- **Encrypted backups.** With a **Backup Password** (Settings > General) every new backup is encrypted, because a backup holds all keys and passwords of the settings. An encrypted backup is put back with that password; if the password of the settings is another one by then, the panel asks for the one the backup was made with. Without the password such a backup cannot be opened.
- **Sessions** (Settings > General): the browsers that are logged in, with their address and when they were last used, a button to log one out, and one to log out all others.
- **A browser test of the panel** runs with every build: it logs in for the first time, sets the panel up, opens every page, sends and removes a download, and checks a phone-sized screen. No image is built if it fails.

### Changed

- **The container never is root any more.** `docker-compose.yml` starts it as a user (`user: "1000:1000"`) and without any capability; the folders of `/data` and `/backup` have to belong to that user, and the container says so if they do not. A stack with `PUID` and `PGID` and the four `cap_add` lines keeps working as before.
- A bulk action on Wanted says why it did fewer than were ticked: which had no release to send, and what a download client or indexer answered.

## [3.5.0] - 2026-11-17

### Added

- **A page per game.** The name of a game, on Games, Wanted, in the Queue and in the History, opens its page: its picture, what you have and what is the latest, what it misses with the best release and the status of each, and the history of that game. The toolbar has Search Game, Interactive Search and Ignore. The Back button of the browser now goes back a page everywhere.
- **Posters on Games.** The **View** menu switches between the table and a wall of pictures; the bar under a picture says whether the game misses something.
- **Options** in the toolbar: which columns the table of the games shows, and how many rows a page of the Queue, the History, the Blocklist and the Events has (20, 50, 100 or 200).
- **Removing from the queue asks what to do**, as Sonarr and Radarr do: also take the download and its files out of the download client (NZBGet, SABnzbd, qBittorrent, Transmission, uTorrent), and add the release to the blocklist. What went through the download client of Prowlarr can only be removed there.
- **A search term of your own** in Interactive Search, for releases that are not named after the game. Such a search leaves the turn of the game in the searches by name alone.
- **Unsaved Changes.** Leaving a settings page with changes that were not saved asks first.

### Changed

- **The panel is drawn again only when something changed**, and once a minute for texts like "5 min ago". Before it was drawn again every eight seconds, which took the focus of the keyboard out of a table and made tooltips flicker.

## [3.4.0] - 2026-11-17

### Added

- **System > Updates**, as in Sonarr and Radarr: what changed in every version up to the one that runs, with the installed version marked. It reads the list of changes that comes with the image; nothing is fetched from elsewhere.
- **Details** in the History and on the Blocklist: the small "i" at the end of a row opens a window with the release, the game, the indexer, the protocol, the score, the download client and the message.
- **Remove Selected** in the Queue and on the Blocklist, with a tick box per row and one for all of them; the Blocklist has **Clear** too, which asks before it takes everything off.
- **Uptime** on the Status page.

### Changed

- **The other lists follow Sonarr and Radarr too**, as Games and Wanted already did. The Queue, the History and the Events start a row with a small drawing for its state instead of a label; the Queue shows the protocol as a coloured label and the progress as a bar.
- **Long lists come a page at a time** (50 rows), with the buttons to leaf through them under the table next to the total number of records. That is the History, the Events, the Queue and the Blocklist.
- **System > Status**: Health and Services show a drawing per line, and About is a list with the names on the left.
- **System > Backup** starts a row with a drawing for scheduled or made by hand.

## [3.3.0] - 2026-11-17

### Changed

- **Wanted is a table now, as Wanted > Missing in Sonarr and Radarr.** One row per game with a tick box, what it misses, the best release that was found, its score, a status label and when it was last searched, and three small buttons: Automatic Search, Interactive Search and Download. The toolbar has **Search All**, **Search Selected**, **Download Selected**, **Ignore Selected** and **Download All**; under the table stands the total number of records.
- **Wanted has two pages in the menu:** **Missing** (everything) and **Awaiting Choice** (only the games with a release to decide on). The tiles on top made way for the **Filter** menu of the toolbar: All, Update Missing, DLC Missing, Awaiting Choice, In Queue, Ignored.
- **Interactive Search.** The name of a game, on Wanted, Games and in the Queue, opens a window with everything that was found for it: per missing update or DLC the releases with score, indexer, size and age, and a button to download or reject each. What was ruled out and what is on the blocklist is there too.
- **Sort and Filter are menus** on the right of the toolbar, with a drawing and a name like the other buttons, instead of select boxes.
- **Games** has **Update All**, **RSS Sync** and **Search All** in its toolbar, the name of a game as a link, a status label in one colour (Complete, Update Missing, DLC Missing) and the two search buttons at the end of a row.
- **System > Tasks** has no toolbar any more and a second list, **Queue**: the last twenty tasks that ran, with when they started and ended and how long they took. The button to run a task is a small drawing at the end of its row.
- **Lists use the whole width** of the window, with the total number of records under them. The buttons in the rows of the Queue, the Blocklist and the backups are small drawings; the name of a backup downloads it.
- The **account** is behind the drawing in the bar on top, with Log out. What NSWHunter is doing and when the next round starts is at the foot of the menu.

### Fixed

- On the Blocklist the line under the name of a game ("Update", "DLC: ...") was missing on all but one of its rows.

## [3.2.0] - 2026-11-17

### Added

- **Pictures on the Games page.** Every row starts with the small picture of the game, as Switch-library-manager-web has it. NSWHunter fetches a picture once, keeps it in `/data/covers` and hands it to the panel itself, so your browser loads nothing from elsewhere. A game the library has no picture of gets a grey square.
- **System > Tasks**, as in Sonarr and Radarr: what runs by itself (Check Health, Library Sync, Rss Sync, Search Missing, Refresh Monitored Downloads, Refresh Version List, Backup), how often, when it last ran, how long that took and when it runs next. Every task has a button to run it now.

### Changed

- **A log file per day**, named `nswhunter_2026-03-25.txt`. The setting for the size of a log file made way for **Log Retention**: how many days of log files are kept (7, 14, 30 or 90; default 14). Log files of the old kind are removed once they are older than that.
- The README is shorter again.

## [3.1.1] - 2026-11-17

### Changed

- **Nothing in the repository names an account or a server any more.** `docker-compose.yml` has placeholders for the two folders (`/path/to/nswhunter/data` and `/path/to/nswhunter/backup`), the build names the image after the repository it runs in, and `commit-git.sh` pushes to the remote of its folder.
- **The defaults are the usual ones:** `PUID` and `PGID` 1000 and `TZ` `Etc/UTC`. A stack that sets them itself, as the compose file always did, notices nothing.
- The README is a good deal shorter.

## [3.1.0] - 2026-11-17

### Changed

- **The panel now really looks and works like Sonarr and Radarr.** A bar on top with a search box that finds a game from any page; the menu on the left with drawings, numbers for what waits, and groups that open (Activity, Settings, System); a toolbar per page; lists as tables; settings with the name on the left and the field on the right.
- **Settings** opens on an overview of its pages. The pages with single settings have **Save Changes** in the toolbar, which lights up when something was changed.
- **Adding** an indexer, a download client or a connection opens a window with what can be added, grouped under Usenet and Torrents. The window to change one has Delete on the left and Test, Cancel and Save on the right.
- The **Wanted** page lists the games as rows; an opened game shows its releases in columns. Sync Now, Search All and Download All are in the toolbar.
- The backups moved from the General page to **System > Backup**; their settings stay under General. The log is **System > Events**.

### Added

- **Activity > Queue:** what was sent to a download client and is not in the library yet, with the client, the indexer and a progress bar.
- **Activity > History:** what was sent, what arrived and what failed. It starts empty: earlier versions did not keep it.
- **Activity > Blocklist:** the releases you rejected and the downloads that failed, in one list, with Remove and Try again.
- **Notification triggers** per connection, as in Sonarr and Radarr: On Grab, On Arrival, On Download Failure, On Manual Interaction Required and On Health Issue. All are on until you switch one off.
- **Search All** searches every game that misses something by name now, not only the ones whose turn it is.
- **Test All** on the pages with cards and on the Status page.
- **System > Log Files:** the log files, to download.
- **System > Status** starts with Health: what does not work, or that nothing is wrong.

## [3.0.0] - 2026-11-17

Version 3 because the panel has a new layout and the settings a new shape. Your settings are taken over at the first start: the one Prowlarr, the download client and Telegram become the first entries of the new lists. Take the new [docker-compose.yml](docker-compose.yml) over in your stack: it has a second volume, `/backup`.

### Added

- **A layout like Sonarr and Radarr:** a menu on the left with Games, Wanted, Settings (Media Management, Indexers, Download Clients, Connect, General, UI) and System (Status, Log).
- **Games:** every game of your library with the version you have, the latest, the DLC and the size. It can be filtered, searched and sorted; a game that misses something leads to its card on the Wanted page.
- **Wanted** is what the Updates tab was.
- **Indexers:** next to Prowlarr, a Newznab (usenet) or Torznab (torrent) indexer can be added and is then asked directly. Several indexers are asked at once; one that does not answer does not cost the releases of the others.
- **Download clients:** qBittorrent, Transmission and uTorrent, next to NZBGet, SABnzbd and the download client of Prowlarr. Several can be added; a usenet release goes to the first usenet client that is switched on, a torrent to the first torrent client.
- **Torrents.** With a torrent client switched on, torrents are searched too, shown with their seeders, sent as a torrent file or a magnet link, and followed like a usenet download. Without a torrent client nothing changes.
- **Connect:** the library (Switch-library-manager-web) and the notifications: Telegram, Discord (a webhook) and Apprise. Several can be added; each gets every message.
- **General > Logging:** the log level (info, debug, trace) and the size of a log file. The log is now also written to `/data/logs`.
- **General > Backups:** a backup of the settings and the state every 7 days in `/backup`, removed after 28 days; both can be set. The page lists the backups, with Backup now, Download, Restore and Delete.
- **UI:** light or dark, the format of dates and times, and relative dates on or off. Kept on the server, so every browser shows the same.
- **System > Status:** what every service last answered. Indexers, download clients and connections are cards that say so too, and every one has a Test button.

### Changed

- **The first login.** The first start makes the user `admin` with a password it makes up and writes both to the log of the container, at every start until you have changed it. With that password the panel only lets you choose a password of your own (and another username if you want). The screen that asked to make a login is gone. A login you already have stays as it is.
- A download client that does not answer is no longer concluded from: its downloads are left as they are instead of counting as not arrived after the waiting time.
- The value `ja` for yes in an environment variable is no longer read; use `true`.
- The first tile on the Wanted page counts the games that miss something. The number of games in the library is on the Games page.

### Removed

- The environment variables for the one Prowlarr, download client and Telegram are only read at the very first start, to make the first entries. After that the lists in the panel count.
- `NOTIFY_URLS`: Apprise is a connection on the Connect page now. A value that is set becomes that connection at the first start.

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
- Runs as `PUID`:`PGID`; `/data` gets that owner at start.
- Image on the GitHub Container Registry for amd64 and arm64: `latest` on every push, `X.Y.Z` and `X.Y` on a release.
