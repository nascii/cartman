import re
import logging
from datetime import datetime
import urllib

import requests
from peewee import *

class News(Model):
    ticker = CharField(5)
    id = IntegerField()
    date = TimestampField(utc=True, index=True)
    source = TextField(null=True)
    title = TextField()
    description = TextField(null=True)
    url = TextField(null=True)
    engagement = IntegerField(null=True)
    marked = BooleanField()

    class Meta:
        primary_key = CompositeKey('ticker', 'id')
        without_rowid = True

class Scraper:
    def __init__(self, db, ticker, continuation=''):
        self.db = db
        self.ticker = ticker
        self.continuation = continuation
        self.extracted = 0

        with Using(db, [News]):
            db.create_tables([News], safe=True)

    def scrape(self):
        with Using(self.db, [News], False):
            while self.continuation is not None:
                self._step()

    def _step(self):
        response = self._fetch()

        news = [self._extract_news(item) for item in response['items']]
        self.continuation = response.get('continuation')

        self.extracted += len(news)
        oldest = datetime.utcfromtimestamp(min(n['date'] for n in news))

        logging.info('Extracted {} (+{}) news, oldest: {}, continuation: {}'.format(
            self.extracted, len(news), oldest, self.continuation
        ))

        with self.db.atomic():
            for i in range(0, len(news), 100):
                News.insert_many(news[i:i+100]).on_conflict('IGNORE').execute()

    def _fetch(self):
        r = requests.get('http://cloud.feedly.com/v3/streams/contents', params={
            'streamId': 'feed/http://finance.yahoo.com/rss/headline?s=' + self.ticker,
            'count': 1000,
            'continuation': self.continuation
        })

        return r.json()

    def _extract_news(self, item):
        alt_href = item['alternate'][0]['href']
        summary = item['summary']['content'].strip() if 'summary' in item else None

        marked = item['title'].startswith('[$$]')
        title = (item['title'][len('[$$]'):] if marked else item['title']).strip()

        description = summary and re.sub(r'^\[.+?\]\s*-\s*', '', summary)

        match = re.search(r'finance/(news|external/(.+?))/', alt_href)
        source = match.group(2) or summary and re.search(r'^\[.+?\]', summary).group(0)

        url = item.get('canonicalUrl')
        if not url:
            match = re.search(r'(https?(:|%3A)//.+?)(\?|#|$)', alt_href[7:])

            # Broken url.
            if not match and 'finance/news/rss/story/*&' in alt_href:
                url = None
            else:
                url = match.group(1) if match.group(2) == ':' else urllib.parse.unquote(match.group(1))

        return {
            'ticker': self.ticker,
            'id': int(item['originId'][len('yahoo_finance/'):]),
            'date': item['published'] // 1000,
            'source': source,
            'title': title,
            'description': description,
            'url': url,
            'engagement': item.get('engagement'),
            'marked': marked
        }
