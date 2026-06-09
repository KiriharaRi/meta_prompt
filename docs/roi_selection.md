# ROI Selection for the Friends Multi-ROI Pilot

## Goal

The Friends multi-ROI pilot now uses Brainnetome 246 subregions as the ROI
selection space. The active ROI set follows the user-provided high-level
cognition CSV and intentionally keeps overlapping ROIs because redundant target
signals may improve prediction.

## Active ROI Set

The pilot keeps all 14 CSV ROIs:

1. `DLPFC` - working memory, cognitive control, and goal-directed behavior.
2. `VMPFC` - valuation, emotion regulation, and self-referential processing.
3. `OFC` - reward learning, outcome expectation, and stimulus-value coding.
4. `ACC` - conflict monitoring, error detection, motivation, and emotion
   integration.
5. `PCC` - default-network integration, episodic memory, and self-related
   context.
6. `Precuneus` - self-awareness, episodic retrieval, and visuospatial imagery.
7. `IPL` - multisensory integration, attention reorienting, and spatial or
   symbolic cognition.
8. `SMG` - phonological working memory, action observation, and somatosensory
   integration.
9. `AG` - semantic integration, reading, numerical cognition, and theory of
   mind.
10. `TPJ` - theory of mind, attention switching, and social prediction-error
    monitoring.
11. `pSTS` - biological motion, intention inference, and gaze/action
    interpretation.
12. `FFA` - face recognition and expert-like visual identity processing.
13. `Insula` - interoception, emotion awareness, risk decisions, and pain
    empathy.
14. `Temporal_Pole` - semantic memory, social concepts, and autobiographical
    meaning.

## Atlas Contract

Selection rules use Brainnetome 1-based `Label` ids from
`atlas/subregion_func_network_Yeo_updated.csv`. The Yeo columns are retained in
parcel metadata for interpretation, but the ROI definitions use exact label ids
as the primary selector so every configured ROI resolves to at least one parcel.

The expected fMRI target file for encoding is a Brainnetome246 H5 with datasets
shaped `TR x 246` and columns ordered by the same Brainnetome label table.

## Grouping

This round does not define a primary ROI network or secondary/control ROIs.
Encoding reports the overall multi-ROI model plus per-ROI summaries. Overlap
between ROIs is allowed and is handled by the existing multi-ROI target
de-duplication and `roi_memberships` metadata.

## Reporting Rules

- Report overall multi-ROI encoding performance from `group_summary.json`.
- Report single-ROI summaries to show which Brainnetome-derived ROI targets are
  best predicted.
- Do not remove ROIs solely because their Brainnetome labels overlap with a
  broader ROI in this round.
