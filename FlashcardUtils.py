import re
import time
import os
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

import requests


API_URL = "https://pl.wiktionary.org/w/api.php"


class Wikislownik:
    def __init__(self):
        self.session = requests.Session()

        # Wikimedia requires a *real* contact address, not wikimedia.org as a placeholder.
        # Set WM_CONTACT to your own email address or public project URL.
        contact = os.environ.get('WM_CONTACT', '').strip()
        if not contact:
            raise RuntimeError('Set WM_CONTACT to your email or project URL first, e.g. export WM_CONTACT="you@example.com"')
        self.session.headers.update({
            'User-Agent': f'PolishAnkiBot/2.0 ({contact}) python-requests/{requests.__version__}',
            'Accept-Encoding': 'gzip',
        })
        self._last_request = 0.0
        self._next_allowed = 0.0

    def _wait_turn(self):
        # Conservative global pacing: sequential requests, 1 every 2 seconds.
        pause = max(self._next_allowed, self._last_request + 2.0) - time.monotonic()
        if pause > 0:
            time.sleep(pause)
        self._last_request = time.monotonic()

    @staticmethod
    def _retry_seconds(header, fallback):
        if header:
            try:
                return max(5, int(header))
            except ValueError:
                try:
                    return max(5, int((parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()))
                except (ValueError, TypeError, OverflowError):
                    pass
        return fallback


    def request(self, params):
        for attempt in range(4):
            self._wait_turn()
            response = self.session.get(API_URL, params=params, timeout=30)
            if response.status_code in (429, 503):
                wait = self._retry_seconds(response.headers.get('Retry-After'), min(120, 10 * (2 ** attempt)))
                response.close()
                print(f'Wikimedia API returned 429/503; waiting {wait}s...')
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError('Wikimedia API still rate limited after retries; wait and try later')

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

    def download_media(self, filename, destination_dir):
        """Cache media by Commons filename and use compliant, sequential downloads.

        429 from upload.wikimedia.org may be an independent operational limit,
        NOT the per-minute API quota. Never circumvent or rotate hosts/IPs.
        """
        import hashlib
        from pathlib import Path

        if not filename:
            return None
        dest = Path(destination_dir)
        dest.mkdir(parents=True, exist_ok=True)
        name = filename.removeprefix('File:').removeprefix('Plik:').replace('_', ' ').strip()
        suffix = Path(name).suffix.lower()
        if suffix not in ('.ogg', '.oga', '.wav', '.mp3', '.flac', '.jpg', '.jpeg', '.png', '.webp', '.gif'):
            return None
        key = hashlib.sha256(name.casefold().encode('utf-8')).hexdigest()[:24]
        target = dest / (key + suffix)
        if target.is_file() and target.stat().st_size:
            return target

        cooldown = dest / '.wikimedia_cooldown'
        if cooldown.exists():
            try:
                until = float(cooldown.read_text())
                if time.time() < until:
                    raise RuntimeError(f'Wikimedia media cooldown: {int(until-time.time())} seconds remaining; run --repair-audio later')
            except ValueError:
                pass

        metadata = next(iter(self.get_file_info([name]).values()), None)
        if not metadata or not metadata.get('url'):
            return None
        # Use the URL Wikimedia provides. Don't add misleading Referer headers.
        url = metadata['url']
        for attempt in range(3):
            self._wait_turn()
            response = self.session.get(url, timeout=60, stream=True)
            if response.status_code in (429, 503):
                wait = self._retry_seconds(response.headers.get('Retry-After'), min(300, 30 * (2 ** attempt)))
                response.close()
                cooldown.write_text(str(time.time() + wait))
                # Do not keep requesting blocked media during the cooldown.
                raise RuntimeError(f'Wikimedia media returned {response.status_code}; retry after {wait}s with --repair-audio')
            try:
                response.raise_for_status()
                temp = target.with_suffix(target.suffix + '.part')
                try:
                    with temp.open('wb') as out:
                        for chunk in response.iter_content(chunk_size=65536):
                            if chunk:
                                out.write(chunk)
                    if not temp.stat().st_size:
                        raise RuntimeError('Empty media download')
                    temp.replace(target)
                finally:
                    temp.unlink(missing_ok=True)
                cooldown.unlink(missing_ok=True)
                return target
            finally:
                response.close()
        return None
