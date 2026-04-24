import logging
import asyncio
import time
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

# --- НАСТРОЙКИ ---
TOKEN = "8331981056:AAETEMewZiaM-0ffToiaIHOIJTxQkiWk7Rw"
# Главные админы (Владельцы)
MAIN_ADMINS = [8461055593, 5845609895]
# ID твоего канала для наборов (обязательно с -100...)
CHANNEL_ID = -1002482381285  # ЗАМЕНИ НА СВОЙ ID КАНАЛА

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ (В ПАМЯТИ) ---
db = {
    "secondary_admins": [],  # Список ID обычных админов
    "countries": ["🇷🇺Russia", "🇺🇦Ukraine", "🇰🇿Kazakhstan", "🇧🇾Belarus"],
    "teams": {},             # Сборные: {"Название": {"owner_id": 123, "coach_id": 456, "players": []}}
    "players": {},           # Игроки: {user_id: {"nick": "...", "country": "...", "last_nick_change": 0}}
}

# --- СОСТОЯНИЯ (FSM) ---
class Form(StatesGroup):
    # Регистрация
    register_nick = State()
    register_country = State()
    # Админка
    admin_add_team = State()
    admin_add_owner_team = State()
    admin_add_owner_id = State()
    admin_new_admin_id = State()
    # Игрок и Владелец
    edit_nick = State()
    recruit_text = State()
    invite_player_tag = State()
    send_msg_team = State()
    send_msg_text = State()

# --- КЛАВИАТУРЫ ---

def get_main_menu(user_id):
    """Главное меню, которое меняется в зависимости от прав"""
    builder = ReplyKeyboardBuilder()
    
    # 1. Кнопка Админ Панели (только для админов)
    if user_id in MAIN_ADMINS or user_id in db["secondary_admins"]:
        builder.button(text="⚙️ Админ панель")
    
    # 2. Проверка: является ли юзер владельцем сборной
    is_owner = any(t.get("owner_id") == user_id for t in db["teams"].values())
    if is_owner:
        builder.button(text="📋 Посмотреть сборную")
        builder.button(text="📢 Сделать набор")
        builder.button(text="🧠 Добавить Тренера")
        builder.button(text="📞 Вызов в сборную")

    # 3. Общие кнопки для игрока
    builder.button(text="📝 Изменить ник")
    builder.button(text="🏃 Завершить Карьеру")
    builder.button(text="🔙 Вернуть Карьеру")
    builder.button(text="✉️ Сообщение владельцу")
    
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_admin_menu():
    """Меню внутри админ-панели"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить Сборную")
    builder.button(text="👑 Добавить владельца")
    builder.button(text="🛡 Добавить Админа")
    builder.button(text="🔙 Назад")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_back_button():
    """Универсальная кнопка назад"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="🔙 Назад")
    return builder.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ РЕГИСТРАЦИИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id in db["players"]:
        await message.answer("👋 Добро пожаловать в Eastern European Cup Bot!", 
                             reply_markup=get_main_menu(message.from_user.id))
    else:
        await message.answer("👋 Привет! Введите свой ник Roblox для регистрации:")
        await state.set_state(Form.register_nick)

@dp.message(Form.register_nick)
async def process_reg_nick(message: types.Message, state: FSMContext):
    await state.update_data(nick=message.text)
    builder = InlineKeyboardBuilder()
    for country in db["countries"]:
        builder.button(text=country, callback_data=f"reg_country_{country}")
    builder.adjust(1)
    await message.answer("🌐 Из какой вы страны?", reply_markup=builder.as_markup())
    await state.set_state(Form.register_country)

@dp.callback_query(F.data.startswith("reg_country_"))
async def process_reg_country(callback: types.CallbackQuery, state: FSMContext):
    country = callback.data.replace("reg_country_", "")
    user_data = await state.get_data()
    
    db["players"][callback.from_user.id] = {
        "nick": user_data["nick"],
        "country": country,
        "career_active": True,
        "last_nick_change": 0
    }
    
    await callback.message.delete()
    await callback.message.answer(f"✅ Регистрация успешна!\nНик: {user_data['nick']}\nСтрана: {country}", 
                                 reply_markup=get_main_menu(callback.from_user.id))
    await state.clear()

# --- ЛОГИКА КНОПКИ НАЗАД ---

