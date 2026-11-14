---
name: Metastat
description: Local Facebook and Instagram statistics for an agency running many campaigns, dressed as a missing tab of Meta Business Suite.
colors:
  bg: "#F0F2F5"
  card: "#FFFFFF"
  hover: "#F2F3F5"
  row: "#F7F8FA"
  text: "#1C1E21"
  text-2: "#65676B"
  icon: "#606770"
  line: "#E4E6EB"
  line-2: "#CED0D4"
  field: "#CCD0D5"
  control-hover: "#D8DADF"
  chart-gray: "#8A8D91"
  blue: "#0866FF"
  blue-hover: "#0757D9"
  blue-ink: "#0058D6"
  blue-tint: "#EBF3FF"
  blue-soft: "#DCE9FF"
  ig: "#D62976"
  ig-tint: "#FCE8F1"
  up: "#1A7F37"
  meta-green: "#31A24C"
  ok-bg: "#E6F4EA"
  down: "#E41E3F"
  down-ink: "#C4122F"
  err-bg: "#FFEBEE"
  warn: "#8A5A00"
  warn-bg: "#FFF4D6"
typography:
  display:
    fontFamily: "Segoe UI, system-ui, -apple-system, Helvetica, Arial, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.2
    fontFeature: "tnum"
  headline:
    fontFamily: "Segoe UI, system-ui, -apple-system, Helvetica, Arial, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.25
  title:
    fontFamily: "Segoe UI, system-ui, -apple-system, Helvetica, Arial, sans-serif"
    fontSize: "17px"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: "Segoe UI, system-ui, -apple-system, Helvetica, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.4
    fontFeature: "tnum"
  body-small:
    fontFamily: "Segoe UI, system-ui, -apple-system, Helvetica, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.4
  label:
    fontFamily: "Segoe UI, system-ui, -apple-system, Helvetica, Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.4
  caption:
    fontFamily: "Segoe UI, system-ui, -apple-system, Helvetica, Arial, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.4
  mono:
    fontFamily: "Cascadia Mono, Consolas, monospace"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
rounded:
  xs: "4px"
  sm: "6px"
  md: "8px"
  badge: "11px"
  pill: "16px"
  full: "50%"
spacing:
  xxs: "4px"
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  xxl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.card}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "36px"
  button-primary-hover:
    backgroundColor: "{colors.blue-hover}"
  button-secondary:
    backgroundColor: "{colors.line}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "36px"
  button-secondary-hover:
    backgroundColor: "{colors.control-hover}"
  button-soft:
    backgroundColor: "{colors.blue-tint}"
    textColor: "{colors.blue-ink}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "36px"
  button-soft-hover:
    backgroundColor: "{colors.blue-soft}"
  button-danger:
    backgroundColor: "{colors.err-bg}"
    textColor: "{colors.down-ink}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "36px"
  button-small:
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "32px"
  input:
    backgroundColor: "{colors.card}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "0 10px"
    height: "36px"
  pill:
    backgroundColor: "{colors.line}"
    textColor: "{colors.text}"
    typography: "{typography.body-small}"
    rounded: "{rounded.pill}"
    padding: "0 12px"
    height: "32px"
  pill-active:
    backgroundColor: "{colors.blue-tint}"
    textColor: "{colors.blue-ink}"
  badge:
    backgroundColor: "{colors.line}"
    textColor: "{colors.text}"
    typography: "{typography.caption}"
    rounded: "{rounded.badge}"
    padding: "0 8px"
    height: "22px"
  badge-test:
    backgroundColor: "{colors.warn-bg}"
    textColor: "{colors.warn}"
  badge-ok:
    backgroundColor: "{colors.ok-bg}"
    textColor: "{colors.up}"
  badge-bad:
    backgroundColor: "{colors.err-bg}"
    textColor: "{colors.down-ink}"
  card:
    backgroundColor: "{colors.card}"
    rounded: "{rounded.md}"
    padding: "16px 16px 18px"
  nav-item:
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "44px"
  nav-item-active:
    backgroundColor: "{colors.blue-tint}"
    textColor: "{colors.blue-ink}"
  top-bar:
    backgroundColor: "{colors.card}"
    padding: "0 16px"
    height: "56px"
  top-post-pill:
    backgroundColor: "{colors.card}"
    textColor: "{colors.blue-ink}"
    typography: "{typography.caption}"
    rounded: "{rounded.badge}"
    padding: "3px 8px"
  views-bar:
    backgroundColor: "{colors.line}"
    rounded: "3px"
    height: "6px"
  test-banner:
    backgroundColor: "{colors.warn-bg}"
    textColor: "#5C3D00"
    rounded: "{rounded.md}"
    padding: "10px 16px"
