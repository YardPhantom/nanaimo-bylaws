import "./account-session.min.js";
const $ = selector => document.querySelector(selector);
const status = $("#account-status");
const signedOut = $("#account-signed-out");
const signedIn = $("#account-signed-in");
const signInButton = $("#account-sign-in");
const signOutButton = $("#account-sign-out");
const preferencesForm = $("#account-preferences");
const watchlistCount = $("#account-watchlist-count");
const migrateNote = $("#account-migration-note");
const subscriptionForm = $("#account-subscriptions");
const subscriptionState = $("#subscription-state");
const subscriptionSaveStatus = $("#subscription-save-status");
const watchlistItems = $("#account-watchlist-items");
const watchlistUnresolved = $("#account-watchlist-unresolved");
let accountBylaws = [];


function renderAccountWatchlist(numbers) {
  const unique = [...new Set((numbers || []).map(String))];
  const recordsByNumber = new Map(accountBylaws.map(record => [String(record.number), record]));
  const matched = unique.map(number => recordsByNumber.get(number)).filter(Boolean);
  const unresolved = unique.filter(number => !recordsByNumber.has(number));
  watchlistCount.textContent = matched.length.toLocaleString();
  if (watchlistItems) {
    watchlistItems.innerHTML = matched.length
      ? matched.map(record => `<li><a href="bylaws/${record.detail_url || `detail.html?number=${encodeURIComponent(record.number)}`}">${record.title || `Bylaw ${record.number}`}</a><button class="watch-star active" type="button" data-account-watch-number="${record.number}" aria-label="Remove ${record.title || `Bylaw ${record.number}`} from watchlist" aria-pressed="true">★</button></li>`).join("")
      : "<li>No current bylaw records are on this watchlist.</li>";
  }
  if (watchlistUnresolved) {
    watchlistUnresolved.hidden = unresolved.length === 0;
    watchlistUnresolved.textContent = unresolved.length
      ? `${unresolved.length} saved item${unresolved.length === 1 ? "" : "s"} no longer match the current bylaw dataset.`
      : "";
  }
}

