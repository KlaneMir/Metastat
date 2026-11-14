# A home-made "Supermetrics" for Looker Studio

An Apps Script project with two parts:
- a **Looker Studio connector** (`Code.gs` + `appsscript.json`),
- a **panel** (`Index.html`): a web page where you check the token, browse the data and posts with their images, and export CSV.

Both parts use the same token and the same data-fetching functions.

## What comes from where

| Source | How to connect |
|---|---|
| Google Ads | Built-in Looker Studio connector "Google Ads" |
| GA4 | Built-in connector "Google Analytics" |
| Search Console | Built-in connector "Search Console" |
| Meta Ads | This connector, **Meta Ads (campaigns, daily)** |
| FB page, daily totals | **Facebook page (daily)** |
| FB posts | **Facebook posts**: one row per post |
| Instagram, daily totals | **Instagram (daily)** |
| IG posts | **Instagram posts**: one row per post |

### What the post sources contain

Each row is one post: publication date and time, type (photo, video, carousel, reel), text, a link to the post and the **image** (an Image-type field in Looker Studio).

- **FB posts:** views, reactions (all), likes, comments, shares.
- **IG posts:** views, reach, likes, comments, shares, saves.

The publication time is calculated in the Apps Script project's time zone (Europe/Warsaw).

## 1. Meta token (one-time setup)

1. On developers.facebook.com, create an app of type **Business**.
2. In Business Settings → Users → **System users**, add a user (Admin role).
3. Assign assets to it: the ad account, the page and the Instagram account.
4. **Generate a token** for your app, with expiration set to *Never*. Permissions:
   `ads_read`, `read_insights`, `pages_show_list`, `pages_read_engagement`, `pages_read_user_content`, `instagram_basic`, `instagram_manage_insights`, `business_management`.
5. Keep the token. You will paste it into the panel, or into Looker Studio as the "key".

## 2. Apps Script project

1. Go to script.google.com and create a **New project**.
2. Paste `Code.gs` into the `Code.gs` file.
3. **Files + → HTML**, name it `Index` and paste in the contents of `Index.html`.
4. In Project Settings, tick **Show "appsscript.json" manifest file in editor** and paste in `appsscript.json`.

## 3. Panel

1. **Deploy → New deployment → Web app**.
2. Execute as: **Me**. Who has access: **Only myself**.
3. Open the URL shown after deployment and paste in the token. The panel loads the list of your ad accounts, pages and IG profiles on its own, so you don't have to copy IDs by hand.

In the panel:
- **Posts** are shown as a **Contact sheet**: each post is a frame with a number, date, image and figures. The top post for the selected sort order is circled. The **Table** toggle switches to a table view.
- **Metrics** can be switched on and off without fetching the data again.
- **Export CSV** saves a file suited to Excel with Polish regional settings: semicolon separator, decimal comma, UTF-8 encoding.

After every code change, go to **Deploy → Manage deployments → Edit → New version**, otherwise the panel keeps serving the old version.

## 4. Connector in Looker Studio

1. **Deploy → Test deployments** and copy the **Head deployment ID**.
2. In Looker Studio: **Create → Data source → Build your own** and paste in the ID.
3. Authorize, paste the token (or save it in the panel first, it is the same token), choose the source and enter the ID.
4. For posts, add a table with the **Image** field. Looker shows thumbnails.

Each source is a separate dataset. Combined reports with Google Ads or GA4 can be built with **Blend data** on the *Date* field.

## Where to find IDs (if you don't pick them from the list in the panel)

- **Ad account:** the `act=…` parameter in the Ads Manager URL.
- **Page:** Page → About → Page transparency.
- **Instagram:** Graph API Explorer, `me/accounts?fields=instagram_business_account` (a number, not the username).

## Good to know

- **Image links expire.** Meta serves thumbnail URLs that are valid only for a limited time. In Looker Studio and in the panel they are refreshed on every fetch, but links in an old CSV file stop working after a few days.
- **IG followers** is today's count: Meta does not provide follower-count history further back than 30 days. On Facebook, daily history comes from **Followers (total)** in the page source.
- **FB post views** come from the `post_media_view` metric, or from `post_impressions` if the API does not recognise the former. If Meta returns neither, the field is empty.
- **Reach** summed over days or posts is not unique reach. It gives an upper bound.
- **Spend** is in the ad account's currency.
- Add CTR, CPC and CPM in Looker Studio as calculated fields, e.g. `SUM(Link clicks)/SUM(Ad impressions)`.
- Meta changes its metrics often. The metric lists are at the top of `Code.gs`. A metric the API no longer recognises is skipped and does not break the whole report.
- The Graph API version (`v23.0`) is also at the top of that file. When Meta retires it, bump the number.
- Large accounts and long date ranges can exceed the Apps Script execution time limit (about 6 minutes). If that happens, shorten the range. For posts, every post needs a separate insights request, so a few hundred posts at once can take up to a minute.

## Security

- **Token in the header only.** Every request sends the token in the `Authorization` header, never in the URL, because URLs end up in logs and error messages. Paging links (`paging.next`) pointing outside `graph.facebook.com` are rejected, and `access_token` is stripped from them.
- **A shared report does not leak the token.** Error messages visible to report viewers contain no tokens, and technical details are disabled (`isAdminUser`).
- **Narrow permissions.** The project requests only the `script.external_request` scope, and `urlFetchWhitelist` allows connections to `graph.facebook.com` only. The token is stored in user properties (`UserProperties`), and the panel runs with access set to "Only myself".
- **CSV export from the panel** is protected against formula injection (`=`, `+`, `-`, `@` at the start of a cell).

## Tests

The connector and the panel are tested with Node's built-in test runner (Node 18+, no packages to install). The tests run `Code.gs` and the panel script from `Index.html` with small stand-ins for the Google services and the page:

```bash
node --test meta-connector/tests/connector.test.js
```

They check that the token never goes into a URL, that foreign `paging.next` links are refused, that error messages for report viewers contain no token, that post data from Meta cannot inject HTML or unsafe links into the panel, that the CSV export never starts a formula, and that the regular expressions stay fast on long input.