@dp.message(F.text == "🔙 Назад")
async def universal_back(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вернулись в главное меню.", reply_markup=get_main_menu(message.from_user.id))

# --- АДМИН ПАНЕЛЬ ---

@dp.message(F.text == "⚙️ Админ панель")
async def open_admin_panel(message: types.Message):
    if message.from_user.id in MAIN_ADMINS or message.from_user.id in db["secondary_admins"]:
        await message.answer("📂 Админ-меню открыто:", reply_markup=get_admin_menu())
    else:
        await message.answer("⛔ У вас нет доступа к этой панели.")

@dp.message(F.text == "🛡 Добавить Админа")
async def admin_add_start(message: types.Message, state: FSMContext):
    # Только главные админы могут добавлять других
    if message.from_user.id not in MAIN_ADMINS:
        await message.answer("❌ Добавить админа могут только влд")
        return
    
    await message.answer("Введите Telegram ID будущего админа:", reply_markup=get_back_button())
    await state.set_state(Form.admin_new_admin_id)

@dp.message(Form.admin_new_admin_id)
async def admin_add_save(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад": return
    try:
        new_admin_id = int(message.text)
        if new_admin_id not in db["secondary_admins"]:
            db["secondary_admins"].append(new_admin_id)
            await message.answer(f"✅ Пользователь {new_admin_id} теперь админ.", reply_markup=get_admin_menu())
            try:
                await bot.send_message(new_admin_id, "⚙️ Вам выдали права администратора!", 
                                       reply_markup=get_main_menu(new_admin_id))
            except: pass
        else:
            await message.answer("Он уже админ.")
        await state.clear()
    except ValueError:
        await message.answer("Введите числовой ID.")

@dp.message(F.text == "➕ Добавить Сборную")
async def admin_team_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_ADMINS and message.from_user.id not in db["secondary_admins"]: return
    await message.answer("Введите название сборной (вместе с флагом):", reply_markup=get_back_button())
    await state.set_state(Form.admin_add_team)

@dp.message(Form.admin_add_team)
async def admin_team_save(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад": return
    team_name = message.text
    db["teams"][team_name] = {"owner_id": None, "coach_id": None, "players": []}
    await message.answer(f"✅ Сборная {team_name} добавлена в систему!", reply_markup=get_admin_menu())
    await state.clear()

@dp.message(F.text == "👑 Добавить владельца")
async def admin_owner_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_ADMINS and message.from_user.id not in db["secondary_admins"]: return
    if not db["teams"]:
        await message.answer("Сборных еще нет.")
        return
    
    builder = ReplyKeyboardBuilder()
    for t_name in db["teams"].keys():
        builder.button(text=t_name)
    builder.button(text="🔙 Назад")
    builder.adjust(2)
    
    await message.answer("Выберите сборную для назначения владельца:", reply_markup=builder.as_markup(resize_keyboard=True))
    await state.set_state(Form.admin_add_owner_team)

@dp.message(Form.admin_add_owner_team)
async def admin_owner_team_pick(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Отмена", reply_markup=get_admin_menu())
        await state.clear()
        return
    if message.text not in db["teams"]:
        await message.answer("Выберите сборную из списка.")
        return
    await state.update_data(chosen_team=message.text)
    await message.answer(f"Введите Telegram ID владельца для {message.text}:", reply_markup=get_back_button())
    await state.set_state(Form.admin_add_owner_id)

@dp.message(Form.admin_add_owner_id)
async def admin_owner_final(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад": return
    try:
        owner_id = int(message.text)
        s_data = await state.get_data()
        db["teams"][s_data["chosen_team"]]["owner_id"] = owner_id
        await message.answer(f"✅ Владелец {owner_id} назначен для {s_data['chosen_team']}!", reply_markup=get_admin_menu())
        try:
            await bot.send_message(owner_id, f"👑 Вы стали владельцем сборной {s_data['chosen_team']}!", reply_markup=get_main_menu(owner_id))
        except: pass
        await state.clear()
    except ValueError:
        await message.answer("Введите ID цифрами.")

# --- ЛОГИКА ИГРОКА (ИЗМЕНИТЬ НИК С КД) ---

@dp.message(F.text == "📝 Изменить ник")
async def player_edit_nick(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    # Проверка на админа (им можно без КД)
    is_adm = user_id in MAIN_ADMINS or user_id in db["secondary_admins"]
    
    if not is_adm:
        last_time = db["players"][user_id].get("last_nick_change", 0)
        # 604800 секунд = 7 дней
        if time.time() - last_time < 604800:
            remaining = 604800 - (time.time() - last_time)
            days = int(remaining // 86400)
            await message.answer(f"❌ Менять ник можно раз в 7 дней! Ждать: {days} дн.")
            return

    await message.answer("Введите новый ник Roblox:", reply_markup=get_back_button())
    await state.set_state(Form.edit_nick)

@dp.message(Form.edit_nick)
async def player_save_nick(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад": return
    db["players"][message.from_user.id]["nick"] = message.text
    db["players"][message.from_user.id]["last_nick_change"] = time.time()
    await message.answer(f"✅ Ник успешно изменен на {message.text}!", reply_markup=get_main_menu(message.from_user.id))
    await state.clear()

# --- ЛОГИКА ВЛАДЕЛЬЦА (НАБОР) ---

@dp.message(F.text == "📢 Сделать набор")
async def owner_recruit_start(message: types.Message, state: FSMContext):
    # Проверка: является ли он владельцем
    team_name = next((n for n, t in db["teams"].items() if t["owner_id"] == message.from_user.id), None)
    if not team_name:
        await message.answer("У вас нет сборной.")
        return
    
    await message.answer(f"📢 Сборная: {team_name}\nВведите текст, который должен написать игрок (условия):", 
                         reply_markup=get_back_button())
    await state.set_state(Form.recruit_text)

@dp.message(Form.recruit_text)
async def owner_recruit_send(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад": return
    team_name = next((n for n, t in db["teams"].items() if t["owner_id"] == message.from_user.id), None)
    user_tag = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
    
    # Твой шаблон
    post_text = (
        "🔥 Набор в сборную!\n"
        f"📍 {team_name}\n"
        f"👑 Влд: {user_tag}\n"
        f"📝 Текст: {message.text}"
    )
    
    try:
        await bot.send_message(CHANNEL_ID, post_text)
        await message.answer("✅ Набор успешно опубликован в канале!", reply_markup=get_main_menu(message.from_user.id))
    except Exception as e:
        await message.answer(f"❌ Ошибка публикации! Проверьте, что бот админ в канале {CHANNEL_ID}.\nОшибка: {e}")
    
    await state.clear()

# --- ПРОСМОТР СБОРНОЙ ---

@dp.message(F.text == "📋 Посмотреть сборную")
async def owner_view_team(message: types.Message):
    team_name = next((n for n, t in db["teams"].items() if t["owner_id"] == message.from_user.id), None)
    if not team_name: return
    
    t = db["teams"][team_name]
    coach = "🆕 Нанять" if not t["coach_id"] else f"ID: {t['coach_id']}"
    players = "\n".join(t["players"]) if t["players"] else "Игроков нет"
    
    info = (
        f"☑️ Название - {team_name}\n"
        f"👑 Владелец сборной - @{message.from_user.username}\n"
        f"🦾 Тренер - {coach}\n"
        f"👥 Игроки:\n{players}"
    )
    await message.answer(info)

# --- ЛОГИКА КАРЬЕРЫ ---

@dp.message(F.text == "🏃 Завершить Карьеру")
async def career_stop(message: types.Message):
    if message.from_user.id in db["players"]:
        db["players"][message.from_user.id]["career_active"] = False
        await message.answer("💔 Ваша карьера завершена. Статус обновлен.", reply_markup=get_main_menu(message.from_user.id))

@dp.message(F.text == "🔙 Вернуть Карьеру")
async def career_back(message: types.Message):
    if message.from_user.id in db["players"]:
        db["players"][message.from_user.id]["career_active"] = True
        await message.answer("🔥 С возвращением! Ваша карьера снова активна.", reply_markup=get_main_menu(message.from_user.id))

# --- СООБЩЕНИЕ ВЛАДЕЛЬЦУ ---

@dp.message(F.text == "✉️ Сообщение владельцу")
async def player_msg_start(message: types.Message, state: FSMContext):
    if not db["teams"]:
        await message.answer("Сборных еще нет.")
        return
    
    builder = ReplyKeyboardBuilder()
    for name in db["teams"].keys():
        builder.button(text=name)
    builder.button(text="🔙 Назад")
    builder.adjust(2)
    
    await message.answer("Кому хотите отправить сообщение?", reply_markup=builder.as_markup(resize_keyboard=True))
    await state.set_state(Form.send_msg_team)

@dp.message(Form.send_msg_team)
async def player_msg_team_pick(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад": return
    if message.text not in db["teams"]: return
    
    await state.update_data(target_team=message.text)
    await message.answer(f"Введите текст сообщения для владельца {message.text}:", reply_markup=get_back_button())
    await state.set_state(Form.send_msg_text)

@dp.message(Form.send_msg_text)
async def player_msg_final(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад": return
    s_data = await state.get_data()
    team = db["teams"][s_data["target_team"]]
    
    if team["owner_id"]:
        try:
            user_info = db["players"][message.from_user.id]
            await bot.send_message(team["owner_id"], 
                                 f"📨 Новое сообщение от игрока {user_info['nick']} (@{message.from_user.username}):\n\n{message.text}")
            await message.answer("✅ Сообщение успешно доставлено!", reply_markup=get_main_menu(message.from_user.id))
        except:
            await message.answer("❌ Ошибка отправки.")
    else:
        await message.answer("У этой сборной нет владельца.")
    await state.clear()

# --- ЗАПУСК БОТА ---
async def main():
    print(">>> Eastern European Cup Bot запущен и готов к работе! <<<")
    # Проверка наличия токена
    if TOKEN == "ВАШ_ТОКЕН_ТУТ":
        print("ОШИБКА: Замените токен в коде!")
        return
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
