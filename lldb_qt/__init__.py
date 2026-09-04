"""Python-модуль форматтеров lldb для типов Qt.

Подключается через: command script import lldb_qt

Поддерживает Qt5 и Qt6 одновременно. Форматтеры версия-независимы: каждый
summary/synthetic сам определяет фактическую раскладку типа по структуре
SBValue, поэтому регистрация не требует загруженного таргета и работает при
подключении модуля в .lldbinit (до создания таргета).

Для QtCore-типов реализованы summary и, где нужно, synthetic-провайдеры:
QString, QByteArray, QStringList, QList/QVector, QMap, QHash, QVariant,
даты/время и геометрические типы.
"""

import lldb
import re

from . import assoc
from . import containers
from . import datetime
from . import geometry
from . import set as set_mod
from . import strings
from . import variant

__all__ = ["__lldb_init_module", "initialize"]

CATEGORY = "qt"


def _anchor_re(name):
    """Якоряет простое имя типа, оставляя явные regex нетронутыми.

    Точные имена типа (QString, QDate, ...) регистрируются через -x (regex);
    без якоря они совпадают и с производными типами (QStringList, QDateTime).
    """
    if re.search(r"[.*+?()[\]{}|^$\\]", name):
        return name
    return f"^{name}$"


def _handle(debugger, command, result):
    """Выполняет lldb-команду, проверяя её результат через command interpreter."""
    try:
        debugger.GetCommandInterpreter().HandleCommand(command, result)
    except Exception as exc:
        print(f"[lldb_qt] {command}: {exc}")


def _register_summary(debugger, type_names, fn, expand=False):
    """Регистрирует summary-функцию для набора имён типов."""
    flags = " -e" if expand else ""
    for name in type_names:
        pattern = _anchor_re(name)
        result = lldb.SBCommandReturnObject()
        command = f'type summary add{flags} -F {fn} -x "{pattern}" -w {CATEGORY}'
        _handle(debugger, command, result)
        if not result.Succeeded():
            print(f"[lldb_qt] summary {fn} for {name}: {result.GetError()}")


def _register_synthetic(debugger, type_names, class_path):
    """Регистрирует synthetic-провайдер (класс) для набора имён типов."""
    for name in type_names:
        pattern = _anchor_re(name)
        result = lldb.SBCommandReturnObject()
        command = f'type synthetic add -l {class_path} -x "{pattern}" -w {CATEGORY}'
        _handle(debugger, command, result)
        if not result.Succeeded():
            print(f"[lldb_qt] synthetic {class_path} for {name}: {result.GetError()}")


def initialize(debugger, internal_dict):
    """Регистрирует все форматтеры в debugger (без детекции версии Qt)."""
    s = strings.__name__
    _register_summary(debugger, ["QString"], f"{s}.format_qstring")
    _register_summary(debugger, ["QByteArray"], f"{s}.format_qbytearray")
    _register_summary(debugger, ["QChar"], f"{s}.format_qchar")
    _register_synthetic(debugger, ["QString", "QByteArray"], f"{s}.StringSynthetic")

    c = containers.__name__
    _register_synthetic(
        debugger,
        ["(QList<.*>|QVector<.*>|QStringList|QStack<.*>|QQueue<.*>|QByteArrayList)$"],
        f"{c}.QListSynthetic",
    )
    _register_summary(
        debugger,
        ["(QList<.*>|QVector<.*>|QStringList|QStack<.*>|QQueue<.*>|QByteArrayList)$"],
        f"{c}._summary_qlist",
        expand=True,
    )

    a = assoc.__name__
    _register_summary(debugger, ["QHash<.*>$"], f"{a}.format_qhash")
    _register_synthetic(debugger, ["QHash<.*>$", "QMultiHash<.*>$"], f"{a}.QHashSynthetic")
    _register_summary(debugger, ["QMultiHash<.*>$"], f"{a}.format_qmultihash")
    _register_synthetic(debugger, ["^QHashPrivate::MultiNode<.*>$"], f"{a}.QMultiHashNodeSynthetic")
    _register_summary(debugger, ["QMap<.*>$"], f"{a}.format_qmap")
    _register_synthetic(debugger, ["QMap<.*>$", "QMultiMap<.*>$"], f"{a}.QMapSynthetic")
    _register_summary(debugger, ["QMultiMap<.*>$"], f"{a}.format_qmultimap")

    s = set_mod.__name__
    _register_summary(debugger, ["QSet<.*>$"], f"{s}.format_qset", expand=True)
    _register_synthetic(debugger, ["QSet<.*>$"], f"{s}.QSetSynthetic")

    g = geometry.__name__
    _register_summary(debugger, ["QSize"], f"{g}.format_qsize")
    _register_summary(debugger, ["QPoint"], f"{g}.format_qpoint")
    _register_summary(debugger, ["QRect"], f"{g}.format_qrect")
    _register_summary(debugger, ["QLine"], f"{g}.format_qline")
    _register_summary(debugger, ["QSizeF"], f"{g}.format_qsizef")
    _register_summary(debugger, ["QPointF"], f"{g}.format_qpointf")
    _register_summary(debugger, ["QRectF"], f"{g}.format_qrectf")
    _register_summary(debugger, ["QLineF"], f"{g}.format_qlinef")

    dt = datetime.__name__
    _register_summary(debugger, ["QDate"], f"{dt}.format_qdate")
    _register_summary(debugger, ["QTime"], f"{dt}.format_qtime")
    _register_summary(debugger, ["QDateTime"], f"{dt}.format_qdatetime")

    v = variant.__name__
    _register_summary(debugger, ["QVariant"], f"{v}.format_qvariant")
    _register_synthetic(debugger, ["QVariant"], f"{v}.QVariantSynthetic")

    try:
        debugger.HandleCommand(f"type category enable {CATEGORY}")
    except Exception:
        pass


def __lldb_init_module(debugger, internal_dict):
    """Точка входа при `command script import lldb-qt`."""
    initialize(debugger, internal_dict)
