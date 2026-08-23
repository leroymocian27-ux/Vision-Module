# Phase 6 Public Fall Dataset Survey

## Selection Rules

Datasets are only allowed into Phase 6C training when source, license, RGB availability, and labels are clear. Unknown mirrors are not accepted for formal training.

| Dataset | Official URL | License | RGB Video | ADL Subtypes | Size / Count | Phase 6C Decision |
| --- | --- | --- | --- | --- | --- | --- |
| UR Fall Detection Dataset | https://fenix.ur.edu.pl/~mkepski/ds/uf.html | CC BY-NC-SA 4.0 | Yes | Fall / ADL only, subtype needs manual review | 30 fall + 40 ADL | Use full dataset as smoke + baseline; not commercial |
| GMDCSA-24 | https://github.com/ekramalam/GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos | Open dataset via GitHub/Zenodo; repo lists MIT license | Yes | Descriptive ADL/fall activities in paper tables | 81 fall + 79 ADL | Preferred public ADL subtype augmentation if download succeeds |
| Multiple Cameras Fall Dataset | https://www-labs.iro.umontreal.ca/~labimage/Dataset/ | Not confirmed in current pass | Yes | Confounding events, subtype detail unclear | 24 scenarios x 8 cameras | Candidate only until license/download are confirmed |
| UP-Fall Detection Dataset | https://pmc.ncbi.nlm.nih.gov/articles/PMC6539235/ | Research dataset; license/download to verify | Yes, plus sensors | 11 activities, multimodal | >850 GB | Long-term candidate only; avoid full download in Phase 6C |
| Le2i | No stable official direct video source found in current pass | Not confirmed | Yes in original dataset, but mirrors vary | ADL/fall, subtype unclear | Varies | Exclude from formal training until official/license-clear video source is confirmed |
| Local ADL supplement | Local project capture | Project-owned | Yes | Full subtype control | 5-10 clips per subtype | Recommended when public data lacks sitting/bending/squatting/picking/lying examples |

## Current Decision

Use UR Fall full RGB cam0 as the automatic baseline expansion. Add GMDCSA-24 as the preferred public subtype candidate because it has RGB videos and published ADL/fall descriptions. If GMDCSA download cannot be completed reliably, record local ADL subtype clips before training v2.

## Required ADL Subtypes

```text
standing
walking
sitting
bending
squatting
picking_object
lying_down_normal
unknown_adl
```

`unknown_adl` is allowed only as a temporary fallback and must not dominate the negative training windows.
