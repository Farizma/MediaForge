import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from mediaforge.core import updater
from mediaforge.core.settings import Settings
from mediaforge.core.util import resource_path
from mediaforge.ui.kit import theme
from mediaforge.ui.main_window import MainWindow


def setup_logging(folder: Path) -> Path:
    """A windowed .exe has no console (sys.stderr is None), so send errors to a log file."""
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / "mediaforge.log"
    try:
        if log.exists() and log.stat().st_size > 1_000_000:
            log.write_text("", encoding="utf-8")        # keep it from growing forever
        stream = open(log, "a", encoding="utf-8", buffering=1)
    except OSError:
        return log
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream

    shown = {"dialog": False}

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        stream.write(text + "\n")
        if not shown["dialog"] and QApplication.instance() is not None:
            shown["dialog"] = True                      # once per session, not a flood
            QMessageBox.critical(None, "Unexpected error",
                                 f"MediaForge hit an unexpected error and will try to carry on.\n\n"
                                 f"Details were saved to:\n{log}\n\n{exc_type.__name__}: {exc}")

    sys.excepthook = hook
    return log


def main() -> int:
    data_dir = updater.default_data_dir()
    try:
        # Must happen before anything imports yt_dlp: puts a downloaded, newer yt-dlp first.
        updater.activate_ytdlp(data_dir)
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("MediaForge")
    app.setOrganizationName("MediaForge")
    app.setStyle("Fusion")
    settings = Settings()
    theme.install(app, settings.colourway)              # bundled fonts, the saved colourway (dark only), live restyle
    setup_logging(data_dir)
    threading.Thread(target=lambda: (updater.cleanup_old(data_dir), updater.cleanup_app_update(data_dir)),
                     daemon=True).start()
    icon = resource_path("assets/icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow(settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
