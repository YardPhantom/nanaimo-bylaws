window.BylawWatchlist = (() => {
  const KEY = 'nanaimoBylawWatchlist';
  let syncing = false;

  const read = () => {
    try {
      const value = JSON.parse(localStorage.getItem(KEY) || '[]');
      return Array.isArray(value) ? [...new Set(value.map(String))] : [];
    } catch { return []; }
  };

  const persistCloud = values => {
    if (!window.NBTAccount?.user || syncing) return;
    window.NBTAccount.saveWatchlist(values).catch(error => console.error('[NBT] Watchlist sync failed', error));
  };

  const write = values => {
    const clean = [...new Set(values.map(String))];
    localStorage.setItem(KEY, JSON.stringify(clean));
    persistCloud(clean);
    window.dispatchEvent(new CustomEvent('bylaw-watchlist-change', {detail:{numbers:clean}}));
    return clean;
  };

  const syncAccount = async user => {
    if (!user || !window.NBTAccount) return;
    syncing = true;
    try {
      const cloud = await window.NBTAccount.loadWatchlist();
      const merged = [...new Set([...cloud, ...read()])];
      localStorage.setItem(KEY, JSON.stringify(merged));
      await window.NBTAccount.saveWatchlist(merged);
      window.dispatchEvent(new CustomEvent('bylaw-watchlist-change', {detail:{numbers:merged}}));
    } finally { syncing = false; }
  };

  window.addEventListener('nbt-auth-change', event => syncAccount(event.detail.user));
  if (window.NBTAccount?.user) syncAccount(window.NBTAccount.user);

  const has = number => read().includes(String(number));
  const add = number => write([...read(), String(number)]);
  const remove = number => write(read().filter(value => value !== String(number)));
  const toggle = number => has(number) ? (remove(number), false) : (add(number), true);
  return {read, write, has, add, remove, toggle, syncAccount};
})();
