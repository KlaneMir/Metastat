/**
 * Looker Studio community connector for Meta: Meta Ads, a Facebook page, Instagram and their posts.
 * The same project also serves the panel (Index.html) as a web app.
 * Setup instructions are in README.md.
 */
var cc = DataStudioApp.createCommunityConnector();

// Graph API version. Meta retires versions after about 2 years, so bump it from time to time.
var API = 'https://graph.facebook.com/v23.0/';

// Metrics. Meta changes them often; a metric the API no longer recognises is skipped.
var ADS_METRICS = ['spend', 'impressions', 'reach', 'clicks', 'link_clicks', 'leads', 'purchases', 'purchase_value'];
var PAGE_METRICS = ['page_media_view', 'page_post_engagements', 'page_daily_follows_unique', 'page_follows'];
var IG_METRICS = ['views', 'reach', 'accounts_engaged', 'total_interactions', 'likes', 'comments', 'shares', 'saves'];
var FB_POST_VIEW_METRICS = ['post_media_view', 'post_impressions']; // the first one that works wins
var IG_MEDIA_METRICS = ['views', 'reach', 'shares', 'saved'];

var POST_DIMS = ['post_time', 'post_id', 'post_type', 'message', 'permalink', 'image'];

var SOURCES = {
  ads: { label: 'Meta Ads (campaigns, daily)', idHint: 'Ad account ID, e.g. act_1234567890',
         dims: ['campaign_id', 'campaign_name'], metrics: ADS_METRICS },
  page: { label: 'Facebook page (daily)', idHint: 'Page ID', dims: [], metrics: PAGE_METRICS },
  fbposts: { label: 'Facebook posts', idHint: 'Page ID', dims: POST_DIMS,
             metrics: ['views', 'reactions', 'likes', 'comments', 'shares'] },
  ig: { label: 'Instagram (daily)', idHint: 'Instagram Business account ID', dims: [],
        metrics: IG_METRICS.concat(['followers_count']) },
  igposts: { label: 'Instagram posts', idHint: 'Instagram Business account ID', dims: POST_DIMS,
             metrics: ['views', 'reach', 'likes', 'comments', 'shares', 'saves'] }
};

var LABELS = {
  date: 'Date', campaign_id: 'Campaign ID', campaign_name: 'Campaign',
  post_time: 'Published at', post_id: 'Post ID', post_type: 'Type', message: 'Text',
  permalink: 'Link', image: 'Image',
  spend: 'Spend', impressions: 'Ad impressions', reach: 'Reach', clicks: 'Clicks (all)',
  link_clicks: 'Link clicks', leads: 'Leads', purchases: 'Purchases', purchase_value: 'Purchase value',
  page_media_view: 'Content views', page_post_engagements: 'Post engagements',
  page_daily_follows_unique: 'New followers', page_follows: 'Followers (total)',
  views: 'Views', accounts_engaged: 'Accounts engaged', total_interactions: 'Interactions',
  likes: 'Likes', reactions: 'Reactions (all)', comments: 'Comments', shares: 'Shares',
  saves: 'Saves', followers_count: 'Followers (current)'
};

var DIM_TYPES = {
  date: 'YEAR_MONTH_DAY', post_time: 'YEAR_MONTH_DAY_SECOND', permalink: 'URL', image: 'IMAGE'
}; // all other dimensions: TEXT

var MAX_METRICS = ['page_follows', 'followers_count']; // point-in-time values, not increments: never summed

// ---------- auth: the Meta token is pasted in as the key ----------

function getAuthType() {
  return cc.newAuthTypeResponse()
    .setAuthType(cc.AuthType.KEY)
    .setHelpUrl('https://developers.facebook.com/docs/marketing-api/system-users/')
    .build();
}

function isAuthValid() {
  return !!getToken_();
}

function setCredentials(request) {
  var res = UrlFetchApp.fetch(API + 'me', opts_(request.key));
  if (res.getResponseCode() !== 200) return { errorCode: 'INVALID_CREDENTIALS' };
  PropertiesService.getUserProperties().setProperty('meta.token', request.key);
  return { errorCode: 'NONE' };
}

function resetAuth() {
  PropertiesService.getUserProperties().deleteProperty('meta.token');
}

function isAdminUser() {
  return false; // error details (debug text) would be visible to every viewer of a shared report
}

function getToken_() {
  return PropertiesService.getUserProperties().getProperty('meta.token');
}

// ---------- config and schema (Looker Studio) ----------

