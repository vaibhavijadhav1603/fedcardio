"use client";

import * as DialogP from "@radix-ui/react-dialog";
import * as ProgressP from "@radix-ui/react-progress";
import * as SliderP from "@radix-ui/react-slider";
import { Slot } from "@radix-ui/react-slot";
import * as SwitchP from "@radix-ui/react-switch";
import * as TabsP from "@radix-ui/react-tabs";
import * as TooltipP from "@radix-ui/react-tooltip";
import { cva, type VariantProps } from "class-variance-authority";
import { AlertTriangle, Inbox, Loader2, RotateCw, X } from "lucide-react";
import { forwardRef } from "react";
import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------- Button */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-all " +
    "disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 " +
    "focus-visible:outline-ring active:scale-[0.98] [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-fg shadow-sm hover:bg-primary-hover",
        secondary: "bg-surface border border-border text-fg hover:bg-surface-2 hover:border-border-strong",
        ghost: "text-muted hover:text-fg hover:bg-surface-2",
        danger: "bg-danger text-white hover:opacity-90",
        soft: "bg-primary-soft text-primary hover:brightness-95",
        link: "text-primary underline-offset-4 hover:underline px-0 h-auto",
      },
      size: { sm: "h-8 px-3 text-[13px]", md: "h-10 px-4", lg: "h-11 px-5 text-[15px]", icon: "size-9" },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, loading, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} disabled={disabled || loading} {...props}>
        {asChild ? (
          children
        ) : (
          <>
            {loading && <Loader2 className="animate-spin" aria-hidden />}
            {children}
          </>
        )}
      </Comp>
    );
  },
);
Button.displayName = "Button";

/* ---------------------------------------------------------------- Card */
export function Card({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-2xl border border-border bg-surface shadow-card", className)} {...p} />;
}
export function CardHeader({
  title,
  description,
  action,
  icon,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 px-5 pt-5", className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && (
          <div className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary [&_svg]:size-[18px]">
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold tracking-tight text-fg">{title}</h2>
          {description && <p className="mt-0.5 text-[13px] leading-relaxed text-muted">{description}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}
export function CardBody({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5", className)} {...p} />;
}

/* ---------------------------------------------------------------- Badge */
const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium ring-1 ring-inset whitespace-nowrap [&_svg]:size-3",
  {
    variants: {
      tone: {
        neutral: "bg-surface-2 text-muted ring-border",
        primary: "bg-primary-soft text-primary ring-primary/20",
        accent: "bg-accent-soft text-accent ring-accent/20",
        success: "bg-success-soft text-success ring-success/20",
        warning: "bg-warning-soft text-warning ring-warning/25",
        danger: "bg-danger-soft text-danger ring-danger/20",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);
export function Badge({
  tone,
  className,
  ...p
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...p} />;
}

/* ---------------------------------------------------------------- Form controls */
export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...p }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-fg placeholder:text-subtle " +
          "transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:outline-2 " +
          "focus-visible:outline-offset-0 focus-visible:outline-ring/40 aria-[invalid=true]:border-danger",
        className,
      )}
      {...p}
    />
  ),
);
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...p }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "min-h-20 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-subtle " +
          "hover:border-border-strong focus-visible:border-ring focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-ring/40",
        className,
      )}
      {...p}
    />
  ),
);
Textarea.displayName = "Textarea";

