from collections.abc import Sequence

from app.core.config import Settings, get_settings


class OpenAIEmbedder:
    """Small adapter around the OpenAI embeddings endpoint."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.openai_api_key:
            raise ValueError(
                "Configure OPENAI_API_KEY or LOGIC_OPENAI_API_KEY to use RAG embeddings."
            )
        from openai import OpenAI

        self.client = OpenAI(
            api_key=self.settings.openai_api_key,
            timeout=self.settings.openai_timeout_seconds,
            max_retries=2,
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=list(texts),
        )
        return [list(item.embedding) for item in response.data]