function getConfig() {
  var config = cc.getConfig();
  var select = config.newSelectSingle().setId('source').setName('Data source');
  Object.keys(SOURCES).forEach(function (id) {
    select.addOption(config.newOptionBuilder().setLabel(SOURCES[id].label).setValue(id));
  });
  config.newTextInput()
    .setId('objectId')
    .setName('ID')
    .setHelpText('Meta Ads: ad account ID (act_123... or just the number). Facebook page and posts: page ID. Instagram and Instagram posts: IG Business account ID.');
  config.setDateRangeRequired(true);
  return config.build();
}

function fieldIds_(source) {
  var s = SOURCES[source] || SOURCES.ads;
  return { dims: ['date'].concat(s.dims), metrics: s.metrics };
}

function getFields_(source) {
  var fields = cc.getFields();
  var ids = fieldIds_(source);
  ids.dims.forEach(function (id) {
    fields.newDimension().setId(id).setName(LABELS[id] || id).setType(cc.FieldType[DIM_TYPES[id] || 'TEXT']);
  });
  ids.metrics.forEach(function (id) {
    fields.newMetric()
      .setId(id)
      .setName(LABELS[id] || id)
      .setType(cc.FieldType.NUMBER)
      .setAggregation(MAX_METRICS.indexOf(id) >= 0 ? cc.AggregationType.MAX : cc.AggregationType.SUM);
  });
  return fields;
}

function getSchema(request) {
  return { schema: getFields_(source_(request)).build() };
}

function source_(request) {
  return (request.configParams && request.configParams.source) || 'ads';
}

function getData(request) {
  var source = source_(request);
  var requested = request.fields.map(function (f) { return f.name; });
  var rows;
  try {
    rows = fetchRows_(source, request.configParams.objectId, request.dateRange.startDate, request.dateRange.endDate);
  } catch (e) {
    cc.newUserError()
      .setDebugText(redact_(e.stack || e))
      .setText('Meta API: ' + redact_(e.message))
      .throwException();
  }
  return {
    schema: getFields_(source).forIds(requested).build(),
    rows: rows.map(function (r) {
      return { values: requested.map(function (k) { return r[k] === undefined ? null : r[k]; }) };
    })
  };
}

// ---------- fetching ----------

/** Shared by the connector and the panel. Dates are YYYY-MM-DD; rows are objects keyed by schema field ids. */
function fetchRows_(source, objectId, from, to) {
  var id = String(objectId || '').trim();
  if (!id) throw new Error('Enter an ID.');
  if (source === 'page') return fetchPage_(id, from, to);
  if (source === 'fbposts') return fetchFbPosts_(id, from, to);
  if (source === 'ig') return fetchIg_(id, from, to);
  if (source === 'igposts') return fetchIgPosts_(id, from, to);
  return fetchAds_(id, from, to);
}

function fetchAds_(id, from, to) {
  if (id.indexOf('act_') !== 0) id = 'act_' + id;
  var token = getToken_();
  var rows = [];
  eachPage_(fetchJson_(API + id + '/insights?' + toQuery_({
    level: 'campaign',
    fields: 'campaign_id,campaign_name,spend,impressions,reach,clicks,actions,action_values',
    time_range: { since: from, until: to },
    time_increment: 1,
    limit: 500
  }), token), function (d) {
    rows.push({
      date: ymd_(d.date_start),
      campaign_id: d.campaign_id,
      campaign_name: d.campaign_name,
      spend: toNumber_(d.spend),
      impressions: toNumber_(d.impressions),
      reach: toNumber_(d.reach),
      clicks: toNumber_(d.clicks),
      link_clicks: action_(d.actions, 'link_click'),
      leads: action_(d.actions, 'lead'),
      purchases: action_(d.actions, 'purchase'),
      purchase_value: action_(d.action_values, 'purchase')
    });
  }, token);
  return rows;
}

function fetchPage_(pageId, from, to) {
  var token = pageToken_(pageId);
  // The API accepts at most ~93 days per request, and each metric is requested separately so one retired metric does not break the rest.
  var urls = [];
  for (var s = from; s <= to; s = addDays_(s, 90)) {
    var e = addDays_(s, 89) < to ? addDays_(s, 89) : to;
    for (var i = 0; i < PAGE_METRICS.length; i++) {
      urls.push({ url: API + pageId + '/insights?' + toQuery_({
        metric: PAGE_METRICS[i], period: 'day', since: unix_(s), until: unix_(addDays_(e, 2))
      }), token: token });
    }
  }
  var byDate = {};
  var firstError = null;
  var anyOk = false;
  fetchAllJson_(urls).forEach(function (body) {
    if (body.error) { firstError = firstError || body.error.message; return; }
    anyOk = true;
    body.data.forEach(function (m) {
      m.values.forEach(function (v) {
        // end_time is the end of the day, so the value belongs to the previous day
        var day = addDays_(v.end_time.slice(0, 10), -1);
        if (day < from || day > to) return;
        byDate[day] = byDate[day] || { date: ymd_(day) };
        byDate[day][m.name] = toNumber_(v.value);
      });
    });
  });
  if (!anyOk) throw new Error(firstError);
  return Object.keys(byDate).sort().map(function (k) { return byDate[k]; });
}

