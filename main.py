import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# --- КОНФИГУРАЦИЯ ---
TOKEN = "8331981056:AAETEMewZiaM-0ffToiaIHOIJTxQkiWk7Rw"
# Главные админы (Владельцы бота)
MAIN_ADMINS = [8461055593, 5845609895]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ (в памяти) ---
db = {
    "secondary_admins": [],  # Список ID обычных админов
    "countries": ["🇷🇺Russia", "🇺🇦Ukraine", "🇰🇿Kazakhstan", "🇧🇾Belarus"],
    "teams": {},             # Сборные
    "players": {},           # Данные игроков
}

# --- СОСТОЯНИЯ ---
class Form(StatesGroup):
    register_nick = State()
    register_country = State()
    admin_add_team = State()
    admin_add_owner_team = State()
    admin_add_owner_id = State()
    admin_new_admin_id = State()
    owner_invite_player = State()
    player_msg_owner_team = State()
    player_msg_text = State()

# --- ФУНКЦИЯ ГЕНЕРАЦИИ МЕНЮ ---
def get_main_menu(user_id):
    builder = ReplyKeyboardBuilder()
    
    # Проверка: является ли пользователь админом (любым)
    is_main = user_id in MAIN_ADMINS
    is_secondary = user_id in db["secondary_admins"]
    
    # АДМИН-ПАНЕЛЬ (видят оба типа админов)
    if is_main or is_secondary:
        builder.button(text="➕ Добавить Сборную")
        builder.button(text="👑 Добавить владельца сборной")
        builder.button(text="🛡 Добавить Админа")
    
    # МЕНЮ ВЛАДЕЛЬЦА СБОРНОЙ (если ID записан как владелец в db["teams"])
    is_team_owner = any(t.get("owner_id") == user_id for t in db["teams"].values())
    if is_team_owner:
        builder.button(text="📋 Посмотреть сборную")
        builder.button(text="🧠 Добавить Тренера")
        builder.button(text="📞 Вызов в сборную")

    # МЕНЮ ИГРОКА (для всех зарегистрированных)
    if user_id in db["players"]:
        if db["players"][user_id].get("career_active", True):
            builder.button(text="🏃 Завершить Карьеру")
        else:
            builder.button(text="🔙 Вернуть Карьеру")
        builder.button(text="✉️ Сообщение владельцу сборной")
    
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.from_user.id in db["players"]:
        await message.answer("Главное меню:", reply_markup=get_main_menu(message.from_user.id))
    else:
        await message.answer("👋 Привет! Введите свой ник Roblox для регистрации:")
        await state.set_state(Form.register_nick)

@dp.message(Form.register_nick)
async def reg_nick(message: types.Message, state: FSMContext):
    await state.update_data(nick=message.text)
    builder = InlineKeyboardBuilder()
    for c in db["countries"]:
        builder.button(text=c, callback_data=f"set_c_{c}")
    builder.adjust(1)
    await message.answer("🌐 Из какой вы страны?", reply_markup=builder.as_markup())
    await state.set_state(Form.register_country)

@dp.callback_query(F.data.startswith("set_c_"))
async def reg_country(callback: types.CallbackQuery, state: FSMContext):
    country = callback.data.replace("set_c_", "")
    u_data = await state.get_data()
    db["players"][callback.from_user.id] = {
        "nick": u_data["nick"],
        "country": country,
        "career_active": True
    }
    await callback.message.delete()
    await callback.message.answer(f"✅ Регистрация завершена!\nНик: {u_data['nick']}\nСтрана: {country}", 
                                 reply_markup=get_main_menu(callback.from_user.id))
    await state.clear()

# --- ЛОГИКА АДМИНИСТРАТОРА ---

@dp.message(F.text == "🛡 Добавить Админа")
async def btn_add_admin(message: types.Message, state: FSMContext):
    # ПРОВЕРКА ПРАВ
    if message.from_user.id not in MAIN_ADMINS:
        await message.answer("❌ Добавить админа могут только влд")
        return
    
    await message.answer("Введите Telegram ID пользователя, которого хотите сделать админом:")
    await state.set_state(Form.admin_new_admin_id)

@dp.message(Form.admin_new_admin_id)
async def save_new_admin(message: types.Message, state: FSMContext):
    try:
        new_id = int(message.text)
        if new_id not in db["secondary_admins"]:
            db["secondary_admins"].append(new_id)
            await message.answer(f"✅ Пользователь {new_id} назначен администратором.")
            # Уведомляем нового админа
            try:
                await bot.send_message(new_id, "⚙️ Вам выданы права администратора!", reply_markup=get_main_menu(new_id))
            except:
                pass 
        else:
            await message.answer("Этот пользователь уже админ.")
        await state.clear()
    except ValueError:
        await message.answer("Ошибка! Введите числовой ID.")

