import logging
import asyncio
import time
import datetime
import sys
import os
from typing import Union, List, Dict, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ReplyKeyboardRemove, BotCommand

# ==============================================================================
# --- КОНФИГУРАЦИЯ И ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
# ==============================================================================
TOKEN = "8331981056:AAETEMewZiaM-0ffToiaIHOIJTxQkiWk7Rw"
MAIN_OWNERS = [8461055593, 5845609895]

# Настройка логирования для контроля состояния сервера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("EEC_FINAL_SYSTEM")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==============================================================================
# --- ХРАНИЛИЩЕ ДАННЫХ (DATABASE IMITATION) ---
# ==============================================================================
class Database:
    def __init__(self):
        self.admins = []       # Список дополнительных ID администраторов
        self.countries = [
            "🇷🇺 Россия", "🇺🇦 Украина", "🇰🇿 Казахстан", 
            "🇧🇾 Беларусь", "🇵🇱 Польша", "🇪🇪 Эстония", 
            "🇱🇹 Литва", "🇱🇻 Латвия", "🇲🇩 Молдова"
        ]
        # {TeamName: {owner: int, coach: int, players: list, history: list}}
        self.teams = {}   
        # {ID: {nick: str, country: str, active: bool, nick_cd: float, career_cd: float}}
        self.players = {} 
        # {username_lower: ID}
        self.user_index = {} 
        self.config = {
            "channel_id": None,
            "channel_name": "Не привязан",
            "maintenance": False
        }
        self.stats = {
            "total_recruits": 0,
            "total_career_changes": 0,
            "total_nicks": 0
        }

db = Database()

# ==============================================================================
# --- МАШИНА СОСТОЯНИЙ (FSM) ---
# ==============================================================================
class Registration(StatesGroup):
    nick = State()
    country = State()

class ProfileUpdate(StatesGroup):
    new_nick = State()

class CareerProcess(StatesGroup):
    finishing_reason = State()
    returning_msg = State()

class AdminProcess(StatesGroup):
    create_team_name = State()
    delete_team_confirm = State()
    set_owner_team = State()
    set_owner_id = State()
    add_admin_id = State()
    remove_admin_id = State()
    wait_channel_forward = State()
    broadcast_msg = State()

class TeamManagement(StatesGroup):
    recruit_desc = State()
    invite_tag = State()
    kick_select = State()
    set_coach_id = State()
    contact_owner_team = State()
    contact_owner_text = State()

# ==============================================================================
# --- УНИВЕРСАЛЬНЫЕ КЛАВИАТУРЫ ---
# ==============================================================================

