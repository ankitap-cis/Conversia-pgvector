import logging
from logging.handlers import RotatingFileHandler
import os
from colorlog import ColoredFormatter
from datetime import datetime as dt
from contextvars import ContextVar

from requests import Session

from connection import get_db
from models.users import ImpersonationLog

# Context vars to hold impersonation info (set these in your middleware or auth)
actor_email_ctx: ContextVar[str] = ContextVar("actor_email", default="anonymous")
subject_email_ctx: ContextVar[str] = ContextVar("subject_email", default="anonymous")
action_ctx: ContextVar[str] = ContextVar("action", default="anonymous")


# Custom logging Filter to inject impersonation info into LogRecord
class ImpersonationContextFilter(logging.Filter):
    def filter(self, record):
        record.actor_email = actor_email_ctx.get()
        record.subject_email = subject_email_ctx.get()
        return True

# Create logs directory if not exists
log_dir = 'log_files'
os.makedirs(log_dir, exist_ok=True)

# Base logger
base_logger = logging.getLogger(__name__)
base_logger.setLevel(logging.DEBUG)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_formatter = ColoredFormatter(
    "%(log_color)s%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
    reset=True,
    log_colors={
        'DEBUG': 'green',
        'INFO': 'blue',
        'ERROR': 'red',
        'WARNING': 'yellow',
        'CRITICAL': 'red'
    }
)
console_handler.setFormatter(console_formatter)
console_handler.addFilter(ImpersonationContextFilter())
base_logger.addHandler(console_handler)

# File handler
log_filename = os.path.join(log_dir, dt.now().strftime('%Y-%m-%d') + '_applog.log')
file_handler = RotatingFileHandler(log_filename, maxBytes=10 * 1024 * 1024, backupCount=10)  # 10MB, keep 10 backups
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
)
file_handler.setFormatter(file_formatter)
file_handler.addFilter(ImpersonationContextFilter())
base_logger.addHandler(file_handler)


# --- DB handler (custom) ---
class DBLogHandler(logging.Handler):
    def __init__(self, db_session_factory=get_db):
        super().__init__()
        self.db_session_factory = db_session_factory

    def emit(self, record: logging.LogRecord):
        try:
            actor = actor_email_ctx.get()
            subject = subject_email_ctx.get()
            action = action_ctx.get()

            if actor != subject:  # only save impersonated actions
                db: Session = next(self.db_session_factory())
                log_entry = ImpersonationLog(
                    actor_email=actor,
                    subject_email=subject,
                    action=action,
                    message=record.getMessage(),
                )
                db.add(log_entry)
                db.commit()
        except Exception as e:
            logger.error(f"Failed to save impersonation log: {e}")


db_handler = DBLogHandler()
db_handler.setLevel(logging.INFO)
db_handler.setFormatter(file_formatter)  # reuse same format
base_logger.addHandler(db_handler)

# Logger wrapper that prefixes messages based on impersonation
class ContextLogger:
    def __init__(self, logger):
        self._logger = logger

    def _prefix_message(self, msg):
        actor = actor_email_ctx.get()
        subject = subject_email_ctx.get()
        if actor != subject:
            prefix = f"Action by superadmin {actor} on behalf of {subject} - "
        else:
            prefix = ""
        return prefix + msg

    def debug(self, msg, *args, **kwargs):
        self._logger.debug(self._prefix_message(msg), *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._logger.info(self._prefix_message(msg), *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._logger.warning(self._prefix_message(msg), *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._logger.error(self._prefix_message(msg), *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self._logger.critical(self._prefix_message(msg), *args, **kwargs)

# Wrap the base logger with ContextLogger
logger = ContextLogger(base_logger)

