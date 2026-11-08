"""Key <-> character mapping for the us and ua (xkb default "unicode") layouts.

A key sequence is represented canonically as the string the us layout produces,
so "ghbdsn" *is* the key sequence; to_uk("ghbdsn") == "привіт".
"""

US_LOWER = "`1234567890-=qwertyuiop[]\\asdfghjkl;'zxcvbnm,./"
UA_LOWER = "'1234567890-=йцукенгшщзхїґфівапролджєячсмитьбю."
US_UPPER = '~!@#$%^&*()_+QWERTYUIOP{}|ASDFGHJKL:"ZXCVBNM<>?'
UA_UPPER = 'ʼ!"№;%:?*()_+ЙЦУКЕНГШЩЗХЇҐФІВАПРОЛДЖЄЯЧСМИТЬБЮ,'

assert len(US_LOWER) == len(UA_LOWER) and len(US_UPPER) == len(UA_UPPER)

_US2UA = dict(zip(US_LOWER + US_UPPER, UA_LOWER + UA_UPPER))
_UA2US = {v: k for k, v in _US2UA.items()}
# Apostrophe variants that people (and corpora) use in Ukrainian words.
for _a in "’ʼ‘":
    _UA2US.setdefault(_a, "`")

EN_LETTERS = set("abcdefghijklmnopqrstuvwxyz")
UK_LETTERS = set("абвгґдеєжзиіїйклмнопрстуфхцчшщьюя")
APOSTROPHES = "'’ʼ‘"


def to_uk(keys: str) -> str:
    return "".join(_US2UA.get(c, c) for c in keys)


def to_keys(text: str) -> str:
    """Ukrainian text -> the us-layout key sequence that types it."""
    return "".join(_UA2US.get(c, c) for c in text)


def norm_apostrophe(s: str) -> str:
    for a in APOSTROPHES:
        s = s.replace(a, "'")
    return s
