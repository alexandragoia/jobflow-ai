import os
import socket
import threading
import time
import urllib.request
import webbrowser

# Some antivirus products inject an unwritable SSL key log path into child processes.
# Never write TLS session keys from this personal app.
os.environ.pop("SSLKEYLOGFILE", None)

def available_port():
    for port in range(8765, 8786):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Los puertos locales 8765–8785 están ocupados. Cierra las ventanas antiguas de JobFlow y vuelve a abrirlo.")

def open_when_ready(url):
    for _ in range(120):
        try:
            with urllib.request.urlopen(url + "api/health", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except OSError:
            time.sleep(.25)

if __name__ == "__main__":
    import uvicorn
    port = available_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"JobFlow AI: {url}\nDeja esta ventana abierta mientras usas la aplicación.\n")
    threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="info")
