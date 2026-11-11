/*
 * Small add-ons for the existing SimAPI static dashboard.
 *
 * 1. Episode quality chips use textContent, so IDs and labels stay plain text.
 * 2. Clean CSV export requires explicit episode verdicts and excludes whole
 *    episodes. Ambiguous or unreported rows are omitted.
 * 3. The MCP snippet configures the local stdio server.
 */
(function () {
  "use strict";

  var EPISODE_KEYS = ["episode_id", "episode", "trajectory_id", "sequence_id"];

  function episodesOf(report) {
    if (!report || typeof report !== "object") return [];
    if (report.episode_quality && Array.isArray(report.episode_quality.episodes)) {
      return report.episode_quality.episodes;
    }
    if (Array.isArray(report.episodes)) return report.episodes;
    if (report.robotics_summary && Array.isArray(report.robotics_summary.episodes)) {
      return report.robotics_summary.episodes;
    }
    return [];
  }

  function episodeId(episode) {
    return episode && episode.episode_id !== null && episode.episode_id !== undefined
      ? String(episode.episode_id)
      : "(missing episode)";
  }

  function episodeFailed(episode) {
    if (!episode || typeof episode !== "object") return true;
    if (episode.training_ready === false) return true;
    var verdict = episode.verdict || episode.status;
    if (verdict && String(verdict).toLowerCase() !== "passed") return true;
    if (Array.isArray(episode.failure_labels) && episode.failure_labels.length) return true;
    var hasFlagCount = episode.flagged_samples !== undefined && episode.flagged_samples !== null;
    var flagged = hasFlagCount ? Number(episode.flagged_samples) : 0;
    if (hasFlagCount && (!Number.isFinite(flagged) || flagged > 0)) return true;
    var hasDecision = episode.training_ready === true || Boolean(verdict) ||
      Array.isArray(episode.failure_labels) || hasFlagCount;
    return !hasDecision;
  }

  function failedEpisodeIds(report) {
    var bad = new Map();
    episodesOf(report).forEach(function (episode) {
      if (episodeFailed(episode)) bad.set(episodeId(episode), true);
    });
    return bad;
  }

  function simapiRenderEpisodeChips(report, containerId) {
    var el = typeof document !== "undefined" && document.getElementById(containerId);
    if (!el) return 0;
    var episodes = episodesOf(report);
    if (typeof el.replaceChildren === "function") el.replaceChildren();
    else el.textContent = "";
    if (!episodes.length) {
      el.textContent = "No episode verdicts are available for this report.";
      return 0;
    }
    episodes.forEach(function (episode) {
      var failed = episodeFailed(episode);
      var labels = Array.isArray(episode.failure_labels) ? episode.failure_labels : [];
      var chip = document.createElement("span");
      chip.className = "episode-chip " + (failed ? "episode-chip-failed" : "episode-chip-passed");
      chip.textContent = episodeId(episode) + (failed ? " ✗" : " ✓") +
        (labels.length ? " — " + labels.join(", ") : "") +
        (Number(episode.flagged_samples || 0) > 0
          ? " (" + Number(episode.flagged_samples) + " flagged)"
          : "");
      chip.title = failed
        ? "Failed — excluded from a clean export"
        : "Passed — included in a clean export";
      el.appendChild(chip);
    });
    return episodes.length;
  }

  function findEpisodeKey(rows) {
    for (var i = 0; i < EPISODE_KEYS.length; i += 1) {
      var key = EPISODE_KEYS[i];
      if (rows.some(function (row) {
        return row && typeof row === "object" && Object.prototype.hasOwnProperty.call(row, key);
      })) return key;
    }
    return null;
  }

  function cleanEpisodeRows(rows, report) {
    if (!Array.isArray(rows) || !rows.length) {
      return { rows: [], reason: "No sample rows are available." };
    }
    var episodes = episodesOf(report);
    if (!episodes.length) {
      return { rows: [], reason: "A report with episode verdicts is required before clean export." };
    }
    var key = findEpisodeKey(rows);
    if (!key) {
      if (episodes.length !== 1) {
        return { rows: [], reason: "Rows cannot be matched safely to multiple episode verdicts." };
      }
      return episodeFailed(episodes[0])
        ? { rows: [], reason: "The unnamed episode failed validation." }
        : { rows: rows.slice(), reason: "" };
    }

    var statusById = new Map();
    episodes.forEach(function (episode) {
      var id = episodeId(episode);
      // Fail closed if duplicate report entries disagree about an episode.
      statusById.set(id, Boolean(statusById.get(id)) || episodeFailed(episode));
    });
    var clean = rows.filter(function (row) {
      if (!row || typeof row !== "object") return false;
      var value = row[key];
      var id = value === null || value === undefined ? "(missing episode)" : String(value);
      return statusById.has(id) && statusById.get(id) === false;
    });
    var reason = clean.length
      ? ""
      : "No rows belong to a passing episode in this report.";
    return { rows: clean, reason: reason, episodeKey: key };
  }

  function csvValue(value) {
    if (value === null || value === undefined) return "";
    var text = typeof value === "object" ? JSON.stringify(value) : String(value);
    // Preserve numeric strings, but prevent text values from becoming formulas
    // when someone opens the export in a spreadsheet.
    if (typeof value === "string" && text.trim() !== "") {
      var isNumeric = text.trim() !== "" && Number.isFinite(Number(text));
      if (!isNumeric && /^[\t\r ]*[=+\-@]/.test(text)) text = "'" + text;
    }
    return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  function toCsv(rows) {
    if (!Array.isArray(rows) || !rows.length) return "";
    var keys = [];
    rows.forEach(function (row) {
      if (!row || typeof row !== "object") return;
      Object.keys(row).forEach(function (key) {
        if (keys.indexOf(key) === -1) keys.push(key);
      });
    });
    var lines = [keys.map(csvValue).join(",")];
    rows.forEach(function (row) {
      lines.push(keys.map(function (key) { return csvValue(row && row[key]); }).join(","));
    });
    return lines.join("\r\n");
  }

  function simapiDownloadCleanEpisodes(rows, report, filename) {
    var selection = cleanEpisodeRows(rows, report);
    if (!selection.rows.length || typeof Blob === "undefined" ||
        typeof document === "undefined" || typeof URL === "undefined" ||
        typeof URL.createObjectURL !== "function") return 0;
    var blob = new Blob([toCsv(selection.rows)], { type: "text/csv;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename || "clean_episodes.csv";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    return selection.rows.length;
  }

  function simapiMcpConfig(pythonPath, scriptPath, simapiPath) {
    return JSON.stringify({
      mcpServers: {
        simapi: {
          command: pythonPath || "/path/to/venv/bin/python",
          args: [scriptPath || "/path/to/simapi_mcp.py"],
          env: { SIMAPI_PATH: simapiPath || "/path/to/simapi" }
        }
      }
    }, null, 2);
  }

  function simapiCopyMcpConfig(pythonPath, scriptPath, simapiPath) {
    var text = simapiMcpConfig(pythonPath, scriptPath, simapiPath);
    if (typeof navigator !== "undefined" && navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return text; }, function () {
        return copyFallback(text);
      });
    }
    return copyFallback(text);
  }

  function copyFallback(text) {
    if (typeof document === "undefined" || !document.execCommand) {
      return Promise.reject(new Error("Clipboard access is unavailable in this browser."));
    }
    var textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    var copied = false;
    try { copied = document.execCommand("copy"); }
    finally { document.body.removeChild(textarea); }
    return copied
      ? Promise.resolve(text)
      : Promise.reject(new Error("The browser did not allow copying to the clipboard."));
  }

  var api = {
    simapiRenderEpisodeChips: simapiRenderEpisodeChips,
    simapiDownloadCleanEpisodes: simapiDownloadCleanEpisodes,
    simapiCopyMcpConfig: simapiCopyMcpConfig,
    simapiMcpConfig: simapiMcpConfig,
    _episodesOf: episodesOf,
    _episodeFailed: episodeFailed,
    _failedEpisodeIds: failedEpisodeIds,
    _cleanEpisodeRows: cleanEpisodeRows,
    _toCsv: toCsv
  };
  if (typeof window !== "undefined") Object.assign(window, api);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
