import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import BootScreen from "./components/BootScreen";
import LoginScreen from "./auth/LoginScreen";
import { SessionProvider } from "./auth/SessionContext";
import { getSession, restoreSession, signOut, subscribeSession, type Session } from "./lib/session";
import { isNative, prefersMobileShell } from "./lib/platform";
import PowerIntro, { shouldPlayIntro } from "./intro/PowerIntro";

// Each shell is its own chunk: the phone app never downloads the desktop
// dashboard (WebGPU background, fleet map, rail) and vice versa.
const DesktopApp = lazy(() => import("./App"));
const MobileApp = lazy(() => import("./mobile/MobileApp"));

/**
 * Top-level gate: restore the saved session, show sign-in when there is none,
 * then render the phone or desktop shell for the signed-in account.
 */
export default function Root() {
  const mobile = useMemo(() => prefersMobileShell(), []);
  const [restoring, setRestoring] = useState(true);
  // The intro plays while the saved session is restored in the background.
  const [intro, setIntro] = useState(() => shouldPlayIntro(isNative()));
  const [session, setSessionState] = useState<Session | null>(getSession());

  useEffect(() => {
    const off = subscribeSession(setSessionState);
    restoreSession()
      .then((s) => setSessionState(s))
      .finally(() => setRestoring(false));
    return () => {
      off();
    };
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("is-mobile-shell", mobile);
  }, [mobile]);

  if (intro) return <PowerIntro onDone={() => setIntro(false)} />;
  if (restoring) return <BootScreen state="loading" />;
  if (!session) return <LoginScreen mobile={mobile} />;

  const value = { user: session.user, signOut: () => signOut() };
  return (
    <SessionProvider value={value}>
      <Suspense fallback={<BootScreen state="loading" />}>
        {/* key: a different account starts from a clean app state */}
        {mobile ? (
          <MobileApp key={session.user.username} />
        ) : (
          <DesktopApp key={session.user.username} />
        )}
      </Suspense>
    </SessionProvider>
  );
}
