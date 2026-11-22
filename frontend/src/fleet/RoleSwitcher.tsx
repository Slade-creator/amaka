import { useEffect, useRef, useState, type CSSProperties } from "react";
import { LogOut } from "lucide-react";
import { getRoleConfig, type Role } from "./roles";
import { useSession } from "../auth/SessionContext";
import "./fleet.css";

type Props = {
  role: Role;
  /** Kept for call-site compatibility; the role is fixed by the account. */
  onChange?: (role: Role) => void;
  /** Tighter trigger for dense headers. */
  compact?: boolean;
};

/**
 * Account menu: accent dot + the account's role, opening a small card with
 * the signed-in user and a sign-out action. Roles are assigned per account on
 * the server, so the menu no longer switches roles. Escape closes (focus
 * returns to the trigger) and outside clicks close.
 */
export default function RoleSwitcher({ role, compact }: Props) {
  const { user, signOut } = useSession();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const cfg = getRoleConfig(role);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className={`rs-root${compact ? " is-compact" : ""}`} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="rs-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Signed in as ${user.name}, ${cfg.label}. Account menu`}
        style={{ "--acc": cfg.accent } as CSSProperties}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="rs-dot" aria-hidden="true" />
        <span className="rs-label">{cfg.label}</span>
        <span className="rs-caret" aria-hidden="true">
          ▾
        </span>
      </button>

      {open ? (
        <div className="rs-menu" role="menu" aria-label="Account">
          <p className="rs-menu-title">SIGNED IN</p>
          <div className="rs-account" style={{ "--acc": cfg.accent } as CSSProperties}>
            <span className="rs-account-name">{user.name}</span>
            <span className="rs-account-meta">
              @{user.username} · {cfg.purpose.toLowerCase()}
            </span>
          </div>
          <button
            type="button"
            role="menuitem"
            className="rs-item"
            onClick={() => {
              setOpen(false);
              signOut();
            }}
          >
            <LogOut size={13} aria-hidden="true" />
            <span className="rs-item-label">Sign out</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}
