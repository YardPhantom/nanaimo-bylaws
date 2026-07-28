import { initializeApp } from "https://www.gstatic.com/firebasejs/12.16.0/firebase-app.js";
import {
  browserLocalPersistence,
  getAuth,
  GoogleAuthProvider,
  onAuthStateChanged,
  setPersistence,
  signInWithPopup,
  signOut,
  useDeviceLanguage
} from "https://www.gstatic.com/firebasejs/12.16.0/firebase-auth.js";
import {
  collection,
  deleteDoc,
  deleteField,
  doc,
  getDoc,
  getDocs,
  getFirestore,
  serverTimestamp,
  setDoc,
  writeBatch
} from "https://www.gstatic.com/firebasejs/12.16.0/firebase-firestore.js";
import { firebaseConfig } from "./firebase-config.js";

const requiredConfigKeys = ["apiKey", "authDomain", "projectId", "appId"];
const configured = requiredConfigKeys.every(key => {
  const value = firebaseConfig?.[key];
  return Boolean(value) && !String(value).startsWith("PASTE_");
});
let auth = null;
let db = null;
let currentUser = null;
let resolveReady;
const ready = new Promise(resolve => { resolveReady = resolve; });

function dispatchAuth(user, error = null) {
  window.dispatchEvent(new CustomEvent("nbt-auth-change", {
    detail: { user, configured, error }
  }));
  document.querySelectorAll("[data-account-state]").forEach(node => {
    node.textContent = user ? (user.displayName || user.email || "Account") : "Account";
  });
  document.documentElement.classList.toggle("account-signed-in", Boolean(user));
}

async function applyPreferences() {
  if (!currentUser || !db) return null;
  const snapshot = await getDoc(doc(db, "users", currentUser.uid, "settings", "preferences"));
  if (!snapshot.exists()) return null;
  const preferences = snapshot.data();
  document.documentElement.dataset.density = preferences.density || "comfortable";
  window.dispatchEvent(new CustomEvent("nbt-preferences-change", { detail: preferences }));
  return preferences;
}

function friendlyAuthError(error) {
  const code = error?.code || "";
  if (code === "auth/unauthorized-domain") {
    return "This website hostname is not listed in Firebase Authentication authorized domains.";
  }
  if (code === "auth/operation-not-allowed") {
    return "Google sign-in is not enabled in Firebase Authentication.";
  }
  if (code === "auth/popup-blocked") {
    return "Your browser blocked the Google sign-in window. Allow pop-ups for this site and try again.";
  }
  if (code === "auth/network-request-failed") {
    return "Google sign-in could not reach Firebase. Check the internet connection and browser privacy settings.";
  }
  if (code === "auth/popup-closed-by-user") return "";
  return error?.message || "Google sign-in failed.";
}

async function signInGoogle() {
  if (!configured || !auth) throw new Error("Firebase configuration is incomplete.");
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  return signInWithPopup(auth, provider);
}

async function signOutAccount() {
  if (auth) await signOut(auth);
}

async function loadWatchlist() {
  if (!currentUser || !db) return [];
  const snapshot = await getDocs(collection(db, "users", currentUser.uid, "watchlist"));
  return snapshot.docs.map(item => String(item.id));
}

async function saveWatchlist(numbers) {
  if (!currentUser || !db) return;
  const clean = [...new Set((numbers || []).map(String))];
  const existing = await getDocs(collection(db, "users", currentUser.uid, "watchlist"));
  const existingIds = new Set(existing.docs.map(item => item.id));
  const batch = writeBatch(db);
  clean.forEach(number => {
    batch.set(doc(db, "users", currentUser.uid, "watchlist", number), {
      number,
      savedAt: serverTimestamp()
    }, { merge: true });
    existingIds.delete(number);
  });
  existingIds.forEach(number => batch.delete(doc(db, "users", currentUser.uid, "watchlist", number)));
  await batch.commit();
}

async function loadPreferences() {
  if (!currentUser || !db) return null;
  const snapshot = await getDoc(doc(db, "users", currentUser.uid, "settings", "preferences"));
  return snapshot.exists() ? snapshot.data() : null;
}

async function savePreferences(preferences) {
  if (!currentUser || !db) throw new Error("Sign in before saving preferences.");
  const clean = {
    density: preferences.density === "compact" ? "compact" : "comfortable",
    defaultSort: ["newest", "title", "number"].includes(preferences.defaultSort) ? preferences.defaultSort : "newest",
    rememberFilters: Boolean(preferences.rememberFilters),
    updatedAt: serverTimestamp()
  };
  await setDoc(doc(db, "users", currentUser.uid, "settings", "preferences"), clean, { merge: true });
  document.documentElement.dataset.density = clean.density;
  window.dispatchEvent(new CustomEvent("nbt-preferences-change", { detail: clean }));
  return clean;
}

async function loadSubscription() {
  if (!currentUser || !db) return null;
  const snapshot = await getDoc(doc(db, "users", currentUser.uid, "subscriptions", "email"));
  return snapshot.exists() ? snapshot.data() : null;
}

async function saveSubscription(settings) {
  if (!currentUser || !db) throw new Error("Sign in before saving subscription settings.");
  const allowedTypes = ["new", "amended", "consolidated", "repealed"];
  const changeTypes = [...new Set((settings.changeTypes || []).filter(value => allowedTypes.includes(value)))];
  if (settings.active && !changeTypes.length) throw new Error("Select at least one change type.");
  const reference = doc(db, "users", currentUser.uid, "subscriptions", "email");
  const existingSnapshot = await getDoc(reference);
  const existing = existingSnapshot.exists() ? existingSnapshot.data() : {};
  const active = Boolean(settings.active);
  const clean = {
    active,
    frequency: ["immediate", "daily", "weekly"].includes(settings.frequency) ? settings.frequency : "daily",
    changeTypes,
    categories: settings.category && settings.category !== "all" ? [settings.category] : [],
    updatedAt: serverTimestamp()
  };
  if (!existingSnapshot.exists()) clean.createdAt = serverTimestamp();
  if (active && !existing.active) clean.activatedAt = serverTimestamp();
  // The recipient address is resolved server-side from Firebase Authentication.
  // Remove any fields written by older builds so the private settings document
  // contains preferences only.
  await setDoc(reference, {
    ...clean,
    recipientEmail: deleteField(),
    subscriptionKey: deleteField()
  }, { merge: true });
  return { ...existing, ...clean };
}

window.NBTAccount = {
  ready,
  get configured() { return configured; },
  get user() { return currentUser; },
  signInGoogle,
  signOut: signOutAccount,
  loadWatchlist,
  saveWatchlist,
  loadPreferences,
  savePreferences,
  loadSubscription,
  saveSubscription,
  friendlyAuthError
};

if (!configured) {
  resolveReady(null);
  dispatchAuth(null, "Firebase configuration is incomplete.");
} else {
  try {
    const app = initializeApp(firebaseConfig);
    auth = getAuth(app);
    db = getFirestore(app);
    useDeviceLanguage(auth);
    await setPersistence(auth, browserLocalPersistence);
    onAuthStateChanged(auth, async user => {
      currentUser = user;
      resolveReady(user);
      dispatchAuth(user);
      if (user) {
        try { await applyPreferences(); }
        catch (error) { console.error("[NBT] Could not load account preferences", error); }
      } else {
        delete document.documentElement.dataset.density;
      }
    });
  } catch (error) {
    console.error("[NBT] Firebase initialization failed", error);
    resolveReady(null);
    dispatchAuth(null, error.message);
  }
}
