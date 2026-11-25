#!/usr/bin/env python3
"""Look up Polish words and append unique notes to today's Anki package."""
import argparse
from pathlib import Path

from FlashcardUtils import Wikislownik
from FlashcardParser import FlashcardParser
from AnkiPackageManager import AnkiPackageManager, ROOT


def resolve_input(text, target=None):
    """Use PolishNormalizer when available; otherwise treat input as a lemma."""
    try:
        from PolishNormalizer import PolishNormalizer
    except ImportError:
        if target:
            return target, text, target
        if len(text.split()) > 1:
            raise RuntimeError('Sentence input requires PolishNormalizer.py beside this script.')
        print('PolishNormalizer.py not found; looking up the word as entered.')
        return text, None, text

    normalizer = PolishNormalizer()
    result = normalizer.resolve(text, target_word=target, interactive=True)
    if not result or not result.get('lemma'):
        raise RuntimeError('No dictionary form was selected.')
    return result['lemma'], result.get('context'), result.get('original') or target or text


def choose_sense(result):
    """Let the user choose the intended Wikisłownik meaning."""
    choices = []
    for meaning in result['meanings']:
        for definition in meaning['definitions']:
            choices.append((meaning['part_of_speech'], definition))
    if len(choices) == 1:
        pos, definition = choices[0]
        return pos, definition
    print('\nChoose the meaning for your Anki card:')
    for index, (pos, definition) in enumerate(choices, 1):
        print(f"  {index}. ({definition['sense']}) [{pos}] {definition['definition']}")
    while True:
        try:
            choice = int(input('Meaning number (Enter for 1): ').strip() or '1')
        except ValueError:
            continue
        if 1 <= choice <= len(choices):
            return choices[choice - 1]


def process_entry(text, target=None, no_media=False, wiki=None, wikparser=None):
    """Process one entry; errors are handled by the interactive loop."""
    lemma, context, original = resolve_input(text, target)
    wiki = wiki or Wikislownik()
    wikparser = wikparser or FlashcardParser()
    print(f'Looking up: {lemma}')
    page = wiki.get_page(lemma)
    if page is None:
        print('Word not found on Wikisłownik.')
        return
    result = wikparser.parse(lemma, page['wikitext'])
    if result is None:
        print('Could not parse the Polish entry.')
        return

    print(f"Part of speech: {result['part_of_speech']}")
    audio_matches = original.casefold() == lemma.casefold()
    print(f"Dictionary audio: {result['audio'] or 'none'} (base-form card only)")
    grammar, selected = choose_sense(result)
    print(f"Selected: ({selected['sense']}) [{grammar}] {selected['definition']}")

    with AnkiPackageManager() as manager:
        is_inflected = original.casefold() != lemma.casefold()
        need_original = not manager.has_card(original, lemma, selected['sense'])
        need_base = is_inflected and not manager.has_card(lemma, lemma, selected['sense'])
        audio_path = image_path = None
        if (need_original or need_base) and not no_media:
            download_dir = ROOT / 'downloads'
            # The dictionary audio is for the lemma. Attach it ONLY to the base-form card.
            for kind, filename in (('audio', result['audio']), ('image', selected['image'])):
                if not filename:
                    continue
                if kind == 'audio' and not (need_base or (need_original and not is_inflected)):
                    continue
                try:
                    downloaded = wiki.download_media(filename, download_dir)
                    if kind == 'audio':
                        audio_path = downloaded
                    else:
                        image_path = downloaded
                    if downloaded is None:
                        print(f'No downloadable {kind} available: {filename}')
                except Exception as exc:
                    print(f'Warning: could not download {kind} {filename}: {exc}')
        changed = False
        if is_inflected:
            print(f'Creating two cards: {original} (no audio) + {lemma} (dictionary audio).')
        changed |= manager.add_card(
            original=original, lemma=lemma, definition=selected['definition'],
            sense=selected['sense'], context=context or '', grammar=grammar,
            audio_path=audio_path if not is_inflected else None, image_path=image_path,
        )
        if is_inflected:
            changed |= manager.add_card(
                original=lemma, lemma=lemma, definition=selected['definition'],
                sense=selected['sense'], context='', grammar=grammar,
                audio_path=audio_path, image_path=image_path,
            )
        if context:
            changed |= manager.add_sentence_card(
                original=original, lemma=lemma, definition=selected['definition'],
                sense=selected['sense'], context=context, grammar=grammar,
                image_path=image_path,
            )
        if changed:
            manager.build_daily_package()


def main():
    parser = argparse.ArgumentParser(description='Add Polish Anki cards in a continuous session.')
    parser.add_argument('text', nargs='*', help='Optional first Polish word or sentence')
    parser.add_argument('--target', help='Target word in the initial sentence')
    parser.add_argument('--no-media', action='store_true', help='Skip downloading audio and images')
    args = parser.parse_args()
    wiki = Wikislownik()
    wikparser = FlashcardParser()
    pending = ' '.join(args.text).strip() if args.text else None
    print('Polish flashcard session. Enter a word or sentence; type q to quit.')
    while True:
        try:
            if pending is not None:
                text = pending
                target = args.target
                pending = None
            else:
                text = input('\nNext word or sentence (q to quit): ').strip()
                target = None
            if not text:
                continue
            if text.casefold() in ('q', 'quit', 'exit', ':q'):
                print('Session ended. Your cards are saved.')
                break
            try:
                process_entry(text, target=target, no_media=args.no_media,
                              wiki=wiki, wikparser=wikparser)
            except (EOFError, KeyboardInterrupt):
                print('\nSession ended. Your cards are saved.')
                break
            except Exception as exc:
                print(f'Could not add card: {exc}')
                print('You can try another word or sentence.')
        except (EOFError, KeyboardInterrupt):
            print('\nSession ended. Your cards are saved.')
            break


if __name__ == '__main__':
    main()
