import logging
from logging.handlers import RotatingFileHandler


def configureLogging(paths):
    logger = logging.getLogger("oso")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = RotatingFileHandler(paths.data / "logs" / "oso.log", maxBytes=5_000_000, backupCount=9, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.addHandler(logging.StreamHandler())
    return logger
