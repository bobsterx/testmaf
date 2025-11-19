from __future__ import annotations

from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext, CallbackQueryHandler, CommandHandler

from .config import MAX_BOTS, MAX_PLAYERS, MIN_PLAYERS
from .game import Game
from .models import Phase, Player


games: Dict[int, Game] = {}


def find_game_by_player(user_id: int) -> Optional[Game]:
    for game in games.values():
        if user_id in game.players:
            return game
    return None


def get_game(chat_id: int, title: str) -> Game:
    game = games.get(chat_id)
    if not game:
        game = Game(chat_id, title)
        games[chat_id] = game
    return game


def lobby_keyboard(game: Game) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("Доєднатися", callback_data="lobby|join")],
        [InlineKeyboardButton("Вийти", callback_data="lobby|leave")],
        [InlineKeyboardButton("Додати бота", callback_data="lobby|bot")],
        [InlineKeyboardButton("Почати гру", callback_data="lobby|start")],
    ]
    return InlineKeyboardMarkup(buttons)


def format_lobby(game: Game) -> str:
    humans = [p.display_name for p in game.players.values() if not p.is_bot]
    bots = [p.display_name for p in game.players.values() if p.is_bot]
    text = ["<b>Лобі мафії</b>"]
    text.append("Гравці:" if humans else "Гравців немає")
    for name in humans:
        text.append(f"• {name}")
    if bots:
        text.append("\nБоти:")
        for bot in bots:
            text.append(f"• {bot}")
    text.append(f"\nЗареєстровано: {len(game.players)}/{MAX_PLAYERS}")
    text.append(f"Мінімум для старту: {MIN_PLAYERS}")
    return "\n".join(text)


async def start_private(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.type != "private":
        return
    text = (
        "Привіт! Це бот для гри в мафію. Додайте мене в групу та використовуйте /mafia, щоб створити лобі.\n"
        "Не забудьте залишити мені повідомлення, щоб я міг писати вам у грі."
    )
    await update.message.reply_text(text)


async def mafia_command(update: Update, context: CallbackContext) -> None:
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text("Гра доступна лише в групах.")
        return
    game = get_game(chat.id, chat.title or "Місто")
    await update.message.reply_text(format_lobby(game), reply_markup=lobby_keyboard(game), parse_mode="HTML")


async def lobby_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    chat = query.message.chat
    game = get_game(chat.id, chat.title or "Місто")
    action = query.data.split("|")[1]
    user = query.from_user
    if action == "join":
        if len(game.players) >= MAX_PLAYERS:
            await query.edit_message_text("Лобі заповнено.")
            return
        player = Player(user.id, user.username or "", user.full_name)
        if game.add_player(player):
            await query.edit_message_text(format_lobby(game), reply_markup=lobby_keyboard(game), parse_mode="HTML")
        else:
            await query.answer("Ви вже в грі", show_alert=True)
    elif action == "leave":
        game.remove_player(user.id)
        await query.edit_message_text(format_lobby(game), reply_markup=lobby_keyboard(game), parse_mode="HTML")
    elif action == "bot":
        if game.bot_count >= MAX_BOTS or len(game.players) >= MAX_PLAYERS:
            await query.answer("Ліміт ботів", show_alert=True)
            return
        game.add_bot()
        await query.edit_message_text(format_lobby(game), reply_markup=lobby_keyboard(game), parse_mode="HTML")
    elif action == "start":
        if not game.can_start():
            await query.answer("Мало гравців", show_alert=True)
            return
        if game.phase != Phase.LOBBY:
            await query.answer("Гра вже триває", show_alert=True)
            return
        await game.start_game(context)
        await query.edit_message_text("Гру розпочато!", parse_mode="HTML")


async def action_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    prefix = parts[0]
    user_id = query.from_user.id
    game = find_game_by_player(user_id)
    if not game:
        await query.answer("Не в грі", show_alert=True)
        return
    player = game.players[user_id]
    if prefix == "action":
        action_type = parts[1]
        target_id = int(parts[2])
        await game.record_action(context, user_id, action_type, target_id)
    elif prefix == "detective":
        action = parts[1]
        if action == "inspect":
            keyboard = game.targets_keyboard(user_id, allow_self=False, action="detective_inspect")
            await query.edit_message_text("Кого перевіряємо?", reply_markup=keyboard)
        else:
            keyboard = game.targets_keyboard(user_id, allow_self=False, action="detective_shoot")
            await query.edit_message_text("У кого стріляємо?", reply_markup=keyboard)
    elif prefix == "vote":
        target = int(parts[1])
        await game.record_vote(context, user_id, target)
        await query.edit_message_text("Голос зафіксовано")


def build_application(application):
    application.add_handler(CommandHandler("start", start_private))
    application.add_handler(CommandHandler("mafia", mafia_command))
    application.add_handler(CallbackQueryHandler(lobby_callback, pattern=r"^lobby"))
    application.add_handler(CallbackQueryHandler(action_callback, pattern=r"^(action|detective|vote)"))
    return application
