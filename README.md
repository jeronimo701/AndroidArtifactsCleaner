# Android Artifacts Cleaner

Приватный репозиторий Jeronimo701. Доступ — владельцу и приглашённым пользователям. Исходники, иконки и существующий EXE перенесены вместе с историей прежнего Gist. Его первоначальные файлы сохранены без изменений в legacy-gist/; старые адреса Gist больше не используются.

[Скачать готовый EXE](https://github.com/jeronimo701/AndroidArtifactsCleaner/releases/tag/snapshot-2026-10-22). Это существующая Windows onefile-сборка, не APK. Встроенный код сопоставлен с android_artifacts_cleaner.py; EXE не пересобирался. Собственная версия автором не задана; тег обозначает дату снимка публикации.

Программа ищет Android-артефакты на выбранных дисках и удаляет отмеченные элементы после подтверждения. Исходник — android_artifacts_cleaner.py, рецепт PyInstaller — AndroidArtifactsCleaner.spec, генератор иконок — generate_android_cleaner_icon.py. Для запуска исходника нужны Windows, Python и PySide6; для генератора — Pillow; для сборки — PyInstaller.

```
python -m PyInstaller AndroidArtifactsCleaner.spec
```

Синтаксис и поиск секретов проверены. При публикации очистка и сканирование реальных дисков не запускались. Исходные контрольные суммы и сведения о публикации находятся в legacy-gist/. Собственные условия — LICENSE.txt / LICENSE-SCOPE.md; библиотеки не перелицензируются, notices сохранены отдельно.
