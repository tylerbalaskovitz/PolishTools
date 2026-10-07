from AnkiPackageManager import AnkiPackageManager

manager = AnkiPackageManager()

try:
    manager.add_card(
        original="kotami",
        lemma="kot",
        sense="1.1",
        definition="Felis catus, zwierzę domowe",
        context="Bawiłem się z kotami.",
    )

    manager.add_card(
        original="dziećmi",
        lemma="dziecko",
        sense="1.1",
        definition="Młody człowiek.",
        context="Rozmawiałem z dziećmi.",
    )
finally:
    manager.close()
