import type { PaymentStatus, ViewState } from "./store";

export interface PaymentStatusView {
  label: string;
  color: string;
  busy?: boolean;
}

const STATUS: Record<PaymentStatus, PaymentStatusView> = {
  idle: { label: "Ready", color: "rgba(0,0,0,.38)" },
  deciding: { label: "Decision in progress", color: "var(--accent)", busy: true },
  in_transit: { label: "In transit", color: "var(--accent)", busy: true },
  held: { label: "Held in escrow", color: "var(--medium)" },
  awaiting_supplier: { label: "Awaiting supplier", color: "var(--medium)", busy: true },
  frozen: { label: "Frozen by the guardian", color: "var(--danger)" },
  stopped: { label: "Stopped", color: "var(--danger)" },
  credited: { label: "Supplier credited", color: "var(--low)" },
};

export function paymentStatusView(state: ViewState): PaymentStatusView {
  if (state.attack.reverted) {
    return { label: "Attack reverted", color: "var(--low)" };
  }

  const status = state.payment?.status ?? "idle";
  const meta = STATUS[status];
  return status === "stopped" && state.refunded
    ? { ...meta, label: "Stopped and refunded" }
    : meta;
}
