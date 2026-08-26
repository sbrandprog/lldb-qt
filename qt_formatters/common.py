"""Общая инфраструктура для lldb-форматтеров Qt.

Содержит низкоуровневые хелперы для безопасного чтения памяти через SBValue
и общие обёртки для регистрации summary/synthetic провайдеров.
"""


def raw_value(value):
    """Возвращает 'сырое' SBValue, минуя synthetic-обёртку.

    Когда применяется synthetic-провайдер, self.value в summary/провайдере
    уже обёрнут в synthetic-структуру, и GetChildMemberWithName ищет среди
    synthetic-детей, а не реальных полей. Чтобы прочитать настоящие поля
    контейнера, нужно запросить non-synthetic значение.
    """
    if value is None or not value.IsValid():
        return value
    try:
        return value.GetNonSyntheticValue()
    except Exception:
        return value


def get_child_by_name(value, name):
    """Находит дочерний SBValue по имени поля (с учётом базовых классов).

    lldb может не показывать поле прямо в GetChildMemberWithName, если оно
    спрятано за базовым классом шаблонов; пробуем разные стратегии.
    """
    if not value.IsValid():
        return None
    child = value.GetChildMemberWithName(name)
    if child and child.IsValid():
        return child
    return None


def read_pointer(value):
    """Читает значение указателя/целочисленного поля из SBValue.

    Возвращает int (адрес или число) или None при неудаче.
    """
    if value is None or not value.IsValid():
        return None
    return value.GetValueAsUnsigned()


def get_template_arg_type(value_type):
    """Возвращает SBType первого шаблонного аргумента (для QList<T> и т.п.)."""
    return value_type.GetTemplateArgumentType(0)
