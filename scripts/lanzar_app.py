"""Inicia Streamlit sin consola y abre el navegador cuando esté listo."""

import ctypes
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    process = None
    try:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", 8501))
            except OSError:
                sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        url = f"http://127.0.0.1:{port}"
        log = root / ".venv" / "lanzador.log"
        with log.open("ab") as output:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    "src/app/ui/streamlit_app.py",
                    "--server.headless",
                    "true",
                    "--server.fileWatcherType",
                    "none",
                    "--browser.gatherUsageStats",
                    "false",
                    "--server.address",
                    "127.0.0.1",
                    "--server.port",
                    str(port),
                ],
                cwd=root,
                stdout=output,
                stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and process.poll() is None:
            try:
                with urlopen(f"{url}/_stcore/health", timeout=1) as response:
                    if response.read().strip() == b"ok" and process.poll() is None:
                        if not webbrowser.open(url):
                            ctypes.windll.user32.MessageBoxW(
                                0, f"Abre {url} en tu navegador.", "Rutas ciclistas", 0
                            )
                        return
            except (URLError, TimeoutError):
                time.sleep(0.25)
        raise RuntimeError(f"Revisa el registro {log} e inténtalo de nuevo.")
    except (OSError, RuntimeError) as exc:
        if process is not None and process.poll() is None:
            process.terminate()
        ctypes.windll.user32.MessageBoxW(
            0, f"No se pudo iniciar Streamlit. {exc}", "Rutas ciclistas", 16
        )


if __name__ == "__main__":
    main()
