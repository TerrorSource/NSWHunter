# Changelog

All changes per version. The version number is in `app/version.py`; each version has a section here and a release on GitHub.

## [3.20.0] - 2026-11-22

### Added

- **Wanted > Wishlist**: the games that are not in your library yet, each with when it was added, its status, the best release and its score. **Add Game** is in its toolbar, **Remove** in every row.

### Changed

- **Missing** only shows the games of your library; the games of Add Game are on the Wishlist now, and the filter New Games is gone. While a release of one awaits your choice it is on **Awaiting Choice** too.

## [3.19.0] - 2026-11-22

### Added

- **Add Game**, in the toolbar of the Games page: look for a game that is not in your library yet. Search by name: NSWHunter searches your indexers and shows the games of the releases by the title ID in their names; or fill in the title ID yourself. The game is on Wanted (filter **New Games**) and is searched like the others. The game itself and a bundle with its update or DLC are wanted; an update or DLC alone is ruled out, and so is anything for the Switch 2. Importing gives it a folder of its own by the Folder Name Template. When the library has it, it leaves the list and its updates and DLC are looked for as usual. **Remove** on the page of the game stops looking for it.
- **The name NSWHunter at the top** leads to the Games page.

## [3.18.0] - 2026-11-21

### Added

- **Rescan Folder** in the toolbar of the page of a game: switch-library-manager-web scans its folders, NSWHunter waits until that is done (at most 15 minutes) and reads the game anew. For files you put in the folder of a game yourself. It needs an API key with the Editor role.

## [3.17.4] - 2026-11-21

### Changed

- **A download that cannot be fetched says which indexer and why**, in plain words instead of the raw answer: for example "Fetching the NZB from NZBgeek through Prowlarr: HTTP 429, Indexer is disabled till 11/21/2026 11:03:31 due to recent failures." Error answers of every service are shortened the same way: the description of a Newznab error or the message of a JSON error, and no HTML.

## [3.17.3] - 2026-11-21

### Fixed

- **A connection whose Test works is no longer shown as failing.** The Test button of a saved indexer, download client or connection now puts its card and the warning on every page right; before, a connection stayed red until its next message.
- **Telegram tries once more** when it cannot connect, after 3 seconds, and the error says what went wrong: no answer in time, or which kind of connection error.

## [3.17.2] - 2026-11-20

### Security

- **The login only changes under Settings > Security**, with the current password. The window for choosing a password of your own at the first start no longer answers once that is done.
- **Wrong logins that arrive together are all counted**: the wait after 5 wrong logins can no longer be skipped by sending many logins at once.
- **Wrong logins are counted per IPv6 network (/64)** instead of per single address, and a full list of addresses no longer frees the ones that have to wait.
- **A download link into your own network is only followed to an indexer of the settings**, so a hostile indexer cannot make NSWHunter call other services of your network.
- **`state.json` is only readable by its owner** (mode 0600): its download links hold the API key of Prowlarr.

## [3.17.1] - 2026-11-20

### Changed

- **Adding SABnzbd** shows which setting to change in SABnzbd itself: add `nsp, nsz, xci, xcz` to Config > Special > ext_rename_ignore, or its option Deobfuscate final filenames renames the Switch files.

## [3.17.0] - 2026-11-20

### Changed

- **Defaults for a working setup**, so a new installation needs fewer settings: Missing DLC on, Wait for the Library 30 minutes, Import Completed Downloads on, Remove Completed on, Delete Empty Folders in Download Folder on. The rest stays as it was: Automatic Download off, Hide Failed Downloads on, Folder Name Template `{TITLE_NAME} [{TITLE_ID}]`, Automatic Search every 24 hours, Log Level Info, Log Retention 14 days, backups in `/config/backups`, theme, dates and times as the system and the browser do, relative dates on.
- A setting that was saved in the panel or set as an environment variable keeps its value: only what was never set gets the new default. With importing on and no root folder yet, System > Status says to add one.

## [3.16.0] - 2026-11-20

### Changed

- **Settings > UI is laid out as in Prowlarr**: Dates first (Short Date Format, Long Date Format, Time Format, Show Relative Dates), then Style (Theme, Enable Color-Impaired Mode).

### Added

- **Long Date Format**: "Tuesday, 25 March, 2026", "Tuesday, March 25, 2026" or as the browser does. Used for the date in the Details window of History and Blocklist. As an environment variable: `UI_LONG_DATE_FORMAT`.
- **Enable Color-Impaired Mode**: blue and orange instead of green and red, in light and dark. As an environment variable: `UI_COLOR_IMPAIRED`.

## [3.15.0] - 2026-11-18

### Added

