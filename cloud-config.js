/*
 * Nanaimo Bylaw Tracker cloud data configuration.
 * After deploying cloud/worker, set enabled to true and paste its workers.dev URL.
 * Preserve this deployment-specific file during future website upgrades.
 */
window.NANAIMO_CLOUD_CONFIG = Object.freeze({
  enabled: true,
  baseUrl: "https://nanaimo-bylaw-data.yardplots.workers.dev",
  localFallback: false
});
