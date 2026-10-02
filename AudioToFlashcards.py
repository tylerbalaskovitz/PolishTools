import whisperx
import subprocess
import os
from deep_translator import GoogleTranslator

# -------------------
# CONFIG
# -------------------
file_name = "BlueyCamping07182026B"

AUDIO_FILE = f"{file_name}.mp3"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

ANKI_MEDIA_DIR = os.path.expanduser(
    "~/.local/share/Anki2/User 1/collection.media"
)

CSV_FILE = os.path.join(SCRIPT_DIR, f"{file_name}.csv")

device = "cuda"

CONF_THRESHOLD = 0.75
MIN_WORDS = 2 

translator = GoogleTranslator(source="pl", target="en")

os.makedirs(ANKI_MEDIA_DIR, exist_ok=True)

# -------------------
# LOAD MODEL
# -------------------
print("Loading WhisperX model...")

model = whisperx.load_model("large", device)

# -------------------
# LOAD AUDIO
# -------------------
print("Loading audio...")

audio = whisperx.load_audio(AUDIO_FILE)

# -------------------
# TRANSCRIBE
# -------------------
print("Transcribing Polish audio...")

result = model.transcribe(
    audio,
    batch_size=16,
    language="pl",
    task="transcribe"
)

print("Detected language:", result.get("language"))

# -------------------
# ALIGNMENT
# -------------------
print("Aligning words...")

align_model, metadata = whisperx.load_align_model(
    language_code="pl",
    device=device
)

result = whisperx.align(
    result["segments"],
    align_model,
    metadata,
    audio,
    device
)

# -------------------
# TIME FORMATTER
# -------------------
def fmt(t):
    ms = int(t * 1000)

    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    ms = ms % 1000

    return f"{h:02}:{m:02}:{s:02}.{ms:03}"

# -------------------
# CARD CREATION
# -------------------
csv_lines = []

i = 1

current_words = []

def flush_segment():
    global current_words
    global i

    if len(current_words) < MIN_WORDS:
        current_words = []
        return

    # -------------------
    # BUILD SENTENCE
    # -------------------
    text = " ".join(
        w["word"].strip()
        for w in current_words
    ).strip()

    start = current_words[0]["start"]
    end = current_words[-1]["end"]

    # -------------------
    # TRANSLATE
    # -------------------
    try:
        translation = translator.translate(text)
    except Exception:
        translation = ""

    # -------------------
    # AUDIO EXPORT
    # -------------------
    media_filename = f"{file_name}_{i}.m4a"

    out_file = os.path.join(
        ANKI_MEDIA_DIR,
        media_filename
    )

    subprocess.run(
        [
            "ffmpeg",
            "-i", AUDIO_FILE,
            "-ss", fmt(start),
            "-to", fmt(end),
            "-c:a", "aac",
            "-b:a", "128k",
            out_file,
            "-y"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # -------------------
    # CSV ENTRY
    # -------------------
    csv_lines.append(
        f"{text}\t{translation} [sound:{media_filename}]"
    )

    print(f"{i} | {text}")

    i += 1

    current_words = []

# -------------------
# PROCESS WORDS
# -------------------
print("Building sentence cards...")

for seg in result["segments"]:

    words = seg.get("words", [])

    if not words:
        continue

    for w in words:

        if "start" not in w or "end" not in w:
            continue

        prob = w.get("probability", 1.0)

        # skip uncertain words
        if prob < CONF_THRESHOLD:
            continue

        current_words.append(w)

        word_text = w["word"].strip()

        # sentence boundary detection
        if (
            word_text.endswith(".")
            or word_text.endswith("?")
            or word_text.endswith("!")
        ):
            flush_segment()

# flush leftovers
flush_segment()

# -------------------
# WRITE CSV
# -------------------
print("Writing CSV...")

with open(CSV_FILE, "w", encoding="utf-8") as f:

    f.write("Polish\tEnglish\tAudio\n")

    f.write("\n".join(csv_lines))

print("DONE")
print("CSV:", CSV_FILE)
print("Audio:", ANKI_MEDIA_DIR)