- **Already Tried in the Filter menu of Wanted**: only the games of which every release was sent before.
- **Forget that a release was sent**: a button next to the label "sent" in Interactive Search. The release is a choice to make again, and its game is back on Awaiting Choice. Not for the release that is in the queue.
- **Disk Space on System > Status**: the free and the total space of the disks the config folder, the root folders and the finished downloads of each download client are on. Folders on one disk are one row. Under Health there is a warning when less than 5 GB is free where the library or the downloads are, or less than 100 MB where only the settings are.
- **Size and Time Left in the Queue**: the size of a download and how long it still takes at the speed of the moment, as the download client says. NZBGet, SABnzbd, qBittorrent, Transmission and uTorrent; a download that is paused or waits its turn has no time left to show.

### Fixed

- Manual Import works for every game of the library. For a game that misses nothing it said that the game was not in the library.

## [3.14.0] - 2026-11-17

### Added

- **Manual Import**: on the page of a game, and in the Queue for a download that could not be put in the library. Choose a folder or a file in the File Browser; a window shows which Switch files would be moved to the folder of the game, and Import moves them. A file with the title ID of another game in its name is left where it is, and so is the game itself. For a download of the Queue, that download then counts as put in the library. Nothing is taken out of a root folder.
- **A DLC unlocker is a kind of its own.** A release named "DLC Unlocker" is a small file that opens DLC, and a library may go on missing the DLC itself. It is listed with the DLC packs as "DLC unlocker", scores 3 instead of 5, and is never sent by automatic download or Download All: only with a click on that release.
- **An imported download the library never recognises leaves the queue.** If the files were put in the folder of the game, the library scanned on request after that, and it still misses the update or DLC when the waiting time (Wait for the Library) is over, the download goes to History as **Not Recognised** and you are told once. Its files stay where they are and the release is not rejected, but it counts as tried, so the next release gets its turn. With a library that refuses to scan on request nothing changes: such a download stays in the queue as "not seen in your library".
- The task **Rescan Download Folder** also removes the empty folders that earlier downloads left where a download client keeps its finished downloads, if Delete Empty Folders in Download Folder is on. Only a folder without a single file in it, and not one that changed in the last ten minutes.

## [3.13.1] - 2026-11-17

### Fixed

- **A game no longer awaits a choice when every release it has was sent before.** A release that was sent and then left the queue without arriving (taken out of the queue, or downloaded but never seen in the library) stayed a choice, so the game stood on Awaiting Choice while Interactive Search showed "sent" on everything. Such a game now says **Already Tried**; it is back on Awaiting Choice as soon as a release is found that was never sent.

### Changed

- With releases that were sent and releases that were not, the best one that was never sent is the one a download button, Download All, automatic download and the question in Telegram are about. Nothing is sent a second time without a click on that release in Interactive Search. Interactive Search lists what was never sent first.
- A release that is taken off the blocklist is offered again, also if it was sent before.
- **Authenticator App** (Settings > General) is right under Current Password, above Enable HTTPS, and no longer in a section of its own under the page.

## [3.13.0] - 2026-11-17

### Added

- **Delete Empty Folders in Download Folder** (Settings > Media Management > Importing, off by default): after the files of a download were moved to the library, the folder it came from is looked at and removed if nothing is left in it, with the empty folders inside it. A folder that still holds a file stays as it is, so nothing is lost. The folder all downloads are in, a root folder and a volume are never removed, and neither is the folder of a torrent, whose files stay to go on seeding. As an environment variable: `DELETE_EMPTY_FOLDERS`.

## [3.12.0] - 2026-11-17

### Added

- **The task Rescan Download Folder** (System > Tasks): asks the download clients once more and looks again in the folder of every finished download that is not in the folder of its game yet. For after something was put right by hand, such as a download that came out packed and was unpacked. What still cannot be imported is said again in the Events. It also runs by itself with Refresh Monitored Downloads, while a finished download waits.

## [3.11.2] - 2026-11-17

### Changed

- **An import that finds no Switch files says what the folder holds**: "it holds 14 file(s): 12 .r00-.r99, 1 .nfo, 1 .rar. The download is still packed", or that the folder is empty. Before it only asked whether the download was still packed.
- **A finished download that its client no longer lists is still found**, if it was taken out of the history of the download client: NSWHunter looks for a folder named after the release where the other finished downloads of that client are. If there is none, the message says that the client no longer has the download in its list.

## [3.11.1] - 2026-11-17

### Changed

- **The default backup folder is `/config/backups`**, and the General page shows it as such. An installation that has a volume at `/backup` keeps using that one.

## [3.11.0] - 2026-11-17

### Changed

- **The settings are in `/config`, as with Sonarr and Radarr, so `/data` is free for the folder of your media.** `docker-compose.yml` mounts one folder, at `/config`. With your media at `/data`, as your other containers have it, the paths of your download client and your library are the same here and nothing has to be translated.
- **An existing installation keeps working.** If the settings are found in `/data`, they are used from there, and the log says how to move: mount the same folder at `/config` instead of `/data`. Nothing has to be copied.
- **Backups are kept in the folder `backups` of the config folder**, unless `/backup` is a volume of the container: then they go there, as before. The image no longer makes volumes of its own that are gone with the container.
- **The start of the container never touches `/data` when that is your media**: it only changes the owner of the config folder and of NSWHunter's own files in it. If nothing is mounted at `/config`, the container says so and stops, instead of writing somewhere else.

