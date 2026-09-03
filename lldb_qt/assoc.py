"""Версия-независимые summary и synthetic для ассоциативных контейнеров."""

from itertools import islice

from . import common
from . import hash as hash_mod
from . import map as map_mod
from .providers import IterSynthetic, build_values


def _format_items(size, entries):
    """Собирает строку 'size=N [(k: v), ...]' из итератора пар (k, v)."""
    if size == 0:
        return "[]"
    items = []
    for k, v in islice(entries, 8):
        items.append(f"({common.item_summary(k)}: {common.item_summary(v)})")
    tail = "…" if size > 8 else ""
    return "size=" + str(size) + " [" + ", ".join(items) + tail + "]"


def format_qhash(valobj, internal_dict):
    """Summary для QHash<K,V>: size=N [(k: v), ...].

    Пары ключ/значение читаются через общий обход hash.iter_hash_nodes
    (Qt5 — buckets/связанные списки, Qt6 — spans). Порядок не детерминирован.
    """
    try:
        size = hash_mod.hash_size(valobj)
        if size is None:
            return "<invalid>"
        entries = (
            (node.GetChildMemberWithName("key"), node.GetChildMemberWithName("value"))
            for node in hash_mod.iter_hash_nodes(valobj)
        )
        return _format_items(size, entries)
    except Exception:
        return "<unreadable>"


def _iter_multihash_entries(valobj):
    """Генератор пар (key, value) для QMultiHash.

    Qt5: QMultiHash наследует QHash, каждая пара — отдельный узел (value — T).
    Qt6: отдельный класс с узлами MultiNode<K,V>, где value — указатель на
    связанный список Chain<T>; раскрываем цепочку в отдельные записи.
    """
    for node in hash_mod.iter_hash_nodes(valobj):
        k = node.GetChildMemberWithName("key")
        v = node.GetChildMemberWithName("value")
        if v is not None and v.IsValid() and v.GetType().IsPointerType() and "Chain" in v.GetTypeName():
            chain = v
            guard = 0
            while chain is not None and chain.IsValid() and guard < 1024:
                ptr = common.read_pointer(chain)
                if not ptr:
                    break
                cc = chain.Dereference()
                if cc is None or not cc.IsValid():
                    break
                cv = cc.GetChildMemberWithName("value")
                if cv is not None and cv.IsValid():
                    yield k, cv
                chain = cc.GetChildMemberWithName("next")
                guard += 1
        else:
            yield k, v


def format_qmultihash(valobj, internal_dict):
    """Summary для QMultiHash<K,V>: size=N [(k: v), ...].

    Qt6: реальное число пар — в отдельном поле m_size (d->size считает только
    уникальные ключи). Qt5: QMultiHash наследует QHash, размер в d->size.
    """
    try:
        raw = common.raw_value(valobj)
        m_size = common.get_child_by_name(raw, "m_size")
        if m_size is not None and m_size.IsValid():
            size = m_size.GetValueAsUnsigned()
        else:
            size = hash_mod.hash_size(valobj)
        if size is None:
            return "<invalid>"
        return _format_items(size, _iter_multihash_entries(valobj))
    except Exception:
        return "<unreadable>"


def format_qmap(valobj, internal_dict):
    """Summary для QMap<K,V>: size=N [(k: v), ...].

    Пары читаются через map.iter_map_nodes (Qt5 — QMapNode, Qt6 — std::map).
    Порядок детерминирован (сортировка по ключу).
    """
    try:
        size = map_mod.map_size(valobj)
        if size is None:
            return "<invalid>"
        entries = ((map_mod.entry_key(node), map_mod.entry_value(node)) for node in map_mod.iter_map_nodes(valobj))
        return _format_items(size, entries)
    except Exception:
        return "<unreadable>"


def format_qmultimap(valobj, internal_dict):
    """Summary для QMultiMap<K,V>.

    Раскладка повторяет QMap (Qt5 — базовый QMap с QMapData*, Qt6 — std::multimap),
    поэтому просто делегируем в format_qmap.
    """
    return format_qmap(valobj, internal_dict)


class QHashSynthetic(IterSynthetic):
    """Synthetic для QHash<K,V>: записи (key/value) как дочерние [i].

    Как и встроенные форматтеры std::map/std::unordered_map, каждый ребёнок —
    это узел-запись, внутри которого видны и ключ, и значение (поля key/value;
    в Qt5 у узла есть также служебные next/h). Реализует контракт
    IterSynthetic: build_values() -> list[(имя, SBValue)].
    """

    def build_values(self):
        return build_values(
            self.value.GetTarget(),
            ((node.GetLoadAddress(), node.GetType()) for node in hash_mod.iter_hash_nodes(self.value)),
        )


def _is_chain(value):
    """True, если value — указатель на MultiNodeChain (Qt6 QMultiHash)."""
    return (
        value is not None
        and value.IsValid()
        and value.GetType().IsPointerType()
        and "Chain" in value.GetTypeName()
    )


class QMultiHashSynthetic(IterSynthetic):
    """Synthetic для QMultiHash<K,V>: дочерние [i] по раскладке версии.

    В Qt6 QMultiHash — отдельный класс: каждый узел MultiNode<K,V> хранит ключ
    и указатель на связанный список Chain<T> значений. Переиспользуем
    _iter_multihash_entries (как в format_qmultihash), чтобы раскрыть цепочки в
    плоские значения — число детей совпадает с размером из m_size. В Qt5
    QMultiHash наследует QHash и каждая пара — отдельный узел с полями
    key/value, поэтому поведение совпадает с QHashSynthetic (узлы-записи).
    """

    def build_values(self):
        target = self.value.GetTarget()
        if any(_is_chain(node.GetChildMemberWithName("value")) for node in hash_mod.iter_hash_nodes(self.value)):
            # Qt6: плоские значения раскрытых цепочек.
            return build_values(
                target,
                (
                    (v.GetLoadAddress(), v.GetType())
                    for _, v in _iter_multihash_entries(self.value)
                    if v is not None and v.IsValid() and v.GetLoadAddress()
                ),
            )
        # Qt5: узлы-записи key/value, как QHashSynthetic.
        return build_values(
            target,
            ((node.GetLoadAddress(), node.GetType()) for node in hash_mod.iter_hash_nodes(self.value)),
        )


class QMapSynthetic(IterSynthetic):
    """Synthetic для QMap<K,V>/QMultiMap<K,V>: записи как дочерние [i].

    Каждый ребёнок — узел-запись: QMapNode<K,V> (поля key/value) в Qt5 или
    std::pair<const K,V> (поля first/second) в Qt6. Реализует контракт
    IterSynthetic: build_values() -> list[(имя, SBValue)].
    """

    def build_values(self):
        return build_values(
            self.value.GetTarget(),
            ((node.GetLoadAddress(), node.GetType()) for node in map_mod.iter_map_nodes(self.value)),
        )
