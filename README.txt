Polish Anki - Wikimedia audio fix
=================================
INSTALL (Arch Linux):
  cd ~/PolishTools
  cp data/flashcards.db data/flashcards.db.bak  # if database exists
  # Extract these 4 .py files into ~/PolishTools, replacing the old scripts.
  python -m pip install --user requests genanki morfeusz2  # or use your existing venv

Wikimedia requires a genuine operator contact in User-Agent, for API and media requests.
Use your REAL email or project URL, not example.com:
  export WM_CONTACT='you@your-real-domain.com'
To keep this setting for future terminals, add the export to ~/.bashrc (bash) or ~/.zshrc (zsh).

Start continuous word entry:
  python FlashcardMaker.py

Recover missing original audio on saved base-form cards and rebuild affected daily .apkg files:
  python AnkiPackageManager.py --repair-audio

Inspect card counts:
  python AnkiPackageManager.py --stats

Audio is attached ONLY to the lemma/base-form card, never an inflected card.
A word like poszedlem (properly poszedłem) makes two cards: poszedłem (silent) and pójść (audio).
Audio and images are cached under downloads/; saved copies are in media/.

IMPORTANT: Wikimedia may rate-limit original-media downloads independently of the Action API.
A proper User-Agent and caching reduce avoidable blocks, but no client can guarantee
Wikimedia will accept every request. On HTTP 429 the tool respects Retry-After,
persists a cooldown, and leaves missing audio eligible for --repair-audio later.
DO NOT reset your SQLite database to retry audio.
