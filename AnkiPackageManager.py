"""Persist unique Wikisłownik notes and export one self-contained Anki package per day."""
import hashlib
import html
import os
import shutil
import sqlite3
from datetime import datetime, date
from pathlib import Path

import genanki

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
MEDIA = ROOT / 'media'
OUTPUT = ROOT / 'flashcards'
DECK_ID = 2059400110
MODEL_ID = 1607392319

MODEL = genanki.Model(
    MODEL_ID, 'Polish Wikislownik Vocabulary',
    fields=[{'name': n} for n in ('Polish', 'Lemma', 'Grammar', 'Definition', 'Audio', 'Image', 'Context')],
    templates=[{
        'name': 'Vocabulary',
        'qfmt': '<div class="polish">{{Polish}}</div><div class="audio">{{Audio}}</div>',
        'afmt': """{{FrontSide}}
<hr id="answer">
<div class="lemma">{{Grammar}}</div>
<div class="image">{{Image}}</div>
<div class="definition">{{Definition}}</div>
{{#Context}}<div class="context">{{Context}}</div>{{/Context}}"""
    }],
    css="""
.card {
    font-family: Arial;
    font-size: 22px;
    text-align: center;
}
.polish {
    font-size: inherit;
    font-weight: normal;
}
.audio {
    margin-top: 4px;
}
.lemma {
    margin: 10px 0;
    font-style: italic;
}
.image {
    margin: 15px 0;
}
img {
    max-width: 90%;
    max-height: 300px;
}
.definition {
    margin-top: 15px;
}
.context {
    margin-top: 15px;
}
"""
)



