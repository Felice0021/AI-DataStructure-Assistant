"""Standalone indexing worker; cloud use requires global opt-in AND per-document consent."""
import argparse
import logging
import signal
from threading import Event

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from backend.v2.core.config import Settings
from backend.v2.core.logging import configure_logging
from backend.v2.db.session import build_engine, build_session_factory
from backend.v2.models import EmbeddingSpace
from backend.v2.services import embedding_service as jobs
from backend.v2.services.embedding_provider import EmbeddingError, build_provider, enabled

logger=logging.getLogger(__name__)


def run_once(factory,settings,stop=None,provider=None):
    if not enabled(settings):return False
    with factory() as session:
        jobs.reconcile(session,settings)
        claim=jobs.claim_next(session,settings)
    if claim is None:return False
    provider=provider or build_provider(settings,factory.kw['bind'])
    def reserve():
        if stop is not None and stop.is_set():raise EmbeddingError('worker_stopped',True)
        with factory() as session:jobs.reserve_attempt(session,claim,settings)
    try:
        if provider.space.id!=claim.space_id:raise EmbeddingError('embedding_model_mismatch')
        # Verify BOTH modes on synthetic text before sending any personal document text.
        with factory() as session:
            space=session.get(EmbeddingSpace,claim.space_id)
            needs_probe=space.provider=='dashscope' and space.verified_at is None
        if needs_probe:
            for mode in ('document','query'):
                provider.embed(['合成数据结构测试：链表与数组。'],text_type=mode,before_attempt=reserve)
            with factory() as session:
                if jobs.current(session,claim,settings) is None:return True
                session.get(EmbeddingSpace,claim.space_id).verified_at=session.scalar(select(func.clock_timestamp()))
                session.commit()
        while True:
            with factory() as session:batch=jobs.load_batch(session,claim,settings)
            if not batch:
                with factory() as session:jobs.complete(session,claim,settings)
                break
            vectors=provider.embed([row[2] for row in batch],text_type='document',before_attempt=reserve)
            with factory() as session:
                if not jobs.save_batch(session,claim,batch,vectors,settings):break
    except EmbeddingError as error:
        with factory() as session:jobs.fail(session,claim,error,settings)
    except SQLAlchemyError:
        logger.warning('Embedding database failure; fenced lease recovery required')
    return True


def main():
    parser=argparse.ArgumentParser(description='V2 embedding worker (disabled by default)')
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    configure_logging();settings=Settings()
    if not enabled(settings):
        logger.warning('Embedding disabled or configuration incomplete; no external calls made')
        return
    engine=build_engine(settings);factory=build_session_factory(engine);stop=Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    try:
        while not stop.is_set():
            try:worked=run_once(factory,settings,stop)
            except SQLAlchemyError:
                logger.warning('Embedding database unavailable');worked=False
            if args.once:break
            if not worked:stop.wait(settings.worker_poll_seconds)
    finally:engine.dispose()


if __name__=='__main__':main()
