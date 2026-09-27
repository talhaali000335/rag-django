from prometheus_client import Counter, Histogram

# Count total questions asked
QUERY_COUNTER = Counter('rag_queries_total', 'Total RAG queries')

# Count errors
ERROR_COUNTER = Counter('rag_errors_total', 'Total errors')

# Count retrievals
RETRIEVAL_COUNTER = Counter('rag_retrievals_total', 'Total vector searches')

# Measure how long each step takes
LATENCY_HISTOGRAM = Histogram(
    'rag_node_latency_seconds',
    'Time spent in each graph node',
    labelnames=['node'],
    buckets=[.05, .1, .25, .5, 1, 2, 5]
)

# Track hallucination scores
HALLUCINATION_SCORE_HISTOGRAM = Histogram(
    'rag_hallucination_score',
    'Hallucination score (0=good, 1=bad)',
    buckets=[0, .1, .2, .3, .5, .7, 1.0]
)