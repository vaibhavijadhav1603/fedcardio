"use client";

import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import { AuthProvider } from "@/lib/auth";
import { I18nProvider } from "@/lib/i18n";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <I18nProvider>
        <AuthProvider>
          {children}
          <Toaster
            position="bottom-right"
            closeButton
            toastOptions={{
              classNames: {
                toast: "!bg-surface !text-fg !border-border !rounded-xl !shadow-card",
                description: "!text-muted",
              },
            }}
          />
        </AuthProvider>
      </I18nProvider>
    </ThemeProvider>
  );
}