async function loadAccountBylaws() {
  try {
    const response = await NanaimoData.fetch(`data/bylaws.json?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    accountBylaws = Array.isArray(payload) ? payload : (Array.isArray(payload.bylaws) ? payload.bylaws : []);
  } catch (error) {
    console.error("[NBT] Could not load account watchlist records", error);
    accountBylaws = [];
  }
}

function setSubscriptionStatus(message, type = "", options = []) {
  if (!subscriptionSaveStatus) return;
  subscriptionSaveStatus.hidden = !message;
  subscriptionSaveStatus.replaceChildren();
  subscriptionSaveStatus.className = `account-message subscription-save-message ${type}`.trim();
  if (!message) return;

  const summary = document.createElement("span");
  summary.textContent = message;
  subscriptionSaveStatus.append(summary);

  if (options.length) {
    const list = document.createElement("ul");
    list.className = "subscription-saved-options";
    options.forEach(option => {
      const item = document.createElement("li");
      item.textContent = option;
      list.append(item);
    });
    subscriptionSaveStatus.append(list);
  }
}

function localWatchlist() {
  try {
    const values = JSON.parse(localStorage.getItem("nanaimoBylawWatchlist") || "[]");
    return Array.isArray(values) ? [...new Set(values.map(String))] : [];
  } catch { return []; }
}

function setStatus(message, type = "") {
  status.textContent = message;
  status.className = `account-message ${type}`.trim();
}

async function refreshAccount(user) {
  signedOut.hidden = Boolean(user);
  signedIn.hidden = !user;
  if (!user) {
    setStatus(window.NBTAccount?.configured
      ? "Sign in with Google to access your private account data."
      : "Add your Firebase web configuration to firebase-config.js before signing in.",
      window.NBTAccount?.configured ? "" : "warning");
    return;
  }

  $("#account-name").textContent = user.displayName || "Google user";
  $("#account-email").textContent = user.email || "";
  const photo = $("#account-photo");
  if (user.photoURL) {
    photo.src = user.photoURL;
    photo.hidden = false;
  } else photo.hidden = true;

  setStatus("Signed in. Your watchlist and preferences are private to this Google account.", "success");

  const cloud = await window.NBTAccount.loadWatchlist();
  const local = localWatchlist();
  const merged = [...new Set([...cloud, ...local])];
  if (merged.length !== cloud.length) {
    await window.NBTAccount.saveWatchlist(merged);
    migrateNote.textContent = `Merged ${local.length} browser-saved item${local.length === 1 ? "" : "s"} into this account.`;
  } else {
    migrateNote.textContent = "Your browser watchlist is synchronized with this account.";
  }
  localStorage.setItem("nanaimoBylawWatchlist", JSON.stringify(merged));
  renderAccountWatchlist(merged);
  window.dispatchEvent(new CustomEvent("bylaw-watchlist-change", { detail: { numbers: merged } }));

  const preferences = await window.NBTAccount.loadPreferences() || {};
  $("#preference-density").value = preferences.density || "comfortable";
  $("#preference-sort").value = preferences.defaultSort || "newest";
  $("#preference-filters").checked = Boolean(preferences.rememberFilters);

  const subscription = await window.NBTAccount.loadSubscription() || {};
  $("#subscription-active").checked = Boolean(subscription.active);
  $("#subscription-frequency").value = subscription.frequency || "daily";
  const selectedTypes = new Set(subscription.changeTypes || ["new", "amended", "consolidated", "repealed"]);
  document.querySelectorAll('[name="subscription-type"]').forEach(input => { input.checked = selectedTypes.has(input.value); });
  $("#subscription-categories").value = subscription.categories?.[0] || "all";
  subscriptionState.textContent = subscription.active ? "On" : "Off";
  subscriptionState.className = `status ${subscription.active ? "active" : "consolidated"}`;
}

signInButton?.addEventListener("click", async () => {
  signInButton.disabled = true;
  setStatus("Opening Google sign-in…");
  try { await window.NBTAccount.signInGoogle(); }
  catch (error) {
    const message = window.NBTAccount.friendlyAuthError(error);
    if (message) setStatus(message, "error");
  } finally { signInButton.disabled = false; }
});

signOutButton?.addEventListener("click", async () => {
  await window.NBTAccount.signOut();
});

preferencesForm?.addEventListener("submit", async event => {
  event.preventDefault();
  const button = preferencesForm.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    await window.NBTAccount.savePreferences({
      density: $("#preference-density").value,
      defaultSort: $("#preference-sort").value,
      rememberFilters: $("#preference-filters").checked
    });
    setStatus("Preferences saved.", "success");
  } catch (error) {
    setStatus(error.message || "Preferences could not be saved.", "error");
  } finally { button.disabled = false; }
});

subscriptionForm?.addEventListener("submit", async event => {
  event.preventDefault();
  const button = subscriptionForm.querySelector('button[type="submit"]');
  if (!button) return;
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "Saving…";
  setSubscriptionStatus("Saving subscription settings…");
  try {
    if (!window.NBTAccount?.user) throw new Error("Your account session is not ready. Sign in again and retry.");
    const saved = await window.NBTAccount.saveSubscription({
      active: $("#subscription-active").checked,
      frequency: $("#subscription-frequency").value,
      changeTypes: [...document.querySelectorAll('[name="subscription-type"]:checked')].map(input => input.value),
      category: $("#subscription-categories").value
    });
    subscriptionState.textContent = saved.active ? "On" : "Off";
    subscriptionState.className = `status ${saved.active ? "active" : "consolidated"}`;
    const message = saved.active
      ? "Saved. Email alerts are enabled for this account."
      : "Saved. Email alerts are turned off for this account.";
    const optionLabels = {
      new: "New bylaws and Council items",
      amended: "Amendments and readings",
      consolidated: "Consolidations",
      repealed: "Repeals and replacements"
    };
    const selectedOptions = saved.active
      ? (saved.changeTypes || []).map(value => optionLabels[value]).filter(Boolean)
      : [];
    setSubscriptionStatus(message, "success", selectedOptions);
    setStatus(message, "success");
  } catch (error) {
    console.error("[NBT] Subscription save failed", error);
    const message = error?.code === "permission-denied" || String(error?.message || "").includes("insufficient permissions")
      ? "Firestore denied this save. Publish the supplied V0.13.1 firestore.rules, then sign out and back in."
      : (error?.message || "Subscription settings could not be saved.");
    setSubscriptionStatus(message, "error");
    setStatus(message, "error");
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
});

window.addEventListener("nbt-auth-change", event => {
  refreshAccount(event.detail.user).catch(error => setStatus(error.message || "Account data could not be loaded.", "error"));
});

watchlistItems?.addEventListener("click", event => {
  const button = event.target.closest("[data-account-watch-number]");
  if (!button || !window.BylawWatchlist) return;
  window.BylawWatchlist.remove(button.dataset.accountWatchNumber);
});

window.addEventListener("bylaw-watchlist-change", event => {
  renderAccountWatchlist(event.detail?.numbers || localWatchlist());
});

Promise.all([window.NBTAccount.ready, loadAccountBylaws()]).then(() => refreshAccount(window.NBTAccount.user));