export const NativeSelect = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...p }, ref) => (
    <select
      ref={ref}
      className={cn(
        "h-10 w-full appearance-none rounded-lg border border-border bg-surface bg-[length:16px] bg-[right_10px_center] bg-no-repeat " +
          "pl-3 pr-9 text-sm text-fg hover:border-border-strong focus-visible:border-ring focus-visible:outline-2 " +
          "focus-visible:outline-offset-0 focus-visible:outline-ring/40",
        className,
      )}
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%238a97ab' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
      }}
      {...p}
    >
      {children}
    </select>
  ),
);
NativeSelect.displayName = "NativeSelect";

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
  className,
}: {
  label: React.ReactNode;
  htmlFor: string;
  hint?: React.ReactNode;
  error?: string | null;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-fg">
        {label}
      </label>
      {children}
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

export function Switch({ id, checked, onCheckedChange, label, description, disabled }: {
  id: string;
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4", disabled && "opacity-50")}>
      <label htmlFor={id} className="cursor-pointer">
        <span className="block text-sm font-medium text-fg">{label}</span>
        {description && <span className="block text-xs text-muted">{description}</span>}
      </label>
      <SwitchP.Root
        id={id}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
        className="relative mt-0.5 h-6 w-11 shrink-0 rounded-full bg-surface-3 transition-colors data-[state=checked]:bg-primary"
      >
        <SwitchP.Thumb className="block size-5 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[22px]" />
      </SwitchP.Root>
    </div>
  );
}

export function Slider({ value, onValueChange, min, max, step, label, id }: {
  value: number;
  onValueChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  label: string;
  id?: string;
}) {
  return (
    <SliderP.Root
      id={id}
      value={[value]}
      min={min}
      max={max}
      step={step}
      onValueChange={(v) => onValueChange(v[0])}
      className="relative flex h-5 w-full touch-none select-none items-center"
      aria-label={label}
    >
      <SliderP.Track className="relative h-1.5 grow overflow-hidden rounded-full bg-surface-3">
        <SliderP.Range className="absolute h-full bg-primary" />
      </SliderP.Track>
      <SliderP.Thumb
        aria-label={label}
        className="block size-[18px] rounded-full border-2 border-primary bg-surface shadow transition-transform hover:scale-110"
      />
    </SliderP.Root>
  );
}

export function Progress({ value, className, tone = "primary", label }: {
  value: number;
  className?: string;
  tone?: "primary" | "warning" | "danger" | "success";
  label?: string;
}) {
  const color = { primary: "bg-primary", warning: "bg-warning", danger: "bg-danger", success: "bg-success" }[tone];
  return (
    <ProgressP.Root
      value={value}
      aria-label={label}
      className={cn("relative h-2 w-full overflow-hidden rounded-full bg-surface-3", className)}
    >
      <ProgressP.Indicator
        className={cn("h-full rounded-full transition-[width] duration-500 ease-out", color)}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </ProgressP.Root>
  );
}

/* ---------------------------------------------------------------- Tabs */
export const Tabs = TabsP.Root;
export function TabsList({ className, ...p }: React.ComponentProps<typeof TabsP.List>) {
  return (
    <TabsP.List
      className={cn("inline-flex h-10 items-center gap-1 rounded-xl border border-border bg-surface-2 p-1", className)}
      {...p}
    />
  );
}
export function TabsTrigger({ className, ...p }: React.ComponentProps<typeof TabsP.Trigger>) {
  return (
    <TabsP.Trigger
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-muted transition-all " +
          "hover:text-fg data-[state=active]:bg-surface data-[state=active]:text-fg data-[state=active]:shadow-sm [&_svg]:size-3.5",
        className,
      )}
      {...p}
    />
  );
}
export const TabsContent = ({ className, ...p }: React.ComponentProps<typeof TabsP.Content>) => (
  <TabsP.Content className={cn("mt-5 focus-visible:outline-none", className)} {...p} />
);

/* ---------------------------------------------------------------- Dialog */
export function Dialog({ open, onOpenChange, title, description, children, footer, wide, dismissible = true }: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
  dismissible?: boolean; // false: no close button (e.g. a required step)
}) {
  return (
    <DialogP.Root open={open} onOpenChange={onOpenChange}>
      <DialogP.Portal>
        <DialogP.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px] data-[state=open]:animate-in" />
        <DialogP.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto " +
              "rounded-2xl border border-border bg-surface p-6 shadow-2xl",
            wide ? "max-w-3xl" : "max-w-lg",
          )}
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <DialogP.Title className="text-lg font-semibold tracking-tight">{title}</DialogP.Title>
              {description ? (
                <DialogP.Description className="mt-1 text-sm text-muted">{description}</DialogP.Description>
              ) : (
                <DialogP.Description className="sr-only">{String(title)}</DialogP.Description>
              )}
            </div>
            {dismissible && (
              <DialogP.Close asChild>
                <Button variant="ghost" size="icon" aria-label="Close dialog">
                  <X />
                </Button>
              </DialogP.Close>
            )}
          </div>
          <div className="mt-5">{children}</div>
          {footer && <div className="mt-6 flex flex-wrap justify-end gap-2">{footer}</div>}
        </DialogP.Content>
      </DialogP.Portal>
    </DialogP.Root>
  );
}

