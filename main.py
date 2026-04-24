import logging
import asyncio
import time
import datetime
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# --- ПАРАМЕТРЫ КОНФИГУРАЦИИ ---
# Вставь сюда свой актуальный токен
BOT_TOKEN = "8331981056:AAETEMewZiaM-0ffToiaIHOIJTxQkiWk7Rw"

# Список главных администраторов (Владельцы системы)
PRIMARY_ADMINS = [8461055593, 5845609895]

# Настройка детализированного логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- СТРУКТУРА ХРАНИЛИЩА (DATABASE MOCKUP) ---
# Все данные хранятся в оперативной памяти (в словаре)
db_store = {
    "assistants": [],         # Список ID назначенных админов
    "available_countries": [
        "🇷🇺 Россия", "🇺🇦 Украина", "🇰🇿 Казахстан", 
        "🇧🇾 Беларусь", "🇵🇱 Польша", "🇲🇩 Молдова"
    ],
    "national_teams": {},     # Сборные: {"Название": {"owner": ID, "coach": ID, "roster": []}}
    "user_profiles": {},      # Профили: {user_id: {"nick": str, "country": str, "active": bool, "cd": float}}
    "username_map": {},       # Карта @тег -> user_id
    "active_channel_id": None # ID канала для наборов и логов ников
}

# --- МАШИНА СОСТОЯНИЙ (FSM) ---
class RegistrationStates(StatesGroup):
    input_nickname = State()
    select_country = State()

class ProfileStates(StatesGroup):
    change_nickname = State()

class AdministrativeStates(StatesGroup):
    create_team = State()
    delete_team = State()
    assign_owner_team = State()
    assign_owner_id = State()
    assign_assistant_id = State()
    set_custom_channel = State()

class ManagementStates(StatesGroup):
    hire_coach_id = State()
    send_invite_tag = State()
    draft_recruit_post = State()
    direct_message_team = State()
    direct_message_text = State()

# --- ГЕНЕРАЦИЯ ИНТЕРФЕЙСА (КЛАВИАТУРЫ) ---

def main_dashboard_keyboard(user_id):
    """Генерация главного меню на основе ролей пользователя"""
    kb = ReplyKeyboardBuilder()
    
    # Права супер-админа или ассистента
    is_admin = user_id in PRIMARY_ADMINS or user_id in db_store["assistants"]
    if is_admin:
        kb.button(text="⚙️ Админ панель")
    
    # Права управления (Владелец или Тренер)
    is_boss = any(t.get("owner") == user_id for t in db_store["national_teams"].values())
    is_trainer = any(t.get("coach") == user_id for t in db_store["national_teams"].values())
    
    if is_boss or is_trainer:
        kb.button(text="📋 Состав сборной")
        kb.button(text="📢 Набор в команду")
        kb.button(text="📞 Вызов игрока")
        if is_boss:
            kb.button(text="🧠 Назначить Тренера")

    # Кнопки для всех пользователей
    kb.button(text="📝 Сменить ник")
    kb.button(text="🏃 Завершить карьеру")
    kb.button(text="🔙 Возобновить карьеру")
    kb.button(text="✉️ Написать владельцу")
    
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

def admin_panel_keyboard():
    """Меню инструментов администратора"""
    kb = ReplyKeyboardBuilder()
    kb.button(text="➕ Создать сборную")
    kb.button(text="❌ Удалить сборную")
    kb.button(text="👑 Назначить владельца")
    kb.button(text="🛡 Добавить ассистента")
    kb.button(text="📡 Настроить канал")
    kb.button(text="🔙 В главное меню")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

def cancel_action_keyboard():
    """Универсальная кнопка отмены"""
    kb = ReplyKeyboardBuilder()
    kb.button(text="⛔ Отменить действие")
    return kb.as_markup(resize_keyboard=True)

# --- ОБРАБОТКА СОБЫТИЙ КАНАЛА ---

@dp.my_chat_member()
async def auto_detect_channel(event: types.ChatMemberUpdated):
    """
    Автоматическое определение канала при добавлении бота.
    Бот запоминает последний канал, куда его добавили как админа.
    """
    if event.new_chat_member.status in ["administrator", "member"]:
        db_store["active_channel_id"] = event.chat.id
        logger.info(f"Обнаружен канал: {event.chat.title} (ID: {event.chat.id})")
        
        # Если есть права, отправляем приветствие в канал
        try:
            await bot.send_message(event.chat.id, "🤖 Бот Eastern European Cup успешно подключен!")
        except:
            pass

