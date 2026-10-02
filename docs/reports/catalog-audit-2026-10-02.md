# Catalog audit, 2026-10-02

A read-only audit of the **development** catalog, produced with `athena audit` after one
`athena seed --per-query 250` run on an empty database earlier the same day. The server
catalog does not exist yet; rerun the audit there after seeding and do not reuse these
counts as evidence for it.

## Totals

| Measure | Result |
| --- | --- |
| Papers | 7,765 |
| Source records | 7,863 |
| Identifiers | 11,773 |
| Publication dates | 2022-09-20 to 2026-10-02 |
| Import runs | 42 completed, 0 failed, 0 records rejected |

## Coverage

| Sources holding a record | Papers |
| --- | --- |
| arXiv only | 4,315 |
| OpenAlex only | 3,352 |
| Both | 98 |

| Metadata owner and type | Papers |
| --- | --- |
| arXiv preprint | 4,413 |
| OpenAlex article | 2,858 |
| OpenAlex preprint | 410 |
| OpenAlex review | 84 |

| Publication year | Papers |
| --- | --- |
| 2026 | 7,585 |
| 2025 | 51 |
| 2024 | 64 |
| 2023 | 45 |
| 2022 | 20 |

| Missing field | arXiv-owned (4,413) | OpenAlex-owned (3,352) |
| --- | --- | --- |
| Abstract | 0 | 3,352 |
| Venue | 4,149 | 59 |
| DOI | 4,101 | 45 |
| Authors | 0 | 47 |
| Topics | 0 | 13 |

The most common topics are arXiv categories: `cs.LG` (1,938 papers), `cs.AI` (1,904),
`cs.CV` (720), `cs.CL` (584), and `cs.RO` (357). OpenAlex records carry descriptive topic
names instead, such as "Artificial Intelligence in Healthcare and Education" (211).

## Checks

| Check | Result |
| --- | --- |
| Future publication dates | 0 |
| Unmerged arXiv DOI pairs | 0 |
| Papers without a source record | 0 |
| Papers without an identifier | 0 |
| Imports left running | 0 |
| Records rejected for identity conflicts | 0 |
| Titles shared by several papers | 204 titles, 422 papers |

## What this means for search and recommendations

- **The catalog is a snapshot of the last few weeks, not of the field.** 98% of papers
  are from 2026 and 96% were published in the 90 days before the audit; September and
  October 2026 alone hold 6,683. Each seed query asks for the newest records, so older
  and foundational work is almost absent. Queries about foundational papers cannot be
  evaluated on this catalog, and a "newest" baseline is nearly indistinguishable from
  a random one.
- **43% of papers have a title and no abstract.** Every OpenAlex-owned record lacks an
  abstract by design. Lexical scores and any text embedding for these papers rest on
  the title alone, so results will lean toward arXiv records unless that is measured
  and corrected. Evaluation results must be reported separately for the two groups.
- **Type and venue split along the same line.** All arXiv-owned papers are preprints,
  mostly without a venue or DOI; nearly all journal articles are title-only OpenAlex
  records. A venue filter therefore mostly selects title-only papers.
- **Topics use two vocabularies.** arXiv categories and OpenAlex topic names do not
  map to each other, so topic overlap is not comparable across sources as stored.
- **Shared titles are all within OpenAlex.** The 204 repeated titles involve only
  OpenAlex-owned papers; none pair an arXiv record with an OpenAlex one. They need a
  review before recommendations, so one work does not fill several slots. Titles never
  drive automatic merges.
- **No cross-source duplicates of the earlier kind.** The arXiv DOI matching added
  before this seed left no unmerged arXiv/OpenAlex pairs, and no import hit an
  identity conflict.

## Reproduce

```sh
uv run athena audit
```

The command runs in one read-only transaction and reports the same sections as JSON.
