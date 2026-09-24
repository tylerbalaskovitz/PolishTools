import sys

from FlashcardUtils import Wikislownik
from FlashcardParser import FlashcardParser


def main():
    if len(sys.argv) != 2:
        print("Usage: python FlashcardMaker.py WORD")
        sys.exit(1)

    word = sys.argv[1]

    wiki = Wikislownik()
    parser = FlashcardParser()

    print(f"Looking up: {word}")
    print()

    page = wiki.get_page(word)

    if page is None:
        print("Word not found.")
        return

    result = parser.parse(
        word,
        page["wikitext"],
    )

    if result is None:
        print("Could not parse Polish entry.")
        return

    print(f"Word:          {result['word']}")
    print(f"Part of speech: {result['part_of_speech']}")
    print(f"Sense:         {result['sense']}")
    print(f"Definition:    {result['definition']}")
    print(f"Audio:         {result['audio']}")
    print(f"Image:         {result['image']}")
    print()

    print("All meanings:")
    print("-" * 60)

    for meaning in result["meanings"]:
        print(meaning["part_of_speech"])

        for definition in meaning["definitions"]:
            print(
                f"  ({definition['sense']}) "
                f"{definition['definition']}"
            )

            if definition["image"]:
                print(f"       Image: {definition['image']}")

        print()


if __name__ == "__main__":
    main()