# --- БЛОК РЕГИСТРАЦИИ ПОЛЬЗОВАТЕЛЕЙ ---

@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    """Начало работы с ботом и проверка регистрации"""
    await state.clear()
    user_id = message.from_user.id
    
    # Индексация для поиска по тегам
    if message.from_user.username:
        db_store["username_map"][message.from_user.username.lower()] = user_id
        
    if user_id in db_store["user_profiles"]:
        profile = db_store["user_profiles"][user_id]
        welcome_text = (
            f"✅ Вы авторизованы!\n\n"
            f"Ник: {profile['nick']}\n"
            f"Страна: {profile['country']}\n"
            f"Карьера: {'Активна' if profile['active'] else 'Завершена'}"
        )
        await message.answer(welcome_text, reply_markup=main_dashboard_keyboard(user_id))
    else:
        await message.answer(
            "👋 Приветствуем в системе Eastern European Cup!\n"
            "Для участия необходимо пройти регистрацию.\n\n"
            "Введите ваш официальный ник Roblox:"
        )
        await state.set_state(RegistrationStates.input_nickname)

@dp.message(RegistrationStates.input_nickname)
async def handle_reg_nick(message: types.Message, state: FSMContext):
    nickname = message.text.strip()
    if len(nickname) < 3 or len(nickname) > 24:
        await message.answer("❌ Некорректный ник. Допускается от 3 до 24 символов.")
        return
    
    await state.update_data(chosen_nick=nickname)
    
    # Клавиатура выбора страны
    builder = InlineKeyboardBuilder()
    for country in db_store["available_countries"]:
        builder.button(text=country, callback_data=f"sel_c_{country}")
    builder.adjust(2)
    
    await message.answer("🌍 Теперь выберите сборную (страну), которую вы представляете:", 
                         reply_markup=builder.as_markup())
    await state.set_state(RegistrationStates.select_country)

@dp.callback_query(F.data.startswith("sel_c_"))
async def handle_reg_country(callback: types.CallbackQuery, state: FSMContext):
    country_name = callback.data.replace("sel_c_", "")
    user_data = await state.get_data()
    
    db_store["user_profiles"][callback.from_user.id] = {
        "nick": user_data["chosen_nick"],
        "country": country_name,
        "active": True,
        "last_nick_change": 0
    }
    
    await callback.message.delete()
    await callback.message.answer(
        f"🎊 Регистрация завершена!\n\nНик: {user_data['chosen_nick']}\nСборная: {country_name}",
        reply_markup=main_dashboard_keyboard(callback.from_user.id)
    )
    await state.clear()

# --- ФУНКЦИОНАЛ СМЕНЫ НИКА (С ЛОГАМИ) ---

