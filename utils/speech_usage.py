import time
import tiktoken

DEFAULT_SAMPLE_RATE = 16000


class SpeechToTextUsage:
    """
    Billing truth  -> audio_seconds
    Analytics only -> transcript tokens
    """

    def __init__(self, model: str | None = None):
        self.model = model
        self.total_audio_seconds = 0.0
        self.total_transcript_tokens = 0
        self.segments = []
        self.session_start_time = None

        try:
            self.encoding = tiktoken.encoding_for_model(model) if model else tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.encoding = tiktoken.get_encoding("cl100k_base")

    # ---------------- SESSION ---------------- #

    def start_session(self):
        self.session_start_time = time.time()

    # ---------------- AUDIO ---------------- #

    def _count_audio_seconds(
        self,
        audio_bytes: bytes,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = 1,
        sample_width: int = 2,  # PCM16
    ) -> float:
        samples = len(audio_bytes) / (sample_width * channels)
        return samples / sample_rate

    def add_audio_chunk(self, audio_bytes: bytes):
        if not self.session_start_time:
            self.start_session()

        duration = self._count_audio_seconds(audio_bytes)
        self.total_audio_seconds += duration

        return duration


    def add_final_transcript(self, text: str):
        timestamp = time.time()

        try:
            tokens = len(self.encoding.encode(text))
        except Exception:
            tokens = len(text.split())

        self.total_transcript_tokens += tokens

        segment = {
            "text": text,
            "tokens_estimated": tokens,
            "timestamp": timestamp,
            "latency_since_start": round(timestamp - self.session_start_time, 2)
        }

        self.segments.append(segment)
        return segment


    def get_usage_dict(self):
        return {
            "audio_seconds": round(self.total_audio_seconds, 2),
            "audio_minutes": round(self.total_audio_seconds / 60, 2),
            "transcript_tokens_estimated": self.total_transcript_tokens,
            "segments_count": len(self.segments),
            "segments": self.segments,
        }
