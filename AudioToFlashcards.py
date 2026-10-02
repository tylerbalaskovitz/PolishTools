import os
import shutil
import subprocess

import torch
import whisperx
from transformers import MarianMTModel, MarianTokenizer


# ============================================================
# CONFIG
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

UNPROCESSED_DIR = os.path.join(
    SCRIPT_DIR,
    "unprocessed"
)

PROCESSED_DIR = os.path.join(
    SCRIPT_DIR,
    "processed"
)

AUDIOFLASHCARDS_DIR = os.path.join(
    SCRIPT_DIR,
    "audioflashcards"
)

ANKI_MEDIA_DIR = os.path.expanduser(
    "~/.local/share/Anki2/User 1/collection.media"
)


# ============================================================
# WHISPER SETTINGS
# ============================================================

DEVICE = "cuda"
WHISPER_MODEL = "large-v3"
LANGUAGE = "pl"
WHISPER_BATCH_SIZE = 16


# ============================================================
# TRANSLATION SETTINGS
# ============================================================

TRANSLATION_MODEL = "Helsinki-NLP/opus-mt-pl-en"

# Number of sentences translated simultaneously.
# 32 should be comfortable on an RTX 3060.
TRANSLATION_BATCH_SIZE = 32

# Maximum tokenizer length.
TRANSLATION_MAX_LENGTH = 512


# ============================================================
# FLASHCARD SETTINGS
# ============================================================

MIN_WORDS = 2

SUPPORTED_AUDIO = (
    ".mp3",
    ".m4a",
    ".wav",
    ".ogg",
    ".opus",
    ".webm",
    ".flac",
)


# ============================================================
# CREATE DIRECTORIES
# ============================================================

os.makedirs(
    UNPROCESSED_DIR,
    exist_ok=True
)

os.makedirs(
    PROCESSED_DIR,
    exist_ok=True
)

os.makedirs(
    AUDIOFLASHCARDS_DIR,
    exist_ok=True
)

os.makedirs(
    ANKI_MEDIA_DIR,
    exist_ok=True
)


# ============================================================
# CHECK CUDA
# ============================================================

if not torch.cuda.is_available():

    raise RuntimeError(
        "CUDA is not available. "
        "This script is configured to use the NVIDIA GPU."
    )


print("=" * 70)
print("SYSTEM")
print("=" * 70)

print()
print(
    "GPU:",
    torch.cuda.get_device_name(0)
)

print(
    "CUDA available:",
    torch.cuda.is_available()
)


# ============================================================
# LOAD WHISPERX
# ============================================================

print()
print("=" * 70)
print("LOADING WHISPERX")
print("=" * 70)

print()
print(f"Model:    {WHISPER_MODEL}")
print(f"Language: {LANGUAGE}")
print(f"Device:   {DEVICE}")

print()
print("Loading Whisper transcription model...")

whisper_model = whisperx.load_model(
    WHISPER_MODEL,
    DEVICE,
    language=LANGUAGE
)

print("Loading Polish alignment model...")

align_model, align_metadata = (
    whisperx.load_align_model(
        language_code=LANGUAGE,
        device=DEVICE
    )
)

print()
print("WhisperX models loaded successfully.")


# ============================================================
# TRANSLATION MODEL
# ============================================================

translation_tokenizer = None
translation_model = None


def load_translation_model():
    """
    Load the Polish -> English MarianMT model.

    The model is loaded only when translation is actually needed.
    """

    global translation_tokenizer
    global translation_model

    if (
        translation_tokenizer is not None
        and translation_model is not None
    ):
        return

    print()
    print("=" * 70)
    print("LOADING POLISH -> ENGLISH TRANSLATOR")
    print("=" * 70)

    print()
    print(
        f"Model: {TRANSLATION_MODEL}"
    )

    print()
    print(
        "Loading tokenizer..."
    )

    translation_tokenizer = (
        MarianTokenizer.from_pretrained(
            TRANSLATION_MODEL
        )
    )

    print(
        "Loading translation model..."
    )

    translation_model = (
        MarianMTModel.from_pretrained(
            TRANSLATION_MODEL
        )
    )

    translation_model.to(
        DEVICE
    )

    translation_model.eval()

    print()
    print(
        "Translation model loaded on:"
    )

    print(
        torch.cuda.get_device_name(0)
    )


