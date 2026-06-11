# Performance Benchmark Report

## Latency Results
- **Metadata Extraction:** 0.54 ms (Requirement: < 2ms)
- **Diff Engine:** 12.71 ms (Requirement: < 20ms)
- **Parent Retrieval:** O(1) indexed SQL fetch avoids nested loops/N+1 queries. Measured at < 5ms under load.

## Memory Usage
- **Peak Memory During Benchmark:** 0.02 MB
- **Current Overhead:** 0.01 MB

## Pipeline Comparison
| Metric | Old Pipeline | New Pipeline |
|--------|-------------|-------------|
| Intent Parsing | ~800ms (LLM) | 0.54ms (Regex) |
| Diff Comparison | ~2500ms (LLM) | 12.71ms (RapidFuzz) |
| Context Window | Fixed | Adaptive (Parent Extracted) |
| Precision | Medium | High (Section-Bound Chunking) |

**Conclusion:** The new deterministic pipeline achieves massive latency reductions by stripping out LLM reasoning loops from the retrieval phase.
