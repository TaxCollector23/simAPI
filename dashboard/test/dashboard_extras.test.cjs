const test = require('node:test');
const assert = require('node:assert/strict');
const extras = require('../dashboard_extras.js');

test('clean export removes whole failed episodes, even when rows are interleaved', () => {
  const rows = [
    { episode_id: 'clean', t: 0, value: 'ok' },
    { episode_id: 'bad', t: 0, value: 'drop-1' },
    { episode_id: 'clean', t: 1, value: 'ok-2' },
    { episode_id: 'bad', t: 1, value: 'drop-2' },
  ];
  const report = { training_ready: false, episode_quality: { episodes: [
    { episode_id: 'clean', verdict: 'passed', failure_labels: [] },
    { episode_id: 'bad', verdict: 'failed', failure_labels: ['limit_violation'] },
  ] } };
  assert.deepEqual(extras._cleanEpisodeRows(rows, report).rows, [rows[0], rows[2]]);
});

test('summary-only episodes are not trusted when the overall report failed', () => {
  const rows = [{ episode_id: 'maybe-clean', t: 0, value: 1 }];
  const report = {
    training_ready: false,
    robotics_summary: { episodes: [
      { episode_id: 'maybe-clean', flagged_samples: 0 },
    ] },
  };

  const selection = extras._cleanEpisodeRows(rows, report);
  assert.deepEqual(selection.rows, []);
  assert.match(selection.reason, /overall report is not training ready/i);
});

test('an episode-quality error disables clean export even if a summary has no flags', () => {
  const rows = [{ episode_id: 'unknown-quality', t: 0, value: 1 }];
  const report = {
    training_ready: true,
    episode_quality: { error: 'quality calculation failed' },
    robotics_summary: { episodes: [
      { episode_id: 'unknown-quality', flagged_samples: 0 },
    ] },
  };

  const selection = extras._cleanEpisodeRows(rows, report);
  assert.deepEqual(selection.rows, []);
  assert.match(selection.reason, /episode quality could not be computed/i);
});

test('an unnamed failed episode exports no rows; an unnamed passing one keeps them', () => {
  const rows = [{ t: 0, value: 1 }, { t: 1, value: 2 }];
  const failed = { robotics_summary: { episodes: [
    { episode_id: 'Episode 1', flagged_samples: 1 },
  ] } };
  const passed = { robotics_summary: { episodes: [
    { episode_id: 'Episode 1', flagged_samples: 0 },
  ] } };
  assert.deepEqual(extras._cleanEpisodeRows(rows, failed).rows, []);
  assert.deepEqual(extras._cleanEpisodeRows(rows, passed).rows, rows);
});

test('missing or unreported episode identities fail closed', () => {
  const rows = [{ episode_id: 'known', t: 0 }, { episode_id: 'unknown', t: 1 }];
  const report = { episodes: [{ episode_id: 'known', verdict: 'passed' }] };
  assert.deepEqual(extras._cleanEpisodeRows(rows, report).rows, [rows[0]]);
  assert.equal(extras._cleanEpisodeRows(rows, null).rows.length, 0);
});

test('incomplete episode reports fail closed', () => {
  const rows = [{ episode_id: 'episode-1', value: 1 }];
  const report = { episodes: [{ episode_id: 'episode-1' }] };
  assert.deepEqual(extras._cleanEpisodeRows(rows, report).rows, []);
});

test('CSV quotes commas, quotes, line breaks, and protects text formulas', () => {
  const csv = extras._toCsv([
    { 'signal,name': 'a"b', line: 'first\rsecond', formula: '=2+2', numeric: '-1.5' },
  ]);
  assert.equal(csv, '"signal,name",line,formula,numeric\r\n"a""b","first\rsecond",\'=2+2,-1.5');
});

test('episode labels are rendered as text rather than HTML', () => {
  const container = {
    children: [],
    innerHTML: 'initial',
    replaceChildren() { this.children = []; },
    appendChild(node) { this.children.push(node); },
  };
  const previousDocument = global.document;
  global.document = {
    getElementById(id) { return id === 'chips' ? container : null; },
    createElement(tag) { return { tag, className: '', textContent: '', title: '' }; },
  };
  try {
    extras.simapiRenderEpisodeChips({ episode_quality: { episodes: [
      { episode_id: '<img src=x onerror=alert(1)>', verdict: 'failed', failure_labels: ['<script>'] },
    ] } }, 'chips');
    assert.equal(container.children.length, 1);
    assert.equal(container.children[0].textContent, '<img src=x onerror=alert(1)> ✗ — <script>');
    assert.equal(container.children[0].className, 'episode-chip episode-chip-failed');
  } finally {
    global.document = previousDocument;
  }
});

test('MCP config paths are escaped as JSON data', () => {
  const config = JSON.parse(extras.simapiMcpConfig('/python"bin', '/a\nb.py', '/repo'));
  assert.equal(config.mcpServers.simapi.command, '/python"bin');
  assert.deepEqual(config.mcpServers.simapi.args, ['/a\nb.py']);
  assert.equal(config.mcpServers.simapi.env.SIMAPI_PATH, '/repo');
});
