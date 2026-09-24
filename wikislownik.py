import requests


API_URL = "https://pl.wiktionary.org/w/api.php"


class Wikislownik:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "PolishAnki/1.0"
        })

    def get_page(self, word):
        params = {
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "titles": word,
            "rvprop": "content",
            "rvslots": "main",
        }

        response = self.session.get(API_URL, params=params)
        response.raise_for_status()

        data = response.json()
        pages = data["query"]["pages"]

        page = next(iter(pages.values()))

        if "missing" in page:
            return None

        return {
            "title": page["title"],
            "page_id": page["pageid"],
            "wikitext": page["revisions"][0]["slots"]["main"]["*"],
        }

    def get_images(self, word):
        params = {
            "action": "query",
            "format": "json",
            "prop": "images",
            "titles": word,
            "imlimit": "max",
        }

        response = self.session.get(API_URL, params=params)
        response.raise_for_status()

        data = response.json()
        pages = data["query"]["pages"]

        page = next(iter(pages.values()))

        return [
            image["title"]
            for image in page.get("images", [])
        ]

    def get_file_info(self, filename):
        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "titles": filename,
            "iiprop": "url|mime|size",
        }

        response = self.session.get(API_URL, params=params)
        response.raise_for_status()

        data = response.json()
        pages = data["query"]["pages"]

        page = next(iter(pages.values()))

        imageinfo = page.get("imageinfo")

        if not imageinfo:
            return None

        return imageinfo[0]
