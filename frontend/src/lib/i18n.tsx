"use client";

import { createContext, useContext, useState } from "react";
import en, { type Messages } from "@/messages/en";

export const LOCALES = [
  { code: "en", label: "English", ready: true },
  { code: "hi", label: "हिन्दी (Hindi)", ready: false },
  { code: "kn", label: "ಕನ್ನಡ (Kannada)", ready: false },
] as const;

const catalogs: Record<string, Messages> = { en };

const Ctx = createContext<{ m: Messages; locale: string; setLocale: (l: string) => void }>({
  m: en,
  locale: "en",
  setLocale: () => {},
});

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocale] = useState("en");
  return <Ctx.Provider value={{ m: catalogs[locale] ?? en, locale, setLocale }}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);
