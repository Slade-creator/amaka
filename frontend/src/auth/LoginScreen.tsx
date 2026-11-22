import { useEffect, useRef, useState, type FormEvent } from "react";
import { Eye, EyeOff, Loader2, LogIn, Server } from "lucide-react";
import { AmakaMark } from "../components/ui";
import { DEFAULT_API_BASE, getApiBase, isValidBase } from "../lib/apiBase";
import { HttpError, saveServer, signIn, takeEndReason } from "../lib/session";
import { isNative } from "../lib/platform";
import "./auth.css";

type Props = {
  /** Phone layout (full-bleed) vs centred desktop card. */
  mobile: boolean;
};

/**
 * Sign-in screen. The account's role decides which views the app opens
 * (Commander · Energy Manager · Analyst), so there is no role picker here.
 * Native builds also expose the API server address, so a demo APK can be
 * pointed at a new laptop IP without rebuilding.
 */
export default function LoginScreen({ mobile }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice] = useState<string | null>(() => takeEndReason());
  const [server, setServer] = useState(getApiBase());
  const [showServer, setShowServer] = useState(false);
  const userRef = useRef<HTMLInputElement | null>(null);
  const native = isNative();

  useEffect(() => {
    if (!mobile) userRef.current?.focus();
  }, [mobile]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    if (native && !isValidBase(server)) {
      setError("Server must be a full address, for example http://192.168.1.20:8000");
      setShowServer(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (native) await saveServer(server);
      await signIn(username, password);
    } catch (err) {
      setError(err instanceof HttpError || err instanceof Error ? err.message : "Sign-in failed");
      if (err instanceof HttpError && err.status === undefined && native) setShowServer(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`auth-screen${mobile ? " is-mobile" : ""}`}>
      <div className="auth-glow" aria-hidden="true" />
      <form className="auth-card" onSubmit={submit} noValidate>
        <div className="auth-brand">
          <AmakaMark size={mobile ? 56 : 50} />
          <div className="auth-wordmark">AMAKA</div>
          <div className="auth-sub">ENERGY COMMAND</div>
        </div>

        <h1 className="auth-title">Sign in</h1>
        <p className="auth-lede">See the peak before it hits. Use the account issued by your energy office.</p>

        {notice && !error ? (
          <p className="auth-msg is-notice" role="status">
            {notice}
          </p>
        ) : null}
        {error ? (
          <p className="auth-msg is-error" role="alert">
            {error}
          </p>
        ) : null}

        <label className="auth-field">
          <span>Username</span>
          <input
            ref={userRef}
            name="username"
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            inputMode="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={busy}
          />
        </label>

        <label className="auth-field">
          <span>Password</span>
          <div className="auth-pw">
            <input
              name="password"
              type={showPw ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy}
            />
            <button
              type="button"
              className="auth-eye"
              onClick={() => setShowPw((v) => !v)}
              aria-label={showPw ? "Hide password" : "Show password"}
            >
              {showPw ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
            </button>
          </div>
        </label>

        {native ? (
          showServer ? (
            <label className="auth-field">
              <span>Server</span>
              <input
                name="server"
                inputMode="url"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                placeholder={DEFAULT_API_BASE || "http://192.168.1.20:8000"}
                value={server}
                onChange={(e) => setServer(e.target.value)}
                disabled={busy}
              />
            </label>
          ) : (
            <button type="button" className="auth-server" onClick={() => setShowServer(true)}>
              <Server size={14} aria-hidden="true" />
              <span className="num">{getApiBase() || "Same origin"}</span>
              <span className="auth-server-edit">Change</span>
            </button>
          )
        ) : null}

        <button type="submit" className="auth-submit" disabled={busy}>
          {busy ? (
            <Loader2 size={18} className="auth-spin" aria-hidden="true" />
          ) : (
            <LogIn size={18} aria-hidden="true" />
          )}
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p className="auth-foot">
          Authorised personnel only. Activity is logged.
          <br />
          <span className="num">AMAKA · synthetic demo data · v0.3</span>
        </p>
      </form>
    </div>
  );
}
