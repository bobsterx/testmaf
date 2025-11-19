from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TOKEN = "8597133472:AAHN387YGuvUDlZiUd4s4kqKjOSPoEh66B4"

BASE_DIR = Path(__file__).resolve().parent
GIF_DIR = BASE_DIR.parent / "gifs"

NIGHT_DURATION = 60
DAY_DURATION = 60
VOTE_DURATION = 30
BOT_DECISION_DELAY = 5

MAX_PLAYERS = 10
MIN_PLAYERS = 5
MAX_BOTS = 6

ROLE_TEXT = {
    "don": (
        "Дон",
        "Ви очолюєте мафію. Оберіть жертву вночі та перехитріть мирних."
    ),
    "mafia": (
        "Мафія",
        "Підтримуйте дона і при потребі успадкуйте його справу. Не видавайте себе."
    ),
    "doctor": (
        "Лікар",
        "Щоночі лікуйте когось. Себе можна лікувати лише один раз за гру."
    ),
    "detective": (
        "Детектив Кішкель",
        "Перевіряйте підозрілих та маєте один постріл, щоб зняти маску з ворога."
    ),
    "civil": (
        "Мирний",
        "Уважно слухайте містян та обирайте, кого варто вигнати з міста."
    ),
}

NIGHT_BANNERS = {
    "night_no_kick": "Цієї ночі в місті всі залишилися живі. Перевіримо, чи так буде й надалі...",
    "night_kicked": "Цієї ночі хтось полетів у вирій. Місто ще оговтується...",
}

MORNING_EVENTS = {
    "event_everyone_alive": "Ніч пройшла тихо. Всі жителі прокинулися!",
    "event_single_death": "Місто прокинулося в жалобі — є жертви минулої ночі.",
    "event_both_died": "Цієї ночі пролилася подвійна кров. Хто ж стоїть за цим?",
    "doc_saved": "Доктор зумів зберегти життя. Але чи надовго?",
    "don_dead_no_mafia": "Дона вбито, а сліду мафії не залишилося. Місто святкує перемогу!",
    "don_dead_mafia_alive": "Мафія залишилася сама, але продовжить справу дона...",
    "doc_dead": "Дон забрав життя лікаря. Що робитиме місто без нього?",
    "detective_dead": "Дон позбувся детектива. Тепер темрява стає густішою...",
    "civil_dead": "Дон забрав життя селянина. Хай спочиває з миром...",
    "event_mafia_win": "Мафія отримала контроль над селом та прибрала всіх зайвих.",
    "event_civil_won": "Мафію повержено, село у спокої... Чи надовго?",
}

GIFS = {
    "night": "night.gif",
    "morning": "morning.gif",
    "vote": "vote.gif",
    "dead": "dead.gif",
    "lost_civil": "lost_civil.gif",
    "lost_mafia": "lost_mafia.gif",
}


@dataclass(frozen=True)
class EventAssets:
    gif: Path
    caption: str


def gif_path(key: str) -> Path:
    return GIF_DIR / GIFS[key]
