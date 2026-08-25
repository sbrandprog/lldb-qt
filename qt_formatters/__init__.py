"""Python-модуль форматтеров lldb для типов Qt.

Подключается через: command script import qt_formatters

Поддерживает Qt5 и Qt6. Версия Qt определяется на лету по структуре
отлаживаемого процесса. Для QtCore-типов реализованы summary и, где нужно,
synthetic-провайдеры: QString, QByteArray, QStringList, QList/QVector, QMap,
QHash, QVariant, даты/время и геометрические типы.
"""

import lldb

from . import common
from . import qt5
from . import qt6

__all__ = ["__lldb_init_module", "initialize"]


def _detect_qt_version(debugger):
    """Определяет версию Qt по доступным типам в отлаживаемом процессе.

    Возвращает 5, 6 или None (если не удалось определить).
    """
    try:
        target = debugger.GetSelectedTarget()
        if not target or not target.IsValid():
            return None
        # В Qt6 QString использует QArrayDataPointer (поле ptr), а его
        # QArrayData не имеет поля offset. По наличию символа/типа определяем.
        qt6_marker = target.FindFirstType("QArrayDataPointer<char16_t>")
        if qt6_marker and qt6_marker.IsValid():
            return 6
        qt5_marker = target.FindFirstType("QStringData")
        if qt5_marker and qt5_marker.IsValid():
            return 5
    except Exception:
        pass
    return None


CATEGORY = "qt"


def _register_summary(debugger, type_names, fn, expand=False):
    """Регистрирует summary-функцию для набора имён типов."""
    flags = " -e" if expand else ""
    for name in type_names:
        try:
            debugger.HandleCommand(f'type summary add{flags} -F {fn} -x "{name}" -w {CATEGORY} -h')
        except Exception:
            pass


def _register_synthetic(debugger, type_names, class_path):
    """Регистрирует synthetic-провайдер (класс) для набора имён типов."""
    for name in type_names:
        try:
            debugger.HandleCommand(f'type synthetic add -l {class_path} -x "{name}" -w {CATEGORY}')
        except Exception:
            pass


def initialize(debugger, internal_dict):
    """Регистрирует все форматтеры в debugger."""
    qt_version = _detect_qt_version(debugger)

    if qt_version == 6:
        qt6.register(debugger, internal_dict, _register_summary, _register_synthetic)
    elif qt_version == 5:
        qt5.register(debugger, internal_dict, _register_summary, _register_synthetic)
    else:
        # Если не смогли определить — регистрируем оба набора; lldb сам
        # применит тот, чей тип совпадёт в рантайме.
        qt5.register(debugger, internal_dict, _register_summary, _register_synthetic)
        qt6.register(debugger, internal_dict, _register_summary, _register_synthetic)

    try:
        debugger.HandleCommand(f"type category enable {CATEGORY}")
    except Exception:
        pass


def __lldb_init_module(debugger, internal_dict):
    """Точка входа при `command script import qt_formatters`."""
    initialize(debugger, internal_dict)
