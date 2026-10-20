"""Pyosik Android plugin.

The bundled RIVA_SCHEMA is derived from NVIDIA Riva protobuf definitions.
The following license applies to that descriptor:

Copyright (c) 2022 NVIDIA CORPORATION & AFFILIATES. All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import asyncio
import base64
import zlib
from collections import OrderedDict
from concurrent.futures import CancelledError
from pathlib import Path
from threading import Thread

from android_utils import copy_to_clipboard, run_on_ui_thread
from base_plugin import BasePlugin
from client_utils import (
    STAGE_QUEUE,
    get_notification_center,
    run_on_queue,
    send_request,
)
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from grpclib.client import Channel, UnaryUnaryMethod
from grpclib.const import Status
from grpclib.exceptions import GRPCError
from java import dynamic_proxy
from org.telegram.messenger import (
    DialogObject,
    MessageObject,
    NotificationCenter,
    UserConfig,
)
from org.telegram.tgnet import TLRPC
from ui.bulletin import BulletinHelper
from ui.settings import Header, Input, Switch, Text

__id__ = "pyosik"
__name__ = "Pyosik"
__description__ = "Расшифровка исходящих голосовых через NVIDIA Whisper Large v3"
__version__ = "1.0.0"
__sdk_version__ = ">=1.4.5.0"
__requirements__ = ["grpclib==0.4.9", "protobuf==7.36.2"]

FUNCTION_ID = "b702f636-f60c-4a3d-a6f4-f3568c13bd7d"
MAX_AUDIO_BYTES = 20 * 1024 * 1024
MAX_PENDING = 4

# Generated from NVIDIA's MIT-licensed Riva schemas by tools/update_schema.py.
RIVA_SCHEMA = "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"


def riva_messages():
    schema = descriptor_pb2.FileDescriptorSet.FromString(
        zlib.decompress(base64.b64decode(RIVA_SCHEMA))
    )
    pool = descriptor_pool.DescriptorPool()
    for file in schema.file:
        pool.AddSerializedFile(file.SerializeToString())
    return tuple(
        message_factory.GetMessageClass(
            pool.FindMessageTypeByName("nvidia.riva.asr." + name)
        )
        for name in ("RecognizeRequest", "RecognizeResponse")
    )


class RivaClient:
    """Use the same unary Riva API as the desktop helper, without grpcio."""

    async def transcribe(
        self, paths: tuple[str, ...], api_key: str, language: str
    ) -> str:
        for attempt in range(10):
            path = next((Path(p) for p in paths if Path(p).is_file()), None)
            if path is not None:
                break
            await asyncio.sleep(0.2)
        else:
            raise ValueError("Аудиофайл не найден в кеше Telegram.")

        with path.open("rb") as audio_file:
            audio = audio_file.read(MAX_AUDIO_BYTES + 1)
        if not audio:
            raise ValueError("Аудиофайл пуст.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("Аудиофайл больше 20 МиБ.")
        if not audio.startswith((b"OggS", b"RIFF", b"fLaC")):
            raise ValueError("Ожидался аудиофайл OGG, WAV или FLAC.")

        request_type, response_type = riva_messages()
        request = request_type(audio=audio)
        request.config.language_code = language
        request.config.max_alternatives = 1
        request.config.enable_automatic_punctuation = True
        request.config.verbatim_transcripts = False

        channel = Channel("grpc.nvcf.nvidia.com", 443, ssl=True)
        try:
            recognize = UnaryUnaryMethod(
                channel,
                "/nvidia.riva.asr.RivaSpeechRecognition/Recognize",
                request_type,
                response_type,
            )
            response = await recognize(
                request,
                timeout=60,
                metadata={
                    "function-id": FUNCTION_ID,
                    "authorization": "Bearer " + api_key,
                },
            )
        finally:
            channel.close()

        text = " ".join(
            result.alternatives[0].transcript.strip()
            for result in response.results
            if result.alternatives and result.alternatives[0].transcript.strip()
        )
        if not text:
            raise ValueError("NVIDIA не распознала речь в голосовом.")
        return text


class AsyncWorker:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = Thread(target=self._run, name="pyosik-riva", daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            tasks = list(asyncio.all_tasks(self.loop))
            for task in tasks:
                task.cancel()
            self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)


class SentListener(dynamic_proxy(NotificationCenter.NotificationCenterDelegate)):
    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin

    def didReceivedNotification(self, event_id, account, args):
        if event_id == NotificationCenter.messageReceivedByServer:
            try:
                self.plugin.on_voice_sent(account, args)
            except Exception:
                self.plugin.logger.exception("Could not inspect sent voice message")


class PyosikPlugin(BasePlugin):
    def on_plugin_load(self):
        self._active = True
        self._generation = object()
        self._seen = OrderedDict()
        self._pending = set()
        self._last_text = ""
        self._worker = AsyncWorker()
        self._recognizer = RivaClient()
        self._lock = asyncio.Lock()
        self._listener = SentListener(self)
        self._centers = [
            get_notification_center(account)
            for account in range(UserConfig.MAX_ACCOUNT_COUNT)
        ]
        for center in self._centers:
            center.addObserver(
                self._listener, NotificationCenter.messageReceivedByServer
            )
        self.logger.info("Listening for new outgoing voice messages")

    def on_plugin_unload(self):
        self._active = False
        for center in self._centers:
            center.removeObserver(
                self._listener, NotificationCenter.messageReceivedByServer
            )
        self._worker.close()
        self._last_text = ""

    def create_settings(self):
        return [
            Header(text="Pyosik"),
            Switch(
                key="enabled", text="Расшифровывать исходящие голосовые", default=True
            ),
            Input(
                key="api_key",
                text="NVIDIA API-ключ",
                default="",
                icon="msg_permissions",
            ),
            Input(
                key="language",
                text="Язык",
                default="multi",
                subtext="multi — автоматически, ru — русский, en — английский",
            ),
            Text(
                text="Скопировать последнюю расшифровку",
                subtext="Если текст не поместился в подпись или редактирование не удалось",
                icon="msg_copy",
                on_click=lambda view: self._copy_last_text(),
            ),
            Text(
                text="Распознавание в облаке NVIDIA",
                subtext="Аудио исходящих голосовых передаётся NVIDIA. Готовые подписи, "
                "пересланные, исчезающие сообщения и секретные чаты пропускаются.",
            ),
        ]

    def _copy_last_text(self):
        if self._last_text:
            copy_to_clipboard(self._last_text)
            BulletinHelper.show_copied_to_clipboard()
        else:
            BulletinHelper.show_info("Расшифровок пока нет.")

    def on_voice_sent(self, account, args):
        if not self._active or not self.get_setting("enabled", True) or len(args) < 4:
            return
        raw = args[2]
        if raw is None or int(args[1]) <= 0 or (len(args) > 6 and bool(args[6])):
            return
        dialog_id = int(args[3])
        if DialogObject.isEncryptedDialog(dialog_id):
            return
        message = MessageObject(account, raw, False, False)
        if (
            not message.isVoice()
            or not message.isOutOwner()
            or raw.fwd_from is not None
            or str(raw.message or "").strip()
            or raw.ttl_period > 0
            or (raw.media is not None and raw.media.ttl_seconds > 0)
        ):
            return

        key = (account, dialog_id, int(args[1]))
        if key in self._seen:
            return
        self._seen[key] = None
        if len(self._seen) > 512:
            self._seen.popitem(last=False)

        api_key = str(self.get_setting("api_key", "")).strip()
        language = str(self.get_setting("language", "multi")).strip() or "multi"
        if not api_key:
            BulletinHelper.show_error(
                "Pyosik: укажи NVIDIA API-ключ в настройках плагина."
            )
            return
        if len(self._pending) >= MAX_PENDING:
            BulletinHelper.show_error(
                "Pyosik: очередь заполнена, дождись готовых расшифровок."
            )
            return

        paths = tuple(
            dict.fromkeys(
                filter(
                    None,
                    (
                        str(raw.attachPath or ""),
                        str(
                            self.client(account)
                            .get_file_loader()
                            .getPathToMessage(raw)
                            .getAbsolutePath()
                        ),
                    ),
                )
            )
        )
        self._pending.add(key)
        generation = self._generation
        future = self._worker.submit(self._transcribe(paths, api_key, language))
        future.add_done_callback(
            lambda result: run_on_ui_thread(
                lambda: self._transcription_done(key, message, result, generation)
            )
        )
        self.logger.info(
            "Queued voice transcription, account=%d message=%d", account, key[2]
        )

    async def _transcribe(self, paths, api_key, language):
        async with self._lock:
            if not self._active or not self.get_setting("enabled", True):
                raise asyncio.CancelledError
            return await self._recognizer.transcribe(paths, api_key, language)

    def _transcription_done(self, key, message, future, generation):
        if not self._active or generation is not self._generation:
            return
        self._pending.discard(key)
        if not self.get_setting("enabled", True):
            return
        try:
            text = future.result()
        except CancelledError:
            return
        except (GRPCError, TimeoutError, ValueError, OSError) as error:
            self.logger.warning("Transcription failed: %s", type(error).__name__)
            BulletinHelper.show_error("Pyosik: " + self._error_message(error))
            return
        except Exception:
            self.logger.exception("Unexpected transcription failure")
            BulletinHelper.show_error(
                "Pyosik: ошибка распознавания, смотри журнал плагина."
            )
            return

        self._last_text = text
        if str(message.messageOwner.message or "").strip():
            return
        account, dialog_id, message_id = key
        client = self.client(account)
        controller = client.get_messages_controller()
        caption_length = len(text.encode("utf-16-le")) // 2
        if caption_length > controller.getCaptionMaxLengthLimit():
            BulletinHelper.show_error(
                "Pyosik: текст длиннее лимита подписи. Скопируй его в настройках."
            )
            return

        request = TLRPC.TL_messages_editMessage()
        request.peer = controller.getInputPeer(dialog_id)
        request.id = message_id
        request.message = text
        quote = TLRPC.TL_messageEntityBlockquote()
        quote.offset = 0
        quote.length = caption_length
        request.entities.add(quote)
        request.flags |= 2048 | 8

        def on_edited(response, error):
            if error is not None:
                if not self._active or generation is not self._generation:
                    return
                self.logger.warning("Caption edit failed: %s", error.text)
                run_on_ui_thread(
                    lambda: BulletinHelper.show_error(
                        "Pyosik: Telegram отклонил подпись. Текст можно скопировать в настройках."
                    )
                )
                return
            run_on_queue(
                lambda: controller.processUpdates(response, False), STAGE_QUEUE
            )
            if self._active and generation is self._generation:
                self.logger.info(
                    "Caption updated, account=%d message=%d", account, message_id
                )

        send_request(request, on_edited, account=account)

    @staticmethod
    def _error_message(error):
        if isinstance(error, GRPCError):
            if error.status in (Status.UNAUTHENTICATED, Status.PERMISSION_DENIED):
                return (
                    "NVIDIA отклонила API-ключ. Проверь ключ и доступ к модели Whisper."
                )
            if error.status == Status.RESOURCE_EXHAUSTED:
                return "Достигнут лимит NVIDIA. Повтори позже."
            return "Ошибка NVIDIA: " + error.status.name
        if isinstance(error, TimeoutError):
            return "NVIDIA не ответила за 60 секунд."
        if isinstance(error, ValueError):
            return str(error)
        if isinstance(error, OSError):
            return "Не удалось прочитать аудио или подключиться к NVIDIA."
        return "Распознавание не удалось. Подробности в журнале плагина."
