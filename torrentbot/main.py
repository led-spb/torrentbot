import argparse
from dataclasses import asdict
from typing import List, Any

import requests
import logging
from jinja2 import Environment
from .server import TelegramWebhookServer, BotRequestHandler, PatternMessageHandler
from .trackers import RutrackerHelper, TorrentItem


class TorrentCommandHandler(BotRequestHandler):
    def __init__(self, api_key: str, clients: list):
        super().__init__(api_key)
        self.clients = clients
        self.tracker = RutrackerHelper()
        self.templates = {}
        self.jinja = Environment()
        self.cache = {}

    def authorized_chat_id(self, message):
        chat_id = self.get_chat_id(message)
        if chat_id not in self.clients:
            logging.warning(f'command from unauthorized id {chat_id}')
            return None
        return chat_id

    def format_item(self, item: TorrentItem):
        template = self.templates.get(item.__class__.__name__)
        if template is None:
            template = self.jinja.from_string(item.template)
            self.templates[item.__class__.__name__] = template
        return template.render(asdict(item))

    @PatternMessageHandler('/download_.*')
    def download(self, message):
        chat_id = self.authorized_chat_id(message)
        if not chat_id:
            return
        data = message.get('text').split('_')
        item_id = int(data[1])
        body = self.tracker.download(item_id)
        self.send_document(
            chat_id,
            (f'download_{item_id}.torrent', body),
            eply_to_message_id=message.get('message_id')
        )

    @PatternMessageHandler(pattern='/version')
    def version_command(self, message):
        chat_id = self.authorized_chat_id(message)
        if not chat_id:
            return
        self.send_message(chat_id, 'dummy version', reply_to_message_id=message.get('message_id'))

    @PatternMessageHandler(pattern='/show( .*)?')
    def pager(self, message):
        chat_id = self.authorized_chat_id(message)
        if not chat_id:
            return
        data = message.get('text').split()
        start = int(data[1])

        reply_message_id = message.get('message_id')
        items = self.cache.get(reply_message_id, [])
        self.show_response_pager(chat_id, reply_message_id, items, start)

    @PatternMessageHandler('[^/].*')
    def search(self, message):
        chat_id = self.authorized_chat_id(message)
        if not chat_id:
            return

        reply_message_id = self.send_message(
            chat_id, 'Search in progress', reply_to_message_id=message.get('message_id')
        ).get('message_id')

        try:
            items = self.tracker.search(message.get('text'))
            self.cache[reply_message_id] = items

            self.show_response_pager(chat_id, reply_message_id, items, 1)
        except BaseException:
            logging.exception('Error while searching')
            self.edit_message(chat_id, reply_message_id, 'Error occurred while processing request')
        return

    def show_response_pager(self, chat_id: int, message_id: int, items: List[Any], start: int, page_size: int = 5):
        if len(items) == 0:
            self.edit_message(chat_id, message_id, 'Sorry, nothing is found')
            return

        data = map(
            (lambda i: self.format_item(items[i])),
            range(start - 1, min(start + page_size - 1, len(items)))
        )
        message_text = u"\n".join(data)

        markup = None
        buttons = []
        if start > page_size:
            buttons.append({
                'text': f"Prev {page_size}/{start-1}",
                'callback_data': f'/show {start-page_size}'
            })
        if (start + page_size) < len(items):
            buttons.append({
                'text': f"Next {page_size}/{len(items)-start-page_size+1}",
                'callback_data': f'/show {start + page_size}'
            })
        if len(buttons) > 0:
            markup = {'inline_keyboard': [buttons]}

        self.edit_message(chat_id, message_id, message_text, parse_mode='HTML', reply_markup=markup)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-token', required=True)
    parser.add_argument('--port', type=int, default='8000')
    parser.add_argument('--secret-token', required=True)
    parser.add_argument('--webhook', required=True)
    parser.add_argument('--users', nargs='+', required=True)
    parser.add_argument('-v', action="store_true", default=False, help="Verbose logging", dest="verbose")
    args = parser.parse_args()

    logging.basicConfig(format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
                        level=logging.DEBUG if args.verbose else logging.INFO)

    # initialize webhook
    res = requests.post(f'https://api.telegram.org/bot{args.api_token}/setWebHook',
                        data={'url': args.webhook, 'secret_token': args.secret_token})
    res.raise_for_status()
    logging.info(f'Webhook successfully installed to {args.webhook}')
    logging.info(f'Authorized ids: {args.users}')

    handler = TorrentCommandHandler(args.api_token, [int(x) for x in args.users])

    httpd = TelegramWebhookServer(('', args.port), handler)
    httpd.serve_forever()


if __name__ == '__main__':
    main()
