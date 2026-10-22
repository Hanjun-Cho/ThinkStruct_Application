# Part 2: Scaling the Patent Search Engine

## Simple Architecture

```text
Patent files -> Object storage -> Processing workers -> Search index -> Search API -> UI
```

- Store original patent files in object storage such as S3.
- Use workers to read, validate, and normalize each patent.
- Store metadata in PostgreSQL.
- Store searchable text in OpenSearch or Elasticsearch.
- Keep the current Streamlit UI, but have it call a search API in production.

## Processing Pipeline

1. Find new patent files.
2. Calculate a checksum so files are not processed twice.
3. Add each file to a processing queue.
4. Parse and validate each patent.
5. Save valid records to PostgreSQL.
6. Index title, abstract, claims, description, and classification in the search engine.
7. Mark the file as complete.

The checksum and document number make the process idempotent. Re-running a job should update a patent, not create a duplicate.

## Errors and Monitoring

Each file or patent should have a status:

```text
pending -> processing -> indexed
                     -> failed
```

Temporary failures should be retried. Bad records should be saved in a dead-letter queue with the error message so they can be fixed later without stopping the whole batch.

Track:

- Files processed
- Patents indexed
- Failed records
- Processing duration
- Search latency
- Index version
