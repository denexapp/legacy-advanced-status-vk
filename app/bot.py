import asyncio
from typing import Dict

import aiohttp
from yarl import URL

from app.botdata import BotData
from app.lastfm import LastFm
from app.lastfmdata import LastFmData
from app.vk import Vk


class Bot:
    def __init__(self, group_id: str, group_access_token: str, last_fm_api_key: str, last_fm_shared_secret: str,
                 loop: asyncio.AbstractEventLoop, session: aiohttp.ClientSession):
        self._group_id: str = group_id
        self._group_access_token: str = group_access_token
        self._loop: asyncio.AbstractEventLoop = loop
        self._session: aiohttp.ClientSession = session

        self._bot_data: BotData = BotData()
        self._last_fm_data: LastFmData = LastFmData()

        self._vk: Vk = Vk(self._group_id, self._group_access_token, self._loop, self._session)
        self._last_fm: LastFm = LastFm(last_fm_api_key, last_fm_shared_secret, self._last_fm_data,
                                       self._loop, self._session)

    async def run_bot(self):
        self._loop.create_task(self._watch_vk_messages())
        self._loop.create_task(self._watch_last_fm_tracks())

    async def _watch_vk_messages(self):
        async for message in self._vk.get_message():
            self._loop.create_task(self._handle_message(message))

    async def _watch_last_fm_tracks(self):
        async for user_id, track in self._last_fm.get_new_now_playing():
            self._loop.create_task(self._set_status(user_id, track))

    async def _set_status(self, user_id: str, track: LastFm.Track):
        if track:
            status = "Слушает {} - {}, vk.me/advancedstatus"\
                .format(track.artist, track.name)
        else:
            status = "vk.me/advancedstatus"
        await self._vk.status_set_status(status, self._bot_data.get_user(user_id).vk_token)

    async def _handle_message(self, message: Dict):
        # description of message could be find there: https://vk.com/dev/objects/message
        user_id: str = str(message['user_id'])
        body: str = message['body']
        if not self._bot_data.is_user_exist(user_id):
            self._bot_data.add_user(user_id)
        user = self._bot_data.get_user(user_id)
        if not user.vk_token:
            token = self._extract_token(body, user_id)
            if token:
                self._bot_data.update_user(user_id, token=token)
                message = 'Отлично, теперь ты можешь подключить аккаунт Last.Fm командой:\n' \
                          'setlastfm твой_ник'
                await self._vk.messages_send_message(user_id, message)
            else:
                message = 'Для начала тебя нужно авторизовать. ' \
                          'Перейди по ссылке и пришли мне ссылку из адресной строки: \n' \
                          'https://oauth.vk.com/authorize?client_id=6386667&' \
                          'redirect_uri=https://oauth.vk.com/blank.html&' \
                          'scope=offline,status&response_type=token&v=5.74'
                await self._vk.messages_send_message(user_id, message)
        elif body.startswith('setlastfm '):
            last_fm_id = body[10:]
            # todo transaction safe, data validation, sql injection awareness
            if user.last_fm_id:
                # remove old user
                previous_last_fm_user = self._last_fm_data.get_user(user.last_fm_id)
                vk_ids = previous_last_fm_user.vk_user_ids
                if len(vk_ids) == 1:
                    self._last_fm_data.remove(previous_last_fm_user.user_id)
                else:
                    vk_ids.remove(user.user_id)
                    self._last_fm_data.update_user(previous_last_fm_user.user_id, vk_user_ids=vk_ids)
                # add new
                if self._last_fm_data.is_user_exist(last_fm_id):
                    last_fm_user = self._last_fm_data.get_user(last_fm_id)
                    vk_ids = last_fm_user.vk_user_ids
                    vk_ids.append(user.user_id)
                    self._last_fm_data.update_user(last_fm_user.user_id, vk_user_ids=vk_ids)
                else:
                    self._last_fm_data.add_user(last_fm_id, user.user_id)
            else:
                self._last_fm_data.add_user(last_fm_id, user.user_id)
            self._bot_data.update_user(user.user_id, last_fm_id=last_fm_id)
            message = 'Добавил {} для пользователя {}'.format(last_fm_id, user.user_id)
            await self._vk.messages_send_message(user.user_id, message)
        elif body.startswith('unsetlastfm'):
            # todo transaction safe
            if user.last_fm_id:
                last_fm_user = self._last_fm_data.get_user(user.last_fm_id)
                vk_ids = last_fm_user.vk_user_ids
                if len(vk_ids) == 1:
                    self._last_fm_data.remove(last_fm_user.user_id)
                else:
                    vk_ids.remove(user.user_id)
                    self._last_fm_data.update_user(last_fm_user.user_id, vk_user_ids=vk_ids)
                last_fm_id = user.last_fm_id
                self._bot_data.none_user(user_id, last_fm_id=True)
                message = 'Отвязал профиль last.fm {}.'.format(last_fm_id)
                await self._vk.messages_send_message(user_id, message)
            else:
                message = 'У тебя нет привязанного профиля last.fm, так что мне нечего отвязывать.'
                await self._vk.messages_send_message(user_id, message)
        elif body.startswith('forget'):
            pass
        else:
            message = 'Я тебя не понимаю.\n' \
                      'Доступные команды:\n' \
                      'setlastfm имя_аккаунта_last_fm\n' \
                      'unsetlastfm'
            await self._vk.messages_send_message(user_id, message)

    def _extract_token(self, url: str, user_id: str) -> str:
        url = URL(url)
        if url.scheme != 'https':
            return None
        elif url.host is None:
            return None
        elif url.host != 'oauth.vk.com':
            return None
        elif url.path != '/blank.html':
            return None
        elif url.fragment == '':
            return None
        elif url.query_string != '':
            return None
        query = url.with_query(url.fragment).query
        if 'access_token' not in query:
            return None
        elif query['access_token'] == '':
            return None
        elif 'expires_in' not in query:
            return None
        elif query['expires_in'] != '0':
            return None
        elif 'user_id' not in query:
            return None
        elif query['user_id'] != user_id:
            return None
        return query['access_token']

