export type Admission = { ok: true } | { ok: false; reason: "capacity" | "ip_limit" };

export class SessionGate {
  private sessions = new Map<string, { ip: string; lastSeen: number }>();

  constructor(private readonly capacity: number) {}

  admit(ip: string, sessionId: string, now = Date.now()): Admission {
    if ([...this.sessions.values()].some((session) => session.ip === ip)) return { ok: false, reason: "ip_limit" };
    if (this.sessions.size >= this.capacity) return { ok: false, reason: "capacity" };
    this.sessions.set(sessionId, { ip, lastSeen: now });
    return { ok: true };
  }

  touch(sessionId: string, now = Date.now()): void {
    const session = this.sessions.get(sessionId);
    if (session) session.lastSeen = now;
  }

  release(sessionId: string): void { this.sessions.delete(sessionId); }

  prune(now = Date.now(), idleMs = 60_000): void {
    this.sessions.forEach((session, id) => {
      if (now - session.lastSeen > idleMs) this.sessions.delete(id);
    });
  }

  snapshot(): { active: number; capacity: number } {
    return { active: this.sessions.size, capacity: this.capacity };
  }
}
