"""Inicia una sola instancia local de Rutas Ciclistas en Windows."""

import asyncio
import ctypes
import msvcrt
import os
import socket
import sys
import time
import traceback
import webbrowser
from contextlib import suppress
from pathlib import Path
from threading import Thread
from urllib.request import ProxyHandler, build_opener

from app.services import desktop_session
from app.services.ui_state import write_json

_STARTUP_GRACE_S = 120
_IDLE_GRACE_S = 60
_EXIT_PAGE_GRACE_S = 3


def show_message(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(0, message, "Rutas Ciclistas", 0)


def open_app(port: int) -> None:
    url = f"http://127.0.0.1:{port}"
    if not webbrowser.open(url):
        show_message(f"Abre {url} en tu navegador.")


def reopen_if_ready(endpoint: Path) -> bool:
    try:
        port = int(endpoint.read_text(encoding="ascii"))
        if not 1 <= port <= 65535:
            return False
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
            if response.read(16).strip() != b"ok":
                return False
    except (OSError, ValueError):
        return False

    open_app(port)
    return True


async def stop_when_idle(server) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _STARTUP_GRACE_S
    while loop.time() < deadline:
        if server.browser_is_connected:
            deadline = loop.time() + _IDLE_GRACE_S
        await asyncio.sleep(1)
    server.stop()


async def serve(script: Path, endpoint: Path, port: int) -> None:
    from streamlit.web.server.server import Server

    server = Server(str(script), is_hello=False)
    loop = asyncio.get_running_loop()
    desktop_session.shutdown = lambda: loop.call_soon_threadsafe(
        loop.call_later, _EXIT_PAGE_GRACE_S, server.stop
    )
    try:
        await server.start()
        write_json(endpoint, port)
        Thread(target=open_app, args=(port,), daemon=True).start()
        idle_monitor = asyncio.create_task(stop_when_idle(server))
        try:
            await server.stopped
        finally:
            idle_monitor.cancel()
            with suppress(asyncio.CancelledError):
                await idle_monitor
    finally:
        desktop_session.shutdown = None


def run(data_dir: Path, endpoint: Path) -> None:
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    from streamlit.web import bootstrap

    os.environ.setdefault("APP_CACHE_DIR", str(data_dir / "cache" / "graphs"))
    os.environ.setdefault("APP_GEOCODE_CACHE", str(data_dir / "cache" / "geocode.json"))
    root = Path(__file__).resolve().parent
    script = (
        root / "web" / "streamlit_app.py"
        if getattr(sys, "frozen", False)
        else root.parent / "src" / "app" / "ui" / "streamlit_app.py"
    )
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
    bootstrap.load_config_options(
        flag_options={
            "global.developmentMode": False,
            "server.address": "127.0.0.1",
            "server.port": port,
            "server.headless": True,
            "server.fileWatcherType": "none",
            "browser.gatherUsageStats": False,
        }
    )
    asyncio.run(serve(script, endpoint, port))


def start_or_reopen(data_dir: Path) -> None:
    endpoint = data_dir / "servidor.json"
    lock_path = data_dir / "servidor.lock"
    deadline = time.monotonic() + 45
    with lock_path.open("a+b") as lock:
        while True:
            try:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                if reopen_if_ready(endpoint):
                    return
                if time.monotonic() >= deadline:
                    raise RuntimeError("La instancia abierta todavía no responde.") from None
                time.sleep(0.25)
            else:
                break

        endpoint.unlink(missing_ok=True)
        try:
            with (data_dir / "inicio.log").open("w", encoding="utf-8", buffering=1) as log:
                previous = sys.stdout, sys.stderr
                sys.stdout = sys.stderr = log
                try:
                    run(data_dir, endpoint)
                except Exception:
                    traceback.print_exc()
                    raise
                finally:
                    sys.stdout, sys.stderr = previous
        finally:
            endpoint.unlink(missing_ok=True)


def main() -> int:
    data_dir = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "RutasCiclistas"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        start_or_reopen(data_dir)
    except Exception:
        if "--verificar" not in sys.argv:
            show_message(f"No se pudo abrir la aplicación. Revisa el registro en {data_dir}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
