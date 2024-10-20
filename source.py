from telethon import TelegramClient
from secret import API_ID, API_HASH, TOKEN
from telebot import TeleBot
from datetime import datetime
from json import dump, load
from random import uniform, randint


CLIENT = TelegramClient('one', API_ID, API_HASH)
BOT = TeleBot(TOKEN)
REQUESTS = []
NOISE = 0.3
MENU_BTNS = ('Создать 📝', 'Просмотр 📋', 'Удаление ❌', 'Архив 📦')
RETURN_BTN = ('В меню ↩️',)
TG_MAX_MSG_LEN = 3500
FILE_NAME = 'requests.json'
ARCHIVE_DIR = 'archive'
LAST_NOTIF_PROCESSOR = datetime.now()
NOTIF_TIME_DELTA = 30
LONG_SLEEP = 20
MAX_DAYS_OFFLINE = 30
LAST_SCHEDULE_UPDATE = datetime.now()
COEFS = (0.5,0.4,0.33,0.2,0.16,0.2,0.33,0.4,0.5,1,2,2,1,0.75,0.5,1,2,1,1.5,2,2,1.5,1,0.5)

# ----- TODO LIST -----
# Изменение расписания при выходе поста
# Code style - названия функций
# Запрос кастомных коэфов от пользователя


class RemovalRequest:
    """Класс для представления заявки на удаление подписчиков из канала."""

    def __init__(self, channel, desired, completed=0, coefs=COEFS):
        self.channel = channel
        self.desired = desired
        self.completed = completed
        self.coefs = list(coefs)
        self.schedule = [0] * 24
        self.create_schedule()

    def to_dict(self):
        """Преобразование заявки в словарь для сериализации."""
        return {
            "channel": self.channel,
            "desired": self.desired,
            "completed": self.completed,
            "coefs": self.coefs,
        }

    @classmethod
    def from_dict(cls, data):
        """Создание объекта заявки из словаря."""
        return cls(
            channel=data["channel"],
            desired=data["desired"],
            completed=data["completed"],
            coefs=data["coefs"],
        )

    @staticmethod
    def save_requests_to_file(requests, filename=FILE_NAME):
        """Сохранение всех заявок в файл."""
        data = [req.to_dict() for req in requests]
        with open(filename, 'w', encoding='utf-8') as f:
            dump(data, f, ensure_ascii=False, indent=4, separators=(',', ': '))

    @staticmethod
    def load_requests_from_file(filename=FILE_NAME):
        """Загрузка заявок из файла."""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = load(f)
                return [RemovalRequest.from_dict(item) for item in data]
        except FileNotFoundError:
            return []

    def create_schedule(self):
        """Создание почасового расписания удалений на основе коэффициентов и шума."""
        noisy_coefs = [uniform((1 - NOISE) * coef, (1 + NOISE) * coef) for coef in self.coefs]
        removal_per_coef = self.desired / sum(noisy_coefs)
        for i in range(24):
            self.schedule[i] = int(removal_per_coef * noisy_coefs[i])
        self.adjust_schedule()

    def adjust_schedule(self):
        """Корректировка расписания для достижения нужного количества удалений."""
        total_removals = sum(self.schedule)

        while total_removals != self.desired:
            hour_to_adjust = randint(0, 23)
            if total_removals < self.desired:
                self.schedule[hour_to_adjust] += 1
            elif total_removals > self.desired and self.schedule[hour_to_adjust] > 0:
                self.schedule[hour_to_adjust] -= 1
            total_removals = sum(self.schedule)

    def display_schedule_and_coefs(self):
        hours = [f"{hour:02}" for hour in range(24)]
        schedule_values = [f"{self.schedule[hour]:02}" for hour in range(24)]
        coef_values = [f"{self.coefs[hour]:.2f}" for hour in range(24)]

        rows = []
        for hour, schedule, coef in zip(hours, schedule_values, coef_values):
            rows.append(f"{hour} | {schedule} | {coef}")

        return "\n".join(rows)

    def __str__(self):
        return (f"🔊 Канал: {self.channel}\n"
                f"📅 План: {self.desired}\n"
                f"☑️ Удалено: {self.completed}\n"
                f"📖 Расписание и коэффициенты:\n{self.display_schedule_and_coefs()}")

print(RemovalRequest('ex', 1))