/* ---------------------------------------------------------------- Tooltip */
export function Tip({ content, children }: { content: React.ReactNode; children: React.ReactNode }) {
  return (
    <TooltipP.Provider delayDuration={200}>
      <TooltipP.Root>
        <TooltipP.Trigger asChild>{children}</TooltipP.Trigger>
        <TooltipP.Portal>
          <TooltipP.Content
            sideOffset={6}
            className="z-50 max-w-xs rounded-lg bg-fg px-2.5 py-1.5 text-xs leading-relaxed text-bg shadow-lg"
          >
            {content}
            <TooltipP.Arrow className="fill-fg" />
          </TooltipP.Content>
        </TooltipP.Portal>
      </TooltipP.Root>
    </TooltipP.Provider>
  );
}

/* ---------------------------------------------------------------- States */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-lg bg-surface-3", className)} />;
}

export function LoadingRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ icon, title, description, action }: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 py-12 text-center">
      <div className="grid size-12 place-items-center rounded-2xl bg-surface-2 text-subtle [&_svg]:size-6">
        {icon ?? <Inbox />}
      </div>
      <h3 className="mt-4 text-sm font-semibold">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-[13px] text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="flex flex-col items-center rounded-xl border border-danger/20 bg-danger-soft px-6 py-10 text-center">
      <AlertTriangle className="size-6 text-danger" aria-hidden />
      <h3 className="mt-3 text-sm font-semibold text-fg">Couldn’t load this</h3>
      <p className="mt-1 max-w-md text-[13px] text-muted">{msg}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-4" onClick={onRetry}>
          <RotateCw /> Try again
        </Button>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- Page header & stat */
export function PageHeader({ title, description, actions, eyebrow }: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: React.ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div>
        {eyebrow && <div className="mb-2">{eyebrow}</div>}
        <h1 className="text-[26px] font-semibold tracking-tight text-fg">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-[14px] leading-relaxed text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, icon, tone = "primary" }: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: "primary" | "accent" | "success" | "warning" | "danger";
}) {
  const toneCls = {
    primary: "bg-primary-soft text-primary",
    accent: "bg-accent-soft text-accent",
    success: "bg-success-soft text-success",
    warning: "bg-warning-soft text-warning",
    danger: "bg-danger-soft text-danger",
  }[tone];
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-[12.5px] font-medium text-muted">{label}</span>
        {icon && <span className={cn("grid size-8 place-items-center rounded-lg [&_svg]:size-4", toneCls)}>{icon}</span>}
      </div>
      <div className="tabular mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </Card>
  );
}

/* ---------------------------------------------------------------- Table */
export function Table({ className, ...p }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="scrollbar-thin overflow-x-auto">
      <table className={cn("w-full border-separate border-spacing-0 text-sm", className)} {...p} />
    </div>
  );
}
export const Th = ({ className, ...p }: React.ThHTMLAttributes<HTMLTableCellElement>) => (
  <th
    scope="col"
    className={cn(
      "sticky top-0 border-b border-border bg-surface-2 px-4 py-2.5 text-left text-[11.5px] font-semibold uppercase tracking-wide text-muted first:rounded-tl-lg last:rounded-tr-lg",
      className,
    )}
    {...p}
  />
);
export const Td = ({ className, ...p }: React.TdHTMLAttributes<HTMLTableCellElement>) => (
  <td className={cn("border-b border-border px-4 py-3 align-middle text-fg", className)} {...p} />
);
