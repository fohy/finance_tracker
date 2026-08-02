# GitHub и развёртывание

## GitHub — дом для кода

GitHub Pages подходит только для статичных сайтов. FinFlow — Flask-приложение с
сервером и персональной SQLite-базой, поэтому Pages использовать нельзя: он не
сохранит операции и не выполнит API.

Создайте **приватный** репозиторий на GitHub (финансовый код и конфигурация не
должны быть публичными), затем из папки проекта выполните:

```bash
git init
git add .
git commit -m "Initial FinFlow"
git branch -M main
git remote add origin https://github.com/<ваш-логин>/finflow.git
git push -u origin main
```

`.gitignore` уже исключает базу, `.env` и виртуальное окружение. После первого
push GitHub Actions автоматически проверит линтер и тесты.

## Запуск на своём компьютере

Самый простой способ — Docker Desktop. После его установки:

```bash
docker compose up --build
```

Откройте http://127.0.0.1:5050. При следующих запусках достаточно
`docker compose up -d`; остановка — `docker compose down`. Данные остаются в
`instance/finance.db` на компьютере, а не внутри удаляемого контейнера.

Перед доступом к приложению из локальной сети создайте `.env` из `.env.example`
и замените `SECRET_KEY` длинной случайной строкой. В compose по умолчанию порт
привязан только к этому компьютеру — это безопаснее для семейных данных.

## Два закрытых аккаунта

После первого запуска создайте пользователей на машине, где хранится база:

```bash
docker compose run --rm finflow flask --app app create-user --login sasha --person Саша --admin
docker compose run --rm finflow flask --app app create-user --login nastya --person Настя
```

Команда спросит пароль в терминале и не выводит его на экран. Веб-регистрации нет.
После этого все страницы и API требуют входа; изменения API дополнительно защищены
CSRF-токеном. Для HTTPS установите `SESSION_COOKIE_SECURE=1` в `.env`.

## PythonAnywhere: публичный сайт и приватная SQLite

GitHub хранит только код. База создаётся в домашнем каталоге PythonAnywhere и не
попадает ни в репозиторий, ни в static-файлы сайта.

### 1. Установка

Откройте Bash console в PythonAnywhere и выполните:

```bash
git clone https://github.com/fohy/finance_tracker.git ~/finance_tracker
cd ~/finance_tracker
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p ~/.config/finflow instance backups
python3.12 -c 'import secrets; print(secrets.token_urlsafe(64))' > ~/.config/finflow/secret_key
chmod 600 ~/.config/finflow/secret_key
```

Для приватного GitHub-репозитория используйте GitHub Personal Access Token или
deploy key при клонировании. Пароль от почты или GitHub в команды не вставляйте.

### 2. Web App

На вкладке **Web** создайте Manual configuration для Python 3.12 и укажите:

```text
Source code:        /home/<username>/finance_tracker
Working directory: /home/<username>/finance_tracker
Virtualenv:         /home/<username>/finance_tracker/.venv
```

Откройте WSGI configuration file и замените содержимое кодом из
`deploy/pythonanywhere_wsgi.py`. Затем нажмите **Reload**. В production приложение
не запустится с тестовым `SECRET_KEY`, cookie автоматически будут Secure.

### 3. Первый закрытый пользователь

В Bash console выполните:

```bash
cd ~/finance_tracker
.venv/bin/flask --app app create-user --login sasha --person Саша --admin
```

Пароль вводится интерактивно и не сохраняется в shell history. Публичной
регистрации нет.

### 4. Резервные копии

В Tasks добавьте ежедневную команду:

```bash
/home/<username>/finance_tracker/.venv/bin/python /home/<username>/finance_tracker/scripts/backup_db.py
```

Хранятся последние 14 копий в приватном `~/finance_tracker/backups`. Папка также
исключена из Git.

### 5. Обновление

На бесплатном PythonAnywhere выполните одну команду в Bash console:

```bash
~/finance_tracker/scripts/update_pythonanywhere.sh
```

Скрипт сначала создаёт backup, затем обновляет код и зависимости. Если на странице
**Account → API Token** уже создан токен и новая Bash console видит `$API_TOKEN`,
скрипт сам перезагрузит Web App. Иначе останется нажать **Reload** на вкладке Web.
Миграции additive и применяются при старте.

### 6. Push-уведомления PWA

Один раз создайте приватные VAPID-ключи (они сохраняются вне Git с правами `600`):

```bash
cd ~/finance_tracker
.venv/bin/flask --app app generate-vapid-keys --subject mailto:your-email@example.com
```

Перезагрузите Web App. Затем добавьте в **Tasks** ежедневную команду:

```bash
cd /home/<username>/finance_tracker && .venv/bin/flask --app app send-push-notifications
```

После этого включите уведомления в настройках установленного PWA. Сервер отправляет
одно уведомление о достигнутом лимите категории и напоминания о наступивших регулярных операциях.

## Автоматический CI/CD после push

Workflow `.github/workflows/deploy-pythonanywhere.yml` запускается только после
успешных тестов ветки `main`. Он делает приватную резервную копию базы, переносит
код через SSH, устанавливает зависимости и перезагружает Web App через API.

По умолчанию workflow выключен. Он не создаёт красных failed jobs на бесплатном
аккаунте. Для платного аккаунта добавьте repository variable
`ENABLE_PYTHONANYWHERE_DEPLOY=true`, затем secrets ниже.

SSH на PythonAnywhere доступен только платным аккаунтам. Один раз выполните:

1. На своём компьютере создайте отдельный deploy key:

   ```bash
   ssh-keygen -t ed25519 -C finflow-deploy -f finflow_pythonanywhere
   ```

2. Добавьте содержимое `finflow_pythonanywhere.pub` в
   `~/.ssh/authorized_keys` на PythonAnywhere.
3. В GitHub откройте **Settings → Secrets and variables → Actions** и добавьте:

   | Secret | Значение |
   |---|---|
   | `PA_USERNAME` | username PythonAnywhere, не email |
   | `PA_DOMAIN` | `username.pythonanywhere.com` |
   | `PA_API_TOKEN` | токен со вкладки PythonAnywhere **Account → API Token** |
   | `PA_SSH_PRIVATE_KEY` | полное содержимое файла `finflow_pythonanywhere` |

Для EU-аккаунта дополнительно задайте `PA_SSH_HOST=ssh.eu.pythonanywhere.com` и
`PA_API_BASE=https://eu.pythonanywhere.com`. Для обычного US-аккаунта эти два
необязательных secret не нужны.

После этого каждый `push` в `main` автоматически проходит тесты и выкатывается.
`instance/`, `.env`, `backups/` и `.venv/` явно исключены из `rsync --delete`,
поэтому production-база никогда не отправляется в GitHub и не удаляется deploy'ем.