function fetchFbPosts_(pageId, from, to) {
  var token = pageToken_(pageId);
  var posts = [];
  // One day of margin on each side because the API works in UTC; the exact cut is made on local time.
  eachPage_(fetchJson_(API + pageId + '/posts?' + toQuery_({
    fields: 'id,created_time,message,permalink_url,full_picture,status_type,shares,' +
      'comments.limit(0).summary(total_count),' +
      'reactions.limit(0).summary(total_count).as(reactions_all),' +
      'reactions.type(LIKE).limit(0).summary(total_count).as(reactions_like)',
    since: unix_(addDays_(from, -1)),
    until: unix_(addDays_(to, 2)),
    limit: 100
  }), token), function (p) {
    var t = localTime_(p.created_time);
    if (t.slice(0, 8) >= ymd_(from) && t.slice(0, 8) <= ymd_(to)) posts.push({ p: p, t: t });
  }, token);

  var views = fbPostViews_(posts.map(function (x) { return x.p.id; }), token);
  var TYPES = { added_photos: 'Photo', added_video: 'Video', shared_story: 'Link / share' };
  return posts.map(function (x) {
    var p = x.p;
    return {
      date: x.t.slice(0, 8), post_time: x.t, post_id: p.id,
      post_type: TYPES[p.status_type] || 'Post',
      message: p.message || '', permalink: p.permalink_url || null, image: p.full_picture || null,
      views: views[p.id] === undefined ? null : views[p.id],
      reactions: summary_(p.reactions_all), likes: summary_(p.reactions_like),
      comments: summary_(p.comments), shares: p.shares ? Number(p.shares.count) : 0
    };
  });
}

function fbPostViews_(ids, token) {
  var out = {};
  if (!ids.length) return out;
  // Probe the first post to find which views metric the API still recognises.
  var metric = null;
  for (var i = 0; i < FB_POST_VIEW_METRICS.length && !metric; i++) {
    var probe = fetchAllJson_([{ url: API + ids[0] + '/insights?' + toQuery_({ metric: FB_POST_VIEW_METRICS[i] }), token: token }])[0];
    if (!probe.error) metric = FB_POST_VIEW_METRICS[i];
  }
  if (!metric) return out;
  fetchAllJson_(ids.map(function (id) {
    return { url: API + id + '/insights?' + toQuery_({ metric: metric }), token: token };
  })).forEach(function (body, i) {
    if (!body.error && body.data.length) out[ids[i]] = readInsights_(body)[metric];
  });
  return out;
}

function fetchIg_(igId, from, to) {
  var days = [];
  for (var d = from; d <= to; d = addDays_(d, 1)) days.push(d);
  if (days.length > 400) throw new Error('For Instagram, choose a range of up to 400 days.');

  var token = getToken_();
  function igUrl(day, metrics) {
    return { url: API + igId + '/insights?' + toQuery_({
      metric: metrics.join(','), period: 'day', metric_type: 'total_value',
      since: unix_(day), until: unix_(addDays_(day, 1))
    }), token: token };
  }

  // Check once which metrics the API still accepts.
  var ok = [];
  var firstError = null;
  fetchAllJson_(IG_METRICS.map(function (m) { return igUrl(from, [m]); })).forEach(function (body, i) {
    if (body.error) firstError = firstError || body.error.message;
    else ok.push(IG_METRICS[i]);
  });
  if (!ok.length) throw new Error(firstError);

  var followers = fetchJson_(API + igId + '?' + toQuery_({ fields: 'followers_count' }), token).followers_count;
  return fetchAllJson_(days.map(function (day) { return igUrl(day, ok); })).map(function (body, i) {
    if (body.error) throw new Error(body.error.message);
    var row = readInsights_(body);
    row.date = ymd_(days[i]);
    row.followers_count = followers === undefined ? null : Number(followers);
    return row;
  });
}

