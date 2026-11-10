# MediaForge

A Windows app for converting, joining and downloading video and audio, built on **ffmpeg** and **yt-dlp**
with Python + PySide6.

## Install

Download **`MediaForge_setup_vX.Y.Z.exe`** from the [latest release](https://github.com/Farizma/MediaForge/releases/latest)
and run it. The setup wizard installs MediaForge for your account (no administrator rights needed), adds it to the
Start menu and, if you like, the desktop, and registers an uninstaller. ffmpeg is included, and MediaForge keeps
itself up to date (see [Updates](#updates-mediaforge-ffmpeg-and-yt-dlp)).

The installer isn't code-signed yet, so Windows may say "Windows protected your PC": choose *More info > Run anyway*.

## Run from source

**Easiest:** double-click **`Start_MediaForge.pyw`**. It checks that everything MediaForge needs is
present and, if something is missing, *asks you first* and then installs it:

- a private Python environment (`.venv` next to the file) with PySide6 and yt-dlp
- ffmpeg + ffprobe (Windows: downloaded for you; macOS/Linux: it tells you the package-manager command)

then it starts the program. You only need Python 3.10+ installed. (From a terminal:
`python Start_MediaForge.pyw --check` just reports what's missing; `--yes` skips the question; `--console` avoids pop-ups.)

Manual route:

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

MediaForge finds ffmpeg/ffprobe in this order: the path set in **Settings**, a copy it downloaded
itself, a `./bin` folder next to the app, then your `PATH`. Requires Python 3.10+.

## Tests

```bash
pip install pytest
python -m pytest tests          # headless machine: set QT_QPA_PLATFORM=offscreen first
```

## Layout

```
main.py                         entry point
Start_MediaForge.pyw            launcher: checks / installs requirements, then starts main.py
mediaforge/core/                no GUI code here (easy to test / reuse)
    ffmpeg_builder.py           options -> ffmpeg command, presets, sanity warnings
    join_builder.py             N clips -> one filter_complex join (normalises size/fps/audio)
    ytdlp_builder.py            options -> yt-dlp CLI args; format-table / info parsing
    ytdlp_runner.py             YtDlpJob + info fetch (yt-dlp as a library, in daemon threads)
    jobs.py                     Job base class, FFmpegJob (QProcess), JobManager queue
    queue_store.py, procctl.py  queue saved across restarts; suspend / resume a running ffmpeg
    presets.py                  built-in and saved presets, import / export
    updater.py                  download + checksum-verify ffmpeg, yt-dlp and MediaForge releases (stdlib only)
    update_service.py           runs update checks / installs in the background for the UI
    probe.py                    ffprobe wrapper
    binaries.py                 find ffmpeg/ffprobe, detect available encoders
    settings.py, util.py, fmt_helpers.py
mediaforge/ui/
    kit/                        design system: theme + colourways, springs, icons, controls, layout, sheets, toasts
    form.py                     one declarative field list per options dataclass
    pages/                      convert, join, download, queue, log (tool.py: shared base of convert / join)
    main_window.py              sidebar + pages, toasts, start-up checks, self-update
    sheets.py, sidebar.py, preset_bar.py   Settings / Updates sheets, navigation, presets
assets/                         icon, bundled fonts (assets/fonts, SIL OFL)
packaging/                      PyInstaller spec, Inno Setup script
tools/                          build_exe.py (the Windows build), make_icon.py (draws the logo)
release-notes/                  vX.Y.Z.md, used as the GitHub release text
tests/                          pytest suite (builders, updater, presets, queue, UI logic, build script)
```

## The interface

A Windows-native take on the macOS / iOS look, built from one small design system in `mediaforge/ui/kit/`.

- **Layout** - a sidebar (Convert, Join, Download | Queue, Log; Updates and Settings at the bottom) beside the content.
  Narrow windows collapse the sidebar to icons and stack two-column screens. Shortcuts: `Ctrl+1`..`Ctrl+5` pages,
  `Ctrl+,` Settings, `Ctrl+U` Updates, `Ctrl+Q` quit. Messages appear as toasts at the bottom instead of a status bar.
- **Look** - dark colourways on near-black (Midnight Obsidian by default; pick another in
  *Settings > Appearance*, it previews live), white-tint glass buttons and cards with hairline edges, a white primary
  button, a soft glow from the top of the page in the highlight colour, colour icon tiles in the sidebar, and mono
  upper-case section labels. Fonts are bundled (Plus Jakarta Sans and JetBrains Mono, both SIL OFL, in `assets/fonts`).
  A 4-pt spacing grid, 44-px hit targets, text roles that follow Windows' *Settings > Accessibility > Text size*,
  and a title bar coloured to match the sidebar on Windows 11.
- **Motion** - springs, not fixed-duration transitions: buttons scale to 0.97 the moment you press, toggles and the
  segmented control's white pill slide on interruptible springs, the sidebar's selection pill glides between pages,
  progress bars ease toward their value, sheets rise in over a dark wash and toasts rise in. Keyboard-driven changes never animate, and Windows'
  *Animation effects* off setting (reduced motion) makes everything snap.
- **Feedback** - Windows desktop apps have no haptics, so *Settings > Feedback* offers an optional, very quiet system sound
  when jobs finish or fail (off by default).
- **Code shape** - every option screen is a `Form`: one list of fields per options dataclass drives the widgets, change
  tracking, collecting and presets. The Convert and Join screens share one base class.

## Updates (MediaForge, ffmpeg and yt-dlp)

**MediaForge itself** checks [GitHub releases](https://github.com/Farizma/MediaForge/releases) (at start-up, at most
once a day, and from *Updates*). When a newer version exists a toast offers **Update**: it downloads
`MediaForge_setup_v<version>.exe`, checks it against the release's `.sha256` (no checksum, no install), asks, then
closes MediaForge and opens the setup wizard, which upgrades in place. It never installs without asking, even with
*Install updates automatically* on. Running from source, Update opens the release page instead.

**Updates** in the sidebar (`Ctrl+U`) shows the installed and latest version of MediaForge, ffmpeg and yt-dlp and
installs newer ones.

- *Check when MediaForge starts* (on by default, at most once a day) and *Install updates automatically*
  (off by default; it only updates ffmpeg and yt-dlp, and only if they are already installed).
- Tool updates are downloaded into your data folder (sidebar *More* (...) > *Open Data Folder*), never into the
  program folder, and are **checksum-verified**; if no checksum can be fetched, nothing is installed.
- Each update goes into its own versioned folder, so a conversion that is running keeps using the ffmpeg it
  started with. New jobs use the new ffmpeg straight away. A new yt-dlp is used after restarting MediaForge.
- This works from source **and** inside the built `.exe` (yt-dlp's official single-file release is put in front of
  the bundled copy). ffmpeg downloads are Windows-only (gyan.dev "essentials" build); on macOS/Linux use brew/apt.
- If ffmpeg is missing, the app offers to download it on first start. yt-dlp comes with MediaForge; if it is
  missing (running from source), the Download page offers *Install yt-dlp*.

## Pause, retry and presets

- **Pause / Resume** - select a job in the queue. A paused conversion is frozen in place (the
  ffmpeg process is suspended) and carries on exactly where it stopped. A paused download stops
  cleanly and keeps its partial file; Resume continues from it. Paused jobs don't hold a queue slot.
- **Retry** - *Retry* restarts the selected failed/cancelled job, *Retry failed* restarts them all.
  *Retry failed* is in the queue's *More* (...) menu, along with *Pause all*, *Resume all* and *Clear finished*.
  *Settings > Jobs > Retry failed jobs automatically* re-runs failed jobs by themselves (0-5 times).
- **Queue survives restarts** - on quit you can keep unfinished jobs; they return *paused* next
  launch (a conversion that was mid-run restarts from the beginning, downloads continue).
- **Presets** - the preset box on the Convert and Download pages has built-in presets and yours
  (marked with a star). *Save as...* stores the current settings; *...* imports/exports a JSON file
  to share. Imported yt-dlp presets that use options able to run programs (`--exec` etc.) are refused.
- Everything MediaForge saves (presets, queue, log, downloaded tools) lives in the data folder: sidebar
  *More* (...) > **Open Data Folder** (`%APPDATA%\MediaForge\MediaForge` on Windows).

## yt-dlp notes

- yt-dlp is used as a **Python library** (installed by `requirements.txt`, bundled in the installer). The Download
  page builds the same command-line arguments you would type, shows them in the command preview, and hands them
  to `yt_dlp.parse_options()`. So anything the CLI accepts works in *Output > Extra yt-dlp arguments*.
- ffmpeg is needed for merging video + audio, audio conversion and embedding; MediaForge passes
  its location to yt-dlp automatically.
- Sites change often, so keep yt-dlp fresh: the Download page's *Update yt-dlp* button (or *Updates* in the sidebar)
  downloads the official release.
- Only use it for content you have the right to download.

## How it fits together

Everything that runs is a `Job`. The Convert and Join pages build an ffmpeg command and hand an
`FFmpegJob` to the `JobManager`; the Download page hands it a `YtDlpJob`. The Queue page just
displays whatever jobs the manager holds.

## Roadmap

- [x] Core, job queue, settings
- [x] FFmpeg tab (batch convert, presets, trim, resize, audio extract, GIF, extra args)
- [x] Join tab (reorder, silent audio for clips without audio, match size/fps/audio, loudness option)
- [ ] Lossless join (stream copy) for identical clips
- [x] yt-dlp tab (fetch formats, pick one or set quality limits, audio extraction, playlists,
      subtitles, thumbnails/metadata, SponsorBlock, cookies, rate limit, in-app install/update)
- [x] Pause / resume (conversions freeze in place; downloads continue from the partial file)
- [x] Retry failed jobs (one, all, or automatically N times) and a queue that survives restarts
- [x] Saved presets for ffmpeg and yt-dlp (save, delete, import / export)
- [x] Windows packaging (PyInstaller folder/one-file build, zip, Inno Setup installer, CI workflow)
- [x] 1.0: setup wizard on GitHub releases, self-updates from GitHub, dark colourways, new logo
- [ ] Drag-reorder queue, editable raw-command mode, presets for the Join tab
- [ ] macOS / Linux packaging

## Building the Windows .exe (one click)

Double-click **`BUILD_EXE.bat`**. That's it. It:

1. finds Python 3.10+ - and if there is none, *asks* before installing Python 3.12 with winget
2. creates its own build environment (`.venv-build`) and installs the dependencies + PyInstaller
3. downloads ffmpeg into `bin\` (so the finished program has it)
4. builds with PyInstaller and zips the result

Result: `dist\MediaForge\MediaForge.exe` and `dist\MediaForge-<version>-win64.zip`
(the folder opens automatically). No administrator rights are needed.

Options (add them after the file name in a terminal): `--installer` also builds the setup wizard
(needs [Inno Setup 6](https://jrsoftware.org/isinfo.php); `BUILD_INSTALLER.bat` below does this for you), `--onefile` makes one single .exe
(slower to start), `--no-ffmpeg` skips bundling ffmpeg, `--clean` starts from scratch, `--check` only
verifies the prerequisites. `BUILD_EXE.bat` has to stay in the project folder (it uses `tools\build_exe.py`).

**The setup wizard (one click):** double-click **`BUILD_INSTALLER.bat`**. It finds Inno Setup 6 (and, if it's
missing, *asks* before installing it with winget), then runs the build above with `--installer`. Result:
`dist\MediaForge_setup_v<version>.exe` - a normal Windows setup wizard that installs for the current user
(no administrator rights), adds Start-menu and optional desktop shortcuts, and an uninstaller - plus
`dist\MediaForge_setup_v<version>.exe.sha256`.

**Releases:** bump `__version__` in `mediaforge/__init__.py`, add `release-notes/v<version>.md`, then on GitHub
choose *Releases > Draft a new release*, type the tag (`v1.0.1`), and Publish (or push the tag:
`git tag v1.0.1 && git push origin v1.0.1`). `.github/workflows/release.yml` runs the tests, builds the setup wizard
on a Windows runner and attaches the installer, its `.sha256` and the zip to the release (creating it if you pushed
a tag). The tag must match `__version__`. *Actions > Release > Run workflow* builds the same files as a downloadable
artifact without publishing, and it rebuilds every Monday so the bundled tools stay fresh.

Good to know:
- **ffmpeg licence** - the bundled "essentials" build is GPL v3. If you redistribute the zip/installer,
  keep `bin\FFMPEG-LICENSE.txt` with it (see ffmpeg.org/legal.html), or build with `--no-ffmpeg`
  (the app then offers to download ffmpeg on first start).
- **SmartScreen / antivirus** - an unsigned PyInstaller app often triggers "Windows protected your PC" or a
  false positive. Choose *More info > Run anyway*, or sign the exe with a code-signing certificate.
- Errors are written to `mediaforge.log` in the data folder (sidebar *More* (...) > *Open Data Folder*).

## License

MediaForge is [MIT licensed](LICENSE). The bundled fonts are SIL OFL 1.1 (licences in `assets/fonts`), and the
ffmpeg build in the installer is GPL v3 (`bin\FFMPEG-LICENSE.txt`).
