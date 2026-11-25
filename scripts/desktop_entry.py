"""Entrada autónoma de Windows para la interfaz local."""

import ctypes
import os
import socket
import sys
import time
import traceback
import webbrowser
from pathlib import Path
from threading import Thread
from urllib.error import URLError
from urllib.request import urlopen


def open_when_ready(url: str) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{url}/_stcore/health", timeout=1) as response:
                ready = response.read().strip() == b"ok"
        except (URLError, TimeoutError):
            time.sleep(0.25)
            continue
        if ready:
            if not webbrowser.open(url):
                show_message(f"Abre {url} en tu navegador.")
            else:
                print(f"Navegador abierto: {url}")
            return
    show_message("El servidor local no respondió. Revisa el registro en RutasCiclistas.")


def show_message(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(0, message, "Rutas Ciclistas", 16)


def run(data_dir: Path) -> None:
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    from streamlit.web import bootstrap

    os.environ.setdefault("APP_CACHE_DIR", str(data_dir / "cache" / "graphs"))
    os.environ.setdefault("APP_GEOCODE_CACHE", str(data_dir / "cache" / "geocode.json"))
    # Folium debe importarse durante la sesión para que Streamlit registre el mapa.
    script = Path(__file__).resolve().parent / "web" / "streamlit_app.py"
    if "--verificar" in sys.argv:
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(script), default_timeout=45).run()
        if app.exception:
            raise RuntimeError(str(app.exception))
        print(app.title[0].value)
        return

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    options = {
        "global.developmentMode": False,
        "server.address": "127.0.0.1",
        "server.port": port,
        "server.headless": True,
        "server.fileWatcherType": "none",
        "browser.gatherUsageStats": False,
    }
    bootstrap.load_config_options(flag_options=options)
    Thread(target=open_when_ready, args=(f"http://127.0.0.1:{port}",), daemon=True).start()
    bootstrap.run(str(script), False, [], options)


def main() -> int:
    data_dir = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "RutasCiclistas"
    log_path = data_dir / "inicio.log"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8", buffering=1) as log:
            sys.stdout = sys.stderr = log
            try:
                run(data_dir)
            except Exception:
                traceback.print_exc()
                raise
    except Exception:
        if "--verificar" not in sys.argv:
            show_message(f"No se pudo abrir la aplicación. Revisa el registro {log_path}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
