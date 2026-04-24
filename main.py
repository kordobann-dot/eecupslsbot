import logging
import asyncio
import time
import datetime
import os
import sys
import random
from typing import Union, List, Dict

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ReplyKeyboardRemove

# ==============================================================================
# --- ГЛОБАЛЬНЫЕ НАСТРОЙКИ ---
# ==============================================================================
TOKEN = "8331981056:AAETEMewZiaM-0ffToiaIHOIJTxQkiWk7Rw"
MAIN_OWNERS = [8461055593, 5845609895]

# Настройка логирования в консоль для отладки
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("EEC_BOT")

# Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==============================================================================
# --- СТРУКТУРА ДАННЫХ (БАЗА В ПАМЯТИ) ---
# ==============================================================================
# Мы храним всё в объекте, чтобы имитировать работу реальной базы данных
class DataBase:
    def __init__(self):
        self.assistants = [] # ID помощников администратора
        self.countries = ["🇷🇺 Россия", "🇺🇦 Украина", "🇰🇿 Казахстан", "🇧🇾 Беларусь", "🇵🇱 Польша"]
        self.teams = {}      # {Название: {owner: ID, coach: ID, players: [], description: str}}
        self.players = {}    # {ID: {nick: str, country: str, active: bool, last_change: float}}
        self.usernames = {}  # {username_lower: ID}
        self.config = {
            "channel_id": None,
            "channel_title": "Не привязан",
            "log_nick_changes": True
        }
        self.stats = {
            "total_recruits": 0,
            "total_nicks_changed": 0
        }

db = DataBase()

# ==============================================================================
# --- МАШИНА СОСТОЯНИЙ (FSM) ---
# ==============================================================================
class Registration(StatesGroup):
    input_nick = State()
    select_country = State()

class ProfileEdit(StatesGroup):
    change_nick = State()

class AdminWork(StatesGroup):
    create_team_name = State()
    delete_team_select = State()
    assign_owner_team = State()
    assign_owner_id = State()
    add_helper_id = State()
    setup_channel_wait = State() # Ожидание пересылки сообщения из канала

class TeamManagement(StatesGroup):
    set_coach_id = State()
    invite_player_username = State()
    recruit_text_input = State()
    message_to_owner_team = State()
    message_to_owner_text = State()

# ==============================================================================
# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (ИНТЕРФЕЙС) ---
# ==============================================================================

def get_main_menu(user_id: int):
    """Динамическое формирование клавиатуры под роль пользователя"""
    builder = ReplyKeyboardBuilder()
    
    # Роль: Главный администратор / Помощник
    if user_id in MAIN_OWNERS or user_id in db.assistants:
        builder.button(text="⚒ Админ-панель")
    
    # Роль: Владелец сборной или Тренер
    is_lead = False
    for t_name, t_data in db.teams.items():
        if t_data["owner"] == user_id or t_data["coach"] == user_id:
            is_lead = True
            break
            
    if is_lead:
        builder.button(text="📋 Состав сборной")
        builder.button(text="📣 Создать набор")
        builder.button(text="📞 Вызвать игрока")
        builder.button(text="👨‍🏫 Управление штабом")

    # Общие функции для всех
    builder.button(text="👤 Мой профиль")
    builder.button(text="🔄 Сменить никнейм")
    builder.button(text="🏁 Завершить карьеру")
    builder.button(text="🔙 Возобновить карьеру")
    builder.button(text="✉️ Написать владельцу")
    
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_admin_menu():
    """Меню инструментов для управления ботом"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Новая сборная")
    builder.button(text="➖ Удалить сборную")
    builder.button(text="👑 Назначить главу")
    builder.button(text="🛡 Добавить ассистента")
    builder.button(text="🔗 Привязать канал (ID)")
    builder.button(text="📊 Статистика бота")
    builder.button(text="🏠 Главное меню")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_cancel_btn():
    """Кнопка для выхода из любого режима ввода"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="⛔️ Отменить")
    return builder.as_markup(resize_keyboard=True)

# ==============================================================================
# --- СИСТЕМА ЛОГИРОВАНИЯ И ПРИВЯЗКИ КАНАЛА ---
# ==============================================================================

