import logging
import datetime
from dataclasses import dataclass
from typing import List
import lxml.html
import lxml.cssselect
from requests import Session
from http.cookiejar import CookieJar, MozillaCookieJar


class CookieStore:
    _cookiejar = MozillaCookieJar('.cookies')

    @property
    def cookiejar(self) -> CookieJar:
        CookieStore._cookiejar.load('.cookies')
        return CookieStore._cookiejar


@dataclass
class TorrentItem:
    id: str
    title: str
    category: str = None
    link: str = None
    created: datetime.datetime = None
    size: int = None
    seeds: int = None

    template = u"""<b>{{ title | e}}</b>
Раздел: {{ category | e }}
Размер: {{ size | filesizeformat }} ({{seeds}})
Скачать: /download_{{id}}

"""


class TrackerHelper:
    def __init__(self):
        self.session = Session()
        self.session.cookies = CookieStore().cookiejar

    def search(self, query) -> List[TorrentItem]:
        ...

    def download(self, item_id):
        ...


class RutrackerItemParser:
    def __init__(self, element):
        self.element = element

    @property
    def id(self):
        return self.element.get('data-topic_id')

    @property
    def title(self):
        nodes = self.element.cssselect('.t-title')
        node = nodes.pop() if len(nodes) else None
        return node.text_content().strip() if node is not None else None

    @property
    def category(self):
        nodes = self.element.cssselect('.t-title')
        node = nodes.pop() if len(nodes) else None
        return node.text_content().strip() if node is not None else None

    @property
    def size(self):
        nodes = self.element.cssselect('.tor-size')
        node = nodes.pop() if len(nodes) else None
        return (int(node.get('data-ts_text')) or 0) if node is not None else 0

    @property
    def seeds(self):
        nodes = self.element.cssselect('.seedmed')
        node = nodes.pop() if len(nodes) else None
        return int(node.text_content().strip() or 0) if node is not None else 0

    @property
    def created(self):
        nodes = self.element.cssselect('.td')
        node = nodes.pop() if len(nodes) else None
        return (int(node.get('data-ts_text')) or 0) if node is not None else 0


class RutrackerHelper(TrackerHelper):
    def search(self, query) -> List[TorrentItem]:
        response = self.session.post(
            'https://rutracker.org/forum/tracker.php',
            data={
                'f[]': -1,
                'o': 1,
                's': 2,
                'pn': None,
                'nm': f'"{query}"'}
        )
        response.raise_for_status()
        logging.debug(response.text)

        tree = lxml.html.fromstring(response.text)
        sel = lxml.cssselect.CSSSelector(u"tr[data-topic_id]")
        results = []
        for item in sel(tree):
            results.append(self.parse_item(item))
        return results

    def download(self, item_id):
        result = self.session.get(f'https://rutracker.org/forum/dl.php?t={item_id}')
        result.raise_for_status()
        return result.content

    def parse_item(self, element) -> TorrentItem:
        parser = RutrackerItemParser(element)
        return TorrentItem(
            id=parser.id,
            title=parser.title,
            category=parser.category,
            size=parser.size,
            seeds=parser.seeds,
            created=datetime.datetime.utcfromtimestamp(parser.created)
        )
