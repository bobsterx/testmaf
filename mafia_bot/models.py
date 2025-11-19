from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Optional


class Role(Enum):
    DON = "don"
    MAFIA = "mafia"
    DOCTOR = "doctor"
    DETECTIVE = "detective"
    CIVIL = "civil"

    @property
    def key(self) -> str:
        return self.value


class Phase(Enum):
    LOBBY = auto()
    NIGHT = auto()
    DAY = auto()
    VOTE = auto()
    ENDED = auto()


@dataclass
class Player:
    user_id: int
    username: str
    display_name: str
    is_bot: bool = False
    role: Optional[Role] = None
    alive: bool = True
    can_self_heal: bool = True
    has_shot: bool = False
    last_target: Optional[int] = None
    metadata: Dict[str, str] = field(default_factory=dict)

    def mention(self) -> str:
        if self.is_bot:
            return self.display_name
        if self.username:
            return f"@{self.username}"
        return self.display_name


@dataclass
class VoteResult:
    target: Optional[int]
    votes_for: int
    required: int
