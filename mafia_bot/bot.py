from __future__ import annotations

from telegram.ext import Application

from .config import TOKEN
from .handlers import build_application


def main() -> None:
    application = Application.builder().token(TOKEN).build()
    build_application(application)
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
