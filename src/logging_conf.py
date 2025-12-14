"""Logging configuration with Better Stack support."""
import logging
import sys
from logtail import LogtailHandler
from . import settings


def setup_logging():
    """Configure logging with optional Better Stack."""
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if settings.BETTERSTACK_SOURCE_TOKEN:
        logtail_handler = LogtailHandler(
            source_token=settings.BETTERSTACK_SOURCE_TOKEN,
            host=settings.BETTERSTACK_INGEST_HOST or "in.logs.betterstack.com",
        )
        handlers.append(logtail_handler)
    
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    
    # Reduce noise from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

