from datetime import datetime, timedelta
from source import (RemovalRequest, BOT, MENU_BTNS, RETURN_BTN, TG_MAX_MSG_LEN, ARCHIVE_DIR,
                    NOTIF_TIME_DELTA, LONG_SLEEP, MAX_DAYS_OFFLINE, CLIENT, FILE_NAME)
from traceback import format_exc
from asyncio import run, get_event_loop, create_task, gather
from threading import Thread
from common import ShowButtons, Stamp, AsyncSleep
import source
from telebot.apihelper import ApiException
from os.path import join, exists
from os import makedirs
from secret import ADM_IDS, PASSWORD, PHONE
from telethon.tl.types import UserStatusOffline, UserStatusLastMonth
from telethon.errors.rpcerrorlist import ChatAdminRequiredError
from random import sample
from pytz import utc


def BotPolling():
    while True:
        try:
            BOT.polling(none_stop=True, interval=1)
        except Exception as e:
            Stamp(f'{e}', 'e')
            Stamp(format_exc(), 'e')


def SendRequests(user_id, list_of_requests):
    msg = ''
    cnt = 1
    if not list_of_requests:
        BOT.send_message(user_id, '💤 Нет заявок')
        return
    for req in list_of_requests:
        msg += f'––––– {cnt} –––––\n'
        cnt += 1
        msg += str(req)
        if len(msg) > TG_MAX_MSG_LEN:
            BOT.send_message(user_id, msg, parse_mode='HTML')
            msg = ''
    if msg:
        BOT.send_message(user_id, msg, parse_mode='HTML')


async def Main():
    await CLIENT.start(phone=PHONE, password=PASSWORD)
    source.REQUESTS = RemovalRequest.load_requests_from_file()
    loop = get_event_loop()
    unsubscribe = create_task(ProcessRequests())
    try:
        await gather(unsubscribe)
    finally:
        loop.stop()
        loop.close()


def sendToMultipleUsers(user_ids, message):
    for user in user_ids:
        BOT.send_message(user, message)


