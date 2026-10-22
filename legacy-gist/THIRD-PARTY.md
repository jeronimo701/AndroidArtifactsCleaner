# Сторонние компоненты

Готовый EXE перенесён без изменений. Встроенные Qt/PySide6 и Shiboken имеют версию 6.8.2.1, определённую по архиву EXE. Приложение использует Python и PyInstaller; Pillow используется отдельным генератором иконки.

Тексты лицензий сохранены в THIRD-PARTY-*.txt. Эти тексты не означают перелицензирования зависимостей лицензией автора приложения.

Исходники и условия Qt/PySide: https://doc.qt.io/qtforpython-6/licenses.html ; https://download.qt.io/archive/qt/6.8/6.8.2/submodules/ ; https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.8.2.1 . При желании клиент можно пересобрать с заменёнными динамическими библиотеками, используя опубликованные .py и .spec. Содержимое onefile можно исследовать через https://pyinstaller.org/en/stable/advanced-topics.html#using-pyi-archive-viewer . Модификация Qt/PySide не заявлена.

Python: https://github.com/python/cpython ; PyInstaller: https://github.com/pyinstaller/pyinstaller ; Pillow: https://github.com/python-pillow/Pillow . Тексты общих лицензий скопированы из набора notices, уже подготовленного при публикации MultiToolHub, с сохранением оригинального текста. Они не являются lock-файлом старой сборки.
