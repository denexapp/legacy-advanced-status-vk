import asyncio
from typing import Dict

import aiohttp
from yarl import URL

from app.botdata import BotData
from app.vk import Vk


class Bot:
    def __init__(self, group_id: str, group_access_token: str, loop: asyncio.AbstractEventLoop,
                 session: aiohttp.ClientSession):
        self._group_id = group_id  # type: str
        self._group_access_token = group_access_token  # type: str
        self._loop = loop  # type: asyncio.AbstractEventLoop
        self._session = session  # type: aiohttp.ClientSession
        self._vk = Vk(self._group_id, self._group_access_token, self._loop, self._session)  # type: Vk
        self._bot_data = BotData()  # type: BotData

    async def run_bot(self):
        self._loop.create_task(self._watch_vk_messages())

    async def _watch_vk_messages(self):
        async for message in self._vk.get_message():
            self._loop.create_task(self._handle_message(message))

    async def _handle_message(self, message: Dict):
        # description of message could be find there: https://vk.com/dev/objects/message
        user_id = str(message['user_id'])
        body = message['body']
        if not self._bot_data.is_user_exist(user_id):
            self._bot_data.add_user(user_id)
        user = self._bot_data.get_user(user_id)
        if not user.vk_token:
            token = self._extract_token(body, user_id)
            if token:
                self._bot_data.update_user(user_id, token)
                message = 'Отлично! Теперь напиши мне статус для установки.'
                await self._vk.messages_send_message(user_id, message)

            else:
                message = 'Для начала тебя нужно авторизовать. ' \
                          'Перейди по ссылке и пришли мне ссылку из адресной строки: \n' \
                          'https://oauth.vk.com/authorize?client_id=6386667&' \
                          'redirect_uri=https://oauth.vk.com/blank.html&' \
                          'scope=offline,status&response_type=token&v=5.74'
                await self._vk.messages_send_message(user_id, message)

        else:
            await self._vk.status_set_status(body, user.vk_token)
            message = 'Установил статус: {}'.format(body)
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
