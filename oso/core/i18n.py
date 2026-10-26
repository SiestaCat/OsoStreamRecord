import json
from functools import lru_cache
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "locales"


@lru_cache(maxsize=8)
def translations(lang):
    lang = lang if lang in ("en", "es", "pt") else "en"
    return json.loads((BASE / f"{lang}.json").read_text(encoding="utf-8"))


def translate(lang, key):
    return translations(lang).get(key, translations("en").get(key, key))
