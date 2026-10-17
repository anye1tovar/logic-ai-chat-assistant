import logging


def configure_logging(level: str) -> None:
    """Configure concise application logging without dumping settings or payloads."""
    normalized_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=normalized_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
