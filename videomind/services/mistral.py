from typing import Generator
try:
    from mistralai import Mistral
except ImportError:
    from mistralai.client import Mistral
from config import Config

class MistralServiceError(Exception):
    """Custom exception for Mistral Service errors."""
    pass

def stream_chat(query: str, context: str, history: list) -> Generator[str, None, None]:
    """
    Builds system prompt, sets up message history, calls Mistral API,
    and yields streamed text tokens. Handles MistralException/errors gracefully.
    """
    if not Config.MISTRAL_API_KEY:
        yield "[Error: MISTRAL_API_KEY is not set. Please configure it in the env.]"
        return

    try:
        # Initialize client
        client = Mistral(api_key=Config.MISTRAL_API_KEY)
        
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
                # Ensure roles are mapped to standard mistral roles ("user", "assistant")
                role = message["role"]
                if role not in ["user", "assistant", "system"]:
                    role = "user" # default fallback
                messages.append({
                    "role": role,
                    "content": message["content"]
                })
                
        # Append current user query
        messages.append({
            "role": "user",
            "content": query
        })
        
        # Call the streaming endpoint of Mistral using 'mistral-small-latest'
        response_stream = client.chat.stream(
            model="mistral-small-latest",
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
            except (AttributeError, IndexError) as e:
                # Silently catch and try fallback methods if needed
                pass
                
            if content is not None:
                yield content
                
    except Exception as e:
        print(f"Mistral streaming exception: {e}")
        yield f"\n[Mistral Stream Error: {str(e)}]"

def generate_wikipedia_article(transcript: str, title: str) -> str:
    """
    Calls Mistral non-streaming to synthesize a beautifully styled
    encyclopedic Wikipedia article in Markdown format based on the transcript.
    """
    if not Config.MISTRAL_API_KEY:
        return "Error: MISTRAL_API_KEY is not configured."
        
    try:
        client = Mistral(api_key=Config.MISTRAL_API_KEY)
        
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
        
        context_text = transcript[:50000] if transcript else "Empty transcript context."
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Title of Video: {title}\n\nTranscript Content:\n{context_text}"}
        ]
        
        response = client.chat.complete(
            model="mistral-small-latest",
            messages=messages
        )
        
        content = None
        if hasattr(response, 'choices') and len(response.choices) > 0:
            content = response.choices[0].message.content
        
        if not content:
            return f"# {title}\n\n## Executive Summary\nFailed to generate a full article. Here is the raw transcript:\n\n{transcript[:2000]}..."
            
        return content
        
    except Exception as e:
        print(f"Mistral article generation exception: {e}")
        return f"# {title}\n\n## Executive Summary\nFailed to generate article: {str(e)}"

