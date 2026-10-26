"""Standalone leased ingestion worker. No API lifespan/background thread autostart."""
import argparse
import logging
import signal
from threading import Event

from sqlalchemy.exc import SQLAlchemyError

from backend.v2.core.config import Settings
from backend.v2.core.logging import configure_logging
from backend.v2.db.session import build_engine, build_session_factory
from backend.v2.services import ingestion_service as jobs
from backend.v2.services.chunking import ParseFailure
from backend.v2.services.parser_runner import parse_source

logger = logging.getLogger(__name__)


def run_once(factory, settings, stop=None):
    with factory() as session:
        jobs.reconcile(session, settings)
        claim = jobs.claim_next(session, settings)
    if claim is None:
        return False
    try:
        with factory() as session:
            source = jobs.open_claim_source(session, claim, settings)
        if source is None:
            return True
        with source:
            chunks = parse_source(source, claim, settings, stop)
        with factory() as session:
            jobs.complete(session, claim, chunks, settings)
    except ParseFailure as error:
        with factory() as session:
            jobs.fail(session, claim, error.code, error.retryable, settings)
    except OSError:
        with factory() as session:
            jobs.fail(session, claim, "storage_unavailable", True, settings)
    except SQLAlchemyError:
        # No commit is assumed after disconnect; the fenced lease expires and is reclaimed.
        logger.warning("Ingestion database failure; lease recovery will retry")
    return True


def main():
    parser = argparse.ArgumentParser(description="V2 PostgreSQL document ingestion worker")
    parser.add_argument("--once", action="store_true", help="Reconcile and process at most one job")
    args = parser.parse_args()
    configure_logging()
    settings, stop = Settings(), Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        while not stop.is_set():
            try:
                worked = run_once(factory, settings, stop)
            except SQLAlchemyError:
                logger.warning("Ingestion database temporarily unavailable")
                worked = False
            if args.once:
                break
            if not worked:
                stop.wait(settings.worker_poll_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