class AnkiPackageManager:
    def __init__(self):
        for directory in (DATA, MEDIA, OUTPUT):
            directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(DATA / 'flashcards.db')
        self._ensure_cards_schema()
        self.db.execute('''CREATE TABLE IF NOT EXISTS lookup_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, original TEXT NOT NULL,
            lemma TEXT NOT NULL, sense TEXT, looked_up_at TEXT NOT NULL)''')
        self.db.commit()

    def _ensure_cards_schema(self):
        # Migrate old uniqueness while preserving Anki GUIDs.
        exists = self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cards'").fetchone()
        if not exists:
            self.db.execute('''CREATE TABLE cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original TEXT NOT NULL, lemma TEXT NOT NULL, sense TEXT NOT NULL,
                definition TEXT NOT NULL, context TEXT, audio TEXT, image TEXT, grammar TEXT,
                created_date TEXT NOT NULL, guid TEXT NOT NULL,
                UNIQUE(original, lemma, sense))''')
            self.db.commit()
            return
        cols = {row[1] for row in self.db.execute('PRAGMA table_info(cards)')}
        if 'grammar' not in cols:
            self.db.execute('ALTER TABLE cards ADD COLUMN grammar TEXT')
            self.db.commit()
            cols.add('grammar')
        if 'guid' in cols:
            return
        # Old cards retain their original Anki GUIDs for safe reimports.
        old_rows = self.db.execute('''SELECT id, original, lemma, sense, definition,
            context, audio, image, created_date FROM cards ORDER BY id''').fetchall()
        with self.db:
            self.db.execute('''CREATE TABLE cards_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original TEXT NOT NULL, lemma TEXT NOT NULL, sense TEXT NOT NULL,
                definition TEXT NOT NULL, context TEXT, audio TEXT, image TEXT, grammar TEXT,
                created_date TEXT NOT NULL, guid TEXT NOT NULL,
                UNIQUE(original, lemma, sense))''')
            for row in old_rows:
                old_guid = genanki.guid_for('wikislownik', row[2], row[3])
                self.db.execute('''INSERT INTO cards_v2
                    (id, original, lemma, sense, definition, context, audio, image, created_date, guid)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (*row, old_guid))
            self.db.execute('DROP TABLE cards')
            self.db.execute('ALTER TABLE cards_v2 RENAME TO cards')

    @staticmethod
    def today():
        return datetime.now().astimezone().date().isoformat()

    def store_media(self, path):
        if not path:
            return None
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
        filename = digest + source.suffix.lower()
        dest = MEDIA / filename
        if not dest.exists():
            shutil.copy2(source, dest)
        return filename

    def add_card(self, original, lemma, definition, sense='1.1', context='', grammar='',
                 audio_path=None, image_path=None):
        if not all((original.strip(), lemma.strip(), definition.strip())):
            raise ValueError('Original, lemma and definition are required')
        original, lemma, definition, sense = original.strip(), lemma.strip(), definition.strip(), str(sense)
        existing = self.db.execute('''SELECT created_date FROM cards
            WHERE original=? AND lemma=? AND sense=?''', (original, lemma, sense)).fetchone()
        audio = self.store_media(audio_path) if not existing and original.casefold() == lemma.casefold() else None
        image = self.store_media(image_path) if not existing else None
        guid = genanki.guid_for('wikislownik', 'v2', original, lemma, sense)
        with self.db:
            cursor = self.db.execute('''INSERT INTO cards
                (original, lemma, sense, definition, context, audio, image, created_date, guid, grammar)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(original, lemma, sense) DO UPDATE SET grammar=excluded.grammar''',
                (original, lemma, sense, definition, context, audio, image, self.today(), guid, grammar.strip()))
            self.db.execute('''INSERT INTO lookup_history
                (original, lemma, sense, looked_up_at) VALUES (?, ?, ?, ?)''',
                (original, lemma, sense, datetime.now().astimezone().isoformat(timespec='seconds')))
        if cursor.rowcount:
            print(f'Added: {original} ({sense})')
            return True
        print(f'Already exists: {original} ({sense}); original package date: {existing[0]}')
        return False

    def has_card(self, original, lemma, sense):
        return self.db.execute('''SELECT 1 FROM cards
            WHERE original=? AND lemma=? AND sense=?''',
            (original, lemma, str(sense))).fetchone() is not None

    def build_daily_package(self, day=None):
        day = day or self.today()
        date.fromisoformat(day)  # Validate before constructing output filename.
        rows = self.db.execute('''SELECT original, lemma, sense, definition, context, audio, image, guid, grammar
            FROM cards WHERE created_date=? ORDER BY id''', (day,)).fetchall()
        if not rows:
            print(f'No cards for {day}')
            return None
        deck = genanki.Deck(DECK_ID, 'Polish::Wikisłownik Vocabulary')
        media_paths = set()
        for original, lemma, sense, definition, context, audio, image, guid, grammar in rows:
            audio_field = ''
            image_field = ''
            # Safety guard for cards created by older versions.
            if audio and original.casefold() == lemma.casefold():
                path = MEDIA / audio
                if not path.is_file():
                    raise FileNotFoundError(path)
                media_paths.add(str(path))
                audio_field = f'[sound:{audio}]'
            if image:
                path = MEDIA / image
                if not path.is_file():
                    raise FileNotFoundError(path)
                media_paths.add(str(path))
                image_field = f'<img src="{html.escape(image, quote=True)}">'
            note = genanki.Note(model=MODEL, guid=guid,
                                fields=[html.escape(original), html.escape(lemma), html.escape(grammar or ''),
                                        html.escape(definition), audio_field, image_field,
                                        html.escape(context or '')])
            deck.add_note(note)
        output = OUTPUT / f'PolishVocabulary_{day}.apkg'
        temporary = OUTPUT / f'.PolishVocabulary_{day}.apkg.tmp'
        package = genanki.Package(deck)
        package.media_files = sorted(media_paths)
        try:
            package.write_to_file(str(temporary))
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        print(f'Package: {output} | Cards: {len(rows)} | Media: {len(media_paths)}')
        return output

    def repair_audio(self):
        """Attach missing Commons audio to existing base-form notes and rebuild dated packages."""
        from FlashcardUtils import Wikislownik
        from FlashcardParser import FlashcardParser
        wiki, parser = Wikislownik(), FlashcardParser()
        rows = self.db.execute("""SELECT id, lemma, created_date FROM cards
            WHERE original=lemma AND (audio IS NULL OR audio='') ORDER BY id""").fetchall()
        if not rows:
            print('No base-form cards with missing audio.')
            return 0
        updated = 0
        dates = set()
        resolved = {}
        for card_id, lemma, created_date in rows:
            if lemma not in resolved:
                try:
                    page = wiki.get_page(lemma)
                    parsed = parser.parse(lemma, page['wikitext']) if page else None
                    filename = parsed.get('audio') if parsed else None
                    resolved[lemma] = wiki.download_media(filename, ROOT / 'downloads') if filename else None
                except Exception as exc:
                    print(f'Audio pending for {lemma}: {exc}')
                    resolved[lemma] = None
            path = resolved[lemma]
            if path:
                stored = self.store_media(path)
                with self.db:
                    self.db.execute('UPDATE cards SET audio=? WHERE id=?', (stored, card_id))
                dates.add(created_date)
                updated += 1
                print(f'Audio restored: {lemma}')
        for day in sorted(dates):
            self.build_daily_package(day)
        print(f'Restored audio on {updated}/{len(rows)} base-form cards. Missing files can be retried later.')
        return updated

    def repair_grammar(self):
        """Populate grammar headings on existing cards and rebuild affected packages."""
        from FlashcardUtils import Wikislownik
        from FlashcardParser import FlashcardParser
        wiki, parser = Wikislownik(), FlashcardParser()
        rows = self.db.execute("""SELECT id, lemma, sense, created_date FROM cards
            WHERE grammar IS NULL OR grammar='' ORDER BY id""").fetchall()
        if not rows:
            print('No cards with missing grammar.')
            return 0
        parsed_cache = {}
        updated = 0
        dates = set()
        for card_id, lemma, sense, created_date in rows:
            if lemma not in parsed_cache:
                try:
                    page = wiki.get_page(lemma)
                    parsed_cache[lemma] = parser.parse(lemma, page['wikitext']) if page else None
                except Exception as exc:
                    print(f'Grammar pending for {lemma}: {exc}')
                    parsed_cache[lemma] = None
            parsed = parsed_cache[lemma]
            grammar = None
            if parsed:
                for meaning in parsed.get('meanings', []):
                    if any(d.get('sense') == sense for d in meaning.get('definitions', [])):
                        grammar = meaning.get('part_of_speech')
                        break
            if grammar:
                with self.db:
                    self.db.execute('UPDATE cards SET grammar=? WHERE id=?', (grammar, card_id))
                dates.add(created_date)
                updated += 1
                print(f'Grammar restored: {lemma} ({sense}) -> {grammar}')
        for day in sorted(dates):
            self.build_daily_package(day)
        print(f'Restored grammar on {updated}/{len(rows)} cards.')
        return updated

    def remove_mismatched_audio(self):
        """Clear legacy audio on inflected cards and rebuild affected daily packages."""
        rows = self.db.execute(
            'SELECT id, original, lemma, created_date FROM cards WHERE audio IS NOT NULL'
        ).fetchall()
        changed_dates = set()
        count = 0
        for card_id, original, lemma, created_date in rows:
            if original.casefold() != lemma.casefold():
                self.db.execute('UPDATE cards SET audio=NULL WHERE id=?', (card_id,))
                changed_dates.add(created_date)
                count += 1
        self.db.commit()
        for day in sorted(changed_dates):
            self.build_daily_package(day)
        print(f'Removed mismatched audio from {count} cards; rebuilt {len(changed_dates)} daily packages.')
        return count

    def get_daily_stats(self, day=None):
        day = day or self.today()
        date.fromisoformat(day)
        cards = self.db.execute('SELECT COUNT(*) FROM cards WHERE created_date=?', (day,)).fetchone()[0]
        lookups = self.db.execute('SELECT COUNT(*) FROM lookup_history WHERE substr(looked_up_at,1,10)=?', (day,)).fetchone()[0]
        return {'date': day, 'cards': cards, 'lookups': lookups}

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='YYYY-MM-DD; defaults to today')
    parser.add_argument('--stats', action='store_true')
    parser.add_argument('--remove-mismatched-audio', action='store_true',
                        help='Clear legacy mismatched audio and rebuild affected packages')
    parser.add_argument('--repair-audio', action='store_true', help='Download missing original Wikimedia audio and rebuild packages')
    parser.add_argument('--repair-grammar', action='store_true', help='Populate missing grammar headings and rebuild packages')
    args = parser.parse_args()
    with AnkiPackageManager() as manager:
        if args.repair_audio:
            manager.repair_audio()
        elif args.repair_grammar:
            manager.repair_grammar()
        elif args.remove_mismatched_audio:
            manager.remove_mismatched_audio()
        elif args.stats:
            print(manager.get_daily_stats(args.date))
        else:
            manager.build_daily_package(args.date)


if __name__ == '__main__':
    main()
