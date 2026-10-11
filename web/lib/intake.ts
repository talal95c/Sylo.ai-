import { engineUrl } from "./engine";

export interface IntakeField {
  value: string | null;
}

export interface IntakeResponse {
  intake: {
    fields: Record<string, IntakeField>;
    senderDomain?: IntakeField;
  };
  matchedOrder: string | null;
  decision: {
    risk: {
      score: number;
      tier: string;
    };
  } | null;
}

export type QuoteOrder = "legit" | "diverted";

export function orderForMatchedPayment(paymentId: string | null): QuoteOrder | null {
  if (paymentId === "PAY-2026-0001") return "legit";
  if (paymentId === "PAY-2026-0002") return "diverted";
  return null;
}

export function accountDiffersFromVerified(
  documentAccount: string | null,
  verifiedAccount: string | null,
): boolean {
  const digits = (value: string | null) => value?.replace(/\D/g, "").slice(-4) ?? "";
  const documentDigits = digits(documentAccount);
  const verifiedDigits = digits(verifiedAccount);
  return Boolean(documentDigits && verifiedDigits && documentDigits !== verifiedDigits);
}

function responseDetail(payload: unknown): string | undefined {
  if (typeof payload !== "object" || payload === null || !("detail" in payload)) {
    return undefined;
  }
  const detail = payload.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const first = detail[0];
    if (
      typeof first === "object" &&
      first !== null &&
      "msg" in first &&
      typeof first.msg === "string" &&
      first.msg.trim()
    ) {
      return first.msg;
    }
  }
  return undefined;
}

export async function submitIntake(text: string): Promise<IntakeResponse> {
  let response: Response;
  try {
    response = await fetch(`${engineUrl.replace(/\/$/, "")}/v1/intake`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error("Engine unreachable: check the connection or switch to Replay");
    }
    throw error;
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      detail = responseDetail(await response.json());
    } catch {
      detail = undefined;
    }
    throw new Error(
      detail ? `Engine refused: ${detail}` : `Engine refused (${response.status})`,
    );
  }
  return (await response.json()) as IntakeResponse;
}
