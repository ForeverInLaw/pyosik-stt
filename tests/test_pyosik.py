import asyncio
import importlib.util
import sys
import unittest
from concurrent.futures import CancelledError, Future
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from grpclib.const import Status
from grpclib.exceptions import GRPCError


def load_plugin():
    """Replace only the Android SDK boundary; use the real gRPC and protobuf libraries."""
    sdk = {
        "android_utils": {
            "copy_to_clipboard": Mock(),
            "run_on_ui_thread": lambda fn: fn(),
        },
        "base_plugin": {"BasePlugin": type("BasePlugin", (), {})},
        "client_utils": {
            "STAGE_QUEUE": "stageQueue",
            "get_notification_center": Mock(),
            "run_on_queue": lambda fn, queue: fn(),
            "send_request": Mock(),
        },
        "java": {"dynamic_proxy": lambda interface: object},
        "org.telegram.messenger": {
            "DialogObject": SimpleNamespace(isEncryptedDialog=Mock(return_value=False)),
            "MessageObject": Mock(
                side_effect=lambda account, raw, *args: SimpleNamespace(
                    messageOwner=raw,
                    isVoice=lambda: raw.voice,
                    isOutOwner=lambda: raw.out,
                )
            ),
            "NotificationCenter": SimpleNamespace(
                messageReceivedByServer=1, NotificationCenterDelegate=object
            ),
            "UserConfig": SimpleNamespace(MAX_ACCOUNT_COUNT=2),
        },
        "org.telegram.tgnet": {
            "TLRPC": SimpleNamespace(
                TL_messages_editMessage=lambda: SimpleNamespace(
                    flags=0, entities=Mock()
                ),
                TL_messageEntityBlockquote=lambda: SimpleNamespace(offset=0, length=0),
            )
        },
        "ui.bulletin": {"BulletinHelper": Mock()},
        "ui.settings": dict.fromkeys(("Header", "Input", "Switch", "Text"), Mock()),
    }
    modules = {}
    for name, members in sdk.items():
        module = ModuleType(name)
        module.__dict__.update(members)
        modules[name] = module
    spec = importlib.util.spec_from_file_location(
        "pyosik_under_test", Path(__file__).resolve().parents[1] / "pyosik.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


plugin = load_plugin()


class RivaTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_and_best_alternative_round_trip(self):
        request_type, response_type = plugin.riva_messages()
        response = response_type()
        first = response.results.add()
        first.alternatives.add(transcript=" Первое. ")
        first.alternatives.add(transcript="Wrong alternative")
        response.results.add().alternatives.add(transcript="Второе.")
        rpc = AsyncMock(return_value=response)
        channel = Mock()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "voice.ogg"
            path.write_bytes(b"OggS test audio")
            with (
                patch.object(plugin, "Channel", return_value=channel),
                patch.object(plugin, "UnaryUnaryMethod", return_value=rpc),
            ):
                text = await plugin.RivaClient().transcribe(
                    (str(path),), "test-key", "ru"
                )
        self.assertEqual(text, "Первое. Второе.")
        request = rpc.call_args.args[0]
        decoded = request_type.FromString(request.SerializeToString())
        self.assertEqual(decoded.audio, b"OggS test audio")
        self.assertEqual(decoded.config.language_code, "ru")
        self.assertTrue(decoded.config.enable_automatic_punctuation)
        self.assertEqual(
            rpc.call_args.kwargs["metadata"]["function-id"], plugin.FUNCTION_ID
        )
        self.assertEqual(rpc.call_args.kwargs["timeout"], 60)
        channel.close.assert_called_once()

    async def test_invalid_audio_never_reaches_network(self):
        with (
            TemporaryDirectory() as directory,
            patch.object(plugin, "Channel") as channel,
        ):
            path = Path(directory) / "voice.ogg"
            for audio, limit in ((b"", 20), (b"not audio", 20), (b"OggS too big", 5)):
                with (
                    self.subTest(audio=audio),
                    patch.object(plugin, "MAX_AUDIO_BYTES", limit),
                ):
                    path.write_bytes(audio)
                    with self.assertRaises(ValueError):
                        await plugin.RivaClient().transcribe(
                            (str(path),), "key", "multi"
                        )
            channel.assert_not_called()

    async def test_rpc_error_closes_channel_and_does_not_expose_key(self):
        error = GRPCError(Status.UNAUTHENTICATED, "secret-token-from-server")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "voice.wav"
            path.write_bytes(b"RIFF test audio")
            channel = Mock()
            with (
                patch.object(plugin, "Channel", return_value=channel),
                patch.object(
                    plugin,
                    "UnaryUnaryMethod",
                    return_value=AsyncMock(side_effect=error),
                ),
                self.assertRaises(GRPCError),
            ):
                await plugin.RivaClient().transcribe(
                    (str(path),), "secret-key", "multi"
                )
            channel.close.assert_called_once()
        message = plugin.PyosikPlugin._error_message(error)
        self.assertNotIn("secret", message)
        self.assertIn("API-ключ", message)


class PluginTests(unittest.TestCase):
    def setUp(self):
        plugin.send_request.reset_mock()
        plugin.BulletinHelper.reset_mock()
        plugin.DialogObject.isEncryptedDialog.reset_mock(return_value=True)
        plugin.DialogObject.isEncryptedDialog.return_value = False
        self.settings = {"api_key": "test-key"}
        self.instance = plugin.PyosikPlugin()
        self.instance.get_setting = lambda key, default=None: self.settings.get(
            key, default
        )
        self.instance.logger = Mock()
        self.controller = Mock(maxCaptionLength=1024)
        self.controller.getCaptionMaxLengthLimit.return_value = 1024
        self.client = Mock()
        self.client.get_messages_controller.return_value = self.controller
        self.client.get_file_loader.return_value.getPathToMessage.return_value.getAbsolutePath.return_value = "/cache/voice.ogg"
        self.instance.client = Mock(return_value=self.client)
        self.futures = []

        def submit(coroutine):
            coroutine.close()
            future = Future()
            self.futures.append(future)
            return future

        worker = Mock()
        worker.submit.side_effect = submit
        with patch.object(plugin, "AsyncWorker", return_value=worker):
            self.instance.on_plugin_load()
        self.raw = SimpleNamespace(
            voice=True,
            out=True,
            fwd_from=None,
            message="",
            ttl_period=0,
            media=SimpleNamespace(ttl_seconds=0),
            attachPath="/cache/voice.ogg",
        )
        self.args = [-1, 42, self.raw, 1234, 0, 0, False]

    def tearDown(self):
        self.instance.on_plugin_unload()

    def test_duplicate_events_trigger_one_transcription_and_correct_account_edit(self):
        self.instance.on_voice_sent(1, self.args)
        self.instance.on_voice_sent(1, self.args)
        self.assertEqual(len(self.futures), 1)
        self.futures[0].set_result("Проверка.")
        request = plugin.send_request.call_args.args[0]
        self.assertEqual(request.id, 42)
        self.assertEqual(request.message, "Проверка.")
        self.assertEqual(request.flags, 2048 | 8)
        self.assertEqual(plugin.send_request.call_args.kwargs["account"], 1)
        self.instance.client.assert_called_with(1)

    def test_caption_is_quoted_with_utf16_length(self):
        self.instance.on_voice_sent(0, self.args)
        text = "Привет 😀"
        self.futures[0].set_result(text)
        request = plugin.send_request.call_args.args[0]
        request.entities.add.assert_called_once()
        quote = request.entities.add.call_args.args[0]
        self.assertEqual(request.message, text)
        self.assertEqual(quote.offset, 0)
        self.assertEqual(quote.length, len(text.encode("utf-16-le")) // 2)

    def test_private_and_existing_content_is_not_uploaded(self):
        for field, value in (
            ("voice", False),
            ("out", False),
            ("message", "Existing caption"),
            ("fwd_from", object()),
            ("ttl_period", 10),
        ):
            original = getattr(self.raw, field)
            with self.subTest(field=field):
                setattr(self.raw, field, value)
                self.instance.on_voice_sent(0, self.args)
                self.assertEqual(self.futures, [])
                setattr(self.raw, field, original)
        self.raw.media.ttl_seconds = 10
        self.instance.on_voice_sent(0, self.args)
        self.assertEqual(self.futures, [])

    def test_secret_scheduled_and_disabled_messages_are_not_uploaded(self):
        plugin.DialogObject.isEncryptedDialog.return_value = True
        self.instance.on_voice_sent(0, self.args)
        plugin.DialogObject.isEncryptedDialog.return_value = False
        self.args[6] = True
        self.instance.on_voice_sent(0, self.args)
        self.args[6] = False
        self.settings["enabled"] = False
        self.instance.on_voice_sent(0, self.args)
        self.assertEqual(self.futures, [])

    def test_queue_is_bounded(self):
        for message_id in range(plugin.MAX_PENDING + 1):
            args = self.args.copy()
            args[1] = message_id + 1
            self.instance.on_voice_sent(0, args)
        self.assertEqual(len(self.futures), plugin.MAX_PENDING)
        plugin.BulletinHelper.show_error.assert_called_once()

    def test_missing_key_does_not_upload(self):
        self.settings["api_key"] = ""
        self.instance.on_voice_sent(0, self.args)
        self.assertEqual(self.futures, [])

    def test_old_result_after_reload_never_edits_message(self):
        self.instance.on_voice_sent(0, self.args)
        self.instance._generation = object()
        self.futures[0].set_result("Stale transcript")
        plugin.send_request.assert_not_called()

    def test_disabling_during_recognition_prevents_edit(self):
        self.instance.on_voice_sent(0, self.args)
        self.settings["enabled"] = False
        self.futures[0].set_result("Transcript")
        plugin.send_request.assert_not_called()

    def test_caption_added_during_recognition_is_preserved(self):
        self.instance.on_voice_sent(0, self.args)
        self.raw.message = "User caption"
        self.futures[0].set_result("Transcript")
        plugin.send_request.assert_not_called()
        self.assertEqual(self.instance._last_text, "Transcript")

    def test_long_transcript_is_retained_without_silent_truncation(self):
        self.instance.on_voice_sent(0, self.args)
        text = "😀" * 600
        self.futures[0].set_result(text)
        plugin.send_request.assert_not_called()
        self.assertEqual(self.instance._last_text, text)
        plugin.BulletinHelper.show_error.assert_called_once()

    def test_telegram_error_preserves_transcript_for_copying(self):
        self.instance.on_voice_sent(0, self.args)
        self.futures[0].set_result("Transcript")
        callback = plugin.send_request.call_args.args[1]
        callback(None, SimpleNamespace(text="MESSAGE_AUTHOR_REQUIRED"))
        self.controller.processUpdates.assert_not_called()
        self.assertEqual(self.instance._last_text, "Transcript")
        plugin.BulletinHelper.show_error.assert_called_once()

    def test_server_updates_are_applied_even_if_plugin_was_disabled_after_edit(self):
        self.instance.on_voice_sent(0, self.args)
        self.futures[0].set_result("Transcript")
        callback = plugin.send_request.call_args.args[1]
        self.instance._active = False
        response = object()
        callback(response, None)
        self.controller.processUpdates.assert_called_once_with(response, False)


class WorkerTests(unittest.TestCase):
    def test_unload_cancels_inflight_work(self):
        worker = plugin.AsyncWorker()

        async def wait_forever():
            await asyncio.Event().wait()

        future = worker.submit(wait_forever())
        worker.close()
        worker.thread.join(timeout=2)
        self.assertFalse(worker.thread.is_alive())
        with self.assertRaises(CancelledError):
            future.result(timeout=1)


if __name__ == "__main__":
    unittest.main()
