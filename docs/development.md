# Разработка Pyosik

## Устройство

`pyosik.py` содержит плагин и gRPC-клиент NVIDIA Riva.
Плагин подписывается на `NotificationCenter.messageReceivedByServer`
для каждого аккаунта. После подтверждения отправки он читает локальный
аудиофайл и ставит распознавание в фоновую очередь.

События дедуплицируются по аккаунту, диалогу и серверному ID сообщения.
Распознавание использует отдельный поток с asyncio. При отключении плагина
подписки снимаются, незавершённые задачи отменяются.

Подпись добавляется через `TL_messages_editMessage` с явным аккаунтом.
Цитату задаёт `TL_messageEntityBlockquote`; её длина считается в UTF-16.
Успешные обновления Telegram обрабатываются на `stageQueue`.

Доступ к NVIDIA работает через `grpclib` и `protobuf` на чистом Python.
`grpcio` и нативные Python-расширения на телефоне не используются.
API-ключ берётся из настроек SDK.

## Локальные проверки

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\ruff.exe check pyosik.py tools tests
.venv\Scripts\ruff.exe format --check pyosik.py tools tests
```

В Linux и macOS замени `.venv\Scripts\python.exe` на `.venv/bin/python`,
а `.venv\Scripts\ruff.exe` на `.venv/bin/ruff`.

`tests/test_pyosik.py` подменяет Android SDK на границе интеграции,
сохраняя настоящие `grpclib` и `protobuf`.

## Работа с телефоном

Включи Dev Server и подключи телефон через ADB:

```shell
adb devices
adb forward tcp:42690 tcp:42690
python tools/dev.py ping
python tools/dev.py install
```

| Команда | Назначение |
| :--- | :--- |
| `python tools/dev.py list` | Состояние установленных плагинов |
| `python tools/dev.py install` | Установка текущего файла и включение Pyosik |
| `python tools/dev.py enable` | Включение установленного Pyosik |
| `python tools/dev.py disable` | Отключение Pyosik |

Журнал плагина:

```shell
adb logcat -s plugin.pyosik
```

Для проверки отправь голосовое в "Избранное". В журнале должны появиться
`Queued voice transcription` и `Caption updated` для одного сообщения.
Проверь, что подпись появилась в виде цитаты.

## Файл релиза

В GitHub Releases публикуется один файл `pyosik.plugin` с содержимым
`pyosik.py` из коммита релиза. Клиент читает его как Python-плагин,
устанавливает зависимости из `__requirements__` и загружает иконку из Telegram.

При открытии файла установщик проверяет метаданные и показывает зависимости.
Для установки файла из GitHub в настройках «Система плагинов» должны быть
разрешены «Неизвестные источники».

## GitHub Actions

Workflow [CI and release](https://github.com/ForeverInLaw/pyosik-stt/actions/workflows/ci.yml)
запускается для `main`, pull request и тегов `v*`. Он проверяет код Ruff,
запускает тесты на Python 3.11 и сохраняет `pyosik.plugin` в артефактах запуска.
Кнопка **Run workflow** запускает эти же проверки и упаковку.

При пуше тега workflow также публикует GitHub Release с файлом `pyosik.plugin`
и автоматически составленным списком изменений. Тег должен совпадать
с `__version__` в `pyosik.py`: для версии `1.0.3` нужен тег `v1.0.3`.

Для выпуска версии обнови `__version__`, закоммить изменение и отправь тег:

```shell
git push origin main
git tag v1.0.3
git push origin v1.0.3
```

Публикация выполняется после успешных проверок. Она использует штатный
`GITHUB_TOKEN` с правом `contents: write` только в отдельной задаче релиза.

## Иконка плагина

Метаданные `__icon__ = "PyosikSTT/0"` указывают на первый стикер
в [паке Pyosik STT](https://t.me/addstickers/PyosikSTT).
SDK принимает ссылку на стикер, а не путь к PNG или URL изображения.
На проверенной сборке AyuGram индексы стикеров начинаются с нуля.
Исходник сохранён в `docs/pyosik-mascot.png`, версия для Telegram
размером 512×512 с прозрачным фоном находится в `docs/pyosik-icon.webp`.

## Генерация схемы Riva

Схема встроена в `pyosik.py` как сжатый protobuf-дескриптор.
Генератор скачивает официальные исходники NVIDIA, закреплённые на ревизии
`268890b7286031a6d4950e34f7ce13ed0d4ce621`, и использует `grpcio-tools`
только на компьютере:

```powershell
.venv\Scripts\python.exe tools/update_schema.py
```

Лицензия NVIDIA на встроенный дескриптор включена в `pyosik.py`.
Используется endpoint `grpc.nvcf.nvidia.com:443` и функция Whisper Large v3
`b702f636-f60c-4a3d-a6f4-f3568c13bd7d`, как в исходном Windows-помощнике.

## Особенности проверенного SDK

На AyuGram с SDK 1.4.5.7 прямое наследование от SDK-класса
`NotificationCenterDelegate` вызывает ошибку
`dynamic_proxy must be used first in class bases`. Плагин использует
`dynamic_proxy(NotificationCenter.NotificationCenterDelegate)`.

Java `ArrayList` в этой сборке не поддерживает Python-итерацию.
Для Java-списков используй `size()` и `get(index)`.

## Источники

- [Уведомления, запросы и очереди](https://plugins.exteragram.app/docs/client-utils)
- [Метаданные плагина и поле автора](https://plugins.exteragram.app/docs/plugin-class)
- [Протокол Dev Server](https://plugins.exteragram.app/docs/dev-server)
- [NVIDIA Whisper Large v3 API](https://build.nvidia.com/openai/whisper-large-v3/api)
- [Закреплённая версия Riva protobuf](https://github.com/nvidia-riva/common/tree/268890b7286031a6d4950e34f7ce13ed0d4ce621/riva/proto)
