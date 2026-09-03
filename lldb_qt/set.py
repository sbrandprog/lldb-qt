"""Версия-независимые форматтеры для QSet<T>.

QSet<T> в Qt5 и Qt6 — обёртка над QHash<T, QHashDummyValue> (единственный член
q_hash). Выдача элементов множества сводится к обходу ключей QHash, который
реализован в hash.iter_hash_nodes.
"""

from itertools import islice

from . import common
from . import hash as hash_mod
from .providers import IterSynthetic, build_values

import lldb


def _qhash_of(valobj):
    """Возвращает член q_hash (QHash<T, QHashDummyValue>) или None."""
    raw = common.raw_value(valobj)
    if raw is None or not raw.IsValid():
        return None
    q_hash = common.get_child_by_name(raw, "q_hash")
    if q_hash is None or not q_hash.IsValid():
        return None
    return q_hash


def _key_info(valobj):
    """Возвращает (elem_type, q_hash) для QSet любой версии Qt (или (None, None))."""
    q_hash = _qhash_of(valobj)
    if q_hash is None:
        return None, None
    elem_type = q_hash.GetType().GetTemplateArgumentType(0)
    return elem_type, q_hash


def _iter_key_addrs(q_hash):
    """Генератор адресов ключей QSet (по обходу QHash)."""
    for node in hash_mod.iter_hash_nodes(q_hash):
        key = node.GetChildMemberWithName("key")
        if key is None or not key.IsValid():
            continue
        addr = key.GetLoadAddress()
        if addr:
            yield addr


def _key_value(target, addr, elem_type, name):
    """Создаёт SBValue ключа типа elem_type по адресу addr (или None)."""
    if not addr or elem_type is None or not elem_type.IsValid():
        return None
    return target.CreateValueFromAddress(name, lldb.SBAddress(addr, target), elem_type)


def format_qset(valobj, internal_dict):
    """Summary для QSet<T>: size=N [k1, k2, ...]."""
    try:
        elem_type, q_hash = _key_info(valobj)
        if elem_type is None:
            return "<invalid>"
        size = hash_mod.hash_size(q_hash)
        if size is None:
            return "<invalid>"
        if size == 0:
            return "[]"
        items = []
        for addr in islice(_iter_key_addrs(q_hash), 8):
            v = _key_value(valobj.GetTarget(), addr, elem_type, "[i]")
            if v is None or not v.IsValid():
                items.append("?")
                continue
            items.append(common.item_summary(v))
        tail = "…" if size > 8 else ""
        return "size=" + str(size) + " [" + ", ".join(items) + tail + "]"
    except Exception:
        return "<unreadable>"


class QSetSynthetic(IterSynthetic):
    """Synthetic для QSet<T>: элементы-ключи как дочерние [i].

    Реализует контракт IterSynthetic: build_values() -> list[(имя, SBValue)].
    """

    def build_values(self):
        elem_type, q_hash = _key_info(self.value)
        if elem_type is None:
            return []
        return build_values(
            self.value.GetTarget(),
            ((addr, elem_type) for addr in _iter_key_addrs(q_hash)),
        )
