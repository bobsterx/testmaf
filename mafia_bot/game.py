from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .config import (
    BOT_DECISION_DELAY,
    DAY_DURATION,
    MIN_PLAYERS,
    NIGHT_BANNERS,
    NIGHT_DURATION,
    VOTE_DURATION,
    gif_path,
    MORNING_EVENTS,
)
from .models import Phase, Player, Role, VoteResult


@dataclass
class PendingAction:
    role: Role
    actor_id: int
    action_type: str
    target_id: Optional[int]


class Game:
    def __init__(self, chat_id: int, title: str):
        self.chat_id = chat_id
        self.title = title
        self.players: Dict[int, Player] = {}
        self.phase = Phase.LOBBY
        self.pending_actions: Dict[int, PendingAction] = {}
        self.bot_count = 0
        self.jobs = {}
        self.last_log_message: Optional[int] = None
        self.pending_votes: Dict[int, int] = {}
        self.awaiting_confirmation: Optional[int] = None
        self.day_counter = 0
        self.history: List[str] = []
        self.winner: Optional[str] = None
        self.next_night_banner = "night_no_kick"

    # region lobby helpers
    def living_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.alive]

    def add_player(self, player: Player) -> bool:
        if player.user_id in self.players:
            return False
        player.metadata["chat"] = str(self.chat_id)
        self.players[player.user_id] = player
        return True

    def remove_player(self, user_id: int) -> bool:
        if user_id in self.players:
            del self.players[user_id]
            return True
        return False

    def add_bot(self) -> Optional[Player]:
        if self.bot_count >= 6:
            return None
        self.bot_count += 1
        bot_id = -1000 - self.bot_count
        bot = Player(
            user_id=bot_id,
            username=f"bot{self.bot_count}",
            display_name=f"🤖 Бот #{self.bot_count}",
            is_bot=True,
        )
        bot.metadata["chat"] = str(self.chat_id)
        self.players[bot_id] = bot
        return bot

    def can_start(self) -> bool:
        return len(self.players) >= MIN_PLAYERS

    # endregion

    # region role assignment
    def assign_roles(self) -> None:
        alive_players = list(self.players.values())
        for p in alive_players:
            p.alive = True
            p.role = None
            p.can_self_heal = True
            p.has_shot = False
        random.shuffle(alive_players)
        total = len(alive_players)
        mafia_count = 1 if total >= 8 else 0

        humans = [p for p in alive_players if not p.is_bot]
        detective_holder = humans or alive_players
        detective = detective_holder[0]
        detective.role = Role.DETECTIVE

        remaining = [p for p in alive_players if p.user_id != detective.user_id]
        don = remaining[0]
        don.role = Role.DON

        pointer = 1
        for _ in range(mafia_count):
            if pointer >= len(remaining):
                break
            maf = remaining[pointer]
            maf.role = Role.MAFIA
            pointer += 1

        if pointer < len(remaining):
            doctor = remaining[pointer]
            doctor.role = Role.DOCTOR
            pointer += 1
        else:
            doctor = don

        for p in alive_players:
            if p.role is None:
                p.role = Role.CIVIL

    # endregion

    # region messaging helpers
    async def send_group(self, context: ContextTypes.DEFAULT_TYPE, text: str, gif: Optional[str] = None) -> None:
        if gif:
            path = gif_path(gif)
            try:
                await context.bot.send_animation(
                    chat_id=self.chat_id,
                    animation=InputFile(path),
                    caption=text,
                    parse_mode=ParseMode.HTML,
                )
            except FileNotFoundError:
                await context.bot.send_message(self.chat_id, text, parse_mode=ParseMode.HTML)
        else:
            await context.bot.send_message(self.chat_id, text, parse_mode=ParseMode.HTML)

    async def log(self, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        await context.bot.send_message(self.chat_id, text)

    async def send_dm(self, context: ContextTypes.DEFAULT_TYPE, player: Player, text: str, keyboard: Optional[InlineKeyboardMarkup] = None) -> None:
        if player.is_bot:
            return
        await context.bot.send_message(player.user_id, text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

    # endregion

    def reset_actions(self) -> None:
        self.pending_actions.clear()
        self.pending_votes.clear()
        self.awaiting_confirmation = None

    # region phase control
    async def start_game(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.assign_roles()
        self.phase = Phase.NIGHT
        self.day_counter = 0
        await self.send_group(
            context,
            text="Гра розпочалась! Місто засинає...",
            gif="night",
        )
        await self.push_role_messages(context)
        await self.prepare_night_actions(context)
        self.schedule_job(context, "resolve_night", NIGHT_DURATION, self.resolve_night)

    async def push_role_messages(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        from .config import ROLE_TEXT

        for player in self.players.values():
            role_key = player.role.key
            title, description = ROLE_TEXT[role_key]
            msg = (
                f"Ви долучилися до гри в мафію у групі <b>{self.title}</b>.\n\n"
                f"<b>Ваша роль:</b> {title}\n{description}"
            )
            await self.send_dm(context, player, msg)

    async def prepare_night_actions(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.reset_actions()
        self.phase = Phase.NIGHT
        await self.send_group(context, NIGHT_BANNERS[self.next_night_banner], gif="night")
        self.next_night_banner = "night_no_kick"
        for player in self.living_players():
            if player.role == Role.DON:
                await self.send_dm(
                    context,
                    player,
                    "Кого прибираємо цієї ночі?",
                    self.targets_keyboard(player.user_id, allow_self=False, action="don"),
                )
            elif player.role == Role.MAFIA and not self.has_don_alive():
                await self.send_dm(
                    context,
                    player,
                    "Ти очолив мафію. Обери жертву",
                    self.targets_keyboard(player.user_id, allow_self=False, action="mafia"),
                )
            elif player.role == Role.DOCTOR:
                await self.send_dm(
                    context,
                    player,
                    "Кого лікуємо цієї ночі?",
                    self.targets_keyboard(
                        player.user_id,
                        allow_self=player.can_self_heal,
                        action="doctor",
                    ),
                )
            elif player.role == Role.DETECTIVE:
                await self.send_dm(context, player, "Обери дію: перевірити чи вистрілити.", self.detective_keyboard(player.user_id))

        for player in self.living_players():
            if not player.is_bot:
                continue
            if player.role in {Role.DON, Role.DOCTOR}:
                self.schedule_job(
                    context,
                    f"bot_{player.user_id}",
                    BOT_DECISION_DELAY,
                    self.bot_decision,
                    data=player.user_id,
                )
            elif player.role == Role.MAFIA and not self.has_don_alive():
                self.schedule_job(
                    context,
                    f"bot_{player.user_id}",
                    BOT_DECISION_DELAY,
                    self.bot_decision,
                    data=player.user_id,
                )

    def schedule_job(self, context: ContextTypes.DEFAULT_TYPE, name: str, delay: int, callback, data=None) -> None:
        if name in self.jobs:
            self.jobs[name].schedule_removal()
        job = context.job_queue.run_once(callback, delay, data=data)
        self.jobs[name] = job

    def cancel_job(self, name: str) -> None:
        if name in self.jobs:
            self.jobs[name].schedule_removal()
            del self.jobs[name]

    def has_don_alive(self) -> bool:
        return any(p.alive and p.role == Role.DON for p in self.players.values())

    # endregion

    # region keyboards
    def targets_keyboard(self, actor_id: int, allow_self: bool, action: str) -> InlineKeyboardMarkup:
        buttons = []
        for player in self.living_players():
            if not allow_self and player.user_id == actor_id:
                continue
            buttons.append(InlineKeyboardButton(player.display_name, callback_data=f"action|{action}|{player.user_id}"))
        return InlineKeyboardMarkup.from_column(buttons)

    def detective_keyboard(self, actor_id: int) -> InlineKeyboardMarkup:
        inspect = InlineKeyboardButton("Перевірити", callback_data=f"detective|inspect|{actor_id}")
        shoot = InlineKeyboardButton("Вистрілити", callback_data=f"detective|shoot|{actor_id}")
        return InlineKeyboardMarkup([[inspect], [shoot]])

    def vote_keyboard(self, voter_id: int) -> InlineKeyboardMarkup:
        buttons = []
        for player in self.living_players():
            if player.user_id == voter_id:
                continue
            buttons.append([InlineKeyboardButton(player.display_name, callback_data=f"vote|{player.user_id}")])
        return InlineKeyboardMarkup(buttons)

    def confirm_keyboard(self, candidate_id: int) -> InlineKeyboardMarkup:
        yes = InlineKeyboardButton("Так", callback_data=f"confirm|{candidate_id}|yes")
        no = InlineKeyboardButton("Ні", callback_data=f"confirm|{candidate_id}|no")
        return InlineKeyboardMarkup([[yes, no]])

    # endregion

    async def record_action(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        actor_id: int,
        action_type: str,
        target_id: Optional[int],
    ) -> None:
        if self.phase != Phase.NIGHT:
            return
        actor = self.players.get(actor_id)
        if not actor or not actor.alive:
            return
        clean_action = action_type
        if action_type in {"detective_inspect", "detective_shoot"}:
            clean_action = action_type.split("_", 1)[1]
        if actor.is_bot:
            self.pending_actions[actor_id] = PendingAction(actor.role, actor_id, clean_action, target_id)
            await self.log_action(context, actor.role)
            return
        self.pending_actions[actor_id] = PendingAction(actor.role, actor_id, clean_action, target_id)
        await self.send_dm(context, actor, "Вибір збережено.")
        await self.log_action(context, actor.role)

    async def log_action(self, context: ContextTypes.DEFAULT_TYPE, role: Role) -> None:
        messages = {
            Role.DON: "Дон зробив свій вибір...",
            Role.MAFIA: "Мафія підтримала рішення...",
            Role.DOCTOR: "Лікар завершив лікування...",
            Role.DETECTIVE: "Детектив прийняв рішення...",
        }
        if role in messages:
            await self.log(context, messages[role])

    async def bot_decision(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        actor_id = context.job.data
        actor = self.players.get(actor_id)
        if not actor or not actor.alive:
            return
        if actor.role == Role.DETECTIVE:
            return
        if self.phase != Phase.NIGHT:
            return
        alive = self.living_players()
        choices = [p for p in alive if p.user_id != actor_id]
        if not choices:
            return
        target = random.choice(choices)
        if actor.role == Role.DOCTOR:
            allow_self = actor.can_self_heal
            if allow_self and random.choice([True, False]):
                target = actor
            elif not allow_self:
                target = random.choice(choices)
        await self.record_action(context, actor_id, actor.role.value, target.user_id)

    # region resolution
    async def resolve_night(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self.phase != Phase.NIGHT:
            return
        victims: Dict[int, List[str]] = defaultdict(list)
        saved_target: Optional[int] = None
        doc_action = self.get_action(Role.DOCTOR)
        if doc_action:
            doctor = self.players[doc_action.actor_id]
            if doc_action.target_id == doctor.user_id:
                doctor.can_self_heal = False
            saved_target = doc_action.target_id

        don_action = self.get_action(Role.DON) or self.get_action(Role.MAFIA)
        if don_action and don_action.target_id is not None:
            victims[don_action.target_id].append("don")

        detective_action = self.get_action(Role.DETECTIVE)
        inspection_text = None
        if detective_action:
            if detective_action.action_type == "inspect" and detective_action.target_id:
                inspected = self.players.get(detective_action.target_id)
                if inspected:
                    inspection_text = f"{inspected.display_name} має роль {inspected.role.name.title()}"
            elif detective_action.action_type == "shoot" and detective_action.target_id:
                victims[detective_action.target_id].append("detective")
                self.players[detective_action.actor_id].has_shot = True

        doc_saved = False
        deaths: List[Player] = []
        for target_id, killers in victims.items():
            if target_id == saved_target:
                doc_saved = True
                continue
            target = self.players.get(target_id)
            if not target or not target.alive:
                continue
            target.alive = False
            deaths.append(target)

        await self.broadcast_night_result(context, deaths, doc_saved)

        if inspection_text and detective_action:
            detective = self.players[detective_action.actor_id]
            await self.send_dm(context, detective, inspection_text)

        if await self.check_game_end(context):
            return

        await self.start_day(context)

    def get_action(self, role: Role) -> Optional[PendingAction]:
        for action in self.pending_actions.values():
            if action.role == role:
                return action
        return None

    async def broadcast_night_result(self, context: ContextTypes.DEFAULT_TYPE, deaths: List[Player], doc_saved: bool) -> None:
        if not deaths:
            event_key = "event_everyone_alive"
        elif len(deaths) == 1:
            event_key = "event_single_death"
        else:
            event_key = "event_both_died"
        text = MORNING_EVENTS[event_key]
        if doc_saved:
            text += f"\n\n{MORNING_EVENTS['doc_saved']}"
        await self.send_group(context, text, gif="morning")
        for player in deaths:
            await self.send_group(context, f"{player.mention()} загинув цієї ночі.", gif="dead")
            if player.role == Role.DON:
                if any(p.alive and p.role == Role.MAFIA for p in self.players.values()):
                    await self.send_group(context, MORNING_EVENTS["don_dead_mafia_alive"])
                    inheritor = next(p for p in self.players.values() if p.alive and p.role == Role.MAFIA)
                    inheritor.role = Role.DON
                else:
                    await self.send_group(context, MORNING_EVENTS["don_dead_no_mafia"], gif="lost_mafia")
                    self.winner = "Мирні"
            elif player.role == Role.DOCTOR:
                await self.send_group(context, MORNING_EVENTS["doc_dead"])
            elif player.role == Role.DETECTIVE:
                await self.send_group(context, MORNING_EVENTS["detective_dead"])
            elif player.role == Role.CIVIL:
                await self.send_group(context, MORNING_EVENTS["civil_dead"])

    async def start_day(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self.winner:
            await self.finish_game(context)
            return
        self.phase = Phase.DAY
        self.day_counter += 1
        await self.send_group(
            context,
            text=f"День {self.day_counter}. Обговоріть події та готуйтеся до голосування.",
            gif="morning",
        )
        self.schedule_job(context, "start_vote", DAY_DURATION, self.start_vote)

    async def start_vote(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self.phase != Phase.DAY:
            return
        self.phase = Phase.VOTE
        self.pending_votes.clear()
        await self.send_group(context, "Починаємо голосування. 30 секунд на вибір.", gif="vote")
        for player in self.living_players():
            await self.send_dm(context, player, "Кого підозрюєш?", self.vote_keyboard(player.user_id))
        self.schedule_job(context, "resolve_vote", VOTE_DURATION, self.resolve_vote)

    async def resolve_vote(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self.phase != Phase.VOTE:
            return
        self.phase = Phase.NIGHT
        result = self.calculate_votes()
        if result.target is None:
            await self.send_group(context, "Місто вирішило нікого не чіпати.")
            await self.prepare_night_actions(context)
            self.schedule_job(context, "resolve_night", NIGHT_DURATION, self.resolve_night)
            return
        victim = self.players[result.target]
        victim.alive = False
        self.next_night_banner = "night_kicked"
        await self.send_group(context, f"{victim.mention()} страчено за рішенням містян.", gif="dead")
        if await self.check_game_end(context):
            return
        await self.prepare_night_actions(context)
        self.schedule_job(context, "resolve_night", NIGHT_DURATION, self.resolve_night)

    def calculate_votes(self) -> VoteResult:
        counter: Dict[int, int] = defaultdict(int)
        for target in self.pending_votes.values():
            if target is None:
                continue
            counter[target] += 1
        if not counter:
            return VoteResult(None, 0, self.required_votes())
        target, votes = max(counter.items(), key=lambda item: item[1])
        required = self.required_votes()
        if votes >= required:
            return VoteResult(target, votes, required)
        return VoteResult(None, votes, required)

    def required_votes(self) -> int:
        alive = len(self.living_players())
        return alive // 2 + 1

    async def record_vote(self, context: ContextTypes.DEFAULT_TYPE, voter_id: int, target_id: int) -> None:
        if self.phase != Phase.VOTE:
            return
        voter = self.players.get(voter_id)
        target = self.players.get(target_id)
        if not voter or not target or not voter.alive or not target.alive:
            return
        self.pending_votes[voter_id] = target_id
        await self.send_dm(context, voter, f"Ти віддав голос за {target.display_name}.")

    async def check_game_end(self, context: ContextTypes.DEFAULT_TYPE) -> bool:
        alive = self.living_players()
        mafia_alive = [p for p in alive if p.role in {Role.DON, Role.MAFIA}]
        civ_alive = [p for p in alive if p.role not in {Role.DON, Role.MAFIA}]
        if not mafia_alive:
            self.winner = "Мирні"
        elif len(mafia_alive) >= len(civ_alive):
            self.winner = "Мафія"
        if self.winner:
            await self.finish_game(context)
            return True
        return False

    async def finish_game(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self.winner == "Мирні":
            await self.send_group(context, MORNING_EVENTS["event_civil_won"], gif="lost_mafia")
        elif self.winner == "Мафія":
            await self.send_group(context, MORNING_EVENTS["event_mafia_win"], gif="lost_civil")
        self.phase = Phase.ENDED
        for job in list(self.jobs):
            self.cancel_job(job)

    # endregion
