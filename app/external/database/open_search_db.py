from haystack import Pipeline
from haystack.components.embedders import SentenceTransformersTextEmbedder
from haystack.components.rankers import SentenceTransformersDiversityRanker
from haystack_integrations.document_stores.opensearch import OpenSearchDocumentStore

text_embedder = SentenceTransformersTextEmbedder(
    model="sentence-transformers/all-mpnet-base-v2"
)

# Warm up the model
text_embedder.warm_up()

from haystack.components.joiners.document_joiner import DocumentJoiner
from haystack_integrations.components.retrievers.opensearch.bm25_retriever import (
    OpenSearchBM25Retriever,
)
from haystack_integrations.components.retrievers.opensearch.embedding_retriever import (
    OpenSearchEmbeddingRetriever,
)

from ..constants import OPEN_SEARCH_HOST, OPEN_SEARCH_PASSWORD, OPEN_SEARCH_USER , OPEN_SEARCH_INDEX


async def get_open_search_db() -> OpenSearchDocumentStore:
    document_store = OpenSearchDocumentStore(
        hosts=[OPEN_SEARCH_HOST],  # Local OpenSearch instance
        use_ssl=True,  # SSL is typically not used for local development
        verify_certs=False,  # Certificate verification is typically not needed for local development
        http_auth=(OPEN_SEARCH_USER, OPEN_SEARCH_PASSWORD),
        index = OPEN_SEARCH_INDEX
    )
    return document_store

async def get_open_search_retriver(db) -> Pipeline:
    bm25_retriever = OpenSearchBM25Retriever(document_store=db)
    retrieval_pipeline = Pipeline()
    retrieval_pipeline.add_component("bm25_retriever", bm25_retriever)
    return retrieval_pipeline

# # Define a function to embed text
# async def embed_text(texts) -> SentenceTransformersTextEmbedder:
#     output = await text_embedder.run({"text": texts})
#     return output["embedding"]