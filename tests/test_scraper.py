from src.scraper import parse_feed

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Big AI news</title><link>https://example.com/a</link>
<description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description>
<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title></title><link>https://example.com/b</link></item>
</channel></rss>"""


def test_parse_feed_cleans_html_and_skips_bad_items():
    items = parse_feed(RSS, "test")
    assert len(items) == 1
    assert items[0]["title"] == "Big AI news"
    assert items[0]["content"] == "Hello world"
    assert items[0]["published_at"].year == 2026
