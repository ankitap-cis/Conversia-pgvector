import asyncio
import json
import websockets
from fastapi import WebSocket, WebSocketDisconnect
import configparser
from logger import *
import base64
from utils.speech_usage import SpeechToTextUsage

config = configparser.ConfigParser()
config.read("config.ini")

transcription_model = config["openAI_config"]["transcription_model"]
usage_tracker = SpeechToTextUsage(model=transcription_model)


class TranscriptionService:
    """Service to handle OpenAI real-time transcription"""

    OPENAI_WSS_URL = "wss://api.openai.com/v1/realtime?intent=transcription"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def handle_transcription(self, client_websocket: WebSocket, usage_tracker=None):
        try:
            async with websockets.connect(
                self.OPENAI_WSS_URL,
                additional_headers={
                    "Authorization": f"Bearer {self.api_key}",
                    # "OpenAI-Beta": "realtime=v1"
                }
            ) as openai_websocket:

                logger.info("Successfully connected to OpenAI WebSocket.")
                await self._initialize_session(openai_websocket)

                send_task = asyncio.create_task(
                    self._forward_to_openai(
                        client_websocket,
                        openai_websocket,
                        usage_tracker
                    )
                )

                receive_task = asyncio.create_task(
                    self._forward_to_client(
                        client_websocket,
                        openai_websocket,
                        usage_tracker
                    )
                )

                done, pending = await asyncio.wait(
                    [send_task, receive_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in pending:
                    task.cancel()

        except Exception as e:
            logger.error(f"Error in transcription service: {e}")

        finally:
            logger.info("Transcription session ending.")

            if usage_tracker:
                usage = usage_tracker.get_usage_dict()

                logger.info(f"Final audio seconds: {usage.get('audio_seconds')}")
                logger.info(f"Final audio minutes: {usage.get('audio_minutes')}")

                return usage

            return None

    async def _initialize_session(self, openai_websocket):
        """Initialize OpenAI transcription session"""

        initial_message = await openai_websocket.recv()
        session_data = json.loads(initial_message)

        logger.info(f"Received event: {session_data.get('type')}")
        logger.info(json.dumps(session_data, indent=2))

        if session_data.get("type") in [
            "session.created",
            "transcription_session.created"
        ]:
            session_update = {
                "type": "session.update",
                "session": {
                    "type": "transcription",
                    "audio": {
                        "input": {
                            "format": {
                                "type": "audio/pcm",
                                "rate": 24000
                            },
                            "transcription": {
                                "model": "gpt-realtime-whisper",
                                "language": "en"
                            },
                            "turn_detection": None
                        }
                    }
                }
            }

            await openai_websocket.send(json.dumps(session_update))
            logger.info("Transcription session update sent.")

            update_response = await openai_websocket.recv()
            update_data = json.loads(update_response)

            logger.info(f"Session update response type: {update_data.get('type')}")
            logger.info(json.dumps(update_data, indent=2))

    async def _forward_to_openai(
        self,
        client_websocket: WebSocket,
        openai_websocket,
        usage_tracker
    ):
        while True:
            try:
                message = await client_websocket.receive()

                if message.get("type") == "websocket.disconnect":
                    logger.info("Client disconnected.")
                    return
                text_message = message.get("text")

                if text_message:
                    try:
                        payload = json.loads(text_message)

                        if payload.get("event") == "stop":
                            logger.info("Received stop event.")

                            await openai_websocket.send(json.dumps({
                                "type": "input_audio_buffer.commit"
                            }))

                            continue
                    except Exception:
                        pass

                audio_bytes = message.get("bytes")

                if not audio_bytes:
                    continue

                logger.info(f"Received audio bytes from client: {len(audio_bytes)} bytes")

                if usage_tracker:
                    usage_tracker.add_audio_chunk(audio_bytes)

                audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

                await openai_websocket.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": audio_base64
                }))

            except WebSocketDisconnect:
                logger.info("Client disconnected with WebSocketDisconnect.")
                return

            except RuntimeError as e:
                if "disconnect message has been received" in str(e):
                    logger.info("Client already disconnected.")
                    return

                logger.error(f"Runtime error in _forward_to_openai: {e}")
                return

            except Exception as e:
                logger.error(f"Unexpected error in _forward_to_openai: {e}")
                return

    async def _flush_audio_buffer(
        self,
        openai_websocket,
        buffer: bytearray,
        min_audio_bytes: int,
        sample_rate: int,
        bytes_per_sample: int
    ):
        """Append and commit buffered audio only if enough audio exists."""

        if len(buffer) < min_audio_bytes:
            logger.info(
                f"Dropping small leftover audio: {len(buffer)} bytes "
                f"(< {min_audio_bytes})"
            )
            return

        audio_base64 = base64.b64encode(bytes(buffer)).decode("utf-8")

        await openai_websocket.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": audio_base64
        }))

        await asyncio.sleep(0.05)

        logger.info(
            f"Sent audio append + commit to OpenAI: {len(buffer)} bytes "
            f"(~{len(buffer) / (sample_rate * bytes_per_sample):.3f}s)"
        )

        buffer.clear()

    async def _forward_to_client(
        self,
        client_websocket: WebSocket,
        openai_websocket,
        usage_tracker
    ):
        """Forward transcription results from OpenAI to client"""


        partial_transcripts = {}

        while True:
            try:
                message = await openai_websocket.recv()
                response = json.loads(message)

                logger.info(json.dumps(response, indent=2))

                event_type = response.get("type", "")

                if event_type == "conversation.item.input_audio_transcription.delta":
                    item_id = response.get("item_id")
                    delta = response.get("delta", "")

                    if item_id not in partial_transcripts:
                        partial_transcripts[item_id] = ""

                    partial_transcripts[item_id] += delta

                    transcript_data = {
                        "text": partial_transcripts[item_id],
                        "is_final": False
                    }

                    await client_websocket.send_text(json.dumps(transcript_data))
                
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    item_id = response.get("item_id")
                    text = response.get("transcript", "")

                    if not text and item_id in partial_transcripts:
                        text = partial_transcripts[item_id]

                    transcript_data = {
                        "text": text.strip(),
                        "is_final": True
                    }

                    await client_websocket.send_text(json.dumps(transcript_data))

                    await client_websocket.send_text(json.dumps({
                        "event": "session_ended"
                    }))

                    if item_id in partial_transcripts:
                        del partial_transcripts[item_id]

                elif event_type == "conversation.item.done":
                    item = response.get("item", {})
                    content = item.get("content", [])

                    for part in content:
                        if part.get("type") == "input_audio":
                            text = part.get("transcript")

                            if text:
                                transcript_data = {
                                    "text": text,
                                    "is_final": True
                                }

                                await client_websocket.send_text(
                                    json.dumps(transcript_data)
                                )

                elif event_type == "error":
                    error_info = response.get("error", {})
                    error_code = error_info.get("code")
                    error_message = error_info.get("message", "Unknown error")

                    logger.error(f"OpenAI Error: {error_message}")
                    logger.error(f"Full error: {json.dumps(response, indent=2)}")

                    if error_code == "session_expired":
                        logger.warning("OpenAI session expired. Closing connections.")

                        await openai_websocket.close()
                        await client_websocket.close(
                            code=1011,
                            reason="Transcription session expired"
                        )
                        break

                    if error_code == "input_audio_buffer_commit_empty":
                        logger.warning(
                            "Commit failed because OpenAI audio buffer was empty."
                        )
                        continue

                else:
                    logger.info(f"Received event: {event_type}")

            except Exception as e:
                logger.error(f"Error receiving from OpenAI: {e}")
                break