## [3.10.3] - 2026-11-17

### Fixed

- **A library that is a volume somewhere under `/data` can be a root folder.** Many setups have everything under `/data` (`/data/media/...`, `/data/usenet/...`), and with the same paths in every container nothing has to be translated. It was refused with "it is not where your games are". Only the folders NSWHunter keeps its own files in are still refused: `/data` itself, and its logs, covers, certificates and backups.
- **The start of the container no longer changes the owner of everything under `/data`.** When it starts as root and `/data` belongs to another user, it now changes the owner of `/data` itself and of NSWHunter's own files in it, by name. A library or a download folder mounted inside `/data` keeps its owner.

### Changed

- Fields for paths and search terms ask password managers to leave them alone: they are no part of a login.

## [3.10.2] - 2026-11-17

### Security

- **The login only changes with the current password.** Settings > General has a field **Current Password**; without it the username and the password stay as they are, whatever is in their fields. Before, saving that page for something else (the backup folder, say) also saved the username and password fields as they stood, so a password manager that had filled them in changed the login without a word. When the login does change, the panel says so and the Events page records it.
- The fields for API keys and the backup password ask password managers to leave them alone.

### Added

- **Resetting a lost password without editing a file by hand.** Put an empty file named `reset-password` in the data folder and restart the container: NSWHunter makes up a new password, writes it to the log of the container, switches two-step login off and logs everyone out. The username and every other setting stay.

### Fixed

- **A damaged settings file is never written over.** If `settings.json` cannot be read, NSWHunter no longer starts with empty settings and saves those over it, which lost every key and password. It stops, says why in the log, and leaves the file as it is.

## [3.10.1] - 2026-11-17

### Changed

- The File Browser has a narrow Type column, and the table of root folders leaves out the path the library has for a folder while a Folder Name Template is set, where it plays no part.

## [3.10.0] - 2026-11-17

### Added

- **File Browser**, as in Sonarr and Radarr: a window that lists the folders of the container, to click through instead of typing a path. A click on a folder opens it, ".." goes to the folder above, and typing in the box narrows the list to what starts like it. **Add Root Folder** opens it, and Ok adds the folder. The Local Path of a download client, the backup folder and the two certificate paths have a button for it next to their field.

## [3.9.0] - 2026-11-17

### Added

- **Folder Name Template** (Settings > Media Management > Importing), default `{TITLE_NAME} [{TITLE_ID}]`: the folder of a game in the root folder, written as Organize of Switch-library-manager-web writes it. A finished download goes in that folder, for example `Some Game [0100ABCD0000A000]`. The name is cleaned the way Switch-library-manager-web cleans it.

### Changed

- **Importing puts everything of a game in its folder by the template**, instead of next to the files the game already has. A folder in the root folder that already has the title ID of the game in its name is used as it is, whatever name is around it; a new folder is only made when there is none. With the template emptied the old way is back: next to the updates or DLC the game has, as the library names its folders.
- With a template the "Path in Switch-library-manager-web" of a root folder is not needed: where the library says its files are is not used.

## [3.8.1] - 2026-11-17

### Changed

- The example path of a root folder in the panel is a neutral one.

## [3.8.0] - 2026-11-17

### Added

- **Importing: a finished download is put in the folder of its game**, as Completed Download Handling does in Sonarr and Radarr. Off until you switch it on (Settings > Media Management > Import Completed Downloads).
  - **Root Folders** (Settings > Media Management): where your library is, as a volume of the container, with its free space. If Switch-library-manager-web has the same folder under another path, the root folder says which.
  - The download client says where a finished download is (NZBGet, SABnzbd, qBittorrent, Transmission, uTorrent). The Switch files in it (NSP, NSZ, XCI, XCZ) go **next to the updates or DLC the game already has, or else next to the game itself**. They keep their names.
  - A usenet download is moved. A torrent is linked, or copied if that cannot be done, so it goes on seeding.
  - Nothing is overwritten, and nothing is written outside a root folder. The game itself, from a bundle, is left in the download: the library has it already.
  - A download client can have a **Remote Path** and a **Local Path**, for when this container has the download folder under another path than the client names.
  - If it cannot be done, the Queue says why ("Downloaded, import failed"), with a button to try again; it is also tried again by itself. You get a notification (On Download Failure) once.
  - **Remove Completed** (optional): after a usenet download was put in the library, it is taken out of the download client too.
  - The History has a line **Imported** with where the files went.

### Changed

- The download folder and the library have to be volumes of the container for this; without the setting NSWHunter still touches no files of your games.

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
