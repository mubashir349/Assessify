"""Production server (Phase 8). Use this instead of `python run.py` on the deployed machine.

    python serve.py                    # http://0.0.0.0:8000, settings from .env (FLASK_ENV=production)

waitress is a pure-Python production server that works the same on Windows and Linux. One process, many threads:
the login limits and the AI job state stay in one place. PORT / HOST / WAITRESS_THREADS can be set in .env.
"""
import logging
import os

from waitress import serve

from app import create_app


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app()
    # a server must listen on its network address to be reachable
    host = os.getenv("HOST", "0.0.0.0")  # NOSONAR
    port = int(os.getenv("PORT", "8000"))
    threads = int(os.getenv("WAITRESS_THREADS", "16"))
    logging.getLogger(__name__).info("Assessify on http://%s:%s (%s threads, env=%s)", host, port, threads,
                                     app.config["ENV"])
    serve(app, host=host, port=port, threads=threads, connection_limit=1000, channel_timeout=120,
          clear_untrusted_proxy_headers=False, ident="assessify")


if __name__ == "__main__":
    main()
