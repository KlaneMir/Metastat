---
name: Meta Connector
description: Personal Meta data panel; posts read as frames on a contact sheet.
colors:
  paper: "#F4F4F2"
  sheet: "#FFFFFF"
  ink: "#141414"
  ink-muted: "#4A4A46"
  rule: "#D6D6D0"
  field-stroke: "#BDBDB8"
  film: "#141414"
  film-raised: "#26261F"
  film-ink: "#EDEDE8"
  film-ink-muted: "#A8A69E"
  edge-amber: "#E39B2D"
  grease-red: "#D7372F"
  error-red: "#B8281F"
  up-green: "#2E7D4F"
  warning-brown: "#8A5A10"
  seam: "#2E2E29"
typography:
  title:
    fontFamily: "Segoe UI, system-ui, -apple-system, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 700
    lineHeight: 1.45
  body:
    fontFamily: "Segoe UI, system-ui, -apple-system, Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  table:
    fontFamily: "Segoe UI, system-ui, -apple-system, Roboto, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Segoe UI, system-ui, -apple-system, Roboto, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.45
  figure:
    fontFamily: "Cascadia Mono, Cascadia Code, Consolas, monospace"
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.2
    fontFeature: "tnum"
  data:
    fontFamily: "Cascadia Mono, Cascadia Code, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.2
    fontFeature: "tnum"
  edge-print:
    fontFamily: "Cascadia Mono, Cascadia Code, Consolas, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.06em"
rounded:
  none: "0px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  strip-gap: "18px"
  page-x: "32px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.none}"
    padding: "0 16px"
    height: "36px"
  button-secondary:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "0 16px"
    height: "36px"
  input:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "0 10px"
    height: "36px"
  segment-on:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.none}"
    padding: "0 12px"
  frame:
    backgroundColor: "{colors.film}"
    textColor: "{colors.film-ink}"
    typography: "{typography.data}"
    padding: "9px 10px 12px"
  table-header:
    backgroundColor: "{colors.film}"
    textColor: "{colors.film-ink}"
    padding: "9px 12px"
---

# Design System: Meta Connector

## Overview

**Creative North Star: "The Contact Sheet"**

The panel is a photographer's contact sheet laid over a working data tool. Paper holds the controls and the figures; black film carries the posts. Each post is a numbered frame with its date and type in amber edge print, its numbers printed underneath, and the strongest frame circled in red grease pencil. Everything else is a plain, dense, standard tool: native selects, date inputs, segmented toggles, a sortable table.

Density is high and calm. One row of controls, one row of totals, then the sheet. Colour does jobs: black for film and primary actions, amber for frame codes and the views ramp, red only for the pencil mark and errors.

**Key Characteristics:**
- Paper ground, black film strips, square corners everywhere.
- Every figure in tabular mono, grouped in threes including four-digit numbers.
- One signature move: the grease-pencil circle that draws itself around the top frame.
- Standard controls only; the world never supplies navigation or control shapes.

## Colors

Restrained: tinted neutrals of paper and film, plus two working accents taken from film stock and the darkroom.

### Primary
- **Film Black** (film / ink): film strips, the header bar, table headers, primary buttons and the selected segment. Also the body text colour on paper.

### Secondary
- **Edge-Print Amber** (edge-amber): frame numbers, dates and types on the film edge, the views ramp under each frame, the token-valid dot, sort arrows on film. Only on film or as a fill; never as text on paper, where it fails contrast.

### Tertiary
- **Grease-Pencil Red** (grease-red): the circle around the top frame and the invalid-token dot. Nothing else.

### Neutral
- **Print Paper** (paper): page ground, table footer.
- **Sheet White** (sheet): the query row, token panel, inputs, table body.
- **Ink Muted** (ink-muted): labels and secondary text on paper.
- **Rule** (rule) and **Field Stroke** (field-stroke): 1px dividers and control borders.
- **Film Raised** (film-raised): image placeholders and the ramp track on film.
- **Film Ink** / **Film Ink Muted**: text on film; muted for captions and metric icons.
- **Error Red** (error-red): error text on paper (red that passes 4.5:1, unlike the pencil red). Also every decrease against the previous period.
- **Ledger Green** (up-green): every increase against the previous period and a successful sync. Paired only with Error Red for change; never decorative.
- **Warning Brown** (warning-brown): a sync that finished with some campaigns failing. Readable amber for text on paper.
- **Seam** (seam): the 1px line between abutting frames on a strip.

### Change colours
Green up, red down, "–" for no data (a requirement of the reports). Zero change shows "±0" in ink. A percentage appears only when it rounds to at least 1%.

### Named Rules
**The Darkroom Rule.** Amber and pencil red live on film. On paper, emphasis is black weight, and errors use Error Red.
**The One Circle Rule.** Exactly one frame gets the pencil circle: the leader for the active sort metric, or views when sorted by date.

## Typography

**Body Font:** Segoe UI (with system-ui, -apple-system, Roboto)
**Label/Mono Font:** Cascadia Mono (with Consolas, monospace)