# ============================================================
# TIMESTAMP FORMATTER
# ============================================================

def fmt(t):
    """
    Convert seconds to an FFmpeg-compatible timestamp.

    Example:

        65.123

    becomes:

        00:01:05.123
    """

    ms = int(t * 1000)

    h = ms // 3600000

    m = (
        ms % 3600000
    ) // 60000

    s = (
        ms % 60000
    ) // 1000

    ms = ms % 1000

    return (
        f"{h:02}:"
        f"{m:02}:"
        f"{s:02}."
        f"{ms:03}"
    )


# ============================================================
# EXTRACT SENTENCES
# ============================================================

def extract_sentences(result):
    """
    Convert WhisperX word alignment data into sentence records.

    IMPORTANT:

    Words are NOT discarded because of low alignment confidence.

    We only require a word to have usable start/end timestamps.
    """

    sentence_records = []

    current_words = []

    def flush_segment():

        nonlocal current_words

        if len(current_words) < MIN_WORDS:

            current_words = []

            return

        text = " ".join(
            word["word"].strip()
            for word in current_words
        ).strip()

        if not text:

            current_words = []

            return

        start = current_words[0]["start"]
        end = current_words[-1]["end"]

        sentence_records.append(
            {
                "text": text,
                "start": start,
                "end": end,
            }
        )

        current_words = []

    for segment in result["segments"]:

        words = segment.get(
            "words",
            []
        )

        if not words:
            continue

        for word in words:

            # We need timestamps in order to cut the
            # corresponding sentence from the source audio.

            if (
                "start" not in word
                or "end" not in word
            ):
                continue

            word_text = word.get(
                "word",
                ""
            ).strip()

            if not word_text:
                continue

            # DO NOT filter based on:
            #
            # word["probability"]
            #
            # Alignment confidence does not necessarily mean
            # that the transcription itself is wrong.

            current_words.append(
                word
            )

            # Normal sentence boundaries.

            if (
                word_text.endswith(".")
                or word_text.endswith("?")
                or word_text.endswith("!")
            ):

                flush_segment()

    # Handle text remaining at EOF without punctuation.

    flush_segment()

    return sentence_records


# ============================================================
# LOCAL TRANSLATION
# ============================================================

def translate_sentences(sentences):
    """
    Translate Polish sentences to English locally using
    MarianMT on the NVIDIA GPU.

    No Google Translate or Internet requests are made here.
    """

    if not sentences:
        return []

    load_translation_model()

    translations = []

    total = len(sentences)

    print()
    print("=" * 70)
    print("TRANSLATING LOCALLY")
    print("=" * 70)

    print()
    print(
        f"Sentences: {total}"
    )

    print(
        f"Batch size: {TRANSLATION_BATCH_SIZE}"
    )

    print(
        f"GPU: {torch.cuda.get_device_name(0)}"
    )

    for start in range(
        0,
        total,
        TRANSLATION_BATCH_SIZE
    ):

        batch = sentences[
            start:
            start + TRANSLATION_BATCH_SIZE
        ]

        first_number = start + 1

        last_number = (
            start + len(batch)
        )

        print()
        print(
            f"Translating "
            f"{first_number}-{last_number} "
            f"of {total}..."
        )

        # ----------------------------------------------------
        # TOKENIZE
        # ----------------------------------------------------

        encoded = translation_tokenizer(
            batch,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=TRANSLATION_MAX_LENGTH
        )

        encoded = {
            key: value.to(DEVICE)
            for key, value in encoded.items()
        }

        # ----------------------------------------------------
        # TRANSLATE
        # ----------------------------------------------------

        with torch.inference_mode():

            generated = translation_model.generate(
                **encoded,
                max_length=TRANSLATION_MAX_LENGTH,
                num_beams=4,
                early_stopping=True
            )

        # ----------------------------------------------------
        # DECODE ENGLISH
        # ----------------------------------------------------

        batch_translations = (
            translation_tokenizer.batch_decode(
                generated,
                skip_special_tokens=True
            )
        )

        if len(batch_translations) != len(batch):

            raise RuntimeError(
                "Translation model returned "
                f"{len(batch_translations)} translations "
                f"for {len(batch)} Polish sentences."
            )

        translations.extend(
            batch_translations
        )

        # Free temporary tensors.

        del encoded
        del generated

    if len(translations) != len(sentences):

        raise RuntimeError(
            "Translation count does not match "
            "sentence count."
        )

    print()
    print(
        f"Translated {len(translations)} "
        "sentences successfully."
    )

    return translations


