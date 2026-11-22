import { createContext, useContext, type ReactNode } from "react";
import type { SessionUser } from "../lib/session";

type SessionValue = {
  user: SessionUser;
  signOut: () => void;
};

const Ctx = createContext<SessionValue | null>(null);

export function SessionProvider({ value, children }: { value: SessionValue; children: ReactNode }) {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Signed-in account. Only valid below <Root>, which renders after sign-in. */
export function useSession(): SessionValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession() used outside <SessionProvider>");
  return v;
}