@dp.message(F.text == "➕ Добавить Сборную")
async def btn_add_team(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_ADMINS and message.from_user.id not in db["secondary_admins"]:
        return
    await message.answer("Введите название новой сборной (с флагом):")
    await state.set_state(Form.admin_add_team)

@dp.message(Form.admin_add_team)
async def save_new_team(message: types.Message, state: FSMContext):
    db["teams"][message.text] = {"owner_id": None, "coach_id": None, "players": []}
    await message.answer(f"✅ Сборная {message.text} успешно создана!")
    await state.clear()

@dp.message(F.text == "👑 Добавить владельца сборной")
async def btn_add_owner(message: types.Message, state: FSMContext):
    if message.from_user.id not in MAIN_ADMINS and message.from_user.id not in db["secondary_admins"]:
        return
    if not db["teams"]:
        await message.answer("Сначала добавьте хотя бы одну сборную.")
        return
    
    builder = ReplyKeyboardBuilder()
    for team_name in db["teams"].keys():
        builder.button(text=team_name)
    builder.adjust(2)
    
    await message.answer("Выберите сборную для назначения владельца:", reply_markup=builder.as_markup(resize_keyboard=True))
    await state.set_state(Form.admin_add_owner_team)

@dp.message(Form.admin_add_owner_team)
async def save_owner_step_2(message: types.Message, state: FSMContext):
    if message.text not in db["teams"]:
        await message.answer("Выберите сборную из списка на кнопках.")
        return
    await state.update_data(target_team=message.text)
    await message.answer(f"Введите Telegram ID будущего владельца {message.text}:")
    await state.set_state(Form.admin_add_owner_id)

@dp.message(Form.admin_add_owner_id)
async def save_owner_final(message: types.Message, state: FSMContext):
    try:
        owner_id = int(message.text)
        s_data = await state.get_data()
        db["teams"][s_data["target_team"]]["owner_id"] = owner_id
        await message.answer(f"✅ Владелец для {s_data['target_team']} назначен!", reply_markup=get_main_menu(message.from_user.id))
        
        # Уведомляем владельца
        try:
            await bot.send_message(owner_id, f"👑 Вы назначены владельцем сборной {s_data['target_team']}!", reply_markup=get_main_menu(owner_id))
        except:
            pass
        await state.clear()
    except ValueError:
        await message.answer("Ошибка! Введите числовой ID.")

# --- ЛОГИКА ВЛАДЕЛЬЦА ---

@dp.message(F.text == "📋 Посмотреть сборную")
async def btn_view_team(message: types.Message):
    # Ищем сборную, где отправитель — владелец
    team_data = None
    team_name = ""
    for name, data in db["teams"].items():
        if data["owner_id"] == message.from_user.id:
            team_data = data
            team_name = name
            break
            
    if not team_data:
        await message.answer("Вы не владелец ни одной сборной.")
        return

    coach = "🆕 Нанять" if not team_data["coach_id"] else f"ID: {team_data['coach_id']}"
    players_str = "\n".join(team_data["players"]) if team_data["players"] else "Игроков нет"
    
    # Твой шаблон
    msg = (
        f"☑️ Название - {team_name}\n"
        f"👑 Владелец сборной - @{message.from_user.username if message.from_user.username else 'Нет юза'}\n"
        f"🦾 Тренер - {coach}\n"
        f"👥 Игроки:\n{players_str}"
    )
    await message.answer(msg)

# --- ЛОГИКА ИГРОКА ---

@dp.message(F.text == "🏃 Завершить Карьеру")
async def career_stop(message: types.Message):
    if message.from_user.id in db["players"]:
        db["players"][message.from_user.id]["career_active"] = False
        await message.answer("🛑 Карьера завершена. Вы можете вернуть её в любой момент.", reply_markup=get_main_menu(message.from_user.id))

@dp.message(F.text == "🔙 Вернуть Карьеру")
async def career_return(message: types.Message):
    if message.from_user.id in db["players"]:
        db["players"][message.from_user.id]["career_active"] = True
        await message.answer("✅ Карьера возобновлена!", reply_markup=get_main_menu(message.from_user.id))

@dp.message(F.text == "✉️ Сообщение владельцу сборной")
async def msg_owner_start(message: types.Message, state: FSMContext):
    if not db["teams"]:
        await message.answer("Сборных пока нет.")
        return
    
    builder = ReplyKeyboardBuilder()
    for t in db["teams"].keys():
        builder.button(text=t)
    builder.adjust(2)
    await message.answer("Выберите сборную, владельцу которой хотите написать:", reply_markup=builder.as_markup(resize_keyboard=True))
    await state.set_state(Form.player_msg_owner_team)

@dp.message(Form.player_msg_owner_team)
async def msg_owner_text(message: types.Message, state: FSMContext):
    if message.text not in db["teams"]:
        await message.answer("Выберите команду из списка.")
        return
    await state.update_data(to_team=message.text)
    await message.answer("Введите текст сообщения:")
    await state.set_state(Form.player_msg_text)

@dp.message(Form.player_msg_text)
async def msg_owner_final(message: types.Message, state: FSMContext):
    s_data = await state.get_data()
    team = db["teams"][s_data["to_team"]]
    
    if team["owner_id"]:
        try:
            player_nick = db["players"][message.from_user.id]["nick"]
            await bot.send_message(
                team["owner_id"], 
                f"📨 Сообщение от игрока {player_nick} (@{message.from_user.username}):\n\n{message.text}"
            )
            await message.answer("✅ Сообщение отправлено!", reply_markup=get_main_menu(message.from_user.id))
        except:
            await message.answer("❌ Не удалось отправить (владелец заблокировал бота).")
    else:
        await message.answer("У этой сборной нет владельца.")
    await state.clear()

# --- ЗАПУСК ---
async def main():
    print("Бот Восточно-Европейского Кубка запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
