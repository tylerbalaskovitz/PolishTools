#!/usr/bin/env python3
"""Offline Polish sentence + explanation generator using Ollama (Gemma 3 12B).

Requires a running Ollama service and a downloaded model:
    ollama pull gemma3:12b

No third-party Python packages required.
"""
import argparse
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / 'data' / 'polish_contexts.db'
DEFAULT_URL = 'http://127.0.0.1:11434/api/chat'


def generate(word, definition='', model='gemma3:12b', url=DEFAULT_URL):
    instructions = (
        'Jesteś starannym nauczycielem języka polskiego. '
        'Tworzysz naturalne, krótkie zdania dla osoby uczącej się języka polskiego. '
        'Używaj słownictwa A1–A2, jeśli to możliwe. '
        'Słowo docelowe może być trudniejsze niż A2. '
        'W zdaniu użyj dokładnie podanego słowa, jeśli pasuje gramatycznie; '
        'w przeciwnym razie użyj jego poprawnej formy fleksyjnej. '
        'Nie wymyślaj znaczenia słowa. Jeśli podano definicję, trzymaj się jej. '
        'Wyjaśnienie powinno prostymi słowami objaśniać znaczenie zdania, '
        'bez powtarzania trudnego słowa, o ile to możliwe. '
        'Zwróć WYŁĄCZNIE obiekt JSON z dwoma polami tekstowymi: '
        '"zdanie" oraz "wyjasnienie". Bez markdownu i dodatkowego tekstu.'
    )
    content = f'Słowo: {word}\n'
    if definition:
        content += f'Definicja: {definition}\n'
    content += 'Utwórz jedno zdanie i jedno proste wyjaśnienie.'
    payload = {
        'model': model,
        'stream': False,
        'format': 'json',
        'options': {'temperature': 0.35, 'num_predict': 220, 'num_ctx': 2048},
        'messages': [
            {'role': 'system', 'content': instructions},
            {'role': 'user', 'content': content},
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    raw = result.get('message', {}).get('content', '').strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f'Model did not return valid JSON: {raw[:300]}') from exc
    sentence = str(parsed.get('zdanie', '')).strip()
    explanation = str(parsed.get('wyjasnienie', '')).strip()
    if not sentence or not explanation:
        raise ValueError(f'Model returned incomplete output: {raw[:300]}')
    return sentence, explanation



def lookup_wikislownik(word):
    """Fetch Polish senses using the same Wikislownik and FlashcardParser as FlashcardMaker."""
    from FlashcardUtils import Wikislownik
    from FlashcardParser import FlashcardParser

    wiki = Wikislownik()  # Respect WM_CONTACT; surface errors instead of claiming no entry.
    page = wiki.get_page(word)
    if page is None:
        return [], 'missing'
    result = FlashcardParser().parse(word, page['wikitext'])
    if not result:
        return [], 'unparsed'
    choices = []
    for meaning in result.get('meanings', []):
        for item in meaning.get('definitions', []):
            definition = (item.get('definition') or '').strip()
            if definition:
                choices.append((meaning.get('part_of_speech', ''), item.get('sense', ''), definition))
    return choices, 'ok' if choices else 'unparsed'


def normalized_headwords(word):
    """Use the normalizer's participle rule as well as Morfeusz analyses."""
    try:
        from PolishNormalizer import PolishNormalizer
        analyses = PolishNormalizer().candidates(word)
    except (ImportError, RuntimeError, ValueError) as exc:
        print(f'Normalizacja niedostępna: {exc}')
        return []
    result = []
    seen = set()
    for analysis in analyses:
        lemma = analysis.get('lemma', '').strip()
        if lemma and lemma.casefold() not in seen:
            result.append((lemma, analysis.get('tag', '')))
            seen.add(lemma.casefold())

    # Same original-form alternative as PolishNormalizer.resolve().
    # It is a deliberate choice even when the exact Wikisłownik page is absent.
    if (word.casefold().endswith(('ony', 'any', 'ęty', 'ity', 'yty'))
            and word.casefold() not in seen):
        result.append((word, 'adjective/participle (original form)'))
    return result


def choose_definition(word, manual_definition='', no_wiki=False):
    """Try exact Wikisłownik entry, then Morfeusz lemmas; never silently pick an ambiguous meaning."""
    if manual_definition:
        return manual_definition
    if no_wiki:
        return ''

    lookup_word = word
    attempted = set()
    while True:
        attempted.add(lookup_word.casefold())
        try:
            choices, status = lookup_wikislownik(lookup_word)
        except Exception as exc:
            print(f'Błąd podczas pobierania definicji: {exc}')
            print('Sprawdź połączenie i WM_CONTACT; to nie oznacza braku hasła.')
            choices, status = [], 'error'
        if choices:
            print(f'\nDefinicje z Wikisłownika ({lookup_word}):')
            for i, (pos, sense, definition) in enumerate(choices, 1):
                print(f'  {i}. ({sense}) [{pos}] {definition}')
            while True:
                selected = input('Numer znaczenia [1], m = własna definicja, 0 = pomiń słowo: ').strip().lower()
                if selected in ('', '1'):
                    return choices[0][2]
                if selected == '0':
                    return ''
                if selected == 'm':
                    return input('Definicja: ').strip()
                if selected.isdecimal() and 1 <= int(selected) <= len(choices):
                    return choices[int(selected) - 1][2]
                print('Wybierz numer z listy.')

        if status == 'missing':
            print(f'Brak osobnej strony hasła „{lookup_word}” w Wikisłowniku.')
        elif status == 'unparsed':
            print(f'Nie udało się odczytać polskich znaczeń dla „{lookup_word}”.')

        # Only normalize after a genuinely missing/unparsed page, not an API failure.
        alternatives = []
        if status in ('missing', 'unparsed'):
            alternatives = [(lemma, tag) for lemma, tag in normalized_headwords(word)
                            if lemma.casefold() not in attempted or tag == 'adjective/participle (original form)']
        if alternatives:
            print('\nMożliwe formy słownikowe (Morfeusz):')
            for i, (lemma, tag) in enumerate(alternatives, 1):
                print(f'  {i}. {lemma} ({tag})')
            if len(alternatives) == 1:
                answer = input('Enter = sprawdź tę formę, numer / [h] inne hasło / [d] definicja / [p] pomiń: ').strip().lower()
                if answer in ('', '1'):
                    lemma, tag = alternatives[0]
                    if tag == 'adjective/participle (original form)' and lemma.casefold() in attempted:
                        print('Brak hasła dla formy przymiotnikowej; podaj jej znaczenie lub pomiń.')
                        return input('Definicja (Enter = pomiń słowo): ').strip()
                    lookup_word = lemma
                    continue
            else:
                answer = input('Wybierz numer formy, [h] inne hasło / [d] definicja / [p] pomiń: ').strip().lower()
                if answer.isdecimal() and 1 <= int(answer) <= len(alternatives):
                    lemma, tag = alternatives[int(answer) - 1]
                    if tag == 'adjective/participle (original form)' and lemma.casefold() in attempted:
                        print('Brak hasła dla formy przymiotnikowej; podaj jej znaczenie lub pomiń.')
                        return input('Definicja (Enter = pomiń słowo): ').strip()
                    lookup_word = lemma
                    continue
        else:
            answer = input('[h] inne hasło / [d] własna definicja / Enter = pomiń słowo: ').strip().lower()

        if answer == 'h':
            candidate = input('Hasło słownikowe: ').strip()
            if candidate:
                lookup_word = candidate
                continue
        if answer == 'd':
            return input('Definicja: ').strip()
        return ''


def init_db(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute('''CREATE TABLE IF NOT EXISTS contexts (
        word TEXT NOT NULL,
        definition TEXT NOT NULL DEFAULT '',
        sentence TEXT NOT NULL,
        explanation TEXT NOT NULL,
        model TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (word, definition)
    )''')
    conn.commit()
    return conn


def read_saved(conn, word, definition):
    return conn.execute(
        'SELECT sentence, explanation FROM contexts WHERE word=? AND definition=?',
        (word, definition),
    ).fetchone()


def save(conn, word, definition, sentence, explanation, model):
    conn.execute('''INSERT INTO contexts
        (word, definition, sentence, explanation, model, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(word, definition) DO UPDATE SET
            sentence=excluded.sentence,
            explanation=excluded.explanation,
            model=excluded.model,
            updated_at=excluded.updated_at''',
        (word, definition, sentence, explanation, model,
         datetime.now(timezone.utc).isoformat(timespec='seconds')))
    conn.commit()


def process(conn, word, definition, args):
    # Never ask the language model to guess a word's meaning.
    if not definition or not definition.strip():
        print(f'Pominięto „{word}”: brak definicji. Nie generuję kontekstu bez znaczenia słowa.')
        return
    if not args.regenerate:
        cached = read_saved(conn, word, definition)
        if cached:
            print('\n[Zapisany kontekst]')
            print(f'Zdanie: {cached[0]}\nWyjaśnienie: {cached[1]}')
            return
    while True:
        try:
            sentence, explanation = generate(word, definition, args.model, args.url)
        except urllib.error.URLError as exc:
            print(f'Cannot connect to Ollama: {exc}\nStart it with: sudo systemctl start ollama', file=sys.stderr)
            return
        except (ValueError, TimeoutError) as exc:
            print(f'Generation failed: {exc}', file=sys.stderr)
            return
        print(f'\nSłowo: {word}')
        print(f'Zdanie: {sentence}')
        print(f'Wyjaśnienie: {explanation}')
        if args.yes:
            choice = 's'
        else:
            choice = input('\n[s] zapisz / [r] ponów / [p] pomiń: ').strip().lower()
        if choice in ('s', 'save', 'y', 'yes'):
            save(conn, word, definition, sentence, explanation, args.model)
            print('Zapisano.')
            return
        if choice in ('r', 'retry'):
            continue
        print('Pominięto.')
        return


def main():
    parser = argparse.ArgumentParser(description='Generate simple Polish context offline using Ollama')
    parser.add_argument('word', nargs='?', help='Polish word (omit for interactive mode)')
    parser.add_argument('--definition', '-d', default='', help='Polish definition, e.g. from Wikisłownik')
    parser.add_argument('--model', default='gemma3:12b')
    parser.add_argument('--no-wiki', action='store_true', help='Skip Wikisłownik lookup')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--url', default=DEFAULT_URL, help='Local Ollama chat API URL')
    parser.add_argument('--regenerate', action='store_true', help='Generate again even if saved')
    parser.add_argument('--yes', '-y', action='store_true', help='Save without asking (review first is recommended)')
    args = parser.parse_args()
    conn = init_db(args.db)
    try:
        if args.word:
            word = args.word.strip()
            definition = choose_definition(word, args.definition.strip(), args.no_wiki)
            process(conn, word, definition, args)
        else:
            print('Polish Context Creator — wpisz q, aby zakończyć.')
            while True:
                try:
                    word = input('\nSłowo: ').strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if word.lower() in ('q', 'quit', 'exit'):
                    break
                if not word:
                    continue
                definition = choose_definition(word, args.definition.strip(), args.no_wiki)
                process(conn, word, definition, args)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
