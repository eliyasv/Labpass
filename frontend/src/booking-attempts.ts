// Retry metadata only. Credentials, cookies and CSRF tokens never enter storage.
export class BookingAttempts {
  private memory = new Map<string, string>();
  constructor(private storage: () => Storage) {}
  private name(user: string, workshop: string) {
    return `labpass:booking:${user}:${workshop}`;
  }
  pending(user: string, workshop: string) {
    const name = this.name(user, workshop);
    if (this.memory.has(name)) return true;
    try {
      return Boolean(this.storage().getItem(name));
    } catch {
      return false;
    }
  }
  get(user: string, workshop: string) {
    const name = this.name(user, workshop);
    let key = this.memory.get(name);
    try {
      key ||= this.storage().getItem(name) || undefined;
    } catch {
      /* Private browsing may deny storage. */
    }
    key ||= crypto.randomUUID();
    this.memory.set(name, key);
    try {
      this.storage().setItem(name, key);
    } catch {
      /* In-memory retries still work. */
    }
    return key;
  }
  finish(user: string, workshop: string) {
    const name = this.name(user, workshop);
    this.memory.delete(name);
    try {
      this.storage().removeItem(name);
    } catch {
      /* No persisted entry to clear. */
    }
  }
}
