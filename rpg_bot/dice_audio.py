"""Optional voice-channel sound effects for visual dice rolls."""

import asyncio
import logging
from pathlib import Path
import wave

import discord


LOGGER = logging.getLogger(__name__)

SAMPLES_PER_FRAME = 960
BYTES_PER_FRAME = SAMPLES_PER_FRAME * 2 * 2
SYNC_MARGIN_SECONDS = 0.2
DEFAULT_DICE_SOUND_DIRECTORY = (
    Path(__file__).resolve().parent.parent / "assets" / "audio" / "dice"
)


class WaveSequenceAudioSource(discord.AudioSource):
    """Stream compatible PCM WAV files one after another."""

    def __init__(
        self,
        paths: tuple[Path, ...],
        max_duration_seconds: float | None = None,
    ) -> None:
        chunks: list[bytes] = []
        for path in paths:
            with wave.open(str(path), "rb") as source:
                if (
                    source.getnchannels() != 2
                    or source.getsampwidth() != 2
                    or source.getframerate() != 48_000
                    or source.getcomptype() != "NONE"
                ):
                    raise ValueError(
                        f"Dice sound must be 48 kHz, stereo, 16-bit PCM: {path}"
                    )
                chunks.append(source.readframes(source.getnframes()))

        self._audio = b"".join(chunks)
        if max_duration_seconds is not None:
            pcm_frames = max(0, int(max_duration_seconds * 48_000))
            discord_frames = pcm_frames // SAMPLES_PER_FRAME
            self._audio = self._audio[: discord_frames * BYTES_PER_FRAME]
        self._offset = 0

    def read(self) -> bytes:
        data = self._audio[self._offset : self._offset + BYTES_PER_FRAME]
        self._offset += len(data)
        return data.ljust(BYTES_PER_FRAME, b"\0") if data else b""

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        self._audio = b""
        self._offset = 0


class DiceSoundManager:
    """Connect to a roller's voice channel and play synchronized dice sounds."""

    def __init__(self, sound_directory: Path = DEFAULT_DICE_SOUND_DIRECTORY) -> None:
        self.sound_directory = sound_directory
        self._connection_locks: dict[int, asyncio.Lock] = {}
        self._warned_missing_assets = False

    async def prepare(
        self, interaction: discord.Interaction
    ) -> discord.VoiceClient | None:
        guild = getattr(interaction, "guild", None)
        voice_state = getattr(interaction.user, "voice", None)
        channel = getattr(voice_state, "channel", None)
        if guild is None or channel is None:
            return None

        lock = self._connection_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            current = guild.voice_client
            if current is not None:
                if current.is_connected() and current.channel.id == channel.id:
                    return current
                return None
            try:
                return await channel.connect(self_deaf=True)
            except RuntimeError as error:
                LOGGER.warning("Dice voice support is unavailable: %s", error)
                return None
            except (asyncio.TimeoutError, discord.DiscordException, OSError):
                LOGGER.warning(
                    "Could not join voice channel %s for dice audio",
                    getattr(channel, "id", "unknown"),
                    exc_info=True,
                )
                return None

    def play_spin(
        self,
        voice_client: discord.VoiceClient | None,
        animation_duration_seconds: float | None = None,
    ) -> bool:
        max_duration = (
            max(0.0, animation_duration_seconds - SYNC_MARGIN_SECONDS)
            if animation_duration_seconds is not None
            else None
        )
        return self._play_paths(
            voice_client,
            (self.sound_directory / "spin.wav",),
            max_duration,
        )

    def play_result(
        self,
        voice_client: discord.VoiceClient | None,
        sides: int,
        results: tuple[int, ...],
        kept_result: int | None,
    ) -> bool:
        paths = [self.sound_directory / "settle.wav"]
        special_result = self._special_result(sides, results, kept_result)
        if special_result is not None:
            paths.append(self.sound_directory / f"natural_{special_result}.wav")
        return self._play_paths(voice_client, tuple(paths), replace=True)

    def _play_paths(
        self,
        voice_client: discord.VoiceClient | None,
        paths: tuple[Path, ...],
        max_duration_seconds: float | None = None,
        replace: bool = False,
    ) -> bool:
        if voice_client is None or not voice_client.is_connected():
            return False
        if voice_client.is_playing():
            if not replace:
                LOGGER.info("Skipping dice audio because another roll sound is playing")
                return False
            voice_client.stop()
        if any(not path.is_file() for path in paths):
            if not self._warned_missing_assets:
                LOGGER.warning(
                    "Dice audio assets are missing from %s", self.sound_directory
                )
                self._warned_missing_assets = True
            return False

        source: WaveSequenceAudioSource | None = None
        try:
            source = WaveSequenceAudioSource(paths, max_duration_seconds)
            voice_client.play(source, after=self._after_playback)
            return True
        except (discord.DiscordException, OSError, ValueError):
            if source is not None:
                source.cleanup()
            LOGGER.warning("Could not play dice audio", exc_info=True)
            return False

    @staticmethod
    def _special_result(
        sides: int,
        results: tuple[int, ...],
        kept_result: int | None,
    ) -> int | None:
        if sides != 20:
            return None
        if kept_result is not None:
            return kept_result if kept_result in (1, 20) else None
        if 20 in results:
            return 20
        return 1 if 1 in results else None

    @staticmethod
    def _after_playback(error: Exception | None) -> None:
        if error is not None:
            LOGGER.warning("Dice audio playback failed: %s", error)
