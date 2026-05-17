# VK Autoposter

Автопостинг текста, изображений и видео в сообщество ВКонтакте через пользовательский токен, полученный через `vkhost.github.io` / `Kate Mobile`.

## Настройка

1. Установите Python 3.10 или новее.
2. Откройте папку проекта:

```powershell
C:\Users\Ali PC\CascadeProjects\vk-autoposter
```

3. Установите зависимости:

```powershell
python -m pip install -r requirements.txt
```

4. Скопируйте `.env.example` в `.env`:

```powershell
Copy-Item .env.example .env
```

5. Откройте `.env` и укажите значения:

```env
VK_USER_TOKEN=vk1.a.your_real_token_here
VK_GROUP_ID=-123456789
TELEGRAM_BOT_TOKEN=1234567890:your_bot_token_here
TELEGRAM_CHAT_ID=@your_channel_username
OK_ACCESS_TOKEN=your_ok_access_token_here
OK_APPLICATION_KEY=your_ok_public_application_key_here
OK_APPLICATION_SECRET_KEY=your_ok_secret_application_key_here
OK_GROUP_ID=your_ok_group_id_here
YOUTUBE_CLIENT_SECRETS_FILE=client_secret.json
YOUTUBE_TOKEN_FILE=youtube_token.json
YOUTUBE_PRIVACY_STATUS=public
```

## Как узнать ID сообщества

ID нужно указывать с минусом.

Пример:

```env
VK_GROUP_ID=-123456789
```

Если у вас есть только короткий адрес сообщества, например `https://vk.com/my_group`, можно узнать ID через любой сервис определения ID ВК или через методы VK API.

## Публикация только текста

```powershell
python autopost.py --message "Текст поста"
```

## Публикация текста с картинкой

```powershell
python autopost.py --message "Текст поста" --image "C:\path\to\image.jpg"
```

## Несколько картинок

```powershell
python autopost.py --message "Текст поста" --image "C:\path\to\image1.jpg" --image "C:\path\to\image2.jpg"
```

## Публикация короткого видео

```powershell
python autopost.py --message "Текст поста" --video "C:\path\to\video.mp4"
```

## Публикация короткого видео с названием

```powershell
python autopost.py --message "Текст поста" --video "C:\path\to\video.mp4" --video-title "Название видео"
```

## Несколько видео

```powershell
python autopost.py --message "Текст поста" --video "C:\path\to\video1.mp4" --video "C:\path\to\video2.mp4"
```

## Автопубликация новых видео из папки

Положите новые видео в папку:

```powershell
videos\new
```

Запустите:

```powershell
python autopost.py --video-folder "videos\new"
```

В этом режиме текст поста и название видео берутся из имени файла и сокращаются до 7 символов.

Если нужен одинаковый текст для всех видео:

```powershell
python autopost.py --video-folder "videos\new" --message "Новый ролик"
```

Чтобы перед публикацией применить бесплатный локальный мультяшный эффект с усиленной резкостью:

```powershell
python autopost.py --video-folder "videos\new" --effect cartoon
```

Более мягкий и красивый OpenCV-стиль без грубых чёрных контуров:

```powershell
python autopost.py --video-folder "videos\new" --effect stylization
```

Мягкая уникализация без водяного знака и без сильного изменения внешнего вида:

```powershell
python autopost.py --video-folder "videos\new" --effect unique
```

Обработанные видео сохраняются в:

```powershell
videos\processed
```

После успешной публикации файл переносится в:

```powershell
videos\posted
```

Если в `.env` заполнены ключи Одноклассников, видео также будет отправлено в группу ОК.

Если рядом со скриптом есть файл `client_secret.json`, видео также будет загружено на YouTube.

Для YouTube нужно:

- создать проект в Google Cloud;
- включить YouTube Data API v3;
- создать OAuth Client ID типа Desktop app;
- скачать файл OAuth и положить его рядом со скриптом как `client_secret.json`;
- при первом запуске открыть ссылку авторизации и разрешить загрузку видео.

Для Одноклассников нужны:

- `OK_ACCESS_TOKEN`
- `OK_APPLICATION_KEY`
- `OK_APPLICATION_SECRET_KEY`
- `OK_GROUP_ID`

У приложения ОК должны быть права:

- `VIDEO_CONTENT`
- `GROUP_CONTENT`
- `VALUABLE_ACCESS`

## Ссылка на сайт и хештеги

К каждому посту автоматически добавляется ссылка:

```text
👇 Переходите на сайт 👇
https://masterhacks.ru/
```

Также к каждому посту автоматически добавляются 5 случайных хештегов из файла:

```text
hashtags.txt
```

Можно редактировать этот файл и добавлять свои хештеги, каждый хештег должен быть на отдельной строке.

## Важно

- Используйте именно пользовательский токен администратора сообщества, не токен сообщества.
- Пользователь должен быть администратором или иметь права публикации в сообществе.
- Не публикуйте свой токен в GitHub, Telegram или открытых чатах.
- Если VK вернет `User authorization failed`, получите новый токен.
- Если VK вернет `Access denied`, проверьте права пользователя в сообществе и корректность `VK_GROUP_ID`.
- Для видео используется метод `video.save`, поэтому токен должен иметь доступ к загрузке видео.
- VK может обрабатывать видео не мгновенно: пост может появиться, а видео стать доступным через некоторое время.
