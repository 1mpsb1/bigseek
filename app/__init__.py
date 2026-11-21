"""BigSeek Desktop — isolated browser profiles for chat.deepseek.com."""

from .config import APP_AUTHOR, APP_TITLE, APP_VERSION_FALLBACK, app_version

__title__ = APP_TITLE
__author__ = APP_AUTHOR
__version__ = app_version() or APP_VERSION_FALLBACK