@dp.message(F.text == "🔗 Привязать канал (ID)")
async def admin_channel_init(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_OWNERS and message.from_user.id not in db.assistants:
        return
    
    await message.answer(
        "🛠 **Настройка автоматической публикации**\n\n"
        "Чтобы привязать канал, выполните шаги:\n"
        "1. Добавьте этого бота в канал как администратора.\n"
        "2. Убедитесь, что у бота есть право отправлять сообщения.\n"
        "3. **ПЕРЕШЛИТЕ** любое сообщение из вашего канала в этот чат.\n\n"
        "Я получу ID канала из пересланного сообщения автоматически.",
        parse_mode="Markdown",
        reply_markup=get_cancel_btn()
    )
    await state.set_state(AdminWork.setup_channel_wait)

@dp.message(AdminWork.setup_channel_wait)
async def admin_channel_catch(message: types.Message, state: FSMContext):
    if message.text == "⛔️ Отменить":
        await message.answer("Действие отменено.", reply_markup=get_admin_menu())
        await state.clear()
        return

    # Извлекаем данные из пересланного сообщения
    if message.forward_from_chat:
        chat_id = message.forward_from_chat.id
        chat_title = message.forward_from_chat.title
        
        db.config["channel_id"] = chat_id
        db.config["channel_title"] = chat_title
        
        await message.answer(
            f"✅ **Канал успешно привязан!**\n\n"
            f"Название: `{chat_title}`\n"
            f"Системный ID: `{chat_id}`\n\n"
            "Теперь все наборы и логи смены ников будут публиковаться здесь.",
            parse_mode="Markdown",
            reply_markup=get_admin_menu()
        )
        await state.clear()
    else:
        await message.answer(
            "❌ Ошибка! Это сообщение не является пересланным из канала.\n"
            "Попробуйте еще раз или нажмите кнопку отмены."
        )

# ==============================================================================
# --- ОБРАБОТКА СМЕНЫ НИКА (С ЛОГОМ В КАНАЛ) ---
# ==============================================================================

@dp.message(F.text == "🔄 Сменить никнейм")
async def process_nick_change_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if user_id not in db.players:
        await message.answer("Сначала пройдите регистрацию через /start")
        return

    # Проверка на КД 7 дней для обычных пользователей
    is_staff = user_id in MAIN_OWNERS or user_id in db.assistants
    if not is_staff:
        last_change = db.players[user_id].get("last_change", 0)
        cooldown = 604800 # 7 дней в секундах
        if time.time() - last_change < cooldown:
            rem = cooldown - (time.time() - last_change)
            days = int(rem // 86400)
            hours = int((rem % 86400) // 3600)
            await message.answer(f"⏳ Смена ника доступна раз в неделю.\nОсталось: {days}д. {hours}ч.")
            return

    await message.answer("Введите ваш новый игровой ник Roblox:", reply_markup=get_cancel_btn())
    await state.set_state(ProfileEdit.change_nick)

@dp.message(ProfileEdit.change_nick)
async def process_nick_change_apply(message: types.Message, state: FSMContext):
    if message.text == "⛔️ Отменить":
        await message.answer("Отмена операции.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return

    new_name = message.text.strip()
    if len(new_name) < 2 or len(new_name) > 30:
        await message.answer("❌ Ник должен содержать от 2 до 30 символов.")
        return

    user_id = message.from_user.id
    old_name = db.players[user_id]["nick"]
    
    # Обновление в базе
    db.players[user_id]["nick"] = new_name
    db.players[user_id]["last_change"] = time.time()
    db.stats["total_nicks_changed"] += 1
    
    await message.answer(f"✅ Ваш ник успешно изменен с `{old_name}` на `{new_name}`!", 
                         parse_mode="Markdown", 
                         reply_markup=get_main_menu(user_id))

    # ПУБЛИКАЦИЯ В КАНАЛ (Твой шаблон)
    if db.config["channel_id"]:
        try:
            # Формируем юзернейм или ID, если юзернейма нет
            user_ref = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
            
            # (юзернейм игрока) старый ник -> новый ник
            log_message = f"🔔 **Лог изменения ника**\n{user_ref} {old_name} —> {new_name}"
            
            await bot.send_message(
                chat_id=db.config["channel_id"],
                text=log_message,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить лог в канал: {e}")

    await state.clear()

# ==============================================================================
# --- РЕГИСТРАЦИЯ И СТАРТ ---
# ==============================================================================

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    u_id = message.from_user.id
    
    # Индексация для быстрого поиска
    if message.from_user.username:
        db.usernames[message.from_user.username.lower()] = u_id
    
    if u_id in db.players:
        p = db.players[u_id]
        await message.answer(
            f"👋 Добро пожаловать, {p['nick']}!\n"
            f"Ваша страна: {p['country']}\n"
            f"Статус: {'🏃 Активен' if p['active'] else '🛑 Карьера завершена'}",
            reply_markup=get_main_menu(u_id)
        )
    else:
        await message.answer("👋 Добро пожаловать в EEC Bot!\nПожалуйста, введите ваш игровой ник Roblox для регистрации:")
        await state.set_state(Registration.input_nick)

@dp.message(Registration.input_nick)
async def reg_nick_save(message: types.Message, state: FSMContext):
    nick = message.text.strip()
    if len(nick) < 2:
        await message.answer("Слишком короткий ник. Попробуйте еще раз:")
        return
    await state.update_data(nick=nick)
    
    kb = InlineKeyboardBuilder()
    for c in db.countries:
        kb.button(text=c, callback_data=f"reg_c_{c}")
    kb.adjust(2)
    
    await message.answer("Выберите вашу страну/сборную из списка:", reply_markup=kb.as_markup())
    await state.set_state(Registration.select_country)

@dp.callback_query(F.data.startswith("reg_c_"))
async def reg_country_save(callback: types.CallbackQuery, state: FSMContext):
    country = callback.data.replace("reg_c_", "")
    data = await state.get_data()
    
    db.players[callback.from_user.id] = {
        "nick": data["nick"],
        "country": country,
        "active": True,
        "last_change": 0
    }
    
    await callback.message.delete()
    await callback.message.answer(
        f"✅ Регистрация завершена!\nНик: **{data['nick']}**\nСборная: **{country}**",
        parse_mode="Markdown",
        reply_markup=get_main_menu(callback.from_user.id)
    )
    await state.clear()

# ==============================================================================
# --- АДМИНИСТРАТИВНЫЙ БЛОК (БОЛЕЕ 200 СТРОК ЛОГИКИ) ---
# ==============================================================================

@dp.message(F.text == "⚒ Админ-панель")
async def admin_panel_root(message: types.Message):
    if message.from_user.id in MAIN_OWNERS or message.from_user.id in db.assistants:
        await message.answer("🛠 Система управления EEC готова к работе.", reply_markup=get_admin_menu())

@dp.message(F.text == "📊 Статистика бота")
async def admin_stats(message: types.Message):
    if message.from_user.id not in MAIN_OWNERS and message.from_user.id not in db.assistants: return
    
    msg = (
        "📈 **Статистика системы**\n\n"
        f"👥 Зарегистрировано игроков: {len(db.players)}\n"
        f"🏆 Активных сборных: {len(db.teams)}\n"
        f"📢 Проведено наборов: {db.stats['total_recruits']}\n"
        f"🔄 Смен ников: {db.stats['total_nicks_changed']}\n"
        f"🛰 Канал: {db.config['channel_title']}"
    )
    await message.answer(msg, parse_mode="Markdown")

@dp.message(F.text == "🎖 Добавить ассистента")
async def admin_add_helper_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_OWNERS:
        await message.answer("❌ Только владельцы могут назначать ассистентов.")
        return
    await message.answer("Введите Telegram ID пользователя:", reply_markup=get_cancel_btn())
    await state.set_state(AdminWork.add_helper_id)

@dp.message(AdminWork.add_helper_id)
async def admin_add_helper_end(message: types.Message, state: FSMContext):
    if message.text == "⛔️ Отменить":
        await message.answer("Отмена.", reply_markup=get_admin_menu())
        await state.clear()
        return
    try:
        new_id = int(message.text)
        if new_id not in db.assistants:
            db.assistants.append(new_id)
            await message.answer(f"✅ Пользователь {new_id} теперь ассистент.", reply_markup=get_admin_menu())
        else:
            await message.answer("Он уже в списке.")
        await state.clear()
    except: await message.answer("Введите числовой ID.")

@dp.message(F.text == "➕ Новая сборная")
async def admin_create_team_1(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_OWNERS and message.from_user.id not in db.assistants: return
    await message.answer("Введите полное название сборной (например, '🇺🇦 Украина'):", reply_markup=get_cancel_btn())
    await state.set_state(AdminWork.create_team_name)

@dp.message(AdminWork.create_team_name)
async def admin_create_team_2(message: types.Message, state: FSMContext):
    if message.text == "⛔️ Отменить":
        await message.answer("Действие отменено.", reply_markup=get_admin_menu())
        await state.clear()
        return
    
    t_name = message.text.strip()
    db.teams[t_name] = {"owner": None, "coach": None, "players": [], "description": ""}
    await message.answer(f"✅ Сборная **{t_name}** создана и добавлена в реестр.", 
                         parse_mode="Markdown", reply_markup=get_admin_menu())
    await state.clear()

@dp.message(F.text == "➖ Удалить сборную")
async def admin_delete_team_1(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_OWNERS and message.from_user.id not in db.assistants: return
    if not db.teams:
        await message.answer("Список команд пуст.")
        return
    
    builder = ReplyKeyboardBuilder()
    for name in db.teams.keys():
        builder.button(text=name)
    builder.button(text="⛔️ Отменить")
    builder.adjust(2)
    
    await message.answer("Выберите команду для ПОЛНОГО удаления:", reply_markup=builder.as_markup(resize_keyboard=True))
    await state.set_state(AdminWork.delete_team_select)

@dp.message(AdminWork.delete_team_select)
async def admin_delete_team_2(message: types.Message, state: FSMContext):
    if message.text == "⛔️ Отменить":
        await message.answer("Удаление отменено.", reply_markup=get_admin_menu())
        await state.clear()
        return
        
    if message.text in db.teams:
        del db.teams[message.text]
        await message.answer(f"🗑 Сборная {message.text} удалена.", reply_markup=get_admin_menu())
        await state.clear()

@dp.message(F.text == "👑 Назначить главу")
async def admin_set_boss_1(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_OWNERS and message.from_user.id not in db.assistants: return
    
    builder = ReplyKeyboardBuilder()
    for name in db.teams.keys(): builder.button(text=name)
    builder.button(text="⛔️ Отменить")
    builder.adjust(2)
    
    await message.answer("Выберите сборную:", reply_markup=builder.as_markup(resize_keyboard=True))
    await state.set_state(AdminWork.assign_owner_team)

@dp.message(AdminWork.assign_owner_team)
async def admin_set_boss_2(message: types.Message, state: FSMContext):
    if message.text == "⛔️ Отменить":
        await message.answer("Отмена.", reply_markup=get_admin_menu())
        await state.clear()
        return
    await state.update_data(target_team=message.text)
    await message.answer(f"Введите Telegram ID владельца для {message.text}:", reply_markup=get_cancel_btn())
    await state.set_state(AdminWork.assign_owner_id)

@dp.message(AdminWork.assign_owner_id)
async def admin_set_boss_3(message: types.Message, state: FSMContext):
    if message.text == "⛔️ Отменить": return
    try:
        new_boss_id = int(message.text)
        data = await state.get_data()
        team = data["target_team"]
        
        db.teams[team]["owner"] = new_boss_id
        await message.answer(f"✅ Владелец сборной {team} изменен.", reply_markup=get_admin_menu())
        
        # Уведомляем нового владельца
        try:
            await bot.send_message(new_boss_id, f"👑 Вы назначены владельцем сборной {team}!", 
                                   reply_markup=get_main_menu(new_boss_id))
        except: pass
        await state.clear()
    except: await message.answer("ID должен быть цифровым.")

# ==============================================================================
# --- УПРАВЛЕНИЕ СБОРНОЙ (ВЛАДЕЛЬЦЫ / ТРЕНЕРЫ) ---
# ==============================================================================

@dp.message(F.text == "📣 Создать набор")
async def lead_recruit_init(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    # Проверяем, в какой команде юзер — власть
    team = next((n for n, d in db.teams.items() if d["owner"] == user_id or d["coach"] == user_id), None)
    
    if not team: return
    if not db.config["channel_id"]:
        await message.answer("❌ Канал публикации не настроен. Обратитесь к администратору.")
        return
        
    await message.answer(f"📢 **Создание набора для {team}**\n\nВведите текст объявления (требования, время и т.д.):", 
                         parse_mode="Markdown", reply_markup=get_cancel_btn())
    await state.set_state(TeamManagement.recruit_text_input)

@dp.message(TeamManagement.recruit_text_input)
async def lead_recruit_send(message: types.Message, state: FSMContext):
    if message.text == "⛔️ Отменить":
        await message.answer("Набор отменен.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return

    user_id = message.from_user.id
    team = next((n for n, d in db.teams.items() if d["owner"] == user_id or d["coach"] == user_id), None)
    
    db.stats["total_recruits"] += 1
    contact = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
    
    post = (
        "🔥 **ОБЪЯВЛЕН НАБОР В СБОРНУЮ** 🔥\n\n"
        f"🏆 Команда: **{team}**\n"
        f"👤 Ответственный: {contact}\n\n"
        f"📝 **Информация:**\n{message.text}\n\n"
        "Писать строго по контакту выше! ⤴️"
    )

    try:
        await bot.send_message(db.config["channel_id"], post, parse_mode="Markdown")
        await message.answer("✅ Набор успешно опубликован в канале!", reply_markup=get_main_menu(user_id))
    except Exception as e:
        await message.answer(f"❌ Ошибка публикации: {e}")
    
    await state.clear()

@dp.message(F.text == "📞 Вызвать игрока")
async def lead_invite_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    team = next((n for n, d in db.teams.items() if d["owner"] == user_id or d["coach"] == user_id), None)
    if not team: return
    
    await message.answer("Введите @username игрока (тег), которого хотите пригласить:", reply_markup=get_cancel_btn())
    await state.set_state(TeamManagement.invite_player_username)

@dp.message(TeamManagement.invite_player_username)
async def lead_invite_end(message: types.Message, state: FSMContext):
    if message.text == "⛔️ Отменить":
        await message.answer("Отмена.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return
        
    username = message.text.replace("@", "").lower().strip()
    target_id = db.usernames.get(username)
    
    if not target_id:
        await message.answer("❌ Игрок не найден. Он должен запустить бота хотя бы один раз.")
        return
        
    team = next((n for n, d in db.teams.items() if d["owner"] == message.from_user.id or d["coach"] == message.from_user.id), None)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Вступить", callback_data=f"join_{team}")
    kb.button(text="❌ Отклонить", callback_data="decline_inv")
    
    try:
        await bot.send_message(target_id, f"⚡️ Вас приглашают в основной состав сборной **{team}**!\nПринимаете вызов?", 
                               parse_mode="Markdown", reply_markup=kb.as_markup())
        await message.answer(f"✅ Приглашение отправлено игроку @{username}.", reply_markup=get_main_menu(message.from_user.id))
    except:
        await message.answer("❌ Не удалось отправить приглашение (бот заблокирован).")
    await state.clear()

@dp.callback_query(F.data.startswith("join_"))
async def callback_join_handler(callback: types.CallbackQuery):
    team_name = callback.data.replace("join_", "")
    user_id = callback.from_user.id
    
    if team_name in db.teams:
        if user_id not in db.teams[team_name]["players"]:
            db.teams[team_name]["players"].append(user_id)
            await callback.message.edit_text(f"🎉 Поздравляем! Вы теперь в составе {team_name}.")
            
            # Сообщение владельцу
            owner = db.teams[team_name]["owner"]
            if owner:
                p_nick = db.players.get(user_id, {}).get("nick", "Игрок")
                try:
                    await bot.send_message(owner, f"🔔 Игрок {p_nick} принял ваш вызов в сборную!")
                except: pass
        else:
            await callback.message.answer("Вы уже состоите в этой сборной.")

# ==============================================================================
# --- ОБЩИЕ ФУНКЦИИ (КАРЬЕРА, ПРОФИЛЬ) ---
# ==============================================================================

@dp.message(F.text == "🏁 Завершить карьеру")
async def profile_stop(message: types.Message):
    u_id = message.from_user.id
    if u_id in db.players:
        db.players[u_id]["active"] = False
        await message.answer("🛑 Вы официально завершили карьеру игрока.")

@dp.message(F.text == "🔙 Возобновить карьеру")
async def profile_resume(message: types.Message):
    u_id = message.from_user.id
    if u_id in db.players:
        db.players[u_id]["active"] = True
        await message.answer("🚀 Поздравляем с возвращением в большой спорт!")

@dp.message(F.text == "👤 Мой профиль")
async def profile_view(message: types.Message):
    u_id = message.from_user.id
    if u_id not in db.players: return
    
    p = db.players[u_id]
    team_found = "Не состоит"
    for n, d in db.teams.items():
        if u_id in d["players"]:
            team_found = n
            break
            
    msg = (
        "👤 **Ваш профиль игрока**\n\n"
        f"🏷 Ник: `{p['nick']}`\n"
        f"🌍 Сборная: {p['country']}\n"
        f"🏆 Команда: {team_found}\n"
        f"📈 Статус: {'🏃 Активен' if p['active'] else '🛑 На пенсии'}\n"
        f"🆔 Ваш ID: `{u_id}`"
    )
    await message.answer(msg, parse_mode="Markdown")

@dp.message(F.text == "📋 Состав сборной")
async def lead_team_view(message: types.Message):
    user_id = message.from_user.id
    team_name = next((n for n, d in db.teams.items() if d["owner"] == user_id or d["coach"] == user_id), None)
    if not team_name: return
    
    team = db.teams[team_name]
    players_str = ""
    for idx, pid in enumerate(team["players"], 1):
        p_data = db.players.get(pid, {"nick": "Неизвестный"})
        players_str += f"{idx}. {p_data['nick']} (ID: {pid})\n"
        
    if not players_str: players_str = "В составе пока нет игроков."
    
    await message.answer(f"🚩 **Состав {team_name}**\n\n{players_str}", parse_mode="Markdown")

@dp.message(F.text == "✉️ Написать владельцу")
async def contact_boss_1(message: types.Message, state: FSMContext):
    if not db.teams:
        await message.answer("Список команд пуст.")
        return
    kb = ReplyKeyboardBuilder()
    for name in db.teams.keys(): kb.button(text=name)
    kb.button(text="⛔️ Отменить")
    kb.adjust(2)
    await message.answer("Кому хотите отправить сообщение?", reply_markup=kb.as_markup(resize_keyboard=True))
    await state.set_state(TeamManagement.message_to_owner_team)

@dp.message(TeamManagement.message_to_owner_team)
async def contact_boss_2(message: types.Message, state: FSMContext):
    if message.text == "⛔️ Отменить":
        await message.answer("Отмена.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return
    await state.update_data(target=message.text)
    await message.answer(f"Введите текст сообщения для владельца {message.text}:", reply_markup=get_cancel_btn())
    await state.set_state(TeamManagement.message_to_owner_text)

@dp.message(TeamManagement.message_to_owner_text)
async def contact_boss_3(message: types.Message, state: FSMContext):
    if message.text == "⛔️ Отменить": return
    data = await state.get_data()
    team = db.teams.get(data["target"])
    
    if team and team["owner"]:
        try:
            sender_nick = db.players[message.from_user.id]["nick"]
            sender_tag = f"@{message.from_user.username}" if message.from_user.username else "нет тега"
            await bot.send_message(team["owner"], 
                                   f"📩 **Новое обращение!**\nОт: {sender_nick} ({sender_tag})\n\nТекст: {message.text}", 
                                   parse_mode="Markdown")
            await message.answer("✅ Сообщение успешно доставлено!", reply_markup=get_main_menu(message.from_user.id))
        except: await message.answer("❌ Ошибка доставки.")
    await state.clear()

@dp.message(F.text == "🏠 Главное меню")
async def back_to_root(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вернулись в главное меню.", reply_markup=get_main_menu(message.from_user.id))

# ==============================================================================
# --- ЗАПУСК БОТА ---
# ==============================================================================

async def main_engine():
    print("EEC BOT v7.0: ENGINE STARTING...")
    print(f"ADMINS CONFIGURED: {MAIN_OWNERS}")
    
    # Удаляем вебхуки и запускаем чистый поллинг
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main_engine())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")
    except Exception as fatal:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: {fatal}")