function fetchIgPosts_(igId, from, to) {
  var token = getToken_();
  var posts = [];
  var body = fetchJson_(API + igId + '/media?' + toQuery_({
    fields: 'id,timestamp,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,like_count,comments_count',
    limit: 100
  }), token);
  // Media come newest first. Pinned posts can be old, so stop only at a page that is entirely older than the range.
  while (true) {
    var anyInRange = false;
    body.data.forEach(function (m) {
      var t = localTime_(m.timestamp);
      if (t.slice(0, 8) >= ymd_(from)) anyInRange = true;
      if (t.slice(0, 8) >= ymd_(from) && t.slice(0, 8) <= ymd_(to)) posts.push({ m: m, t: t });
    });
    if (!anyInRange || !body.paging || !body.paging.next) break;
    body = fetchJson_(nextUrl_(body.paging.next), token);
  }

  var insights = igMediaInsights_(posts.map(function (x) { return x.m.id; }), token);
  var TYPES = { IMAGE: 'Photo', VIDEO: 'Video', CAROUSEL_ALBUM: 'Carousel' };
  return posts.map(function (x) {
    var m = x.m;
    var ins = insights[m.id] || {};
    return {
      date: x.t.slice(0, 8), post_time: x.t, post_id: m.id,
      post_type: m.media_product_type === 'REELS' ? 'Reel' : (TYPES[m.media_type] || m.media_type),
      message: m.caption || '', permalink: m.permalink || null,
      image: m.thumbnail_url || m.media_url || null,
      views: ins.views === undefined ? null : ins.views,
      reach: ins.reach === undefined ? null : ins.reach,
      likes: m.like_count === undefined ? null : Number(m.like_count),
      comments: m.comments_count === undefined ? null : Number(m.comments_count),
      shares: ins.shares === undefined ? null : ins.shares,
      saves: ins.saved === undefined ? null : ins.saved
    };
  });
}

function igMediaInsights_(ids, token) {
  var out = {};
  function req(id, metrics) {
    return { url: API + id + '/insights?' + toQuery_({ metric: metrics.join(',') }), token: token };
  }
  var retry = [];
  fetchAllJson_(ids.map(function (id) { return req(id, IG_MEDIA_METRICS); })).forEach(function (body, i) {
    if (body.error) retry.push(ids[i]);
    else out[ids[i]] = readInsights_(body);
  });
  // Not every post type supports every metric: on error, request each metric separately.
  var reqs = [];
  retry.forEach(function (id) {
    IG_MEDIA_METRICS.forEach(function (m) { reqs.push({ id: id, req: req(id, [m]) }); });
  });
  fetchAllJson_(reqs.map(function (r) { return r.req; })).forEach(function (body, i) {
    var id = reqs[i].id;
    out[id] = out[id] || {};
    if (!body.error) {
      var vals = readInsights_(body);
      Object.keys(vals).forEach(function (k) { out[id][k] = vals[k]; });
    }
  });
  return out;
}

// ---------- panel (web app) ----------

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('Meta Connector')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function panelStatus() {
  var token = getToken_();
  var sources = Object.keys(SOURCES).map(function (id) {
    var ids = fieldIds_(id);
    return {
      id: id, label: SOURCES[id].label, idHint: SOURCES[id].idHint,
      dims: ids.dims.map(function (f) { return { id: f, label: LABELS[f] || f, type: DIM_TYPES[f] || 'TEXT' }; }),
      metrics: ids.metrics.map(function (f) { return { id: f, label: LABELS[f] || f, max: MAX_METRICS.indexOf(f) >= 0 }; })
    };
  });
  if (!token) return { hasToken: false, sources: sources };
  var me = JSON.parse(UrlFetchApp.fetch(API + 'me?fields=name', opts_(token)).getContentText());
  return {
    hasToken: true, valid: !me.error, name: me.name || null,
    error: me.error ? me.error.message : null, sources: sources
  };
}

function panelSaveToken(token) {
  var r = setCredentials({ key: String(token || '').trim() });
  if (r.errorCode !== 'NONE') throw new Error('Meta rejected this token. Check that you copied all of it.');
  return panelStatus();
}

function panelClearToken() {
  resetAuth();
  return panelStatus();
}

