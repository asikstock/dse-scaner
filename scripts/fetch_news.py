# scripts/fetch_news.py (একটি প্রাথমিক ধারণা)
import feedparser
import json
from datetime import datetime
import re

# ১. বাংলা নিউজ সাইটের RSS ফিড
RSS_FEEDS = [
    'https://businessbarta.net/feed/', # উদাহরণ স্বরূপ
    'https://www.ittefaq.com.bd/feed/', # উদাহরণ স্বরূপ
]

# ২. যেসব কোম্পানি ট্র্যাক করতে চান
TRACKED_SYMBOLS = ['GP', 'BEXIMCO', 'SQURPHARMA'] # আপনি চাইলে পুরো লিস্ট দিতে পারেন

def fetch_from_rss():
    all_news = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                # শুধু শিরোনাম ও লিঙ্ক নিচ্ছি আপাতত
                title = entry.title
                link = entry.link
                date = entry.get('published', datetime.now().isoformat())
                
                # কোন সিম্বল সম্পর্কে খবর সেটা খুঁজে বের করি
                for sym in TRACKED_SYMBOLS:
                    if sym in title.upper():
                        all_news.append({
                            'date': date,
                            'symbol': sym,
                            'title': title,
                            'source': feed_url,
                            'link': link
                        })
        except Exception as e:
            print(f"Error fetching {feed_url}: {e}")
    return all_news

def save_news(news_list):
    # খবরগুলোকে সিম্বল অনুযায়ী সাজিয়ে সেভ করি
    with open('docs/data/news.json', 'w', encoding='utf-8') as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(news_list)} news items.")

if __name__ == "__main__":
    news = fetch_from_rss()
    save_news(news)
