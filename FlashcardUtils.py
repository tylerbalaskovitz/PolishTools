import re
import time

import requests


API_URL = "https://pl.wiktionary.org/w/api.php"


class Wikislownik:
    def __init__(self):
        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": "PolishAnki/1.0 (personal vocabulary tool)",
            "Accept-Encoding": "gzip",
        })

    def request(self, params):
        while True:
            response = self.session.get(API_URL, params=params)

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")

                if retry_after:
                    wait = int(retry_after)
                else:
                    wait = 10

                print(f"Rate limited. Waiting {wait} seconds...")
                time.sleep(wait)
                continue

            response.raise_for_status()

            return response.json()

    def get_page(self, word):
        params = {
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "titles": word,
            "rvprop": "content",
            "rvslots": "main",
        }

        data = self.request(params)

        pages = data["query"]["pages"]
        page = next(iter(pages.values()))

        if "missing" in page:
            return None

        return {
            "title": page["title"],
            "page_id": page["pageid"],
            "wikitext": page["revisions"][0]["slots"]["main"]["*"],
        }

    def extract_audio(self, wikitext):
        return re.findall(
            r"\{\{audio\|([^}|]+)",
            wikitext,
            re.IGNORECASE,
        )

    def extract_images(self, wikitext):
        images = []

        pattern = r"\[\[Plik:([^|\]]+)(?:\|[^]]*)?\]\]"

        for match in re.finditer(pattern, wikitext):
            filename = match.group(1).strip()

            images.append(filename)

        return images

    def get_file_info(self, filenames):
        if not filenames:
            return {}

        titles = "|".join(
            f"Plik:{filename}"
            for filename in filenames
        )

        params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "titles": titles,
            "iiprop": "url|mime|size",
        }

        data = self.request(params)

        result = {}

        for page in data["query"]["pages"].values():
            imageinfo = page.get("imageinfo")

            if not imageinfo:
                continue

            result[page["title"]] = imageinfo[0]

        return result