@dp.message(F.text == "📝 Сменить ник")
async def change_nick_init(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    
    # Проверка на КД (только для простых игроков)
    is_staff = uid in PRIMARY_ADMINS or uid in db_store["assistants"]
    if not is_staff:
        last_change = db_store["user_profiles"][uid].get("last_nick_change", 0)
        current_time = time.time()
        # 604800 секунд = 7 дней
        if current_time - last_change < 604800:
            diff = 604800 - (current_time - last_change)
            days = int(diff // 86400)
            hours = int((diff % 86400) // 3600)
            await message.answer(f"⏳ Слишком часто! Вы сможете сменить ник через: {days} д. {hours} ч.")
            return

    await message.answer("Введите ваш новый игровой ник Roblox:", reply_markup=cancel_action_keyboard())
    await state.set_state(ProfileStates.change_nickname)

@dp.message(ProfileStates.change_nickname)
async def change_nick_apply(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие":
        await message.answer("Изменение ника отменено.", reply_markup=main_dashboard_keyboard(message.from_user.id))
        await state.clear()
        return

    new_nickname = message.text.strip()
    if len(new_nickname) < 3:
        await message.answer("❌ Слишком короткий ник.")
        return

    user_id = message.from_user.id
    old_nickname = db_store["user_profiles"][user_id]["nick"]
    
    # Обновляем данные
    db_store["user_profiles"][user_id]["nick"] = new_nickname
    db_store["user_profiles"][user_id]["last_nick_change"] = time.time()
    
    await message.answer(f"✅ Ваш ник успешно обновлен: {new_nickname}", 
                         reply_markup=main_dashboard_keyboard(user_id))

    # ПУБЛИКАЦИЯ В КАНАЛ ПО ШАБЛОНУ: (юзернейм) старый ник -> новый ник
    if db_store["active_channel_id"]:
        try:
            tag = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
            log_text = f"📝 **Смена ника**\n{tag} {old_nickname} —> {new_nickname}"
            await bot.send_message(db_store["active_channel_id"], log_text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Не удалось отправить лог ника: {e}")
    
    await state.clear()

# --- АДМИНИСТРАТИВНЫЙ МОДУЛЬ ---

@dp.message(F.text == "⚙️ Админ панель")
async def show_admin_hub(message: types.Message):
    if message.from_user.id in PRIMARY_ADMINS or message.from_user.id in db_store["assistants"]:
        await message.answer("🛠 Доступ разрешен. Выберите инструмент управления:", 
                             reply_markup=admin_panel_keyboard())
    else:
        await message.answer("⛔ Ошибка доступа.")

@dp.message(F.text == "🛡 Добавить ассистента")
async def add_assistant_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in PRIMARY_ADMINS:
        await message.answer("❌ Только главные владельцы могут назначать ассистентов.")
        return
    await message.answer("Отправьте Telegram ID пользователя:", reply_markup=cancel_action_keyboard())
    await state.set_state(AdministrativeStates.assign_assistant_id)

@dp.message(AdministrativeStates.assign_assistant_id)
async def add_assistant_end(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие":
        await message.answer("Отмена.", reply_markup=admin_panel_keyboard())
        await state.clear()
        return
    
    try:
        new_id = int(message.text)
        if new_id not in db_store["assistants"]:
            db_store["assistants"].append(new_id)
            await message.answer(f"✅ Пользователь {new_id} назначен ассистентом.", reply_markup=admin_panel_keyboard())
            try:
                await bot.send_message(new_id, "⚙️ Вам выдали права ассистента администратора!", 
                                       reply_markup=main_dashboard_keyboard(new_id))
            except: pass
        else:
            await message.answer("Он уже в списке.")
        await state.clear()
    except:
        await message.answer("Введите корректный цифровой ID.")

@dp.message(F.text == "📡 Настроить канал")
async def manual_set_channel(message: types.Message, state: FSMContext):
    if message.from_user.id not in PRIMARY_ADMINS and message.from_user.id not in db_store["assistants"]: return
    await message.answer(
        "Вы можете вручную привязать канал.\n"
        "Пришлите его @username (например, @my_channel_name):", 
        reply_markup=cancel_action_keyboard()
    )
    await state.set_state(AdministrativeStates.set_custom_channel)

@dp.message(AdministrativeStates.set_custom_channel)
async def manual_set_channel_finish(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие":
        await message.answer("Отмена.", reply_markup=admin_panel_keyboard())
        await state.clear()
        return
    
    ch_tag = message.text.strip()
    if not ch_tag.startswith("@"):
        ch_tag = f"@{ch_tag}"
    
    db_store["active_channel_id"] = ch_tag
    await message.answer(f"✅ Канал привязан: {ch_tag}", reply_markup=admin_panel_keyboard())
    await state.clear()

@dp.message(F.text == "➕ Создать сборную")
async def team_create_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in PRIMARY_ADMINS and message.from_user.id not in db_store["assistants"]: return
    await message.answer("Введите название сборной (например, '🇷🇺 Россия'):", reply_markup=cancel_action_keyboard())
    await state.set_state(AdministrativeStates.create_team)

@dp.message(AdministrativeStates.create_team)
async def team_create_finish(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие":
        await message.answer("Отмена.", reply_markup=admin_panel_keyboard())
        await state.clear()
        return
    
    name = message.text.strip()
    db_store["national_teams"][name] = {"owner": None, "coach": None, "roster": []}
    await message.answer(f"✅ Сборная '{name}' создана!", reply_markup=admin_panel_keyboard())
    await state.clear()

@dp.message(F.text == "❌ Удалить сборную")
async def team_delete_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in PRIMARY_ADMINS and message.from_user.id not in db_store["assistants"]: return
    if not db_store["national_teams"]:
        await message.answer("Список пуст.")
        return
    
    kb = ReplyKeyboardBuilder()
    for t_name in db_store["national_teams"].keys():
        kb.button(text=t_name)
    kb.button(text="⛔ Отменить действие")
    kb.adjust(2)
    
    await message.answer("Выберите сборную для удаления:", reply_markup=kb.as_markup(resize_keyboard=True))
    await state.set_state(AdministrativeStates.delete_team)

@dp.message(AdministrativeStates.delete_team)
async def team_delete_finish(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие":
        await message.answer("Удаление отменено.", reply_markup=admin_panel_keyboard())
        await state.clear()
        return
    
    if message.text in db_store["national_teams"]:
        del db_store["national_teams"][message.text]
        await message.answer(f"✅ Сборная {message.text} удалена.", reply_markup=admin_panel_keyboard())
        await state.clear()

@dp.message(F.text == "👑 Назначить владельца")
async def owner_assign_step1(message: types.Message, state: FSMContext):
    if message.from_user.id not in PRIMARY_ADMINS and message.from_user.id not in db_store["assistants"]: return
    
    kb = ReplyKeyboardBuilder()
    for t in db_store["national_teams"].keys():
        kb.button(text=t)
    kb.button(text="⛔ Отменить действие")
    kb.adjust(2)
    
    await message.answer("Для какой сборной назначить владельца?", reply_markup=kb.as_markup(resize_keyboard=True))
    await state.set_state(AdministrativeStates.assign_owner_team)

@dp.message(AdministrativeStates.assign_owner_team)
async def owner_assign_step2(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие":
        await message.answer("Отмена.", reply_markup=admin_panel_keyboard())
        await state.clear()
        return
    
    await state.update_data(target_team_name=message.text)
    await message.answer(f"Введите Telegram ID будущего владельца {message.text}:", reply_markup=cancel_action_keyboard())
    await state.set_state(AdministrativeStates.assign_owner_id)

@dp.message(AdministrativeStates.assign_owner_id)
async def owner_assign_finish(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие":
        await message.answer("Отмена.", reply_markup=admin_panel_keyboard())
        await state.clear()
        return
    
    try:
        new_owner_id = int(message.text)
        data = await state.get_data()
        team = data["target_team_name"]
        
        db_store["national_teams"][team]["owner"] = new_owner_id
        await message.answer("✅ Владелец успешно назначен!", reply_markup=admin_panel_keyboard())
        
        try:
            await bot.send_message(new_owner_id, f"👑 Поздравляем! Вы стали владельцем сборной {team}!", 
                                   reply_markup=main_dashboard_keyboard(new_owner_id))
        except: pass
        await state.clear()
    except:
        await message.answer("ID должен быть числом.")

# --- УПРАВЛЕНИЕ СБОРНОЙ: ТРЕНЕР, ВЫЗОВ, НАБОР ---

@dp.message(F.text == "🧠 Назначить Тренера")
async def coach_hire_start(message: types.Message, state: FSMContext):
    # Поиск команды, где отправитель — владелец
    team_name = next((n for n, d in db_store["national_teams"].items() if d["owner"] == message.from_user.id), None)
    if not team_name:
        await message.answer("❌ Ошибка: Вы не владелец сборной.")
        return
    
    await message.answer(f"Введите Telegram ID будущего тренера сборной {team_name}:", reply_markup=cancel_action_keyboard())
    await state.set_state(ManagementStates.hire_coach_id)

@dp.message(ManagementStates.hire_coach_id)
async def coach_hire_finish(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие":
        await message.answer("Действие отменено.", reply_markup=main_dashboard_keyboard(message.from_user.id))
        await state.clear()
        return
    
    try:
        c_id = int(message.text)
        team_name = next((n for n, d in db_store["national_teams"].items() if d["owner"] == message.from_user.id), None)
        db_store["national_teams"][team_name]["coach"] = c_id
        
        await message.answer("✅ Тренер назначен!", reply_markup=main_dashboard_keyboard(message.from_user.id))
        try:
            await bot.send_message(c_id, f"🦾 Вы назначены тренером сборной {team_name}!", 
                                   reply_markup=main_dashboard_keyboard(c_id))
        except: pass
        await state.clear()
    except:
        await message.answer("Введите цифровой ID.")

@dp.message(F.text == "📞 Вызов игрока")
async def player_invite_start(message: types.Message, state: FSMContext):
    # Могут владелец и тренер
    team_name = next((n for n, d in db_store["national_teams"].items() if d["owner"] == message.from_user.id or d["coach"] == message.from_user.id), None)
    if not team_name: return
    
    await message.answer("Введите @username игрока для вызова в сборную:", reply_markup=cancel_action_keyboard())
    await state.set_state(ManagementStates.send_invite_tag)

@dp.message(ManagementStates.send_invite_tag)
async def player_invite_finish(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие":
        await message.answer("Отмена.", reply_markup=main_dashboard_keyboard(message.from_user.id))
        await state.clear()
        return
    
    target_tag = message.text.replace("@", "").lower().strip()
    target_id = db_store["username_map"].get(target_tag)
    
    if not target_id:
        await message.answer("❌ Игрок не найден в базе. Он должен зарегистрироваться в боте.")
        return
        
    team_name = next((n for n, d in db_store["national_teams"].items() if d["owner"] == message.from_user.id or d["coach"] == message.from_user.id), None)
    
    # Кнопки для игрока
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять вызов", callback_data=f"inv_acc_{team_name}")
    kb.button(text="❌ Отклонить", callback_data="inv_dec")
    
    try:
        await bot.send_message(target_id, f"⚽️ Вас вызывает сборная **{team_name}**! Принимаете?", 
                               parse_mode="Markdown", reply_markup=kb.as_markup())
        await message.answer(f"✅ Вызов отправлен игроку @{target_tag}!", reply_markup=main_dashboard_keyboard(message.from_user.id))
    except:
        await message.answer("❌ Ошибка отправки. Бот заблокирован пользователем?")
    await state.clear()

@dp.callback_query(F.data.startswith("inv_acc_"))
async def callback_invite_accept(callback: types.CallbackQuery):
    team = callback.data.replace("inv_acc_", "")
    user_id = callback.from_user.id
    
    if team in db_store["national_teams"]:
        if user_id not in db_store["national_teams"][team]["roster"]:
            db_store["national_teams"][team]["roster"].append(user_id)
            await callback.message.edit_text(f"✅ Вы вступили в сборную {team}!")
            
            # Уведомление владельцу
            boss = db_store["national_teams"][team]["owner"]
            if boss:
                try:
                    p_nick = db_store["user_profiles"][user_id]["nick"]
                    await bot.send_message(boss, f"🔔 Игрок {p_nick} (@{callback.from_user.username}) принял вызов!")
                except: pass
        else:
            await callback.message.answer("Вы уже в этой команде.")

@dp.message(F.text == "📢 Набор в команду")
async def recruit_post_start(message: types.Message, state: FSMContext):
    team_name = next((n for n, d in db_store["national_teams"].items() if d["owner"] == message.from_user.id or d["coach"] == message.from_user.id), None)
    if not team_name: return
    
    if not db_store["active_channel_id"]:
        await message.answer("❌ Канал для наборов не настроен. Добавьте бота в канал как админа.")
        return
        
    await message.answer("Введите текст условий (что нужно от игрока):", reply_markup=cancel_action_keyboard())
    await state.set_state(ManagementStates.draft_recruit_post)

@dp.message(ManagementStates.draft_recruit_post)
async def recruit_post_finish(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие":
        await message.answer("Отмена.", reply_markup=main_dashboard_keyboard(message.from_user.id))
        await state.clear()
        return
    
    team_name = next((n for n, d in db_store["national_teams"].items() if d["owner"] == message.from_user.id or d["coach"] == message.from_user.id), None)
    owner_tag = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
    
    # Шаблон набора
    final_post = (
        "📣 **НОВЫЙ НАБОР В СБОРНУЮ!**\n\n"
        f"🏆 Команда: **{team_name}**\n"
        f"👑 Ответственный: {owner_tag}\n\n"
        f"📝 **Условия:**\n{message.text}"
    )
    
    try:
        await bot.send_message(db_store["active_channel_id"], final_post, parse_mode="Markdown")
        await message.answer("✅ Набор успешно опубликован в канале!", reply_markup=main_dashboard_keyboard(message.from_user.id))
    except Exception as e:
        await message.answer(f"❌ Ошибка публикации: {e}")
    await state.clear()

# --- КНОПКИ ЖИЗНЕННОГО ЦИКЛА КАРЬЕРЫ ---

@dp.message(F.text == "🏃 Завершить карьеру")
async def career_end_handler(message: types.Message):
    uid = message.from_user.id
    if uid in db_store["user_profiles"]:
        db_store["user_profiles"][uid]["active"] = False
        await message.answer("💔 Ваша карьера официально завершена. Информация обновлена.")

@dp.message(F.text == "🔙 Возобновить карьеру")
async def career_start_handler(message: types.Message):
    uid = message.from_user.id
    if uid in db_store["user_profiles"]:
        db_store["user_profiles"][uid]["active"] = True
        await message.answer("🔥 С возвращением на поле! Карьера возобновлена.")

# --- ПРОСМОТР ИНФОРМАЦИИ И СООБЩЕНИЯ ---

@dp.message(F.text == "📋 Состав сборной")
async def team_roster_view(message: types.Message):
    team_name = next((n for n, d in db_store["national_teams"].items() if d["owner"] == message.from_user.id or d["coach"] == message.from_user.id), None)
    if not team_name: return
    
    team = db_store["national_teams"][team_name]
    boss = f"ID: {team['owner']}"
    trainer = f"ID: {team['coach']}" if team['coach'] else "Не назначен"
    
    roster_list = []
    for pid in team["roster"]:
        p_nick = db_store["user_profiles"].get(pid, {}).get("nick", f"ID:{pid}")
        roster_list.append(f"• {p_nick}")
    
    full_roster = "\n".join(roster_list) if roster_list else "Список пуст."
    
    report = (
        f"🚩 **Сборная {team_name}**\n\n"
        f"👑 Владелец: {boss}\n"
        f"🦾 Тренер: {trainer}\n\n"
        f"👥 **Список игроков:**\n{full_roster}"
    )
    await message.answer(report, parse_mode="Markdown")

@dp.message(F.text == "✉️ Написать владельцу")
async def contact_owner_init(message: types.Message, state: FSMContext):
    if not db_store["national_teams"]:
        await message.answer("Сборных еще нет.")
        return
        
    kb = ReplyKeyboardBuilder()
    for name in db_store["national_teams"].keys():
        kb.button(text=name)
    kb.button(text="⛔ Отменить действие")
    kb.adjust(2)
    
    await message.answer("Выберите сборную, владельцу которой хотите написать:", 
                         reply_markup=kb.as_markup(resize_keyboard=True))
    await state.set_state(ManagementStates.direct_message_team)

@dp.message(ManagementStates.direct_message_team)
async def contact_owner_step2(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие":
        await message.answer("Отмена.", reply_markup=main_dashboard_keyboard(message.from_user.id))
        await state.clear()
        return
    
    if message.text not in db_store["national_teams"]: return
    await state.update_data(target_t=message.text)
    await message.answer(f"Введите текст вашего сообщения для {message.text}:", reply_markup=cancel_action_keyboard())
    await state.set_state(ManagementStates.direct_message_text)

@dp.message(ManagementStates.direct_message_text)
async def contact_owner_final(message: types.Message, state: FSMContext):
    if message.text == "⛔ Отменить действие": return
    
    data = await state.get_data()
    team_data = db_store["national_teams"].get(data["target_t"])
    owner_id = team_data["owner"]
    
    if owner_id:
        try:
            sender_nick = db_store["user_profiles"][message.from_user.id]["nick"]
            await bot.send_message(
                owner_id, 
                f"📨 **Новое ЛС!**\nОт: {sender_nick} (@{message.from_user.username})\n\n**Текст:** {message.text}",
                parse_mode="Markdown"
            )
            await message.answer("✅ Отправлено!", reply_markup=main_dashboard_keyboard(message.from_user.id))
        except:
            await message.answer("❌ Ошибка доставки.")
    await state.clear()

# --- СИСТЕМНЫЕ КНОПКИ НАЗАД ---

@dp.message(F.text == "🔙 В главное меню")
async def back_to_main_from_admin(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вернулись в главное меню.", reply_markup=main_dashboard_keyboard(message.from_user.id))

@dp.message(F.text == "🔙 Назад")
async def back_universal(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_dashboard_keyboard(message.from_user.id))

# --- ЗАПУСК И ОБСЛУЖИВАНИЕ ---

async def on_startup_notify():
    """Служебное уведомление о запуске бота"""
    print("\n" + "="*50)
    print("EASTERN EUROPEAN CUP BOT IS ONLINE")
    print(f"Time: {datetime.datetime.now()}")
    print("="*50 + "\n")

async def run_bot_service():
    """Основной цикл запуска"""
    await on_startup_notify()
    # Удаление старых вебхуков и начало поллинга
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(run_bot_service())
    except (KeyboardInterrupt, SystemExit):
        print("\n[!] Бот выключен администратором.")
    except Exception as fatal_error:
        print(f"\n[Критическая ошибка]: {fatal_error}")
