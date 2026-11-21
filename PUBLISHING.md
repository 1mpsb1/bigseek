# Публикация на GitHub

Папка проекта уже готова к загрузке: исходники, установщик, CI и документация на месте.
Ниже — порядок действий.

## 0. Что куда попадает

| Путь | В git | Зачем |
|---|---|---|
| `app/`, `main.py`, `assets/` | да | исходный код |
| `installer/`, `scripts/`, `*.bat` | да | сборка exe и установщика |
| `.github/workflows/build.yml` | да | автоматическая сборка релизов |
| `dist/`, `build/` | нет | локальная сборка (~516 МБ) |
| `release/` | нет | готовые установщики для раздачи |
| `data/`, `portable.flag` | нет | рабочие данные |

GitHub не принимает файлы больше 100 МБ, а папка `dist` весит около 500 МБ — поэтому
её и `release` нельзя коммитить. Установщик и портативный ZIP прикладываются к
**Releases**, а не к репозиторию. Всё это уже прописано в `.gitignore`.

## 1. Создать репозиторий

На GitHub: **New repository** → имя, например `BigSeek-Desktop` → **Public** →
**не** добавляйте README, .gitignore и лицензию (они уже есть) → **Create repository**.

## 2. Залить файлы

### Вариант А — GitHub Desktop (без командной строки)

1. Установите [GitHub Desktop](https://desktop.github.com/).
2. **File → Add local repository** → выберите папку `BigSeek-Desktop`.
3. Если он предложит создать репозиторий — согласитесь (ветка `main`).
4. Нажмите **Publish repository**, снимите галочку «Keep this code private», если нужен
   публичный репозиторий.

### Вариант Б — git в командной строке

```bat
cd C:\Users\vitaliy\Documents\Default Project\BigSeek-Desktop
git init
git add .
git commit -m "BigSeek Desktop 1.2.0"
git branch -M main
git remote add origin https://github.com/ВАШ_ЛОГИН/BigSeek-Desktop.git
git push -u origin main
```

Проверка перед первым коммитом:

```bat
git status
```

В списке не должно быть `dist`, `build`, `release`, `data`, `__pycache__`.

## 3. Выложить готовый релиз 1.2.0

Соберите файлы (если ещё не собраны):

```bat
release.bat
```

В папке `release` появятся:

- `BigSeek-Desktop-1.2.0-setup.exe`
- `BigSeek-Desktop-1.2.0-portable.zip`
- `SHA256SUMS.txt`

На GitHub: **Releases → Draft a new release** →

1. **Choose a tag** → впишите `v1.2.0` → **Create new tag on publish**.
2. Заголовок: `BigSeek Desktop 1.2.0`.
3. Прикрепите три файла из `release` (перетащите в поле «Attach binaries»).
4. Опубликуйте.

Ссылки вида `https://github.com/ВАШ_ЛОГИН/BigSeek-Desktop/releases/latest` после этого
можно вставлять в README и раздавать пользователям.

## 4. Автоматическая сборка

Workflow `.github/workflows/build.yml` уже настроен:

- при каждом push и pull request собирает exe, ZIP и установщик — файлы лежат в
  **Actions → build → Artifacts**;
- при push тега `v*` дополнительно создаёт GitHub Release и прикладывает те же файлы.

То есть в следующий раз достаточно:

```bat
git tag v1.2.0
git push origin v1.2.0
```

Версию в `version.txt` желательно обновить заранее (тег её переопределяет, но так
номер будет одинаковым везде).

## 5. Мелочи, которые стоит поправить

- В `CHANGELOG.md` ссылка `https://github.com/OWNER/REPO/...` — замените `OWNER/REPO`
  на свой репозиторий.
- В `LICENSE` при желании укажите своё имя вместо «BigSeek Desktop contributors».
  Лицензия MIT разрешает использовать, изменять и распространять проект; если нужна
  другая — замените файл.
- Скриншоты лежат в `docs/`; после правок интерфейса их стоит обновить.
- Установщик не подписан. Если планируете широкую раздачу, получите сертификат
  code signing и подпишите `dist\...\BigSeek Desktop.exe` и `release\...-setup.exe`
  (`signtool sign /fd SHA256 ...`) — SmartScreen перестанет предупреждать.
