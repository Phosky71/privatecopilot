from typing import Any

from core.embeddings import embedding_service
from core.logging_config import logger
from db.chroma_manager import chroma_manager


class RAGService:
    def __init__(self):
        pass

    def search(self, workspace_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        collection = chroma_manager.get_collection(workspace_id)

        try:
            count = collection.count()
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to count collection for %s: %s", workspace_id, e)
            return []

        if count == 0:
            return []

        n_results = min(top_k, count)

        try:
            query_embedding = embedding_service.embed_text(query)
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("RAG query failed for %s: %s", workspace_id, e)
            return []

        formatted_results = []
        if results and results.get("documents") and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                formatted_results.append({
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "distance": results["distances"][0][i] if results.get("distances") else 0.0,
                })

        return formatted_results


rag_service = RAGService()
