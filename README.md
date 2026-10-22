# Patent Search Engine

## Problem Statement

Semantic search is usually better than exact keyword matching, but it can
still return many candidates that are only broadly related to a user's
query. The specific problem addressed by this project is how to improve the
quality of those results with a two-phase search process: first reduce the
full patent collection to roughly 100 relevant candidates, then apply a more
sophisticated ranking algorithm to select and order the best 30 results.

This project applies that problem to patent applications, where relevant
information is spread across titles, abstracts, claims, descriptions, and
classification codes. The goal is a local, reproducible search engine that
retrieves a manageable candidate set and then improves its ordering before
displaying results.

## Approach and Enhancement

The application uses the following pipeline:

1. Patent JSON files are read from `data/patent_data_small/`.
2. Records are normalized into a SQLite `patents` table.
3. SQLite FTS5 indexes the title, abstract, claims, and detailed description.
4. The first search phase uses BM25 full-text retrieval to produce up to 100
   candidates.
5. The second phase optionally applies a cross-encoder to score those
   candidates and returns the best 30 results.
6. The Streamlit application displays the ranked results and search timings.

The selected enhancement is **cross-encoder reranking** as the second phase
of the search pipeline.

- **Candidate retrieval** uses BM25 to reduce the collection to at most 100
  candidates.
- **Cross-encoder reranking** scores each candidate against the complete
  query and patent context, then orders the results by the model score.
- **Hybrid filters** can further constrain candidates by classification
  prefix, title keyword, abstract keyword, and exact title.
- The interface reports the enhanced search time alongside a baseline BM25
  search time, making the effect of the enhancement observable.

Cross-encoder reranking was chosen because it directly implements the
second phase in the problem statement. Unlike first-stage retrieval, the
cross-encoder evaluates the query and each candidate together, allowing it
to distinguish among similarly related patents. The baseline remains
available so the effect of the second phase can be compared on the same
candidate set and dataset.

## Requirements

- Python 3.12 or newer
- The packages listed in `requirements.txt`
- The patent JSON files in `data/patent_data_small/`

The first search with cross-encoder reranking enabled may download the
`cross-encoder/ms-marco-MiniLM-L-6-v2` model. Internet access is required for
that initial download; subsequent runs use the local model cache.

## Reproducing Part 1: Baseline Search

From the repository root, create and activate a virtual environment:

```bash
python -m venv venv
```

On macOS/Linux/WSL:

```bash
source venv/bin/activate
```

On Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
```

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

Build the local SQLite database from the supplied patent files:

```bash
python ingestion.py
```

The command prints a summary containing the number of files seen, indexed,
and failed. A successful initial run should report the patent files as
indexed and create/update `patents.db`.

Start the baseline application:

```bash
streamlit run app.py
```

In the browser, uncheck **Enable hybrid filters** and leave **Use
cross-encoder reranking** unchecked. Enter a query such as:

```text
vehicle wheel sensor
```

The displayed results and the `baseline` timing provide the Part 1 keyword
search result to reproduce.

## Reproducing Part 3: Enhanced Search

With the same environment and database, start the application:

```bash
streamlit run app.py
```

Use the search page as follows:

1. Enter the same query used for the baseline, such as `vehicle wheel
   sensor`.
2. Keep **Enable hybrid filters** checked.
3. Optionally enter one or more filters:
   - **Classification starts with**, for example `B60B`
   - **Title contains**
   - **Abstract contains**
   - **Exact title**
4. Check **Use cross-encoder reranking** to run the selected enhancement.
5. Compare the displayed result ordering and timing with the baseline.

The application searches up to 100 candidates, reranks them when the
cross-encoder option is enabled, and displays 30 results per page. Use the
**Previous** and **Next** buttons to reproduce pagination behavior.

To re-create the database after changing or replacing input JSON files, run:

```bash
python ingestion.py
streamlit run app.py
```

The ingestion step validates each JSON file, uses checksums to skip files
that have already been indexed, and records failures in the SQLite
`ingestion_jobs` table.

## Project Files

- `app.py` - Streamlit user interface, filters, pagination, and timing.
- `database.py` - SQLite schema, FTS5 index construction, search, and
  reranking.
- `ingestion.py` - Input validation, checksum-based ingestion, and job
  status tracking.
- `data/patent_data_small/` - Input patent JSON files.
- `patents.db` - Generated SQLite database and search index.
- `requirements.txt` - Python dependencies.
