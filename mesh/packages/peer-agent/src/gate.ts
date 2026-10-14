export class SenderGate {
  private roster: Set<string>
  private _violations = 0

  constructor(roster: string[]) { this.roster = new Set(roster) }

  setRoster(handles: string[]): void { this.roster = new Set(handles) }

  accept(handle: string): boolean {
    if (this.roster.has(handle)) return true
    this._violations++
    return false
  }

  violations(): number { return this._violations }
}
