import unittest
from src.rss_parser import normalize_title, cluster_and_deduplicate_articles, clean_article_url

class TestRSSParser(unittest.TestCase):
    def test_clean_article_url_bing(self):
        bing_url = "http://www.bing.com/news/apiclick.aspx?ref=FexRss&aid=&tid=123&url=https%3a%2f%2fexample.com%2farticle%2f100"
        cleaned = clean_article_url(bing_url)
        self.assertEqual(cleaned, "https://example.com/article/100")

    def test_clean_article_url_direct(self):
        direct_url = "https://example.com/direct/news"
        self.assertEqual(clean_article_url(direct_url), direct_url)

    def test_normalize_title(self):
        title = "외교부·코이카, '제19회 서울 ODA 국제회의' 개최 - 행정신문"
        normalized = normalize_title(title)
        self.assertNotIn("행정신문", normalized)
        self.assertIn("외교부", normalized)
        self.assertIn("제19회", normalized)
        self.assertIn("서울", normalized)
        self.assertIn("oda", normalized)

    def test_cluster_and_deduplicate_articles(self):
        articles = [
            {
                "title": "외교부·코이카, 제19회 서울 ODA 국제회의 개최 - lawissue.co.kr",
                "country": "KR",
                "link": "https://lawissue.co.kr/view.php?ud=1",
                "description": "Short desc"
            },
            {
                "title": "외교부·KOICA, ′제19회 서울 ODA 국제회의′ 개최 - 프레스뉴스",
                "country": "KR",
                "link": "https://pressnews.co.kr/view.php?ud=2",
                "description": "A much longer and more informative description of the conference with details."
            },
            {
                "title": "외교부·코이카, 18일 서울 ODA 국제회의…주제는 'AI' - SPN 서울평양뉴스",
                "country": "KR",
                "link": "https://spnews.co.kr/news/1",
                "description": "Medium description"
            },
            {
                "title": "인천대, 초광역 성장엔진 인재육성사업서 AI로봇 인재 700명 양성 - 매일일보",
                "country": "KR",
                "link": "https://m-i.kr/1",
                "description": "Completely different article"
            }
        ]
        deduped = cluster_and_deduplicate_articles(articles, threshold=65)
        # Should collapse the 3 conference articles into 1, leaving 2 articles total
        self.assertEqual(len(deduped), 2)
        # Should pick the one with the longest description
        conference_art = [a for a in deduped if "서울" in a["title"]][0]
        self.assertIn("much longer and more informative", conference_art["description"])

if __name__ == "__main__":
    unittest.main()