async def ProcessRequests():
    while True:
        try:
            now = datetime.now()
            Stamp('Pending requests', 'i')
            if source.LAST_SCHEDULE_UPDATE.date() < now.date():
                Stamp('Updating schedules and archiving the previous day', 'i')
                await MakeArchive()
                for req in source.REQUESTS:
                    req.create_schedule()
                source.LAST_SCHEDULE_UPDATE = now
            if now - source.LAST_NOTIF_PROCESSOR > timedelta(minutes=NOTIF_TIME_DELTA):
                Stamp('Sending notification about proper work', 'i')
                sendToMultipleUsers(ADM_IDS, '📤 ProcessRequests OK')
                source.LAST_NOTIF_PROCESSOR = datetime.now()
            for req in source.REQUESTS:
                now = datetime.now()
                start_of_day = datetime(now.year, now.month, now.day)
                seconds_passed = (now - start_of_day).total_seconds()
                hours_passed = int(seconds_passed // 3600)
                remaining_seconds = seconds_passed % 3600
                expected = sum(req.schedule[:hours_passed]) + int(remaining_seconds / 3600 * req.schedule[hours_passed])
                to_add = expected - req.completed
                Stamp(f'For channel {req.channel} expected = {expected}, to_add = {to_add}, hours_passed = {hours_passed}, remaining = {remaining_seconds}', 'i')
                if to_add > 0:
                    try:
                        successfully_deleted = await DeleteUsers(req, to_add)
                        req.completed += successfully_deleted
                    except ChatAdminRequiredError:
                        Stamp(f'Need to set account as an admin in channel {req.channel}', 'w')
                        sendToMultipleUsers(ADM_IDS, f'❗️Назначьте аккаунт {PHONE} администратором в канале {req.channel}')
        except Exception as e:
            Stamp(f'Uncaught exception in processor happened: {e}', 'w')
            sendToMultipleUsers(ADM_IDS, f'🔴 Ошибка в ProcessRequests: {e}')
        RemovalRequest.save_requests_to_file(source.REQUESTS)
        await AsyncSleep(LONG_SLEEP)


async def MakeArchive():
    yesterday = datetime.now() - timedelta(days=1)
    archive_dir = join('archive', str(yesterday.year), str(yesterday.month), str(yesterday.day))
    makedirs(archive_dir, exist_ok=True)
    file_path = join(archive_dir, 'requests.json')
    RemovalRequest.save_requests_to_file(source.REQUESTS, file_path)
    Stamp(f'Archived requests to {file_path}', 'i')


async def DeleteUsers(req, to_add, client=source.CLIENT):
    successfully_deleted = 0

    async for user in client.iter_participants(req.channel):
        if to_add <= 0:
            break

        if user.deleted:
            await client.kick_participant(req.channel, user)
            Stamp(f'Deleted account was removed from channel {req.channel}', 'i')
            to_add -= 1
            successfully_deleted += 1
            continue

        last_seen = user.status
        if isinstance(last_seen, UserStatusOffline):
            if last_seen.was_online:
                now_utc = datetime.now(utc)
                last_online_utc = last_seen.was_online.astimezone(utc)
                days_offline = (now_utc - last_online_utc).days
                if days_offline > MAX_DAYS_OFFLINE:
                    await client.kick_participant(req.channel, user)
                    Stamp(f'Offline account was removed from channel {req.channel}', 'i')
                    to_add -= 1
                    successfully_deleted += 1
                    continue

        elif isinstance(last_seen, UserStatusLastMonth):
            await client.kick_participant(req.channel, user)
            Stamp(f'Account inactive for a month was removed from channel {req.channel}', 'i')
            to_add -= 1
            successfully_deleted += 1
            continue

    if to_add > 0:
        users = await client.get_participants(req.channel)
        random_users = sample(users, min(to_add, len(users)))
        for user in random_users:
            await client.kick_participant(req.channel, user)
            to_add -= 1
            successfully_deleted += 1
            Stamp(f'Random account was removed from channel {req.channel}', 'i')
            if to_add <= 0:
                break

    return successfully_deleted


def CreateRequest(message):
    if message.text == RETURN_BTN[0]:
        ShowButtons(message, MENU_BTNS, '❔ Выберите действие:')
        return
    channel = message.text.strip()
    if channel.startswith('https://t.me/'):
        channel = '@' + channel.split('/')[-1]
    elif not channel.startswith('@'):
        channel = '@' + channel
    try:
        chat = BOT.get_chat(channel)
        if chat.type == 'channel':
            ShowButtons(message, RETURN_BTN, f'✅ Канал {chat.title} найден! Введите желаемое количество удалений в день:')
            BOT.register_next_step_handler(message, SetDesiredRemoval, channel)
        else:
            BOT.send_message(message.from_user.id, '❌ Это не канал. Введите правильную ссылку на канал.')
            BOT.register_next_step_handler(message, CreateRequest)
    except ApiException:
        BOT.send_message(message.from_user.id, '❌ Канал не найден. Проверьте правильность ссылки или имени канала.')
        BOT.register_next_step_handler(message, CreateRequest)


def SetDesiredRemoval(message, channel):
    if message.text == RETURN_BTN[0]:
        ShowButtons(message, MENU_BTNS, '❔ Выберите действие:')
        return
    try:
        desired = int(message.text)
        if desired > 0:
            request = RemovalRequest(channel[1:], desired)
            request.create_schedule()
            source.REQUESTS.append(request)
            RemovalRequest.save_requests_to_file(source.REQUESTS)
            BOT.send_message(message.from_user.id, '✅ Заявка успешно создана!')
        else:
            BOT.send_message(message.from_user.id, '❌ Количество должно быть положительным числом.')
            BOT.register_next_step_handler(message, SetDesiredRemoval)
    except ValueError:
        BOT.send_message(message.from_user.id, '❌ Введите корректное число.')
        BOT.register_next_step_handler(message, SetDesiredRemoval)
    ShowButtons(message, MENU_BTNS, '❔ Выберите действие:')


def DeleteRequest(message):
    if message.text == RETURN_BTN[0]:
        ShowButtons(message, MENU_BTNS, '❔ Выберите действие:')
        return
    channel = message.text.strip()
    found = False
    for req in source.REQUESTS:
        if req.channel == channel:
            source.REQUESTS.remove(req)
            found = True
            RemovalRequest.save_requests_to_file(source.REQUESTS)
            BOT.send_message(message.from_user.id, f'✅ Заявка для канала {channel} удалена.')
            break
    if not found:
        BOT.send_message(message.from_user.id, f'❌ Заявка для канала {channel} не найдена.')
    ShowButtons(message, MENU_BTNS, '❔ Выберите действие:')


def ShowFromArchive(message):
    if message.text == RETURN_BTN[0]:
        ShowButtons(message, MENU_BTNS, '❔ Выберите действие:')
        return
    date_str = message.text.strip()
    try:
        date_obj = datetime.strptime(date_str, '%d.%m.%Y')
    except ValueError:
        BOT.send_message(message.from_user.id, '❌ Неверный формат даты! Введите дату в формате ДД.ММ.ГГГГ.')
        BOT.register_next_step_handler(message, ShowFromArchive)
        return
    year = date_obj.strftime('%Y')
    month = date_obj.strftime('%m')
    day = date_obj.strftime('%d')
    archive_path = join(ARCHIVE_DIR, year, month, day, FILE_NAME)
    if exists(archive_path):
        BOT.send_message(message.from_user.id, f'📂 Архив за {date_str} найден.')
        archive = RemovalRequest.load_requests_from_file(archive_path)
        SendRequests(message.from_user.id, archive)
    else:
        BOT.send_message(message.from_user.id, f'❌ Архив за {date_str} не найден.')
    ShowButtons(message, MENU_BTNS, '❔ Выберите действие:')


@BOT.message_handler(content_types=['text'])
def MessageAccept(message) -> None:
    Stamp(f'User {message.from_user.username} requested {message.text}', 'i')
    if message.text == '/start':
        BOT.send_message(message.from_user.id, f'Привет, {message.from_user.first_name}!')
    elif message.text == MENU_BTNS[0]:
        ShowButtons(message, RETURN_BTN, '📝 Введите имя канала:')
        BOT.register_next_step_handler(message, CreateRequest)
        return
    elif message.text == MENU_BTNS[1]:
        SendRequests(message.from_user.id, source.REQUESTS)
    elif message.text == MENU_BTNS[2]:
        ShowButtons(message, RETURN_BTN, '📝 Введите имя канала:')
        BOT.register_next_step_handler(message, DeleteRequest)
        return
    elif message.text == MENU_BTNS[3]:
        ShowButtons(message, RETURN_BTN, '📝 Введите дату в формате ДД.ММ.ГГГГ:')
        BOT.register_next_step_handler(message, ShowFromArchive)
        return
    else:
        BOT.send_message(message.from_user.id, '❌ Я вас не понял...')
    ShowButtons(message, MENU_BTNS, '❔ Выберите действие:')


if __name__ == '__main__':
    Thread(target=BotPolling, daemon=True).start()
    run(Main())

