"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import {
  Activity, BrainCircuit, Building2, ChevronDown, FlaskConical, Globe, KeyRound, LogOut, Menu, Monitor, Moon, Network,
  ScrollText, Share2, Sun, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Logo } from "@/components/brand";
import { ChangePasswordDialog } from "@/components/password-dialog";
import { Badge, Button } from "@/components/ui";
import { ROLE_LABEL, useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { LOCALES, useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: typeof Activity; perm: string | string[] };

export function AppShell({ children }: { children: React.ReactNode }) {
  const { m } = useI18n();
  const { user, can } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [pathname]);

  const sections: { title: string; items: NavItem[] }[] = [
    {
      title: m.nav.sectionClinical,
      items: [
        { href: "/risk", label: m.nav.risk, icon: Activity, perm: "predict" },
        { href: "/sharing", label: m.nav.sharing, icon: Share2, perm: ["share:view", "share:decide"] },
      ],
    },
    {
      title: m.nav.sectionResearch,
      items: [
        { href: "/federated", label: m.nav.federated, icon: Network, perm: "fl:view" },
        { href: "/results", label: m.nav.results, icon: FlaskConical, perm: "results:view" },
        { href: "/models", label: m.nav.models, icon: BrainCircuit, perm: "model:view" },
      ],
    },
    {
      title: m.nav.sectionGovernance,
      items: [
        { href: "/admin", label: m.nav.admin, icon: Building2, perm: "user:manage" },
        { href: "/audit", label: m.nav.audit, icon: ScrollText, perm: "audit:view" },
      ],
    },
  ];
  const allowed = (p: NavItem["perm"]) => (Array.isArray(p) ? p.some(can) : can(p));

  const nav = (
    <nav aria-label="Main" className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 py-4">
      {sections.map((s) => {
        const items = s.items.filter((i) => allowed(i.perm));
        if (!items.length) return null;
        return (
          <div key={s.title}>
            <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-subtle">{s.title}</div>
            <ul className="space-y-0.5">
              {items.map((i) => {
                const active = pathname.startsWith(i.href);
                return (
                  <li key={i.href}>
                    <Link
                      href={i.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "group flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] font-medium transition-colors",
                        active ? "bg-primary-soft text-primary" : "text-muted hover:bg-surface-2 hover:text-fg",
                      )}
                    >
                      <i.icon className={cn("size-[18px]", active ? "text-primary" : "text-subtle group-hover:text-fg")} aria-hidden />
                      {i.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );

  return (
    <div className="flex min-h-dvh">
      {/* sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-border bg-surface lg:flex">
        <Brand />
        {nav}
        <SidebarFooter />
      </aside>
      {/* mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} aria-hidden />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col border-r border-border bg-surface">
            <div className="flex items-center justify-between pr-3">
              <Brand />
              <Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="Close menu">
                <X />
              </Button>
            </div>
            {nav}
            <SidebarFooter />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-surface/80 px-4 backdrop-blur-md md:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu />
          </Button>
          <div className="flex min-w-0 items-center gap-2">
            {user?.hospital_name ? (
              <Badge tone="primary" className="max-w-[60vw] truncate">
                <Building2 /> {user.hospital_name}
              </Badge>
            ) : (
              <Badge tone="accent">
                <Globe /> All hospitals
              </Badge>
            )}
          </div>
          <div className="ml-auto flex items-center gap-1">
            <LanguageMenu />
            <ThemeMenu />
            <UserMenu />
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-7 md:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex h-16 items-center gap-2.5 px-5">
      <Logo className="size-8" />
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight">FedCardio</div>
        <div className="text-[11px] text-muted">Federated · Private · Explainable</div>
      </div>
    </Link>
  );
}

function SidebarFooter() {
  const { can } = useAuth();
  const nodes = useApi<{ status: string }[]>(can("fl:view") ? "/fl/nodes" : null);
  const online = nodes.data?.filter((n) => n.status === "online").length;
  return (
    <div className="m-3 rounded-xl border border-border bg-surface-2 p-3">
      <div className="flex items-center gap-2 text-xs font-semibold">
        <span className="relative flex size-2">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
          <span className="relative inline-flex size-2 rounded-full bg-success" />
        </span>
        Federation online
      </div>
      <p className="mt-1 text-[11.5px] leading-relaxed text-muted">
        {online !== undefined && `${online} hospital node${online === 1 ? "" : "s"} · `}mTLS · CKKS-ready
      </p>
    </div>
  );
}

function ThemeMenu() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const Icon = !mounted ? Monitor : theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <Button variant="ghost" size="icon" aria-label="Change theme">
          <Icon />
        </Button>
      </Dropdown.Trigger>
      <Menu_>
        {[
          ["light", "Light", Sun],
          ["dark", "Dark", Moon],
          ["system", "System", Monitor],
        ].map(([v, l, I]) => {
          const Ic = I as typeof Sun;
          return (
            <Item key={v as string} onSelect={() => setTheme(v as string)} active={theme === v}>
              <Ic className="size-4" /> {l as string}
            </Item>
          );
        })}
      </Menu_>
    </Dropdown.Root>
  );
}

function LanguageMenu() {
  const { locale, setLocale } = useI18n();
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <Button variant="ghost" size="icon" aria-label="Change language">
          <Globe />
        </Button>
      </Dropdown.Trigger>
      <Menu_>
        {LOCALES.map((l) => (
          <Item key={l.code} disabled={!l.ready} active={locale === l.code} onSelect={() => setLocale(l.code)}>
            {l.label}
            {!l.ready && <span className="ml-auto text-[10px] text-subtle">soon</span>}
          </Item>
        ))}
      </Menu_>
    </Dropdown.Root>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const { m } = useI18n();
  const [pw, setPw] = useState(false);
  if (!user) return null;
  const initials = user.full_name
    .replace(/^Dr\.\s*/, "")
    .split(" ")
    .map((s) => s[0])
    .slice(0, 2)
    .join("");
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <button className="ml-1 flex items-center gap-2 rounded-lg py-1 pl-1 pr-2 transition-colors hover:bg-surface-2" aria-label="Account menu">
          <span className="grid size-8 place-items-center rounded-full bg-gradient-to-br from-primary to-accent text-xs font-semibold text-white">
            {initials}
          </span>
          <span className="hidden text-left leading-tight md:block">
            <span className="block text-[13px] font-medium">{user.full_name}</span>
            <span className="block text-[11px] text-muted">{ROLE_LABEL[user.role]}</span>
          </span>
          <ChevronDown className="hidden size-4 text-subtle md:block" />
        </button>
      </Dropdown.Trigger>
      <Menu_>
        <div className="px-2.5 py-2">
          <div className="text-[13px] font-medium">{user.email}</div>
          <div className="text-[11.5px] text-muted">
            {ROLE_LABEL[user.role]} · MFA {user.mfa_enabled ? "on" : "off"}
          </div>
        </div>
        <Dropdown.Separator className="my-1 h-px bg-border" />
        <Item onSelect={() => setPw(true)}>
          <KeyRound className="size-4" /> Change password
        </Item>
        <Item onSelect={logout}>
          <LogOut className="size-4" /> {m.common.signOut}
        </Item>
      </Menu_>
      <ChangePasswordDialog open={pw || user.must_change_password} onOpenChange={setPw} forced={user.must_change_password} />
    </Dropdown.Root>
  );
}

function Menu_({ children }: { children: React.ReactNode }) {
  return (
    <Dropdown.Portal>
      <Dropdown.Content
        align="end"
        sideOffset={8}
        className="z-50 min-w-48 rounded-xl border border-border bg-surface p-1 shadow-card"
      >
        {children}
      </Dropdown.Content>
    </Dropdown.Portal>
  );
}

function Item({ children, onSelect, active, disabled }: {
  children: React.ReactNode;
  onSelect?: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <Dropdown.Item
      disabled={disabled}
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] outline-none data-[disabled]:cursor-not-allowed " +
          "data-[disabled]:opacity-50 data-[highlighted]:bg-surface-2",
        active && "text-primary",
      )}
    >
      {children}
    </Dropdown.Item>
  );
}
