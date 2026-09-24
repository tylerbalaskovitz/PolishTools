import re


class FlashcardParser:
    def extract_polish_section(self, wikitext):
        match = re.search(
            r"^==\s*.*?\(\{\{język polski\}\}\)\s*==\s*$",
            wikitext,
            re.MULTILINE,
        )

        if not match:
            return None

        start = match.end()

        next_section = re.search(
            r"^==\s*.*?\s*==\s*$",
            wikitext[start:],
            re.MULTILINE,
        )

        if next_section:
            return wikitext[start:start + next_section.start()]

        return wikitext[start:]

    def extract_meanings_section(self, section):
        match = re.search(
            r"\{\{znaczenia\}\}(.*?)(?=\n\{\{[^{}\n]+\}\}|\Z)",
            section,
            re.DOTALL,
        )

        if not match:
            return None

        return match.group(1)

    def clean_definition(self, text):
        text = re.sub(
            r"<ref\b[^>]*>.*?</ref>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        text = re.sub(
            r"<!--.*?-->",
            "",
            text,
            flags=re.DOTALL,
        )

        text = re.sub(
            r"\{\{wikipedia\|[^{}]*\}\}",
            "",
            text,
            flags=re.IGNORECASE,
        )

        def replace_systematic(match):
            parts = match.group(1).split("|")
            return parts[0].strip()

        text = re.sub(
            r"\{\{nazwa systematyczna\|([^{}]+)\}\}",
            replace_systematic,
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"\{\{[^{}]*\}\}",
            "",
            text,
        )

        def replace_link(match):
            parts = match.group(1).split("|")
            return parts[-1]

        text = re.sub(
            r"\[\[([^\]]+)\]\]",
            replace_link,
            text,
        )

        text = text.replace("'''", "")
        text = text.replace("''", "")

        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)

        text = text.strip(" ;,.")

        return text

    def extract_images_by_sense(self, wikitext):
        images = {}

        pattern = re.compile(
            r"\[\[Plik:([^|\]]+)(?:\|([^\]]*))?\]\]",
            re.IGNORECASE,
        )

        for match in pattern.finditer(wikitext):
            filename = match.group(1).strip()
            options = match.group(2) or ""

            sense_match = re.search(
                r"\((\d+\.\d+)\)",
                options,
            )

            if not sense_match:
                continue

            sense = sense_match.group(1)

            if sense not in images:
                images[sense] = filename

        return images

    def extract_audio(self, wikitext):
        audio = re.findall(
            r"\{\{audio\|([^}|]+)",
            wikitext,
            re.IGNORECASE,
        )

        return list(dict.fromkeys(
            filename.strip()
            for filename in audio
        ))

    def choose_audio(self, audio):
        for filename in audio:
            if filename.lower().startswith("pl-"):
                return filename

        if audio:
            return audio[0]

        return None

    def parse_meanings(self, meanings_section, images):
        positions = list(re.finditer(
            r"^''([^']+)''\s*$",
            meanings_section,
            re.MULTILINE,
        ))

        results = []

        for index, position in enumerate(positions):
            pos_text = position.group(1).strip()

            next_position = (
                positions[index + 1].start()
                if index + 1 < len(positions)
                else len(meanings_section)
            )

            block = meanings_section[
                position.end():next_position
            ]

            definitions = []

            for match in re.finditer(
                r"^:\s*\((\d+\.\d+)\)\s*(.*)$",
                block,
                re.MULTILINE,
            ):
                sense = match.group(1)
                raw_definition = match.group(2)

                definition = self.clean_definition(
                    raw_definition
                )

                if not definition:
                    continue

                definitions.append({
                    "sense": sense,
                    "definition": definition,
                    "image": images.get(sense),
                })

            if definitions:
                part_of_speech = pos_text.split(
                    ",",
                    1
                )[0].strip()

                results.append({
                    "part_of_speech": part_of_speech,
                    "definitions": definitions,
                })

        return results

    def parse(self, word, wikitext):
        polish_section = self.extract_polish_section(
            wikitext
        )

        if not polish_section:
            return None

        meanings_section = self.extract_meanings_section(
            polish_section
        )

        if not meanings_section:
            return None

        images = self.extract_images_by_sense(
            polish_section
        )

        audio = self.extract_audio(
            polish_section
        )

        meanings = self.parse_meanings(
            meanings_section,
            images
        )

        if not meanings:
            return None

        first = meanings[0]
        first_definition = first["definitions"][0]

        return {
            "word": word,
            "part_of_speech": first["part_of_speech"],
            "definition": first_definition["definition"],
            "sense": first_definition["sense"],
            "audio": self.choose_audio(audio),
            "image": first_definition["image"],
            "meanings": meanings,
        }
