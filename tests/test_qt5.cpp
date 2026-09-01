// Тестовая программа для lldb-форматтеров Qt (Qt5).
//
// Содержит глобальные инстансы поддерживаемых типов, чтобы их можно было
// легко прочитать из lldb. Собирается под Qt5 в исполняемый test_qt5.
//
// Программа выводит в stderr строку вида:QT_VERSION=5.15.19
// чтобы тестовый скрипт знал, какая версия Qt использована.

#include <QtCore/QByteArray>
#include <QtCore/QDate>
#include <QtCore/QDateTime>
#include <QtCore/QHash>
#include <QtCore/QLine>
#include <QtCore/QMap>
#include <QtCore/QPoint>
#include <QtCore/QRect>
#include <QtCore/QSize>
#include <QtCore/QString>
#include <QtCore/QStringList>
#include <QtCore/QTime>
#include <QtCore/QUrl>
#include <QtCore/QVariant>
#include <QtCore/QVector>

#include <cstdio>

#define QT_MAJOR 5

// Простая POD-структура без Q_DECLARE_TYPEINFO: для QList из таких типов в Qt5
// применяется IndirectLayout (элементы хранятся по указателю).
struct PlainPair
{
    int a;
    int b;
};

// --- Глобальные переменные для чтения из lldb ----------------------------

// Точка остановки после инициализации всех глобальных данных.
void qt_break_anchor()
{
    // точка остановки
}

static const char * qtVersion()

{
    return QT_VERSION_STR;
}

// Глобальные строки
QString g_string_ascii = QString("hello world");
QString g_string_unicode = QString::fromUtf8("привет мир ☺ 日本語");
QString g_string_emoji = QString::fromUtf8("😀🚀🔥");
QString g_string_empty;
QString g_string_long = QString(400, QLatin1Char('x'));
QByteArray g_bytes = QByteArray("byte-data-123");
QByteArray g_bytes_empty;
QByteArray g_bytes_hex = QByteArray("\x01\x02\xff\x00\x10", 5);

// Списки
QStringList g_stringlist = QStringList() << "alpha" << "beta" << "gamma" << "delta";
QStringList g_stringlist_empty;

// QVector / inline-списки (структура различается в Qt5/Qt6)
QVector<QString> g_qvector;
QList<int> g_qlist_ints;
QList<PlainPair> g_qlist_pairs; // IndirectLayout: указатели на PlainPair

// Ассоциативные контейнеры
QMap<QString, int> g_map;
QHash<QString, int> g_hash;

// QVariant
QVariant g_variant_int = QVariant(42);
QVariant g_variant_str = QVariant(QString("hi"));
QVariant g_variant_double = QVariant(3.14);
QVariant g_variant_null;

// Дата / время
QDate g_date = QDate(2024, 2, 29);
QTime g_time = QTime(13, 45, 30);
QDateTime g_dt = QDateTime(QDate(2024, 2, 29), QTime(23, 59, 59));

// Геометрия
QSize g_size = QSize(800, 600);
QPoint g_point = QPoint(12, -34);
QRect g_rect = QRect(0, 0, 640, 480);
QLine g_line = QLine(1, 2, 3, 4);
QUrl g_url = QUrl("https://example.com/path?q=1");

int main(int argc, char ** argv)
{
    // Наполняем ассоциативные контейнеры после статической инициализации
    g_map = QMap<QString, int>();
    g_map.insert("one", 1);
    g_map.insert("two", 2);
    g_map.insert("three", 3);
    g_hash = QHash<QString, int>();
    g_hash.insert("apple", 10);
    g_hash.insert("banana", 20);

    g_qvector = QVector<QString>();
    g_qvector << "x" << "y" << "z";
    g_qlist_ints = QList<int>();
    g_qlist_ints << 7 << 8;
    g_qlist_pairs = QList<PlainPair>();
    g_qlist_pairs << PlainPair{ 1, 2 } << PlainPair{ 3, 4 };

    // Позволяем отладчику остановиться здесь (после инициализации данных)
    qt_break_anchor();

    std::fprintf(stderr, "QT_VERSION=%s\n", QT_VERSION_STR);
    std::fflush(stderr);

    // Не даём компилятору выкинуть переменные, но и не мешаем отладке
    volatile int sink = 0;
    sink += g_string_ascii.size() + g_string_unicode.size() + g_string_emoji.size() + g_bytes.size()
            + g_stringlist.size() + g_bytes_hex.size() + g_map.size() + g_hash.size() + g_variant_int.toInt()
            + g_date.year() + g_time.hour() + g_dt.date().day() + g_size.width() + g_point.x() + g_rect.width()
            + g_line.x1() + g_url.isValid() + g_qvector.size() + g_qlist_ints.size() + g_qlist_pairs.size();
    Q_UNUSED(qtVersion)
    return (argc > 1) ? sink : 0;
}
