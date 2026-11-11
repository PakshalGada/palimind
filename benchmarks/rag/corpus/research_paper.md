# Abstract

We study retrieval quality for local document assistants and propose a hybrid sparse-dense pipeline.

# Method

We evaluated 240 questions across six document collections, comparing BM25, dense retrieval, and reciprocal-rank fusion. Each run used the same chunker and token budget.

# Results

Reciprocal-rank fusion improved Recall@10 by 9.4 points over dense retrieval alone. Reranking improved nDCG@10 by 6.1 points but added 180 milliseconds per query.
