# Historical FIGARO data audit, 2010-2024

All fifteen annual accounts pass the declared data and accounting checks. No source values needed correction, imputation, clipping, rebalancing or deletion. This is data preparation; no exposure, ranking, decomposition or causal result is estimated.

The largest cost-side versus sales-side output discrepancy is 1.7462298274e-10 million euros (0.000174623 euros), below the unchanged absolute tolerance of 1e-7 million euros. This reconciles the published accounts; it does not independently validate their underlying sources.

## Handling required before analysis

- Preserve signed inventory/final-use, operating-surplus/mixed-income, tax/subsidy and residence-adjustment entries. Nonnegativity applies to intermediate flows, not every account. Observed negative final-use categories: P5M. The annual audit also records negative accounting entries by item.
- Keep the 64-category universe. U has zero output and flows in every year; retain it with active=false and exclude it from per-unit-output denominators. The other 63 industries have positive output and external deliveries.
- Distinguish DE domestic flows from DOM accounting entries. Keep WRL_REST in foreign-origin totals. Structurally absent source positions are not imputed zeros.
- Uses and sales are overlapping views: DE-to-DE intermediate and final flows agree exactly. Keep the named archive arrays separate; do not add the two views as disjoint transactions. The intermediate panel has one row per year/supplier/user. China inputs are a subset of all imported inputs, so its three value columns must not all be added together.
- Retain current-basic-price units. Ratios are not deflators, and a temporal movement cannot by itself identify physical sourcing or a policy effect.
- China's source SUT status is OECD_ICIO for 2010-2019 and EE (Eurostat estimates using other-year SUTs) for 2020-2024. This source-construction distinction is recorded per year; it does not mean every Chinese bilateral cell has the same estimation method. Missing observation-status flags do not mean every cell was directly observed. See the preserved official metadata, section 18.3, referenced and hashed in validation.json.

## Combined files

- [history_2010_2024.npz](history_2010_2024.npz): 13.62 MB, losslessly compressed float64 arrays covering all fifteen years, all origins/destinations, final uses and signed accounts. Named arrays follow the existing baseline schema, with a leading year axis; classifications are stored once.
- [intermediate_panel.csv](intermediate_panel.csv): 3.51 MB and 61,440 unique year/supplying-industry/using-industry rows containing D, M and T0. CSV values retain round-trip numeric precision.
- [industry_accounts.csv](industry_accounts.csv): 960 unique year/industry rows, including output, cost factors, sales, external deliveries and the activity mask. Join output for an input coefficient on year and using industry; joining on year alone would duplicate observations.
- [validation.json](validation.json): annual checks, signs, source and code hashes, file sizes, exact 2022-2023 baseline comparisons, archive schema and output checksums.

The raw downloads, acquisition manifest and original research pipeline are unchanged. The original 2022 and 2023 arrays agree exactly with the preserved baseline. All saved numerical values were read back and compared; no precision reduction was used.

## Annual checks

Negative final-use counts describe the two overlapping source views separately; they must not be summed as unique transactions.

| Year | Active industries | Maximum output gap (million EUR) | Negative final uses received | Negative final sales | China source SUT status |
|---|---:|---:|---:|---:|---|
| 2010 | 63 | 1.75e-10 | 352 | 480 | OECD_ICIO |
| 2011 | 63 | 8.73e-11 | 374 | 450 | OECD_ICIO |
| 2012 | 63 | 5.82e-11 | 1084 | 541 | OECD_ICIO |
| 2013 | 63 | 8.73e-11 | 629 | 523 | OECD_ICIO |
| 2014 | 63 | 5.82e-11 | 312 | 471 | OECD_ICIO |
| 2015 | 63 | 1.16e-10 | 825 | 445 | OECD_ICIO |
| 2016 | 63 | 1.16e-10 | 1194 | 473 | OECD_ICIO |
| 2017 | 63 | 1.16e-10 | 505 | 364 | OECD_ICIO |
| 2018 | 63 | 1.16e-10 | 537 | 372 | OECD_ICIO |
| 2019 | 63 | 1.16e-10 | 638 | 479 | OECD_ICIO |
| 2020 | 63 | 5.82e-11 | 676 | 777 | EE |
| 2021 | 63 | 1.16e-10 | 690 | 364 | EE |
| 2022 | 63 | 1.16e-10 | 691 | 351 | EE |
| 2023 | 63 | 1.75e-10 | 706 | 527 | EE |
| 2024 | 63 | 5.82e-11 | 681 | 547 | EE |

## Reproduce

From the project root, using the existing pinned environment:

```powershell
.\.venv\Scripts\python.exe -B extensions\history-2010-2024\prepare_data.py
.\.venv\Scripts\python.exe -B extensions\history-2010-2024\prepare_data.py --check
```

The first command rebuilds and validates the prepared data. The second checks stored input, code and output fingerprints offline without writing. The full archive additionally preserves the signed values beyond the compact CSVs. See the canonical data codebook for definitions and axis conventions.
