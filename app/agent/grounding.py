"""Which draft parameters cannot be found anywhere in the conversation.

The approval card already tells apart two kinds of value: one the user stated,
and one the app filled in as a default (`applied_defaults`). There is a third,
and it was rendering as the first: a value the MODEL supplied because a
question was asked and answering it felt more helpful than relaying it.

Fourteen required parameters carry "ONLY set this when the user has said..."
in their help text for exactly that reason. `docs/BACKLOG.md` recorded what
that instruction is worth: 2 of 3 on a repeat probe. A prompt cannot be a
guard, because the failure it guards against is the model not following the
prompt.

So this does not try to stop the model writing a value. It reports, in code,
which values cannot be traced to anything anyone said, and the card shows
those separately -- which removes the actual harm. The harm was never that a
guess exists; it is that a guess and a choice look identical at the moment of
approval.

**Grounding is deliberately generous, and false NEGATIVES are the safe
direction here.** A value is grounded if it appears anywhere in the
conversation, including in a tool's own output -- a basis set named by an
earlier job's summary, an active space returned by a literature search, a
coordinate the user gave three turns ago. Flagging one of those would be
noise on a card that must stay worth reading, and noise is how a warning
stops being read. Missing one guess is recoverable; crying wolf is not.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# Only the parameters whose help says the model must not invent them. A value
# the app is entitled to default (`use_tda`, say) is already covered by
# applied_defaults and does not belong here.
from app.chemistry.registry2.params import PARAMS_BY_NAME

GUARDED_PARAMS = frozenset(
    name for name, spec in PARAMS_BY_NAME.items() if "ONLY set this" in (spec.help or "")
)

UNGROUNDED_KEY = "ungrounded"

_WORD = re.compile(r"[a-z0-9.+*-]+")


def _leaves(value: Any) -> Iterable[Any]:
    """Every scalar inside a value, however it is nested."""
    if isinstance(value, dict):
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _leaves(v)
    else:
        yield value


def _mentions(haystack: str, leaf: Any) -> bool:
    """Is this one scalar findable in the conversation text?

    Booleans are never checked. "true" is not something a user types, and a
    boolean has only two values, so a wrong one is a coin flip rather than an
    invention -- flagging every one of them would drown the real findings.
    """
    if isinstance(leaf, bool) or leaf is None:
        return True
    if isinstance(leaf, (int, float)):
        text = ("%g" % leaf)
        # A bare number must appear as its own token: `2` should not be
        # grounded by the `2` inside `cc-pVDZ` or a job id.
        return re.search(r"(?<![\w.])%s(?![\w.])" % re.escape(text), haystack) is not None
    token = str(leaf).strip().lower()
    if len(token) < 2:
        return True  # too short to say anything about
    if token in haystack:
        return True
    # Basis and functional names get written a dozen ways: cc-pVDZ, ccpvdz,
    # "cc pvdz". Compare with the punctuation removed before deciding a user
    # never said it.
    squashed = re.sub(r"[^a-z0-9]", "", token)
    return bool(squashed) and squashed in re.sub(r"[^a-z0-9]", "", haystack)


def conversation_text(messages: Iterable[Any]) -> str:
    """Everything anyone said, lowercased, as one haystack.

    Tool output counts. A basis set that came back from a capability lookup,
    an active space from a literature search and a geometry from an earlier
    job are all things the user effectively chose by accepting them, and
    treating them as inventions would flag the app's own good behaviour.
    """
    parts = []
    for m in messages or ():
        content = getattr(m, "content", None)
        if content is None and isinstance(m, dict):
            content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(str(c) for c in content)
    return "\n".join(parts).lower()


def ungrounded_params(updates: dict, messages: Iterable[Any]) -> list[str]:
    """Names from `updates` whose value is nowhere in the conversation.

    Only guarded parameters are considered, and a parameter counts as
    grounded the moment every scalar inside its value is findable.
    """
    if not updates:
        return []
    haystack = conversation_text(messages)
    if not haystack:
        return []
    out = []
    for name, value in updates.items():
        if name not in GUARDED_PARAMS or value is None:
            continue
        if not all(_mentions(haystack, leaf) for leaf in _leaves(value)):
            out.append(name)
    return sorted(out)