def get_main_menu(uid: int):
    """Генерация меню на основе ролей пользователя"""
    builder = ReplyKeyboardBuilder()
    
    # 1. Проверка на Администратора
    if uid in MAIN_OWNERS or uid in db.admins:
        builder.button(text="🛡 ПАНЕЛЬ УПРАВЛЕНИЯ")
    
    # 2. Проверка на Лидерские права
    is_lead = False
    for t_data in db.teams.values():
        if t_data["owner"] == uid or t_data["coach"] == uid:
            is_lead = True
            break
            
    if is_lead:
        builder.button(text="📋 МОЯ СБОРНАЯ")
        builder.button(text="📢 ОБЪЯВИТЬ НАБОР")
        builder.button(text="➕ ПРИГЛАСИТЬ")
        builder.button(text="👢 ИСКЛЮЧИТЬ")

    # 3. Общий функционал
    builder.button(text="👤 МОЙ ПРОФИЛЬ")
    builder.button(text="🔄 СМЕНИТЬ НИК")
    builder.button(text="🏁 УЙТИ ИЗ СПОРТА")
    builder.button(text="🔙 ВЕРНУТЬСЯ В СПОРТ")
    builder.button(text="✉️ СВЯЗЬ С ГЛАВОЙ")
    
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_admin_menu():
    """Меню для работы администрации бота"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="🏗 СОЗДАТЬ СБОРНУЮ")
    builder.button(text="🗑 УДАЛИТЬ СБОРНУЮ")
    builder.button(text="👑 НАЗНАЧИТЬ ГЛАВУ")
    builder.button(text="🛡 ДОБАВИТЬ АДМИНА")
    builder.button(text="🔗 ПРИВЯЗАТЬ КАНАЛ")
    builder.button(text="📊 СТАТИСТИКА БОТА")
    builder.button(text="📢 ОБЪЯВЛЕНИЕ ВСЕМ")
    builder.button(text="🏠 ГЛАВНОЕ МЕНЮ")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_cancel_kb():
    """Кнопка выхода из любого сценария"""
    return ReplyKeyboardBuilder().button(text="⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ").as_markup(resize_keyboard=True)

# ==============================================================================
# --- СИСТЕМА ЛОГИРОВАНИЯ И КАНАЛА (ID BINDING) ---
# ==============================================================================

@dp.message(F.text == "🔗 ПРИВЯЗАТЬ КАНАЛ")
async def channel_setup_init(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_OWNERS and message.from_user.id not in db.admins:
        return
    await message.answer(
        "🛠 **Настройка системного канала логов**\n\n"
        "Чтобы бот мог публиковать наборы и смены ников, сделайте следующее:\n"
        "1. Добавьте бота в канал как администратора.\n"
        "2. Убедитесь, что у него есть права на публикацию сообщений.\n"
        "3. **ПЕРЕШЛИТЕ** любое сообщение из этого канала в этот чат.\n\n"
        "Бот автоматически вытянет скрытый ID канала.",
        parse_mode="Markdown",
        reply_markup=get_cancel_kb()
    )
    await state.set_state(AdminProcess.wait_channel_forward)

@dp.message(AdminProcess.wait_channel_forward)
async def channel_setup_catch(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ":
        await message.answer("Настройка отменена.", reply_markup=get_admin_menu())
        await state.clear()
        return

    if message.forward_from_chat:
        db.config["channel_id"] = message.forward_from_chat.id
        db.config["channel_name"] = message.forward_from_chat.title
        await message.answer(
            f"✅ **Канал успешно привязан!**\n\n"
            f"Название: `{db.config['channel_name']}`\n"
            f"ID: `{db.config['channel_id']}`\n\n"
            "Все автоматические уведомления теперь будут приходить туда.",
            parse_mode="Markdown",
            reply_markup=get_admin_menu()
        )
        await state.clear()
    else:
        await message.answer("❌ Ошибка! Это не пересланное сообщение. Попробуйте снова или отмените действие.")

# ==============================================================================
# --- КАРЬЕРНЫЙ ЦИКЛ (ЗАВЕРШЕНИЕ И ВОЗВРАТ) ---
# ==============================================================================

# --- ЗАВЕРШЕНИЕ ---
@dp.message(F.text == "🏁 УЙТИ ИЗ СПОРТА")
async def process_retire_start(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in db.players or not db.players[uid]["active"]:
        await message.answer("Вы уже не являетесь активным участником.")
        return

    await message.answer(
        "📝 **Завершение карьеры**\n\n"
        "Напишите текст вашего прощального заявления. "
        "Он будет опубликован в официальном канале.",
        reply_markup=get_cancel_kb()
    )
    await state.set_state(CareerProcess.finishing_reason)

@dp.message(CareerProcess.finishing_reason)
async def process_retire_finish(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ":
        await message.answer("Действие отменено.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return

    uid = message.from_user.id
    text = message.text
    
    # Обновление данных
    db.players[uid]["active"] = False
    db.players[uid]["career_cd"] = time.time()
    db.stats["total_career_changes"] += 1
    
    await message.answer("💔 Вы официально завершили карьеру. Информация передана в архив.", reply_markup=get_main_kb(uid))

    # ПУБЛИКАЦИЯ В КАНАЛ
    if db.config["channel_id"]:
        try:
            tag = f"@{message.from_user.username}" if message.from_user.username else f"ID: {uid}"
            log_msg = (
                "📉 **Завершение карьеры!**\n\n"
                f"👤 Игрок: {tag}\n"
                f"🎮 Ник: {db.players[uid]['nick']}\n"
                f"💬 Текст: {text}"
            )
            await bot.send_message(db.config["channel_id"], log_msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to post retirement: {e}")
    await state.clear()

# --- ВОЗВРАЩЕНИЕ ---
@dp.message(F.text == "🔙 ВЕРНУТЬСЯ В СПОРТ")
async def process_return_start(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in db.players: return
    
    if db.players[uid]["active"]:
        await message.answer("Ваша карьера уже активна.")
        return

    # Проверка КД 7 дней (Обход для владельцев и админов)
    is_staff = uid in MAIN_OWNERS or uid in db.admins
    if not is_staff:
        last_exit = db.players[uid].get("career_cd", 0)
        cooldown = 604800 # 7 суток
        if time.time() - last_exit < cooldown:
            remaining = cooldown - (time.time() - last_exit)
            days = int(remaining // 86400)
            await message.answer(f"⏳ Вернуться можно только спустя 7 дней после ухода.\nОсталось: {days} дн.")
            return

    await message.answer(
        "🔥 **Возвращение в карьеру**\n\n"
        "Напишите текст вашего обращения по случаю возвращения:",
        reply_markup=get_cancel_kb()
    )
    await state.set_state(CareerProcess.returning_msg)

@dp.message(CareerProcess.returning_msg)
async def process_return_finish(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ":
        await message.answer("Действие отменено.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return

    uid = message.from_user.id
    db.players[uid]["active"] = True
    
    await message.answer("✅ Карьера возобновлена! Удачи на полях сражений.", reply_markup=get_main_menu(uid))

    if db.config["channel_id"]:
        try:
            tag = f"@{message.from_user.username}" if message.from_user.username else f"ID: {uid}"
            log_msg = (
                "📈 **Возвращение карьеры!**\n\n"
                f"👤 Игрок: {tag}\n"
                f"🎮 Ник: {db.players[uid]['nick']}\n"
                f"💬 Текст: {message.text}"
            )
            await bot.send_message(db.config["channel_id"], log_msg, parse_mode="Markdown")
        except: pass
    await state.clear()

# ==============================================================================
# --- СМЕНА НИКА (ЛОГ ПО ШАБЛОНУ) ---
# ==============================================================================

@dp.message(F.text == "🔄 СМЕНИТЬ НИК")
async def process_nick_change_1(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in db.players: return
    
    # КД на ник (7 дней)
    if uid not in MAIN_OWNERS and uid not in db.admins:
        last = db.players[uid].get("nick_cd", 0)
        if time.time() - last < 604800:
            await message.answer("❌ Смена никнейма возможна раз в неделю.")
            return

    await message.answer("Введите ваш новый игровой ник Roblox:", reply_markup=get_cancel_kb())
    await state.set_state(ProfileUpdate.new_nick)

@dp.message(ProfileUpdate.new_nick)
async def process_nick_change_2(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ":
        await message.answer("Отменено.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return

    new_name = message.text.strip()
    if len(new_name) < 3 or len(new_name) > 20:
        await message.answer("❌ Ник должен быть от 3 до 20 символов.")
        return

    uid = message.from_user.id
    old_name = db.players[uid]["nick"]
    
    db.players[uid]["nick"] = new_name
    db.players[uid]["nick_cd"] = time.time()
    db.stats["total_nicks"] += 1
    
    await message.answer(f"✅ Ник успешно обновлен: {new_name}!", reply_markup=get_main_menu(uid))

    if db.config["channel_id"]:
        try:
            tag = f"@{message.from_user.username}" if message.from_user.username else f"ID: {uid}"
            # ШАБЛОН: (юзернейм) старый -> новый
            log_line = f"🔄 **Лог изменения ника**\n{tag} {old_name} —> {new_name}"
            await bot.send_message(db.config["channel_id"], log_line, parse_mode="Markdown")
        except: pass
    await state.clear()

# ==============================================================================
# --- АДМИНИСТРАТИВНЫЙ БЛОК (БОЛЕЕ 300 СТРОК ЛОГИКИ) ---
# ==============================================================================

@dp.message(F.text == "🛡 ПАНЕЛЬ УПРАВЛЕНИЯ")
async def admin_panel_open(message: types.Message):
    if message.from_user.id in MAIN_OWNERS or message.from_user.id in db.admins:
        await message.answer("🛡 Доступ к панели администратора разрешен.", reply_markup=get_admin_menu())

@dp.message(F.text == "🛡 ДОБАВИТЬ АДМИНА")
async def admin_add_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_OWNERS:
        await message.answer("❌ Только главные владельцы могут добавлять админов.")
        return
    await message.answer("Введите системный ID пользователя:", reply_markup=get_cancel_kb())
    await state.set_state(AdminProcess.add_admin_id)

@dp.message(AdminProcess.add_admin_id)
async def admin_add_finish(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ":
        await message.answer("Отмена.", reply_markup=get_admin_menu())
        await state.clear()
        return
    try:
        new_id = int(message.text)
        if new_id not in db.admins:
            db.admins.append(new_id)
            await message.answer(f"✅ Пользователь {new_id} теперь админ бота.", reply_markup=get_admin_menu())
        else:
            await message.answer("Он уже в списке.")
        await state.clear()
    except: await message.answer("Введите числовой ID.")

@dp.message(F.text == "🏗 СОЗДАТЬ СБОРНУЮ")
async def admin_team_create_1(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_OWNERS and message.from_user.id not in db.admins: return
    await message.answer("Введите название сборной (например, 🇺🇦 Украина):", reply_markup=get_cancel_kb())
    await state.set_state(AdminProcess.create_team_name)

@dp.message(AdminProcess.create_team_name)
async def admin_team_create_2(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ":
        await message.answer("Отмена.", reply_markup=get_admin_menu())
        await state.clear()
        return
    
    t_name = message.text.strip()
    db.teams[t_name] = {"owner": None, "coach": None, "players": [], "history": []}
    await message.answer(f"✅ Сборная **{t_name}** создана.", parse_mode="Markdown", reply_markup=get_admin_menu())
    await state.clear()

@dp.message(F.text == "🗑 УДАЛИТЬ СБОРНУЮ")
async def admin_team_del_1(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_OWNERS and message.from_user.id not in db.admins: return
    if not db.teams:
        await message.answer("Список пуст.")
        return
    
    kb = ReplyKeyboardBuilder()
    for name in db.teams.keys(): kb.button(text=name)
    kb.button(text="⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ")
    kb.adjust(2)
    
    await message.answer("Выберите сборную для удаления:", reply_markup=kb.as_markup(resize_keyboard=True))
    await state.set_state(AdminProcess.delete_team_confirm)

@dp.message(AdminProcess.delete_team_confirm)
async def admin_team_del_2(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ":
        await message.answer("Удаление отменено.", reply_markup=get_admin_menu())
        await state.clear()
        return
        
    if message.text in db.teams:
        del db.teams[message.text]
        await message.answer(f"🗑 Сборная {message.text} полностью удалена.", reply_markup=get_admin_menu())
        await state.clear()

@dp.message(F.text == "👑 НАЗНАЧИТЬ ГЛАВУ")
async def admin_set_boss_1(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_OWNERS and message.from_user.id not in db.admins: return
    
    kb = ReplyKeyboardBuilder()
    for name in db.teams.keys(): kb.button(text=name)
    kb.button(text="⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ")
    kb.adjust(2)
    
    await message.answer("Выберите сборную:", reply_markup=kb.as_markup(resize_keyboard=True))
    await state.set_state(AdminProcess.set_owner_team)

@dp.message(AdminProcess.set_owner_team)
async def admin_set_boss_2(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ":
        await message.answer("Отмена.", reply_markup=get_admin_menu())
        await state.clear()
        return
    await state.update_data(target_t=message.text)
    await message.answer(f"Введите Telegram ID владельца для {message.text}:", reply_markup=get_cancel_kb())
    await state.set_state(AdminProcess.set_owner_id)

@dp.message(AdminProcess.set_owner_id)
async def admin_set_boss_3(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ": return
    try:
        new_boss_id = int(message.text)
        data = await state.get_data()
        team = data["target_t"]
        
        db.teams[team]["owner"] = new_boss_id
        await message.answer(f"✅ Владелец {team} обновлен.", reply_markup=get_admin_menu())
        
        try:
            await bot.send_message(new_boss_id, f"👑 Вы назначены владельцем сборной {team}!", 
                                   reply_markup=get_main_menu(new_boss_id))
        except: pass
        await state.clear()
    except: await message.answer("ID должен быть цифровым.")

@dp.message(F.text == "📊 СТАТИСТИКА БОТА")
async def admin_global_stats(message: types.Message):
    if message.from_user.id not in MAIN_OWNERS and message.from_user.id not in db.admins: return
    
    msg = (
        "📊 **Глобальная статистика EEC**\n\n"
        f"👤 Зарегистрировано: {len(db.players)}\n"
        f"🏆 Сборных создано: {len(db.teams)}\n"
        f"📢 Опубликовано наборов: {db.stats['total_recruits']}\n"
        f"🔄 Смен ников: {db.stats['total_nicks']}\n"
        f"📉 Карьерных изменений: {db.stats['total_career_changes']}\n\n"
        f"🛰 Активный канал: {db.config['channel_name']}"
    )
    await message.answer(msg, parse_mode="Markdown")

# ==============================================================================
# --- УПРАВЛЕНИЕ КОМАНДОЙ (ЛИДЕРЫ) ---
# ==============================================================================

@dp.message(F.text == "📋 МОЯ СБОРНАЯ")
async def team_view_roster(message: types.Message):
    uid = message.from_user.id
    team_name = next((n for n, d in db.teams.items() if d["owner"] == uid or d["coach"] == uid), None)
    if not team_name: return
    
    t_data = db.teams[team_name]
    roster = "📋 **Состав команды:**\n\n"
    for i, pid in enumerate(t_data["players"], 1):
        p_nick = db.players.get(pid, {}).get("nick", "Unknown")
        roster += f"{i}. {p_nick} (ID: {pid})\n"
        
    if not t_data["players"]: roster += "В составе пока пусто."
    
    await message.answer(roster, parse_mode="Markdown")

@dp.message(F.text == "📢 ОБЪЯВИТЬ НАБОР")
async def team_recruit_init(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    team = next((n for n, d in db.teams.items() if d["owner"] == uid or d["coach"] == uid), None)
    
    if not team or not db.config["channel_id"]:
        await message.answer("❌ Канал не привязан или у вас нет прав.")
        return
        
    await message.answer(f"📢 **Набор в {team}**\nВведите текст объявления:", 
                         reply_markup=get_cancel_kb())
    await state.set_state(TeamManagement.recruit_desc)

@dp.message(TeamManagement.recruit_desc)
async def team_recruit_publish(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ":
        await message.answer("Отмена.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return

    uid = message.from_user.id
    team = next((n for n, d in db.teams.items() if d["owner"] == uid or d["coach"] == uid), None)
    db.stats["total_recruits"] += 1
    
    contact = f"@{message.from_user.username}" if message.from_user.username else f"ID: {uid}"
    post = (
        "⚡️ **ОТКРЫТ НАБОР В СБОРНУЮ!** ⚡️\n\n"
        f"🏆 Сборная: **{team}**\n"
        f"📝 Инфо: {message.text}\n"
        f"👤 Контакт: {contact}"
    )

    try:
        await bot.send_message(db.config["channel_id"], post, parse_mode="Markdown")
        await message.answer("✅ Набор опубликован в канале!", reply_markup=get_main_menu(uid))
    except:
        await message.answer("❌ Ошибка при отправке в канал.")
    await state.clear()

@dp.message(F.text == "👢 ИСКЛЮЧИТЬ")
async def team_kick_start(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    team_name = next((n for n, d in db.teams.items() if d["owner"] == uid or d["coach"] == uid), None)
    if not team_name: return
    
    t_data = db.teams[team_name]
    if not t_data["players"]:
        await message.answer("В команде нет игроков.")
        return
        
    kb = ReplyKeyboardBuilder()
    for pid in t_data["players"]:
        p_nick = db.players.get(pid, {}).get("nick", f"ID:{pid}")
        kb.button(text=f"Kick: {p_nick}", callback_data=f"kick_{pid}")
    
    kb.adjust(1)
    await message.answer("Выберите игрока для исключения из сборной:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("kick_"))
async def team_kick_execute(cb: types.CallbackQuery):
    target_pid = int(cb.data.replace("kick_", ""))
    uid = cb.from_user.id
    team_name = next((n for n, d in db.teams.items() if d["owner"] == uid or d["coach"] == uid), None)
    
    if target_pid in db.teams[team_name]["players"]:
        db.teams[team_name]["players"].remove(target_pid)
        await cb.message.edit_text(f"✅ Игрок (ID: {target_pid}) был исключен из состава.")
        try:
            await bot.send_message(target_pid, f"❗️ Вы были исключены из состава сборной {team_name}.")
        except: pass
    else:
        await cb.answer("Игрок уже не в составе.")

@dp.message(F.text == "➕ ПРИГЛАСИТЬ")
async def team_invite_1(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    team = next((n for n, d in db.teams.items() if d["owner"] == uid or d["coach"] == uid), None)
    if not team: return
    
    await message.answer("Введите @username игрока для приглашения:", reply_markup=get_cancel_kb())
    await state.set_state(TeamManagement.invite_tag)

@dp.message(TeamManagement.invite_tag)
async def team_invite_2(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ":
        await message.answer("Отмена.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return
        
    username = message.text.replace("@", "").lower().strip()
    target_id = db.user_index.get(username)
    
    if not target_id:
        await message.answer("❌ Этот игрок не зарегистрирован в боте.")
        return
        
    team = next((n for n, d in db.teams.items() if d["owner"] == message.from_user.id or d["coach"] == message.from_user.id), None)
    
    ikb = InlineKeyboardBuilder()
    ikb.button(text="✅ ПРИНЯТЬ", callback_data=f"accept_team_{team}")
    ikb.button(text="❌ ОТКАЗАТЬСЯ", callback_data="refuse_invite")
    
    try:
        await bot.send_message(target_id, f"🎮 Вас приглашают в основной состав сборной **{team}**!\n\nПринимаете вызов?", 
                               parse_mode="Markdown", reply_markup=ikb.as_markup())
        await message.answer(f"✅ Приглашение отправлено @{username}.", reply_markup=get_main_menu(message.from_user.id))
    except:
        await message.answer("❌ Личные сообщения игрока закрыты.")
    await state.clear()

@dp.callback_query(F.data.startswith("accept_team_"))
async def callback_accept_invite(cb: types.CallbackQuery):
    t_name = cb.data.replace("accept_team_", "")
    uid = cb.from_user.id
    
    if t_name in db.teams:
        if uid not in db.teams[t_name]["players"]:
            db.teams[t_name]["players"].append(uid)
            await cb.message.edit_text(f"🎉 Вы стали участником сборной {t_name}!")
            
            # Лог владельцу
            owner = db.teams[t_name]["owner"]
            if owner:
                p_nick = db.players.get(uid, {}).get("nick", "Игрок")
                try: await bot.send_message(owner, f"🔔 {p_nick} вступил в вашу сборную!")
                except: pass
        else:
            await cb.message.answer("Вы уже в этой команде.")

# ==============================================================================
# --- ОБЩАЯ РЕГИСТРАЦИЯ И СТАРТ ---
# ==============================================================================

@dp.message(Command("start"))
async def cmd_start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    
    # Индексируем username
    if message.from_user.username:
        db.user_index[message.from_user.username.lower()] = uid
    
    if uid in db.players:
        p = db.players[uid]
        await message.answer(
            f"👋 С возвращением, {p['nick']}!\n"
            f"Твой статус: {'🏃 Активен' if p['active'] else '🛑 Неактивен'}",
            reply_markup=get_main_menu(uid)
        )
    else:
        await message.answer("👋 Добро пожаловать в EEC Bot!\nПожалуйста, введите ваш игровой ник Roblox:")
        await state.set_state(Registration.nick)

@dp.message(Registration.nick)
async def reg_nick_catch(message: types.Message, state: FSMContext):
    nick = message.text.strip()
    if len(nick) < 2:
        await message.answer("Слишком короткий ник.")
        return
    await state.update_data(nick=nick)
    
    builder = InlineKeyboardBuilder()
    for country in db.countries:
        builder.button(text=country, callback_data=f"reg_country_{country}")
    builder.adjust(2)
    
    await message.answer("Выберите вашу страну/сборную:", reply_markup=builder.as_markup())
    await state.set_state(Registration.country)

@dp.callback_query(F.data.startswith("reg_country_"))
async def reg_country_catch(cb: types.CallbackQuery, state: FSMContext):
    country = cb.data.replace("reg_country_", "")
    data = await state.get_data()
    
    db.players[cb.from_user.id] = {
        "nick": data["nick"],
        "country": country,
        "active": True,
        "nick_cd": 0,
        "career_cd": 0
    }
    
    await cb.message.delete()
    await cb.message.answer(
        f"✅ Регистрация прошла успешно!\nНик: **{data['nick']}**\nСборная: **{country}**",
        parse_mode="Markdown",
        reply_markup=get_main_menu(cb.from_user.id)
    )
    await state.clear()

# ==============================================================================
# --- ПРОФИЛЬ И СЕРВИСЫ ---
# ==============================================================================

@dp.message(F.text == "👤 МОЙ ПРОФИЛЬ")
async def profile_show_handler(message: types.Message):
    uid = message.from_user.id
    if uid not in db.players: return
    
    p = db.players[uid]
    team = "Не состоит"
    for n, d in db.teams.items():
        if uid in d["players"]:
            team = n
            break
            
    msg = (
        "👤 **ВАШ ПРОФИЛЬ ИГРОКА**\n\n"
        f"🏷 Ник: `{p['nick']}`\n"
        f"🌍 Сборная: {p['country']}\n"
        f"🏆 Команда: {team}\n"
        f"📈 Статус: {'🏃 Активен' if p['active'] else '🛑 На пенсии'}\n"
        f"🆔 Telegram ID: `{uid}`"
    )
    await message.answer(msg, parse_mode="Markdown")

@dp.message(F.text == "✉️ СВЯЗЬ С ГЛАВОЙ")
async def contact_boss_init(message: types.Message, state: FSMContext):
    if not db.teams:
        await message.answer("Команд нет.")
        return
    kb = ReplyKeyboardBuilder()
    for name in db.teams.keys(): kb.button(text=name)
    kb.button(text="⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ")
    kb.adjust(2)
    await message.answer("Кому хотите написать?", reply_markup=kb.as_markup(resize_keyboard=True))
    await state.set_state(TeamManagement.contact_owner_team)

@dp.message(TeamManagement.contact_owner_team)
async def contact_boss_step2(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ":
        await message.answer("Отмена.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return
    await state.update_data(target=message.text)
    await message.answer(f"Введите сообщение для владельца {message.text}:", reply_markup=get_cancel_kb())
    await state.set_state(TeamManagement.contact_owner_text)

@dp.message(TeamManagement.contact_owner_text)
async def contact_boss_final(message: types.Message, state: FSMContext):
    if message.text == "⛔️ ОТМЕНИТЬ ДЕЙСТВИЕ": return
    data = await state.get_data()
    team = db.teams.get(data["target"])
    
    if team and team["owner"]:
        try:
            nick = db.players[message.from_user.id]["nick"]
            await bot.send_message(team["owner"], 
                                   f"📩 **Новое обращение!**\nОт: {nick}\n\nТекст: {message.text}", 
                                   parse_mode="Markdown")
            await message.answer("✅ Сообщение отправлено!", reply_markup=get_main_menu(message.from_user.id))
        except: await message.answer("Ошибка доставки.")
    await state.clear()

@dp.message(F.text == "🏠 ГЛАВНОЕ МЕНЮ")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Возврат в меню.", reply_markup=get_main_menu(message.from_user.id))

# ==============================================================================
# --- ЗАПУСК ЯДРА БОТА ---
# ==============================================================================

async def main_engine():
    print("--- SYSTEM STARTING ---")
    print(f"--- BOT TIME: {datetime.datetime.now()} ---")
    
    # Регистрация системных команд
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands([
        BotCommand(command="start", description="Запуск / Регистрация"),
        BotCommand(command="profile", description="Профиль"),
        BotCommand(command="admin", description="Админка (для админов)")
    ])
    
    # Старт поллинга
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main_engine())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical(f"CRITICAL SYSTEM ERROR: {e}")
