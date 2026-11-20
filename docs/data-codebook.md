# FIGARO data codebook

## Active historical extension: validated inputs and combined data, 17 September 2026

The [authoritative plan](../china-input-rankings-thesis-plan.md) extends the research to **2010–2024** while preserving the 2022–2023 contract and completed work below. Acquire two full-resolution German slices per year: `c_dest=DE` for all-origin uses and `c_orig=DE` for all-destination sales, each with the appropriate `time` filter. These cover the 64-industry accounts, final uses and published accounting rows needed for the agreed core extension. All fifteen years use the July 2026 FIGARO edition; record each partition's actual source timestamp separately.

| Reference years | Official dataset | Source `updated` timestamp |
|---|---|---|
| 2010–2013 | `NAIO_10_FCP_II1` | `2026-07-18T23:00:00+0200` |
| 2014–2017 | `NAIO_10_FCP_II2` | `2026-07-18T23:00:00+0200` |
| 2018–2021 | `NAIO_10_FCP_II3` | `2026-07-18T23:00:00+0200` |
| 2022–2024 | `NAIO_10_FCP_II4` | `2026-07-20T11:00:00+0200` |

The [extension manifest](../extensions/history-2010-2024/data/manifest.json) is the acquisition record: 30 year/role entries, comprising 26 new raw files under `extensions/history-2010-2024/data/raw/figaro/2026-07-20/` and four original 2022–2023 files referenced in place. Manifest paths are relative to the project root. It preserves request URLs, source and retrieval dates, byte sizes, SHA-256 hashes, classification and observation-pattern checks, signed-value counts and source flags. The separate [acquisition script](../extensions/history-2010-2024/download_data.py) supports an offline `--check`; it does not modify the frozen pipeline or registry.

Acquisition and a fresh offline verification of all 30 inputs completed on **17 September 2026**. All reference years and both extraction roles are present; all category labels and codes match the preserved baseline classification. These extracts contain no flagged observations or negative real-economy intermediate cells. Other signed values remain untouched. Total raw input size is 90,947,389 bytes, of which 78,733,697 bytes are new downloads.

The subsequent [data audit and preparation](../extensions/history-2010-2024/data/processed/data-audit.md) passes annual accounting reconciliation, activity and delivery checks, and constructs the fifteen annual systems. **New exposure/ranking analysis and economic interpretation remain pending.** No corrections, imputations, clipping, rebalancing, smoothing or observation deletion were needed. Sparse structural absences are not converted to zeros. All signed entries are retained, including negative operating-surplus/mixed-income, tax/subsidy, inventory and residence-adjustment entries. U is inactive with zero associated flows in every year; retain it in the classification and use the explicit activity mask for denominators.

