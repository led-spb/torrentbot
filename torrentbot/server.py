import http.server
import inspect
import logging
import json
import re
from http.server import HTTPServer
from typing import Union

import requests


class MessageHandler(object):
    def __init__(self, message_type='text'):
        self.message_type = message_type

    def pre_process(self, message):
        if self.message_type not in message:
            return False
        return True

    def __call__(self, func):
        def wrapped(this, message):
            if self.pre_process(message):
                arguments = []
                for arg in inspect.getargspec(func).args:
                    if arg == 'self':
                        arguments.append(this)
                    elif arg == 'message':
                        arguments.append(message)
                    elif arg in message:
                        arguments.append(message[arg])
                    else:
                        arguments.append(None)

                return func(*arguments)
            else:
                return False
        wrapped.is_handler = True
        return wrapped


class PatternMessageHandler(MessageHandler):
    def __init__(self, pattern):
        MessageHandler.__init__(self, 'text')
        self.pattern = re.compile(pattern)

    def pre_process(self, message):
        if not MessageHandler.pre_process(self, message):
            return False
        if self.pattern.match(message['text']) is not None:
            return True
        return False


class BotRequestHandler:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = f'https://api.telegram.org/bot{self.api_key}'
        self._commands = None

    @property
    def commands(self):
        if self._commands is not None:
            return self._commands
        self._commands = []
        for func_name in dir(self):
            func = getattr(self, func_name)
            if callable(func) and hasattr(func, 'is_handler'):
                self._commands.append(func)
        return self._commands

    def get_chat_id(self, message) -> Union[int, None]:
        return message.get('chat', {}).get('id')

    def send_message(self, chat_id, message, reply_markup=None, **extra):
        body = {'chat_id': chat_id, 'text': message}
        if reply_markup is not None:
            body['reply_markup'] = json.dumps(reply_markup)
        if extra is not None:
            body.update(extra)
        return self.send_request('sendMessage', body)

    def edit_message(self, chat_id, message_id, text, reply_markup=None, **extra):
        body = {'chat_id': chat_id, 'message_id': message_id, 'text': text}
        if reply_markup is not None:
            body['reply_markup'] = json.dumps(reply_markup)
        if extra is not None:
            body.update(extra)
        return self.send_request('editMessageText', body)

    def send_document(self, chat_id, document, **extra):
        body = {'chat_id': chat_id}
        if extra is not None:
            body.update(extra)
        return self.send_request('sendDocument', body, files={'document': document})

    def send_request(self, method, body, files=None):
        logging.debug(f'Telegram method call {method}: {body}')
        res = requests.post(f'{self.base_url}/{method}', files=files, data=body)
        logging.debug(res.text)
        res.raise_for_status()
        return res.json().get('result', {})


class TelegramWebhookServer(HTTPServer):
    def __init__(self, server_address: tuple[str, int], handler: BotRequestHandler = None) -> None:
        self.handlers = []
        if handler is not None:
            self.handlers.append(handler)
        super().__init__(server_address, TelegramBotHandler)

    def add_handler(self, handler: BotRequestHandler):
        self.handlers.append(handler)

    def exec_command(self, message):
        logging.debug(json.dumps(message, indent=2))
        for handler in self.handlers:
            for cmd_handler in handler.commands:
                if cmd_handler(message):
                    return True
        return False

    def process_update(self, update):
        if 'callback_query' in update:
            update['message'] = update['callback_query']['message']
            update['message']['text'] = update['callback_query']['data']

        if 'message' in update:
            message = update['message']
            if 'from' in message:
                user = message['from']

                message_type = list(
                    set(message.keys())
                    & {"text", "audio", "document", "photo", "sticker", "video", "voice", "contact", "location",
                       "venue", "game"})

                if "text" in message_type:
                    message_type = message["text"]
                else:
                    message_type = next(iter(message_type), "unknown")

                logging.info("message \"%s\" from %d/%s", message_type, user.get('id'), user.get('first_name'))
                try:
                    self.exec_command(message)
                except Exception:
                    logging.exception('Error while processing request')


class TelegramBotHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)
        update = json.loads(body)
        logging.info(json.dumps(update, indent=2))
        if isinstance(self.server, TelegramWebhookServer):
            try:
                self.server.process_update(update)
            except BaseException:
                logging.exception('Error while processing update')

        self.send_response(200)
        self.end_headers()