**Character:** A plain workhorse sans for words and a tabular mono for every number, code and date, the way a contact sheet separates handwriting from machine edge print.

### Hierarchy
- **Title** (700, 15px): the product name in the header and section headings such as "Posts".
- **Figure** (mono 600, 22px, 1.2): totals row.
- **Body** (400, 14px, 1.45): controls, status line, table cells (13px in tables).
- **Label** (400, 12px): field labels above controls, totals labels, captions on film.
- **Data** (mono 400, 12px, tabular): metrics inside frames, dates in tables.
- **Edge print** (mono 400, 11px, 0.06em, uppercase): the frame code line.

### Named Rules
**The Machine Numbers Rule.** Numbers, dates and IDs are always mono with tabular figures and en-GB grouping, so columns align.

## Layout

Full-width page with 32px side gutters (16px under 720px). Header bar 52px. The query row is a single wrapping flex row of labelled controls with 10px gaps; on a 1440px screen it fits on one line with "Export CSV" pushed to the right. The totals row sits between a 1px ink rule above and a 1px rule below. The sheet is a grid of frames at minimum 210px wide with no column gap, so each row reads as one continuous strip; an 18px row gap of paper separates strips. Tables scroll inside a bordered container capped at 70vh with a sticky header and sticky totals footer.

## Elevation & Depth

Flat. Depth comes from paper versus film, not shadows. The only shadow is the metrics dropdown menu (`0 8px 24px rgba(20,20,20,.14)`), because it floats over content.

## Shapes

Square corners everywhere (0px). 1px borders and rules only. Frames abut within a strip, separated by a 1px #2E2E29 seam. Post images are 4:5 and cropped to fill.

## Components

### Buttons
- **Shape:** square (0px), 36px tall.
- **Primary:** Film Black fill, white 600 text ("Fetch", "Save and check"). Hover lightens to #333.
- **Secondary:** white with a 1px ink border ("Export CSV", "Remove token"). Hover fills with paper.
- **On film:** transparent with a 1px #55554F border ("Token").
- **Disabled:** 40% opacity.

### Inputs / Fields
- **Style:** white, 1px field-stroke border, square, 36px; select chevron is a drawn SVG. Date inputs use the mono face.
- **Focus:** 2px ink outline offset 2px on paper, amber on film.

### Segmented toggles
- Joined square buttons sharing borders; the pressed one inverts to ink with white text. Used for date presets and Contact sheet/Table.

### Navigation
- A single black header bar: product name, subtitle, token state with a coloured square dot, and the Token button. No other navigation.

### Frame (signature)
- Film-black cell: edge-print line (frame number in bold, date and time, type), the 4:5 image linking to the post, a two-line caption, a two-column grid of metric icons and figures, and a 3px amber views ramp on a shared scale. The top frame gets a hand-drawn red ellipse that draws on in 0.9s (`cubic-bezier(.16,1,.3,1)`), only when the leader changes; reduced motion shows it static. An expired or missing image shows "No preview" / "Preview expired…" in muted film ink.

### Data table
- Black sticky header with sortable header buttons and an amber chevron for the active sort; white body with 1px row rules (13px Table type); paper footer with "Total".
- **Campaign summary** (Metastat dashboard): one row per campaign × platform, campaign cell spans its FB and IG rows, platform as a mono code (FB / IG). Each figure carries its change against the previous period on a second mono line in Ledger Green / Error Red. Flags show as a red square with "N to review" under the campaign name.

### Chart panel
- Charts sit on film, never on paper: a black panel, 1px #33332C gridlines, mono 11px axis labels in Film Ink Muted. Series: Edge-Print Amber for the subject (this post, Instagram), Film Ink for Facebook followers, dashed Film Ink Muted for the typical/median curve. SVG drawn server-side, aspect preserved, the top tick always above the maximum.

### Metric tiles (post view)
- The Business Suite overview translated into the world: a row of mono 26px figures between a 1px ink rule and a 1px rule (Views, Viewers/Reach, Interactions, Link clicks/Saves, Reactions, Comments, Shares). No cards.

### Post preview
- White sheet with profile name, platform and time, full text with colour emoji, the 800 px image and a mono metric footer. No platform logos.

### Test-data banner
- A full-width Edge-Print Amber strip with ink text under the header whenever the program runs on generated data. It is the only amber fill on paper.

## Do's and Don'ts

### Do:
- **Do** keep every number in the Data or Figure mono with tabular figures and always-on grouping.
- **Do** keep states in place: the status line holds loading, success and error text; no toasts.
- **Do** draw icons as 16px SVG strokes (1.6 width) from the sprite.

### Don't:
- **Don't** add perforations, sprocket holes, film grain or any other film costume; the strip is flat black.
- **Don't** use amber or grease red for text on paper.
- **Don't** round corners or add card shadows to frames, controls or tables.
- **Don't** use emoji or Unicode glyphs as icons.
