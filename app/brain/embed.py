"""Passage vectors without a model: hashed word counts ("feature hashing").

Each content word (lower case, simple plural strip, stop words dropped) adds +1 or -1 to one of EMBED_DIM slots
chosen by a hash of the word; the vector is then scaled to length 1. Two passages are close when they share
words, so this finds passages that use the question's words, not passages that mean the same thing in other
words. It needs no model, no download and no network, and gives the same vector every time.
"""

import hashlib
import math
import re

from app import config

WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
STOP = frozenset("""
a an the and or but if then so of to in on at by for with from as is are was were be been being it its this that
these those there here what which who whom whose why how when where do does did done have has had not no yes can
could should would will shall may might must we our us you your they them their he she his her i me my about into
over under than too very just also only any all each every some such own same other more most again once up down
out off one two after before while during until any get got
""".split())


def _norm(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss") and "-" not in w:
        return w[:-1]
    return w


def content_words(text: str) -> list[str]:
    return [_norm(w) for w in WORD.findall(text.lower()) if w not in STOP and len(w) > 1]


def embed(text: str, dim: int | None = None) -> list[float]:
    dim = dim or config.EMBED_DIM
    v = [0.0] * dim
    for w in content_words(text):
        h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "big")
        v[h % dim] += 1.0 if (h >> 63) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v))
    if n == 0:
        v[0] = 1.0  # an empty text still gets a valid (unit) vector
        return v
    return [x / n for x in v]