---

# Design System: Metastat

## Overview

**Creative North Star: "The Missing Business Suite Tab"**

Metastat is built to look like a tab Meta forgot to ship. The person using it spends the working day in Meta Business Suite, so the app reuses that product's materials: a cool gray ground, white cards with 8px corners and a hairline shadow, Meta blue for anything you can act on or have selected, Instagram magenta only where an Instagram series is drawn. The point is that nothing needs learning. It is not a custom "analytics product" look, and it drops the old black contact-sheet styling entirely.

The app is an operator's tool and the density follows from that. It uses a 56px top bar, a 240px left rail and a main column that holds tables with ten numeric columns, metric tiles and grids of post cards. Type is the Windows system face at 15px, and every figure uses tabular numerals so columns of counts line up. Colour carries meaning, not decoration: green and red appear only on change figures and states, amber only on anything that labels test or demo data.

One addition goes beyond the borrowed world, and it is the system's signature. Every post card has a views bar under its image, and all bars in a list share one scale. The most-viewed post also gets a white "Most views" pill on its image. Business Suite never shows posts side by side like this. Metastat does.

**Key Characteristics:**
- Gray ground (#F0F2F5), white 8px cards, a 1px soft shadow, and no borders on cards.
- Meta blue marks action, selection and Facebook data. Magenta marks Instagram data only.
- Segoe UI stack throughout, tabular figures everywhere, weights 400/600/700.
- Pill tabs for periods and filters, gray secondary buttons, and a left rail with a blue-tinted active item.
- Posts compare on one shared-scale views bar under each image.
- Test and demo data always carry an amber label.

## Colors

The palette is Meta's product palette, with a few contrast fixes: neutral grays for structure, one action blue, one platform magenta, and semantic green, red and amber kept to small areas.

### Primary
- **Meta Blue** (blue): primary buttons, focus rings, the selected-row icon in the rail, the "running" sync dot, Facebook chart series, Facebook views bars and avatars, and the paid segment of the organic/paid bar.
- **Blue Ink** (blue-ink): blue used as text. Use it for links, active pill and active rail labels, the top-post pill and soft-button labels. It is a shade darker than Meta Blue so small text stays readable on tint.
- **Blue Tint / Blue Soft** (blue-tint, blue-soft): background of a selected pill, the active rail item, soft buttons, the "Meta" badge, and text selection. Soft is the hover step of tint.
- **Blue Hover** (blue-hover): pressed or hover state of the primary button only.

### Secondary
- **Instagram Magenta** (ig): Instagram series, views bars, avatars and the IG brand mark. It is a platform colour, never an action colour.

### Tertiary (semantic)
- **Up Green** (up): positive change text, the "ok" sync status and ok badges. It replaces Meta's green for text because Meta's green is only about 3.3:1 on white at 12–13px.
- **Meta Green** (meta-green): non-text marks only. Use it for the ok status dot, the ok notice icon and the organic segment of the organic/paid bar.
- **Down Red / Down Ink** (down, down-ink): down is for negative change figures, the failed-sync dot and failed status. Down Ink is red text on a red tint (danger button, error notice, bad badge, "to check" flags).
- **Warning Amber** (warn, warn-bg): the test-account and demo banners, the "Test account" badge and partial sync status.
- **Tints** (ok-bg, err-bg, ig-tint): quiet fills behind semantic badges and notices.

### Neutral
- **Business Suite Gray** (bg): app ground behind every card. It is also the fill of the by-type chips and inline code.
- **Card White** (card): cards, top bar, left rail, inputs, sticky table headers.
- **Ink** (text): headings, figures and body text.
- **Secondary Gray** (text-2): labels, column headers, sub-lines, notes and chart axis labels.
- **Icon Gray** (icon): stroke icons at rest, plus the select chevron.
- **Divider** (line): table rules, rail border, empty bar tracks and image placeholders. The same gray is the fill of secondary buttons, pills and neutral badges.
- **Strong Divider** (line-2): group separators between campaigns in a table, totals rule, the idle sync dot.
- **Field Border** (field): input stroke.
- **Control Hover** (control-hover): hover fill of gray buttons and pills.
- **Hover / Row** (hover, row): rail item hover, on-card pill hover, table row hover, totals row and log box fill.
- **Chart Gray** (chart-gray): the dashed "typical post" comparison line and its legend swatch.

### Named Rules
**The Blue Means Act Rule.** Meta Blue is for action, selection, focus and Facebook data. Don't use it for decoration, headings or illustrative fills.

**The Platform Colour Rule.** Facebook is always blue and Instagram is always magenta: charts, views bars, avatars, brand marks. A series takes its platform's colour, and the neutral comparison series is dashed Chart Gray.

**The Green For Text Rule.** Use Up Green when green is text. Meta Green is allowed only on dots, icons and bar segments, where 3:1 is the bar.

**The Labelled Test Data Rule.** Anything built on test-account or demo data is labelled in amber: a banner at the top of the main column and a "Test account" badge next to the connection switcher.

## Typography

**Display Font:** Segoe UI (with system-ui, -apple-system, Helvetica, Arial)
**Body Font:** the same stack
**Label/Mono Font:** Cascadia Mono (with Consolas), only for tokens, IDs, paths and sync logs

**Character:** One system face, the one Meta's own UI uses on Windows. Hierarchy comes from size and weight steps (400/600/700), not from a second family. Tabular numerals are set on the body, so every count, date and delta lines up.

### Hierarchy
- **Display** (700, 24px, 1.2): the large figures in metric tiles. It drops to 20px below 640px.
- **Headline** (700, 22px, 1.25): the page title (h1) in the head row. Empty-state titles are 20px.
- **Title** (700, 17px, 1.3): card and section titles (h2), and the brand word in the top bar. h3 is 15px/600.
- **Body** (400, 15px, 1.4): default text, rail items (600), buttons (600), post preview text.
- **Body Small** (400, 14px): table cells, notices, pill labels (600), post card text, crumbs.
- **Label** (600, 13px): column headers, metric tile labels, form field labels, sub-lines and notes (400), legends.
- **Caption** (600, 12px): badges, delta lines under table figures, the top-post pill (700), the page footer (400).

### Named Rules
**The Tabular Figures Rule.** Every number uses tabular numerals and is right-aligned in tables. Show stored numbers exactly: comma-grouped thousands (10,896), a decimal point, a true minus sign (−), and an en dash (–) for missing data.

**The Three Weights Rule.** Use 400 for reading, 600 for labels and controls, and 700 for titles and figures. Don't use other weights.

## Layout

The shell is fixed: a sticky 56px white top bar (brand, connection switcher, sync state, Sync), then a two-column grid with a 240px sticky left rail and a main column (padding 20px 24px 48px, max 1480px). Every page opens with a head row: the h1, an optional muted sub-line, and right-aligned controls. On data pages that is the period bar: preset pills, two date inputs, "Show", and a full-width right-aligned comparison line under them.

Content is a stack of cards with 16px gaps. Paired cards use a two-column auto-fit grid (min 440px). Metric tiles auto-fill at a 120px minimum. Post cards auto-fill at 230px with 12px gaps. The post page uses a 380px sticky preview column next to the stats. Spacing steps are 4, 6, 8, 12, 16, 20 and 24px. Card padding is 16px. Table cells are 10px by 12px.

Responsive behaviour:
- **≤1100px:** the post page stacks, and the preview loses its sticky position and caps at 520px.
- **≤900px:** the rail becomes a horizontal scrolling strip under the top bar with no footer, the brand word hides, paired cards stack, and main padding drops to 16px.
- **≤640px:** the rail becomes four equal icon-over-label tabs (52px, 11px labels). The sync text, the long "Sync" label and the connection kind badge hide. Post cards drop to two columns with 8px gaps, and metric figures shrink to 20px.

## Elevation & Depth

Depth is Meta's: almost flat. White surfaces sit on the gray ground with one hairline shadow. Nothing floats except on hover. Notices of the error kind drop the shadow and rely on their tint.

### Shadow Vocabulary
- **Card hairline** (`box-shadow: 0 1px 2px rgba(0,0,0,.1)`): cards, the top bar, notices, post cards at rest, the top-post pill.
- **Card lift** (`box-shadow: 0 2px 12px rgba(0,0,0,.12)`): post card hover only. Transition 0.2s cubic-bezier(.16,1,.3,1).

### Named Rules
**The One Hairline Rule.** A surface gets the 1px hairline shadow or nothing. Cards don't get borders. Lift is a hover response on clickable cards, never a resting state.

## Shapes

Corners are soft and consistent: 8px for cards, rail items, metric tiles, notices and the test banner. Buttons, inputs and the log box use 6px. Thumbnails and inline code use 4px. Pills are fully rounded (16px on 32px height), badges 11px on 22px, avatars and status dots are circles. The Instagram mark and the IG avatar badge use a rounded square. Post images are 1:1 crops with object-fit cover. Progress bars (views bar 6px, organic/paid bar 10px) are fully rounded tracks in Divider gray. Dividers are 1px solid lines. Icons are 16px (20px in the rail and notices) line icons with a 1.7 stroke and round caps, served from one inline sprite.

## Components

### Buttons
Gray by default and blue when it matters, just like Business Suite.
- **Shape:** gently rounded (6px), 36px tall, 14px side padding, 15px/600 label, optional 16px leading icon with an 8px gap.
- **Primary:** Meta Blue with white text. Keep it to one per area (Sync, Save, Add Meta token). Hover is Blue Hover.
- **Secondary (default):** Divider gray fill with Ink text. Hover is Control Hover.
- **Soft:** Blue Tint fill with Blue Ink text, for gentle calls such as "Add connection".
- **Danger:** red tint with Down Ink text, for removing a connection.
- **Small:** 32px tall, 12px padding, 14px text. Use it in the top bar, the period bar and tables. Icon-only buttons are 32px square.
- **Disabled:** 45% opacity, no hover change, and always with a title that says why.
- **Focus:** a 2px Meta Blue outline offset 2px on every focusable element.

### Chips (pills and badges)
- **Pills:** 32px, fully rounded, gray fill, 14px/600. The selected pill is Blue Tint with Blue Ink. On a card the unselected pills go transparent with a Hover-gray hover. Use them for period presets and the platform and view toggles.
- **Badges:** 22px, 12px/600, rounded 11px. Variants are neutral gray (campaign label), blue ("Meta"), amber ("Test account"), green ok, red bad, and a muted ground-gray "ended".
- **By-type chips:** ground-gray rounded spans with a bold count, on the post page.

### Cards / Containers
- **Corner Style:** 8px.
- **Background:** Card White on the Business Suite Gray ground.
- **Shadow Strategy:** the card hairline (see Elevation).
- **Border:** none.
- **Internal Padding:** 16px (18px bottom). The header row is title + muted sub-line + right-aligned controls, 14px above the content. Flush cards hold edge-to-edge tables, and only the header keeps 16px padding.

### Inputs / Fields
- **Style:** 36px (32px inside the period bar), white, 1px Field Border, 6px radius, 10px padding. Selects use a custom gray chevron. Textareas switch to 13px mono.
- **Hover:** the border darkens to #B0B3B8.
- **Focus:** 2px Meta Blue outline at 0 offset, and the border turns blue.
- **Labels:** 13px/600 stacked above the field with a 6px gap. Hints are 400 Secondary Gray.

### Navigation
- **Top bar:** white, 56px, hairline shadow. It holds the blue round bar-chart logo with "Metastat" (17px/700), the connection switcher select with its kind badge, and on the right the status dot (gray idle, green ok, red failed, pulsing blue running), last-sync text and the small primary Sync button.
- **Left rail:** white, 1px Divider on the right. Items are 44px, 8px radius, 15px/600 Ink with 20px Icon Gray icons, and the hover is Hover gray. The active item is Blue Tint with Blue Ink text and a Meta Blue icon. The footer shows the active connection name and campaign count above a Divider.
- **Mobile:** see Layout. The rail becomes a strip, then a four-tab bar.

### Tables
Right-aligned numeric columns with sticky white headers (13px/600 Secondary Gray). Rows are separated by 1px Divider, hover is Row gray, and campaign groups get a Strong Divider on top. Each figure carries its delta as a 12px/600 line underneath, green or red by direction. The totals row is bold on Row gray. Platform cells use the small FB/IG brand mark plus the name.

### Metric tiles
A label (13px/600 Secondary Gray, ellipsis) over a 24px/700 figure, with an optional 13px/600 change line. They sit in an auto-fill grid inside a platform card whose title carries the FB or IG mark.

### Notices and the test banner
A notice is a white hairline card with a 20px icon (Meta Green for ok, blue for info). An error notice is red tint, unshadowed, with a Down Ink icon. The test/demo banner is amber tint with dark amber text, an alert icon and a bold lead sentence. It sits at the top of the main column on every page while test or demo data is active.

### Post card (signature)
A clickable white card (8px, hairline, overflow clipped) that lifts to the card-lift shadow on hover. Layout:
- a header with a 36px platform-coloured initial avatar carrying a small FB/IG mark at its corner, the campaign name (14px/700) and "Facebook/Instagram · date" (12px)
- two lines of post text (14px)
- a 1:1 image, or a "No image" placeholder on Divider gray
- the views bar: eye icon, the views figure (14px/700), and a 6px rounded track filled in the platform colour
- a three-column row of reactions, comments and shares (13px, icon plus figure)

**The Shared Scale Rule.** Every views bar in one list is scaled against the largest views figure in that list, so bar length compares posts directly. Fill width animates over 0.5s. Never scale a bar on its own.

**The Top Post Rule.** Only the first, most-viewed card in a ranked list gets the "Most views" pill: white, Blue Ink, 12px/700, rounded, hairline shadow, 8px from the image's top-left corner.

### Charts
Server-rendered inline SVG. The grid is 1px Divider lines, axis labels are 12px Secondary Gray, and series are 2.5px round-joined lines with 3px point dots. The primary series takes the platform colour (magenta by default, blue inside a Facebook context). The comparison series ("typical post", median) is dashed 5/5 Chart Gray. Legends use a 16×3px swatch, dashed for the comparison.

## Do's and Don'ts

### Do:
- **Do** put every page on the gray ground (#F0F2F5), with content in white 8px cards carrying the 1px hairline shadow.
- **Do** use Meta Blue (#0866FF) for the one primary action per area, for selection and for Facebook data. Use Blue Ink (#0058D6) when the blue is text.
- **Do** colour every series, bar and avatar by platform: Facebook blue, Instagram magenta (#D62976).
- **Do** use Up Green (#1A7F37) for positive change text and Down Red (#E41E3F) for negative. Use Down Ink (#C4122F) for red text on a red tint.
- **Do** label test-account and demo data with the amber banner and the "Test account" badge on every screen that shows it.
- **Do** scale all views bars in a list against the list's maximum, and mark only the top post with "Most views".
- **Do** set figures in tabular numerals, right-aligned in tables, with the period delta on a 12px line beneath.
- **Do** use the line icons from the inline sprite at 16px or 20px, 1.7 stroke, coloured by currentColor.

### Don't:
- **Don't** give the app a custom "analytics product" look or bring back the black contact-sheet, amber edge-print styling of the old panel. The root of this system is Meta Business Suite.
- **Don't** put borders on cards or stack shadows. Use the hairline, or the lift on hover for clickable cards only.
- **Don't** use Meta's #31A24C for text. It is for dots, icons and bar segments only.
- **Don't** use magenta for actions or blue for Instagram data.
- **Don't** add a second typeface or weights other than 400/600/700. Mono is only for tokens, IDs, paths and logs.
- **Don't** show simulated or demo numbers without the amber label.