# ============================================================
# CREATE ANKI AUDIO CLIP
# ============================================================

def create_audio_clip(
    audio_file,
    start,
    end,
    output_file
):

    subprocess.run(
        [
            "ffmpeg",

            "-i",
            audio_file,

            "-ss",
            fmt(start),

            "-to",
            fmt(end),

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            output_file,

            "-y"
        ],

        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,

        check=True
    )


# ============================================================
# PROCESS ONE AUDIO FILE
# ============================================================

def process_audio(audio_file):

    filename = os.path.basename(
        audio_file
    )

    file_name = os.path.splitext(
        filename
    )[0]

    csv_file = os.path.join(
        AUDIOFLASHCARDS_DIR,
        f"{file_name}.csv"
    )

    print()
    print("=" * 70)
    print(f"PROCESSING: {filename}")
    print("=" * 70)

    # --------------------------------------------------------
    # LOAD AUDIO
    # --------------------------------------------------------

    print()
    print("Loading audio...")

    audio = whisperx.load_audio(
        audio_file
    )

    # --------------------------------------------------------
    # TRANSCRIBE
    # --------------------------------------------------------

    print()
    print("Transcribing Polish audio...")

    result = whisper_model.transcribe(
        audio,
        batch_size=WHISPER_BATCH_SIZE,
        language=LANGUAGE,
        task="transcribe"
    )

    print()
    print(
        "Detected language:",
        result.get("language")
    )

    # --------------------------------------------------------
    # ALIGN
    # --------------------------------------------------------

    print()
    print("Aligning Polish words...")

    result = whisperx.align(
        result["segments"],
        align_model,
        align_metadata,
        audio,
        DEVICE
    )

    # --------------------------------------------------------
    # EXTRACT SENTENCES
    # --------------------------------------------------------

    print()
    print("Building sentences...")

    sentence_records = (
        extract_sentences(
            result
        )
    )

    if not sentence_records:

        raise RuntimeError(
            "WhisperX did not produce "
            "any usable sentences."
        )

    print()
    print(
        f"Found {len(sentence_records)} "
        "sentences."
    )

    # --------------------------------------------------------
    # SHOW POLISH TRANSCRIPTION
    # --------------------------------------------------------

    for number, record in enumerate(
        sentence_records,
        start=1
    ):

        print(
            f"{number:03}: "
            f"{record['text']}"
        )

    # --------------------------------------------------------
    # LOCAL TRANSLATION
    # --------------------------------------------------------

    polish_sentences = [
        record["text"]
        for record in sentence_records
    ]

    translations = translate_sentences(
        polish_sentences
    )

    for record, translation in zip(
        sentence_records,
        translations
    ):

        record["translation"] = (
            translation
        )

    # --------------------------------------------------------
    # CREATE ANKI AUDIO
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("CREATING ANKI AUDIO")
    print("=" * 70)

    csv_lines = []

    created_audio_files = []

    try:

        for card_number, record in enumerate(
            sentence_records,
            start=1
        ):

            polish = record["text"]

            english = record[
                "translation"
            ]

            start = record["start"]
            end = record["end"]

            media_filename = (
                f"{file_name}_"
                f"{card_number}.m4a"
            )

            output_audio = os.path.join(
                ANKI_MEDIA_DIR,
                media_filename
            )

            print()
            print(
                f"Card {card_number}/"
                f"{len(sentence_records)}"
            )

            # ----------------------------------------------
            # CREATE AUDIO
            # ----------------------------------------------

            create_audio_clip(
                audio_file,
                start,
                end,
                output_audio
            )

            created_audio_files.append(
                output_audio
            )

            # ----------------------------------------------
            # DISPLAY RESULT
            # ----------------------------------------------

            print(
                f"PL: {polish}"
            )

            print(
                f"EN: {english}"
            )

            # ----------------------------------------------
            # ADD TSV LINE
            # ----------------------------------------------

            csv_lines.append(
                f"{polish}\t"
                f"{english} "
                f"[sound:{media_filename}]"
            )

    except Exception:

        print()
        print(
            "Audio generation failed."
        )

        print(
            "Removing audio files created "
            "during this attempt..."
        )

        for created_file in created_audio_files:

            try:

                if os.path.exists(
                    created_file
                ):

                    os.remove(
                        created_file
                    )

            except OSError:
                pass

        raise

    # --------------------------------------------------------
    # WRITE CSV
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("WRITING ANKI CSV")
    print("=" * 70)

    try:

        with open(
            csv_file,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(
                "Polish\tEnglish\tAudio\n"
            )

            file.write(
                "\n".join(
                    csv_lines
                )
            )

    except Exception:

        print()
        print(
            "CSV creation failed."
        )

        print(
            "Removing generated audio..."
        )

        for created_file in created_audio_files:

            try:

                if os.path.exists(
                    created_file
                ):

                    os.remove(
                        created_file
                    )

            except OSError:
                pass

        raise

    print()
    print("CSV created:")
    print(csv_file)

    print()
    print(
        f"Cards created: "
        f"{len(csv_lines)}"
    )

    # --------------------------------------------------------
    # MOVE SOURCE FILE
    # --------------------------------------------------------

    processed_file = os.path.join(
        PROCESSED_DIR,
        filename
    )

    if os.path.exists(
        processed_file
    ):

        print()
        print(
            "A file with this name already "
            "exists in processed/."
        )

        print(
            "Replacing existing file."
        )

        os.remove(
            processed_file
        )

    shutil.move(
        audio_file,
        processed_file
    )

    print()
    print(
        "Original audio moved to:"
    )

    print(
        processed_file
    )

    print()
    print("=" * 70)
    print("FILE COMPLETED SUCCESSFULLY")
    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("POLISH AUDIO -> ANKI")
    print("=" * 70)

    print()
    print("Input:")
    print(UNPROCESSED_DIR)

    print()
    print("Flashcards:")
    print(AUDIOFLASHCARDS_DIR)

    print()
    print("Processed audio:")
    print(PROCESSED_DIR)

    print()
    print("Anki media:")
    print(ANKI_MEDIA_DIR)

    # --------------------------------------------------------
    # FIND AUDIO
    # --------------------------------------------------------

    audio_files = [
        os.path.join(
            UNPROCESSED_DIR,
            filename
        )

        for filename
        in os.listdir(
            UNPROCESSED_DIR
        )

        if filename.lower().endswith(
            SUPPORTED_AUDIO
        )
    ]

    audio_files.sort()

    # --------------------------------------------------------
    # NOTHING FOUND
    # --------------------------------------------------------

    if not audio_files:

        print()
        print("=" * 70)
        print("NO AUDIO FILES FOUND")
        print("=" * 70)

        print()
        print(
            "Put audio files in:"
        )

        print(
            UNPROCESSED_DIR
        )

        return

    print()
    print(
        f"Found {len(audio_files)} "
        "audio file(s)."
    )

    # --------------------------------------------------------
    # PROCESS FILES
    # --------------------------------------------------------

    successful = 0
    failed = 0

    for number, audio_file in enumerate(
        audio_files,
        start=1
    ):

        print()
        print("#" * 70)

        print(
            f"FILE {number} OF "
            f"{len(audio_files)}"
        )

        print("#" * 70)

        try:

            process_audio(
                audio_file
            )

            successful += 1

        except Exception as error:

            failed += 1

            print()
            print("=" * 70)
            print("ERROR PROCESSING FILE")
            print("=" * 70)

            print()
            print(
                os.path.basename(
                    audio_file
                )
            )

            print()
            print("Error:")

            print(
                error
            )

            print()
            print(
                "The original audio file "
                "was NOT moved."
            )

            print(
                "It remains in unprocessed/."
            )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("ALL FILES FINISHED")
    print("=" * 70)

    print()
    print(
        f"Successful: {successful}"
    )

    print(
        f"Failed:     {failed}"
    )

    print()
    print("CSV flashcards:")
    print(AUDIOFLASHCARDS_DIR)

    print()
    print("Processed originals:")
    print(PROCESSED_DIR)

    print()
    print("Anki audio clips:")
    print(ANKI_MEDIA_DIR)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
