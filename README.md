# Collecting and checking input–output data: an excerpt

This repository is an excerpt from a university research project I am working on. The project asks how much German industries rely on Chinese inputs. It uses Eurostat's FIGARO tables for 2010–2024, which record how much each industry buys from each other industry, by country of origin. The full project is private. The excerpt shows the part that collects the data, records where every file came from and checks it before anything is computed.

The code was written with an AI coding assistant under my direction; [How AI was used](#how-ai-was-used) says who did what.

## Start with three files

| File | What it shows |
|---|---|
| [extensions/history-2010-2024/download_data.py](extensions/history-2010-2024/download_data.py) | Collects 30 annual extracts from the Eurostat API: it fetched 26 and took over four that the project already held. Each response is checked before it is stored |
| [extensions/history-2010-2024/data/manifest.json](extensions/history-2010-2024/data/manifest.json) | The record that script wrote, one entry per file: request URL, retrieval time, size, SHA-256 and the result of the checks |
| [tests/test_figaro.py](tests/test_figaro.py) | 27 tests of the parser in [code/figaro.py](code/figaro.py). Most of them damage a real extract in memory and require the parser to reject it |

## Run it

Written for Python 3.13.7 with the packages pinned in [requirements.txt](requirements.txt). The commands below need only NumPy.

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt      # on Linux or macOS: .venv/bin/python
```

Then, from the repository root, with the environment's `python`:

```
python extensions/history-2010-2024/download_data.py --check
python extensions/history-2010-2024/prepare_data.py --check
python -m unittest discover -s tests
python -m unittest discover -s extensions/trade-model/tests
```

What they do and print:

1. The first verifies all 30 raw extracts (90.9 MB, about 6.6 million published values) against the manifest and the classification, without the network. It prints `Verified all 30 extracts offline: 26 new files, four preserved inputs. No files changed.` Change one byte of a raw file and it stops with `Integrity check failed`.
2. The second verifies the prepared files against the hashes of their raw inputs, of the code that built them and of the files themselves. It prints `PASS: all prepared files and their raw-input, code and baseline dependencies verified offline.`
3. The third runs 41 tests: the 27 of the parser, and 14 of the script that builds the 2022 and 2023 matrices.
4. The fourth runs 12 tests of the trade model listed below.

To rebuild the prepared data from the raw extracts into a folder outside the repository:

```
python extensions/history-2010-2024/prepare_data.py --output-dir ../rebuilt
```

With the pinned environment this reproduces all five prepared files byte for byte: the array archive, the panel of 61,440 industry pairs by year, the 960 industry-year accounts, the validation record and the audit ([data-audit.md](extensions/history-2010-2024/data/processed/data-audit.md)).

All of this was run on Windows, from a clean copy of the repository with a fresh environment. Linux and macOS were not tested.

## How the collection works

- **A file is fetched once and never overwritten.** A later run fetches only what the manifest does not list yet, so an interrupted run can be continued.
- **A response from the Eurostat API is checked before it is stored.** The checks are: the dataset and the exact edition (Eurostat's `updated` timestamp), the dimensions and their order, every code and label against a classification file whose hash is fixed, and the complete pattern of observations. A cell that should hold a value and does not stops the run; nothing is filled in with zero.
- **Every file a script fetched has a record:** request URL, retrieval time, HTTP headers, size and SHA-256.
- **The four earliest extracts (2022 and 2023) are the exception.** They were saved before the scripts existed. Their records hold the URL, the size, the hash and the day of retrieval, without the time or the headers. For the two 2022 files that day belongs to a later download that returned the same bytes; the first download was not logged, and `data/manifest.json` says so.
- **`--check` verifies everything again without the network:** each file against its recorded size and hash, and each extract from the Eurostat API against the same content checks as at download.
- **Signed values are kept as published.** Negative inventory changes, taxes less subsidies and similar entries are not clipped.

## Also in the excerpt

| File | What it shows |
|---|---|
| [extensions/history-2010-2024/prepare_data.py](extensions/history-2010-2024/prepare_data.py) | Builds one panel for all fifteen years from the raw extracts, reconciles each year's accounts and writes the audit |
| [extensions/look-through/download_figaro_ic.py](extensions/look-through/download_figaro_ic.py) | The full table for all 50 economies: 750 requests, with pauses, retries and a run that can be stopped and resumed |
| [extensions/two-editions/download_editions.py](extensions/two-editions/download_editions.py) | Earlier editions of the tables, which Eurostat no longer serves, taken from the Wayback Machine's copies. These files are checked for size and type, and `--check` compares their hashes |
| [extensions/prices/download_prices.py](extensions/prices/download_prices.py), [extensions/lactam-mirror/download_comtrade.py](extensions/lactam-mirror/download_comtrade.py) | Trade values and quantities (Eurostat Comext), a deflator, an exchange rate (ECB) and mirror trade data (UN Comtrade) |
| [extensions/trade-model/trade_model.py](extensions/trade-model/trade_model.py) and [its tests](extensions/trade-model/tests/test_trade_model.py) | Not data collection: a multi-sector trade model (Caliendo and Parro, 2015) solved in relative changes, tested on small made-up economies whose answers can be derived by hand |
| [docs/data-codebook.md](docs/data-codebook.md) | The project's codebook: codes, labels, accounting definitions and the orientation of the matrices |

These are downloads from APIs and from a web archive. Nothing here scrapes HTML pages or reads PDFs.

## What is not here

- **The analysis, its results and the text.** The project is unfinished research and stays private.
- **The raw files of the other four download scripts.** Their manifests are here, so the sources and hashes can be read. Their `--check` stops with a missing-file error in this excerpt, as it should.
- **Four Eurostat methodology PDFs** that [data/manifest.json](data/manifest.json) pins by hash. `code/build_matrices.py` refuses to run without them. Its tests run, and its outputs are in `outputs/data-pipeline/`.
- **What comments and links point to.** The files are copied from the project unchanged. Their comments mention a thesis, memos, a plan and other scripts; some links in the codebook lead outside the excerpt. None of that is included.

## How AI was used

The code was written with an AI coding assistant (Claude Code), working under my direction: I set the question, said what the pipeline should do and reviewed its output. The AI assisted in most of the code and the tests.

## Data source and reuse

Source of the data: Eurostat, FIGARO tables (datasets `NAIO_10_FCP_II1` to `NAIO_10_FCP_II4`), edition of July 2026, retrieved through Eurostat's dissemination API on the dates recorded in the manifests. The raw extracts and the saved metadata page are stored unchanged. Eurostat authorises reuse of its data if the source is acknowledged ([copyright notice](https://ec.europa.eu/eurostat/help/copyright-notice)). The prepared files under `extensions/history-2010-2024/data/processed/` and `outputs/data-pipeline/` rearrange these data; Eurostat is not responsible for them.

No licence is attached to the code. Please ask before reusing it.