/** Ad accounts, pages and IG profiles the token can access, so IDs do not have to be typed in by hand. */
function panelAssets() {
  var token = getToken_();
  var out = { ads: [], pages: [], ig: [] };
  try {
    eachPage_(fetchJson_(API + 'me/adaccounts?' + toQuery_({ fields: 'name,account_id', limit: 100 }), token),
      function (a) { out.ads.push({ id: 'act_' + a.account_id, name: a.name }); }, token);
  } catch (e) { /* no ads_read permission: the list stays empty */ }
  try {
    eachPage_(fetchJson_(API + 'me/accounts?' + toQuery_({
      fields: 'name,id,instagram_business_account{id,username}', limit: 100
    }), token), function (p) {
      out.pages.push({ id: p.id, name: p.name });
      if (p.instagram_business_account) {
        out.ig.push({ id: p.instagram_business_account.id, name: '@' + p.instagram_business_account.username });
      }
    }, token);
  } catch (e) { /* no pages_show_list permission: the list stays empty */ }
  return out;
}

function panelQuery(q) {
  var started = Date.now();
  var rows = fetchRows_(q.source, q.objectId, q.from, q.to);
  return { rows: rows, fetchedAt: new Date().toISOString(), ms: Date.now() - started };
}

// ---------- helpers ----------

function pageToken_(pageId) {
  // Page insights and posts require a page token, not a user token.
  var token = fetchJson_(API + pageId + '?fields=access_token', getToken_()).access_token;
  if (!token) throw new Error('The token has no access to this page.');
  return token;
}

/** The token always goes in the Authorization header, never in the URL: URLs end up in logs and error messages. */
function opts_(token) {
  return { headers: { Authorization: 'Bearer ' + token }, muteHttpExceptions: true };
}

/** The paging.next link comes from the API response: allow graph.facebook.com only and strip access_token (the token goes in the header). */
function nextUrl_(url) {
  url = String(url);
  if (url.indexOf('https://graph.facebook.com/') !== 0) throw new Error('Rejected a paging link from outside the Graph API.');
  return url.replace(/([?&])access_token=[^&#]*&?/g, '$1').replace(/[?&]$/, '');
}

/** Error text with tokens removed: the connector shows it in Looker Studio to report viewers too. */
function redact_(text) {
  return String(text).replace(/(access_token=)[^&\s"']+/gi, '$1…').replace(/(Bearer\s+)[A-Za-z0-9._-]+/g, '$1…');
}

function fetchJson_(url, token) {
  var body = JSON.parse(UrlFetchApp.fetch(url, opts_(token)).getContentText());
  if (body.error) throw new Error(body.error.message);
  return body;
}

/** Parallel { url, token } requests in batches of 50. Errors come back as { error: { message } } and do not stop the rest. */
function fetchAllJson_(reqs) {
  var out = [];
  for (var i = 0; i < reqs.length; i += 50) {
    UrlFetchApp.fetchAll(reqs.slice(i, i + 50).map(function (r) { var o = opts_(r.token); o.url = r.url; return o; }))
      .forEach(function (res) {
        try { out.push(JSON.parse(res.getContentText())); } catch (e) { out.push({ error: { message: 'Invalid API response' } }); }
      });
  }
  return out;
}

function eachPage_(body, fn, token) {
  while (true) {
    body.data.forEach(fn);
    if (!body.paging || !body.paging.next) return;
    body = fetchJson_(nextUrl_(body.paging.next), token);
  }
}

function readInsights_(body) {
  var o = {};
  body.data.forEach(function (m) {
    if (m.total_value) o[m.name] = toNumber_(m.total_value.value);
    else if (m.values && m.values.length) o[m.name] = toNumber_(m.values[0].value);
  });
  return o;
}

function toQuery_(params) {
  return Object.keys(params).map(function (k) {
    var v = params[k];
    if (typeof v === 'object') v = JSON.stringify(v);
    return encodeURIComponent(k) + '=' + encodeURIComponent(v);
  }).join('&');
}

function action_(list, type) {
  if (!list) return 0;
  for (var i = 0; i < list.length; i++) {
    if (list[i].action_type === type) return Number(list[i].value);
  }
  return 0;
}

function summary_(edge) {
  return edge && edge.summary ? Number(edge.summary.total_count) : 0;
}

function toNumber_(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === 'object') { // metrics with a breakdown: sum the parts
    return Object.keys(v).reduce(function (sum, k) { return sum + Number(v[k]); }, 0);
  }
  return Number(v);
}

function localTime_(iso) {
  // Meta returns e.g. 2026-10-31T17:04:00+0000; V8 prefers the offset with a colon.
  var d = new Date(String(iso).replace(/([+-]\d\d)(\d\d)$/, '$1:$2'));
  return Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyyMMddHHmmss');
}

function addDays_(day, n) {
  var d = new Date(day + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function unix_(day) {
  return Math.floor(Date.parse(day + 'T00:00:00Z') / 1000);
}

function ymd_(s) {
  return s.slice(0, 10).replace(/-/g, '');
}
