#!/usr/bin/env python3

import argparse
import re
import morfeusz2


class PolishNormalizer:

    def __init__(self):
        self.analyzer = morfeusz2.Morfeusz()

    @staticmethod
    def clean_lemma(lemma):
        return lemma.split(":", 1)[0]

    @staticmethod
    def tokenize(text):
        """
        Extract Polish words while preserving their spelling.
        """
        return re.findall(
            r"[^\W\d_]+(?:[-'][^\W\d_]+)*",
            text,
            flags=re.UNICODE
        )

    def candidates(self, word):
        """
        Find possible dictionary forms.

        Supports standard inflections and segmented
        past-tense/conditional verb forms.
        """

        word = word.strip()
        if not word:
            return []

        analyses = self.analyzer.analyse(word)

        results = []
        seen = set()

        for start, end, interpretation in analyses:

            orth, raw_lemma, tag, names, labels = interpretation
            pos = tag.split(":")[0]

            if pos in {"ign", "interp", "sp"}:
                continue

            # For segmented forms, retain the main verb.
            if orth.casefold() != word.casefold():

                if pos != "praet":
                    continue

                if not word.casefold().startswith(
                    orth.casefold()
                ):
                    continue

            lemma = self.clean_lemma(raw_lemma)

            key = (lemma, tag)
            if key in seen:
                continue

            seen.add(key)

            results.append({
                "lemma": lemma,
                "raw_lemma": raw_lemma,
                "part_of_speech": pos,
                "tag": tag,
            })

        return results

    def normalize(self, word):
        """
        Return a lemma only when unambiguous.
        """

        candidates = self.candidates(word)
        lemmas = {c["lemma"] for c in candidates}

        if len(lemmas) == 1:
            return next(iter(lemmas))

        return None

    def resolve(self, text, target_word=None, interactive=True):
        """
        Resolve a word to a dictionary form.

        Returns a dictionary suitable for downstream
        Wikisłownik lookup and Anki generation.
        """

        words = self.tokenize(text)

        if not words:
            raise ValueError("No Polish words found.")

        # If a full sentence was supplied, choose a target.
        if target_word is None:

            if len(words) == 1:
                target_word = words[0]

            elif not interactive:
                raise ValueError(
                    "A target_word is required for sentences."
                )

            else:
                print("\nWords in the sentence:")

                for i, word in enumerate(words, 1):
                    print(f"  {i}. {word}")

                while True:
                    choice = input(
                        "\nChoose the word number: "
                    ).strip()

                    if choice.isdigit():
                        index = int(choice) - 1

                        if 0 <= index < len(words):
                            target_word = words[index]
                            break

                    print("Please enter a valid number.")

        # Validate the selected target.
        if target_word.casefold() not in {
            word.casefold() for word in words
        }:
            raise ValueError(
                f"Target '{target_word}' was not found in the input."
            )

        candidates = self.candidates(target_word)

        # Group grammatical interpretations by lemma.
        lemma_options = {}

        for candidate in candidates:
            lemma_options.setdefault(
                candidate["lemma"], []
            ).append(candidate)

        if not lemma_options:
            raise ValueError(
                f"No dictionary analysis found for '{target_word}'."
            )

        # Morfeusz sometimes returns only the underlying verb for an
        # adjectival participle. Offer the written form independently of
        # Morfeusz so it can be looked up directly in Wikisłownik.
        participial_ending = target_word.casefold().endswith(
            ('ony', 'any', 'ęty', 'ity', 'yty')
        )
        if participial_ending and target_word.casefold() not in {
            lemma.casefold() for lemma in lemma_options
        }:
            lemma_options[target_word] = [{
                'lemma': target_word,
                'part_of_speech': 'adjective/participle (original form)',
                'tag': 'original-form',
            }]

        lemmas = list(lemma_options)

        # Automatically resolve unambiguous words.
        if len(lemmas) == 1:
            selected = lemmas[0]
            method = "automatic"

        else:
            if not interactive:
                return {
                    "original": target_word,
                    "lemma": None,
                    "context": text if len(words) > 1 else None,
                    "ambiguous": True,
                    "candidates": candidates,
                    "resolution": "unresolved",
                }

            print(
                f"\n'{target_word}' has multiple "
                "possible dictionary forms:"
            )

            for i, lemma in enumerate(lemmas, 1):

                tags = sorted({
                    c["tag"]
                    for c in lemma_options[lemma]
                })

                print(
                    f"  {i}. {lemma} "
                    f"({', '.join(tags)})"
                )

            if len(words) == 1:
                context = input(
                    "\nOptional: enter a sentence containing "
                    f"'{target_word}' (or press Enter to skip): "
                ).strip()

                if context:
                    text = context

            print(
                "\nSelect the intended dictionary form."
            )

            while True:
                choice = input(
                    "Enter the number: "
                ).strip()

                if choice.isdigit():
                    index = int(choice) - 1

                    if 0 <= index < len(lemmas):
                        selected = lemmas[index]
                        break

                print("Please enter a valid number.")

            method = "manual"

        selected_candidates = lemma_options[selected]

        return {
            "original": target_word,
            "lemma": selected,
            "context": text if len(self.tokenize(text)) > 1 else None,
            "part_of_speech": sorted({
                c["part_of_speech"]
                for c in selected_candidates
            }),
            "ambiguous": len(lemmas) > 1,
            "candidates": candidates,
            "resolution": method,
        }


def main():

    parser = argparse.ArgumentParser(
        description="Interactive Polish dictionary-form normalizer"
    )

    parser.add_argument(
        "text",
        nargs="*",
        help="Polish word or sentence"
    )

    parser.add_argument(
        "--target",
        help="Target word within a sentence"
    )

    args = parser.parse_args()

    normalizer = PolishNormalizer()

    if args.text:
        text = " ".join(args.text)

    else:
        text = input(
            "Enter a Polish word or sentence: "
        ).strip()

    try:
        result = normalizer.resolve(
            text,
            target_word=args.target,
            interactive=True
        )

    except ValueError as error:
        print(f"\nError: {error}")
        return

    print("\n" + "=" * 50)
    print("NORMALIZATION RESULT")
    print("=" * 50)

    print(f"Original:   {result['original']}")
    print(f"Lemma:      {result['lemma']}")
    print(
        "Part of speech: "
        + ", ".join(result["part_of_speech"])
    )
    print(f"Resolution: {result['resolution']}")

    if result["context"]:
        print(f"Context:    {result['context']}")

    print("\nReady for Wikisłownik lookup:")
    print(result["lemma"])


if __name__ == "__main__":
    main()
