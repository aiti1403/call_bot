import asyncio
import logging
import sqlite3
import datetime
from typing import Dict, List, Union, Optional, Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Конфигурация
BOT_TOKEN = "7894090680:AAHHbmjerlGd9qTTL13yGmFzJBf9hdgn9sY"  # Замените на свой токен
ADMIN_IDS = [519206919, 6377272527, 1252744817, 641425229, 5704933313,  5028852658]  # Замените на ID администраторов (ПДО, начальники смен)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Состояния FSM для создания заявки
class ShiftRequest(StatesGroup):
    waiting_for_location = State()
    waiting_for_department = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_employees_count = State()
    waiting_for_employee_category = State()
    waiting_for_note = State()
    confirm_request = State()

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        user_id INTEGER UNIQUE,
        username TEXT,
        full_name TEXT,
        category TEXT,
        is_admin INTEGER DEFAULT 0
    )
    ''')
    
    # Таблица заявок
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY,
        creator_id INTEGER,
        location TEXT,
        department TEXT,
        shift_date TEXT,
        shift_time TEXT,
        employees_needed INTEGER,
        employee_category TEXT,
        note TEXT,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица откликов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY,
        request_id INTEGER,
        user_id INTEGER,
        status TEXT DEFAULT 'confirmed',
        responded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (request_id) REFERENCES requests (id),
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    conn.commit()
    conn.close()

def add_user(user_id: int, username: str, full_name: str, category: str = None, is_admin: int = 0):
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    # Проверяем, существует ли пользователь
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    existing_user = cursor.fetchone()
    
    if existing_user:
        # Обновляем существующего пользователя
        if category:
            cursor.execute(
                "UPDATE users SET username = ?, full_name = ?, category = ?, is_admin = ? WHERE user_id = ?",
                (username, full_name, category, is_admin, user_id)
            )
        else:
            cursor.execute(
                "UPDATE users SET username = ?, full_name = ?, is_admin = ? WHERE user_id = ?",
                (username, full_name, is_admin, user_id)
            )
    else:
        # Добавляем нового пользователя
        cursor.execute(
            "INSERT INTO users (user_id, username, full_name, category, is_admin) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, full_name, category, is_admin)
        )
    
    conn.commit()
    conn.close()
    
    logger.info(f"Пользователь {full_name} (ID: {user_id}) {'обновлен' if existing_user else 'добавлен'} в базу. Категория: {category}")




# Функции для работы с базой данных
@router.callback_query(F.data.startswith("empl_cat_"))
async def process_employee_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[2]
    # Стандартизируем категорию (убираем лишние пробелы, приводим к нужному регистру)
    category = category.strip()
    
    await state.update_data(employee_category=category)
    
    # Отладочный вывод
    logger.info(f"Выбрана категория: '{category}'")
    
    user_data = await state.get_data()
    await callback.message.edit_text(
        f"Шаг 6/7: Выбрана площадка: {user_data['location']}, "
        f"участок: {user_data['department']}, дата: {user_data['shift_date']}, "
        f"время: {user_data['shift_time']}, сотрудников: {user_data['employees_needed']}, "
        f"категория: {category}\n\n"
        "Введите примечание к заявке (например, 'горячая линия', 'срочный заказ') "
        "или отправьте /skip, чтобы пропустить этот шаг:"
    )
    
    await state.set_state(ShiftRequest.waiting_for_note)
    await callback.answer()


def is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    conn.close()
    
    return result is not None and result[0] == 1

def create_shift_request(creator_id: int, location: str, department: str, 
                         shift_date: str, shift_time: str, employees_needed: int, 
                         employee_category: str, note: str) -> int:
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    cursor.execute(
        """INSERT INTO requests 
           (creator_id, location, department, shift_date, shift_time, 
            employees_needed, employee_category, note) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (creator_id, location, department, shift_date, shift_time, 
         employees_needed, employee_category, note)
    )
    
    request_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    
    return request_id


def get_users_by_category(category: str) -> List[int]:
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    # Выводим отладочную информацию
    logger.info(f"Ищем сотрудников категории: '{category}'")
    
    # Проверяем точное совпадение
    cursor.execute("SELECT user_id, full_name FROM users WHERE category = ?", (category,))
    exact_matches = cursor.fetchall()
    
    if exact_matches:
        logger.info(f"Найдено {len(exact_matches)} сотрудников с точным совпадением категории '{category}'")
        result = [row[0] for row in exact_matches]
    else:
        # Если точных совпадений нет, ищем без учета регистра
        logger.info(f"Точных совпадений не найдено, ищем без учета регистра")
        cursor.execute("SELECT user_id, full_name FROM users WHERE LOWER(category) = LOWER(?)", (category,))
        case_insensitive_matches = cursor.fetchall()
        logger.info(f"Найдено {len(case_insensitive_matches)} сотрудников без учета регистра")
        result = [row[0] for row in case_insensitive_matches]
    
    # Выводим найденных пользователей
    for user_id, name in (exact_matches or case_insensitive_matches):
        logger.info(f"- ID: {user_id}, Имя: {name}")
    
    conn.close()
    return result



def add_response(request_id: int, user_id: int) -> bool:
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    # Проверяем, не откликался ли уже пользователь
    cursor.execute("SELECT id FROM responses WHERE request_id = ? AND user_id = ?", 
                  (request_id, user_id))
    if cursor.fetchone():
        conn.close()
        return False
    
    cursor.execute(
        "INSERT INTO responses (request_id, user_id) VALUES (?, ?)",
        (request_id, user_id)
    )
    
    conn.commit()
    conn.close()
    
    return True

def get_request_info(request_id: int) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, creator_id, location, department, shift_date, shift_time,
               employees_needed, employee_category, note, status
        FROM requests WHERE id = ?
    """, (request_id,))
    
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return None
    
    request = {
        'id': row[0],
        'creator_id': row[1],  # Добавляем creator_id в результат
        'location': row[2],
        'department': row[3],
        'shift_date': row[4],
        'shift_time': row[5],
        'employees_needed': row[6],
        'employee_category': row[7],
        'note': row[8],
        'status': row[9]
    }
    
    # Получаем количество откликнувшихся
    cursor.execute("SELECT COUNT(*) FROM responses WHERE request_id = ?", (request_id,))
    request['responses_count'] = cursor.fetchone()[0]
    
    conn.close()
    
    return request


def get_responses_for_request(request_id: int) -> List[Dict[str, Any]]:
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT r.user_id, u.full_name, r.status
        FROM responses r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.request_id = ?
        ORDER BY r.responded_at
    """, (request_id,))
    
    responses = []
    for row in cursor.fetchall():
        responses.append({
            'user_id': row[0],
            'full_name': row[1],
            'status': row[2]
        })
    
    conn.close()
    
    return responses

def update_request_status(request_id: int, status: str):
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    cursor.execute("UPDATE requests SET status = ? WHERE id = ?", (status, request_id))
    
    conn.commit()
    conn.close()

def update_response_status(request_id: int, user_id: int, status: str):
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE responses SET status = ? WHERE request_id = ? AND user_id = ?", 
        (status, request_id, user_id)
    )
    
    conn.commit()
    conn.close()

# Обработчики команд
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name
    
    # Добавляем пользователя в базу, если его там нет
    add_user(user_id, username, full_name, is_admin=1 if user_id in ADMIN_IDS else 0)
    
    if is_admin(user_id):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Создать заявку на смену", callback_data="create_request")],
            [InlineKeyboardButton(text="Мои активные заявки", callback_data="my_requests")]
        ])
        await message.answer("Добро пожаловать в систему срочного вызова на смену!", reply_markup=keyboard)
    else:
        # Для обычных сотрудников
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Указать мою категорию", callback_data="set_category")]
        ])
        await message.answer(
            "Добро пожаловать в систему срочного вызова на смену!\n"
            "Через этого бота вы будете получать уведомления о срочных вызовах на смену.",
            reply_markup=keyboard
        )
    
    await state.clear()

@router.callback_query(F.data == "set_category")
async def set_category(callback: CallbackQuery, state: FSMContext):
    categories = [
        "Операторы", "Сборщики", "Кладовщики", 
        "Наладчики", "Механики", "Настройщики",
        "Грузчики", "Мастера смены"
    ]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=category, callback_data=f"category_{category}")]
        for category in categories
    ])
    
    await callback.message.edit_text(
        "Выберите вашу категорию персонала:",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data.startswith("category_"))
async def process_category_selection(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[1]
    user_id = callback.from_user.id
    username = callback.from_user.username or ""
    full_name = callback.from_user.full_name
    
    add_user(user_id, username, full_name, category=category)
    
    await callback.message.edit_text(
        f"Ваша категория установлена: {category}\n\n"
        "Теперь вы будете получать уведомления о срочных вызовах для вашей категории."
    )
    await callback.answer()

@router.callback_query(F.data == "create_request")
async def create_request(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    locations = ["Михалевича", "Карла Маркса"]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=location, callback_data=f"location_{location}")]
        for location in locations
    ])
    
    await callback.message.edit_text(
        "Шаг 1/7: Выберите площадку:",
        reply_markup=keyboard
    )
    
    await state.set_state(ShiftRequest.waiting_for_location)
    await callback.answer()

@router.callback_query(ShiftRequest.waiting_for_location, F.data.startswith("location_"))
async def process_location(callback: CallbackQuery, state: FSMContext):
    location = callback.data.split("_")[1]
    await state.update_data(location=location)
    
    departments = ["Станки", "Линия сборки", "Склад", "ОТК"]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=dept, callback_data=f"dept_{dept}")]
        for dept in departments
    ])
    
    await callback.message.edit_text(
        f"Шаг 2/7: Выбрана площадка: {location}\n"
        "Выберите участок:",
        reply_markup=keyboard
    )
    
    await state.set_state(ShiftRequest.waiting_for_department)
    await callback.answer()

@router.callback_query(ShiftRequest.waiting_for_department, F.data.startswith("dept_"))
async def process_department(callback: CallbackQuery, state: FSMContext):
    department = callback.data.split("_")[1]
    await state.update_data(department=department)
    
    # Создаем календарь на ближайшие 7 дней
    today = datetime.datetime.now()
    dates = []
    for i in range(7):
        date = today + datetime.timedelta(days=i)
        dates.append(date.strftime("%d.%m.%Y"))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=date, callback_data=f"date_{date}")]
        for date in dates
    ])
    
    user_data = await state.get_data()
    await callback.message.edit_text(
        f"Шаг 3/7: Выбрана площадка: {user_data['location']}, участок: {department}\n"
        "Выберите дату смены:",
        reply_markup=keyboard
    )
    
    await state.set_state(ShiftRequest.waiting_for_date)
    await callback.answer()

@router.callback_query(ShiftRequest.waiting_for_date, F.data.startswith("date_"))
async def process_date(callback: CallbackQuery, state: FSMContext):
    date = callback.data.split("_")[1]
    await state.update_data(shift_date=date)
    
    shift_times = ["08:00-20:00", "20:00-08:00", "8:00-8:00", "8:00-17:00"]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=time, callback_data=f"time_{time}")]
        for time in shift_times
    ])
    
    user_data = await state.get_data()
    await callback.message.edit_text(
        f"Шаг 4/7: Выбрана площадка: {user_data['location']}, "
        f"участок: {user_data['department']}, дата: {date}\n"
        "Выберите время смены:",
        reply_markup=keyboard
    )
    
    await state.set_state(ShiftRequest.waiting_for_time)
    await callback.answer()

@router.callback_query(ShiftRequest.waiting_for_time, F.data.startswith("time_"))
async def process_time(callback: CallbackQuery, state: FSMContext):
    time = callback.data.split("_")[1]
    await state.update_data(shift_time=time)
    
    # Выбор количества сотрудников
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1", callback_data="count_1"),
            InlineKeyboardButton(text="2", callback_data="count_2"),
            InlineKeyboardButton(text="3", callback_data="count_3"),
        ],
        [
            InlineKeyboardButton(text="4", callback_data="count_4"),
            InlineKeyboardButton(text="5", callback_data="count_5"),
            InlineKeyboardButton(text="6", callback_data="count_6"),
        ]
    ])
    
    user_data = await state.get_data()
    await callback.message.edit_text(
        f"Шаг 5/7: Выбрана площадка: {user_data['location']}, "
        f"участок: {user_data['department']}, дата: {user_data['shift_date']}, "
        f"время: {time}\n"
        "Выберите количество требуемых сотрудников:",
        reply_markup=keyboard
    )
    
    await state.set_state(ShiftRequest.waiting_for_employees_count)
    await callback.answer()

@router.callback_query(ShiftRequest.waiting_for_employees_count, F.data.startswith("count_"))
async def process_employees_count(callback: CallbackQuery, state: FSMContext):
    count = int(callback.data.split("_")[1])
    await state.update_data(employees_needed=count)
    
    # Выбор категории сотрудников
    categories = [
        "Операторы", "Сборщики", "Кладовщики", 
        "Наладчики", "Механики", "Настройщики",
        "Грузчики", "Мастера смены", "Контролер ОТК"
    ]
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=category, callback_data=f"empl_cat_{category}")]
        for category in categories
    ])
    
    user_data = await state.get_data()
    await callback.message.edit_text(
        f"Шаг 6/7: Выбрана площадка: {user_data['location']}, "
        f"участок: {user_data['department']}, дата: {user_data['shift_date']}, "
        f"время: {user_data['shift_time']}, сотрудников: {count}\n"
        "Выберите категорию персонала:",
        reply_markup=keyboard
    )
    
    await state.set_state(ShiftRequest.waiting_for_employee_category)
    await callback.answer()

@router.callback_query(F.data.startswith("empl_cat_"))
async def process_employee_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[2]
    # Стандартизируем категорию (убираем лишние пробелы, приводим к нужному регистру)
    category = category.strip()
    
    await state.update_data(employee_category=category)
    
    # Отладочный вывод
    logger.info(f"Выбрана категория: '{category}'")
    
    user_data = await state.get_data()
    await callback.message.edit_text(
        f"Шаг 6/7: Выбрана площадка: {user_data['location']}, "
        f"участок: {user_data['department']}, дата: {user_data['shift_date']}, "
        f"время: {user_data['shift_time']}, сотрудников: {user_data['employees_needed']}, "
        f"категория: {category}\n\n"
        "Введите примечание к заявке (например, 'горячая линия', 'срочный заказ') "
        "или отправьте /skip, чтобы пропустить этот шаг:"
    )
    
    await state.set_state(ShiftRequest.waiting_for_note)
    await callback.answer()



@router.message(ShiftRequest.waiting_for_note, Command("skip"))
async def skip_note(message: Message, state: FSMContext):
    await state.update_data(note="")
    await confirm_request(message, state)

@router.message(ShiftRequest.waiting_for_note)
async def process_note(message: Message, state: FSMContext):
    note = message.text
    await state.update_data(note=note)
    await confirm_request(message, state)

async def confirm_request(message: Message, state: FSMContext):
    user_data = await state.get_data()
    
    confirmation_text = (
        "Пожалуйста, подтвердите заявку:\n\n"
        f"🏭 Площадка: {user_data['location']}\n"
        f"🔧 Участок: {user_data['department']}\n"
        f"📅 Дата: {user_data['shift_date']}\n"
        f"⏰ Время: {user_data['shift_time']}\n"
        f"👥 Требуется сотрудников: {user_data['employees_needed']}\n"
        f"👤 Категория персонала: {user_data['employee_category']}\n"
    )
    
    if user_data.get('note'):
        confirmation_text += f"📝 Примечание: {user_data['note']}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_yes"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="confirm_no")
        ]
    ])
    
    await message.answer(confirmation_text, reply_markup=keyboard)
    await state.set_state(ShiftRequest.confirm_request)

@router.callback_query(ShiftRequest.confirm_request, F.data == "confirm_no")
async def cancel_request(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Создание заявки отменено.")
    await state.clear()
    await callback.answer()

@router.callback_query(ShiftRequest.confirm_request, F.data == "confirm_yes")
async def process_confirmation(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    creator_id = callback.from_user.id
    
    # Создаем заявку в базе данных
    request_id = create_shift_request(
        creator_id=creator_id,
        location=user_data['location'],
        department=user_data['department'],
        shift_date=user_data['shift_date'],
        shift_time=user_data['shift_time'],
        employees_needed=user_data['employees_needed'],
        employee_category=user_data['employee_category'],
        note=user_data.get('note', '')
    )
    
    await callback.message.edit_text(
        f"✅ Заявка #{request_id} успешно создана!\n\n"
        "Начинаем рассылку уведомлений сотрудникам..."
    )
    
    # Диагностика: проверяем, какие категории есть в базе
    category = user_data['employee_category']
    logger.info(f"Ищем сотрудников категории: '{category}'")
    
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, full_name, category FROM users WHERE category IS NOT NULL")
    all_users = cursor.fetchall()
    conn.close()
    
    logger.info(f"Все пользователи с категориями в базе:")
    for uid, name, cat in all_users:
        logger.info(f"- ID: {uid}, Имя: {name}, Категория: '{cat}'")
    
    # Получаем список сотрудников нужной категории
    employees = get_users_by_category(user_data['employee_category'])
    
    logger.info(f"Найдено сотрудников категории '{category}': {len(employees)}")
    logger.info(f"Список ID сотрудников: {employees}")
    
    if not employees:
        await callback.message.answer(
            f"⚠️ В базе нет сотрудников категории {user_data['employee_category']}."
        )
        await state.clear()
        await callback.answer()
        return
    
    # Формируем сообщение для рассылки
    notification_text = (
        f"🔔 Срочный вызов на смену!\n\n"
        f"📅 Дата: {user_data['shift_date']}\n"
        f"⏰ Время: {user_data['shift_time']}\n"
        f"🏭 Площадка: {user_data['location']}\n"
        f"🔧 Участок: {user_data['department']}\n"
    )
    
    if user_data.get('note'):
        notification_text += f"📝 Примечание: {user_data['note']}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готов выйти", callback_data=f"ready_{request_id}")]
    ])
    
    # Рассылаем уведомления
    sent_count = 0
    for employee_id in employees:
        try:
            await bot.send_message(
                chat_id=employee_id,
                text=notification_text,
                reply_markup=keyboard
            )
            sent_count += 1
            logger.info(f"Отправлено уведомление пользователю {employee_id}")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {employee_id}: {e}")
    
    await callback.message.answer(
        f"✅ Уведомления разосланы {sent_count} сотрудникам категории {user_data['employee_category']}.\n"
        f"Ожидаем отклики. Вы получите уведомление, когда наберется нужное количество сотрудников."
    )
    
    await state.clear()
    await callback.answer()


@router.callback_query(F.data.startswith("ready_"))
async def process_ready_response(callback: CallbackQuery):
    request_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    # Получаем информацию о заявке
    request_info = get_request_info(request_id)
    
    if not request_info:
        await callback.message.edit_text("⚠️ Заявка не найдена или была отменена.")
        await callback.answer()
        return
    
    if request_info['status'] != 'active':
        await callback.message.edit_text("⚠️ Эта заявка уже закрыта или отменена.")
        await callback.answer()
        return
    
    # Добавляем отклик в базу
    success = add_response(request_id, user_id)
    
    if not success:
        await callback.answer("Вы уже откликнулись на эту заявку", show_alert=True)
        return
    
    # Получаем информацию о пользователе
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,))
    user_info = cursor.fetchone()
    conn.close()
    
    user_name = user_info[0] if user_info else f"Пользователь {user_id}"
    
    # Обновляем информацию о заявке после добавления отклика
    updated_request = get_request_info(request_id)
    responses_count = updated_request['responses_count']
    employees_needed = updated_request['employees_needed']
    
    # Уведомляем пользователя
    if responses_count <= employees_needed:
        await callback.message.edit_text(
            f"🟢 Вы записаны на смену {updated_request['shift_date']} "
            f"({updated_request['shift_time']}), "
            f"Площадка {updated_request['location']}, "
            f"Участок {updated_request['department']}."
        )
    else:
        await callback.message.edit_text(
            f"ℹ️ Вы в резерве на смену {updated_request['shift_date']} "
            f"({updated_request['shift_time']}). "
            f"Если кто-то откажется — вам придёт уведомление."
        )
    
    # Получаем список откликнувшихся
    responses = get_responses_for_request(request_id)
    
    # Формируем сообщение для создателя
    creator_message = (
        f"👤 Новый отклик на заявку #{request_id}\n\n"
        f"Сотрудник: {user_name}\n"
        f"Всего откликнулось: {responses_count}/{employees_needed}\n\n"
        f"📅 Дата: {updated_request['shift_date']}\n"
        f"⏰ Время: {updated_request['shift_time']}\n"
        f"🏭 Площадка: {updated_request['location']}\n"
        f"🔧 Участок: {updated_request['department']}"
    )
    
    # Если набрали нужное количество сотрудников, добавляем список
    if responses_count >= employees_needed:
        creator_message += "\n\n✅ Набрано необходимое количество сотрудников!\n\nСписок сотрудников:\n"
        confirmed_users = [r for r in responses if r['status'] == 'confirmed']
        
        for i, user in enumerate(confirmed_users[:employees_needed], 1):
            creator_message += f"{i}. {user['full_name']}\n"
    
    # Добавляем кнопки для управления заявкой
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Управление заявкой", callback_data=f"manage_request_{request_id}")],
        [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_request_{request_id}")]
    ])
    
    try:
        await bot.send_message(
            chat_id=updated_request['creator_id'],
            text=creator_message,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления создателю заявки: {e}")
    
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_request_"))
async def cancel_shift_request(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    request_id = int(callback.data.split("_")[2])
    
    # Получаем информацию о заявке
    request_info = get_request_info(request_id)
    
    if not request_info:
        await callback.message.edit_text("⚠️ Заявка не найдена.")
        await callback.answer()
        return
    
    # Обновляем статус заявки
    update_request_status(request_id, 'cancelled')
    
    await callback.message.edit_text(
        f"❌ Заявка #{request_id} отменена.\n"
        "Уведомляем всех откликнувшихся сотрудников..."
    )
    
    # Получаем список откликнувшихся сотрудников
    responses = get_responses_for_request(request_id)
    
    # Уведомляем всех откликнувшихся об отмене
    cancellation_message = (
        f"❌ Заявка на смену отменена!\n\n"
        f"📅 Дата: {request_info['shift_date']}\n"
        f"⏰ Время: {request_info['shift_time']}\n"
        f"🏭 Площадка: {request_info['location']}\n"
        f"🔧 Участок: {request_info['department']}"
    )
    
    for response in responses:
        try:
            await bot.send_message(
                chat_id=response['user_id'],
                text=cancellation_message
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления об отмене пользователю {response['user_id']}: {e}")
    
    await callback.answer("Заявка отменена, сотрудники уведомлены", show_alert=True)

@router.callback_query(F.data == "my_requests")
async def show_my_requests(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not is_admin(user_id):
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    # Получаем активные заявки пользователя
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, location, department, shift_date, shift_time, 
               employees_needed, employee_category
        FROM requests 
        WHERE creator_id = ? AND status = 'active'
        ORDER BY created_at DESC
    """, (user_id,))
    
    requests = cursor.fetchall()
    conn.close()
    
    if not requests:
        await callback.message.edit_text(
            "У вас нет активных заявок на смену.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Создать заявку", callback_data="create_request")]
            ])
        )
        await callback.answer()
        return
    
    text = "Ваши активные заявки на смену:\n\n"
    
    keyboard = []
    for req in requests:
        req_id, location, department, shift_date, shift_time, employees_needed, category = req
        
        # Получаем количество откликов
        request_info = get_request_info(req_id)
        responses_count = request_info['responses_count']
        
        text += (
            f"Заявка #{req_id}\n"
            f"📅 {shift_date}, ⏰ {shift_time}\n"
            f"🏭 {location}, 🔧 {department}\n"
            f"👥 {responses_count}/{employees_needed} ({category})\n\n"
        )
        
        keyboard.append([
            InlineKeyboardButton(
                text=f"Управление заявкой #{req_id}", 
                callback_data=f"manage_request_{req_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton(text="Создать новую заявку", callback_data="create_request")])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("manage_request_"))
async def manage_request(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет доступа к этой функции", show_alert=True)
        return
    
    request_id = int(callback.data.split("_")[2])
    
    # Получаем информацию о заявке
    request_info = get_request_info(request_id)
    
    if not request_info or request_info['status'] != 'active':
        await callback.message.edit_text(
            "Заявка не найдена или была отменена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Назад к списку заявок", callback_data="my_requests")]
            ])
        )
        await callback.answer()
        return
    
    # Получаем список откликнувшихся
    responses = get_responses_for_request(request_id)
    
    text = (
        f"Управление заявкой #{request_id}\n\n"
        f"📅 Дата: {request_info['shift_date']}\n"
        f"⏰ Время: {request_info['shift_time']}\n"
        f"🏭 Площадка: {request_info['location']}\n"
        f"🔧 Участок: {request_info['department']}\n"
        f"👥 Требуется: {request_info['employees_needed']} ({request_info['employee_category']})\n"
    )
    
    if request_info.get('note'):
        text += f"📝 Примечание: {request_info['note']}\n"
    
    text += f"\nОткликнулось: {len(responses)}/{request_info['employees_needed']}\n\n"
    
    if responses:
        text += "Список откликнувшихся:\n"
        for i, response in enumerate(responses, 1):
            status_emoji = "🟢" if response['status'] == 'confirmed' else "⚪️"
            text += f"{i}. {status_emoji} {response['full_name']}\n"
    else:
        text += "Пока никто не откликнулся на заявку."
    
    keyboard = [
        [InlineKeyboardButton(text="❌ Отменить заявку", callback_data=f"cancel_request_{request_id}")],
        [InlineKeyboardButton(text="Назад к списку заявок", callback_data="my_requests")]
    ]
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@router.message(Command("normalize_categories"))
async def cmd_normalize_categories(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    # Получаем все уникальные категории
    cursor.execute("SELECT DISTINCT category FROM users WHERE category IS NOT NULL")
    categories = [row[0] for row in cursor.fetchall() if row[0]]
    
    # Словарь для нормализации категорий
    normalized = {
        "кладовщики": "Кладовщики",
        "операторы": "Операторы",
        "сборщики": "Сборщики",
        "наладчики": "Наладчики",
        "механики": "Механики",
        "настройщики": "Настройщики"
    }
    
    updated_count = 0
    
    for category in categories:
        # Нормализуем категорию
        category_lower = category.strip().lower()
        if category_lower in normalized and category != normalized[category_lower]:
            # Обновляем категорию
            cursor.execute(
                "UPDATE users SET category = ? WHERE LOWER(TRIM(category)) = ?", 
                (normalized[category_lower], category_lower)
            )
            updated_count += cursor.rowcount
    
    conn.commit()
    conn.close()
    
    await message.answer(f"Нормализация категорий завершена. Обновлено записей: {updated_count}")

@router.message(Command("fix_category"))
async def cmd_fix_category(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "Пожалуйста, укажите ID пользователя и категорию.\n"
            "Пример: /fix_category 123456789 Кладовщики"
        )
        return
    
    try:
        user_id = int(args[1])
        category = ' '.join(args[2:]).strip()
        
        conn = sqlite3.connect('shift_call.db')
        cursor = conn.cursor()
        
        # Проверяем, существует ли пользователь
        cursor.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            await message.answer(f"Пользователь с ID {user_id} не найден в базе данных.")
            conn.close()
            return
        
        # Обновляем категорию
        cursor.execute("UPDATE users SET category = ? WHERE user_id = ?", (category, user_id))
        conn.commit()
        
        # Проверяем, что категория обновлена
        cursor.execute("SELECT category FROM users WHERE user_id = ?", (user_id,))
        updated_category = cursor.fetchone()[0]
        conn.close()
        
        await message.answer(
            f"✅ Категория для пользователя {user[0]} (ID: {user_id}) обновлена:\n"
            f"Новая категория: {updated_category}"
        )
        
    except ValueError:
        await message.answer("Ошибка: ID пользователя должен быть числом.")
    except Exception as e:
        await message.answer(f"Произошла ошибка: {e}")
        logger.error(f"Ошибка при обновлении категории: {e}", exc_info=True)


# Команда для регистрации администраторов (только для существующих админов)
@router.message(Command("add_admin"))
async def cmd_add_admin(message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    # Проверяем, есть ли в сообщении упоминание пользователя
    if not message.entities or not message.text:
        await message.answer(
            "Пожалуйста, укажите пользователя, которого нужно сделать администратором.\n"
            "Пример: /add_admin @username"
        )
        return
    
    # Ищем упоминание пользователя
    username = None
    for entity in message.entities:
        if entity.type == "mention":
            username = message.text[entity.offset+1:entity.offset+entity.length]
            break
    
    if not username:
        await message.answer(
            "Пожалуйста, укажите пользователя через @username.\n"
            "Пример: /add_admin @username"
        )
        return
    
    # Проверяем, есть ли пользователь в базе
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    
    if not result:
        await message.answer(f"Пользователь @{username} не найден в базе данных.")
        conn.close()
        return
    
    target_user_id = result[0]
    
    # Делаем пользователя администратором
    cursor.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (target_user_id,))
    conn.commit()
    conn.close()
    
    await message.answer(f"Пользователь @{username} теперь администратор.")

# Команда для добавления категории сотрудника (для администраторов)
@router.message(Command("set_employee_category"))
async def cmd_set_employee_category(message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "Пожалуйста, укажите пользователя и категорию.\n"
            "Пример: /set_employee_category @username Операторы"
        )
        return
    
    username = args[1]
    if username.startswith('@'):
        username = username[1:]
    
    category = args[2]
    
    # Проверяем, есть ли пользователь в базе
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id, full_name FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    
    if not result:
        await message.answer(f"Пользователь @{username} не найден в базе данных.")
        conn.close()
        return
    
    target_user_id, full_name = result
    
    # Обновляем категорию сотрудника
    cursor.execute("UPDATE users SET category = ? WHERE user_id = ?", (category, target_user_id))
    conn.commit()
    conn.close()
    
    await message.answer(f"Категория для {full_name} (@{username}) установлена: {category}")

# Команда для просмотра статистики по категориям
@router.message(Command("stats"))
async def cmd_stats(message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    # Получаем статистику по категориям
    cursor.execute("""
        SELECT category, COUNT(*) as count
        FROM users
        WHERE category IS NOT NULL
        GROUP BY category
        ORDER BY count DESC
    """)
    
    categories_stats = cursor.fetchall()
    
    # Получаем общее количество пользователей
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    # Получаем количество пользователей без категории
    cursor.execute("SELECT COUNT(*) FROM users WHERE category IS NULL")
    no_category = cursor.fetchone()[0]
    
    conn.close()
    
    if not categories_stats:
        await message.answer("В базе данных нет пользователей с указанной категорией.")
        return
    
    text = "📊 Статистика по категориям сотрудников:\n\n"
    
    for category, count in categories_stats:
        text += f"{category}: {count} чел.\n"
    
    text += f"\nБез категории: {no_category} чел.\n"
    text += f"Всего пользователей: {total_users} чел."
    
    await message.answer(text)

@router.message(Command("debug_db"))
async def cmd_debug_db(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    # Проверяем таблицу users
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE category IS NOT NULL")
    users_with_category = cursor.fetchone()[0]
    
    # Получаем все категории
    cursor.execute("SELECT category, COUNT(*) FROM users WHERE category IS NOT NULL GROUP BY category")
    categories = cursor.fetchall()
    
    # Проверяем конкретно категорию "Кладовщики"
    cursor.execute("SELECT user_id, full_name, category FROM users WHERE category LIKE '%ладов%'")
    warehousemen = cursor.fetchall()
    
    conn.close()
    
    report = (
        f"📊 Диагностика базы данных:\n\n"
        f"Всего пользователей: {total_users}\n"
        f"Пользователей с категорией: {users_with_category}\n\n"
        f"Распределение по категориям:\n"
    )
    
    for cat, count in categories:
        report += f"- {cat}: {count} чел.\n"
    
    report += "\nПользователи с категорией 'Кладовщики' (поиск по части слова):\n"
    if warehousemen:
        for uid, name, cat in warehousemen:
            report += f"- {name} (ID: {uid}, категория: '{cat}')\n"
    else:
        report += "Не найдено\n"
    
    await message.answer(report)


@router.message(Command("add_employee"))
async def cmd_add_employee(message: Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    # Проверяем формат команды
    args = message.text.split()
    if len(args) < 4:
        await message.answer(
            "Пожалуйста, укажите ID пользователя, имя и категорию.\n"
            "Пример: /add_employee 123456789 Иванов_Иван Операторы"
        )
        return
    
    try:
        # Явно преобразуем ID в целое число
        employee_id = int(args[1])
        full_name = args[2].replace('_', ' ')
        
        # Собираем все оставшиеся аргументы как категорию (если категория содержит пробелы)
        category = ' '.join(args[3:]).strip()
        
        logger.info(f"Добавление сотрудника: ID={employee_id}, Имя={full_name}, Категория={category}")
        
        # Добавляем пользователя в базу
        conn = sqlite3.connect('shift_call.db')
        cursor = conn.cursor()
        
        # Проверяем, существует ли пользователь
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (employee_id,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            # Обновляем существующего пользователя
            cursor.execute(
                "UPDATE users SET full_name = ?, category = ? WHERE user_id = ?",
                (full_name, category, employee_id)
            )
            logger.info(f"Обновлен существующий пользователь: ID={employee_id}")
        else:
            # Добавляем нового пользователя
            cursor.execute(
                "INSERT INTO users (user_id, username, full_name, category, is_admin) VALUES (?, ?, ?, ?, ?)",
                (employee_id, "", full_name, category, 0)
            )
            logger.info(f"Добавлен новый пользователь: ID={employee_id}")
        
        conn.commit()
        
        # Проверяем, что пользователь действительно добавлен с правильной категорией
        cursor.execute("SELECT user_id, full_name, category FROM users WHERE user_id = ?", (employee_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            await message.answer(
                f"✅ Сотрудник успешно добавлен/обновлен:\n"
                f"ID: {result[0]}\n"
                f"Имя: {result[1]}\n"
                f"Категория: {result[2]}"
            )
        else:
            await message.answer(
                f"⚠️ Возникла проблема при добавлении сотрудника. Проверьте логи."
            )
    except ValueError:
        await message.answer("Ошибка: ID пользователя должен быть числом.")
    except Exception as e:
        await message.answer(f"Произошла ошибка при добавлении сотрудника: {e}")
        logger.error(f"Ошибка при добавлении сотрудника: {e}", exc_info=True)



@router.message(Command("check_category"))
async def cmd_check_category(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /check_category Категория")
        return
    
    category = args[1]
    
    conn = sqlite3.connect('shift_call.db')
    cursor = conn.cursor()
    
    # Проверяем точное совпадение
    cursor.execute("SELECT user_id, full_name FROM users WHERE category = ?", (category,))
    exact_matches = cursor.fetchall()
    
    # Проверяем без учета регистра
    cursor.execute("SELECT user_id, full_name FROM users WHERE category COLLATE NOCASE = ? COLLATE NOCASE", (category,))
    case_insensitive_matches = cursor.fetchall()
    
    conn.close()
    
    response = f"Результаты поиска для категории '{category}':\n\n"
    
    if exact_matches:
        response += "Точные совпадения:\n"
        for user_id, name in exact_matches:
            response += f"- {name} (ID: {user_id})\n"
    else:
        response += "Точных совпадений не найдено.\n"
    
    if len(case_insensitive_matches) > len(exact_matches):
        response += "\nСовпадения без учета регистра:\n"
        for user_id, name in case_insensitive_matches:
            if (user_id, name) not in exact_matches:
                response += f"- {name} (ID: {user_id})\n"
    
    await message.answer(response)

@router.message(Command("check_user"))
async def cmd_check_user(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет доступа к этой команде.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /check_user ID")
        return
    
    try:
        check_id = int(args[1])
        
        conn = sqlite3.connect('shift_call.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id, full_name, category FROM users WHERE user_id = ?", (check_id,))
        user_info = cursor.fetchone()
        
        conn.close()
        
        if user_info:
            await message.answer(
                f"Информация о пользователе:\n"
                f"ID: {user_info[0]} (тип: {type(user_info[0])})\n"
                f"Имя: {user_info[1]}\n"
                f"Категория: {user_info[2]}"
            )
            
            # Пробуем отправить тестовое сообщение
            try:
                await bot.send_message(
                    chat_id=check_id,
                    text="Это тестовое сообщение для проверки работы уведомлений."
                )
                await message.answer("✅ Тестовое сообщение успешно отправлено пользователю.")
            except Exception as e:
                await message.answer(f"❌ Ошибка при отправке тестового сообщения: {e}")
        else:
            await message.answer(f"Пользователь с ID {check_id} не найден в базе данных.")
    
    except ValueError:
        await message.answer("Ошибка: ID пользователя должен быть числом.")
    except Exception as e:
        await message.answer(f"Произошла ошибка: {e}")


# Команда для помощи
@router.message(Command("help"))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    
    if is_admin(user_id):
        help_text = (
            "🔍 Справка по командам бота 'Срочный вызов на смену':\n\n"
            "Для администраторов:\n"
            "/start - начать работу с ботом\n"
            "/add_admin @username - добавить администратора (пользователь должен уже взаимодействовать с ботом)\n"
            "/add_employee ID Имя_Фамилия Категория - добавить сотрудника\n"
            "/set_employee_category @username Категория - установить/обновить категорию сотрудника (пользователь должен уже взаимодействовать с ботом)\n"
            "/stats - просмотр статистики по категориям\n"
            "/help - показать эту справку\n\n"
            "Используйте кнопки в меню для создания и управления заявками на смену."
        )
    else:
        help_text = (
            "🔍 Справка по командам бота 'Срочный вызов на смену':\n\n"
            "/start - начать работу с ботом\n"
            "/help - показать эту справку\n\n"
            "Через этого бота вы будете получать уведомления о срочных вызовах на смену."
        )
    
    await message.answer(help_text)


# Обработчик неизвестных команд
# На этот код:
@router.message(lambda message: message.text and message.text.startswith('/'))
async def unknown_command(message: Message):
    await message.answer(
        "Неизвестная команда. Используйте /help для просмотра доступных команд."
    )

# Обработчик для текстовых сообщений
@router.message(F.text)
async def handle_text(message: Message):
    await message.answer(
        "Используйте команду /start для начала работы с ботом или /help для просмотра справки."
    )

# Функция запуска бота
async def main():
    # Инициализация базы данных
    init_db()
    
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

