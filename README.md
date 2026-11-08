# MediaForge

A desktop GUI for **ffmpeg** and **yt-dlp**, built with Python + PySide6.

## Run it

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

MediaForge finds ffmpeg/ffprobe in this order: the path set in **File > Settings**, a copy it downloaded
itself, a `./bin` folder next to the app, then your `PATH`. Requires Python 3.10+.

## Tests

```bash
pip install pytest
python -m pytest tests
```

## Layout

```
main.py                         entry point
mediaforge/core/                no GUI code here (easy to test / reuse)
    ffmpeg_builder.py           options -> ffmpeg command, presets, sanity warnings
    join_builder.py             N clips -> one filter_complex join (normalises size/fps/audio)
    ytdlp_builder.py            options -> yt-dlp CLI args; format-table / info parsing
    ytdlp_runner.py             YtDlpJob + info fetch (yt-dlp as a library, in daemon threads)
    jobs.py                     Job base class, FFmpegJob (QProcess), JobManager queue
    probe.py                    ffprobe wrapper
    binaries.py                 find ffmpeg/ffprobe, detect available encoders
    settings.py, util.py
mediaforge/ui/
    kit/                        design system: theme, springs, icons, controls, layout, sheets, toasts
    form.py                     one declarative field list per options dataclass
    pages/                      convert, join, download, queue, log
    main_window.py              sidebar + pages
    sheets.py, sidebar.py, preset_bar.py   Settings / Updates sheets, navigation, presets
tests/                          test_builder.py, test_join.py, test_ytdlp.py
```

## The interface

A Windows-native take on the macOS / iOS look, built from one small design system in `mediaforge/ui/kit/`.

- **Layout** - a sidebar (Convert, Join, Download | Queue, Log; Updates and Settings at the bottom) beside the content.
  Narrow windows collapse the sidebar to icons and stack two-column screens. Shortcuts: `Ctrl+1`..`Ctrl+5` pages,
  `Ctrl+,` Settings, `Ctrl+U` Updates, `Ctrl+Q` quit. Messages appear as toasts at the bottom instead of a status bar.
- **Look** - Apple system colors in light and dark (follows Windows live), a 4-pt spacing grid, 44-px hit targets,
  Dynamic-Type-style text roles that follow Windows' *Settings > Accessibility > Text size*, SVG symbols drawn in
  the theme color, and Windows 11 **Mica** behind a translucent sidebar (opaque on Windows 10).
- **Motion** - springs, not fixed-duration transitions: buttons scale to 0.97 the moment you press, toggles and the
  segmented control slide on interruptible springs, the sidebar's selection pill glides between pages, progress bars
  ease toward their value, sheets and toasts rise in. Keyboard-driven changes never animate, and Windows'
  *Animation effects* off setting (reduced motion) makes everything snap.
- **Feedback** - Windows desktop apps have no haptics, so *Settings > Feedback* offers an optional, very quiet system sound
  when jobs finish or fail (off by default).
- **Code shape** - every option screen is a `Form`: one list of fields per options dataclass drives the widgets, change
  tracking, collecting and presets. The Convert and Join screens share one base class.

## Updates (ffmpeg and yt-dlp)

**Help > Check for updates...** shows the installed and latest version of both tools and installs newer ones.

- *Check for updates when MediaForge starts* (on by default, at most once a day) and
  *Install updates automatically* (off by default; it only updates tools that are already installed).
- Updates are downloaded into your data folder (Help > Open data folder), never into the program
  folder, and are **checksum-verified**; if no checksum can be fetched, nothing is installed.
- Each update goes into its own versioned folder, so a conversion that is running keeps using the ffmpeg it
  started with. New jobs use the new ffmpeg straight away. A new yt-dlp is used after restarting MediaForge.
- This works from source **and** inside the built `.exe` (yt-dlp's official single-file release is put in front of
  the bundled copy). ffmpeg downloads are Windows-only (gyan.dev "essentials" build); on macOS/Linux use brew/apt.
- If a yt-dlp or ffmpeg is missing, the app offers to download it on first start.

## Pause, retry and presets

- **Pause / Resume** - select a job in the queue. A paused conversion is frozen in place (the
  ffmpeg process is suspended) and carries on exactly where it stopped. A paused download stops
  cleanly and keeps its partial file; Resume continues from it. Paused jobs don't hold a queue slot.
- **Retry** - *Retry* restarts the selected failed/cancelled job, *Retry failed* restarts them all.
  *File > Settings > Auto-retry* re-runs failed jobs automatically (0-5 times).
- **Queue survives restarts** - on quit you can keep unfinished jobs; they return *paused* next
  launch (a conversion that was mid-run restarts from the beginning, downloads continue).
- **Presets** - the *Preset* box on the FFmpeg and yt-dlp tabs has built-in presets and yours
  (marked with a star). *Save as...* stores the current settings; *...* imports/exports a JSON file
  to share. Imported yt-dlp presets that use options able to run programs (`--exec` etc.) are refused.
- Everything MediaForge saves (presets, queue, log) lives in the folder under **Help > Open data folder**.

## yt-dlp notes

- yt-dlp is used as a **Python library** (installed by `requirements.txt`). The tab builds the
  same command-line arguments you would type, shows them in the command preview, and hands them
  to `yt_dlp.parse_options()`. So anything the CLI accepts works in the *Extra args* box.
- ffmpeg is needed for merging video + audio, audio conversion and embedding; MediaForge passes
  its location to yt-dlp automatically.
- Sites change often, so keep yt-dlp fresh: the tab's *Update yt-dlp* button (or Help > Check for updates) downloads the official release.
- Only use it for content you have the right to download.

## How it fits together

Everything that runs is a `Job`. The ffmpeg tab builds a command and hands an
`FFmpegJob` to the `JobManager`; the queue panel just displays whatever jobs the
manager holds. The yt-dlp tab will add a `YtDlpJob` subclass and reuse the same queue.

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

Options (add them after the file name in a terminal): `--installer` also builds a Setup.exe
(needs [Inno Setup 6](https://jrsoftware.org/isinfo.php)), `--onefile` makes one single .exe
(slower to start), `--no-ffmpeg` skips bundling ffmpeg, `--clean` starts from scratch, `--check` only
verifies the prerequisites. `BUILD_EXE.bat` has to stay in the project folder (it uses `tools\build_exe.py`).

**No Windows machine?** Push the project to GitHub: `.github/workflows/build-windows.yml` runs the tests and builds
the zip + installer on a Windows runner (Actions > *Build Windows* > *Run workflow*, or push a tag like `v0.3.0`
for a Release). It also rebuilds every Monday so the bundled tools stay fresh.

Good to know:
- **ffmpeg licence** - the bundled "essentials" build is GPL v3. If you redistribute the zip/installer,
  keep `bin\FFMPEG-LICENSE.txt` with it (see ffmpeg.org/legal.html), or build with `--no-ffmpeg`
  (the app then offers to download ffmpeg on first start).
- **SmartScreen / antivirus** - an unsigned PyInstaller app often triggers "Windows protected your PC" or a
  false positive. Choose *More info > Run anyway*, or sign the exe with a code-signing certificate.
- Errors in the .exe are written to `mediaforge.log` in the data folder (Help > Open data folder).
