import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import wave

from rpg_bot.dice_audio import BYTES_PER_FRAME, DiceSoundManager, WaveSequenceAudioSource


def create_wave(path: Path, sample: int) -> None:
    frame = int(sample).to_bytes(2, "little", signed=True) * 2
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(frame * 960)


class DiceAudioTests(unittest.IsolatedAsyncioTestCase):
    def test_wave_sources_play_sequentially_as_discord_pcm_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.wav"
            second = Path(directory) / "second.wav"
            create_wave(first, 100)
            create_wave(second, 200)
            source = WaveSequenceAudioSource((first, second))

            first_frame = source.read()
            second_frame = source.read()

            self.assertEqual(len(first_frame), BYTES_PER_FRAME)
            self.assertEqual(len(second_frame), BYTES_PER_FRAME)
            self.assertEqual(
                int.from_bytes(first_frame[:2], "little", signed=True), 100
            )
            self.assertEqual(
                int.from_bytes(second_frame[:2], "little", signed=True), 200
            )
            self.assertEqual(source.read(), b"")

    async def test_prepare_joins_the_rollers_voice_channel(self) -> None:
        voice_client = Mock()
        channel = SimpleNamespace(id=7, connect=AsyncMock(return_value=voice_client))
        interaction = SimpleNamespace(
            guild=SimpleNamespace(id=3, voice_client=None),
            user=SimpleNamespace(voice=SimpleNamespace(channel=channel)),
        )

        prepared = await DiceSoundManager().prepare(interaction)

        self.assertIs(prepared, voice_client)
        channel.connect.assert_awaited_once_with(self_deaf=True)

    async def test_prepare_is_silent_when_the_roller_is_not_in_voice(self) -> None:
        interaction = SimpleNamespace(
            guild=SimpleNamespace(id=3, voice_client=None),
            user=SimpleNamespace(voice=None),
        )

        self.assertIsNone(await DiceSoundManager().prepare(interaction))

    async def test_missing_voice_dependency_does_not_break_the_roll(self) -> None:
        channel = SimpleNamespace(
            id=7,
            connect=AsyncMock(side_effect=RuntimeError("PyNaCl is missing")),
        )
        interaction = SimpleNamespace(
            guild=SimpleNamespace(id=3, voice_client=None),
            user=SimpleNamespace(voice=SimpleNamespace(channel=channel)),
        )

        self.assertIsNone(await DiceSoundManager().prepare(interaction))

    def test_special_sound_uses_kept_result_for_advantage(self) -> None:
        special = DiceSoundManager._special_result

        self.assertEqual(special(20, (1, 17), 17), None)
        self.assertEqual(special(20, (1, 20), 20), 20)
        self.assertEqual(special(20, (1, 17), 1), 1)
        self.assertEqual(special(20, (1, 20), None), 20)
        self.assertEqual(special(12, (1,), None), None)

    def test_play_result_sequences_settle_and_natural_twenty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sound_directory = Path(directory)
            create_wave(sound_directory / "spin.wav", 100)
            create_wave(sound_directory / "settle.wav", 200)
            create_wave(sound_directory / "natural_20.wav", 300)
            voice_client = Mock()
            voice_client.is_connected.return_value = True
            voice_client.is_playing.return_value = False

            played = DiceSoundManager(sound_directory).play_result(
                voice_client, 20, (7, 20), None
            )

            self.assertTrue(played)
            source = voice_client.play.call_args.args[0]
            self.assertEqual(
                int.from_bytes(source.read()[:2], "little", signed=True), 200
            )
            self.assertEqual(
                int.from_bytes(source.read()[:2], "little", signed=True), 300
            )
            self.assertEqual(source.read(), b"")

    def test_play_spin_only_uses_the_spin_sound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sound_directory = Path(directory)
            create_wave(sound_directory / "spin.wav", 100)
            voice_client = Mock()
            voice_client.is_connected.return_value = True
            voice_client.is_playing.return_value = False

            played = DiceSoundManager(sound_directory).play_spin(
                voice_client, animation_duration_seconds=1.0
            )

            self.assertTrue(played)
            source = voice_client.play.call_args.args[0]
            self.assertEqual(
                int.from_bytes(source.read()[:2], "little", signed=True), 100
            )
            self.assertEqual(source.read(), b"")

    def test_wave_source_is_capped_to_the_animation_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.wav"
            second = Path(directory) / "second.wav"
            create_wave(first, 100)
            create_wave(second, 200)

            source = WaveSequenceAudioSource(
                (first, second), max_duration_seconds=0.02
            )

            self.assertEqual(
                int.from_bytes(source.read()[:2], "little", signed=True), 100
            )
            self.assertEqual(source.read(), b"")


if __name__ == "__main__":
    unittest.main()