The [official metadata](https://ec.europa.eu/eurostat/cache/metadata/en/naio_10_fcp_esms.htm), section 18.3, distinguishes China's OECD ICIO source SUTs in 2010–2019 from Eurostat estimates using other-year SUTs in 2020–2024. This is a source-table distinction, not a statement that every Chinese bilateral cell after 2019 is estimated identically. The preserved metadata snapshot is referenced in the manifest. Accounts are at current basic prices; neither ratios nor import-share normalization remove relative-price or source-construction effects. The absence of observation flags does not establish direct observation or measurement accuracy.

### Prepared historical files and join keys

The [preparation script](../extensions/history-2010-2024/prepare_data.py) reuses the original accounting parser without editing it, supplying a derived per-year copy of the contract with the correct dataset, timestamp and year. It writes only `extensions/history-2010-2024/data/processed/`; an optional external output directory supports reproducibility checks. The acquisition manifest remains an unchanged historical receipt. The separate [preparation validation record](../extensions/history-2010-2024/data/processed/validation.json) records this later stage, including source/code/environment hashes, annual tests, shapes, signs and exact saved-value checks.

| File | Unit of observation / structure | Size and coverage |
|---|---|---|
| `history_2010_2024.npz` | Named arrays; dynamic arrays have a leading year axis, with `years` giving its order | 13,618,765 bytes; all 15 years, full 64-industry and 50-economy detail |
| `intermediate_panel.csv` | Unique `(year, supplying_industry, using_industry)` | 3,513,332 bytes; 61,440 rows = 15 × 64 × 64 |
| `industry_accounts.csv` | Unique `(year, industry)` | 179,653 bytes; 960 rows = 15 × 64 |
| `validation.json` / `data-audit.md` | Machine-readable audit and generated readable explanation | Annual findings, lineage, checksums and handling requirements |

The compressed archive uses the array definitions in the preserved contract below. Static classifications (`industries`, `industry_labels`, `economies`, `final_use_codes`, `accounting_codes`, `use_codes`) and scalar `unit` are stored once. All other annual arrays acquire a leading year axis: for example, `D`, `M`, `T0` have shape `(15,64,64)`, `Z_by_origin` has `(15,64,64,50)`, `accounting_by_use` has `(15,6,69)`, and `x`/`active` have `(15,64)`. The scalar annual `year` is replaced by `years` of shape `(15,)`. Added fields are `external_deliveries` of shape `(15,64)`, defined as `x - D.sum(axis=1)` in each annual system, and year-level `source_dataset` and `china_source_sut_status`. The latter is a documented annotation from the metadata table (`OECD_ICIO` or `EE`), not an API observation flag. `source_updated` is also year-level. Every monetary array retains float64 precision and million-euro units; identifiers and the activity mask are not monetary values.

The industry-pair CSV stores `D`, `M` and `T0` as `domestic_intermediate_million_eur`, `imported_intermediate_million_eur` and `china_intermediate_million_eur`. **China inputs are contained in total imports**: add `D + M` for all-origin intermediate inputs, not `D + M + T0`. Both industry axes retain the 64-code universe, including zero rows and columns. CSVs preserve round-trip numeric precision.

The industry-account CSV includes `active` (0/1), `intermediate_inputs`, four signed cost factors (`B2A3G`, `D1`, `D21X31`, `D29X39`), `x`, `intermediate_sales`, `final_sales`, `x_sales`, `x_gap` and `external_deliveries`; monetary column names end in `_million_eur`. These variables retain their baseline definitions below. To attach the denominator for an input coefficient, match `(year, using_industry)` to `(year, industry)`, a many-to-one join whose unique right key must be checked. To attach a supplier's output for another question, use the supplying-industry key explicitly. Matching only on year would create spurious duplicates.

The full source views contain 6,630,210 published observations, including 4,416 domestic DE→DE observations per year present in both views (6,563,970 distinct source observations overall). These overlaps agree exactly. The archive deliberately retains the separately named uses and sales arrays for accounting reconciliation; they are not disjoint transaction pools to append and sum. The compact intermediate panel contains each year/industry-pair key once. Structural absences have no fictitious rows, while published numeric zeros remain values.

The maximum annual cost/output discrepancy is `1.7462298274040222e-10` million euros, below the unchanged absolute tolerance of `1e-7` million euros. The 2022 and 2023 reconstructed arrays match all 25 preserved baseline fields exactly for each year. This validates preparation and accounting consistency, not Eurostat's underlying measurement accuracy. Numerical domestic-system checks are readiness diagnostics only; the preparation does not estimate content scores, industry rankings or decompositions.

Verification on 17 September 2026 included the 27 existing parser tests and an independent coordinate-by-coordinate decode of all 6,630,210 published raw values without calling the preparation/parser implementation. All source values, including 1,499,695 explicit zeros and 17,549 signed negatives across the overlapping views, were preserved exactly in float64 representation. Independent accurately summed aggregates differed by at most `2.33e-10` million euros, within the original tolerance. Both CSVs have complete, unique keys and exact numeric readback. A fresh rebuild from an unrelated working directory reproduced all five generated files byte for byte; all 6,585 pre-existing research and acquisition files were unchanged. Rejection probes also confirmed that missing years, misaligned industry codes and mislabeled years stop the year-stack operation.

### Downstream replication from the combined archive

On 17 September 2026 the user requested a strict same-year comparison, limited to **2022 and 2023**. The annual inputs were reconstructed from `history_2010_2024.npz` in an isolated workspace containing no original raw observations or saved numerical results as analytical inputs. Both annual NPZ archives and their eight CSVs reproduce byte for byte. All 21 downstream analysis/reporting scripts completed using the original analytical source files and settings.

The [full comparison](../extensions/history-2010-2024/outputs/replication-2022-2023/comparison.md) covers all 6,340 registered outputs: 6,313 match byte for byte, and 27 differ only in verified provenance and source-inventory counts. Scientific values and types agree exactly, without a tolerance; every headline value, numerical witness, table and figure retains its result. The source inventory has fewer raw-input records and additional combined-input/adapter records, so its diagnostic counts legitimately change. The three embedded monetary-expansion parent hashes were rebound only after verified scientific equality, with a preserved receipt; numerical methods were unchanged. The complete comparison subsequently revalidated those parents with the final comparator. All 6,591 pre-existing fingerprinted research/data files were preserved.

This establishes that the combined-data route reproduces the existing 2022–2023 study. It does not provide new results for the other thirteen years or remove the source-construction and current-price interpretation limits above. The [project README](../README.md) gives the reproduction and audit-retention details.

## Preserved 2022–2023 analytical contract

This contract covers Germany's 2022 and 2023 industry-by-industry accounts in the **20 July 2026 vintage** of Eurostat dataset `NAIO_10_FCP_II4`. It defines the source classifications and the accounting inputs for a reproducible data pipeline. The classifications remain at 64 industries, including all goods and services and the inactive German category U. It does not define an optimization problem or supply new ranking results.

## Canonical inputs and dates

The four immutable raw extracts are `data/raw/figaro/2026-07-20/de2022_uses.json`, `de2022_sales.json`, `de2023_uses.json` and `de2023_sales.json`. The uses requests select `c_dest=DE`; the sales requests select `c_orig=DE`. Each selects its own reference year. The dataset is [EU inter-country input-output table at basic prices, industry by industry (2022 and onwards)](https://doi.org/10.2908/NAIO_10_FCP_II4). Exact request URLs, bytes, checksums and acquisition records belong in `data/manifest.json`.

| Date or identifier | Meaning |
|---|---|
| 2022 and 2023 | Reference years: the economic activity represented by the observations |
| `2026-07-20T11:00:00+0200` | The `updated` value in every locked extract; source dissemination/data vintage |
| 20 July 2026 | Official HTML metadata's last certified, posted and updated dates, sections 2.1-2.3 |
| 9 September 2026 | Preserved HTML access date and this codebook's local verification date; separate from the reference years and source vintage |
| 2019 / May 2021 | Dates of the handbook and methodology supplement, respectively; not the vintage of the raw data |

The JSON annotation `CREATED=2025-07-15...` and DOI issued date `2025-07-16` describe the dataset object, not the reference year or the July 2026 data vintage. Source retrieval/access and local-copy dates must remain separate. The 2026 metadata describes the overall FIGARO series for 2010-2024; this particular `II4` variant covers 2022 onwards and the locked task selects only 2022 and 2023. Eurostat states that disseminated data can be revised and are never permanently final (metadata section 17.2).

The authoritative ordered classification is [classification.json](../data/metadata/figaro/classification.json). Its code-label records were derived from the official dimensions embedded in the original two 2022 evidence extracts and verified against all four canonical extracts. The preserved [official metadata HTML](../data/metadata/figaro/figaro-metadata-2026-09-09.html) is an unchanged copy of the evidence snapshot. [The canonical source manifest](../data/manifest.json) records its SHA-256 and the existing official PDFs used below. The PDF originals remain in `evidence/china-input-rankings/Pdfs/`; they are not duplicated.

## Dimensions and orientation

Every slice must identify `NAIO_10_FCP_II4` and use the following JSON-stat dimension order. Category labels are copied exactly from Eurostat's English response, including combined NACE aggregates and the source's country codes.

| Position | Dimension | Expected categories |
|---|---|---|
| 0 | `freq` | `A` (Annual) |
| 1 | `ind_use` | 64 industries plus the five listed final uses |
| 2 | `ind_ava` | The same 64 industries plus the six listed accounting items |
| 3 | `c_dest` | Uses: `DE`; sales: the 50 listed economies |
| 4 | `unit` | `MIO_EUR` (Million euro) |
| 5 | `c_orig` | Uses: 50 listed economies plus `DOM`; sales: `DE` |
| 6 | `time` | Exactly the selected reference year |

Expected sizes are `[1,69,70,1,1,51,1]` for uses and `[1,69,70,50,1,1,1]` for sales. Index positions must be read from `dimension.<id>.category.index` and ordered by their numeric index. The saved classification was derived by explicitly excluding `P3_S13`, `P3_S14`, `P3_S15`, `P5M`, `P51G` from `ind_use` and `B2A3G`, `D1`, `D21X31`, `D29X39`, `OP_RES`, `OP_NRES` from `ind_ava`, then checking the remaining industry code-label lists. At execution, validate membership and exact labels against that contract and select observations by code into its canonical order. A correctly reencoded source order therefore does not change the derived matrices. Do not infer industries from incidental JSON object order or select an unexplained first-64 slice.

Decode a flattened observation offset in the declared dimension order, with the last dimension changing fastest. For positions `p_k` and sizes `n_k`, the offset is `sum_k p_k * product_{l>k} n_l`. The raw industry block puts **using industry before supplying industry**. The `D`, `M` and `T0` matrices put **supplying industries in rows and German using industries in columns**, so extracting a raw `(ind_use, ind_ava)` block requires transposition. Labels alone cannot repair an orientation error.

`DE` is the Germany economy code and identifies domestic German intermediate transactions when both `c_orig=DE` and `c_dest=DE`. `DOM`, labelled "Domestic country" by the API, is a separate accounting category used for non-industry items in the uses slice. It is not a supplying economy, not a synonym for `DE`, and not a 51st economy. Exclude it explicitly from the economy list and from all intermediate-origin sums. `WRL_REST` is an economy aggregate and must remain in those sums. Preserve codes such as `EL` and `UK` as supplied; do not silently replace them with ISO alternatives.

## Accounting definitions

Let `I` be the ordered 64-industry list, `E` the ordered 50-economy list, `F` the five final uses, and `K = {B2A3G, D1, D21X31, D29X39}`. For a fixed year, write `R(u,a,d,c)` for the decoded value with `ind_use=u`, `ind_ava=a`, `c_dest=d`, `c_orig=c`, frequency A and unit MIO_EUR. Let `Z^{c,d}_{ij}=R(j,i,d,c)` for industry supplier `i` and industry user `j`.

| Object | Definition | Meaning |
|---|---|---|
| `D[i,j]` | `Z^{DE,DE}_{ij}` | Domestic German intermediate inputs |
| `M[i,j]` | `sum_{c in E, c != DE} Z^{c,DE}_{ij}` | Intermediate inputs from all foreign origins, including China and rest of world |
| `T0[i,j]` | `Z^{CN,DE}_{ij}` | Published China-origin intermediate inputs into Germany |
| `V[k,j]` | `R(j,k,DE,DOM)`, `k in K` | The four signed domestic cost components |
| `x_cost[j]` | `sum_{i in I}(D[i,j]+M[i,j]) + sum_{k in K} V[k,j]` | Gross industry output reconstructed from the cost side |
| `x_sales[i]` | `sum_{d in E} sum_{u in I union F} R(u,i,d,DE)` | Gross output reconstructed from German worldwide intermediate and final sales |

The working output vector `x` is `x_cost`, checked against the independently selected worldwide-sales slice's `x_sales` in the same industry order. This is an accounting reconciliation, not independent validation of Eurostat's underlying microdata. Industry final-use sales must be summed with their published signs. Export uses are represented by foreign destinations and their industries/final uses; do not invent another export final-use code. OP residence adjustments are not added again to German supplying-industry sales.

The cost identity combines intermediate inputs valued at basic prices with the product-tax adjustment and the value-added components. `D21X31` is **taxes less subsidies on products**, a valuation adjustment, and is not itself another component of gross value added. `B2A3G`, `D1` and `D29X39` supply gross operating surplus/mixed income, compensation of employees and other net production taxes. These roles follow the official dimension labels, metadata section 18.3 and the 2021 methodology's cost framework on page 7; the resulting identity is checked directly in the raw data.

All source amounts are in **million euros**. The industry-flow blocks are valued at **current basic prices** (metadata sections 3.1 and 4). They are monetary accounting flows. Basic prices exclude product taxes and include product subsidies, and exclude separately invoiced producer transport charges (ESA 2010, paragraph 3.44, printed page 60). Wholesale/retail output is measured through trade margins on resold goods (paragraph 3.56, printed page 62). A G46 supply cell must therefore not be interpreted as the total invoice value of all merchandise resold by wholesalers. Industry aggregates can also contain secondary production.

## Signs, missingness and inactive sectors

Keep every published numeric value unchanged when decoding. A source zero is a value; a missing observation is not a zero. Validate all expected 64 x 64 x 50 German intermediate cells and all 64 x 4 DOM cost-factor cells before constructing the matrices. Sparse omissions in accounting positions are distinct from absent intermediate cells. The locked industry-by-industry `DOM` block contains no observations, while the required industry/cost-factor DOM cells are present. This structural accounting absence must not become a fictitious domestic intermediate block.

`D`, `M` and `T0` must be finite and nonnegative, with `T0 <= M` checked directly. Do not extend those nonnegativity constraints to all accounting items or final uses. In particular:

- Negative `D29X39` values represent net subsidies in this signed account and must remain negative. The inspected DOM industry rows include 47 negative values in 2022 and 38 in 2023.
- Final-use flows, including changes in inventories/valuables (`P5M`) and any other published negative final-use entry, must retain their signs. Clipping negatives breaks the output reconciliation.
- `OP_RES` and `OP_NRES` are residence adjustments, not additional supplying industries or extra intermediate purchases. Both are explicitly zero for every industry use in these German slices. Their household-consumption entries are nonzero and signed, as shown below.

| Year | `DOM / OP_RES / P3_S14` | `DOM / OP_NRES / P3_S14` |
|---|---:|---:|
| 2022 | 68,883.098 | -27,180.964 |
| 2023 | 85,806.093 | -31,936.962 |

`OP_RES` means direct purchases abroad by residents; `OP_NRES` means purchases on the domestic territory by non-residents. The residence adjustments connect domestic-territory and resident household expenditure concepts. The handbook explains the addition of residents' purchases abroad and the subtraction of non-resident purchases from domestic household expenditure when moving to the national concept (2019 handbook sections 10.1-10.2, printed pages 126-127). Travel expenditure can also involve intermediate consumption conceptually; the zero adjustment entries for German industries are a finding of these extracts, not a claim that all travel expenditure is household consumption. Preserve the published allocation and avoid allocating these aggregate adjustment rows a second time.

Retain U, "Activities of extraterritorial organisations and bodies", in the 64-category contract. In both locked German years it has zero output and zero intermediate supplying row and using column. Treat it as **inactive** for per-unit-output analysis; do not silently drop it, divide by zero, or present a computed zero exposure as a substantive ranking result. Before allowing a zero-output sector, check that its associated flows are zero; a nonzero-flow/zero-output combination is a failed data check requiring investigation. Any later coefficient calculation must use an explicit active-sector mask or a documented zero-inverse convention whose applicability has been checked.

None of the four locked JSON extracts supplies an observation `status` object. Preserve status information if supplied and report its availability explicitly. Its absence does not establish that cells are observed, unadjusted or free from confidentiality treatment. Missing numeric observations and missing status flags are different conditions.

## Source construction and interpretation

The preserved July 2026 metadata is the authority for the edition's current coverage and compilation statements. Section 18.3, Table 1 marks China's 2022 **and** 2023 SUTs `EE`. Its note defines EE as SUTs estimated by Eurostat using SUTs from other years, specifically concerning source supply tables at basic prices and use tables at purchasers' prices. This does not say that every Chinese bilateral cell is absent, nor that all other input sources are estimated in the same way.

The metadata documents source gap filling, national-accounts benchmarks, international-trade balancing, GRAS reconciliation and controlled tabular adjustment for confidentiality (sections 7.2 and 18.3-18.6). Overall accuracy is unavailable (section 13.1). Holding `D`, `M`, `x` or published China supplying-industry totals fixed in a later sensitivity exercise is therefore a maintained conditional benchmark, not a declaration that these quantities are known without error. These sources do not provide a cell-error distribution or exact German firm-level import users.

The 2019 handbook describes a common allocation across users when more specific bilateral information is unavailable, followed by valuation and balancing steps (sections 11.3.2-11.3.3, printed pages 134-136). That historical intermediate step does not imply a universal constant China share in the final 2022/2023 industry table. The handbook and May 2021 supplement describe historical compilation methods, not an exhaustive 2026 algorithm. In particular, the supplement's **page 4, footnote 1** states that national industry-by-industry IOTs were not integrated in the May 2021 release; page 7 also marks the described import-rescaling step as not implemented for that release.

"China origin" means a link attributed to China in the adjusted FIGARO accounting network. Metadata section 3.4 follows changes of ownership between residents/non-residents rather than requiring a physical border crossing. The historical QDR example connects re-exported goods' initial origin to their final destination while separately identifying the intermediary margin (Martins Ferreira, issue 2/2018, printed pages 66-68). A direct CN-to-DE link need not be a direct customs shipment. These inputs alone do not measure Chinese ownership, physical routes, substitutability, welfare losses or all Chinese value added embedded in goods transformed in third countries.

## Generated files and array schema

The pipeline's default generated directory is `outputs/data-pipeline/`. For each year it writes `matrices_<year>.npz`, `D_<year>.csv`, `M_<year>.csv`, `T0_<year>.csv` and `accounting_<year>.csv`; `validation.json` records checks, residuals, runtime information and artifact checksums for both years. These outputs are rebuildable from the canonical inputs and classification contract.

The NPZ files store the following arrays. Every industry axis uses `industries`, every economy axis uses `economies`, and every final-use axis uses `final_use_codes`. All numeric monetary arrays use million euros; the activity mask and identifiers are not monetary quantities.

| NPZ key | Shape | Meaning / axis order |
|---|---|---|
| `industries`, `industry_labels` | `(64,)` each | Ordered industry codes and corresponding official labels |
| `economies` | `(50,)` | Ordered real-economy codes, excluding DOM and including WRL_REST |
| `final_use_codes` | `(5,)` | Ordered final uses |
| `accounting_codes` | `(6,)` | Ordered accounting items |
| `use_codes` | `(69,)` | Industry codes followed by final-use codes in the saved canonical contract order |
| `D`, `M`, `T0` | `(64,64)` each | Supplying industry, German using industry; definitions above |
| `Z_by_origin` | `(64,64,50)` | Supplier industry, German user industry, origin economy |
| `final_uses_by_origin` | `(64,5,50)` | Supplier industry, German final use, origin economy; signed |
| `sales_intermediate_by_destination` | `(64,64,50)` | German supplier industry, destination user industry, destination economy |
| `sales_final_by_destination` | `(64,5,50)` | German supplier industry, destination final use, destination economy; signed |
| `accounting_by_use` | `(6,69)` | Accounting item, German use (industry or final use), selected at origin DOM; signed |
| `intermediate_inputs` | `(64,)` | Each German user's intermediate inputs summed over all suppliers and real origins |
| `intermediate_sales` | `(64,)` | Each German supplier's intermediate sales summed over users and all real destinations |
| `final_sales` | `(64,)` | Each German supplier's signed final-use sales summed over all real destinations |
| `x` | `(64,)` | Cost-side output, `x_cost` above |
| `x_sales` | `(64,)` | `intermediate_sales + final_sales` |
| `x_gap` | `(64,)` | `x - x_sales`; signed reconciliation residual |
| `active` | `(64,)` | Boolean `x > 0`; U is false in both locked years |
| `china_row_totals` | `(64,)` | Published China input totals by supplying industry, `T0.sum(axis=1)` |
| `unit` | scalar | `MIO_EUR` |
| `year` | scalar | Reference year, 2022 or 2023 |
| `source_updated` | scalar | Locked source update timestamp |

The three matrix CSVs label supplying industries on rows and using industries on columns. The accounting CSV has one row per industry and columns `industry`, `active` (0/1), `intermediate_inputs`, `B2A3G`, `D1`, `D21X31`, `D29X39`, `x_inputs`, `intermediate_sales`, `final_sales`, `x_sales`, and `input_minus_sales`. Here `x_inputs` is NPZ `x` and `input_minus_sales` is NPZ `x_gap`. Residence adjustments for final uses remain available in the full NPZ `accounting_by_use` and the raw source; they are outside the industry-only accounting CSV.

The implementation uses an absolute reconciliation tolerance of `1e-7` million euros, with no relative tolerance that could conceal a larger discrepancy. The report gives the actual maximum residual and identifies U explicitly. The data contract retains the full 64-category classification even though the active German system has 63 industries.

## Ordered classification labels

The tables below reproduce `classification.json`; the code, rather than a mutable descriptive label, is the join key. Industries follow NACE Rev. 2 aggregates, not uniformly disaggregated two-digit manufacturing sectors. Country codes preserve Eurostat's source convention. The numeric-index ordering is part of the contract.

### Industries

| Position (zero based) | Code | Official label |
|---:|---|---|
| 0 | `A01` | Crop and animal production, hunting and related service activities |
| 1 | `A02` | Forestry and logging |
| 2 | `A03` | Fishing and aquaculture |
| 3 | `B` | Mining and quarrying |
| 4 | `C10-12` | Manufacture of food products; beverages and tobacco products |
| 5 | `C13-15` | Manufacture of textiles, wearing apparel, leather and related products |
| 6 | `C16` | Manufacture of wood and of products of wood and cork, except furniture; manufacture of articles of straw and plaiting materials |
| 7 | `C17` | Manufacture of paper and paper products |
| 8 | `C18` | Printing and reproduction of recorded media |
| 9 | `C19` | Manufacture of coke and refined petroleum products |
| 10 | `C20` | Manufacture of chemicals and chemical products |
| 11 | `C21` | Manufacture of basic pharmaceutical products and pharmaceutical preparations |
| 12 | `C22` | Manufacture of rubber and plastic products |
| 13 | `C23` | Manufacture of other non-metallic mineral products |
| 14 | `C24` | Manufacture of basic metals |
| 15 | `C25` | Manufacture of fabricated metal products, except machinery and equipment |
| 16 | `C26` | Manufacture of computer, electronic and optical products |
| 17 | `C27` | Manufacture of electrical equipment |
| 18 | `C28` | Manufacture of machinery and equipment n.e.c. |
| 19 | `C29` | Manufacture of motor vehicles, trailers and semi-trailers |
| 20 | `C30` | Manufacture of other transport equipment |
| 21 | `C31_32` | Manufacture of furniture; other manufacturing |
| 22 | `C33` | Repair and installation of machinery and equipment |
| 23 | `D35` | Electricity, gas, steam and air conditioning supply |
| 24 | `E36` | Water collection, treatment and supply |
| 25 | `E37-39` | Sewerage, waste management, remediation activities |
| 26 | `F` | Construction |
| 27 | `G45` | Wholesale and retail trade and repair of motor vehicles and motorcycles |
| 28 | `G46` | Wholesale trade, except of motor vehicles and motorcycles |
| 29 | `G47` | Retail trade, except of motor vehicles and motorcycles |
| 30 | `H49` | Land transport and transport via pipelines |
| 31 | `H50` | Water transport |
| 32 | `H51` | Air transport |
| 33 | `H52` | Warehousing and support activities for transportation |
| 34 | `H53` | Postal and courier activities |
| 35 | `I` | Accommodation and food service activities |
| 36 | `J58` | Publishing activities |
| 37 | `J59_60` | Motion picture, video, television programme production; programming and broadcasting activities |
| 38 | `J61` | Telecommunications |
| 39 | `J62_63` | Computer programming, consultancy, and information service activities |
| 40 | `K64` | Financial service activities, except insurance and pension funding |
| 41 | `K65` | Insurance, reinsurance and pension funding, except compulsory social security |
| 42 | `K66` | Activities auxiliary to financial services and insurance activities |
| 43 | `L` | Real estate activities |
| 44 | `M69_70` | Legal and accounting activities; activities of head offices; management consultancy activities |
| 45 | `M71` | Architectural and engineering activities; technical testing and analysis |
| 46 | `M72` | Scientific research and development |
| 47 | `M73` | Advertising and market research |
| 48 | `M74_75` | Other professional, scientific and technical activities; veterinary activities |
| 49 | `N77` | Rental and leasing activities |
| 50 | `N78` | Employment activities |
| 51 | `N79` | Travel agency, tour operator reservation service and related activities |
| 52 | `N80-82` | Security and investigation, service and landscape, office administrative and support activities |
| 53 | `O84` | Public administration and defence; compulsory social security |
| 54 | `P85` | Education |
| 55 | `Q86` | Human health activities |
| 56 | `Q87_88` | Residential care activities and social work activities without accommodation |
| 57 | `R90-92` | Creative, arts and entertainment activities; libraries, archives, museums and other cultural activities; gambling and betting activities |
| 58 | `R93` | Sports activities and amusement and recreation activities |
| 59 | `S94` | Activities of membership organisations |
| 60 | `S95` | Repair of computers and personal and household goods |
| 61 | `S96` | Other personal service activities |
| 62 | `T` | Activities of households as employers; undifferentiated goods- and services-producing activities of households for own use |
| 63 | `U` | Activities of extraterritorial organisations and bodies |

### Economies

`DOM` is excluded; `WRL_REST` is included. Positions below are the economy-list positions after explicitly excluding DOM, not the raw origin indices.

| Position (zero based) | Code | Official label |
|---:|---|---|
| 0 | `BE` | Belgium |
| 1 | `BG` | Bulgaria |
| 2 | `CZ` | Czechia |
| 3 | `DK` | Denmark |
| 4 | `DE` | Germany |
| 5 | `EE` | Estonia |
| 6 | `IE` | Ireland |
| 7 | `EL` | Greece |
| 8 | `ES` | Spain |
| 9 | `FR` | France |
| 10 | `HR` | Croatia |
| 11 | `IT` | Italy |
| 12 | `CY` | Cyprus |
| 13 | `LV` | Latvia |
| 14 | `LT` | Lithuania |
| 15 | `LU` | Luxembourg |
| 16 | `HU` | Hungary |
| 17 | `MT` | Malta |
| 18 | `NL` | Netherlands |
| 19 | `AT` | Austria |
| 20 | `PL` | Poland |
| 21 | `PT` | Portugal |
| 22 | `RO` | Romania |
| 23 | `SI` | Slovenia |
| 24 | `SK` | Slovakia |
| 25 | `FI` | Finland |
| 26 | `SE` | Sweden |
| 27 | `NO` | Norway |
| 28 | `CH` | Switzerland |
| 29 | `UK` | United Kingdom |
| 30 | `ME` | Montenegro |
| 31 | `MK` | North Macedonia |
| 32 | `AL` | Albania |
| 33 | `RS` | Serbia |
| 34 | `TR` | Türkiye |
| 35 | `RU` | Russia |
| 36 | `ZA` | South Africa |
| 37 | `CA` | Canada |
| 38 | `US` | United States |
| 39 | `MX` | Mexico |
| 40 | `AR` | Argentina |
| 41 | `BR` | Brazil |
| 42 | `CN` | China |
| 43 | `JP` | Japan |
| 44 | `KR` | South Korea |
| 45 | `IN` | India |
| 46 | `ID` | Indonesia |
| 47 | `SA` | Saudi Arabia |
| 48 | `AU` | Australia |
| 49 | `WRL_REST` | Rest of the world |

### Final uses

| Code | Official label |
|---|---|
| `P3_S13` | Final consumption expenditure by government |
| `P3_S14` | Final consumption expenditure by households |
| `P3_S15` | Final consumption expenditure by non-profit organisations serving households (NPISH) |
| `P5M` | Changes in inventories and acquisition less disposals of valuables |
| `P51G` | Gross fixed capital formation |

### Accounting items

| Code | Official label |
|---|---|
| `B2A3G` | Operating surplus and mixed income, gross |
| `D1` | Compensation of employees |
| `D21X31` | Taxes less subsidies on products |
| `D29X39` | Other taxes less other subsidies on production |
| `OP_RES` | Direct purchases abroad by residents |
| `OP_NRES` | Purchases on the domestic territory by non-residents |

## Primary source provenance and verification

All substantive source claims above were checked against the preserved official HTML, local official PDFs, and the four raw API responses. Earlier project reading notes provide useful context and recorded access dates; the source files determine the contract. No new web retrieval was needed to fill a source gap. The canonical `data/manifest.json` stores hashes, bytes, official URLs, source date precision, access-date evidence and the locators used.

| Source | Preserved location | Source date / scope |
|---|---|---|
| FIGARO metadata | [figaro-metadata-2026-09-09.html](../data/metadata/figaro/figaro-metadata-2026-09-09.html) | Updated 20 July 2026; edition coverage, valuation, source availability and compilation |
| FIGARO handbook | [eurostat-2019-figaro-handbook.pdf](../evidence/china-input-rankings/Pdfs/eurostat-2019-figaro-handbook.pdf) | 2019 edition; manuscript completed March 2019; historical method and residence concepts |
| FIGARO methodology | [eurostat-2021-figaro-methodology.pdf](../evidence/china-input-rankings/Pdfs/eurostat-2021-figaro-methodology.pdf) | May 2021; dated supplement with implementation qualifications |
| ESA 2010 | [eurostat-2013-esa2010.pdf](../evidence/china-input-rankings/Pdfs/eurostat-2013-esa2010.pdf) | Published 2013; basic prices and wholesale/transport output concepts |
| Martins Ferreira, QDR article | [eurostat-2018-figaro-qdr.pdf](../evidence/china-input-rankings/Pdfs/eurostat-2018-figaro-qdr.pdf) | Issue 2/2018; volume colophon published 2019; article pp.55-70 within the complete volume |

For each existing PDF the recorded access date is 9 September 2026, supported by the corresponding `urldate` in `thesis/references.bib`; it is not a newly asserted download timestamp. Metadata access is also recorded explicitly in the existing FIGARO accounting reading note. Unknown exact first-download times and PDF update dates are not invented. Publication years/months retain the precision actually shown by the source.

Local checks on 9 September 2026 confirmed matching industry/economy code-label lists in all four slices, the locked update timestamp and dimensions, complete nonnegative German intermediate blocks, the signed cost-factor/residence-adjustment examples above, and U's inactivity. Direct cost-versus-worldwide-sales checks agreed to floating-point precision (maximum absolute discrepancies below `2e-10` million euros in each year). The runnable pipeline must recompute and report its own reconciliation residuals and tolerances; these snapshot checks are not substitutes for validating a later file or vintage. Source-byte checksums, not mutable file timestamps, identify the preserved inputs.
