from typing import Generator
try:
    # mistralai >= 2.0
    from mistralai.client import Mistral
    from mistralai.client.utils import BackoffStrategy, RetryConfig
except ImportError:
    # mistralai 1.x
    from mistralai import Mistral
    from mistralai.utils import BackoffStrategy, RetryConfig
from config import Config

# Hard timeout for Mistral HTTP calls (article synthesis on long transcripts can be slow)
REQUEST_TIMEOUT_MS = 120_000

# How long to keep retrying rate-limited (429) / 5xx responses with exponential backoff.
# The free Mistral tier allows very few requests per minute, so article synthesis waits
# patiently in the background while interactive chat gives up sooner.
ARTICLE_RETRY_MS = 180_000
CHAT_RETRY_MS = 20_000


class MistralServiceError(Exception):
    """Custom exception for Mistral Service errors."""
    pass


def _get_client(max_retry_ms: int) -> Mistral:
    if not Config.MISTRAL_API_KEY:
        raise MistralServiceError("MISTRAL_API_KEY is not set. Please configure it in the env.")
    retry_config = RetryConfig(
        "backoff",
        BackoffStrategy(initial_interval=2_000, max_interval=30_000, exponent=2, max_elapsed_time=max_retry_ms),
        retry_connection_errors=True,
    )
    return Mistral(api_key=Config.MISTRAL_API_KEY, timeout_ms=REQUEST_TIMEOUT_MS, retry_config=retry_config)


def _describe_error(e: Exception) -> str:
    text = str(e)
    if "429" in text or "rate limit" in text.lower():
        return "Mistral rate limit reached (the free tier allows only a few requests per minute). Wait a minute and try again."
    if "401" in text:
        return "Mistral rejected the API key. Check MISTRAL_API_KEY."
    return text


def _content_to_text(content) -> str:
    """Message content may be a plain string or a list of content chunks."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            text = getattr(part, "text", None)
            if text is None and isinstance(part, dict):
                text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return str(content)


def stream_chat(query: str, context: str, history: list) -> Generator[str, None, None]:
    """
    Builds system prompt, sets up message history, calls Mistral API,
    and yields streamed text tokens. Raises MistralServiceError on failure.
    """
    client = _get_client(CHAT_RETRY_MS)

    # Build system prompt with injected context
    system_prompt = (
        "You are an intelligent assistant that answers questions about video transcripts.\n"
        "Answer based on the context below. Be precise, cite specific moments when useful.\n"
        "If the answer is not in the context, say so clearly.\n\n"
        "Transcript context:\n"
        f"{context}"
    )

    # Build messages list starting with system message
    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    # Append history messages (making sure they are in the correct format)
    for message in history:
        if isinstance(message, dict) and "role" in message and "content" in message:
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                continue
            # Only user/assistant turns are accepted from the client; a client-supplied
            # "system" message could override the instructions above
            role = message["role"] if message["role"] in ("user", "assistant") else "user"
            messages.append({
                "role": role,
                "content": content
            })

    # Append current user query
    messages.append({
        "role": "user",
        "content": query
    })

    try:
        response_stream = client.chat.stream(
            model=Config.MISTRAL_MODEL,
            messages=messages
        )

        for chunk in response_stream:
            # Handle differences in SDK response schemas
            content = None
            try:
                if hasattr(chunk, 'data') and chunk.data is not None:
                    content = chunk.data.choices[0].delta.content
                else:
                    content = chunk.choices[0].delta.content
            except (AttributeError, IndexError):
                pass

            text = _content_to_text(content)
            if text:
                yield text

    except Exception as e:
        print(f"Mistral streaming exception: {e}")
        raise MistralServiceError(_describe_error(e)) from e


def generate_wikipedia_article(transcript: str, title: str) -> str:
    """
    Calls Mistral non-streaming to synthesize a beautifully styled
    encyclopedic Wikipedia article in Markdown format based on the transcript.
    Raises MistralServiceError on failure so callers never persist error text as an article.
    """
    if not transcript or not transcript.strip():
        raise MistralServiceError("Transcript is empty; cannot generate an article.")

    client = _get_client(ARTICLE_RETRY_MS)

    system_prompt = (
        "You are an expert technical writer and senior editor for VideoWiki, a highly detailed video encyclopedia.\n"
        "Your task is to transform the provided raw video transcript into a comprehensive, beautifully structured Wikipedia-style article in Markdown.\n\n"
        "Structure requirements:\n"
        "1. Do NOT write simple summaries. Write highly descriptive, long-form encyclopedic content.\n"
        "2. Use these exact top-level Markdown headers:\n"
        "   - # " + title + " (Main Title)\n"
        "   - ## Executive Summary (A professional abstract of the video)\n"
        "   - ## Key Thematic Concepts (Detailed glossary of concepts, definitions, and theories described in the video)\n"
        "   - ## Chronological Timeline & Topics (Outline the main milestones, segments, or chronological timeline if applicable)\n"
        "   - ## Technical Significance & Takeaways (Provide an in-depth analysis of why this content matters, who the target audience is, and key conclusions)\n"
        "3. Make sure to present details in a highly educational, formal encyclopedic tone. Do not use conversational filler or speak in the first person."
    )

    context_text = transcript[:50000]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Title of Video: {title}\n\nTranscript Content:\n{context_text}"}
    ]

    try:
        response = client.chat.complete(
            model=Config.MISTRAL_MODEL,
            messages=messages
        )
    except Exception as e:
        print(f"Mistral article generation exception: {e}")
        raise MistralServiceError(_describe_error(e)) from e

    content = None
    if response is not None and getattr(response, 'choices', None):
        content = _content_to_text(response.choices[0].message.content)

    if not content or not content.strip():
        raise MistralServiceError("Mistral returned an empty article.")

    return content
